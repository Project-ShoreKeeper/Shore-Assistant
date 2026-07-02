import grpc
import pytest

from app.services.ai_client._pb import embed_pb2
from app.services.ai_client.embed import EmbedClient, EmbedUnavailable


class _FakeRpcError(grpc.aio.AioRpcError):
    def __init__(self, code):
        self._code = code

    def code(self):
        return self._code

    def details(self):
        return "x"


class _FakeStub:
    def __init__(self, resp=None, err=None):
        self._resp = resp
        self._err = err

    async def Encode(self, request, timeout=None):
        if self._err is not None:
            raise _FakeRpcError(self._err)
        return self._resp


@pytest.mark.asyncio
async def test_encode_returns_list_of_lists():
    fake = embed_pb2.EncodeResponse(
        vectors=[
            embed_pb2.Vector(values=[0.1, 0.2]),
            embed_pb2.Vector(values=[0.3, 0.4]),
        ],
        dim=2,
        model="all-MiniLM-L6-v2",
    )
    client = EmbedClient(stub=_FakeStub(resp=fake))
    out = await client.encode(["a", "b"])
    assert len(out) == 2
    assert out[0] == pytest.approx([0.1, 0.2])
    assert out[1] == pytest.approx([0.3, 0.4])


@pytest.mark.asyncio
async def test_encode_unavailable_raises():
    client = EmbedClient(stub=_FakeStub(err=grpc.StatusCode.UNAVAILABLE))
    with pytest.raises(EmbedUnavailable):
        await client.encode(["a"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code",
    [grpc.StatusCode.UNAUTHENTICATED, grpc.StatusCode.PERMISSION_DENIED],
)
async def test_encode_auth_failures_raise_embed_unavailable(code):
    client = EmbedClient(stub=_FakeStub(err=code))
    with pytest.raises(EmbedUnavailable):
        await client.encode(["a"])
