"""gRPC bearer-token interceptor."""
from __future__ import annotations

import hmac

import grpc


class BearerInterceptor(grpc.aio.ServerInterceptor):
    def __init__(self, expected_token: str):
        self._expected_header = f"Bearer {expected_token}"

        async def _abort(request, context):
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, "invalid bearer")

        self._reject = grpc.unary_unary_rpc_method_handler(_abort)

    async def intercept_service(self, continuation, handler_call_details):
        for key, val in handler_call_details.invocation_metadata or ():
            if key.lower() == "authorization" and hmac.compare_digest(
                val, self._expected_header,
            ):
                return await continuation(handler_call_details)
        return self._reject
