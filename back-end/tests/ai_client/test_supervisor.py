import pytest

from app.services.ai_client._pb import supervisor_pb2
from app.services.ai_client.supervisor import SupervisorClient


class _Stub:
    def __init__(self):
        self.calls = []

    async def Start(self, req, timeout=None):
        self.calls.append(("start", req.target))
        return supervisor_pb2.ActionResponse(ok=True, detail="started")

    async def Stop(self, req, timeout=None):
        self.calls.append(("stop", req.target))
        return supervisor_pb2.ActionResponse(ok=True, detail="stopped")

    async def Status(self, req, timeout=None):
        self.calls.append(("status", req.target))
        return supervisor_pb2.StatusResponse(
            running=True,
            container_id="cid",
            state="running",
        )


@pytest.mark.asyncio
async def test_supervisor_status_returns_dataclass_like_object():
    stub = _Stub()
    client = SupervisorClient(stub=stub)
    st = await client.status("shore-ai")
    assert st.running is True
    assert st.container_id == "cid"
    assert stub.calls == [("status", "shore-ai")]


@pytest.mark.asyncio
async def test_supervisor_start_stop():
    stub = _Stub()
    client = SupervisorClient(stub=stub)
    await client.start("shore-ai")
    await client.stop("shore-ai")
    assert stub.calls == [("start", "shore-ai"), ("stop", "shore-ai")]
