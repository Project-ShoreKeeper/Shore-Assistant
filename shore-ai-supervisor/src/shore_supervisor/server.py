"""Bootstrap the shore-ai supervisor gRPC server."""
from __future__ import annotations

import asyncio
import hmac
import logging
import os

import grpc

from shore_supervisor.handler import SupervisorHandler
from shore_supervisor._pb import supervisor_pb2_grpc


class _Bearer(grpc.aio.ServerInterceptor):
    def __init__(self, token: str):
        self._expected_header = f"Bearer {token}"

        async def _abort(request, context):
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, "invalid bearer")

        self._reject = grpc.unary_unary_rpc_method_handler(_abort)

    async def intercept_service(self, continuation, details):
        for key, value in details.invocation_metadata or ():
            if key.lower() == "authorization" and hmac.compare_digest(
                value, self._expected_header,
            ):
                return await continuation(details)
        return self._reject


async def serve() -> None:
    bind = os.environ.get("SHORE_SUPERVISOR_BIND", "0.0.0.0:9101")
    token = os.environ["SHORE_SUPERVISOR_TOKEN"]
    compose_file = os.environ["SHORE_AI_COMPOSE_FILE"]

    server = grpc.aio.server(interceptors=[_Bearer(token)])
    supervisor_pb2_grpc.add_SupervisorServicer_to_server(
        SupervisorHandler(
            compose_file=compose_file,
            allowed_targets={"shore-ai"},
        ),
        server,
    )
    server.add_insecure_port(bind)
    await server.start()
    logging.info("shore-ai-supervisor listening on %s", bind)
    await server.wait_for_termination()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[supervisor] %(message)s")
    asyncio.run(serve())


if __name__ == "__main__":
    main()
