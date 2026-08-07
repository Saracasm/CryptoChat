"""Coin resolution: resolve_coin_id() turns a name/symbol/id into the
canonical CoinGecko id every other tool relies on. Hits the real CoinGecko
search API -- no local fixture data exists for "every coin name", and this
project has no HTTP-mocking setup yet.
"""

import pytest

from app.visualization import resolve_coin_id

pytestmark = pytest.mark.integration


async def test_resolve_by_canonical_id():
    result = await resolve_coin_id("bitcoin")
    assert result["coin_id"] == "bitcoin"
    assert result["matched"] is True


async def test_resolve_by_symbol():
    result = await resolve_coin_id("BTC")
    assert result["coin_id"] == "bitcoin"


async def test_resolve_by_display_name():
    result = await resolve_coin_id("Ethereum")
    assert result["coin_id"] == "ethereum"


async def test_resolve_is_case_insensitive():
    lower = await resolve_coin_id("solana")
    upper = await resolve_coin_id("SOLANA")
    mixed = await resolve_coin_id("Solana")
    assert lower["coin_id"] == upper["coin_id"] == mixed["coin_id"] == "solana"


async def test_resolve_unknown_coin_does_not_crash():
    # No CoinGecko match: falls back to the literal string, flagged unmatched,
    # rather than raising -- callers (agent tools) rely on this not crashing.
    result = await resolve_coin_id("this-is-not-a-real-coin-zzz")
    assert result["matched"] is False
    assert result["coin_id"] == "this-is-not-a-real-coin-zzz"
