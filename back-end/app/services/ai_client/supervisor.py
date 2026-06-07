"""Client for shore-ai-supervisor."""
from __future__ import annotations

from dataclasses import dataclass

import grpc

from app.services.ai_client._pb import supervisor_pb2, supervisor_pb2_grpc
from app.services.ai_client.channel import supervisor_channel


@dataclass
class SupervisorStatus:
    running: bool
    container_id: str
    state: str


class SupervisorClient:
    def __init__(self, stub=None):
        self._stub = stub

    def _get_stub(self):
        if self._stub is None:
            self._stub = supervisor_pb2_grpc.SupervisorStub(supervisor_channel())
        return self._stub

    async def start(self, target: str) -> None:
        await self._get_stub().Start(
            supervisor_pb2.TargetRequest(target=target),
            timeout=30.0,
        )

    async def stop(self, target: str) -> None:
        await self._get_stub().Stop(
            supervisor_pb2.TargetRequest(target=target),
            timeout=30.0,
        )

    async def status(self, target: str) -> SupervisorStatus:
        try:
            resp = await self._get_stub().Status(
                supervisor_pb2.TargetRequest(target=target),
                timeout=5.0,
            )
        except grpc.aio.AioRpcError:
            return SupervisorStatus(
                running=False,
                container_id="",
                state="unreachable",
            )
        return SupervisorStatus(
            running=resp.running,
            container_id=resp.container_id,
            state=resp.state,
        )


supervisor_client = SupervisorClient()
