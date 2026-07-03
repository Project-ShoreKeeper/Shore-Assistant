"""Unit tests for CopilotService output summarization, prompt, and tick gating."""
from app.services.copilot_service import summarize_copilot_run


def _events(final_text, actions=()):
    """Build a fake agent_service.run event stream."""
    evs = []
    for a in actions:
        evs.append({"type": "agent_action", "action": "tool_call",
                    "tool": a["tool"], "args": a["args"], "timestamp": 1.0})
        evs.append({"type": "agent_action", "action": "tool_result",
                    "tool": a["tool"], "result": a["result"],
                    "status": a.get("status", "completed"), "timestamp": 2.0})
    evs.append({"type": "llm_complete", "text": final_text})
    return evs


def test_summarize_noop_no_actions_returns_none():
    assert summarize_copilot_run(_events("__NOOP__")) is None


def test_summarize_empty_no_actions_returns_none():
    assert summarize_copilot_run(_events("   ")) is None


def test_summarize_real_text_returns_message():
    out = summarize_copilot_run(_events("I ran the tests, 2 failed."))
    assert out is not None
    assert out["text"] == "I ran the tests, 2 failed."
    assert out["agent_actions"] == []


def test_summarize_collects_actions_with_results():
    out = summarize_copilot_run(_events(
        "Tests are green.",
        actions=[{"tool": "run_command",
                  "args": {"command": "pytest"},
                  "result": "2 passed"}],
    ))
    assert out is not None
    assert len(out["agent_actions"]) == 1
    act = out["agent_actions"][0]
    assert act["tool"] == "run_command"
    assert act["args"] == {"command": "pytest"}
    assert act["result"] == "2 passed"
    assert act["status"] == "completed"


def test_summarize_noop_text_but_actions_keeps_actions():
    out = summarize_copilot_run(_events(
        "__NOOP__",
        actions=[{"tool": "run_command", "args": {"command": "git status"},
                  "result": "clean"}],
    ))
    assert out is not None
    assert out["text"] == ""
    assert len(out["agent_actions"]) == 1


from app.services.copilot_service import build_copilot_prompt


def test_build_copilot_prompt_includes_title_and_noop():
    out = build_copilot_prompt("main.py - VS Code")
    assert "main.py - VS Code" in out
    assert "__NOOP__" in out


def test_build_copilot_prompt_blank_title_falls_back():
    out = build_copilot_prompt("")
    assert "__NOOP__" in out
    assert "unknown" in out


import time
import numpy as np
import pytest

from app.services.copilot_service import CopilotService


async def _noop(*args, **kwargs):
    return None


def _make_service(thumb=None, screenshot="data:image/jpeg;base64,QUJD"):
    """A CopilotService with the client-bridge calls replaced by fakes."""
    thumb = np.zeros((8, 8), dtype=np.uint8) if thumb is None else thumb

    async def fake_request_screenshot():
        return screenshot

    return CopilotService(
        decode_thumbnail=lambda data_url: thumb,
        request_screenshot=fake_request_screenshot,
    )


@pytest.mark.asyncio
async def test_handle_frame_triggers_when_all_gates_pass():
    svc = _make_service()
    fired = []

    async def rec(prompt, shot):
        fired.append((prompt, shot))

    svc.attach(trigger_cb=rec, is_busy_cb=lambda: False)
    await svc.start_session()
    assert await svc.handle_frame("thumb-data-url") is True
    assert len(fired) == 1
    prompt, shot = fired[0]
    assert "unknown" in prompt
    assert shot["data_url"] == "data:image/jpeg;base64,QUJD"
    assert svc._last_thumb is not None


@pytest.mark.asyncio
async def test_handle_frame_skips_when_session_not_active():
    svc = _make_service()
    fired = []

    async def rec(prompt, shot):
        fired.append(1)

    svc.attach(trigger_cb=rec, is_busy_cb=lambda: False)
    assert await svc.handle_frame("thumb-data-url") is False
    assert fired == []


@pytest.mark.asyncio
async def test_handle_frame_skips_when_busy():
    svc = _make_service()
    fired = []

    async def rec(prompt, shot):
        fired.append(1)

    svc.attach(trigger_cb=rec, is_busy_cb=lambda: True)
    await svc.start_session()
    assert await svc.handle_frame("thumb-data-url") is False
    assert fired == []


@pytest.mark.asyncio
async def test_handle_frame_skips_when_within_cooldown():
    svc = _make_service()
    fired = []

    async def rec(prompt, shot):
        fired.append(1)

    svc.attach(trigger_cb=rec, is_busy_cb=lambda: False)
    await svc.start_session()
    svc._last_action_ts = time.monotonic()  # just acted -> inside cooldown
    assert await svc.handle_frame("thumb-data-url") is False
    assert fired == []


def test_session_is_inactive_until_client_starts():
    svc = _make_service()
    svc.attach(trigger_cb=_noop, is_busy_cb=lambda: False)
    assert svc.active is False


@pytest.mark.asyncio
async def test_client_start_then_stop_session():
    svc = _make_service()
    svc.attach(trigger_cb=_noop, is_busy_cb=lambda: False)
    assert await svc.start_session() is True
    assert svc.active is True
    await svc.stop_session()
    assert svc.active is False
