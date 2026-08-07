"""Visualization JSON: build_portfolio_visualization() is pure (no network,
just shapes a portfolio dict into Plotly figure JSON), so most of this file
runs offline and fast. build_market_visualization() hits live CoinGecko and
is marked integration.
"""

import pytest

from app.visualization import build_market_visualization, build_portfolio_visualization

SAMPLE_PORTFOLIO = {
    "bitcoin": {
        "amount": 0.5,
        "avg_buy_price": 40000,
        "current_price": 45000,
        "change_24h_percent": 2.5,
        "cost_basis": 20000,
        "current_value": 22500,
        "profit_loss": 2500,
        "portfolio_weight_percent": 69.2,
    },
    "ethereum": {
        "amount": 5,
        "avg_buy_price": 2000,
        "current_price": 2000,
        "change_24h_percent": -1.1,
        "cost_basis": 10000,
        "current_value": 10000,
        "profit_loss": 0,
        "portfolio_weight_percent": 30.8,
    },
    "_total": {
        "cost_basis": 30000,
        "current_value": 32500,
        "profit_loss": 2500,
        "today_move_usd": 100,
        "today_move_percent": 0.3,
    },
}


def _assert_is_plotly_figure(chart: dict):
    """Minimal shape check for what the frontend's <Plot data=... layout=...>
    expects: a `data` list of traces and a `layout` dict."""
    assert isinstance(chart["data"], list)
    assert len(chart["data"]) >= 1
    assert isinstance(chart["layout"], dict)
    for trace in chart["data"]:
        assert "type" in trace


@pytest.mark.parametrize("chart_type", ["allocation", "profit_loss", "cost_vs_value"])
def test_each_chart_type_produces_valid_plotly_json(chart_type):
    result = build_portfolio_visualization(SAMPLE_PORTFOLIO, chart_type)

    assert result.chart_type == chart_type
    _assert_is_plotly_figure(result.chart)
    assert result.title
    assert "import" in result.python_code  # editable code artifact, per the no-exec design


def test_allocation_chart_is_a_pie_with_one_slice_per_coin():
    result = build_portfolio_visualization(SAMPLE_PORTFOLIO, "allocation")

    trace = result.chart["data"][0]
    assert trace["type"] == "pie"
    assert set(trace["labels"]) == {"BITCOIN", "ETHEREUM"}
    assert trace["values"] == [22500, 10000]


def test_profit_loss_chart_is_a_bar_per_coin():
    result = build_portfolio_visualization(SAMPLE_PORTFOLIO, "profit_loss")

    trace = result.chart["data"][0]
    assert trace["type"] == "bar"
    assert trace["y"] == [2500, 0]


def test_cost_vs_value_chart_has_two_grouped_bars():
    result = build_portfolio_visualization(SAMPLE_PORTFOLIO, "cost_vs_value")

    assert len(result.chart["data"]) == 2
    names = {trace["name"] for trace in result.chart["data"]}
    assert names == {"Cost basis", "Current value"}


def test_dataframe_excludes_total_and_meta_rows():
    result = build_portfolio_visualization(SAMPLE_PORTFOLIO, "allocation")

    coins = {row["coin"] for row in result.dataframe}
    assert coins == {"bitcoin", "ethereum"}
    assert "_total" not in coins


def test_empty_portfolio_raises_value_error():
    with pytest.raises(ValueError):
        build_portfolio_visualization({"_total": {"cost_basis": 0}}, "allocation")


def test_prices_unavailable_raises_a_clear_error():
    portfolio = {
        "bitcoin": {"amount": 1, "cost_basis": 100, "current_value": None},
        "_meta": {"prices_unavailable": True, "message": "Live prices are temporarily unavailable."},
    }
    with pytest.raises(ValueError, match="temporarily unavailable"):
        build_portfolio_visualization(portfolio, "allocation")


@pytest.mark.integration
async def test_market_visualization_returns_valid_plotly_json_for_real_coin():
    result = await build_market_visualization("bitcoin", metric="price_usd", days=7)

    assert result.coin_id == "bitcoin"
    assert len(result.dataframe) > 0
    _assert_is_plotly_figure(result.chart)


async def test_market_visualization_rejects_out_of_range_days():
    # Validated before any network call, so this doesn't need `integration`.
    with pytest.raises(ValueError):
        await build_market_visualization("bitcoin", days=9999)
