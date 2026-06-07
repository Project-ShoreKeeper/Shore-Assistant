import grpc
import pytest

from app.services.ai_client._pb import tts_pb2
from app.services.ai_client.tts import TtsClient


class _FakeRpcError(grpc.aio.AioRpcError):
    def __init__(self, code):
        self._code = code

    def code(self):
        return self._code


class _FakeStream:
    def __init__(self, chunks):
        self._chunks = chunks

    def __aiter__(self):
        self._i = 0
        return self

    async def __anext__(self):
        if self._i >= len(self._chunks):
            raise StopAsyncIteration
        chunk = self._chunks[self._i]
        self._i += 1
        return chunk


class _FakeStub:
    def __init__(self, chunks):
        self._chunks = chunks

    def Synthesize(self, request, timeout=None):
        return _FakeStream(self._chunks)


@pytest.mark.asyncio
async def test_stream_pcm_yields_bytes():
    chunks = [
        tts_pb2.SynthesizeChunk(pcm_s16le=b"\x01\x02", is_last=False),
        tts_pb2.SynthesizeChunk(pcm_s16le=b"\x03\x04", is_last=True),
    ]
    client = TtsClient(stub=_FakeStub(chunks))
    out = []
    async for chunk in client.stream_pcm(text="hi", voice="af_heart"):
        out.append(chunk)
    assert out == [b"\x01\x02", b"\x03\x04"]


@pytest.mark.asyncio
async def test_stream_pcm_silent_on_unavailable():
    class _ErrStub:
        def Synthesize(self, request, timeout=None):
            raise _FakeRpcError(grpc.StatusCode.UNAVAILABLE)

    client = TtsClient(stub=_ErrStub())
    out = [c async for c in client.stream_pcm(text="hi", voice="af_heart")]
    assert out == []
