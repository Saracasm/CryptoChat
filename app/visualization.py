"""Safe, backend-generated market visualizations.

The returned `chart` is Plotly figure JSON, which the frontend can render with
Plotly later. `python_code` is deliberately an editable *artifact*, not code
executed by the API; this avoids running untrusted user or model Python in the
FastAPI process.
"""

from datetime import datetime, timezone
from typing import Literal

import httpx
from pydantic import BaseModel

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
ChartMetric = Literal["price_usd", "daily_change_pct", "market_cap_usd", "volume_usd"]
PortfolioChartType = Literal["allocation", "profit_loss", "cost_vs_value"]


class VisualizationResult(BaseModel):
    coin_id: str
    coin_name: str
    metric: ChartMetric
    days: int
    title: str
    dataframe: list[dict]
    chart: dict
    python_code: str


class PortfolioVisualizationResult(BaseModel):
    chart_type: PortfolioChartType
    title: str
    dataframe: list[dict]
    chart: dict
    python_code: str


async def get_json(url: str, *, params: dict | None = None) -> dict:
    """Fetch public market data used by the demo's MCP and chart features."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        return response.json()


async def resolve_coin_id(coin: str) -> dict:
    """Resolve a coin name, ticker, or CoinGecko id once for the whole demo."""
    literal = coin.strip().lower()
    data = await get_json(f"{COINGECKO_BASE}/search", params={"query": coin})
    coins = data.get("coins", [])
    if not coins:
        return {"coin_id": literal, "name": coin, "matched": False}
    for item in coins:
        if literal in (item["id"], item["symbol"].lower(), item["name"].lower()):
            return {"coin_id": item["id"], "name": item["name"], "matched": True}
    best = coins[0]
    return {"coin_id": best["id"], "name": best["name"], "matched": True}


async def get_market_chart(coin: str, days: int, interval: str = "daily") -> dict:
    """Get canonical coin metadata plus CoinGecko market-chart data."""
    resolved = await resolve_coin_id(coin)
    data = await get_json(
        f"{COINGECKO_BASE}/coins/{resolved['coin_id']}/market_chart",
        params={"vs_currency": "usd", "days": days, "interval": interval},
    )
    return {"coin": resolved, "data": data}


def _plotly_chart(metric: ChartMetric, title: str, dataframe: list[dict]) -> dict:
    dates = [row["date"] for row in dataframe]
    values = [row[metric] for row in dataframe]
    labels = {
        "price_usd": "Price (USD)",
        "daily_change_pct": "Daily change (%)",
        "market_cap_usd": "Market cap (USD)",
        "volume_usd": "24h trading volume (USD)",
    }
    if metric == "daily_change_pct":
        trace = {
            "type": "bar",
            "x": dates,
            "y": values,
            "marker": {"color": ["#16a34a" if value >= 0 else "#dc2626" for value in values]},
            "name": labels[metric],
        }
    else:
        trace = {
            "type": "scatter",
            "mode": "lines",
            "x": dates,
            "y": values,
            "line": {"color": "#8b5cf6", "width": 2},
            "name": labels[metric],
        }
    return {
        "data": [trace],
        "layout": {
            "title": {"text": title},
            "xaxis": {"title": "Date"},
            "yaxis": {"title": labels[metric]},
            "margin": {"l": 55, "r": 20, "t": 55, "b": 45},
            "template": "plotly_white",
        },
    }


def _python_code(metric: ChartMetric, title: str) -> str:
    y_column = metric
    chart_call = "px.bar" if metric == "daily_change_pct" else "px.line"
    extra = (
        ", color='daily_change_pct', color_continuous_scale=['#dc2626', '#16a34a']"
        if metric == "daily_change_pct" else ""
    )
    return (
        "import pandas as pd\n"
        "import plotly.express as px\n\n"
        "# dataframe is supplied by CryptoChat\n"
        "df = pd.DataFrame(dataframe)\n"
        f"fig = {chart_call}(df, x='date', y='{y_column}', title={title!r}{extra})\n"
        "fig.update_layout(template='plotly_white')\n"
        "fig.show()\n"
    )


async def build_market_visualization(
    coin: str, metric: ChartMetric = "price_usd", days: int = 30) -> VisualizationResult:
    """Build a safe, renderable chart from public CoinGecko history."""
    if not 1 <= days <= 365:
        raise ValueError("days must be between 1 and 365")

    market_chart = await get_market_chart(coin, days, interval="daily")
    coin_id = market_chart["coin"]["coin_id"]
    coin_name = market_chart["coin"]["name"]
    data = market_chart["data"]

    market_cap_by_time = dict(data.get("market_caps", []))
    volume_by_time = dict(data.get("total_volumes", []))
    dataframe = []
    previous_price: float | None = None
    for timestamp, price in data.get("prices", []):
        row = {
            "date": datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc).date().isoformat(),
            "price_usd": round(price, 8),
            "market_cap_usd": round(market_cap_by_time.get(timestamp, 0), 2),
            "volume_usd": round(volume_by_time.get(timestamp, 0), 2),
        }
        row["daily_change_pct"] = (
            round((price / previous_price - 1) * 100, 4) if previous_price else 0.0
        )
        previous_price = price
        dataframe.append(row)

    if not dataframe:
        raise ValueError(f"No historical market data found for '{coin}'.")

    metric_labels = {
        "price_usd": "Price (USD)",
        "daily_change_pct": "Daily Change (%)",
        "market_cap_usd": "Market Cap (USD)",
        "volume_usd": "Trading Volume (USD)",
    }
    title = f"{coin_name} {metric_labels[metric]} — Last {days} Days"
    return VisualizationResult(
        coin_id=coin_id,
        coin_name=coin_name,
        metric=metric,
        days=days,
        title=title,
        dataframe=dataframe,
        chart=_plotly_chart(metric, title, dataframe),
        python_code=_python_code(metric, title),
    )


def build_portfolio_visualization(
    portfolio: dict, chart_type: PortfolioChartType = "allocation"
) -> PortfolioVisualizationResult:
    """Build a chart from private portfolio data already fetched by the agent."""
    dataframe = [
        {"coin": coin, **position}
        for coin, position in portfolio.items()
        if coin not in ("_total", "_meta")
        and isinstance(position, dict)
        and position.get("current_value") is not None
    ]
    if not dataframe:
        if portfolio.get("_meta", {}).get("prices_unavailable"):
            raise ValueError(
                "Live prices are temporarily unavailable, so this chart "
                "can't be built right now -- try again shortly."
            )
        raise ValueError("No portfolio holdings are available to chart.")

    labels = [row["coin"].upper() for row in dataframe]
    if chart_type == "allocation":
        title = "Portfolio Allocation by Current Value"
        chart = {
            "data": [{"type": "pie", "labels": labels, "values": [row["current_value"] for row in dataframe], "hole": 0.55}],
            "layout": {"title": {"text": title}, "template": "plotly_white"},
        }
        python_code = (
            "import pandas as pd\nimport plotly.express as px\n\n"
            "df = pd.DataFrame(dataframe)\n"
            f"fig = px.pie(df, names='coin', values='current_value', hole=0.55, title={title!r})\n"
            "fig.show()\n"
        )
    elif chart_type == "profit_loss":
        title = "Profit / Loss by Holding"
        values = [row["profit_loss"] for row in dataframe]
        chart = {
            "data": [{"type": "bar", "x": labels, "y": values, "marker": {"color": ["#16a34a" if value >= 0 else "#dc2626" for value in values]}, "name": "Profit / Loss"}],
            "layout": {"title": {"text": title}, "xaxis": {"title": "Holding"}, "yaxis": {"title": "Profit / Loss (USD)"}, "template": "plotly_white"},
        }
        python_code = (
            "import pandas as pd\nimport plotly.express as px\n\n"
            "df = pd.DataFrame(dataframe)\n"
            f"fig = px.bar(df, x='coin', y='profit_loss', color='profit_loss', title={title!r})\n"
            "fig.show()\n"
        )
    else:
        title = "Cost Basis vs. Current Value"
        chart = {
            "data": [
                {"type": "bar", "name": "Cost basis", "x": labels, "y": [row["cost_basis"] for row in dataframe]},
                {"type": "bar", "name": "Current value", "x": labels, "y": [row["current_value"] for row in dataframe]},
            ],
            "layout": {"title": {"text": title}, "barmode": "group", "xaxis": {"title": "Holding"}, "yaxis": {"title": "USD"}, "template": "plotly_white"},
        }
        python_code = (
            "import pandas as pd\nimport plotly.express as px\n\n"
            "df = pd.DataFrame(dataframe)\n"
            "long_df = df.melt(id_vars='coin', value_vars=['cost_basis', 'current_value'], var_name='metric', value_name='usd')\n"
            f"fig = px.bar(long_df, x='coin', y='usd', color='metric', barmode='group', title={title!r})\n"
            "fig.show()\n"
        )
    return PortfolioVisualizationResult(
        chart_type=chart_type, title=title, dataframe=dataframe, chart=chart,
        python_code=python_code,
    )
