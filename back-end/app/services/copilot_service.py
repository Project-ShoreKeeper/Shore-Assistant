"""Screen co-pilot: server-side watch loop + action-first triggering.

Pure helpers (norm_abs_diff, should_trigger, summarize_copilot_run,
build_copilot_prompt) are kept module-level and I/O-free so they can be unit
tested. The CopilotService singleton owns the background watch loop and is wired
into the /ws/chat handler the same way NotificationService is.

Screenshots come from the connected browser (RemoteCaptureService), not from
the backend host's display — see docs/superpowers/specs/2026-07-02-client-side-screen-capture-design.md.
"""

import asyncio
import base64
import io
import time
from pathlib import Path

import numpy as np
from PIL import Image

from app.core.config import settings
from app.services.remote_capture import remote_capture_service

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
    unavailable (browsers cannot read system-wide idle time) -> the idle gate
    is skipped (degrade open).
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


def _decode_thumbnail_grayscale(data_url: str, size: int = 64) -> np.ndarray:
    """Decode a JPEG data URL into the (size, size) uint8 grayscale array
    shape norm_abs_diff expects."""
    payload = data_url.split(",", 1)[1]
    img = Image.open(io.BytesIO(base64.b64decode(payload))).convert("L").resize((size, size))
    return np.asarray(img, dtype=np.uint8)


async def _remote_grab_thumbnail() -> np.ndarray | None:
    result = await remote_capture_service.request("thumbnail")
    if result is None:
        return None
    return _decode_thumbnail_grayscale(result["data_url"])


async def _remote_capture_full_b64() -> str | None:
    result = await remote_capture_service.request("full")
    if result is None:
        return None
    return result["data_url"].split(",", 1)[1]


async def _remote_os_idle_seconds() -> float | None:
    """Browsers cannot read system-wide idle time -> always degrade open."""
    return None


async def _remote_active_window_title() -> str:
    """Best-effort label from the MediaStreamTrack the browser reported
    alongside the most recent full-frame capture."""
    return remote_capture_service.last_label or "shared screen"


class CopilotService:
    """Owns the screen-watch loop. Single-user: at most one session at a time.

    Wired into /ws/chat: attach(trigger_cb, is_busy_cb) on connect, detach() on
    disconnect; start_session()/stop_session() toggle the loop.
    """

    def __init__(self, *, grab_thumbnail=None, capture_full_b64=None,
                 os_idle=None, active_window=None):
        self._grab_thumbnail = grab_thumbnail or _remote_grab_thumbnail
        self._capture_full_b64 = capture_full_b64 or _remote_capture_full_b64
        self._os_idle = os_idle or _remote_os_idle_seconds
        self._active_window = active_window or _remote_active_window_title
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
        thumb = await self._grab_thumbnail()
        if thumb is None:
            return False  # no active browser stream (yet) -> nothing to compare
        diff = norm_abs_diff(thumb, self._last_thumb)
        idle = await self._os_idle()
        since_last = time.monotonic() - self._last_action_ts
        if not should_trigger(
            diff, idle, since_last, busy=False,
            change_threshold=settings.COPILOT_CHANGE_THRESHOLD,
            idle_threshold=settings.COPILOT_IDLE_THRESHOLD_SECONDS,
            cooldown=settings.COPILOT_COOLDOWN_SECONDS,
        ):
            return False
        image_b64 = await self._capture_full_b64()
        if image_b64 is None:
            return False  # consent prompt declined or timed out
        title = await self._active_window()
        prompt = build_copilot_prompt(title)
        screenshot = {"data_url": f"data:image/jpeg;base64,{image_b64}"}
        self._last_thumb = thumb
        self._last_action_ts = time.monotonic()
        if self._trigger_cb:
            await self._trigger_cb(prompt, screenshot)
        return True

    async def _run_loop(self) -> None:
        try:
            while self._active:
                try:
                    await self._tick()
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    print(f"[Copilot] tick error: {e!r}")
                await asyncio.sleep(settings.COPILOT_CAPTURE_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            pass


copilot_service = CopilotService()
