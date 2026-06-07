import grpc
import pytest

from shore_ai.auth import BearerInterceptor


class _Ctx:
    def __init__(self): self.aborted = None
    def abort(self, code, msg): self.aborted = (code, msg); raise grpc.RpcError(msg)


def _handler_call_details(metadata):
    class D:
        invocation_metadata = metadata
    return D()


@pytest.mark.asyncio
async def test_rejects_missing_token():
    interceptor = BearerInterceptor(expected_token="secret")
    called = []

    async def _continuation(details):
        called.append(details)
        return "passthrough"

    out = await interceptor.intercept_service(_continuation, _handler_call_details(()))
    # The interceptor returns a sentinel handler that aborts with UNAUTHENTICATED
    assert callable(getattr(out, "unary_unary", None)) or out == "rejected"


@pytest.mark.asyncio
async def test_accepts_correct_token():
    interceptor = BearerInterceptor(expected_token="secret")
    async def _continuation(details): return "ok"
    out = await interceptor.intercept_service(
        _continuation,
        _handler_call_details((("authorization", "Bearer secret"),)),
    )
    assert out == "ok"
