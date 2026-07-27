from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from app.config import settings

# The engine is the single connection pool to Postgres, created once.
engine = create_async_engine(settings.database_url)

# A factory that hands out AsyncSession objects (one per unit of work).
SessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# Every ORM model inherits from this Base.
class Base(DeclarativeBase):
    pass