"""Unit tests for ShortTermMemory backed by fakeredis."""

from app.services.memory.short_term import ShortTermMemory
from app.services.memory.types import Message


async def test_append_orders_messages_chronologically(fake_redis, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.REDIS_SHORT_TERM_KEY",
        "test:short_term:messages",
    )
    monkeypatch.setattr("app.core.config.settings.MEMORY_MAX_TURNS", 15)

    st = ShortTermMemory(fake_redis)
    await st.append(Message(role="user", content="hi", timestamp=1.0))
    await st.append(Message(role="assistant", content="hello", timestamp=2.0))

    loaded = await st.load()
    assert [m.timestamp for m in loaded] == [1.0, 2.0]
    assert [m.role for m in loaded] == ["user", "assistant"]


async def test_sliding_window_trims_at_limit(fake_redis, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.REDIS_SHORT_TERM_KEY",
        "test:short_term:trim",
    )
    monkeypatch.setattr("app.core.config.settings.MEMORY_MAX_TURNS", 15)

    st = ShortTermMemory(fake_redis)
    for i in range(35):
        await st.append(Message(role="user", content=str(i), timestamp=float(i)))

    loaded = await st.load()
    assert len(loaded) == 30
    assert loaded[0].content == "5"     # oldest kept (35-30=5)
    assert loaded[-1].content == "34"   # newest


async def test_extras_round_trip(fake_redis, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.REDIS_SHORT_TERM_KEY",
        "test:short_term:extras",
    )
    monkeypatch.setattr("app.core.config.settings.MEMORY_MAX_TURNS", 15)

    st = ShortTermMemory(fake_redis)
    extras = {
        "thinking_text": "Let me think...",
        "agent_actions": [{"tool": "x", "status": "completed"}],
        "attachments": [
            {"type": "image", "mime": "image/png", "data_b64": "iVBOR..."},
        ],
    }
    await st.append(Message(
        role="assistant", content="Done.", timestamp=1.0, extras=extras,
    ))
    loaded = await st.load()
    assert loaded[0].extras == extras


async def test_clear_deletes_key(fake_redis, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.REDIS_SHORT_TERM_KEY",
        "test:short_term:clear",
    )
    monkeypatch.setattr("app.core.config.settings.MEMORY_MAX_TURNS", 15)

    st = ShortTermMemory(fake_redis)
    await st.append(Message(role="user", content="x", timestamp=1.0))

    assert await st.clear() is True
    assert await st.load() == []
    # Idempotent
    assert await st.clear() is False


async def test_health_ok_when_reachable(fake_redis, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.REDIS_SHORT_TERM_KEY",
        "test:short_term:health",
    )
    monkeypatch.setattr("app.core.config.settings.MEMORY_MAX_TURNS", 15)
    assert await ShortTermMemory(fake_redis).health() is True
