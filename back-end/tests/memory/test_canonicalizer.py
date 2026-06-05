"""Unit tests for the canonicalizer — Qdrant + embedder mocked."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from app.services.memory.canonicalizer import (
    _cluster_tags, run_canonicalization,
)


def test_cluster_tags_groups_similar_above_threshold():
    # Two tags with cosine ~0.99, one outlier
    v_a = np.array([1.0, 0.0, 0.0])
    v_b = np.array([0.99, 0.01, 0.0])
    v_c = np.array([0.0, 1.0, 0.0])
    vectors = {"coffee": v_a, "coffees": v_b, "tea": v_c}
    clusters = _cluster_tags(vectors, threshold=0.85)
    # Each cluster maps members → canonical tag
    canonical_for = {}
    for canonical, members in clusters.items():
        for m in members:
            canonical_for[m] = canonical
    assert canonical_for["coffee"] == canonical_for["coffees"]
    assert canonical_for["tea"] != canonical_for["coffee"]


def test_cluster_tags_each_tag_in_own_cluster_when_below_threshold():
    v_a = np.array([1.0, 0.0, 0.0])
    v_b = np.array([0.0, 1.0, 0.0])
    clusters = _cluster_tags({"a": v_a, "b": v_b}, threshold=0.85)
    assert len(clusters) == 2


async def test_run_canonicalization_skips_when_disabled(monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.CANONICALIZER_ENABLED", False,
    )
    result = await run_canonicalization()
    assert result["status"] == "disabled"


async def test_run_canonicalization_updates_payloads(monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.CANONICALIZER_ENABLED", True,
    )
    monkeypatch.setattr(
        "app.core.config.settings.CANONICALIZER_SIMILARITY_THRESHOLD", 0.85,
    )

    # Two points: point_a has both "coffee" and "coffees" which cluster together
    point_a = SimpleNamespace(
        id="a", payload={"entity_tags": ["coffees", "coffee"]},
    )
    point_b = SimpleNamespace(
        id="b", payload={"entity_tags": ["tea"]},
    )
    fake_client = MagicMock()
    fake_client.scroll = AsyncMock(return_value=([point_a, point_b], None))
    fake_client.set_payload = AsyncMock()

    fake_episodic = MagicMock()
    fake_episodic._client = fake_client

    with patch(
        "app.services.memory.canonicalizer.memory_facade",
        SimpleNamespace(episodic=fake_episodic),
    ), patch(
        "app.services.memory.canonicalizer.embedder.encode_many",
        new=AsyncMock(side_effect=lambda tags: [
            np.array([1.0, 0.0]) if t in ("coffee", "coffees")
            else np.array([0.0, 1.0])
            for t in tags
        ]),
    ):
        result = await run_canonicalization()

    assert result["status"] == "ok"
    assert result["updated"] == 1  # only point_a needed rewriting
    fake_client.set_payload.assert_awaited_once()
