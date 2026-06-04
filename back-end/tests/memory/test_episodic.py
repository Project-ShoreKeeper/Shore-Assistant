"""Unit tests for EpisodicMemory — qdrant client mocked."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest

from app.services.memory.episodic import EpisodicMemory, _fact_point_id
from app.services.memory.types import EpisodicFact, EmotionVector


def _fact(text: str = "Luna drinks espresso", tags=("coffee",)) -> EpisodicFact:
    return EpisodicFact(
        fact=text,
        entity_tags=list(tags),
        emotion=EmotionVector(joy=0.6),
        source_turn_ts=1.0,
        source_role="user",
        confidence=0.9,
    )


def test_fact_point_id_deterministic():
    f1 = _fact("same text")
    f2 = _fact("same text")
    assert _fact_point_id(f1) == _fact_point_id(f2)


def test_fact_point_id_changes_when_text_changes():
    assert _fact_point_id(_fact("one")) != _fact_point_id(_fact("two"))


async def test_ensure_collection_noop_when_existing():
    em = EpisodicMemory()
    client = AsyncMock()
    client.get_collections.return_value = SimpleNamespace(
        collections=[SimpleNamespace(name="shore_episodic")],
    )
    em._client = client
    await em._ensure_collection()
    client.create_collection.assert_not_awaited()
    client.create_payload_index.assert_not_awaited()


async def test_ensure_collection_creates_with_indexes_when_missing():
    em = EpisodicMemory()
    client = AsyncMock()
    client.get_collections.return_value = SimpleNamespace(collections=[])
    em._client = client
    await em._ensure_collection()
    client.create_collection.assert_awaited_once()
    # 3 indexes: entity_tags, created_at, valence
    assert client.create_payload_index.await_count == 3


async def test_upsert_builds_payload_and_returns_point_id():
    em = EpisodicMemory()
    client = AsyncMock()
    em._client = client
    with patch(
        "app.services.memory.episodic.embedder.encode",
        new=AsyncMock(return_value=[0.0] * 384),
    ):
        point_id = await em.upsert(_fact())
    assert isinstance(point_id, str)
    client.upsert.assert_awaited_once()
    kwargs = client.upsert.await_args.kwargs
    points = kwargs["points"]
    assert len(points) == 1
    payload = points[0].payload
    assert payload["fact"] == "Luna drinks espresso"
    assert payload["entity_tags"] == ["coffee"]
    assert "valence" in payload
    assert payload["embedding_model_version"]


async def test_upsert_same_fact_uses_same_point_id():
    em = EpisodicMemory()
    client = AsyncMock()
    em._client = client
    with patch(
        "app.services.memory.episodic.embedder.encode",
        new=AsyncMock(return_value=[0.0] * 384),
    ):
        id1 = await em.upsert(_fact("hello"))
        id2 = await em.upsert(_fact("hello"))
    assert id1 == id2


async def test_search_passes_score_threshold_and_no_filter_when_empty():
    em = EpisodicMemory()
    client = AsyncMock()
    client.search.return_value = []
    em._client = client
    with patch(
        "app.services.memory.episodic.embedder.encode",
        new=AsyncMock(return_value=[0.0] * 384),
    ):
        await em.search("query", top_k=3, min_score=0.4)
    kwargs = client.search.await_args.kwargs
    assert kwargs["limit"] == 3
    assert kwargs["score_threshold"] == 0.4
    assert kwargs["query_filter"] is None


async def test_search_builds_filter_when_entity_filter_provided():
    em = EpisodicMemory()
    client = AsyncMock()
    client.search.return_value = []
    em._client = client
    with patch(
        "app.services.memory.episodic.embedder.encode",
        new=AsyncMock(return_value=[0.0] * 384),
    ):
        await em.search("q", entity_filter=["coffee"])
    qf = client.search.await_args.kwargs["query_filter"]
    assert qf is not None  # qm.Filter instance


async def test_search_maps_hits_to_scored_facts():
    em = EpisodicMemory()
    client = AsyncMock()
    hit_payload = {
        "fact": "Luna drinks espresso",
        "entity_tags": ["coffee"],
        "emotion": EmotionVector(joy=0.6).model_dump(),
        "valence": 0.15,
        "source_turn_ts": 1.0,
        "source_role": "user",
        "created_at": 100.0,
        "confidence": 0.9,
        "embedding_model_version": "all-MiniLM-L6-v2",
    }
    client.search.return_value = [
        SimpleNamespace(score=0.92, payload=hit_payload),
    ]
    em._client = client
    with patch(
        "app.services.memory.episodic.embedder.encode",
        new=AsyncMock(return_value=[0.0] * 384),
    ):
        results = await em.search("coffee?")
    assert len(results) == 1
    assert results[0].score == 0.92
    assert results[0].fact.fact == "Luna drinks espresso"
    assert results[0].fact.entity_tags == ["coffee"]


async def test_health_false_when_client_none():
    em = EpisodicMemory()
    assert await em.health() is False
