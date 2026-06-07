from unittest.mock import AsyncMock

import pytest

from app.services.controllers.remote import RemoteServiceController


class _Sup:
    def __init__(self, running=False):
        self.running = running
        self.start = AsyncMock()
        self.stop = AsyncMock()

    async def status(self, target):
        from app.services.ai_client.supervisor import SupervisorStatus

        return SupervisorStatus(
            running=self.running,
            container_id="cid" if self.running else "",
            state="running" if self.running else "stopped",
        )


@pytest.mark.asyncio
async def test_kind_is_remote():
    c = RemoteServiceController(
        "shore-ai",
        display_name="Shore AI",
        target="shore-ai",
        supervisor_client=_Sup(),
    )
    assert c.kind == "remote"


@pytest.mark.asyncio
async def test_is_running_reflects_supervisor_status():
    sup = _Sup(running=True)
    c = RemoteServiceController(
        "shore-ai",
        display_name="Shore AI",
        target="shore-ai",
        supervisor_client=sup,
    )
    assert await c.is_running() is True
    sup.running = False
    assert await c.is_running() is False


@pytest.mark.asyncio
async def test_start_delegates_to_supervisor():
    sup = _Sup()
    c = RemoteServiceController(
        "shore-ai",
        display_name="Shore AI",
        target="shore-ai",
        supervisor_client=sup,
    )
    await c.start()
    sup.start.assert_awaited_once_with("shore-ai")


@pytest.mark.asyncio
async def test_stop_delegates_to_supervisor():
    sup = _Sup()
    c = RemoteServiceController(
        "shore-ai",
        display_name="Shore AI",
        target="shore-ai",
        supervisor_client=sup,
    )
    await c.stop()
    sup.stop.assert_awaited_once_with("shore-ai")
