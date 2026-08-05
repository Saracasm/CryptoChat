"""Vector retrieval: does the full ingest -> embed -> search path actually
return semantically relevant chunks, not just "some chunk"? Needs real
Gemini embeddings (both to index and to embed the query), so this is
marked integration -- there's no local embedding stub in this project.
"""

import pytest

from app.embeddings import embed_query
from app.ingest import chunk_text, ingest_document

pytestmark = pytest.mark.integration

SAMPLE_DOCUMENT = (
    "CryptoChat Investment Notes\n\n"
    "Bitcoin (BTC) is a decentralized digital currency created in 2009. "
    "It has a hard cap of 21 million coins, which makes it deflationary "
    "by design. Many investors treat it as digital gold.\n\n"
    "Ethereum (ETH) introduced smart contracts, enabling decentralized "
    "applications. Its supply is not fixed but issuance has slowed since "
    "the Merge to proof-of-stake in 2022.\n\n"
) * 15  # long enough to force multiple chunks


async def test_ingest_produces_multiple_chunks():
    chunks = chunk_text(SAMPLE_DOCUMENT)
    assert len(chunks) > 1
    assert all(chunk.strip() for chunk in chunks)


async def test_ingest_document_persists_document_and_chunks(repo, profile):
    summary = await ingest_document(
        repo, profile.id, "notes.txt", "text/plain", SAMPLE_DOCUMENT.encode("utf-8")
    )

    assert summary["filename"] == "notes.txt"
    assert summary["chunk_count"] > 1
    # extract_text() strips leading/trailing whitespace, so this is a few
    # chars shorter than the raw sample (which ends in "\n\n").
    assert summary["char_count"] == len(SAMPLE_DOCUMENT.strip())

    docs = await repo.list_documents(profile.id)
    assert len(docs) == 1
    assert docs[0].filename == "notes.txt"


async def test_semantic_search_retrieves_the_relevant_chunk(repo, profile):
    await ingest_document(
        repo, profile.id, "notes.txt", "text/plain", SAMPLE_DOCUMENT.encode("utf-8")
    )

    query_vector = await embed_query("What is Bitcoin's maximum supply?")
    results = await repo.search_document_chunks(profile.id, query_vector, top_k=3)

    assert results
    top_chunk_text = results[0]["chunk_text"]
    assert "21 million" in top_chunk_text or "Bitcoin" in top_chunk_text
    assert results[0]["filename"] == "notes.txt"
    # Cosine similarity is bounded [-1, 1]; a real match should score
    # meaningfully positive, not just "least bad of the results".
    assert results[0]["similarity"] > 0.4


async def test_search_result_includes_source_filename_and_chunk_index(repo, profile):
    await ingest_document(
        repo, profile.id, "whitepaper.md", "text/markdown", SAMPLE_DOCUMENT.encode("utf-8")
    )

    query_vector = await embed_query("smart contracts and proof of stake")
    results = await repo.search_document_chunks(profile.id, query_vector, top_k=1)

    assert results[0]["filename"] == "whitepaper.md"
    assert isinstance(results[0]["chunk_index"], int)
    assert "document_id" in results[0]
