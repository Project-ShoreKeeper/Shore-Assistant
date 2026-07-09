import asyncio

import pytest

from app.core.auth import current_user_role
from app.core.config import settings
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

    async def next_step(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def make_service(responses, tmp_path):
    svc = ComputerUseService(
        client=FakeClient(responses),
        request_screenshot=lambda *a, **k: _ret(TINY),
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
    assert "unavailable" in summary.lower()


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


@pytest.mark.asyncio
async def test_attach_refused_while_running(tmp_path):
    svc, _ = make_service([CLICK, DONE], tmp_path)
    original = svc.broadcast

    async def intruder(msg):
        pass

    original_resolve = svc.resolve_step

    def resolve_and_intrude(request_id, **kwargs):
        assert svc.attach(intruder) is False
        assert svc.broadcast is original
        return original_resolve(request_id, **kwargs)

    svc.resolve_step = resolve_and_intrude

    await svc.run("task", max_steps=5)
    assert svc.attach(intruder) is True


@pytest.mark.asyncio
async def test_detach_wrong_owner_is_noop(tmp_path):
    svc, _ = make_service([DONE], tmp_path)

    async def other(msg):
        pass

    svc.detach(owner=other)
    assert svc.broadcast is not None and svc.ready


@pytest.mark.asyncio
async def test_abort_fails_pending_future_immediately(tmp_path):
    svc, sent = make_service([CLICK, DONE], tmp_path)

    async def broadcast_no_reply(msg):
        sent.append(msg)
        if msg.get("type") == "cua_step":
            svc.abort()

    svc.attach(broadcast_no_reply)

    summary = await asyncio.wait_for(svc.run("task", max_steps=5), timeout=5)
    assert "aborted" in summary.lower()


@pytest.mark.asyncio
async def test_resolve_step_does_not_rearm_cleared_screen(tmp_path):
    svc, _ = make_service([DONE], tmp_path)
    svc.set_ready(None)
    future = asyncio.get_running_loop().create_future()
    svc._pending["r1"] = future
    svc.resolve_step("r1", screenshot=TINY, screen=SCREEN)
    assert not svc.ready


@pytest.mark.asyncio
async def test_run_refuses_non_admin(tmp_path):
    svc, _ = make_service([DONE], tmp_path)
    token = current_user_role.set("user")
    try:
        summary = await svc.run("task", max_steps=5)
    finally:
        current_user_role.reset(token)
    assert "admin" in summary.lower()


@pytest.mark.asyncio
async def test_cua_step_carries_settle_ms(tmp_path):
    svc, sent = make_service([CLICK, DONE], tmp_path)
    await svc.run("task", max_steps=5)
    step = next(message for message in sent if message["type"] == "cua_step")
    assert step["settle_ms"] == settings.CUA_SETTLE_MS


UT_CLICK = (
    "Thought: I can see the OK button. I will click it.\n"
    "Action: click(point='<point>0.5 0.5</point>')"
)
UT_DONE = "Thought: The task is complete.\nAction: finished(content='All set')"


@pytest.mark.asyncio
async def test_run_with_ui_tars_format(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CUA_MODEL_FORMAT", "ui_tars")
    svc, sent = make_service([UT_CLICK, UT_DONE], tmp_path)
    summary = await svc.run("press ok", max_steps=5)
    steps = [message for message in sent if message["type"] == "cua_step"]
    assert len(steps) == 1
    assert steps[0]["action"] == {"func": "click", "x": 720, "y": 450}
    assert "All set" in summary and "success" in summary.lower()
    assert svc._client.calls[0]["model"] == "ui-tars-1.5-7b"
    assert svc._client.calls[0]["extra_params"] == {"frequency_penalty": 1.0}
    system = svc._client.calls[0]["messages"][0]
    assert system["role"] == "system"
    assert "## Action Space" in system["content"]
    first_user_text = svc._client.calls[0]["messages"][1]["content"][0]
    assert first_user_text["type"] == "text"
    assert first_user_text["text"].startswith("## User Instruction")


GO_CLICK = (
    "<think>Weighing the options. The obvious Action: press the button.</think>\n"
    "Thought: I will click OK.\n"
    "Action: click(point='<point>0.5 0.5</point>')"
)
GO_DONE = "Thought: The task is complete.\nAction: finished(content='All set')"


@pytest.mark.asyncio
async def test_run_with_gui_owl_strips_think_from_history(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CUA_MODEL_FORMAT", "gui_owl")
    svc, sent = make_service([GO_CLICK, GO_DONE], tmp_path)
    summary = await svc.run("press ok", max_steps=5)
    steps = [message for message in sent if message["type"] == "cua_step"]
    assert len(steps) == 1
    assert steps[0]["action"] == {"func": "click", "x": 720, "y": 450}
    assert "All set" in summary and "success" in summary.lower()
    assistant = svc._client.calls[1]["messages"][2]
    assert assistant["role"] == "assistant"
    assert "<think>" not in assistant["content"]
    assert assistant["content"].startswith("Thought: I will click OK.")


@pytest.mark.asyncio
async def test_run_with_evocua_format_sends_evocua_label(tmp_path):
    svc, _ = make_service([DONE], tmp_path)
    await svc.run("task", max_steps=3)
    assert svc._client.calls[0]["model"] == "evocua-8b"
    assert svc._client.calls[0]["extra_params"] == {}


@pytest.mark.asyncio
async def test_unknown_format_refuses(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CUA_MODEL_FORMAT", "bogus")
    svc, sent = make_service([DONE], tmp_path)
    summary = await svc.run("task", max_steps=3)
    assert "Unknown CUA_MODEL_FORMAT" in summary
    assert not [m for m in sent if m["type"] == "cua_step"]
