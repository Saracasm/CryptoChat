"""Sandboxed execution of small pandas/plotly code snippets, for the "Make
your own graph" feature. Two independent layers of defense:

1. AST validation (validate_code): a whitelist of allowed syntax nodes,
   plus explicit blocking of dunder access (the classic
   `().__class__.__bases__[0].__subclasses__()` sandbox-escape trick) and a
   handful of dangerous method names (show/write_image/open/...). No
   `import` statement is allowed at all -- pandas and plotly are the only
   two libraries ever placed in the execution namespace, so there is
   nothing to import that isn't already there.
2. Process isolation (run_sandboxed): even code that passed AST validation
   runs in a throwaway subprocess with a hard wall-clock timeout and a
   polled memory ceiling, never in the FastAPI process itself. If it hangs,
   leaks memory, or crashes, only the subprocess dies.

This is deliberately not a claim that arbitrary Python is "100% safe" --
sandboxing a full general-purpose language is a famously hard problem -- but
combined, these two layers cover everything the spec calls for: no imports,
no filesystem, no network, no subprocesses, no DB access, bounded time and
memory.
"""

import ast
import asyncio
import json
import multiprocessing
import time

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio

try:
    import psutil
except ImportError:  # pragma: no cover - psutil is a declared dependency
    psutil = None

# On Windows, spawning a subprocess from an asyncio event loop that has
# already done async network I/O (e.g. the OpenRouter call in
# generate_chart_code) is measurably slower than a cold spawn -- consistently
# ~9s in testing here, vs ~2s standalone. That's a ProactorEventLoop +
# multiprocessing-spawn interaction, not a hang, so the default timeout
# needs headroom above it rather than being tuned to the cold-spawn case.
DEFAULT_TIMEOUT_SECONDS = 15
DEFAULT_MEMORY_LIMIT_MB = 300
_POLL_INTERVAL_SECONDS = 0.05

# Whitelist, not blacklist: any AST node type not in this set is rejected.
# This covers straight-line code, simple `for`/`if` control flow, and
# comprehensions -- everything a pandas/plotly one-to-few-liner needs.
# Notably absent: Import, ImportFrom, FunctionDef, ClassDef, Try, With,
# Global, Nonlocal, While, Delete, Raise, Assert, Yield, Await.
ALLOWED_NODE_TYPES = (
    ast.Module,
    ast.Expr,
    ast.Assign,
    ast.AugAssign,
    ast.AnnAssign,
    ast.Name,
    ast.Load,
    ast.Store,
    ast.Attribute,
    ast.Subscript,
    ast.Slice,
    ast.Call,
    ast.keyword,
    ast.Constant,
    ast.List,
    ast.Tuple,
    ast.Dict,
    ast.Set,
    ast.BinOp,
    ast.UnaryOp,
    ast.BoolOp,
    ast.Compare,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.USub,
    ast.UAdd,
    ast.Not,
    ast.And,
    ast.Or,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.Is,
    ast.IsNot,
    ast.In,
    ast.NotIn,
    ast.Invert,
    ast.BitAnd,
    ast.BitOr,
    ast.BitXor,
    ast.LShift,
    ast.RShift,
    ast.For,
    ast.If,
    ast.IfExp,
    ast.ListComp,
    ast.DictComp,
    ast.SetComp,
    ast.GeneratorExp,
    ast.comprehension,
    ast.Lambda,
    ast.arguments,
    ast.arg,
    ast.JoinedStr,
    ast.FormattedValue,
    ast.Starred,
)

# Rejected at AST time even though the restricted builtins below would
# already make them fail at runtime -- this gives a clear, immediate error
# instead of a confusing NameError, and closes the door before execution
# ever starts.
BLOCKED_NAMES = {
    "eval", "exec", "compile", "open", "input", "__import__", "getattr",
    "setattr", "delattr", "globals", "locals", "vars", "help", "breakpoint",
    "memoryview", "classmethod", "staticmethod", "super", "type",
}

# Attribute access that's syntactically harmless but would open a browser
# tab, spawn a subprocess (kaleido, for image export), or touch disk/network
# -- blocked no matter which object it's called on.
BLOCKED_ATTRS = {
    "show", "write_image", "write_html", "write_json", "to_html",
    "open", "read", "write", "system", "popen", "spawn", "fork",
    "connect", "urlopen", "request", "get", "post",
}

# Everything the sandboxed code is allowed to call by name. Deliberately
# small -- enough for pandas/plotly data wrangling, nothing that touches
# the filesystem, network, or process.
_SAFE_BUILTINS = {
    "len": len, "range": range, "enumerate": enumerate, "min": min,
    "max": max, "sum": sum, "sorted": sorted, "list": list, "dict": dict,
    "set": set, "tuple": tuple, "str": str, "int": int, "float": float,
    "bool": bool, "abs": abs, "round": round, "zip": zip, "map": map,
    "filter": filter, "reversed": reversed, "any": any, "all": all,
    "isinstance": isinstance, "True": True, "False": False, "None": None,
}


class SandboxError(ValueError):
    """Code failed validation or execution in the sandbox."""


def validate_code(code: str) -> ast.Module:
    """Parse and whitelist-check the code. Raises SandboxError on any
    disallowed construct. Returns the parsed tree (unused by callers today,
    but useful for tests / future static checks)."""
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as exc:
        raise SandboxError(f"Invalid Python syntax: {exc}") from exc

    for node in ast.walk(tree):
        if not isinstance(node, ALLOWED_NODE_TYPES):
            raise SandboxError(
                f"'{type(node).__name__}' is not allowed in sandboxed code "
                "(no imports, function/class definitions, while-loops, or "
                "exception handling)."
            )
        if isinstance(node, ast.Name) and (
            node.id in BLOCKED_NAMES or node.id.startswith("__")
        ):
            raise SandboxError(f"'{node.id}' is not allowed.")
        if isinstance(node, ast.Attribute) and (
            node.attr.startswith("__") or node.attr in BLOCKED_ATTRS
        ):
            raise SandboxError(f"'.{node.attr}' is not allowed.")

    return tree


def _worker(code: str, dataframes: dict[str, list[dict]], result_queue) -> None:
    """Runs inside the isolated subprocess. Never has access to anything
    beyond `_SAFE_BUILTINS`, `pd`, `px`, `go`, and the given dataframes --
    in particular, no `__builtins__` module, no `os`/`sys`/`subprocess`.
    """
    try:
        exec_globals = {"__builtins__": _SAFE_BUILTINS, "pd": pd, "px": px, "go": go}
        for name, records in dataframes.items():
            exec_globals[name] = pd.DataFrame(records)

        exec(compile(code, "<sandbox>", "exec"), exec_globals)

        fig = exec_globals.get("fig")
        if fig is None:
            result_queue.put({"error": "Code must assign the chart to a variable named `fig`."})
            return
        if isinstance(fig, dict):
            fig = go.Figure(fig)
        if not hasattr(fig, "to_plotly_json"):
            result_queue.put({"error": "`fig` must be a Plotly figure (e.g. from px.pie(...))."})
            return

        chart_json = json.loads(pio.to_json(fig))
        result_queue.put({"chart": chart_json})
    except Exception as exc:  # noqa: BLE001 - deliberately broad: any failure
        # inside untrusted code becomes a clean error message, not a crash.
        result_queue.put({"error": f"{type(exc).__name__}: {exc}"})


def run_sandboxed(
    code: str,
    dataframes: dict[str, list[dict]],
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    memory_limit_mb: float = DEFAULT_MEMORY_LIMIT_MB,
) -> dict:
    """Validate then execute `code` in an isolated subprocess, enforcing a
    wall-clock timeout and a polled memory ceiling. Blocking -- call via
    run_sandboxed_async from async code.
    """
    validate_code(code)

    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue()
    process = ctx.Process(target=_worker, args=(code, dataframes, queue))
    process.start()

    start = time.monotonic()
    memory_exceeded = False
    try:
        while process.is_alive():
            if time.monotonic() - start > timeout_seconds:
                process.terminate()
                process.join(timeout=2)
                if process.is_alive():
                    process.kill()
                raise SandboxError(
                    f"Code took longer than {timeout_seconds}s to run and was stopped."
                )
            if psutil is not None:
                try:
                    rss_mb = psutil.Process(process.pid).memory_info().rss / (1024 * 1024)
                    if rss_mb > memory_limit_mb:
                        memory_exceeded = True
                        process.terminate()
                        process.join(timeout=2)
                        if process.is_alive():
                            process.kill()
                        break
                except psutil.NoSuchProcess:
                    pass
            time.sleep(_POLL_INTERVAL_SECONDS)
    finally:
        if process.is_alive():
            process.kill()

    if memory_exceeded:
        raise SandboxError(
            f"Code exceeded the {memory_limit_mb:.0f}MB memory limit and was stopped."
        )

    if queue.empty():
        raise SandboxError(
            f"Code did not produce a result (exit code {process.exitcode}); it may have crashed."
        )
    result = queue.get()
    if "error" in result:
        raise SandboxError(result["error"])
    return result["chart"]


async def run_sandboxed_async(
    code: str,
    dataframes: dict[str, list[dict]],
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    memory_limit_mb: float = DEFAULT_MEMORY_LIMIT_MB,
) -> dict:
    """Async wrapper -- run_sandboxed blocks on process.join()/sleep(), so it
    runs off the event loop thread."""
    return await asyncio.to_thread(
        run_sandboxed, code, dataframes, timeout_seconds, memory_limit_mb
    )
