"""Tests for the memory admin router (Profile, Episodic, Audit, Restore)."""

from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _app_with_memory_router() -> FastAPI:
    from app.api.endpoints import memory
    app = FastAPI()
    app.include_router(memory.router)
    return app


def test_profile_change_calls_apply_change(monkeypatch):
    apply = AsyncMock()
    monkeypatch.setattr(
        "app.services.memory.memory_facade.profile.apply_change", apply,
    )
    client = TestClient(_app_with_memory_router())
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
    client = TestClient(_app_with_memory_router())
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
    client = TestClient(_app_with_memory_router())
    r = client.get("/api/memory/profile/history?key=name&limit=10")
    assert r.status_code == 200
    body = r.json()
    assert body["key_path"] == "name"
    assert len(body["rows"]) == 1


def test_profile_audit_returns_global_rows(monkeypatch):
    monkeypatch.setattr(
        "app.services.memory.memory_facade.profile.audit_recent",
        AsyncMock(return_value=[
            {"id": 2, "key_path": "name", "reason": "seed"},
            {"id": 1, "key_path": "pets", "reason": "seed"},
        ]),
    )
    client = TestClient(_app_with_memory_router())
    r = client.get("/api/memory/profile/audit?limit=10")
    assert r.status_code == 200
    body = r.json()
    assert len(body["rows"]) == 2


def test_profile_restore_calls_service(monkeypatch):
    restore = AsyncMock(return_value={"id": 99, "key_path": "name"})
    monkeypatch.setattr(
        "app.services.memory.memory_facade.profile.restore", restore,
    )
    client = TestClient(_app_with_memory_router())
    r = client.post("/api/memory/profile/restore", json={
        "audit_id": 5, "reason": "rolling back",
    })
    assert r.status_code == 200
    assert r.json()["new_row"]["id"] == 99
    restore.assert_awaited_once_with(5, "rolling back")


def test_profile_restore_404_on_unknown(monkeypatch):
    monkeypatch.setattr(
        "app.services.memory.memory_facade.profile.restore",
        AsyncMock(side_effect=ValueError("audit id 5 not found")),
    )
    client = TestClient(_app_with_memory_router())
    r = client.post("/api/memory/profile/restore", json={"audit_id": 5})
    assert r.status_code == 404


def test_episodic_upsert_calls_upsert(monkeypatch):
    upsert = AsyncMock(return_value="point-1")
    monkeypatch.setattr(
        "app.services.memory.memory_facade.episodic.upsert", upsert,
    )
    client = TestClient(_app_with_memory_router())
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
        point_id="pt-1",
        created_at=1700000000.0,
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
    client = TestClient(_app_with_memory_router())
    r = client.get("/api/memory/episodic/search?q=coffee&top_k=3")
    assert r.status_code == 200
    body = r.json()
    assert body["query"] == "coffee"
    assert len(body["hits"]) == 1
    assert body["hits"][0]["fact"] == "Luna drinks espresso"
    assert body["hits"][0]["point_id"] == "pt-1"


def test_episodic_recent_returns_rows(monkeypatch):
    from app.services.memory.types import EmotionVector, EpisodicFact, ScoredFact
    fake = ScoredFact(
        score=1.0,
        point_id="pt-recent",
        created_at=1700000100.0,
        fact=EpisodicFact(
            fact="Luna prefers oolong",
            entity_tags=["tea"],
            emotion=EmotionVector(),
            source_turn_ts=2.0,
            source_role="user",
            confidence=1.0,
        ),
    )
    monkeypatch.setattr(
        "app.services.memory.memory_facade.episodic.list_recent",
        AsyncMock(return_value=[fake]),
    )
    client = TestClient(_app_with_memory_router())
    r = client.get("/api/memory/episodic/recent?limit=25")
    assert r.status_code == 200
    body = r.json()
    assert body["rows"][0]["point_id"] == "pt-recent"
    assert body["rows"][0]["fact"] == "Luna prefers oolong"


def test_episodic_delete_calls_service(monkeypatch):
    delete = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "app.services.memory.memory_facade.episodic.delete", delete,
    )
    client = TestClient(_app_with_memory_router())
    r = client.delete("/api/memory/episodic/pt-1")
    assert r.status_code == 200
    delete.assert_awaited_once_with("pt-1")


def test_episodic_delete_404_when_missing(monkeypatch):
    monkeypatch.setattr(
        "app.services.memory.memory_facade.episodic.delete",
        AsyncMock(return_value=False),
    )
    client = TestClient(_app_with_memory_router())
    r = client.delete("/api/memory/episodic/missing")
    assert r.status_code == 404
