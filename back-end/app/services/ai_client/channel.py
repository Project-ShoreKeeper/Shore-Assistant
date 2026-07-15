"""Long-lived gRPC channels to shore-ai-service and shore-ai-supervisor."""
from __future__ import annotations

import logging
from typing import Optional

import grpc

from app.core.config import settings


log = logging.getLogger(__name__)


class BearerClientInterceptor(grpc.aio.UnaryUnaryClientInterceptor):
    def __init__(self, token: str):
        self._token = token

    async def intercept_unary_unary(
        self, continuation, client_call_details, request
    ):
        metadata = list(client_call_details.metadata or [])
        # Only inject if not already present
        if not any(k.lower() == "authorization" for k, _ in metadata):
            metadata.append(("authorization", f"Bearer {self._token}"))
        new_details = grpc.aio.ClientCallDetails(
            method=client_call_details.method,
            timeout=client_call_details.timeout,
            metadata=metadata,
            credentials=client_call_details.credentials,
            wait_for_ready=client_call_details.wait_for_ready,
        )
        return await continuation(new_details, request)


_ai_channel: Optional[grpc.aio.Channel] = None
_supervisor_channel: Optional[grpc.aio.Channel] = None


def _build_channel(target: str, token: str, use_tls: bool) -> grpc.aio.Channel:
    interceptors = [BearerClientInterceptor(token)] if token else []
    options = [
        ("grpc.keepalive_time_ms", 20000),
        ("grpc.keepalive_timeout_ms", 10000),
        ("grpc.keepalive_permit_without_calls", 1),
    ]
    if use_tls:
        return grpc.aio.secure_channel(
            target,
            grpc.ssl_channel_credentials(),
            options=options,
            interceptors=interceptors,
        )
    return grpc.aio.insecure_channel(
        target,
        options=options,
        interceptors=interceptors,
    )


def init() -> None:
    global _ai_channel, _supervisor_channel
    if _ai_channel is None:
        _ai_channel = _build_channel(
            settings.SHORE_AI_GRPC_URL,
            settings.SHORE_AI_TOKEN,
            use_tls=settings.SHORE_AI_USE_TLS,
        )
        log.info("ai_client: connected channel to %s", settings.SHORE_AI_GRPC_URL)
    if _supervisor_channel is None:
        _supervisor_channel = _build_channel(
            settings.SHORE_AI_SUPERVISOR_GRPC_URL,
            settings.SHORE_AI_TOKEN,
            use_tls=settings.SHORE_AI_USE_TLS,
        )
        log.info(
            "ai_client: connected supervisor channel to %s",
            settings.SHORE_AI_SUPERVISOR_GRPC_URL,
        )


async def close() -> None:
    global _ai_channel, _supervisor_channel
    if _ai_channel is not None:
        await _ai_channel.close()
        _ai_channel = None
    if _supervisor_channel is not None:
        await _supervisor_channel.close()
        _supervisor_channel = None


def ai_channel() -> grpc.aio.Channel:
    if _ai_channel is None:
        init()
    return _ai_channel  # type: ignore[return-value]


def supervisor_channel() -> grpc.aio.Channel:
    if _supervisor_channel is None:
        init()
    return _supervisor_channel  # type: ignore[return-value]
