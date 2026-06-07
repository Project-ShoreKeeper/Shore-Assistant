"""Integration tests — require a real Qdrant at QDRANT_URL.

Gated by SHORE_INTEGRATION_TEST=1. The test runs against a side collection so
the production `shore_episodic` collection is never touched.
"""

import os
import uuid

import pytest
import pytest_asyncio

from app.services.memory.episodic import EpisodicMemory
from app.services.memory.types import EmotionVector, EpisodicFact


pytestmark = pytest.mark.skipif(
    os.getenv("SHORE_INTEGRATION_TEST") != "1",
    reason="Integration tests opt-in via SHORE_INTEGRATION_TEST=1",
)


def _fact(text: str, tags: list[str], ts: float = 1.0) -> EpisodicFact:
    return EpisodicFact(
        fact=text,
        entity_tags=tags,
        emotion=EmotionVector(joy=0.5),
        source_turn_ts=ts,
        source_role="user",
        confidence=0.9,
    )


@pytest_asyncio.fixture
async def episodic(monkeypatch):
    coll = f"shore_episodic_test_{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr("app.core.config.settings.QDRANT_COLLECTION", coll)
    em = EpisodicMemory()
    await em.startup()
    yield em
    # Cleanup — delete the side collection
    try:
        await em._client.delete_collection(collection_name=coll)
    except Exception:
        pass
    await em.shutdown()


async def test_upsert_then_count(episodic):
    for i, (text, tags) in enumerate([
        ("Luna drinks espresso", ["coffee"]),
        ("Luna prefers dark roast", ["coffee"]),
        ("Luna lives in Hanoi", ["place"]),
        ("Shore Assistant uses CUDA 12.9", ["shore_assistant"]),
        ("Luna writes Python", ["language"]),
    ]):
        await episodic.upsert(_fact(text, tags, ts=float(i)))
    assert await episodic.count() == 5


async def test_re_upsert_same_fact_does_not_duplicate(episodic):
    f = _fact("Luna drinks espresso", ["coffee"])
    await episodic.upsert(f)
    await episodic.upsert(f)
    assert await episodic.count() == 1


async def test_search_returns_relevant_hits(episodic):
    await episodic.upsert(_fact("Luna drinks espresso", ["coffee"], ts=1.0))
    await episodic.upsert(_fact("Shore uses CUDA 12.9", ["shore_assistant"], ts=2.0))
    results = await episodic.search("what coffee do I like?", top_k=3, min_score=0.1)
    assert any("espresso" in r.fact.fact.lower() for r in results)


async def test_entity_filter_narrows_results(episodic):
    await episodic.upsert(_fact("Luna drinks espresso", ["coffee"], ts=1.0))
    await episodic.upsert(_fact("Luna lives in Hanoi", ["place"], ts=2.0))
    coffee_only = await episodic.search(
        "Luna", entity_filter=["coffee"], top_k=5, min_score=0.0,
    )
    assert all("coffee" in r.fact.entity_tags for r in coffee_only)
