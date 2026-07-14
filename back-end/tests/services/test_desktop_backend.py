import pytest

from app.services.desktop_backend import (
    CapturedScreen, LocalDesktopBackend, norm_to_pixels,
)


def test_norm_to_pixels_maps_center():
    # 1920x1080 screen, normalized center (0.5, 0.5) -> (960, 540)
    assert norm_to_pixels(0.5, 0.5, 1920, 1080) == (960, 540)


def test_norm_to_pixels_corner_and_rounding():
    assert norm_to_pixels(0.0, 0.0, 1920, 1080) == (0, 0)
    # 0.925 * 1920 = 1776.0, 0.025 * 1080 = 27.0
    assert norm_to_pixels(0.925, 0.025, 1920, 1080) == (1776, 27)
    # rounding: 0.3334 * 1000 = 333.4 -> 333
    assert norm_to_pixels(0.3334, 0.3336, 1000, 1000) == (333, 334)


def test_norm_to_pixels_clamps_out_of_range():
    # values >1 or <0 clamp into the screen so a bad bbox can't click off-screen
    assert norm_to_pixels(1.5, -0.2, 800, 600) == (799, 0)


class _RecordingPyAutoGUI:
    def __init__(self):
        self.events = []
        self.PAUSE = 0
        self.FAILSAFE = True

    def click(self, x, y, button="left"):
        self.events.append(("click", x, y, button))

    def doubleClick(self, x, y):
        self.events.append(("double", x, y))

    def moveTo(self, x, y):
        self.events.append(("move", x, y))

    def typewrite(self, text, interval=0.0):
        self.events.append(("type", text))

    def hotkey(self, *keys):
        self.events.append(("hotkey", keys))

    def scroll(self, amount, x=None, y=None):
        self.events.append(("scroll", amount, x, y))


@pytest.mark.asyncio
async def test_local_backend_click_uses_pixels():
    gui = _RecordingPyAutoGUI()
    backend = LocalDesktopBackend(gui=gui)
    await backend.click(1776, 27)
    assert gui.events == [("click", 1776, 27, "left")]


@pytest.mark.asyncio
async def test_local_backend_double_and_right_click():
    gui = _RecordingPyAutoGUI()
    backend = LocalDesktopBackend(gui=gui)
    await backend.click(10, 20, double=True)
    await backend.click(30, 40, button="right")
    assert gui.events == [("double", 10, 20), ("click", 30, 40, "right")]


@pytest.mark.asyncio
async def test_local_backend_type_and_hotkey_and_scroll():
    gui = _RecordingPyAutoGUI()
    backend = LocalDesktopBackend(gui=gui)
    await backend.type_text("hello")
    await backend.hotkey(["ctrl", "s"])
    await backend.scroll(100, 200, -3)
    assert ("type", "hello") in gui.events
    assert ("hotkey", ("ctrl", "s")) in gui.events
    assert ("scroll", -3, 100, 200) in gui.events


@pytest.mark.asyncio
async def test_local_backend_capture_uses_grabber():
    def fake_grab(monitor_index):
        return b"PNGBYTES", 1920, 1080
    backend = LocalDesktopBackend(gui=_RecordingPyAutoGUI(), grab=fake_grab)
    shot = await backend.capture()
    assert isinstance(shot, CapturedScreen)
    assert shot.png_bytes == b"PNGBYTES"
    assert shot.width == 1920 and shot.height == 1080
