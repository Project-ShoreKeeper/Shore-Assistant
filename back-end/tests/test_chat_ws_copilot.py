"""Source-level wiring check for the screen co-pilot in chat_ws.

chat_ws builds its pipeline inside a WebSocket closure, so (matching the other
test_chat_ws_* tests) we assert the wiring exists at the source level.
We read the source file directly to avoid importing the full FastAPI/gRPC
dependency chain, which is not available in the lightweight test environment.
"""
import pathlib

_SRC_PATH = (
    pathlib.Path(__file__).parent.parent
    / "app" / "api" / "websockets" / "chat_ws.py"
)


def _src() -> str:
    return _SRC_PATH.read_text(encoding="utf-8")


def test_imports_copilot_service():
    src = _src()
    assert "copilot_service" in src
    assert "summarize_copilot_run" in src


def test_attaches_and_detaches_copilot():
    src = _src()
    assert "copilot_service.attach(" in src
    assert "copilot_service.detach()" in src


def test_handles_start_stop_messages():
    src = _src()
    assert '"copilot_start"' in src
    assert '"copilot_stop"' in src
    assert "start_session()" in src
    assert "stop_session()" in src


def test_emits_copilot_message_and_state():
    src = _src()
    assert '"copilot_message"' in src
    assert '"copilot_state"' in src


def test_has_copilot_pipeline():
    src = _src()
    assert "run_copilot_pipeline" in src
    assert "is_copilot" in src  # compact persisted record is tagged
