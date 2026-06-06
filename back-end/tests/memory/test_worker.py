"""Unit tests for WorkerService — extractor + redis mocked."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.core.config import settings
from app.services.memory.types import (
    EmotionVector, EpisodicFact, Message, ProfileChange, WorkerOutput,
)
from app.services.memory.worker import WorkerService


_U = "user_admin"


@pytest.fixture
async def worker_with_fake_redis(fake_redis):
    w = WorkerService()
    w._redis = fake_redis
    yield w


async def test_get_last_extracted_ts_returns_zero_when_absent(worker_with_fake_redis):
    assert await worker_with_fake_redis.get_last_extracted_ts(_U) == 0.0


async def test_set_then_get_last_extracted_ts_roundtrip(worker_with_fake_redis):
    await worker_with_fake_redis.set_last_extracted_ts(123.456, user_id=_U)
    assert await worker_with_fake_redis.get_last_extracted_ts(_U) == 123.456


async def test_last_ts_isolated_per_user(worker_with_fake_redis):
    await worker_with_fake_redis.set_last_extracted_ts(10.0, user_id="alice")
    await worker_with_fake_redis.set_last_extracted_ts(20.0, user_id="bob")
    assert await worker_with_fake_redis.get_last_extracted_ts("alice") == 10.0
    assert await worker_with_fake_redis.get_last_extracted_ts("bob") == 20.0


def _turn(ts: float, role: str, content: str) -> Message:
    return Message(role=role, content=content, timestamp=ts)


def _worker_output() -> WorkerOutput:
    return WorkerOutput(
        profile_changes=[ProfileChange(
            key_path="preferences.coffee", new_value="oat milk latte",
            source_turn_ts=100.0, confidence=0.95, reason="Explicit.",
        )],
        episodic_facts=[EpisodicFact(
            fact="Luna switched to oat milk.",
            entity_tags=["coffee", "preferences"],
            emotion=EmotionVector(joy=0.4),
            source_turn_ts=100.0, source_role="user", confidence=0.95,
        )],
    )


async def test_extract_applies_profile_and_episodic(worker_with_fake_redis, monkeypatch):
    w = worker_with_fake_redis
    w._extractor = MagicMock()
    w._extractor.extract = AsyncMock(return_value=_worker_output())

    fake_facade = MagicMock()
    fake_facade.short_term = MagicMock()
    fake_facade.short_term.load = AsyncMock(return_value=[
        _turn(100.0, "user", "I switched to oat milk."),
        _turn(101.0, "assistant", "Noted."),
    ])
    fake_facade.profile = MagicMock()
    fake_facade.profile.read = AsyncMock(return_value={})
    fake_facade.profile.apply_change = AsyncMock()
    fake_facade.episodic = MagicMock()
    fake_facade.episodic.upsert = AsyncMock(return_value="point-id")
    w._facade = fake_facade

    await w.extract(_U)

    fake_facade.profile.apply_change.assert_awaited_once()
    fake_facade.episodic.upsert.assert_awaited_once()
    assert await w.get_last_extracted_ts(_U) == 101.0


async def test_extract_skips_when_no_new_turns(worker_with_fake_redis):
    w = worker_with_fake_redis
    await w.set_last_extracted_ts(200.0, user_id=_U)
    w._extractor = MagicMock()
    w._extractor.extract = AsyncMock()

    fake_facade = MagicMock()
    fake_facade.short_term = MagicMock()
    fake_facade.short_term.load = AsyncMock(return_value=[
        _turn(100.0, "user", "old turn"),
    ])
    w._facade = fake_facade

    await w.extract(_U)
    w._extractor.extract.assert_not_awaited()


async def test_extract_skips_when_redis_lock_held(worker_with_fake_redis, fake_redis):
    # Pre-acquire the lock so SETNX returns False
    await fake_redis.set(
        settings.WORKER_LOCK_KEY, "other-process",
        nx=True, ex=settings.WORKER_LOCK_TTL_SECONDS,
    )
    w = worker_with_fake_redis
    w._extractor = MagicMock()
    w._extractor.extract = AsyncMock()
    fake_facade = MagicMock()
    fake_facade.short_term = MagicMock()
    fake_facade.short_term.load = AsyncMock(return_value=[
        _turn(100.0, "user", "hi"),
    ])
    w._facade = fake_facade
    await w.extract(_U)
    w._extractor.extract.assert_not_awaited()


async def test_extract_releases_lock_after_success(worker_with_fake_redis, fake_redis):
    w = worker_with_fake_redis
    w._extractor = MagicMock()
    w._extractor.extract = AsyncMock(return_value=WorkerOutput(
        profile_changes=[], episodic_facts=[],
    ))
    fake_facade = MagicMock()
    fake_facade.short_term = MagicMock()
    fake_facade.short_term.load = AsyncMock(return_value=[
        _turn(100.0, "user", "hi"),
    ])
    fake_facade.profile = MagicMock()
    fake_facade.profile.read = AsyncMock(return_value={})
    w._facade = fake_facade
    await w.extract(_U)
    assert await fake_redis.get(settings.WORKER_LOCK_KEY) is None


async def test_on_turn_completed_schedules_extract_after_delay(
    worker_with_fake_redis, monkeypatch,
):
    monkeypatch.setattr(
        "app.core.config.settings.WORKER_IDLE_DELAY_SECONDS", 0.05,
    )
    w = worker_with_fake_redis
    calls: list[str] = []

    async def fake_extract(user_id: str):
        calls.append(user_id)

    w.extract = fake_extract
    w._facade = MagicMock()
    w._facade.short_term = MagicMock()
    w._facade.short_term.load = AsyncMock(return_value=[])

    await w.on_turn_completed(user_id=_U)
    await asyncio.sleep(0.15)
    assert calls == [_U]


async def test_on_turn_completed_cancels_prior_pending(
    worker_with_fake_redis, monkeypatch,
):
    monkeypatch.setattr(
        "app.core.config.settings.WORKER_IDLE_DELAY_SECONDS", 0.2,
    )
    w = worker_with_fake_redis
    calls: list[str] = []

    async def fake_extract(user_id: str):
        calls.append(user_id)

    w.extract = fake_extract
    w._facade = MagicMock()
    w._facade.short_term = MagicMock()
    w._facade.short_term.load = AsyncMock(return_value=[])

    await w.on_turn_completed(user_id=_U)
    await asyncio.sleep(0.05)
    await w.on_turn_completed(user_id=_U)
    await asyncio.sleep(0.05)
    assert calls == []
    await asyncio.sleep(0.25)
    assert calls == [_U]


async def test_on_turn_completed_fires_immediately_at_safety_valve(
    worker_with_fake_redis, monkeypatch,
):
    monkeypatch.setattr(
        "app.core.config.settings.WORKER_IDLE_DELAY_SECONDS", 10.0,
    )
    monkeypatch.setattr(
        "app.core.config.settings.WORKER_MAX_UNPROCESSED_MESSAGES", 2,
    )
    w = worker_with_fake_redis
    calls: list[str] = []

    async def fake_extract(user_id: str):
        calls.append(user_id)

    w.extract = fake_extract
    w._facade = MagicMock()
    w._facade.short_term = MagicMock()
    w._facade.short_term.load = AsyncMock(return_value=[
        _turn(100.0, "user", "a"),
        _turn(101.0, "assistant", "b"),
        _turn(102.0, "user", "c"),
    ])
    await w.on_turn_completed(user_id=_U)
    await asyncio.sleep(0.01)
    assert calls == [_U]


async def test_startup_wires_redis_extractor_and_facade(fake_redis):
    from app.services.memory.facade import memory_facade as real_facade

    w = WorkerService()
    await w.startup(redis=fake_redis, facade=real_facade)
    assert w._redis is fake_redis
    assert w._facade is real_facade
    assert w._extractor is not None


async def test_shutdown_cancels_pending_task(worker_with_fake_redis, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.WORKER_IDLE_DELAY_SECONDS", 10.0,
    )
    w = worker_with_fake_redis
    w._facade = MagicMock()
    w._facade.short_term = MagicMock()
    w._facade.short_term.load = AsyncMock(return_value=[])

    async def slow_extract(user_id: str):
        await asyncio.sleep(10)

    w.extract = slow_extract
    await w.on_turn_completed(user_id=_U)
    assert w._pending_task is not None
    await w.shutdown()
    assert w._pending_task is None
