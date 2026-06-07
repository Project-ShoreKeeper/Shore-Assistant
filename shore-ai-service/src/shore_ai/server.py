"""Bootstrap the shore-ai gRPC server."""
from __future__ import annotations

import asyncio
import logging
import os

import grpc

from shore_ai import __version__
from shore_ai.auth import BearerInterceptor
from shore_ai.handlers.stt import SttHandler
from shore_ai.handlers.tts import TtsHandler
from shore_ai.handlers.embed import EmbedHandler
from shore_ai.handlers.health import HealthHandler
from shore_ai._pb import (
    stt_pb2_grpc, tts_pb2_grpc, embed_pb2_grpc, health_pb2_grpc,
)


log = logging.getLogger("shore_ai.server")


async def serve() -> None:
    bind  = os.environ.get("SHORE_AI_BIND", "0.0.0.0:9200")
    token = os.environ["SHORE_AI_TOKEN"]
    model_size = os.environ.get("SHORE_AI_STT_MODEL", "base")
    embed_model = os.environ.get("SHORE_AI_EMBED_MODEL", "all-MiniLM-L6-v2")

    stt   = SttHandler(model_size=model_size)
    tts   = TtsHandler()
    embed = EmbedHandler(model_name=embed_model)
    health = HealthHandler(
        components={
            "stt":   (stt,   stt.model_size),
            "tts":   (tts,   "af_heart"),
            "embed": (embed, embed.model_name),
        },
        version=__version__,
    )

    server = grpc.aio.server(interceptors=[BearerInterceptor(token)])
    stt_pb2_grpc.add_STTServicer_to_server(stt, server)
    tts_pb2_grpc.add_TTSServicer_to_server(tts, server)
    embed_pb2_grpc.add_EmbedServicer_to_server(embed, server)
    health_pb2_grpc.add_HealthServicer_to_server(health, server)
    server.add_insecure_port(bind)
    await server.start()
    log.info("shore-ai-service listening on %s", bind)

    # Kick off heavy model load in the background so the gRPC port is
    # immediately reachable. Health.Get reflects loaded() state per
    # component, so the Dashboard can show "loading" without the client
    # hitting raw connection errors.
    stt.start_load()

    await server.wait_for_termination()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    asyncio.run(serve())


if __name__ == "__main__":
    main()
