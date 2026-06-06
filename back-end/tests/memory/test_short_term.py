"""Unit tests for ShortTermMemory backed by fakeredis."""

from app.services.memory.short_term import ShortTermMemory
from app.services.memory.types import Message


_USER = "user_a"


async def test_append_orders_messages_chronologically(fake_redis, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.REDIS_SHORT_TERM_KEY",
        "test:short_term",
    )
    monkeypatch.setattr("app.core.config.settings.MEMORY_MAX_TURNS", 15)

    st = ShortTermMemory(fake_redis)
    await st.append(Message(role="user", content="hi", timestamp=1.0), user_id=_USER)
    await st.append(
        Message(role="assistant", content="hello", timestamp=2.0),
        user_id=_USER,
    )

    loaded = await st.load(user_id=_USER)
    assert [m.timestamp for m in loaded] == [1.0, 2.0]
    assert [m.role for m in loaded] == ["user", "assistant"]


async def test_sliding_window_trims_at_limit(fake_redis, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.REDIS_SHORT_TERM_KEY",
        "test:short_term",
    )
    monkeypatch.setattr("app.core.config.settings.MEMORY_MAX_TURNS", 15)

    st = ShortTermMemory(fake_redis)
    for i in range(35):
        await st.append(
            Message(role="user", content=str(i), timestamp=float(i)),
            user_id=_USER,
        )

    loaded = await st.load(user_id=_USER)
    assert len(loaded) == 30
    assert loaded[0].content == "5"
    assert loaded[-1].content == "34"


async def test_per_user_windows_are_isolated(fake_redis, monkeypatch):
    """User A's appends must not leak into user B's load."""
    monkeypatch.setattr(
        "app.core.config.settings.REDIS_SHORT_TERM_KEY",
        "test:short_term",
    )
    monkeypatch.setattr("app.core.config.settings.MEMORY_MAX_TURNS", 15)

    st = ShortTermMemory(fake_redis)
    await st.append(Message(role="user", content="A", timestamp=1.0), user_id="alice")
    await st.append(Message(role="user", content="B", timestamp=2.0), user_id="bob")

    alice = await st.load(user_id="alice")
    bob = await st.load(user_id="bob")

    assert len(alice) == 1 and alice[0].content == "A"
    assert len(bob) == 1 and bob[0].content == "B"


async def test_extras_round_trip(fake_redis, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.REDIS_SHORT_TERM_KEY",
        "test:short_term",
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
    await st.append(
        Message(role="assistant", content="Done.", timestamp=1.0, extras=extras),
        user_id=_USER,
    )
    loaded = await st.load(user_id=_USER)
    assert loaded[0].extras == extras


async def test_clear_deletes_only_target_user_key(fake_redis, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.REDIS_SHORT_TERM_KEY",
        "test:short_term",
    )
    monkeypatch.setattr("app.core.config.settings.MEMORY_MAX_TURNS", 15)

    st = ShortTermMemory(fake_redis)
    await st.append(Message(role="user", content="A", timestamp=1.0), user_id="alice")
    await st.append(Message(role="user", content="B", timestamp=1.0), user_id="bob")

    assert await st.clear(user_id="alice") is True
    assert await st.load(user_id="alice") == []
    assert len(await st.load(user_id="bob")) == 1

    assert await st.clear(user_id="alice") is False  # idempotent


async def test_health_ok_when_reachable(fake_redis, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.REDIS_SHORT_TERM_KEY",
        "test:short_term",
    )
    monkeypatch.setattr("app.core.config.settings.MEMORY_MAX_TURNS", 15)
    assert await ShortTermMemory(fake_redis).health() is True
