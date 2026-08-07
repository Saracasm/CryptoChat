# from uuid import UUID

from datetime import datetime, timezone

import httpx
from mcp.server.fastmcp import FastMCP
from app.visualization import COINGECKO_BASE, get_json, get_market_chart, resolve_coin_id
# from sqlalchemy import select

# from app.database import SessionLocal
# from app.models import Holding

mcp = FastMCP("crypto-tools", host="127.0.0.1", port=8001)

CRYPTOCOMPARE_NEWS_URL = "https://min-api.cryptocompare.com/data/v2/news/"


@mcp.tool()
async def get_trending_coins() -> list[dict]:
    """Get the coins currently trending (most searched) on CoinGecko."""
    data = await get_json(f"{COINGECKO_BASE}/search/trending")

    return [
        {
            "coin_id": item["item"]["id"],
            "name": item["item"]["name"],
            "symbol": item["item"]["symbol"],
            "market_cap_rank": item["item"].get("market_cap_rank"),
        }
        for item in data.get("coins", [])
    ]


@mcp.tool()
async def get_coin_market_data(coin: str) -> dict:
    """Get market cap, 24h change, rank, and volume for a coin.

    Args:
        coin: Coin name, symbol, or CoinGecko id, e.g. 'Bitcoin', 'BTC', 'bitcoin'.
    """
    resolved = await resolve_coin_id(coin)
    coin_id = resolved["coin_id"]

    data = await get_json(
        f"{COINGECKO_BASE}/coins/markets",
        params={"vs_currency": "usd", "ids": coin_id},
    )

    if not data:
        return {"error": f"No market data found for '{coin}'."}

    m = data[0]
    return {
        "coin_id": m["id"],
        "name": m["name"],
        "current_price": m.get("current_price"),
        "market_cap": m.get("market_cap"),
        "market_cap_rank": m.get("market_cap_rank"),
        "total_volume": m.get("total_volume"),
        "change_24h_percent": m.get("price_change_percentage_24h"),
        "high_24h": m.get("high_24h"),
        "low_24h": m.get("low_24h"),
    }


@mcp.tool()
async def get_historical_prices(
    coin: str, days: int = 30, interval: str = "daily"
) -> dict:
    """Get a coin's USD price history for performance analysis and charting.

    Args:
        coin: Coin name, symbol, or CoinGecko id, such as 'BTC' or 'ethereum'.
        days: Number of trailing days to return (1-365). Defaults to 30.
        interval: 'daily' for a compact series or 'hourly' for intraday detail.
    """
    if not 1 <= days <= 365:
        return {"error": "days must be between 1 and 365."}
    if interval not in {"daily", "hourly"}:
        return {"error": "interval must be 'daily' or 'hourly'."}

    try:
        result = await get_market_chart(coin, days, interval)
        resolved = result["coin"]
        data = result["data"]
    except httpx.HTTPError as exc:
        return {"error": f"Could not fetch historical prices for '{coin}': {exc}"}

    # CoinGecko returns [unix_milliseconds, price] pairs. Named fields are
    # easier for the LLM and frontend to consume safely.
    prices = [
        {
            "timestamp": datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isoformat(),
            "price_usd": round(price, 8),
        }
        for ts, price in data.get("prices", [])
    ]
    return {
        "coin_id": resolved["coin_id"],
        "name": resolved["name"],
        "currency": "usd",
        "days": days,
        "interval": interval,
        "prices": prices,
    }


@mcp.tool()
async def get_market_overview() -> dict:
    """Get the global crypto market snapshot, including BTC/ETH dominance.

    Use this to explain whether a portfolio move reflects a broad market move.
    """
    try:
        data = (await get_json(f"{COINGECKO_BASE}/global")).get("data", {})
    except httpx.HTTPError as exc:
        return {"error": f"Could not fetch global market data: {exc}"}

    return {
        "active_cryptocurrencies": data.get("active_cryptocurrencies"),
        "total_market_cap_usd": data.get("total_market_cap", {}).get("usd"),
        "total_volume_24h_usd": data.get("total_volume", {}).get("usd"),
        "market_cap_change_24h_percent": data.get("market_cap_change_percentage_24h_usd"),
        "btc_dominance_percent": data.get("market_cap_percentage", {}).get("btc"),
        "eth_dominance_percent": data.get("market_cap_percentage", {}).get("eth"),
        "updated_at": datetime.fromtimestamp(data["updated_at"], tz=timezone.utc).isoformat()
        if data.get("updated_at") else None,
    }


@mcp.tool()
async def get_crypto_news(coin: str | None = None, limit: int = 5) -> dict:
    """Get recent crypto news headlines from CryptoCompare's public news feed.

    Args:
        coin: Optional ticker to filter by, e.g. 'BTC' or 'ETH'.
        limit: Number of recent stories to return (1-10).
    """
    if not 1 <= limit <= 10:
        return {"error": "limit must be between 1 and 10."}
    params = {"lang": "EN"}
    if coin:
        params["categories"] = coin.upper()
    try:
        data = await get_json(CRYPTOCOMPARE_NEWS_URL, params=params)
    except httpx.HTTPError as exc:
        return {"error": f"Could not fetch crypto news: {exc}"}

    articles = data.get("Data", [])[:limit]
    return {
        "filter": coin.upper() if coin else "all crypto",
        "articles": [
            {
                "title": article.get("title"),
                "source": article.get("source_info", {}).get("name"),
                "published_at": datetime.fromtimestamp(
                    article["published_on"], tz=timezone.utc
                ).isoformat() if article.get("published_on") else None,
                "url": article.get("url"),
                "categories": article.get("categories"),
            }
            for article in articles
        ],
    }


@mcp.tool()
async def get_upcoming_events(coin: str, limit: int = 10) -> dict:
    """Get dated project updates for a coin, such as releases or upgrades.

    CoinGecko exposes these as project status updates. They are not a complete
    token-unlock calendar, so the response explicitly identifies the source.
    """
    if not 1 <= limit <= 20:
        return {"error": "limit must be between 1 and 20."}
    resolved = await resolve_coin_id(coin)
    try:
        data = await get_json(
            f"{COINGECKO_BASE}/coins/{resolved['coin_id']}/status_updates",
            params={"per_page": limit, "page": 1},
        )
    except httpx.HTTPError as exc:
        return {"error": f"Could not fetch project updates for '{coin}': {exc}"}

    updates = data.get("status_updates", [])
    return {
        "coin_id": resolved["coin_id"],
        "name": resolved["name"],
        "source": "CoinGecko project status updates",
        "events": [
            {
                "title": update.get("project", {}).get("name") or update.get("description", "")[:120],
                "date": update.get("created_at"),
                "description": update.get("description"),
                "category": update.get("category"),
                "url": update.get("user", {}).get("website"),
            }
            for update in updates
        ],
    }


@mcp.tool()
async def get_portfolio_risk(positions: list[dict]) -> dict:
    """Calculate concentration and diversification risk from portfolio positions.

    Args:
        positions: Positions with `coin` and `current_value` fields. Usually pass
            the per-coin output from the application's get_portfolio tool.
    """
    cleaned = []
    for position in positions:
        try:
            value = float(position["current_value"])
        except (KeyError, TypeError, ValueError):
            continue
        if value > 0:
            cleaned.append({"coin": str(position.get("coin", "unknown")), "current_value": value})

    total_value = sum(item["current_value"] for item in cleaned)
    if not cleaned or total_value <= 0:
        return {"error": "Provide at least one position with a positive current_value."}

    allocations = sorted(
        (
            {"coin": item["coin"], "weight_percent": round(item["current_value"] / total_value * 100, 1)}
            for item in cleaned
        ),
        key=lambda item: item["weight_percent"],
        reverse=True,
    )
    hhi = sum((item["weight_percent"] / 100) ** 2 for item in allocations)
    stablecoins = {"tether", "usd-coin", "dai", "first-digital-usd", "usds", "paypal-usd"}
    stablecoin_weight = round(
        sum(item["weight_percent"] for item in allocations if item["coin"].lower() in stablecoins), 1
    )
    largest_weight = allocations[0]["weight_percent"]
    return {
        "portfolio_value_usd": round(total_value, 2),
        "asset_count": len(allocations),
        "allocations": allocations,
        "largest_position": allocations[0],
        "stablecoin_weight_percent": stablecoin_weight,
        "concentration_hhi": round(hhi, 3),
        "risk_level": "high" if largest_weight >= 60 or hhi >= 0.45 else "medium" if largest_weight >= 35 or hhi >= 0.25 else "low",
        "interpretation": "Concentration risk is driven mainly by the largest positions; this is not investment advice.",
    }


# @mcp.resource("crypto://global-market")
# async def global_market_snapshot() -> dict:
#     """Global crypto market reference data: total market cap, 24h volume,
#     and BTC/ETH dominance. Exposed as a resource (not a tool) because it's
#     read-only background context an MCP client can pull into its own
#     context window directly -- no LLM round-trip needed to decide whether
#     or how to call it, unlike a tool.
#     """
#     async with httpx.AsyncClient() as client:
#         resp = await client.get(f"{COINGECKO_BASE}/global")
#         data = resp.json().get("data", {})

#     return {
#         "active_cryptocurrencies": data.get("active_cryptocurrencies"),
#         "total_market_cap_usd": data.get("total_market_cap", {}).get("usd"),
#         "total_volume_24h_usd": data.get("total_volume", {}).get("usd"),
#         "market_cap_change_24h_percent": data.get("market_cap_change_percentage_24h_usd"),
#         "btc_dominance_percent": data.get("market_cap_percentage", {}).get("btc"),
#         "eth_dominance_percent": data.get("market_cap_percentage", {}).get("eth"),
#     }


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
