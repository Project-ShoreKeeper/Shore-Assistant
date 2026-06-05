"""Integration test — WorkerService writes through to real Postgres + Qdrant.

Skipped unless RUN_REAL_DB_TESTS=1. Mocks Gemini so no API key is required.

Run from back-end/:
    RUN_REAL_DB_TESTS=1 pytest tests/integration/test_worker_pipeline.py -v
"""

import os
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.memory.facade import MemoryFacade
from app.services.memory.types import (
    EmotionVector, EpisodicFact, Message, ProfileChange, WorkerOutput,
)
from app.services.memory.worker import WorkerService


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_REAL_DB_TESTS") != "1",
    reason="set RUN_REAL_DB_TESTS=1 to run against the real memory stack",
)


@pytest.fixture
async def started_facade():
    facade = MemoryFacade()
    await facade.startup()
    # Clear state for a clean test
    if facade.short_term:
        await facade.short_term.clear()
    yield facade
    await facade.shutdown()


async def test_worker_extracts_and_persists(started_facade, fake_redis):
    # Use the real facade's redis for last_extracted_ts so we observe state
    redis = started_facade._redis

    # Seed two short-term turns
    now = time.time()
    await started_facade.append_user("I love espresso.")
    await started_facade.append_assistant("Noted.")

    # Wire a worker with a mocked extractor
    w = WorkerService()
    await w.startup(redis=redis, facade=started_facade)
    w._extractor = MagicMock()
    w._extractor.extract = AsyncMock(return_value=WorkerOutput(
        profile_changes=[ProfileChange(
            key_path="preferences.coffee", new_value="espresso",
            source_turn_ts=now, confidence=0.95, reason="Explicit.",
        )],
        episodic_facts=[EpisodicFact(
            fact="Luna loves espresso.",
            entity_tags=["coffee", "preferences"],
            emotion=EmotionVector(joy=0.7),
            source_turn_ts=now, source_role="user", confidence=0.95,
        )],
    ))

    await w.extract()

    profile = await started_facade.profile.read()
    assert profile.get("preferences", {}).get("coffee") == "espresso"

    hits = await started_facade.episodic.search("espresso")
    assert any("espresso" in h.fact.fact.lower() for h in hits)


async def test_worker_idempotent_across_reruns(started_facade):
    redis = started_facade._redis
    now = time.time()
    await started_facade.append_user("I drink oat milk.")
    await started_facade.append_assistant("Got it.")

    w = WorkerService()
    await w.startup(redis=redis, facade=started_facade)
    w._extractor = MagicMock()
    fact = EpisodicFact(
        fact="Luna drinks oat milk.",
        entity_tags=["coffee"],
        emotion=EmotionVector(),
        source_turn_ts=now, source_role="user", confidence=0.9,
    )
    w._extractor.extract = AsyncMock(return_value=WorkerOutput(
        profile_changes=[], episodic_facts=[fact],
    ))

    before = await started_facade.episodic.count()
    await w.extract()
    after_first = await started_facade.episodic.count()
    # Reset last_extracted_ts so the worker re-processes the same turns
    await w.set_last_extracted_ts(0.0)
    await w.extract()
    after_second = await started_facade.episodic.count()

    assert after_first - before == 1
    assert after_second == after_first  # deterministic point_id → no duplicate
