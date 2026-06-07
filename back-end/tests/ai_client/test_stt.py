import grpc
import numpy as np
import pytest

from app.services.ai_client._pb import stt_pb2
from app.services.ai_client.stt import SttClient, SttUnavailable


class _FakeRpcError(grpc.aio.AioRpcError):
    def __init__(self, code):
        self._code = code

    def code(self):
        return self._code

    def details(self):
        return "boom"


class _FakeStub:
    def __init__(self, response=None, error_code=None):
        self._resp = response
        self._err = error_code

    async def Transcribe(self, request, timeout=None, metadata=None):
        if self._err is not None:
            raise _FakeRpcError(self._err)
        return self._resp


@pytest.mark.asyncio
async def test_transcribe_returns_dict():
    fake_resp = stt_pb2.TranscribeResponse(
        text="hello",
        language="en",
        language_prob=1.0,
        model="base",
    )
    client = SttClient(stub=_FakeStub(response=fake_resp))
    audio = np.zeros(16000, dtype=np.float32)
    result = await client.transcribe(audio=audio, language="en")
    assert result == {
        "text": "hello",
        "language": "en",
        "language_prob": 1.0,
        "segments": [],
        "model": "base",
    }


@pytest.mark.asyncio
async def test_transcribe_unavailable_raises_typed_error():
    client = SttClient(stub=_FakeStub(error_code=grpc.StatusCode.UNAVAILABLE))
    audio = np.zeros(16000, dtype=np.float32)
    with pytest.raises(SttUnavailable):
        await client.transcribe(audio=audio, language="en")
