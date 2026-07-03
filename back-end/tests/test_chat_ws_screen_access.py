"""Screen-access start/stop survives without proactive frame processing."""

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


def test_start_stop_remain_as_screen_access_toggle():
    source = _src()
    assert 'msg_type == "copilot_start"' in source
    assert 'msg_type == "copilot_stop"' in source
    assert "screen_access_active = True" in source
    assert "screen_access_active = False" in source
    assert '"type": "copilot_state"' in source


def test_stop_revokes_computer_use_readiness():
    source = _src()
    stop_branch = source.split('msg_type == "copilot_stop"', 1)[1]
    stop_branch = stop_branch.split("elif msg_type", 1)[0]
    assert "computer_use_service.set_ready(None)" in stop_branch


def test_proactive_frame_pipeline_is_removed():
    source = _src()
    assert "copilot_frame" not in source
    assert "run_copilot_pipeline" not in source
    assert "copilot_service" not in source
    assert "summarize_copilot_run" not in source
