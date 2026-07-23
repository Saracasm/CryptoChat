from uuid import UUID

from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import SessionLocal
from app.models import Profile
from app.repository import Repository


async def get_session() -> AsyncSession:
    """One database session per request = one unit of work.

    Commits if the request succeeds, rolls back if anything raises.
    """
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def get_repository(
    session: AsyncSession = Depends(get_session),
) -> Repository:
    """Reusable component: hand endpoints a Repository, not a raw session."""
    return Repository(session)


async def get_current_profile(
    x_profile_id: UUID = Header(...),
    repo: Repository = Depends(get_repository),
) -> Profile:
    """Resolve the acting profile from the X-Profile-Id header, or 404."""
    profile = await repo.get_profile(x_profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile