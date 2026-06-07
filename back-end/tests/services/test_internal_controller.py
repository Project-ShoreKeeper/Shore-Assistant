"""Tests for InternalController — singletons mocked, runtime_flags toggled."""
import pytest

from app.core import runtime_flags
from app.services.controllers.internal import InternalController


@pytest.fixture(autouse=True)
def _reset():
    runtime_flags.reset_for_tests()
    runtime_flags.set("TTS_ENABLED", True)
    runtime_flags.set("WORKER_ENABLED", True)
    runtime_flags.set("CANONICALIZER_ENABLED", True)
    yield
    runtime_flags.reset_for_tests()


class _FakeTTS:
    def __init__(self):
        self._pipeline = None

    def load(self):
        self._pipeline = object()

    def unload(self):
        self._pipeline = None


class _FakeScheduler:
    def __init__(self):
        self.jobs: dict[str, tuple] = {}

    def has_system_job(self, job_id):
        return job_id in self.jobs

    def add_system_job(self, func, cron, job_id):
        self.jobs[job_id] = (func, cron)

    def remove_system_job(self, job_id):
        return self.jobs.pop(job_id, None) is not None


# ── TTS ──

@pytest.mark.asyncio
async def test_tts_start_loads_pipeline():
    tts = _FakeTTS()
    ctrl = InternalController("tts", display_name="TTS", target="tts", tts=tts)
    await ctrl.start()
    assert tts._pipeline is not None
    assert runtime_flags.get("TTS_ENABLED") is True


@pytest.mark.asyncio
async def test_tts_stop_unloads_pipeline():
    tts = _FakeTTS()
    tts._pipeline = object()
    ctrl = InternalController("tts", display_name="TTS", target="tts", tts=tts)
    await ctrl.stop()
    assert tts._pipeline is None
    assert runtime_flags.get("TTS_ENABLED") is False


# ── locomo_worker ──

@pytest.mark.asyncio
async def test_locomo_worker_start_sets_flag_no_other_effect():
    ctrl = InternalController(
        "locomo", display_name="LOCOMO worker", target="locomo_worker",
    )
    runtime_flags.set("WORKER_ENABLED", False)
    await ctrl.start()
    assert runtime_flags.get("WORKER_ENABLED") is True


@pytest.mark.asyncio
async def test_locomo_worker_stop_clears_flag():
    ctrl = InternalController(
        "locomo", display_name="LOCOMO worker", target="locomo_worker",
    )
    await ctrl.stop()
    assert runtime_flags.get("WORKER_ENABLED") is False


# ── canonicalizer ──

@pytest.mark.asyncio
async def test_canonicalizer_start_registers_scheduler_job():
    sched = _FakeScheduler()
    ctrl = InternalController(
        "canonicalizer", display_name="Canonicalizer", target="canonicalizer",
        scheduler=sched, canonicalizer_func=lambda: None,
        canonicalizer_cron="0 4 * * *",
    )
    await ctrl.start()
    assert sched.has_system_job("memory_canonicalizer")
    assert runtime_flags.get("CANONICALIZER_ENABLED") is True


@pytest.mark.asyncio
async def test_canonicalizer_stop_removes_job_and_clears_flag():
    sched = _FakeScheduler()
    sched.jobs["memory_canonicalizer"] = (lambda: None, "0 4 * * *")
    ctrl = InternalController(
        "canonicalizer", display_name="Canonicalizer", target="canonicalizer",
        scheduler=sched, canonicalizer_func=lambda: None,
    )
    await ctrl.stop()
    assert not sched.has_system_job("memory_canonicalizer")
    assert runtime_flags.get("CANONICALIZER_ENABLED") is False


def test_invalid_target_raises():
    with pytest.raises(ValueError):
        InternalController("x", display_name="X", target="bogus")  # type: ignore[arg-type]
