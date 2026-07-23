import asyncio

from app.database import Base, engine

# Importing models registers them on Base.metadata so create_all sees them.
import app.models  # noqa: F401

async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    print("Tables created.")

if __name__ == "__main__":
    asyncio.run(main())