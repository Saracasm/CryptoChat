"""Dataframe summarizer: write_sql_query's >50-row path (app.agent).

The pure-logic piece (decimal coercion so Postgres NUMERIC columns are
actually seen as numeric) needs no network and runs every time. The
end-to-end piece (seed >50 holdings, run the real summarizer LLM call) hits
OpenRouter, so it's marked integration like the project's other LLM/network
tests.
"""

import pytest

from app.agent import (
    DATAFRAME_SUMMARY_ROW_THRESHOLD,
    _dataframe_facts,
    summarize_dataframe,
)


def test_decimal_columns_are_detected_as_numeric():
    """Regression check: Postgres NUMERIC columns come back as Python
    Decimal via asyncpg, which pandas used to treat as non-numeric and
    silently skip -- metrics/outliers ended up empty even for all-numeric
    data. See app.agent._coerce_numeric_columns.
    """
    import pandas as pd
    from decimal import Decimal

    df = pd.DataFrame(
        [
            {"coin": "bitcoin", "amount": Decimal("0.5"), "buy_price": Decimal("100.00")},
            {"coin": "ethereum", "amount": Decimal("2.0"), "buy_price": Decimal("200.00")},
        ]
    )

    facts = _dataframe_facts(df)

    assert set(facts["numeric_metrics"].keys()) == {"amount", "buy_price"}
    assert facts["numeric_metrics"]["buy_price"]["max"] == 200.0
    assert facts["numeric_metrics"]["buy_price"]["min"] == 100.0


@pytest.mark.integration
async def test_summarize_dataframe_on_more_than_50_rows(repo, conversation):
    row_count = DATAFRAME_SUMMARY_ROW_THRESHOLD + 11  # comfortably over the threshold
    for i in range(row_count):
        await repo.add_holding(conversation.id, "bitcoin", amount=0.1, buy_price=100 + i)

    rows = await repo.execute_raw_sql(
        f"SELECT coin, amount, buy_price FROM holdings "
        f"WHERE conversation_id = '{conversation.id}'"
    )
    assert len(rows) == row_count

    summary = await summarize_dataframe(rows, task="list all of the user's holdings")

    assert summary["row_count"] == row_count
    assert "buy_price" in summary["metrics"]
    assert summary["metrics"]["buy_price"]["max"] == 100 + row_count - 1
    assert summary["metrics"]["buy_price"]["min"] == 100
    assert len(summary["sample"]) <= 5
    assert summary["explanation"].strip() != ""
