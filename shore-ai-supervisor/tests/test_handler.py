from unittest.mock import AsyncMock, patch

import pytest

from shore_supervisor.handler import SupervisorHandler
from shore_supervisor._pb import supervisor_pb2


@pytest.mark.asyncio
async def test_status_returns_running_when_container_present():
    handler = SupervisorHandler(
        compose_file="/opt/shore-ai/docker-compose.yml",
        allowed_targets={"shore-ai"},
    )
    with patch.object(handler, "_compose", AsyncMock(return_value=("abc123\n", "", 0))):
        resp = await handler.Status(
            supervisor_pb2.TargetRequest(target="shore-ai"),
            None,
        )
    assert resp.running is True
    assert resp.container_id == "abc123"


@pytest.mark.asyncio
async def test_status_returns_stopped_when_container_absent():
    handler = SupervisorHandler(
        compose_file="/opt/shore-ai/docker-compose.yml",
        allowed_targets={"shore-ai"},
    )
    with patch.object(handler, "_compose", AsyncMock(return_value=("", "", 0))):
        resp = await handler.Status(
            supervisor_pb2.TargetRequest(target="shore-ai"),
            None,
        )
    assert resp.running is False
    assert resp.container_id == ""
    assert resp.state == "stopped"


@pytest.mark.asyncio
async def test_start_falls_back_to_up_when_container_missing():
    handler = SupervisorHandler(
        compose_file="/opt/shore-ai/docker-compose.yml",
        allowed_targets={"shore-ai"},
    )
    calls = [
        ("", "no container", 1),
        ("created\n", "", 0),
    ]

    async def fake_compose(*args):
        return calls.pop(0)

    with patch.object(handler, "_compose", fake_compose):
        resp = await handler.Start(
            supervisor_pb2.TargetRequest(target="shore-ai"),
            None,
        )
    assert resp.ok is True
    assert resp.detail == "created"


@pytest.mark.asyncio
async def test_rejects_unknown_target():
    handler = SupervisorHandler(compose_file="x", allowed_targets={"shore-ai"})

    class _Ctx:
        async def abort(self, code, msg):
            raise RuntimeError(f"{code}:{msg}")

    with pytest.raises(RuntimeError):
        await handler.Start(supervisor_pb2.TargetRequest(target="evil"), _Ctx())
