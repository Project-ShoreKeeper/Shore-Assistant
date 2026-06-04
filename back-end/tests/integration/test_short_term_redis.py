"""
Integration tests — require a real Redis on localhost:6379.

Gated by SHORE_INTEGRATION_TEST=1. Each test isolates state by using
Redis DB 15 and flushdb on teardown.
"""

import os

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from app.services.memory.short_term import ShortTermMemory
from app.services.memory.types import Message


pytestmark = pytest.mark.skipif(
    os.getenv("SHORE_INTEGRATION_TEST") != "1",
    reason="Integration tests opt-in via SHORE_INTEGRATION_TEST=1",
)


@pytest_asyncio.fixture
async def real_redis():
    redis = Redis.from_url(
        "redis://localhost:6379/15", decode_responses=True,
    )
    yield redis
    await redis.flushdb()
    await redis.aclose()


async def test_basic_append_load(real_redis, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.REDIS_SHORT_TERM_KEY",
        "shore:integration:short_term",
    )
    monkeypatch.setattr("app.core.config.settings.MEMORY_MAX_TURNS", 15)

    st = ShortTermMemory(real_redis)
    await st.append(Message(role="user", content="hi", timestamp=1.0))
    await st.append(Message(role="assistant", content="hi", timestamp=2.0))

    loaded = await st.load()
    assert len(loaded) == 2
    assert loaded[0].timestamp == 1.0


async def test_window_caps_at_30_messages(real_redis, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.REDIS_SHORT_TERM_KEY",
        "shore:integration:cap",
    )
    monkeypatch.setattr("app.core.config.settings.MEMORY_MAX_TURNS", 15)

    st = ShortTermMemory(real_redis)
    for i in range(50):
        await st.append(Message(role="user", content=str(i), timestamp=float(i)))

    loaded = await st.load()
    assert len(loaded) == 30
    assert loaded[-1].content == "49"
