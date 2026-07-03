import pytest

from app.core.auth import current_user_role
from app.services.cua.service import computer_use_service
from app.tools import ALL_TOOLS
from app.tools.computer_use_tool import computer_use


@pytest.fixture(autouse=True)
def reset_service():
    computer_use_service.set_ready({"width": 100, "height": 100})

    async def broadcast(msg):
        pass

    computer_use_service.attach(broadcast)
    yield
    computer_use_service.detach()


def test_registered():
    assert any(tool.name == "computer_use" for tool in ALL_TOOLS)


@pytest.mark.asyncio
async def test_non_admin_refused():
    token = current_user_role.set("user")
    try:
        result = await computer_use.ainvoke({"task": "open settings"})
    finally:
        current_user_role.reset(token)
    assert "admin" in result.lower()


@pytest.mark.asyncio
async def test_no_desktop_refused():
    computer_use_service.set_ready(None)
    result = await computer_use.ainvoke({"task": "open settings"})
    assert "desktop" in result.lower()


@pytest.mark.asyncio
async def test_delegates_to_service(monkeypatch):
    calls = {}

    async def fake_run(task, max_steps):
        calls["args"] = (task, max_steps)
        return "Computer-use run finished with status=success."

    monkeypatch.setattr(computer_use_service, "run", fake_run)
    result = await computer_use.ainvoke(
        {"task": "open settings", "max_steps": 3}
    )
    assert calls["args"] == ("open settings", 3)
    assert "finished" in result
