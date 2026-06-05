"""Unit tests for WorkerService — extractor + redis mocked."""

import pytest

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
