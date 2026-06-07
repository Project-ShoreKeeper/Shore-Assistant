from __future__ import annotations

from typing import Mapping, Tuple

from shore_ai._pb import health_pb2, health_pb2_grpc


class HealthHandler(health_pb2_grpc.HealthServicer):
    def __init__(self, components: Mapping[str, Tuple[object, str]], version: str):
        # components: {"stt": (handler_with_.loaded(), detail_str), ...}
        self.components = components
        self.version = version

    async def Get(self, request, context):
        out = []
        all_ready = True
        for name, (handler, detail) in self.components.items():
            loaded = bool(handler.loaded())
            all_ready = all_ready and loaded
            out.append(health_pb2.ComponentStatus(name=name, loaded=loaded, detail=detail))
        return health_pb2.StatusResponse(
            ready=all_ready,
            components=out,
            version=self.version,
        )
