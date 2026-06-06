"""Tests for STT runtime_flag gating and unload()."""
import numpy as np
import pytest

from app.core import runtime_flags
from app.services.stt_service import STTService, STTDisabled


@pytest.fixture(autouse=True)
def _reset_flags():
    runtime_flags.reset_for_tests()
    runtime_flags.set("STT_ENABLED", True)
    yield
    runtime_flags.reset_for_tests()


def test_transcribe_raises_sttdisabled_when_flag_false():
    runtime_flags.set("STT_ENABLED", False)
    svc = STTService()
    with pytest.raises(STTDisabled):
        svc.transcribe(np.zeros(16000, dtype=np.float32))


def test_unload_clears_pipe_and_is_loaded():
    svc = STTService()
    # Simulate a loaded state without actually loading Whisper.
    svc.pipe = object()
    svc._is_loaded = True
    svc.unload()
    assert svc.pipe is None
    assert svc.is_loaded is False


def test_unload_is_idempotent_on_unloaded_service():
    svc = STTService()
    svc.unload()  # was never loaded
    svc.unload()
    assert svc.pipe is None
    assert svc.is_loaded is False
