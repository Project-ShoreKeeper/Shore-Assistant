"""Unit tests for FastAPI auth dependencies."""

from unittest.mock import patch

import pytest
from fastapi import FastAPI, Depends, HTTPException
from fastapi.testclient import TestClient

from app.core.auth import SessionStore, User
from app.api import deps as auth_deps


@pytest.fixture
def app_with_store(fake_redis, monkeypatch):
    """A FastAPI app whose auth deps share a fresh in-memory store."""
    store = SessionStore(redis=fake_redis, ttl_seconds=60, key_prefix="t:")
    # Override the module-level accessor so the deps see our fake store.
    monkeypatch.setattr(auth_deps, "_session_store", store)
    # Force AUTH_ENABLED True for these tests (otherwise deps short-
    # circuit and return the legacy admin).
    monkeypatch.setattr(auth_deps.settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_deps.settings, "AUTH_COOKIE_NAME", "shore_session")

    app = FastAPI()

    @app.get("/me")
    async def me(user: User = Depends(auth_deps.current_user)):
        return {"id": user.id, "email": user.email, "role": user.role}

    @app.post("/write")
    async def write(
        user: User = Depends(auth_deps.current_user),
        _: None = Depends(auth_deps.csrf_check),
    ):
        return {"ok": True}

    @app.get("/admin")
    async def admin(user: User = Depends(auth_deps.require_admin)):
        return {"ok": True}

    return app, store


async def _make_session(store: SessionStore, role: str = "admin"):
    return await store.create(User(id="sub_1", email="luna@x.com", role=role))


def test_current_user_401_without_cookie(app_with_store):
    app, _ = app_with_store
    client = TestClient(app)
    r = client.get("/me")
    assert r.status_code == 401
    assert r.json()["detail"]["error"] == "unauthenticated"


def test_current_user_401_with_bad_cookie(app_with_store):
    app, _ = app_with_store
    client = TestClient(app)
    client.cookies.set("shore_session", "garbage")
    r = client.get("/me")
    assert r.status_code == 401
    assert r.json()["detail"]["error"] == "session_expired"


async def test_current_user_200_with_valid_cookie(app_with_store):
    app, store = app_with_store
    sid, _csrf = await _make_session(store)
    client = TestClient(app)
    client.cookies.set("shore_session", sid)
    r = client.get("/me")
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "luna@x.com"
    assert body["role"] == "admin"


async def test_csrf_check_403_when_header_missing(app_with_store):
    app, store = app_with_store
    sid, _csrf = await _make_session(store)
    client = TestClient(app)
    client.cookies.set("shore_session", sid)
    r = client.post("/write")
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "csrf_mismatch"


async def test_csrf_check_403_when_header_wrong(app_with_store):
    app, store = app_with_store
    sid, _csrf = await _make_session(store)
    client = TestClient(app)
    client.cookies.set("shore_session", sid)
    r = client.post("/write", headers={"X-CSRF-Token": "wrong"})
    assert r.status_code == 403


async def test_csrf_check_passes_with_correct_header(app_with_store):
    app, store = app_with_store
    sid, csrf = await _make_session(store)
    client = TestClient(app)
    client.cookies.set("shore_session", sid)
    r = client.post("/write", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200


async def test_require_admin_403_for_user_role(app_with_store):
    app, store = app_with_store
    sid, _ = await _make_session(store, role="user")
    client = TestClient(app)
    client.cookies.set("shore_session", sid)
    r = client.get("/admin")
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "forbidden"


async def test_require_admin_200_for_admin_role(app_with_store):
    app, store = app_with_store
    sid, _ = await _make_session(store, role="admin")
    client = TestClient(app)
    client.cookies.set("shore_session", sid)
    r = client.get("/admin")
    assert r.status_code == 200


def test_auth_disabled_returns_synthetic_admin(monkeypatch, fake_redis):
    """When AUTH_ENABLED=False, deps short-circuit to a legacy admin user."""
    store = SessionStore(redis=fake_redis, ttl_seconds=60, key_prefix="t:")
    monkeypatch.setattr(auth_deps, "_session_store", store)
    monkeypatch.setattr(auth_deps.settings, "AUTH_ENABLED", False)

    app = FastAPI()

    @app.get("/me")
    async def me(user: User = Depends(auth_deps.current_user)):
        return {"id": user.id, "email": user.email, "role": user.role}

    @app.post("/write")
    async def write(
        user: User = Depends(auth_deps.current_user),
        _: None = Depends(auth_deps.csrf_check),
    ):
        return {"ok": True}

    @app.get("/admin")
    async def admin(user: User = Depends(auth_deps.require_admin)):
        return {"role": user.role}

    client = TestClient(app)
    r = client.get("/me")
    assert r.status_code == 200
    assert r.json()["role"] == "admin"

    # No CSRF needed either.
    r = client.post("/write")
    assert r.status_code == 200

    r = client.get("/admin")
    assert r.status_code == 200
