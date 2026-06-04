"""Unit tests for MemoryFacade — circuit breakers, parallelism, lifecycle."""

import asyncio
import time

import pytest
from redis.exceptions import RedisError

from app.services.memory.facade import MemoryFacade
from app.services.memory.short_term import ShortTermMemory


@pytest.fixture
async def started_facade(fake_redis, monkeypatch):
    """A MemoryFacade with short_term wired to fakeredis, profile/episodic stub."""
    monkeypatch.setattr(
        "app.core.config.settings.REDIS_SHORT_TERM_KEY",
        "test:facade:messages",
    )
    monkeypatch.setattr("app.core.config.settings.MEMORY_MAX_TURNS", 15)

    facade = MemoryFacade()
    facade._redis = fake_redis
    facade.short_term = ShortTermMemory(fake_redis)
    yield facade


async def test_assemble_context_returns_empty_when_redis_down(started_facade):
    async def boom():
        raise RedisError("connection refused")

    started_facade.short_term.load = boom
    bundle = await started_facade.assemble_context("hello")
    assert bundle.short_term == []
    assert bundle.profile == {}
    assert bundle.episodic_hits == []


async def test_assemble_context_short_term_timeout_degrades(started_facade):
    async def slow():
        await asyncio.sleep(2.0)
        return []

    started_facade.short_term.load = slow
    t0 = time.monotonic()
    bundle = await started_facade.assemble_context("hello")
    elapsed = time.monotonic() - t0
    assert elapsed < 0.7      # 0.5s circuit-breaker timeout + small slack
    assert bundle.short_term == []


async def test_assemble_context_runs_three_layers_in_parallel(started_facade):
    """All three layer calls happen concurrently."""

    async def slow_load():
        await asyncio.sleep(0.1)
        return []

    async def slow_read():
        await asyncio.sleep(0.1)
        return {}

    async def slow_search(query, **kwargs):
        await asyncio.sleep(0.1)
        return []

    started_facade.short_term.load = slow_load
    started_facade.profile.read = slow_read
    started_facade.episodic.search = slow_search

    t0 = time.monotonic()
    await started_facade.assemble_context("x")
    elapsed = time.monotonic() - t0
    # Parallel: ~0.1 s; sequential would be ~0.3 s.
    assert elapsed < 0.2


async def test_append_user_writes_through_short_term(started_facade):
    await started_facade.append_user("hi", extras={"thinking_text": "..."})
    loaded = await started_facade.short_term.load()
    assert len(loaded) == 1
    assert loaded[0].role == "user"
    assert loaded[0].content == "hi"
    assert loaded[0].extras == {"thinking_text": "..."}


async def test_append_assistant_writes_through_short_term(started_facade):
    await started_facade.append_assistant("ok", extras={"agent_actions": []})
    loaded = await started_facade.short_term.load()
    assert len(loaded) == 1
    assert loaded[0].role == "assistant"
    assert loaded[0].content == "ok"


async def test_clear_returns_false_after_double_clear(started_facade):
    await started_facade.append_user("hi")
    assert await started_facade.clear() is True
    assert await started_facade.clear() is False


async def test_append_user_no_op_when_facade_not_started():
    facade = MemoryFacade()
    # Do NOT call startup() — short_term is None.
    await facade.append_user("hi")    # must not raise


async def test_clear_returns_false_when_facade_not_started():
    facade = MemoryFacade()
    assert await facade.clear() is False
