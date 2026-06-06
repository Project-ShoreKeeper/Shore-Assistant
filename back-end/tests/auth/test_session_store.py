"""Unit tests for the Redis-backed session store."""

import pytest

from app.core.auth import SessionStore, User


def _user(email: str = "luna@example.com", role: str = "admin") -> User:
    return User(id=f"sub_{email}", email=email, role=role)


async def test_create_session_returns_sid_and_csrf(fake_redis):
    store = SessionStore(redis=fake_redis, ttl_seconds=60, key_prefix="t:")
    sid, csrf = await store.create(_user())
    assert isinstance(sid, str) and len(sid) >= 32
    assert isinstance(csrf, str) and len(csrf) >= 32
    assert sid != csrf


async def test_read_session_returns_user_and_csrf(fake_redis):
    store = SessionStore(redis=fake_redis, ttl_seconds=60, key_prefix="t:")
    user = _user()
    sid, csrf = await store.create(user)
    session = await store.read(sid)
    assert session is not None
    assert session.user.id == user.id
    assert session.user.email == user.email
    assert session.user.role == user.role
    assert session.csrf == csrf


async def test_read_missing_session_returns_none(fake_redis):
    store = SessionStore(redis=fake_redis, ttl_seconds=60, key_prefix="t:")
    assert await store.read("no-such-sid") is None


async def test_read_refreshes_sliding_ttl(fake_redis):
    store = SessionStore(redis=fake_redis, ttl_seconds=60, key_prefix="t:")
    sid, _ = await store.create(_user())
    # Manually shrink TTL, then read — read should bump it back to 60.
    await fake_redis.expire(f"t:{sid}", 5)
    ttl_before = await fake_redis.ttl(f"t:{sid}")
    assert ttl_before <= 5
    await store.read(sid)
    ttl_after = await fake_redis.ttl(f"t:{sid}")
    assert ttl_after > 50


async def test_delete_session_removes_key(fake_redis):
    store = SessionStore(redis=fake_redis, ttl_seconds=60, key_prefix="t:")
    sid, _ = await store.create(_user())
    await store.delete(sid)
    assert await store.read(sid) is None


async def test_delete_unknown_sid_is_idempotent(fake_redis):
    store = SessionStore(redis=fake_redis, ttl_seconds=60, key_prefix="t:")
    await store.delete("no-such-sid")  # should not raise


async def test_oauth_state_one_shot(fake_redis):
    store = SessionStore(redis=fake_redis, ttl_seconds=60, key_prefix="t:")
    state = await store.create_oauth_state(ttl_seconds=10, prefix="s:")
    assert isinstance(state, str) and len(state) >= 32
    assert await store.consume_oauth_state(state, prefix="s:") is True
    # Second consume must fail (one-shot).
    assert await store.consume_oauth_state(state, prefix="s:") is False
