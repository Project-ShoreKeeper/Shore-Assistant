import grpc
import pytest

from shore_ai.auth import BearerInterceptor


class _Ctx:
    def __init__(self):
        self.aborted: tuple | None = None

    async def abort(self, code, msg):
        self.aborted = (code, msg)
        raise grpc.RpcError(msg)


def _handler_call_details(metadata):
    class D:
        invocation_metadata = metadata
    return D()


@pytest.mark.asyncio
async def test_rejects_missing_token():
    interceptor = BearerInterceptor(expected_token="secret")
    continuation_calls: list = []

    async def _continuation(details):
        continuation_calls.append(details)
        return "passthrough"

    handler = await interceptor.intercept_service(
        _continuation, _handler_call_details(()),
    )
    # Continuation must NOT have been called — interceptor short-circuited.
    assert continuation_calls == []

    # The returned reject handler aborts the call with UNAUTHENTICATED when
    # invoked. Drive its unary_unary function against a mock context.
    ctx = _Ctx()
    with pytest.raises(grpc.RpcError):
        await handler.unary_unary(None, ctx)
    assert ctx.aborted == (grpc.StatusCode.UNAUTHENTICATED, "invalid bearer")


@pytest.mark.asyncio
async def test_rejects_wrong_token():
    interceptor = BearerInterceptor(expected_token="secret")

    async def _continuation(details):
        raise AssertionError("continuation must not run on wrong token")

    handler = await interceptor.intercept_service(
        _continuation,
        _handler_call_details((("authorization", "Bearer wrong"),)),
    )
    ctx = _Ctx()
    with pytest.raises(grpc.RpcError):
        await handler.unary_unary(None, ctx)
    assert ctx.aborted == (grpc.StatusCode.UNAUTHENTICATED, "invalid bearer")


@pytest.mark.asyncio
async def test_accepts_correct_token():
    interceptor = BearerInterceptor(expected_token="secret")

    async def _continuation(details):
        return "ok"

    out = await interceptor.intercept_service(
        _continuation,
        _handler_call_details((("authorization", "Bearer secret"),)),
    )
    assert out == "ok"
