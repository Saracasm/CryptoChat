import asyncio
import logging
import time
from dataclasses import dataclass
from uuid import UUID
import httpx
from pydantic_ai import Agent, RunContext
from pydantic_ai.capabilities import ProcessHistory
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.providers.openrouter import OpenRouterProvider
from app.config import settings
from app.embeddings import embed_query
from app.visualization import build_portfolio_visualization, resolve_coin_id
from app.repository import Repository

logger = logging.getLogger(__name__)

model = OpenRouterModel(
    settings.openrouter_model,
    provider=OpenRouterProvider(api_key=settings.openrouter_api_key),
)


crypto_mcp_tools = MCPToolset("http://localhost:8001/mcp")


@dataclass
class Deps:
    repo: Repository | None
    conversation_id: UUID | None
    user_id:UUID | None = None    #this is the acting profile's id

from app.database import Base


def get_schema_text() -> str:
    """Introspect the SQLAlchemy schema (Base.metadata) and render it as
    readable text: tables, columns, types, primary keys, and foreign keys.
    Used to ground the SQL subagent in the real, current database schema.
    """
    lines = []
    for table in Base.metadata.sorted_tables:
        lines.append(f"Table: {table.name}")
        for col in table.columns:
            col_desc = f"  - {col.name}: {col.type}"
            if col.primary_key:
                col_desc += " [PK]"
            if col.foreign_keys:
                targets = ", ".join(fk.target_fullname for fk in col.foreign_keys)
                col_desc += f" [FK -> {targets}]"
            lines.append(col_desc)
        lines.append("")
    return "\n".join(lines)


sql_agent = Agent(
    model,
    deps_type=Deps,
    instructions=(
        "Given a task describing what data is needed, write a single correct "
        "PostgreSQL query that accomplishes it. Use only the tables and "
        "columns given to you in the schema -- never invent column or table "
        "names. Reply with ONLY the SQL query, no explanation, no markdown "
        "code fences."
    ),
)

@sql_agent.instructions
def add_schema_context(ctx: RunContext[Deps]) -> str:
    """Dynamic instructions: injects the live DB schema and the current
    conversation_id, so the agent scopes queries correctly."""
    return (
        f"Here is the current database schema:\n\n{get_schema_text()}\n\n"
        f"IMPORTANT: The current conversation_id is '{ctx.deps.conversation_id}'. "
        "Any query touching the holdings table MUST filter by "
        f"conversation_id = '{ctx.deps.conversation_id}'. Never return rows "
        "from other conversations. Only write SELECT queries -- never "
        "INSERT, UPDATE, DELETE, or DDL statements."
    )


chart_code_agent = Agent(
    model,
    deps_type=Deps,
    instructions=(
        "You write a single short Python snippet that builds one Plotly "
        "chart from a pandas DataFrame already available as the variable "
        "`df`. You may only use `pd` (pandas) and `px` (plotly.express) or "
        "`go` (plotly.graph_objects) -- both already imported; never write "
        "an import statement yourself. Only reference the exact columns "
        "you are told exist on `df` -- never invent a column. Assign the "
        "final chart to a variable named `fig`. Do not call `.show()`, "
        "`.write_html()`, or anything that touches a file or the network. "
        "Do not define functions or classes, and do not use try/except or "
        "while loops -- straight-line code (and simple for/if) only. "
        "Reply with ONLY the code, no explanation, no markdown code fences."
    ),
)


async def generate_chart_code(prompt: str, columns: list[str]) -> str:
    """Ask the model for a sandboxed pandas/plotly snippet answering `prompt`
    against a dataframe with the given columns. Returned code still goes
    through app.sandbox.validate_code before ever being executed -- this
    function does not itself guarantee safe output.
    """
    task = f"Available columns on `df`: {', '.join(columns)}.\nUser request: {prompt}"
    result = await chart_code_agent.run(task, deps=Deps(repo=None, conversation_id=None))
    code = result.output.strip()
    if code.startswith("```"):
        code = code.strip("`")
        if code.startswith("python"):
            code = code[len("python"):]
    return code.strip()


CONTEXT_WINDOW = 6

summary_cache: dict[UUID, tuple[str, int]] = {}

summarizer_agent = Agent(
    model,
    deps_type=Deps,
    instructions=(
        "You summarize conversations. Never call any tools. "
        "Just read the conversation and produce a summary."
    ),
)

async def _summarize_messages(
    messages: list[ModelMessage], previous_summary: str | None = None) -> str:
    """Call the model to compress a chunk of turns into a short summary.

    If previous_summary is given, the model extends it to also cover the
    new chunk, so only the newly-aged-out messages need to be read instead
    of re-summarizing the whole growing "old" portion from scratch.
    """
    lines = []
    for m in messages:
        for part in m.parts:
            if isinstance(part, (TextPart, UserPromptPart)) and isinstance(part.content, str):
                role = "user" if isinstance(part, UserPromptPart) else "assistant"
                lines.append(f"{role}: {part.content}")
    convo = "\n".join(lines)

    if previous_summary:
        prompt = (
            "Here is a running summary of a crypto portfolio conversation so far:\n"
            f"{previous_summary}\n\n"
            "Extend it to also cover these new turns. Preserve any concrete facts "
            "the assistant will still need (coins mentioned, amounts, prices, "
            "corrections/removals made). Reply with the updated summary only, "
            "a few sentences.\n\n" + convo
        )
    else:
        prompt = (
            "Summarize this portion of a crypto portfolio conversation in a few "
            "sentences. Preserve any concrete facts the assistant will still need "
            "(coins mentioned, amounts, prices, corrections/removals made). "
            "Reply with the summary only.\n\n" + convo
        )
    # result = await agent.run(prompt, deps=Deps(repo=None, conversation_id=None))
    result = await summarizer_agent.run(prompt, deps=Deps(repo=None, conversation_id=None))
    return result.output.strip()

async def _compact_history(
    ctx: RunContext[Deps], messages: list[ModelMessage]) -> list[ModelMessage]:
    """History processor: once history grows past the window, fold the
    older chunk into a running summary and keep only recent turns verbatim.

    The summary is built incrementally, cached per conversation in-process:
    each call only summarizes messages that newly aged out of the window
    since the last call, extending the cached summary, rather than
    re-summarizing the whole "old" chunk from scratch every turn.
    """
    if len(messages) <= CONTEXT_WINDOW:
        logger.info(
            "compact_history: skipped (%d messages <= window %d)",
            len(messages), CONTEXT_WINDOW,
        )
        return messages

    old, recent = messages[:-CONTEXT_WINDOW], messages[-CONTEXT_WINDOW:]

    conversation_id = ctx.deps.conversation_id
    if conversation_id is None:
        # Sub-run (e.g. the summarizer's own agent.run call) -- there's no
        # conversation to key a running summary by.
        logger.info("compact_history: summarizing %d messages (no conversation_id)", len(old))
        summary = await _summarize_messages(old)
    else:
        previous_summary, summarized_count = summary_cache.get(conversation_id, (None, 0))
        new_chunk = old[summarized_count:]
        if new_chunk:
            logger.info(
                "compact_history: conversation %s - extending summary with %d new message(s) "
                "(previously summarized %d)",
                conversation_id, len(new_chunk), summarized_count,
            )
            summary = await _summarize_messages(new_chunk, previous_summary=previous_summary)
            summary_cache[conversation_id] = (summary, len(old))
            logger.info("compact_history: conversation %s - summary updated", conversation_id)
        else:
            logger.info(
                "compact_history: conversation %s - reusing cached summary, no new messages",
                conversation_id,
            )
            summary = previous_summary

    summary_message = ModelRequest(
        parts=[UserPromptPart(content=f"[Summary of earlier conversation]: {summary}")]
    )
    return [summary_message, *recent]

agent = Agent(
    model,
    deps_type=Deps,
    instructions=(
        "You are a crypto portfolio assistant. "
        "When the user says they bought a coin, call log_holding to record it. "
        "If the user corrects a mistake in a previous purchase (wrong price or "
        "amount), call update_holding to fix the existing entry -- do NOT log a "
        "new one. If they want to remove a purchase, call remove_holding. "
        "When they ask how their portfolio is doing, call get_portfolio. "
        "When they ask for a chart of their own portfolio, call "
        "create_portfolio_chart. It can make allocation, profit/loss, or "
        "cost-vs-current-value charts from their private holdings. "
        "You also have market-intelligence MCP tools. Use get_historical_prices "
        "for price trends, get_market_overview to explain broad market moves, "
        "get_crypto_news for recent headlines, and get_upcoming_events for "
        "project updates. For a risk question, first call get_portfolio, then "
        "call get_portfolio_risk with a list of its per-coin values in the form "
        "{'coin': coin_id, 'current_value': value}. Treat news and project "
        "updates as context, not proof of price causation. "
        "Use CoinGecko coin ids like 'bitcoin', 'ethereum', 'solana'. "
        "When you report the portfolio, INTERPRET the data, do not just list numbers: "
        "explain WHY the user is up or down using each coin's 24h change, "
        "and frame the 'weight on their pocket' -- how much they put in (cost basis) "
        "versus what it is worth now, and how today's market move shifted that. "
        "Be clear, concise, and give one practical takeaway. "
        "If the user explicitly asks to see, write, or be given a SQL query, "
        "call write_sql_query and show them the SQL text in your reply. "
        "If they're asking a normal question about their data (e.g. 'what is my "
        "biggest purchase'), call write_sql_query but answer using the result "
        "data only -- do not show the SQL unless asked. "
        "Relevant excerpts from the user's uploaded documents may already appear "
        "in context as '[Relevant excerpts from your uploaded documents]' -- use "
        "them when they help answer the question, and name the source filename "
        "when you rely on one. If you need a different or more specific search "
        "of their documents than what's already provided, call "
        "search_uploaded_documents. Never invent facts that aren't in the "
        "retrieved excerpts or your other tools' output. "
        "Use only the tool calls needed to answer accurately, then finish with a "
        "plain text reply -- never return an empty response with no tool call and no text."
    ),
    capabilities=[ProcessHistory(_compact_history)],
    toolsets=[crypto_mcp_tools],
)

# Each conversation's Repository shares one SQLAlchemy async session, which
# only supports one flush in flight at a time. If the model calls two
# holding-writing tools in the same turn (e.g. "I bought BTC and ETH"),
# pydantic-ai runs them concurrently and they'd race on that session and
# crash with "Session is already flushing". A per-conversation lock
# serializes them instead.
_holding_locks: dict[UUID, asyncio.Lock] = {}


def _get_holding_lock(conversation_id: UUID) -> asyncio.Lock:
    lock = _holding_locks.get(conversation_id)
    if lock is None:
        lock = asyncio.Lock()
        _holding_locks[conversation_id] = lock
    return lock


@agent.tool
async def log_holding(
    ctx: RunContext[Deps], coin: str, amount: float, buy_price: float) -> str:
    """Record a crypto purchase (a holding).

    Args:
        coin: CoinGecko coin id, e.g. 'bitcoin', 'ethereum', 'solana'.
        amount: How many units were bought, e.g. 0.5.
        buy_price: Price paid per unit in USD, e.g. 2400.
    """
    coin_id = coin.lower()
    async with _get_holding_lock(ctx.deps.conversation_id):
        # Guard: don't log the same purchase twice (the model may re-read old messages).
        already = await ctx.deps.repo.holding_exists(
            ctx.deps.conversation_id, coin_id, amount, buy_price
        )
        if already:
            return f"{amount} {coin} at ${buy_price} was already logged; skipping duplicate."

        await ctx.deps.repo.add_holding(
            ctx.deps.conversation_id, coin_id, amount, buy_price
        )
    return f"Logged {amount} {coin} at ${buy_price} each."

@agent.tool
async def update_holding(ctx: RunContext[Deps], coin:str,
    new_buy_price: float | None = None,
    new_amount: float | None = None,
    old_buy_price: float | None = None,) -> str:
    """Correct a previously logged purchase (e.g. the user made a typo).
    Args:
        coin: Coin name, symbol, or CoinGecko id, e.g. 'Bitcoin', 'BTC', 'bitcoin'.
        new_buy_price: The corrected price per unit, if the price was wrong.
        new_amount: The corrected amount, if the amount was wrong.
        old_buy_price: The wrong price to find the holding by (helps pick the
            right lot when there are several).
    """
    coin_id = (await resolve_coin_id(coin))["coin_id"]
    async with _get_holding_lock(ctx.deps.conversation_id):
        updated = await ctx.deps.repo.update_holding(
            ctx.deps.conversation_id,
            coin_id,
            new_amount=new_amount,
            new_buy_price=new_buy_price,
            old_buy_price=old_buy_price,
        )
    if updated:
        return f"Updated your {coin} holding."
    return f"Couldn't find a {coin} holding to update."

@agent.tool
async def remove_holding(
    ctx: RunContext[Deps], coin: str, buy_price: float | None = None)-> str:
    """Remove a previously logged purchase.
    Args:
        coin: Coin name, symbol, or CoinGecko id, e.g. 'Bitcoin', 'BTC', 'bitcoin'.
        buy_price: The price of the specific lot to remove (optional).
    """
    coin_id = (await resolve_coin_id(coin))["coin_id"]
    async with _get_holding_lock(ctx.deps.conversation_id):
        removed = await ctx.deps.repo.remove_holding(
            ctx.deps.conversation_id, coin_id, buy_price=buy_price
        )
    if removed:
        return f"Removed your {coin} holding."
    return f"Couldn't find a {coin} holding to remove."

# CoinGecko's free tier rate-limits aggressively (a handful of calls/minute).
# A short in-memory cache means repeated portfolio/chart requests within the
# window are served without hitting CoinGecko again at all, and if a request
# does go out and gets rate-limited or fails, we fall back to the last good
# response instead of crashing the endpoint.
MARKET_CACHE_TTL_SECONDS = 45
_market_cache: dict[tuple[str, ...], tuple[float, list[dict]]] = {}


async def _fetch_market_data(coin_ids: list[str]) -> list[dict]:
    """Fetch CoinGecko market data (price, 24h change, etc.) for the given
    coin ids. Never raises -- on rate limits, bad responses, or network
    errors it logs a warning and returns the last cached result (or an
    empty list if there's no cache yet), so callers can degrade cleanly
    instead of crashing.
    """
    cache_key = tuple(sorted(coin_ids))
    cached = _market_cache.get(cache_key)
    if cached and time.monotonic() - cached[0] < MARKET_CACHE_TTL_SECONDS:
        return cached[1]

    stale_fallback = cached[1] if cached else []
    url = "https://api.coingecko.com/api/v3/coins/markets"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                url, params={"vs_currency": "usd", "ids": ",".join(cache_key)}
            )
        if resp.status_code == 429:
            logger.warning("CoinGecko rate limit hit; using stale/empty market data")
            return stale_fallback
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            logger.warning("CoinGecko returned an unexpected payload: %r", data)
            return stale_fallback
    except httpx.HTTPError as exc:
        logger.warning("CoinGecko request failed: %s", exc)
        return stale_fallback

    _market_cache[cache_key] = (time.monotonic(), data)
    return data


async def get_portfolio_report(repo: Repository, conversation_id: UUID) -> dict:
    """Compute the current market value and performance of one portfolio."""
    holdings = await repo.get_holdings(conversation_id)
    if not holdings:
        return {"message": "No holdings recorded yet."}

    positions: dict[str, dict] = {}
    for h in holdings:
        p = positions.setdefault(h.coin, {"amount": 0.0, "cost": 0.0})
        p["amount"] += float(h.amount)
        p["cost"] += float(h.amount) * float(h.buy_price)

    # One CoinGecko call gets price + 24h change + rank for every coin.
    market = await _fetch_market_data(list(positions.keys()))
    market_by_id = {m["id"]: m for m in market if isinstance(m, dict) and "id" in m}
    prices_unavailable = not market_by_id

    report = {}
    total_value = 0.0
    total_cost = 0.0
    # Portfolio-wide "today's move": back out yesterday's value per coin from
    # its 24h % change, sum both sides, then diff -- a simple $ change would
    # instead double-count cost basis, so this only uses coins with known
    # current value and a known 24h change.
    value_today_with_change = 0.0
    value_yesterday_with_change = 0.0
    for coin, p in positions.items():
        avg_cost = p["cost"] / p["amount"] if p["amount"] else 0
        m = market_by_id.get(coin)

        if m is None and prices_unavailable:
            # CoinGecko is down/rate-limited entirely -- report what we
            # actually know (cost basis) and mark the rest as unknown
            # rather than showing a fabricated $0 value / -100% loss.
            report[coin] = {
                "amount": round(p["amount"], 8),
                "avg_buy_price": round(avg_cost, 2),
                "current_price": None,
                "change_24h_percent": None,
                "cost_basis": round(p["cost"], 2),
                "current_value": None,
                "profit_loss": None,
            }
            total_cost += p["cost"]
            continue

        m = m or {}
        price = m.get("current_price", 0) or 0
        change_24h = m.get("price_change_percentage_24h")
        value = p["amount"] * price
        pnl = value - p["cost"]
        report[coin] = {
            "amount": round(p["amount"], 8),
            "avg_buy_price": round(avg_cost, 2),
            "current_price": price,
            "change_24h_percent": (
                round(change_24h, 2) if change_24h is not None else None
            ),
            "cost_basis": round(p["cost"], 2),      # what they put in
            "current_value": round(value, 2),        # what it's worth now
            "profit_loss": round(pnl, 2),
        }
        total_value += value
        total_cost += p["cost"]
        if change_24h is not None and (1 + change_24h / 100) != 0:
            value_today_with_change += value
            value_yesterday_with_change += value / (1 + change_24h / 100)

    # Add allocation % so the model can talk about "weight" per coin.
    for coin in positions:
        v = report[coin]["current_value"]
        report[coin]["portfolio_weight_percent"] = (
            round(v / total_value * 100, 1) if total_value and v is not None else None
        )

    if prices_unavailable:
        report["_total"] = {
            "cost_basis": round(total_cost, 2),
            "current_value": None,
            "profit_loss": None,
        }
        report["_meta"] = {
            "prices_unavailable": True,
            "message": (
                "Live prices are temporarily unavailable (market data "
                "provider is rate-limited or unreachable) -- showing "
                "logged cost basis only."
            ),
        }
    else:
        today_move_usd = None
        today_move_percent = None
        if value_yesterday_with_change:
            today_move_usd = round(value_today_with_change - value_yesterday_with_change, 2)
            today_move_percent = round(
                (value_today_with_change - value_yesterday_with_change)
                / value_yesterday_with_change * 100, 2,
            )
        report["_total"] = {
            "cost_basis": round(total_cost, 2),
            "current_value": round(total_value, 2),
            "profit_loss": round(total_value - total_cost, 2),
            "today_move_usd": today_move_usd,
            "today_move_percent": today_move_percent,
        }
    return report


@agent.tool
async def get_portfolio(ctx: RunContext[Deps]) -> dict:
    """Get the current private portfolio with market context and P&L."""
    return await get_portfolio_report(ctx.deps.repo, ctx.deps.conversation_id)


@agent.tool
async def create_portfolio_chart(
    ctx: RunContext[Deps], chart_type: str = "allocation"
) -> dict:
    """Create a private chart from the current conversation's portfolio.

    Args:
        chart_type: One of allocation, profit_loss, or cost_vs_value.
    """
    allowed_chart_types = {"allocation", "profit_loss", "cost_vs_value"}
    if chart_type not in allowed_chart_types:
        return {"error": f"chart_type must be one of: {', '.join(sorted(allowed_chart_types))}"}
    portfolio = await get_portfolio_report(ctx.deps.repo, ctx.deps.conversation_id)
    if "message" in portfolio:
        return portfolio
    try:
        return build_portfolio_visualization(portfolio, chart_type).model_dump()
    except ValueError as exc:
        return {"error": str(exc)}


@agent.tool
async def search_uploaded_documents(
    ctx: RunContext[Deps], query: str, top_k: int = 5
) -> dict:
    """Search the user's own uploaded documents for relevant passages.

    Use this for a targeted look beyond whatever excerpts are already in
    context -- e.g. the user asks about a specific detail in a document they
    uploaded (a whitepaper, a statement, their notes).

    Args:
        query: What to search for, in the document's own terms.
        top_k: Max chunks to return (1-10). Defaults to 5.
    """
    if ctx.deps.user_id is None:
        return {"error": "No active profile to search documents for."}
    top_k = max(1, min(top_k, 10))
    try:
        query_vector = await embed_query(query)
        results = await ctx.deps.repo.search_document_chunks(
            ctx.deps.user_id, query_vector, top_k=top_k
        )
    except Exception as exc:
        logger.warning("search_uploaded_documents failed: %s", exc)
        return {"error": "Document search is temporarily unavailable."}
    if not results:
        return {"message": "No uploaded documents matched this query."}
    return {"results": results}


@agent.tool
async def write_sql_query(ctx: RunContext[Deps], task: str) -> str:
    """Delegate to the SQL specialist to write AND run a query, returning
    both the SQL used and the resulting data.

    Use this when you need to answer something that requires querying the
    database directly beyond what the other tools provide -- e.g. custom
    lookups, aggregations, or questions about the raw data. Also use this
    when the user explicitly asks to see or be given a SQL query.

    Args:
        task: A plain-English description of what data is needed,
            e.g. "find the holding with the largest loss".
    """
    result = await sql_agent.run(task, deps=ctx.deps)
    sql_query = result.output.strip().strip("`")

    try:
        rows = await ctx.deps.repo.execute_raw_sql(sql_query)
    except Exception as e:
        return f"Query used:\n{sql_query}\n\nThe query failed to run: {e}"

    if not rows:
        return f"Query used:\n{sql_query}\n\nResult: the query ran successfully but returned no rows."
    return f"Query used:\n{sql_query}\n\nResult: {rows}"


# Cap on how much retrieved document text gets injected per turn (roughly
# 1500 tokens at ~4 chars/token) so RAG context can't crowd out the rest of
# the conversation window.
DOCUMENT_CONTEXT_CHAR_BUDGET = 6000
DOCUMENT_CONTEXT_TOP_K = 5


async def _build_document_context(
    repo: Repository, user_id: UUID | None, query: str
) -> str | None:
    """Auto-retrieve the top-k most relevant chunks from the user's own
    uploaded documents for this message, token-budgeted. Never raises --
    on any embedding/DB failure this degrades to "no context" rather than
    breaking the chat turn.
    """
    if repo is None or user_id is None or not query.strip():
        return None
    try:
        query_vector = await embed_query(query)
        chunks = await repo.search_document_chunks(
            user_id, query_vector, top_k=DOCUMENT_CONTEXT_TOP_K
        )
    except Exception as exc:
        logger.warning("Auto document retrieval failed: %s", exc)
        return None
    if not chunks:
        return None

    pieces = []
    remaining = DOCUMENT_CONTEXT_CHAR_BUDGET
    for chunk in chunks:
        if remaining <= 0:
            break
        text = chunk["chunk_text"][:remaining]
        remaining -= len(text)
        pieces.append(f"[{chunk['filename']} - chunk {chunk['chunk_index']}]\n{text}")

    return "[Relevant excerpts from your uploaded documents]\n\n" + "\n\n---\n\n".join(pieces)


def _to_model_messages(history: list[dict]) -> list[ModelMessage]:
    """Turn our [{'role','content'}] list into Pydantic AI message objects.
    We skip the last one (that's the new prompt, passed separately).
    """
    messages: list[ModelMessage] = []
    for m in history[:-1]:
        if m["role"] == "user":
            messages.append(ModelRequest(parts=[UserPromptPart(content=m["content"])]))
        elif m["role"] == "assistant":
            messages.append(ModelResponse(parts=[TextPart(content=m["content"])]))
    return messages

# Tool calls whose output feeds risk/performance judgments -- if the model
# used one of these to answer, we append a disclaimer to the reply
# ourselves rather than trusting the model to remember to add it every time.
RISK_SIGALING_TOOLS = {"get_portfolio_risk", "get_portfolio"}
NOT_FINANCIAL_ADVICE_NOTE = (
    "\n\n_Not financial advice: this is an automated summary of your logged "
    "data and public market info, not a recommendation to buy, sell, or hold._"
)


def _used_risk_tool(messages: list[ModelMessage]) -> bool:
    for message in messages:
        for part in getattr(message, "parts", []):
            if isinstance(part, ToolCallPart) and part.tool_name in RISK_SIGALING_TOOLS:
                return True
    return False


async def get_reply(
    repo: Repository, conversation_id: UUID, history: list[dict], user_id: UUID | None = None
) -> str:
    """Run the agent with prior context + tools, return the reply text."""
    deps = Deps(repo=repo, conversation_id=conversation_id, user_id=user_id)
    latest = history[-1]["content"]
    message_history = _to_model_messages(history)

    document_context = await _build_document_context(repo, user_id, latest)
    if document_context:
        message_history.append(
            ModelRequest(parts=[UserPromptPart(content=document_context)])
        )

    result = await agent.run(latest, deps=deps, message_history=message_history)
    reply = result.output
    if _used_risk_tool(result.new_messages()) and "not financial advice" not in reply.lower():
        reply += NOT_FINANCIAL_ADVICE_NOTE
    return reply


async def summarize_title(history: list[dict]) -> str:
    """Summarize the conversation into a short title."""
    convo = "\n".join(f"{m['role']}: {m['content']}" for m in history)
    prompt = (
        "Summarize this conversation into a short title of at most 6 words. "
        "Reply with the title only.\n\n" + convo
    )
    #result = await agent.run(prompt, deps=Deps(repo=None, conversation_id=None))
    result = await summarizer_agent.run(prompt, deps=Deps(repo=None, conversation_id=None))
    return result.output.strip()[:80]

