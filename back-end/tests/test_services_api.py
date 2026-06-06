"""Tests for /api/services endpoints."""
import asyncio
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import deps as auth_deps
from app.services.controllers.base import Controller, ServiceKind
from app.services.service_manager import ServiceManager


@pytest.fixture(autouse=True)
def _disable_auth(monkeypatch):
    """Run every test as the legacy admin (AUTH_ENABLED=False short-circuit)."""
    monkeypatch.setattr(auth_deps.settings, "AUTH_ENABLED", False)


class _FakeCtrl(Controller):
    def __init__(self, name="fake", *, running=False, slow=False, fail=False):
        super().__init__(name, display_name=name, correlates_with=name)
        self._running = running
        self._slow = slow
        self._fail = fail

    @property
    def kind(self) -> ServiceKind:
        return "internal"

    async def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        if self._slow:
            await asyncio.sleep(0.1)
        if self._fail:
            raise RuntimeError("boom")
        self._running = True

    async def stop(self) -> None:
        if self._slow:
            await asyncio.sleep(0.1)
        if self._fail:
            raise RuntimeError("boom")
        self._running = False


def _app_with(mgr: ServiceManager) -> TestClient:
    from app.api.endpoints import services as services_endpoint
    # Swap the singleton the endpoint module references.
    services_endpoint.service_manager = mgr  # type: ignore[assignment]
    app = FastAPI()
    app.include_router(services_endpoint.router)
    return TestClient(app)


def _seed(ctrl: _FakeCtrl) -> ServiceManager:
    mgr = ServiceManager(registry_path=Path("/tmp/never"))
    mgr._controllers[ctrl.name] = ctrl
    mgr._locks[ctrl.name] = asyncio.Lock()
    return mgr


def test_list_services_returns_states():
    ctrl = _FakeCtrl(running=True)
    client = _app_with(_seed(ctrl))
    r = client.get("/api/services")
    assert r.status_code == 200
    body = r.json()
    assert len(body["services"]) == 1
    row = body["services"][0]
    assert row["name"] == "fake"
    assert row["running"] is True
    assert row["transitioning"] is False
    assert row["kind"] == "internal"


def test_start_returns_202_for_stopped_service():
    ctrl = _FakeCtrl(running=False)
    client = _app_with(_seed(ctrl))
    r = client.post("/api/services/fake/start")
    assert r.status_code == 202
    body = r.json()
    assert body["name"] == "fake"
    assert body["action"] == "start"
    assert body["transitioning"] is True


def test_start_returns_404_for_unknown_service():
    client = _app_with(_seed(_FakeCtrl()))
    r = client.post("/api/services/nope/start")
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "service_not_found"


def test_start_returns_409_when_already_running():
    ctrl = _FakeCtrl(running=True)
    client = _app_with(_seed(ctrl))
    # First call schedules the start, which sees running=True inside the
    # bg task and records "already running" but returns 202 from the API.
    # That's a corner case — the synchronous-side check only fails on
    # "already transitioning". To exercise 409, hold the transitioning
    # slot manually.
    mgr = _seed(ctrl)
    mgr._transitioning.add("fake")
    client2 = _app_with(mgr)
    r = client2.post("/api/services/fake/start")
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "conflict"


def test_stop_returns_202_for_running_service():
    ctrl = _FakeCtrl(running=True)
    client = _app_with(_seed(ctrl))
    r = client.post("/api/services/fake/stop")
    assert r.status_code == 202
    assert r.json()["action"] == "stop"


def test_stop_returns_404_for_unknown_service():
    client = _app_with(_seed(_FakeCtrl()))
    r = client.post("/api/services/nope/stop")
    assert r.status_code == 404
