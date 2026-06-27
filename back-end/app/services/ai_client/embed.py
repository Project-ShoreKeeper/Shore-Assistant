"""Embedding gRPC client."""
from __future__ import annotations

from typing import Optional

import grpc

from app.core.config import settings
from app.services.ai_client._pb import embed_pb2, embed_pb2_grpc
from app.services.ai_client.channel import ai_channel


class EmbedUnavailable(RuntimeError):
    """Raised when shore-ai-service embedding is unreachable or unhealthy."""


_GRACEFUL_CODES = {
    grpc.StatusCode.UNAVAILABLE,
    grpc.StatusCode.DEADLINE_EXCEEDED,
    grpc.StatusCode.RESOURCE_EXHAUSTED,
    grpc.StatusCode.UNAUTHENTICATED,
    grpc.StatusCode.PERMISSION_DENIED,
}


class EmbedClient:
    def __init__(self, stub=None):
        self._stub = stub

    def _get_stub(self):
        if self._stub is None:
            self._stub = embed_pb2_grpc.EmbedStub(ai_channel())
        return self._stub

    async def encode(
        self,
        texts: list[str],
        model: Optional[str] = None,
    ) -> list[list[float]]:
        req = embed_pb2.EncodeRequest(texts=list(texts), model=model or "")
        try:
            resp = await self._get_stub().Encode(
                req,
                timeout=settings.SHORE_AI_EMBED_TIMEOUT_SECONDS,
            )
        except grpc.aio.AioRpcError as e:
            if e.code() in _GRACEFUL_CODES:
                raise EmbedUnavailable(str(e.details() or e.code().name)) from e
            raise
        return [list(v.values) for v in resp.vectors]


embed_client = EmbedClient()
