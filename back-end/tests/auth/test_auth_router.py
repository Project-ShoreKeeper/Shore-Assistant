"""Unit tests for /api/auth/* router."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import deps as auth_deps
from app.api.endpoints import auth as auth_router_module
from app.core.auth import SessionStore, User


@pytest.fixture
def app_with_auth(fake_redis, monkeypatch):
    store = SessionStore(redis=fake_redis, ttl_seconds=60, key_prefix="t:")
    monkeypatch.setattr(auth_deps, "_session_store", store)
    monkeypatch.setattr(auth_router_module, "_session_store", store)
    monkeypatch.setattr(auth_deps.settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_deps.settings, "AUTH_COOKIE_NAME", "shore_session")
    monkeypatch.setattr(auth_deps.settings, "AUTH_COOKIE_SECURE", False)
    monkeypatch.setattr(auth_deps.settings, "AUTH_COOKIE_SAMESITE", "lax")
    monkeypatch.setattr(
        auth_deps.settings, "AUTH_ALLOWED_EMAILS",
        "luna@x.com, bob@y.com",
    )
    monkeypatch.setattr(
        auth_deps.settings, "AUTH_OAUTH_REDIRECT_URL",
        "http://testserver/api/auth/callback",
    )
    monkeypatch.setattr(auth_deps.settings, "AUTH_GOOGLE_CLIENT_ID", "client_x")
    monkeypatch.setattr(auth_deps.settings, "AUTH_GOOGLE_CLIENT_SECRET", "secret_x")

    app = FastAPI()
    app.include_router(auth_router_module.router)
    return app, store


async def test_me_401_without_session(app_with_auth):
    app, _ = app_with_auth
    client = TestClient(app)
    r = client.get("/api/auth/me")
    assert r.status_code == 401


async def test_me_returns_email_role_csrf(app_with_auth):
    app, store = app_with_auth
    sid, csrf = await store.create(User(id="s1", email="luna@x.com", role="admin"))
    client = TestClient(app)
    client.cookies.set("shore_session", sid)
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    body = r.json()
    assert body == {"email": "luna@x.com", "role": "admin", "csrf": csrf}


async def test_logout_deletes_session_and_clears_cookie(app_with_auth):
    app, store = app_with_auth
    sid, csrf = await store.create(User(id="s1", email="luna@x.com", role="admin"))
    client = TestClient(app)
    client.cookies.set("shore_session", sid)
    r = client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200
    assert await store.read(sid) is None
    set_cookie = r.headers.get("set-cookie", "")
    assert "shore_session=" in set_cookie
    assert "Max-Age=0" in set_cookie or "max-age=0" in set_cookie.lower()


async def test_callback_rejects_non_allowlisted_email(app_with_auth, monkeypatch):
    app, store = app_with_auth
    # Pre-create an OAuth state so the callback's state check passes.
    state = await store.create_oauth_state(ttl_seconds=60, prefix="t:state:")
    monkeypatch.setattr(
        auth_deps.settings, "AUTH_OAUTH_STATE_KEY_PREFIX", "t:state:",
    )

    async def fake_exchange(code: str) -> dict:
        return {"sub": "google_sub_x", "email": "stranger@evil.com"}

    monkeypatch.setattr(
        auth_router_module, "_exchange_code_for_userinfo", fake_exchange,
    )
    client = TestClient(app)
    r = client.get(
        f"/api/auth/callback?code=abc&state={state}",
        follow_redirects=False,
    )
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "not_allowlisted"
    assert r.json()["detail"]["email"] == "stranger@evil.com"


async def test_callback_invalid_state_returns_400(app_with_auth, monkeypatch):
    app, _ = app_with_auth
    monkeypatch.setattr(
        auth_deps.settings, "AUTH_OAUTH_STATE_KEY_PREFIX", "t:state:",
    )

    async def fake_exchange(code: str) -> dict:
        return {"sub": "sub", "email": "luna@x.com"}

    monkeypatch.setattr(
        auth_router_module, "_exchange_code_for_userinfo", fake_exchange,
    )
    client = TestClient(app)
    r = client.get(
        "/api/auth/callback?code=abc&state=never_issued",
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "oauth_state_invalid"


async def test_callback_happy_path_sets_cookie_and_redirects(
    app_with_auth, monkeypatch,
):
    app, store = app_with_auth
    monkeypatch.setattr(
        auth_deps.settings, "AUTH_OAUTH_STATE_KEY_PREFIX", "t:state:",
    )
    state = await store.create_oauth_state(ttl_seconds=60, prefix="t:state:")

    async def fake_exchange(code: str) -> dict:
        assert code == "abc"
        return {"sub": "google_sub_luna", "email": "luna@x.com"}

    monkeypatch.setattr(
        auth_router_module, "_exchange_code_for_userinfo", fake_exchange,
    )
    client = TestClient(app)
    r = client.get(
        f"/api/auth/callback?code=abc&state={state}",
        follow_redirects=False,
    )
    assert r.status_code in (302, 307)
    set_cookie = r.headers.get("set-cookie", "")
    assert "shore_session=" in set_cookie
    assert "HttpOnly" in set_cookie or "httponly" in set_cookie.lower()
