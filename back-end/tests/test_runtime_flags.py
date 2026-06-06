"""Tests for app.core.runtime_flags."""
import pytest

from app.core import runtime_flags
from app.core.config import settings


@pytest.fixture(autouse=True)
def _reset():
    runtime_flags.reset_for_tests()
    yield
    runtime_flags.reset_for_tests()


def test_initial_values_match_settings():
    assert runtime_flags.get("WORKER_ENABLED") == settings.WORKER_ENABLED
    assert runtime_flags.get("CANONICALIZER_ENABLED") == settings.CANONICALIZER_ENABLED
    assert runtime_flags.get("STT_ENABLED") == settings.STT_ENABLED
    # TTS has no settings flag — defaults to True.
    assert runtime_flags.get("TTS_ENABLED") is True


def test_set_then_get_round_trips():
    runtime_flags.set("WORKER_ENABLED", False)
    assert runtime_flags.get("WORKER_ENABLED") is False
    runtime_flags.set("WORKER_ENABLED", True)
    assert runtime_flags.get("WORKER_ENABLED") is True


def test_set_unmanaged_key_raises():
    with pytest.raises(KeyError):
        runtime_flags.set("AUTH_ENABLED", False)


def test_get_unknown_key_raises():
    with pytest.raises(KeyError):
        runtime_flags.get("NONEXISTENT_FLAG")


def test_snapshot_returns_copy():
    snap = runtime_flags.snapshot()
    snap["WORKER_ENABLED"] = "tampered"
    assert runtime_flags.get("WORKER_ENABLED") != "tampered"


def test_reset_for_tests_clears_overrides():
    runtime_flags.set("WORKER_ENABLED", False)
    runtime_flags.reset_for_tests()
    # After reset, re-reads from settings on next access.
    assert runtime_flags.get("WORKER_ENABLED") == settings.WORKER_ENABLED
