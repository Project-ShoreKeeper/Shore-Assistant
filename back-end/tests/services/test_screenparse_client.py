import grpc
import pytest

from app.services.ai_client.screenparse import (
    ScreenParseClient, ScreenParseUnavailable, ParsedScreen,
)
from app.services.ai_client._pb import screenparse_pb2


class _FakeAioRpcError(grpc.aio.AioRpcError):
    def __init__(self, code):
        self._code = code

    def code(self):
        return self._code

    def details(self):
        return "boom"


class _FakeStub:
    def __init__(self, response=None, error=None):
        self._response = response
        self._error = error
        self.calls = []

    async def Parse(self, req, timeout=None):
        self.calls.append((req, timeout))
        if self._error:
            raise self._error
        return self._response


def _fake_response():
    return screenparse_pb2.ParseResponse(
        elements=[
            screenparse_pb2.Element(
                id=0, type="icon", content="settings gear",
                interactable=True, x1=0.9, y1=0.0, x2=0.95, y2=0.05,
            ),
        ],
        som_image_jpeg=b"JPEGBYTES",
        width=1920, height=1080, latency_ms=42.0,
    )


@pytest.mark.asyncio
async def test_parse_returns_parsed_screen():
    stub = _FakeStub(response=_fake_response())
    client = ScreenParseClient(stub=stub)
    result = await client.parse(b"PNGDATA")

    assert isinstance(result, ParsedScreen)
    assert result.width == 1920 and result.height == 1080
    assert len(result.elements) == 1
    el = result.elements[0]
    assert el.id == 0 and el.type == "icon" and el.content == "settings gear"
    assert el.interactable is True
    assert el.center() == pytest.approx((0.925, 0.025))
    assert result.som_image_b64  # base64 of JPEGBYTES, non-empty
    assert stub.calls[0][0].image == b"PNGDATA"


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [
    grpc.StatusCode.UNAVAILABLE,
    grpc.StatusCode.DEADLINE_EXCEEDED,
    grpc.StatusCode.RESOURCE_EXHAUSTED,
    grpc.StatusCode.UNAUTHENTICATED,
    grpc.StatusCode.PERMISSION_DENIED,
])
async def test_graceful_codes_raise_unavailable(code):
    stub = _FakeStub(error=_FakeAioRpcError(code))
    client = ScreenParseClient(stub=stub)
    with pytest.raises(ScreenParseUnavailable):
        await client.parse(b"PNGDATA")


@pytest.mark.asyncio
async def test_non_graceful_code_reraises():
    stub = _FakeStub(error=_FakeAioRpcError(grpc.StatusCode.INTERNAL))
    client = ScreenParseClient(stub=stub)
    with pytest.raises(grpc.aio.AioRpcError):
        await client.parse(b"PNGDATA")
