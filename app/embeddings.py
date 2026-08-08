"""Gemini embeddings, used both at ingest time and query time. Batched to
avoid one API call per chunk on the free-tier rate limit."""

from google import genai

from app.config import settings

_client = genai.Client(api_key=settings.gemini_api_key)

# Chunking our own batches keeps big documents from blowing the per-request payload limit.
_BATCH_SIZE = 100


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed one or more chunks of document text (indexing-time)."""
    if not texts:
        return []

    vectors: list[list[float]] = []
    for start in range(0, len(texts), _BATCH_SIZE):
        batch = texts[start : start + _BATCH_SIZE]
        result = await _client.aio.models.embed_content(
            model=settings.gemini_embedding_model,
            contents=batch,
            config={"output_dimensionality": settings.embedding_dimensions},
        )
        vectors.extend(embedding.values for embedding in result.embeddings)
    return vectors


async def embed_query(text: str) -> list[float]:
    """Embed a single query string (retrieval-time)."""
    vectors = await embed_texts([text])
    return vectors[0]
