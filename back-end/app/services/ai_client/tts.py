"""TTS gRPC streaming client."""
from __future__ import annotations

import asyncio
import logging
from typing import AsyncGenerator

import grpc

from app.core.config import settings
from app.services.ai_client._pb import tts_pb2, tts_pb2_grpc
from app.services.ai_client.channel import ai_channel


log = logging.getLogger(__name__)

_GRACEFUL_CODES = {
    grpc.StatusCode.UNAVAILABLE,
    grpc.StatusCode.DEADLINE_EXCEEDED,
    grpc.StatusCode.RESOURCE_EXHAUSTED,
    grpc.StatusCode.CANCELLED,
}


class TtsClient:
    def __init__(self, stub=None):
        self._stub = stub

    def _get_stub(self):
        if self._stub is None:
            self._stub = tts_pb2_grpc.TTSStub(ai_channel())
        return self._stub

    async def stream_pcm(
        self,
        text: str,
        voice: str = "",
        language: str = "en",
        chunk_size: int = 8192,
    ) -> AsyncGenerator[bytes, None]:
        req = tts_pb2.SynthesizeRequest(
            text=text,
            voice=voice,
            language=language,
            chunk_size=chunk_size,
        )
        # Two-tier deadline: a short window for the first chunk (catches
        # "service hung after accept") and the longer overall timeout for the
        # rest of the stream (long sentences can take a while on CPU Kokoro).
        # We iterate manually via __anext__ so the first-chunk timeout is
        # cleanly applied to one read, then drop into a steady-state loop.
        try:
            call = self._get_stub().Synthesize(
                req,
                timeout=settings.SHORE_AI_TIMEOUT_SECONDS,
            )
            it = call.__aiter__()
            first_deadline = settings.SHORE_AI_TTS_FIRST_CHUNK_TIMEOUT_SECONDS
            received_any = False
            while True:
                try:
                    chunk = await asyncio.wait_for(
                        it.__anext__(),
                        timeout=first_deadline if not received_any else None,
                    )
                except StopAsyncIteration:
                    return
                except asyncio.TimeoutError:
                    log.info("tts_client: first-chunk timeout, cancelling call")
                    call.cancel()
                    return
                received_any = True
                if chunk.pcm_s16le:
                    yield chunk.pcm_s16le
        except grpc.aio.AioRpcError as e:
            if e.code() in _GRACEFUL_CODES:
                log.info("tts_client: degrade (%s)", e.code().name)
                return
            raise


tts_client = TtsClient()
