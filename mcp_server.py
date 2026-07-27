# from uuid import UUID

import httpx
from mcp.server.fastmcp import FastMCP
# from sqlalchemy import select

# from app.database import SessionLocal
# from app.models import Holding

mcp = FastMCP("crypto-tools", host="127.0.0.1", port=8001)

COINGECKO_BASE = "https://api.coingecko.com/api/v3"


@mcp.tool()
async def get_trending_coins() -> list[dict]:
    """Get the coins currently trending (most searched) on CoinGecko."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{COINGECKO_BASE}/search/trending")
        data = resp.json()

    return [
        {
            "coin_id": item["item"]["id"],
            "name": item["item"]["name"],
            "symbol": item["item"]["symbol"],
            "market_cap_rank": item["item"].get("market_cap_rank"),
        }
        for item in data.get("coins", [])
    ]


async def _resolve_coin_id(coin: str) -> dict:
    """Resolve free-text coin input (name, symbol, or id) to a CoinGecko id.

    Tries the literal lowercased value first (it's already an id most of the
    time), then falls back to CoinGecko's search endpoint for free-text names.
    """
    literal = coin.strip().lower()
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{COINGECKO_BASE}/search", params={"query": coin})
        data = resp.json()

    coins = data.get("coins", [])
    if not coins:
        return {"coin_id": literal, "name": coin, "matched": False}

    for c in coins:
        if literal in (c["id"], c["symbol"].lower(), c["name"].lower()):
            return {"coin_id": c["id"], "name": c["name"], "matched": True}

    best = coins[0]
    return {"coin_id": best["id"], "name": best["name"], "matched": True}


@mcp.tool()
async def get_coin_market_data(coin: str) -> dict:
    """Get market cap, 24h change, rank, and volume for a coin.

    Args:
        coin: Coin name, symbol, or CoinGecko id, e.g. 'Bitcoin', 'BTC', 'bitcoin'.
    """
    resolved = await _resolve_coin_id(coin)
    coin_id = resolved["coin_id"]

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{COINGECKO_BASE}/coins/markets",
            params={"vs_currency": "usd", "ids": coin_id},
        )
        data = resp.json()

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
