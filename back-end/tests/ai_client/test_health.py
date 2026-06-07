import grpc
import pytest

from app.services.ai_client._pb import health_pb2
from app.services.ai_client.health import HealthClient


class _FakeRpcError(grpc.aio.AioRpcError):
    def __init__(self):
        pass


class _Stub:
    def __init__(self, resp):
        self._resp = resp

    async def Get(self, request, timeout=None):
        return self._resp


@pytest.mark.asyncio
async def test_health_get_returns_dict():
    resp = health_pb2.StatusResponse(
        ready=True,
        version="0.1.0",
        components=[
            health_pb2.ComponentStatus(name="stt", loaded=True, detail="base"),
        ],
    )
    client = HealthClient(stub=_Stub(resp))
    out = await client.get()
    assert out["ready"] is True
    assert out["version"] == "0.1.0"
    assert out["components"] == [
        {"name": "stt", "loaded": True, "detail": "base"},
    ]


@pytest.mark.asyncio
async def test_health_get_returns_unhealthy_on_unavailable():
    class _Err:
        async def Get(self, request, timeout=None):
            raise _FakeRpcError()

    client = HealthClient(stub=_Err())
    out = await client.get()
    assert out["ready"] is False
    assert out["components"] == []
