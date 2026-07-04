"""Source-level cua_* wiring checks for the /ws/chat closure."""

from pathlib import Path

from app.api.websockets.chat_ws import _validate_screenshot_data_url

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
    assert "computer_use_service.detach(owner=my_send_json)" in source


def test_dispatches_cua_ready():
    source = _src()
    assert 'msg_type == "cua_ready"' in source
    ready_branch = source.split('msg_type == "cua_ready"', 1)[1]
    ready_branch = ready_branch.split("elif msg_type", 1)[0]
    assert "computer_use_service.set_ready(" in ready_branch
    assert "owner=send_json_safe" in ready_branch


def test_dispatches_cua_step_result():
    source = _src()
    assert 'msg_type == "cua_step_result"' in source
    result_branch = source.split('msg_type == "cua_step_result"', 1)[1]
    result_branch = result_branch.split("elif msg_type", 1)[0]
    assert "_validate_screenshot_data_url(" in result_branch
    assert "computer_use_service.resolve_step(" in result_branch
    assert 'data.get("request_id", "")' in result_branch
    assert "owner=send_json_safe" in result_branch


def test_dispatches_cua_abort():
    source = _src()
    assert 'msg_type == "cua_abort"' in source
    assert "computer_use_service.abort(owner=send_json_safe)" in source


def test_cua_step_result_rejects_bad_mime():
    screenshot, error = _validate_screenshot_data_url(
        "data:text/html;base64,PGh0bWw+",
        None,
    )
    assert screenshot is None
    assert error == "Unsupported screenshot format."


def test_copilot_stop_aborts_before_clearing_readiness():
    source = _src()
    stop_branch = source.split('msg_type == "copilot_stop"', 1)[1]
    stop_branch = stop_branch.split("elif msg_type", 1)[0]
    abort_at = stop_branch.index("computer_use_service.abort(")
    clear_at = stop_branch.index("computer_use_service.set_ready(")
    assert abort_at < clear_at
    assert stop_branch.count("owner=send_json_safe") == 2
