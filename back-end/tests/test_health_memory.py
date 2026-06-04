"""Tests for the extended /health endpoint reporting all three memory layers."""

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.endpoints.health import router as health_router


@pytest.fixture
def client(monkeypatch):
    # Pretend the facade is started so short_term is not None.
    # Use monkeypatch.setattr so the stub is restored after the test — raw
    # `memory_facade.short_term = ...` would leak the StubST across the rest
    # of the pytest session and break any test that expects the un-started
    # singleton state.
    from app.services.memory import memory_facade

    class StubST:
        async def health(self):
            return True

    monkeypatch.setattr(memory_facade, "short_term", StubST())
    monkeypatch.setattr(
        "app.services.memory.memory_facade.profile.health",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        "app.services.memory.memory_facade.episodic.health",
        AsyncMock(return_value=True),
    )
    app = FastAPI()
    app.include_router(health_router)
    return TestClient(app)


def test_healthy_when_all_three_layers_up(client):
    r = client.get("/health")
    body = r.json()
    assert body["status"] == "healthy"
    assert body["memory"] == {"redis": "ok", "postgres": "ok", "qdrant": "ok"}


def test_degraded_when_postgres_down(monkeypatch, client):
    monkeypatch.setattr(
        "app.services.memory.memory_facade.profile.health",
        AsyncMock(return_value=False),
    )
    r = client.get("/health")
    body = r.json()
    assert body["status"] == "degraded"
    assert body["memory"]["postgres"] == "down"


def test_degraded_when_qdrant_down(monkeypatch, client):
    monkeypatch.setattr(
        "app.services.memory.memory_facade.episodic.health",
        AsyncMock(return_value=False),
    )
    r = client.get("/health")
    assert r.json()["status"] == "degraded"
    assert r.json()["memory"]["qdrant"] == "down"


def test_unhealthy_when_redis_down(monkeypatch, client):
    from app.services.memory import memory_facade

    class StubST:
        async def health(self):
            return False

    monkeypatch.setattr(memory_facade, "short_term", StubST())
    r = client.get("/health")
    assert r.json()["status"] == "unhealthy"
