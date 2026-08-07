"""Visualization planning subagent: plan_visualization() picks a data
source (portfolio vs market), a chart shape, and x/y fields for a free-text
chart request, then generates and sandbox-executes the code for it.

Argument validation is pure and runs offline every time. Anything that
actually calls the planner LLM or CoinGecko is marked integration, like the
project's other LLM/network tests.
"""

import pytest

from app.agent import Deps, plan_visualization
from app.visualization import build_multi_coin_dataframe


async def test_multi_coin_dataframe_rejects_out_of_range_days():
    with pytest.raises(ValueError):
        await build_multi_coin_dataframe(["bitcoin"], days=9999)


async def test_multi_coin_dataframe_requires_at_least_one_coin():
    with pytest.raises(ValueError):
        await build_multi_coin_dataframe([], days=30)


@pytest.mark.integration
async def test_plan_visualization_portfolio_request_without_a_conversation_errors():
    # No repo/conversation_id in deps -- if the planner ever picks
    # 'portfolio' for a request with nothing to read holdings from, this
    # must come back as a clean error, not a crash.
    result = await plan_visualization(
        Deps(repo=None, conversation_id=None), "show my allocation as a donut chart"
    )
    assert "error" in result


@pytest.mark.integration
async def test_multi_coin_dataframe_returns_one_series_per_coin():
    rows = await build_multi_coin_dataframe(["bitcoin", "ethereum"], days=7)

    coins = {row["coin"] for row in rows}
    assert len(coins) == 2
    for row in rows:
        assert {"date", "coin", "price_usd", "daily_change_pct", "market_cap_usd", "volume_usd"} <= row.keys()


@pytest.mark.integration
async def test_plan_visualization_builds_a_portfolio_chart(repo, conversation):
    await repo.add_holding(conversation.id, "bitcoin", amount=0.5, buy_price=40000)
    await repo.add_holding(conversation.id, "ethereum", amount=5, buy_price=2000)

    result = await plan_visualization(
        Deps(repo=repo, conversation_id=conversation.id),
        "show my portfolio allocation as a donut chart",
    )

    assert "error" not in result
    assert result["plan"]["data_source"] == "portfolio"
    assert result["dataframe"]
    assert isinstance(result["chart"]["data"], list)
    assert "fig" in result["code"]  # the generated snippet assigns the chart to `fig`


@pytest.mark.integration
async def test_plan_visualization_builds_a_market_comparison_chart():
    result = await plan_visualization(
        Deps(repo=None, conversation_id=None),
        "compare BTC and ETH price over the last week",
    )

    assert "error" not in result
    assert result["plan"]["data_source"] == "market"
    assert len(result["plan"]["coins"]) >= 2
    assert isinstance(result["chart"]["data"], list)
