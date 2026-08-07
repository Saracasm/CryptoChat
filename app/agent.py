import logging
from dataclasses import dataclass
from uuid import UUID
import httpx
from pydantic_ai import Agent, RunContext
from pydantic_ai.capabilities import ProcessHistory
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.providers.openrouter import OpenRouterProvider
from app.config import settings
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
        "Always finish your turn by either calling exactly one tool or writing a "
        "plain text reply -- never return an empty response with no tool call and no text."
    ),
    capabilities=[ProcessHistory(_compact_history)],
    toolsets=[crypto_mcp_tools],
)

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

async def _resolve_coin_id(coin: str) -> str:
    """Resolve a coin name/symbol/id (e.g. 'Bitcoin', 'BTC') to its CoinGecko id.

    Tries the literal lowercased value first (it's already an id most of the
    time), then falls back to CoinGecko's search endpoint for free-text names.
    """
    literal = coin.strip().lower()
    url = "https://api.coingecko.com/api/v3/search"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, params={"query": coin})
        data = resp.json()
    coins = data.get("coins", [])
    if not coins:
        return literal

    for c in coins:
        if c["id"] == literal or c["symbol"].lower() == literal or c["name"].lower() == literal:
            return c["id"]
    return coins[0]["id"]

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
    coin_id = await _resolve_coin_id(coin)
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
    coin_id = await _resolve_coin_id(coin)
    removed = await ctx.deps.repo.remove_holding(
        ctx.deps.conversation_id, coin_id, buy_price=buy_price
    )
    if removed:
        return f"Removed your {coin} holding."
    return f"Couldn't find a {coin} holding to remove."

@agent.tool
async def get_portfolio(ctx: RunContext[Deps]) -> dict:
    """Compute the portfolio with market context.
    Returns per-coin: amount held, average buy price, current price,
    24h market change %, cost basis (what was spent), current value,
    and profit/loss -- plus portfolio totals. Use this to explain WHY
    the user is up/down and how much weight their purchases carry.
    """
    print(f"DEBUG: user_id in state = {ctx.deps.user_id}")
    print(f"DEBUG: conversation_id in state = {ctx.deps.conversation_id}")
    holdings = await ctx.deps.repo.get_holdings(ctx.deps.conversation_id)
    if not holdings:
        return {"message": "No holdings recorded yet."}

    positions: dict[str, dict] = {}
    for h in holdings:
        p = positions.setdefault(h.coin, {"amount": 0.0, "cost": 0.0})
        p["amount"] += float(h.amount)
        p["cost"] += float(h.amount) * float(h.buy_price)

    # One CoinGecko call gets price + 24h change + rank for every coin.
    ids = ",".join(positions.keys())
    url = "https://api.coingecko.com/api/v3/coins/markets"
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            url, params={"vs_currency": "usd", "ids": ids}
        )
        market = resp.json()

    # Index market data by coin id for easy lookup.
    market_by_id = {m["id"]: m for m in market}

    report = {}
    total_value = 0.0
    total_cost = 0.0
    for coin, p in positions.items():
        m = market_by_id.get(coin, {})
        price = m.get("current_price", 0) or 0
        change_24h = m.get("price_change_percentage_24h")
        value = p["amount"] * price
        pnl = value - p["cost"]
        avg_cost = p["cost"] / p["amount"] if p["amount"] else 0
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

    # Add allocation % so the model can talk about "weight" per coin.
    for coin in positions:
        v = report[coin]["current_value"]
        report[coin]["portfolio_weight_percent"] = (
            round(v / total_value * 100, 1) if total_value else 0
        )

    report["_total"] = {
        "cost_basis": round(total_cost, 2),
        "current_value": round(total_value, 2),
        "profit_loss": round(total_value - total_cost, 2),
    }
    return report

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

async def get_reply(
    repo: Repository, conversation_id: UUID, history: list[dict], user_id: UUID | None = None
) -> str:
    """Run the agent with prior context + tools, return the reply text."""
    deps = Deps(repo=repo, conversation_id=conversation_id, user_id=user_id)
    latest = history[-1]["content"]
    message_history = _to_model_messages(history)
    result = await agent.run(latest, deps=deps, message_history=message_history)
    return result.output


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

