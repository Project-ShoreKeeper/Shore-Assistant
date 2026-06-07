import grpc
import numpy as np
import pytest

from shore_ai.handlers.stt import SttHandler
from shore_ai._pb import stt_pb2


@pytest.mark.asyncio
async def test_transcribe_silent_audio_returns_empty():
    handler = SttHandler(model_size="tiny", device="cpu")
    # Lazy load — wait for the background load task to finish before calling.
    await handler.start_load()
    assert handler.loaded() is True
    audio = np.zeros(16000, dtype=np.float32).tobytes()  # 1s silence
    req = stt_pb2.TranscribeRequest(audio_f32=audio, language="en")
    resp = await handler.Transcribe(req, context=None)
    assert resp.text == ""
    assert resp.language == "en"
    assert resp.model == "tiny"


@pytest.mark.asyncio
async def test_transcribe_aborts_unavailable_while_loading():
    handler = SttHandler(model_size="tiny", device="cpu")
    assert handler.loaded() is False

    aborted: list[tuple] = []

    class _Ctx:
        async def abort(self, code, msg):
            aborted.append((code, msg))
            raise grpc.RpcError(msg)

    req = stt_pb2.TranscribeRequest(
        audio_f32=np.zeros(16000, dtype=np.float32).tobytes(),
        language="en",
    )
    with pytest.raises(grpc.RpcError):
        await handler.Transcribe(req, _Ctx())
    assert aborted == [(grpc.StatusCode.UNAVAILABLE, "stt model still loading")]
