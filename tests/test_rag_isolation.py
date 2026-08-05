"""RAG access isolation by profile: the most important guarantee in the
whole document pipeline. search_document_chunks() must never surface one
profile's chunks to another, even in adversarial cases (searching WITH the
other profile's own embedding vector).

Uses random vectors, not real Gemini embeddings -- isolation is a property
of the SQL query (WHERE profile_id = ...), not of embedding quality, so
these run fully offline against just the DB and stay fast.
"""

import random


def _fake_vector(dim: int = 768) -> list[float]:
    return [random.random() for _ in range(dim)]


async def test_search_only_returns_own_profiles_documents(repo, profile, other_profile):
    doc_a = await repo.create_document(
        profile.id, "a.txt", "text/plain", "Profile A's private notes."
    )
    vec_a = _fake_vector()
    await repo.add_document_embeddings(doc_a.id, [(0, "Profile A's private notes.", vec_a, {})])

    doc_b = await repo.create_document(
        other_profile.id, "b.txt", "text/plain", "Profile B's private notes."
    )
    vec_b = _fake_vector()
    await repo.add_document_embeddings(doc_b.id, [(0, "Profile B's private notes.", vec_b, {})])

    results = await repo.search_document_chunks(profile.id, vec_a, top_k=5)

    assert len(results) == 1
    assert results[0]["filename"] == "a.txt"


async def test_search_never_leaks_another_profiles_document(repo, profile, other_profile):
    """Adversarial case: search profile A using profile B's OWN embedding
    vector (the best possible match for B's document). Even then, A's
    search must not return B's chunk -- the profile_id filter, not
    vector similarity, is what decides visibility.
    """
    vec_b = _fake_vector()
    doc_b = await repo.create_document(
        other_profile.id, "b-secret.txt", "text/plain", "Profile B's secret."
    )
    await repo.add_document_embeddings(doc_b.id, [(0, "Profile B's secret.", vec_b, {})])

    results = await repo.search_document_chunks(profile.id, vec_b, top_k=5)

    assert results == []
    assert all(r["filename"] != "b-secret.txt" for r in results)


async def test_profile_with_no_documents_gets_empty_results(repo, profile, other_profile):
    doc = await repo.create_document(other_profile.id, "other.txt", "text/plain", "content")
    await repo.add_document_embeddings(doc.id, [(0, "content", _fake_vector(), {})])

    results = await repo.search_document_chunks(profile.id, _fake_vector(), top_k=5)

    assert results == []


async def test_list_documents_is_scoped_to_profile(repo, profile, other_profile):
    await repo.create_document(profile.id, "mine.txt", "text/plain", "mine")
    await repo.create_document(other_profile.id, "theirs.txt", "text/plain", "theirs")

    my_docs = await repo.list_documents(profile.id)

    assert [d.filename for d in my_docs] == ["mine.txt"]
