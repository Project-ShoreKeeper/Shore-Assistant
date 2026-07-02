"""Unit tests for capture_screen/analyze_screen against RemoteCaptureService."""
import pytest

from app.services.remote_capture import remote_capture_service
from app.tools import screen_tools


@pytest.fixture(autouse=True)
def _reset_capture_service(monkeypatch):
    # Each test stubs remote_capture_service.request directly; no real
    # connection or asyncio.Future machinery needed at this layer.
    yield
    remote_capture_service.send_json = None


@pytest.mark.asyncio
async def test_capture_screen_returns_declined_message_when_no_frame(monkeypatch):
    async def fake_request(kind):
        return None

    monkeypatch.setattr(remote_capture_service, "request", fake_request)
    result = await screen_tools.capture_screen.ainvoke({"prompt": "what is this"})
    assert result == "Screen sharing was declined or timed out."


@pytest.mark.asyncio
async def test_analyze_screen_returns_declined_message_when_no_frame(monkeypatch):
    async def fake_request(kind):
        return None

    monkeypatch.setattr(remote_capture_service, "request", fake_request)
    result = await screen_tools.analyze_screen.ainvoke({"query": "what error is shown"})
    assert result == "Screen sharing was declined or timed out."


@pytest.mark.asyncio
async def test_capture_screen_analyzes_frame_when_present(monkeypatch):
    async def fake_request(kind):
        assert kind == "full"
        return {"data_url": "data:image/jpeg;base64,QUJD", "label": "Entire screen"}

    async def fake_analyze(prompt, image_b64):
        assert image_b64 == "QUJD"
        return "There is a code editor open."

    monkeypatch.setattr(remote_capture_service, "request", fake_request)
    monkeypatch.setattr(screen_tools, "_analyze", fake_analyze)
    result = await screen_tools.capture_screen.ainvoke({"prompt": "describe"})
    assert result == "There is a code editor open."


@pytest.mark.asyncio
async def test_analyze_screen_wraps_exceptions():
    async def raising_request(kind):
        raise RuntimeError("boom")

    import app.tools.screen_tools as st
    orig = st.remote_capture_service.request
    st.remote_capture_service.request = raising_request
    try:
        result = await screen_tools.analyze_screen.ainvoke({"query": "what is this"})
    finally:
        st.remote_capture_service.request = orig
    assert result.startswith("Error: Unable to capture or analyze the screen.")
