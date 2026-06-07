import numpy as np
import pytest

from shore_ai.handlers.stt import SttHandler
from shore_ai._pb import stt_pb2


@pytest.mark.asyncio
async def test_transcribe_silent_audio_returns_empty():
    handler = SttHandler(model_size="tiny", device="cpu")
    audio = np.zeros(16000, dtype=np.float32).tobytes()  # 1s silence
    req = stt_pb2.TranscribeRequest(audio_f32=audio, language="en")
    resp = await handler.Transcribe(req, context=None)
    assert resp.text == ""
    assert resp.language == "en"
    assert resp.model == "tiny"
