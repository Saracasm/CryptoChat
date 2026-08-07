"""Holdings CRUD: add, list, dedupe, update, remove -- Repository methods
used directly by the agent's log_holding/update_holding/remove_holding tools.
"""


async def test_add_and_get_holding(repo, conversation):
    await repo.add_holding(conversation.id, "bitcoin", amount=0.5, buy_price=40000)

    holdings = await repo.get_holdings(conversation.id)

    assert len(holdings) == 1
    assert holdings[0].coin == "bitcoin"
    assert float(holdings[0].amount) == 0.5
    assert float(holdings[0].buy_price) == 40000


async def test_add_multiple_lots_for_same_coin(repo, conversation):
    await repo.add_holding(conversation.id, "bitcoin", amount=0.5, buy_price=40000)
    await repo.add_holding(conversation.id, "bitcoin", amount=0.25, buy_price=45000)

    holdings = await repo.get_holdings(conversation.id)

    assert len(holdings) == 2


async def test_holding_exists_detects_duplicate(repo, conversation):
    await repo.add_holding(conversation.id, "ethereum", amount=1.0, buy_price=2500)

    assert await repo.holding_exists(conversation.id, "ethereum", 1.0, 2500) is True
    assert await repo.holding_exists(conversation.id, "ethereum", 2.0, 2500) is False
    assert await repo.holding_exists(conversation.id, "solana", 1.0, 2500) is False


async def test_update_holding_by_coin(repo, conversation):
    await repo.add_holding(conversation.id, "solana", amount=10, buy_price=100)

    updated = await repo.update_holding(conversation.id, "solana", new_amount=20)

    assert updated is True
    holdings = await repo.get_holdings(conversation.id)
    assert float(holdings[0].amount) == 20
    assert float(holdings[0].buy_price) == 100  # untouched


async def test_update_holding_disambiguates_by_old_buy_price(repo, conversation):
    await repo.add_holding(conversation.id, "bitcoin", amount=0.1, buy_price=30000)
    await repo.add_holding(conversation.id, "bitcoin", amount=0.2, buy_price=50000)

    updated = await repo.update_holding(
        conversation.id, "bitcoin", new_buy_price=31000, old_buy_price=30000
    )

    assert updated is True
    holdings = {float(h.buy_price) for h in await repo.get_holdings(conversation.id)}
    assert holdings == {31000, 50000}


async def test_update_holding_returns_false_when_not_found(repo, conversation):
    updated = await repo.update_holding(conversation.id, "dogecoin", new_amount=5)
    assert updated is False


async def test_remove_holding(repo, conversation):
    await repo.add_holding(conversation.id, "bitcoin", amount=0.5, buy_price=40000)

    removed = await repo.remove_holding(conversation.id, "bitcoin")

    assert removed is True
    assert await repo.get_holdings(conversation.id) == []


async def test_remove_holding_by_specific_lot(repo, conversation):
    await repo.add_holding(conversation.id, "bitcoin", amount=0.1, buy_price=30000)
    await repo.add_holding(conversation.id, "bitcoin", amount=0.2, buy_price=50000)

    removed = await repo.remove_holding(conversation.id, "bitcoin", buy_price=30000)

    assert removed is True
    remaining = await repo.get_holdings(conversation.id)
    assert len(remaining) == 1
    assert float(remaining[0].buy_price) == 50000


async def test_remove_holding_returns_false_when_not_found(repo, conversation):
    removed = await repo.remove_holding(conversation.id, "dogecoin")
    assert removed is False


async def test_holdings_are_scoped_to_conversation(repo, profile, conversation):
    other_conversation = await repo.create_conversation(profile_id=profile.id)
    await repo.add_holding(conversation.id, "bitcoin", amount=1, buy_price=40000)

    assert len(await repo.get_holdings(conversation.id)) == 1
    assert await repo.get_holdings(other_conversation.id) == []
