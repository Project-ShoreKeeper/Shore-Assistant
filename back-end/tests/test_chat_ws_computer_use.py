"""Tests for the chat_ws computer-use emitter + debug artifact writer."""
import json

from app.api.websockets import chat_ws


def test_make_step_emitter_forwards_and_writes_debug(tmp_path, monkeypatch):
    sent = []

    def fake_send(msg):
        sent.append(msg)

    monkeypatch.setattr(chat_ws.settings, "COMPUTER_USE_DEBUG_DIR", str(tmp_path))
    emit = chat_ws._make_computer_use_emitter(fake_send, session_id="abc")

    step_msg = {
        "type": "computer_use_step", "step": 0, "action": "click",
        "element_id": 1, "element_content": "File", "reason": "open menu",
        "status": "executed", "error": None,
        "som_image": "data:image/jpeg;base64,QUJD", "elements": [],
    }
    emit(step_msg)

    # forwarded to the websocket
    assert sent == [step_msg]
    # debug artifacts written
    session_dir = tmp_path / "abc"
    assert (session_dir / "step_0.jpg").exists()
    decision = json.loads((session_dir / "step_0.json").read_text())
    assert decision["action"] == "click"


def test_make_step_emitter_no_debug_when_dir_empty(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(chat_ws.settings, "COMPUTER_USE_DEBUG_DIR", "")
    emit = chat_ws._make_computer_use_emitter(sent.append, session_id="abc")
    emit({"type": "computer_use_state", "status": "started", "goal": "g",
          "steps_taken": 0})
    assert len(sent) == 1
    assert not (tmp_path / "abc").exists()
