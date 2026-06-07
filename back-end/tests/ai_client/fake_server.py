"""In-process FakeShoreAiServer for backend integration tests."""
from __future__ import annotations

from typing import AsyncIterator

import grpc

from app.services.ai_client._pb import (
    embed_pb2,
    embed_pb2_grpc,
    health_pb2,
    health_pb2_grpc,
    stt_pb2,
    stt_pb2_grpc,
    tts_pb2,
    tts_pb2_grpc,
)


class _Stt(stt_pb2_grpc.STTServicer):
    def __init__(self, text: str = "stub"):
        self.text = text

    async def Transcribe(self, request, context):
        return stt_pb2.TranscribeResponse(
            text=self.text,
            language=request.language or "en",
            language_prob=1.0,
            model="fake",
        )


class _Tts(tts_pb2_grpc.TTSServicer):
    async def Synthesize(
        self,
        request,
        context,
    ) -> AsyncIterator[tts_pb2.SynthesizeChunk]:
        blobs = [b"\x01" * 32, b"\x02" * 32, b"\x03" * 32]
        for i, blob in enumerate(blobs):
            yield tts_pb2.SynthesizeChunk(
                pcm_s16le=blob,
                is_last=(i == len(blobs) - 1),
            )


class _Embed(embed_pb2_grpc.EmbedServicer):
    async def Encode(self, request, context):
        return embed_pb2.EncodeResponse(
            vectors=[
                embed_pb2.Vector(values=[float(len(text))] * 4)
                for text in request.texts
            ],
            dim=4,
            model="fake",
        )


class _Health(health_pb2_grpc.HealthServicer):
    async def Get(self, request, context):
        return health_pb2.StatusResponse(ready=True, version="fake")


class FakeShoreAiServer:
    """Async context manager that boots a real gRPC server on localhost:0."""

    def __init__(self):
        self._server = None
        self.address = ""

    async def __aenter__(self):
        self._server = grpc.aio.server()
        stt_pb2_grpc.add_STTServicer_to_server(_Stt(), self._server)
        tts_pb2_grpc.add_TTSServicer_to_server(_Tts(), self._server)
        embed_pb2_grpc.add_EmbedServicer_to_server(_Embed(), self._server)
        health_pb2_grpc.add_HealthServicer_to_server(_Health(), self._server)
        port = self._server.add_insecure_port("127.0.0.1:0")
        await self._server.start()
        self.address = f"127.0.0.1:{port}"
        return self

    async def __aexit__(self, *exc):
        if self._server is not None:
            await self._server.stop(grace=0)
