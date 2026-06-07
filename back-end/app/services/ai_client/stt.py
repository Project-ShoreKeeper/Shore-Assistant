"""STT gRPC client. Lives in backend, talks to shore-ai-service.STT."""
from __future__ import annotations

from typing import Optional

import grpc
import numpy as np

from app.core.config import settings
from app.services.ai_client._pb import stt_pb2, stt_pb2_grpc
from app.services.ai_client.channel import ai_channel


class SttUnavailable(RuntimeError):
    """Raised when shore-ai-service is unreachable or unhealthy."""


_GRACEFUL_CODES = {
    grpc.StatusCode.UNAVAILABLE,
    grpc.StatusCode.DEADLINE_EXCEEDED,
    grpc.StatusCode.RESOURCE_EXHAUSTED,
}


class SttClient:
    def __init__(self, stub=None):
        self._stub = stub

    def _get_stub(self):
        if self._stub is None:
            self._stub = stt_pb2_grpc.STTStub(ai_channel())
        return self._stub

    async def transcribe(
        self,
        audio: np.ndarray,
        language: str = "en",
        model_size: Optional[str] = None,
    ) -> dict:
        req = stt_pb2.TranscribeRequest(
            audio_f32=audio.astype(np.float32, copy=False).tobytes(),
            language=language,
            model_size=model_size or "",
        )
        try:
            resp = await self._get_stub().Transcribe(
                req,
                timeout=settings.SHORE_AI_TIMEOUT_SECONDS,
            )
        except grpc.aio.AioRpcError as e:
            if e.code() in _GRACEFUL_CODES:
                raise SttUnavailable(str(e.details() or e.code().name)) from e
            raise
        return {
            "text": resp.text,
            "language": resp.language,
            "language_prob": resp.language_prob,
            "segments": [
                {"start": s.start, "end": s.end, "text": s.text}
                for s in resp.segments
            ],
            "model": resp.model,
        }


stt_client = SttClient()
