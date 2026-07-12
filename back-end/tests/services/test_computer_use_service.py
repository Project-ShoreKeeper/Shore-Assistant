import asyncio
import pytest

from app.core.config import settings
from app.services.computer_use_service import (
    ComputerUseAction, validate_action,
)
from app.services.ai_client.screenparse import ParsedElement, ParsedScreen


def _screen(n=2):
    els = [
        ParsedElement(id=i, type="icon", content=f"el{i}", interactable=True,
                      x1=0.1 * i, y1=0.1, x2=0.1 * i + 0.05, y2=0.15)
        for i in range(n)
    ]
    return ParsedScreen(elements=els, som_image_b64="", width=1920, height=1080,
                        latency_ms=1.0)


def test_action_parses_click():
    a = ComputerUseAction.model_validate(
        {"action": "click", "element_id": 1, "reason": "open menu"}
    )
    assert a.action == "click" and a.element_id == 1


def test_validate_click_ok():
    a = ComputerUseAction(action="click", element_id=1, reason="x")
    assert validate_action(a, _screen(2)) is None  # None = valid


def test_validate_click_out_of_range():
    a = ComputerUseAction(action="click", element_id=5, reason="x")
    err = validate_action(a, _screen(2))
    assert err is not None and "range" in err.lower()


def test_validate_click_missing_element():
    a = ComputerUseAction(action="click", reason="x")
    err = validate_action(a, _screen(2))
    assert err is not None and "element_id" in err


def test_validate_type_requires_text():
    a = ComputerUseAction(action="type", element_id=0, reason="x")
    err = validate_action(a, _screen(2))
    assert err is not None and "text" in err


def test_validate_hotkey_requires_keys():
    a = ComputerUseAction(action="hotkey", reason="x")
    err = validate_action(a, _screen(2))
    assert err is not None and "keys" in err


def test_validate_done_needs_nothing():
    a = ComputerUseAction(action="done", text="all done", reason="finished")
    assert validate_action(a, _screen(2)) is None


def test_validate_scroll_requires_amount():
    a = ComputerUseAction(action="scroll", reason="x")
    err = validate_action(a, _screen(2))
    assert err is not None and "scroll_amount" in err


from app.services.computer_use_service import (
    format_elements, build_decision_messages,
)


def test_format_elements_lists_id_type_content():
    out = format_elements(_screen(2))
    assert "[0]" in out and "[1]" in out
    assert "el0" in out and "el1" in out
    assert "icon" in out


def test_build_decision_messages_includes_goal_history_image():
    screen = _screen(2)
    msgs = build_decision_messages(
        goal="open notepad",
        screen=screen,
        history=[{"action": "click", "reason": "start menu", "result": "ok"}],
        system_prompt="SYS",
        som_image_b64="QUJD",  # "ABC"
    )
    assert msgs[0]["role"] == "system" and msgs[0]["content"] == "SYS"
    user = msgs[-1]
    assert user["role"] == "user"
    # multimodal content: text block with goal + elements + history, plus image
    text_blocks = [c for c in user["content"] if c["type"] == "text"]
    image_blocks = [c for c in user["content"] if c["type"] == "image_url"]
    assert len(image_blocks) == 1
    assert image_blocks[0]["image_url"]["url"].startswith("data:image/jpeg;base64,QUJD")
    joined = " ".join(b["text"] for b in text_blocks)
    assert "open notepad" in joined
    assert "start menu" in joined  # history reason present
    assert "[0]" in joined  # element list present


def test_build_decision_messages_truncates_history():
    screen = _screen(1)
    history = [{"action": "click", "reason": f"step{i}", "result": "ok"}
               for i in range(20)]
    msgs = build_decision_messages(
        goal="g", screen=screen, history=history,
        system_prompt="SYS", som_image_b64="", history_limit=3,
    )
    joined = " ".join(
        c["text"] for c in msgs[-1]["content"] if c["type"] == "text"
    )
    assert "step19" in joined and "step17" in joined
    assert "step16" not in joined  # only last 3 kept


import json
import httpx

from app.services.computer_use_service import ComputerUseDecider


def _llm_response(action_dict):
    content = json.dumps(action_dict)
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": content}}]},
    )


@pytest.mark.asyncio
async def test_decider_returns_parsed_action():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return _llm_response(
            {"action": "click", "element_id": 1, "reason": "open menu"}
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://test")
    decider = ComputerUseDecider(http_client=client)

    action = await decider.decide(
        messages=[{"role": "system", "content": "SYS"},
                  {"role": "user", "content": [{"type": "text", "text": "go"}]}],
    )
    assert action.action == "click" and action.element_id == 1
    # response_format json_schema was sent
    assert calls[0]["response_format"]["type"] == "json_schema"
    await client.aclose()


@pytest.mark.asyncio
async def test_decider_retries_then_succeeds():
    state = {"n": 0}

    def handler(request):
        state["n"] += 1
        if state["n"] == 1:
            return httpx.Response(500)
        return _llm_response({"action": "wait", "reason": "loading"})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://test")
    decider = ComputerUseDecider(http_client=client, backoff_base=0.0)
    action = await decider.decide(messages=[{"role": "user", "content": "x"}])
    assert action.action == "wait"
    assert state["n"] == 2
    await client.aclose()


from app.services.computer_use_service import ComputerUseService


class _FakeDesktop:
    def __init__(self):
        self.events = []

    async def capture(self):
        await asyncio.sleep(0.001)
        from app.services.desktop_backend import CapturedScreen
        return CapturedScreen(png_bytes=b"PNG", width=1920, height=1080)

    async def click(self, x, y, button="left", double=False):
        self.events.append(("click", x, y, button, double))

    async def type_text(self, text):
        self.events.append(("type", text))

    async def hotkey(self, keys):
        self.events.append(("hotkey", tuple(keys)))

    async def scroll(self, x, y, amount):
        self.events.append(("scroll", x, y, amount))


class _FakeParser:
    async def parse(self, png_bytes):
        return _screen(2)


class _ScriptedDecider:
    def __init__(self, actions):
        self._actions = list(actions)
        self.calls = 0

    async def decide(self, messages):
        self.calls += 1
        return self._actions.pop(0)


def _make_service(actions, tmp_path):
    svc = ComputerUseService(
        parser=_FakeParser(),
        desktop=_FakeDesktop(),
        decider=_ScriptedDecider(actions),
        audit_path=str(tmp_path / "audit.log"),
    )
    return svc


@pytest.mark.asyncio
async def test_session_runs_to_done(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "COMPUTER_USE_ENABLED", True)
    monkeypatch.setattr(settings, "COMPUTER_USE_SETTLE_SECONDS", 0.0)
    steps = []
    svc = _make_service(
        [ComputerUseAction(action="click", element_id=0, reason="open"),
         ComputerUseAction(action="done", text="finished", reason="done")],
        tmp_path,
    )
    await svc.run_session("goal", emit=lambda m: steps.append(m))

    states = [s for s in steps if s["type"] == "computer_use_state"]
    assert states[0]["status"] == "started"
    assert states[-1]["status"] == "done"
    # one click executed on the fake desktop
    assert ("click", 48, 135, "left", False) in svc._desktop.events
    # audit file has a line for the executed click
    audit = (tmp_path / "audit.log").read_text().strip().splitlines()
    assert any("click" in line for line in audit)


@pytest.mark.asyncio
async def test_session_stops_at_step_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "COMPUTER_USE_ENABLED", True)
    monkeypatch.setattr(settings, "COMPUTER_USE_SETTLE_SECONDS", 0.0)
    monkeypatch.setattr(settings, "COMPUTER_USE_MAX_STEPS", 3)
    steps = []
    # always "wait" -> never terminates on its own
    svc = _make_service(
        [ComputerUseAction(action="wait", reason="loading")] * 10, tmp_path,
    )
    await svc.run_session("goal", emit=lambda m: steps.append(m))
    states = [s for s in steps if s["type"] == "computer_use_state"]
    assert states[-1]["status"] == "failed"
    assert svc._decider.calls == 3  # budget respected


@pytest.mark.asyncio
async def test_invalid_action_then_selfcorrect(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "COMPUTER_USE_ENABLED", True)
    monkeypatch.setattr(settings, "COMPUTER_USE_SETTLE_SECONDS", 0.0)
    steps = []
    svc = _make_service(
        [ComputerUseAction(action="click", element_id=99, reason="bad"),   # invalid
         ComputerUseAction(action="click", element_id=0, reason="good"),   # valid
         ComputerUseAction(action="done", text="ok", reason="done")],
        tmp_path,
    )
    await svc.run_session("goal", emit=lambda m: steps.append(m))
    states = [s for s in steps if s["type"] == "computer_use_state"]
    assert states[-1]["status"] == "done"
    # only the valid click executed
    assert len(svc._desktop.events) == 1


@pytest.mark.asyncio
async def test_two_consecutive_invalid_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "COMPUTER_USE_ENABLED", True)
    monkeypatch.setattr(settings, "COMPUTER_USE_SETTLE_SECONDS", 0.0)
    steps = []
    svc = _make_service(
        [ComputerUseAction(action="click", element_id=99, reason="bad1"),
         ComputerUseAction(action="click", element_id=98, reason="bad2")],
        tmp_path,
    )
    await svc.run_session("goal", emit=lambda m: steps.append(m))
    states = [s for s in steps if s["type"] == "computer_use_state"]
    assert states[-1]["status"] == "failed"
    assert svc._desktop.events == []  # nothing executed


@pytest.mark.asyncio
async def test_single_session_enforced(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "COMPUTER_USE_ENABLED", True)
    monkeypatch.setattr(settings, "COMPUTER_USE_SETTLE_SECONDS", 0.0)
    svc = _make_service(
        [ComputerUseAction(action="wait", reason="x")] * 50, tmp_path,
    )
    monkeypatch.setattr(settings, "COMPUTER_USE_MAX_STEPS", 50)

    task = asyncio.create_task(svc.run_session("goal", emit=lambda m: None))
    await asyncio.sleep(0)  # let it start
    assert svc.active is True
    # second start refused
    ok = svc.start("another goal", emit=lambda m: None, desktop_factory=lambda: _FakeDesktop())
    assert ok is False
    svc.stop()
    await task


@pytest.mark.asyncio
async def test_stop_ends_session(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "COMPUTER_USE_ENABLED", True)
    monkeypatch.setattr(settings, "COMPUTER_USE_SETTLE_SECONDS", 0.0)
    monkeypatch.setattr(settings, "COMPUTER_USE_MAX_STEPS", 50)
    steps = []
    svc = _make_service(
        [ComputerUseAction(action="wait", reason="x")] * 50, tmp_path,
    )
    task = asyncio.create_task(
        svc.run_session("goal", emit=lambda m: steps.append(m))
    )
    await asyncio.sleep(0)
    svc.stop()
    await task
    states = [s for s in steps if s["type"] == "computer_use_state"]
    assert states[-1]["status"] == "stopped"
