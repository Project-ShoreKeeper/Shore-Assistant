"""Unit tests for WorkerService — extractor + redis mocked."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.services.memory.types import (
    EmotionVector, EpisodicFact, Message, ProfileChange, WorkerOutput,
)
from app.services.memory.worker import WorkerService


@pytest.fixture
async def worker_with_fake_redis(fake_redis):
    w = WorkerService()
    w._redis = fake_redis
    yield w


async def test_get_last_extracted_ts_returns_zero_when_absent(worker_with_fake_redis):
    assert await worker_with_fake_redis.get_last_extracted_ts() == 0.0


async def test_set_then_get_last_extracted_ts_roundtrip(worker_with_fake_redis):
    await worker_with_fake_redis.set_last_extracted_ts(123.456)
    assert await worker_with_fake_redis.get_last_extracted_ts() == 123.456


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

    await w.extract()

    fake_facade.profile.apply_change.assert_awaited_once()
    fake_facade.episodic.upsert.assert_awaited_once()
    assert await w.get_last_extracted_ts() == 101.0


async def test_extract_skips_when_no_new_turns(worker_with_fake_redis):
    w = worker_with_fake_redis
    await w.set_last_extracted_ts(200.0)
    w._extractor = MagicMock()
    w._extractor.extract = AsyncMock()

    fake_facade = MagicMock()
    fake_facade.short_term = MagicMock()
    fake_facade.short_term.load = AsyncMock(return_value=[
        _turn(100.0, "user", "old turn"),
    ])
    w._facade = fake_facade

    await w.extract()
    w._extractor.extract.assert_not_awaited()
