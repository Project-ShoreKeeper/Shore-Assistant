"""Screen co-pilot: server-side watch loop + action-first triggering.

Pure helpers (norm_abs_diff, should_trigger, summarize_copilot_run,
build_copilot_prompt) are kept module-level and I/O-free so they can be unit
tested. The CopilotService singleton owns the background watch loop and is wired
into the /ws/chat handler the same way NotificationService is.
"""

import asyncio
import io
import time
from pathlib import Path

import numpy as np

from app.core.config import settings

NOOP_SENTINEL = "__NOOP__"


def norm_abs_diff(a, b) -> float:
    """Normalized (0..1) mean absolute difference of two grayscale thumbnails.

    Returns 1.0 (fully changed) when there is no comparable baseline.
    """
    if a is None or b is None:
        return 1.0
    if a.shape != b.shape:
        return 1.0
    return float(np.mean(np.abs(a.astype(np.int16) - b.astype(np.int16)))) / 255.0


def should_trigger(
    diff: float,
    idle: float | None,
    since_last: float,
    busy: bool,
    *,
    change_threshold: float,
    idle_threshold: float,
    cooldown: float,
) -> bool:
    """Decide whether this tick should analyze the screen.

    Trigger only when not busy, past the cooldown, the screen changed enough,
    and the user has been idle long enough. idle=None means the idle probe is
    unavailable (e.g. non-Windows) -> the idle gate is skipped (degrade open).
    """
    if busy:
        return False
    if since_last < cooldown:
        return False
    if diff < change_threshold:
        return False
    if idle is not None and idle < idle_threshold:
        return False
    return True


def summarize_copilot_run(events: list[dict]) -> dict | None:
    """Reduce an agent_service.run event stream to a single co-pilot result.

    Returns None when the agent produced nothing worth surfacing (the
    __NOOP__ sentinel or empty text with no actions). Otherwise returns
    {"text": str, "agent_actions": list[dict]} for one copilot_message.
    """
    actions: list[dict] = []
    final_text = ""
    for ev in events:
        et = ev.get("type")
        if et == "agent_action" and ev.get("action") == "tool_call":
            actions.append({
                "action": "tool_call",
                "tool": ev.get("tool"),
                "args": ev.get("args"),
                "result": None,
                "status": "running",
                "timestamp": ev.get("timestamp"),
            })
        elif et == "agent_action" and ev.get("action") == "tool_result":
            for a in reversed(actions):
                if a.get("tool") == ev.get("tool") and a.get("status") == "running":
                    a["result"] = ev.get("result")
                    a["status"] = ev.get("status", "completed")
                    break
        elif et == "llm_complete":
            final_text = ev.get("text", "") or ""

    final = "" if final_text.strip() == NOOP_SENTINEL else final_text
    if not final.strip() and not actions:
        return None
    return {"text": final, "agent_actions": actions}


_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "copilot.txt"
_prompt_template: str | None = None


def build_copilot_prompt(window_title: str) -> str:
    """Load prompts/copilot.txt (cached) and inject the focused window title."""
    global _prompt_template
    if _prompt_template is None:
        _prompt_template = _PROMPT_PATH.read_text(encoding="utf-8")
    return _prompt_template.replace("{window_title}", window_title or "unknown")


async def _default_grab_thumbnail(monitor_index: int, size: int = 64) -> np.ndarray:
    """Small grayscale thumbnail — prefers relay capture, falls back to mss."""
    from app.services.screen_relay import screen_relay
    if screen_relay.attached:
        import base64 as _b64
        from PIL import Image
        b64 = await screen_relay.request_capture(max_size=size * 4)
        raw = _b64.b64decode(b64)
        img = Image.open(io.BytesIO(raw)).convert("L").resize((size, size))
        return np.asarray(img, dtype=np.uint8)
    # Fallback: local mss
    import mss
    from PIL import Image
    with mss.mss() as sct:
        shot = sct.grab(sct.monitors[monitor_index])
        img = (
            Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
            .convert("L")
            .resize((size, size))
        )
        return np.asarray(img, dtype=np.uint8)


async def _default_capture_full_b64() -> str:
    from app.tools.screen_tools import _capture_screen_b64
    return await _capture_screen_b64(max_size=settings.COPILOT_MAX_IMAGE_SIZE)


def _default_os_idle_seconds() -> float | None:
    """Seconds since the last system-wide keyboard/mouse input (Windows).

    Returns None on non-Windows or on failure, so the idle gate degrades open.
    """
    try:
        import ctypes

        class _LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

        info = _LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(info)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return None
        millis = ctypes.windll.kernel32.GetTickCount() - info.dwTime
        return millis / 1000.0
    except Exception:
        return None


def _default_active_window_title() -> str:
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value
    except Exception:
        return ""


class CopilotService:
    """Owns the screen-watch loop. Single-user: at most one session at a time.

    Wired into /ws/chat: attach(trigger_cb, is_busy_cb) on connect, detach() on
    disconnect; start_session()/stop_session() toggle the loop.
    """

    def __init__(self, *, grab_thumbnail=None, capture_full_b64=None,
                 os_idle=None, active_window=None):
        self._grab_thumbnail = grab_thumbnail or _default_grab_thumbnail
        self._capture_full_b64 = capture_full_b64 or _default_capture_full_b64
        self._os_idle = os_idle or _default_os_idle_seconds
        self._active_window = active_window or _default_active_window_title
        self._trigger_cb = None
        self._is_busy_cb = None
        self._active = False
        self._loop_task: asyncio.Task | None = None
        self._last_thumb = None
        self._last_action_ts = 0.0

    @property
    def active(self) -> bool:
        return self._active

    def attach(self, trigger_cb, is_busy_cb) -> None:
        self._trigger_cb = trigger_cb
        self._is_busy_cb = is_busy_cb

    def detach(self) -> None:
        self._active = False
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
        self._loop_task = None
        self._trigger_cb = None
        self._is_busy_cb = None

    async def start_session(self) -> bool:
        if not settings.COPILOT_ENABLED:
            return False
        if self._active:
            return True
        self._active = True
        self._last_thumb = None
        self._last_action_ts = 0.0
        self._loop_task = asyncio.create_task(self._run_loop())
        return True

    async def stop_session(self) -> None:
        self._active = False
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
            try:
                await self._loop_task
            except (asyncio.CancelledError, Exception):
                pass
        self._loop_task = None

    async def _tick(self) -> bool:
        if self._is_busy_cb and self._is_busy_cb():
            return False
        thumb = await self._grab_thumbnail(settings.COPILOT_MONITOR_INDEX)
        diff = norm_abs_diff(thumb, self._last_thumb)
        idle = self._os_idle()
        since_last = time.monotonic() - self._last_action_ts
        if not should_trigger(
            diff, idle, since_last, busy=False,
            change_threshold=settings.COPILOT_CHANGE_THRESHOLD,
            idle_threshold=settings.COPILOT_IDLE_THRESHOLD_SECONDS,
            cooldown=settings.COPILOT_COOLDOWN_SECONDS,
        ):
            return False
        image_b64 = await self._capture_full_b64()
        title = self._active_window()
        prompt = build_copilot_prompt(title)
        screenshot = {"data_url": f"data:image/jpeg;base64,{image_b64}"}
        self._last_thumb = thumb
        self._last_action_ts = time.monotonic()
        if self._trigger_cb:
            await self._trigger_cb(prompt, screenshot)
        return True

    async def _run_loop(self) -> None:
        from app.services.desktop_backend import DisplayUnavailableError
        try:
            while self._active:
                try:
                    await self._tick()
                except asyncio.CancelledError:
                    raise
                except DisplayUnavailableError as e:
                    print(f"[Copilot] no display available, stopping watch loop: {e}")
                    self._active = False
                    return
                except Exception as e:
                    print(f"[Copilot] tick error: {e!r}")
                await asyncio.sleep(settings.COPILOT_CAPTURE_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            pass


copilot_service = CopilotService()
