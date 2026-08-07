from uuid import UUID

from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import SessionLocal
from app.models import Profile
from app.repository import Repository
from app.config import settings
from app.security import require_current_user

async def require_api_key(x_api_key: str = Header(...)) -> None:
    if x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")

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
    user_id: UUID = Depends(require_current_user(settings.jwt_secret)),
    repo: Repository = Depends(get_repository),
) -> Profile:
    """Resolve the acting profile from the JWT bearer token, or 404."""
    profile = await repo.get_profile(user_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile