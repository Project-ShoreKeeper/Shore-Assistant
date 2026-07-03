import pytest

from app.services.cua.client import CuaUnavailable
from app.services.cua.service import ComputerUseService

SCREEN = {"width": 1440, "height": 900}
TINY = (
    "data:image/jpeg;base64,"
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0a"
    "HBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAABAAAAAAAA"
    "AAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AVN//2Q=="
)


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def next_step(self, messages):
        self.calls.append(messages)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def make_service(responses, tmp_path):
    svc = ComputerUseService(
        client=FakeClient(responses),
        request_screenshot=lambda: _ret(TINY),
        audit_path=str(tmp_path / "audit.log"),
    )
    sent = []

    async def broadcast(msg):
        sent.append(msg)
        if msg.get("type") == "cua_step":
            svc.resolve_step(msg["request_id"], screenshot=TINY, screen=SCREEN)

    svc.attach(broadcast)
    svc.set_ready(SCREEN)
    return svc, sent


async def _ret(value):
    return value


CLICK = (
    "## Action:\nClick OK\n## Code:\n"
    "```python\npyautogui.click(x=0.5, y=0.5)\n```"
)
DONE = (
    "## Action:\nDone\n## Code:\n"
    '```code\ncomputer.terminate(status="success", answer="All set")\n```'
)


@pytest.mark.asyncio
async def test_run_executes_then_finishes(tmp_path):
    svc, sent = make_service([CLICK, DONE], tmp_path)
    summary = await svc.run("press ok", max_steps=5)
    steps = [message for message in sent if message["type"] == "cua_step"]
    assert len(steps) == 1
    assert steps[0]["action"] == {"func": "click", "x": 720, "y": 450}
    assert "All set" in summary and "success" in summary.lower()
    assert not svc.running


@pytest.mark.asyncio
async def test_step_limit_aborts(tmp_path):
    svc, sent = make_service([CLICK] * 5, tmp_path)
    summary = await svc.run("loop forever", max_steps=2)
    assert "step limit" in summary.lower()
    assert len([message for message in sent if message["type"] == "cua_step"]) == 2


@pytest.mark.asyncio
async def test_abort_stops_before_next_dispatch(tmp_path):
    svc, sent = make_service([CLICK, CLICK, DONE], tmp_path)

    original = svc.resolve_step

    def resolve_and_abort(request_id, **kwargs):
        svc.abort()
        return original(request_id, **kwargs)

    svc.resolve_step = resolve_and_abort

    summary = await svc.run("task", max_steps=5)
    assert "aborted" in summary.lower()
    assert len([message for message in sent if message["type"] == "cua_step"]) == 1


@pytest.mark.asyncio
async def test_parse_failure_aborts_with_error(tmp_path):
    svc, _ = make_service(["no code block at all"], tmp_path)
    summary = await svc.run("task", max_steps=3)
    assert "parse" in summary.lower()


@pytest.mark.asyncio
async def test_cua_unavailable_returns_error_summary(tmp_path):
    svc, _ = make_service([CuaUnavailable("down")], tmp_path)
    summary = await svc.run("task", max_steps=3)
    assert "EvoCUA" in summary


@pytest.mark.asyncio
async def test_not_ready_refuses(tmp_path):
    svc, _ = make_service([DONE], tmp_path)
    svc.set_ready(None)
    summary = await svc.run("task", max_steps=3)
    assert "desktop" in summary.lower()


@pytest.mark.asyncio
async def test_audit_log_written(tmp_path):
    svc, _ = make_service([CLICK, DONE], tmp_path)
    await svc.run("press ok", max_steps=5)
    content = (tmp_path / "audit.log").read_text()
    assert '"func": "click"' in content
