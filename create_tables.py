import asyncio

from sqlalchemy import text

from app.database import Base, engine

# Importing models registers them on Base.metadata so create_all sees them.
import app.models  # noqa: F401

async def main():
    async with engine.begin() as conn:
        # Required once per DB before the `embedding` Vector column can be created.
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
        # HNSW index for fast approximate cosine-similarity search.
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS document_embeddings_embedding_hnsw_idx "
                "ON document_embeddings USING hnsw (embedding vector_cosine_ops)"
            )
        )
    await engine.dispose()
    print("Tables created.")

if __name__ == "__main__":
    asyncio.run(main())