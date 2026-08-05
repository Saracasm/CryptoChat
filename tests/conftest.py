"""Shared test fixtures.

Tests run against the real dev database (DATABASE_URL in .env) rather than a
mock -- this is a small project with no separate test database configured,
so each test instead runs inside a SAVEPOINT that's rolled back afterward.
That means tests exercise the real Postgres + pgvector instance (the thing
that actually matters for the RAG isolation/retrieval tests) while never
leaving any data behind. See `session` below.
"""

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import engine
from app.repository import Repository


@pytest_asyncio.fixture
async def session():
    """One DB session per test, wrapped in a savepoint that's always rolled
    back -- so tests can freely create/delete rows without touching the
    real dataset, and without needing a second database.
    """
    async with engine.connect() as conn:
        trans = await conn.begin()
        async_session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint")
        try:
            yield async_session
        finally:
            await async_session.close()
            await trans.rollback()


@pytest_asyncio.fixture
async def repo(session):
    return Repository(session)


@pytest_asyncio.fixture
async def profile(repo):
    """A throwaway profile, gone at the end of the test via rollback."""
    return await repo.create_profile(name="test-profile")


@pytest_asyncio.fixture
async def other_profile(repo):
    """A second, distinct profile -- for isolation tests."""
    return await repo.create_profile(name="test-profile-other")


@pytest_asyncio.fixture
async def conversation(repo, profile):
    return await repo.create_conversation(profile_id=profile.id)
