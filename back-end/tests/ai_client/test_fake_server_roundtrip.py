import grpc
import numpy as np
import pytest

from app.services.ai_client._pb import embed_pb2_grpc, stt_pb2_grpc, tts_pb2_grpc
from app.services.ai_client.embed import EmbedClient
from app.services.ai_client.stt import SttClient
from app.services.ai_client.tts import TtsClient
from tests.ai_client.fake_server import FakeShoreAiServer


@pytest.mark.asyncio
async def test_end_to_end_stt_via_fake_server():
    async with FakeShoreAiServer() as srv:
        ch = grpc.aio.insecure_channel(srv.address)
        try:
            client = SttClient(stub=stt_pb2_grpc.STTStub(ch))
            out = await client.transcribe(
                np.zeros(16000, dtype=np.float32),
                language="en",
            )
            assert out["text"] == "stub"
        finally:
            await ch.close()


@pytest.mark.asyncio
async def test_end_to_end_embed_via_fake_server():
    async with FakeShoreAiServer() as srv:
        ch = grpc.aio.insecure_channel(srv.address)
        try:
            client = EmbedClient(stub=embed_pb2_grpc.EmbedStub(ch))
            out = await client.encode(["hello", "world!"])
            assert out == [[5.0] * 4, [6.0] * 4]
        finally:
            await ch.close()


@pytest.mark.asyncio
async def test_end_to_end_tts_streams_three_chunks():
    async with FakeShoreAiServer() as srv:
        ch = grpc.aio.insecure_channel(srv.address)
        try:
            client = TtsClient(stub=tts_pb2_grpc.TTSStub(ch))
            out = [c async for c in client.stream_pcm(text="hi", voice="af_heart")]
            assert len(out) == 3
        finally:
            await ch.close()
