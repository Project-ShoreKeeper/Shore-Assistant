"""Desktop capture + input, behind one interface.

Windows gives each interactive desktop a single cursor, input queue, and
foreground window — so capture and input must always target the SAME desktop.
They live together here for exactly that reason. v1 LocalDesktopBackend drives
the host desktop (Shore borrows the real mouse during a session). A phase-2
RemoteDesktopBackend (talking to a shore-desktop-agent in a second RDP session)
can drop in behind this interface with zero loop changes.
"""
from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Callable, Optional

from pydantic import BaseModel

from app.core.config import settings

log = logging.getLogger(__name__)


class DisplayUnavailableError(RuntimeError):
    """Raised when no graphical display is available (headless server)."""
    pass


class CapturedScreen(BaseModel):
    png_bytes: bytes
    width: int
    height: int

    class Config:
        arbitrary_types_allowed = True


def norm_to_pixels(nx: float, ny: float, width: int, height: int) -> tuple[int, int]:
    """Map a normalized (0..1) point to physical pixel coords, clamped on-screen."""
    nx = min(max(nx, 0.0), 1.0)
    ny = min(max(ny, 0.0), 1.0)
    px = min(int(round(nx * width)), max(width - 1, 0))
    py = min(int(round(ny * height)), max(height - 1, 0))
    return px, py


class DesktopBackend(ABC):
    @abstractmethod
    async def capture(self) -> CapturedScreen: ...

    @abstractmethod
    async def click(self, x: int, y: int, button: str = "left",
                    double: bool = False) -> None: ...

    @abstractmethod
    async def type_text(self, text: str) -> None: ...

    @abstractmethod
    async def hotkey(self, keys: list[str]) -> None: ...

    @abstractmethod
    async def scroll(self, x: int, y: int, amount: int) -> None: ...


def _default_grab(monitor_index: int) -> tuple[bytes, int, int]:
    """Grab a full monitor as PNG bytes + its pixel dims (mss + Pillow)."""
    import io
    import mss
    from PIL import Image
    with mss.mss() as sct:
        shot = sct.grab(sct.monitors[monitor_index])
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue(), shot.size[0], shot.size[1]


class LocalDesktopBackend(DesktopBackend):
    """Drives the backend host's own desktop via mss + pyautogui.

    Known v1 limitation: shares the user's cursor and keyboard focus while a
    session runs. Phase 2 removes this by giving Shore her own desktop.
    """

    def __init__(self, gui=None, grab: Optional[Callable] = None):
        self._gui = gui
        self._grab = grab or _default_grab
        self._dpi_aware = False

    def _get_gui(self):
        if self._gui is None:
            try:
                import pyautogui
            except (KeyError, Exception) as exc:
                # pyautogui / mouseinfo crash with KeyError('DISPLAY') or
                # Xlib.error.XError on headless servers without a display.
                raise DisplayUnavailableError(
                    f"Cannot initialise pyautogui — no graphical display "
                    f"available (set $DISPLAY or run on a desktop session): {exc}"
                ) from exc
            pyautogui.FAILSAFE = False  # bbox clamping is our safety, not corner-abort
            self._gui = pyautogui
        if not self._dpi_aware:
            self._make_dpi_aware()
        return self._gui

    def _make_dpi_aware(self) -> None:
        """Ensure pyautogui + mss agree on physical pixels under display scaling."""
        self._dpi_aware = True
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass  # non-Windows or already set

    async def capture(self) -> CapturedScreen:
        self._get_gui()  # ensure DPI awareness before measuring
        png, w, h = await asyncio.get_event_loop().run_in_executor(
            None, self._grab, settings.COMPUTER_USE_MONITOR_INDEX
        )
        return CapturedScreen(png_bytes=png, width=w, height=h)

    async def click(self, x, y, button="left", double=False) -> None:
        gui = self._get_gui()

        def _do():
            if double:
                gui.doubleClick(x, y)
            else:
                gui.click(x, y, button=button)
        await asyncio.get_event_loop().run_in_executor(None, _do)

    async def type_text(self, text) -> None:
        gui = self._get_gui()

        def _do():
            gui.typewrite(text, interval=0.02)
        await asyncio.get_event_loop().run_in_executor(None, _do)

    async def hotkey(self, keys) -> None:
        gui = self._get_gui()

        def _do():
            gui.hotkey(*keys)
        await asyncio.get_event_loop().run_in_executor(None, _do)

    async def scroll(self, x, y, amount) -> None:
        gui = self._get_gui()

        def _do():
            gui.scroll(amount, x=x, y=y)
        await asyncio.get_event_loop().run_in_executor(None, _do)


class ClientDesktopBackend(DesktopBackend):
    """Drives the client's desktop via the WebSocket screen_relay."""

    def __init__(self, *args, **kwargs):
        # Allow passing args from desktop_factory calls
        self._last_width = 1280
        self._last_height = 720

    async def capture(self) -> CapturedScreen:
        from app.services.screen_relay import screen_relay
        if not screen_relay.attached:
            raise RuntimeError("Client is not connected. Cannot capture screen.")
        
        b64 = await screen_relay.request_capture()
        import base64
        from PIL import Image
        import io
        png_bytes = base64.b64decode(b64)
        
        # Load the image to determine actual width and height
        img = Image.open(io.BytesIO(png_bytes))
        self._last_width, self._last_height = img.size
        
        return CapturedScreen(
            png_bytes=png_bytes,
            width=self._last_width,
            height=self._last_height
        )

    async def click(self, x: int, y: int, button: str = "left", double: bool = False) -> None:
        from app.services.screen_relay import screen_relay
        func = "rightClick" if button == "right" else ("doubleClick" if double else "click")
        await screen_relay.request_input({
            "func": func,
            "x": x,
            "y": y
        })

    async def type_text(self, text: str) -> None:
        from app.services.screen_relay import screen_relay
        await screen_relay.request_input({
            "func": "write",
            "text": text
        })

    async def hotkey(self, keys: list[str]) -> None:
        from app.services.screen_relay import screen_relay
        keys_mapped = [k.lower() for k in keys]
        await screen_relay.request_input({
            "func": "hotkey",
            "keys": keys_mapped
        })

    async def scroll(self, x: int, y: int, amount: int) -> None:
        from app.services.screen_relay import screen_relay
        await screen_relay.request_input({
            "func": "scroll",
            "x": x,
            "y": y,
            "dy": amount
        })
