from dataclasses import dataclass
from uuid import UUID

import httpx
from pydantic_ai import Agent, RunContext
from pydantic_ai.capabilities import ProcessHistory
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.providers.openrouter import OpenRouterProvider

from app.config import settings
from app.repository import Repository

model = OpenRouterModel(
    settings.openrouter_model,
    provider=OpenRouterProvider(api_key=settings.openrouter_api_key),
)

@dataclass
class Deps:
    repo: Repository | None
    conversation_id: UUID | None

CONTEXT_WINDOW = 20

async def _summarize_messages(messages: list[ModelMessage]) -> str:
    """Call the model to compress older turns into a short summary."""
    lines = []
    for m in messages:
        for part in m.parts:
            if isinstance(part, (TextPart, UserPromptPart)) and isinstance(part.content, str):
                role = "user" if isinstance(part, UserPromptPart) else "assistant"
                lines.append(f"{role}: {part.content}")
    convo = "\n".join(lines)

    prompt = (
        "Summarize this portion of a crypto portfolio conversation in a few "
        "sentences. Preserve any concrete facts the assistant will still need "
        "(coins mentioned, amounts, prices, corrections/removals made). "
        "Reply with the summary only.\n\n" + convo
    )
    result = await agent.run(prompt, deps=Deps(repo=None, conversation_id=None))
    return result.output.strip()

async def _compact_history(messages: list[ModelMessage]) -> list[ModelMessage]:
    """History processor: once history grows past the window, fold the
    older chunk into one summary message and keep only recent turns verbatim.
    """
    if len(messages) <= CONTEXT_WINDOW:
        return messages

    old, recent = messages[:-CONTEXT_WINDOW], messages[-CONTEXT_WINDOW:]
    summary = await _summarize_messages(old)

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
        "Be clear, concise, and give one practical takeaway."
    ),
    capabilities=[ProcessHistory(_compact_history)],
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
async def get_prices(ctx: RunContext[Deps], coins: list[str])->dict:
    """Get current USD prices for a list of coins from CoinGecko.
    Args:
        coins: list of CoinGecko coin ids, e.g. ['bitcoin', 'ethereum'].
    """
    ids = ",".join(c.lower() for c in coins)
    url = "https://api.coingecko.com/api/v3/simple/price"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, params={"ids": ids, "vs_currencies": "usd"})
        data = resp.json()
    return {coin: info.get("usd") for coin, info in data.items()}

@agent.tool
async def get_portfolio(ctx: RunContext[Deps]) -> dict:
    """Compute the portfolio with market context.
    Returns per-coin: amount held, average buy price, current price,
    24h market change %, cost basis (what was spent), current value,
    and profit/loss -- plus portfolio totals. Use this to explain WHY
    the user is up/down and how much weight their purchases carry.
    """
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

async def get_reply(repo: Repository, conversation_id: UUID, history: list[dict])->str:
    """Run the agent with prior context + tools, return the reply text."""
    deps = Deps(repo=repo, conversation_id=conversation_id)
    latest = history[-1]["content"]
    message_history = _to_model_messages(history)
    result = await agent.run(latest, deps=deps, message_history=message_history)
    return result.output


# CONTEXT_WINDOW = 20

async def summarize_title(history: list[dict]) -> str:
    """Summarize the conversation into a short title."""
    convo = "\n".join(f"{m['role']}: {m['content']}" for m in history)
    prompt = (
        "Summarize this conversation into a short title of at most 6 words. "
        "Reply with the title only.\n\n" + convo
    )
    result = await agent.run(prompt, deps=Deps(repo=None, conversation_id=None))
    return result.output.strip()[:80]

