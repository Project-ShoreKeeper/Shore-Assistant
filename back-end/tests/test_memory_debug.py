"""Tests for the DEBUG_MEMORY-gated memory_debug router."""

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _app_with_debug_router(monkeypatch) -> FastAPI:
    monkeypatch.setattr("app.core.config.settings.DEBUG_MEMORY", True)
    from app.api.endpoints import memory_debug
    app = FastAPI()
    app.include_router(memory_debug.router)
    return app


def test_profile_change_calls_apply_change(monkeypatch):
    apply = AsyncMock()
    monkeypatch.setattr(
        "app.services.memory.memory_facade.profile.apply_change", apply,
    )
    app = _app_with_debug_router(monkeypatch)
    client = TestClient(app)
    r = client.post("/api/memory/profile/change", json={
        "key_path": "name", "new_value": "Luna",
        "reason": "test",
    })
    assert r.status_code == 200
    assert r.json()["ok"] is True
    apply.assert_awaited_once()


def test_profile_read_returns_data_and_size(monkeypatch):
    monkeypatch.setattr(
        "app.services.memory.memory_facade.profile.read",
        AsyncMock(return_value={"name": "Luna"}),
    )
    app = _app_with_debug_router(monkeypatch)
    client = TestClient(app)
    r = client.get("/api/memory/profile")
    assert r.status_code == 200
    body = r.json()
    assert body["data"] == {"name": "Luna"}
    assert body["size_bytes"] > 0


def test_profile_history_returns_rows(monkeypatch):
    monkeypatch.setattr(
        "app.services.memory.memory_facade.profile.history",
        AsyncMock(return_value=[{"id": 1, "reason": "first seed"}]),
    )
    app = _app_with_debug_router(monkeypatch)
    client = TestClient(app)
    r = client.get("/api/memory/profile/history?key=name&limit=10")
    assert r.status_code == 200
    body = r.json()
    assert body["key_path"] == "name"
    assert len(body["rows"]) == 1


def test_episodic_upsert_calls_upsert(monkeypatch):
    upsert = AsyncMock(return_value="point-1")
    monkeypatch.setattr(
        "app.services.memory.memory_facade.episodic.upsert", upsert,
    )
    app = _app_with_debug_router(monkeypatch)
    client = TestClient(app)
    r = client.post("/api/memory/episodic/upsert", json={
        "fact": "Luna drinks espresso",
        "entity_tags": ["coffee"],
    })
    assert r.status_code == 200
    assert r.json()["point_id"] == "point-1"
    upsert.assert_awaited_once()


def test_episodic_search_returns_hits(monkeypatch):
    from app.services.memory.types import EmotionVector, EpisodicFact, ScoredFact
    fake_hit = ScoredFact(
        score=0.81,
        fact=EpisodicFact(
            fact="Luna drinks espresso",
            entity_tags=["coffee"],
            emotion=EmotionVector(),
            source_turn_ts=1.0,
            source_role="user",
            confidence=0.9,
        ),
    )
    monkeypatch.setattr(
        "app.services.memory.memory_facade.episodic.search",
        AsyncMock(return_value=[fake_hit]),
    )
    app = _app_with_debug_router(monkeypatch)
    client = TestClient(app)
    r = client.get("/api/memory/episodic/search?q=coffee&top_k=3")
    assert r.status_code == 200
    body = r.json()
    assert body["query"] == "coffee"
    assert len(body["hits"]) == 1
    assert body["hits"][0]["fact"] == "Luna drinks espresso"


def test_debug_router_not_included_when_flag_false(monkeypatch):
    """Sanity: main app loads without the debug routes when DEBUG_MEMORY=False."""
    monkeypatch.setattr("app.core.config.settings.DEBUG_MEMORY", False)
    # Re-import main to apply the flag — TestClient hits the constructed app.
    import importlib
    import app.main as main_module
    importlib.reload(main_module)
    client = TestClient(main_module.app)
    r = client.get("/api/memory/profile")
    assert r.status_code == 404
