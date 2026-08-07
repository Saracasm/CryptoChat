"""Portfolio math: get_portfolio_report() -- cost basis, current value,
P&L, and allocation %. The no-holdings path is pure logic (no network); the
rest needs live CoinGecko prices, so those are marked integration and assert
structural invariants (e.g. cost_basis == amount * buy_price, weights sum to
~100%) rather than exact dollar figures, since prices move.
"""

import pytest

from app.agent import get_portfolio_report


async def test_no_holdings_returns_message(repo, conversation):
    report = await get_portfolio_report(repo, conversation.id)
    assert report == {"message": "No holdings recorded yet."}


async def test_cost_basis_is_amount_times_buy_price(repo, conversation):
    await repo.add_holding(conversation.id, "bitcoin", amount=0.5, buy_price=40000)
    await repo.add_holding(conversation.id, "ethereum", amount=2, buy_price=2000)

    report = await get_portfolio_report(repo, conversation.id)

    assert report["bitcoin"]["cost_basis"] == pytest.approx(0.5 * 40000)
    assert report["ethereum"]["cost_basis"] == pytest.approx(2 * 2000)
    assert report["_total"]["cost_basis"] == pytest.approx(0.5 * 40000 + 2 * 2000)


async def test_multiple_lots_of_same_coin_are_averaged_and_summed(repo, conversation):
    await repo.add_holding(conversation.id, "bitcoin", amount=1, buy_price=30000)
    await repo.add_holding(conversation.id, "bitcoin", amount=1, buy_price=50000)

    report = await get_portfolio_report(repo, conversation.id)

    assert report["bitcoin"]["amount"] == pytest.approx(2)
    assert report["bitcoin"]["avg_buy_price"] == pytest.approx(40000)
    assert report["bitcoin"]["cost_basis"] == pytest.approx(80000)


@pytest.mark.integration
async def test_profit_loss_equals_value_minus_cost_basis(repo, conversation):
    await repo.add_holding(conversation.id, "bitcoin", amount=0.5, buy_price=40000)

    report = await get_portfolio_report(repo, conversation.id)

    if report.get("_meta", {}).get("prices_unavailable"):
        pytest.skip("CoinGecko unavailable/rate-limited in this run")

    position = report["bitcoin"]
    assert position["current_value"] == pytest.approx(position["amount"] * position["current_price"])
    assert position["profit_loss"] == pytest.approx(position["current_value"] - position["cost_basis"])
    assert report["_total"]["profit_loss"] == pytest.approx(
        report["_total"]["current_value"] - report["_total"]["cost_basis"]
    )


@pytest.mark.integration
async def test_allocation_weights_sum_to_100_percent(repo, conversation):
    await repo.add_holding(conversation.id, "bitcoin", amount=0.5, buy_price=40000)
    await repo.add_holding(conversation.id, "ethereum", amount=5, buy_price=2000)

    report = await get_portfolio_report(repo, conversation.id)

    if report.get("_meta", {}).get("prices_unavailable"):
        pytest.skip("CoinGecko unavailable/rate-limited in this run")

    weights = [
        report[coin]["portfolio_weight_percent"]
        for coin in ("bitcoin", "ethereum")
        if report[coin]["portfolio_weight_percent"] is not None
    ]
    assert sum(weights) == pytest.approx(100, abs=0.5)
