"""Source-level cua_* wiring checks for the /ws/chat closure."""

from pathlib import Path

_SRC_PATH = (
    Path(__file__).parent.parent
    / "app"
    / "api"
    / "websockets"
    / "chat_ws.py"
)


def _src() -> str:
    return _SRC_PATH.read_text(encoding="utf-8")


def test_sets_user_role_context():
    source = _src()
    assert "current_user_role" in source
    assert "current_user_role.set(ws_user_role)" in source


def test_attaches_and_detaches_computer_use_service():
    source = _src()
    assert "computer_use_service.attach(send_json_safe)" in source
    assert "computer_use_service.detach()" in source


def test_dispatches_cua_ready():
    source = _src()
    assert 'msg_type == "cua_ready"' in source
    assert 'computer_use_service.set_ready(data.get("screen"))' in source


def test_dispatches_cua_step_result():
    source = _src()
    assert 'msg_type == "cua_step_result"' in source
    assert "computer_use_service.resolve_step(" in source
    assert 'data.get("request_id", "")' in source


def test_dispatches_cua_abort():
    source = _src()
    assert 'msg_type == "cua_abort"' in source
    assert "computer_use_service.abort()" in source
