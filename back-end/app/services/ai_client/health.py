"""Health gRPC client for shore-ai-service."""
from __future__ import annotations

import grpc

from app.services.ai_client._pb import health_pb2, health_pb2_grpc
from app.services.ai_client.channel import ai_channel


class HealthClient:
    def __init__(self, stub=None):
        self._stub = stub

    def _get_stub(self):
        if self._stub is None:
            self._stub = health_pb2_grpc.HealthStub(ai_channel())
        return self._stub

    async def get(self) -> dict:
        try:
            resp = await self._get_stub().Get(health_pb2.GetRequest(), timeout=5.0)
        except grpc.aio.AioRpcError:
            return {"ready": False, "version": "", "components": []}
        return {
            "ready": resp.ready,
            "version": resp.version,
            "components": [
                {"name": c.name, "loaded": c.loaded, "detail": c.detail}
                for c in resp.components
            ],
        }


health_client = HealthClient()
