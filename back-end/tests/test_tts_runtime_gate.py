"""Tests for TTS runtime_flag gating and unload()."""
import pytest

from app.core import runtime_flags
from app.services.tts_service import TTSService


@pytest.fixture(autouse=True)
def _reset_flags():
    runtime_flags.reset_for_tests()
    runtime_flags.set("TTS_ENABLED", True)
    yield
    runtime_flags.reset_for_tests()


@pytest.mark.asyncio
async def test_synthesize_returns_empty_when_flag_false(monkeypatch):
    runtime_flags.set("TTS_ENABLED", False)
    svc = TTSService()
    # Mark service as available so we exercise the runtime_flag branch
    # (not the kokoro-not-installed branch).
    svc._available = True

    chunks = [c async for c in svc.synthesize_stream_pcm("hello world")]
    assert chunks == []


@pytest.mark.asyncio
async def test_synthesize_returns_empty_when_kokoro_unavailable():
    svc = TTSService()
    svc._available = False
    chunks = [c async for c in svc.synthesize_stream_pcm("hello")]
    assert chunks == []


def test_unload_clears_pipeline():
    svc = TTSService()
    svc._pipeline = object()
    svc.unload()
    assert svc._pipeline is None


def test_unload_is_idempotent_when_never_loaded():
    svc = TTSService()
    svc.unload()
    svc.unload()
    assert svc._pipeline is None
