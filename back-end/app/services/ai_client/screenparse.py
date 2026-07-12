"""ScreenParse gRPC client — captures parsed into numbered UI elements."""
from __future__ import annotations

import base64

import grpc
from pydantic import BaseModel

from app.core.config import settings
from app.services.ai_client._pb import screenparse_pb2, screenparse_pb2_grpc
from app.services.ai_client.channel import ai_channel


class ScreenParseUnavailable(RuntimeError):
    """Raised when shore-ai-service ScreenParse is unreachable or unhealthy."""


_GRACEFUL_CODES = {
    grpc.StatusCode.UNAVAILABLE,
    grpc.StatusCode.DEADLINE_EXCEEDED,
    grpc.StatusCode.RESOURCE_EXHAUSTED,
    grpc.StatusCode.UNAUTHENTICATED,
    grpc.StatusCode.PERMISSION_DENIED,
}


class ParsedElement(BaseModel):
    id: int
    type: str
    content: str
    interactable: bool
    x1: float
    y1: float
    x2: float
    y2: float

    def center(self) -> tuple[float, float]:
        """Normalized (0..1) center of the bbox."""
        return ((self.x1 + self.x2) / 2.0, (self.y1 + self.y2) / 2.0)


class ParsedScreen(BaseModel):
    elements: list[ParsedElement]
    som_image_b64: str  # base64 JPEG (no data: prefix)
    width: int
    height: int
    latency_ms: float


class ScreenParseClient:
    def __init__(self, stub=None):
        self._stub = stub

    def _get_stub(self):
        if self._stub is None:
            self._stub = screenparse_pb2_grpc.ScreenParseStub(ai_channel())
        return self._stub

    async def parse(self, image_bytes: bytes) -> ParsedScreen:
        req = screenparse_pb2.ParseRequest(image=image_bytes)
        try:
            resp = await self._get_stub().Parse(
                req, timeout=settings.SHORE_AI_SCREENPARSE_TIMEOUT_SECONDS,
            )
        except grpc.aio.AioRpcError as e:
            if e.code() in _GRACEFUL_CODES:
                raise ScreenParseUnavailable(
                    str(e.details() or e.code().name)
                ) from e
            raise
        return ParsedScreen(
            elements=[
                ParsedElement(
                    id=el.id, type=el.type, content=el.content,
                    interactable=el.interactable,
                    x1=el.x1, y1=el.y1, x2=el.x2, y2=el.y2,
                )
                for el in resp.elements
            ],
            som_image_b64=base64.b64encode(resp.som_image_jpeg).decode("ascii"),
            width=resp.width, height=resp.height, latency_ms=resp.latency_ms,
        )


screenparse_client = ScreenParseClient()
