"""Screen co-pilot: client-pushed frame gating + action-first triggering.

Pure helpers (norm_abs_diff, should_trigger, summarize_copilot_run,
build_copilot_prompt) are kept module-level and I/O-free so they can be unit
tested. Screen capture happens in the browser (getDisplayMedia) -- the
backend host has no guaranteed display. The frontend pushes a small
thumbnail on every capture tick via a "copilot_frame" message while a
session is active; CopilotService runs the same diff/idle/cooldown gate the
old server-side watch loop used, and on trigger pulls one full-resolution
frame through screenshot_bridge before handing off to the agent.
"""

import base64
import io
import time
from pathlib import Path

import numpy as np
from PIL import Image

from app.core.config import settings
from app.services.screenshot_bridge import screenshot_bridge

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
    unavailable (client-pushed frames carry no OS-level idle signal) -> the
    idle gate is skipped (degrade open).
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


def _decode_thumbnail_b64(data_url: str, size: int = 64) -> np.ndarray:
    """Decode a small client-captured thumbnail (data: URL or raw base64) into
    a grayscale array -- cheap input for diffing."""
    payload = data_url.split(",", 1)[1] if "," in data_url else data_url
    img = Image.open(io.BytesIO(base64.b64decode(payload))).convert("L").resize((size, size))
    return np.asarray(img, dtype=np.uint8)


class CopilotService:
    """Owns co-pilot trigger state. Single-user: at most one session at a time.

    Wired into /ws/chat: attach(trigger_cb, is_busy_cb) on connect, detach() on
    disconnect; start_session()/stop_session() toggle whether pushed frames
    are processed; handle_frame() is called per "copilot_frame" message.
    """

    def __init__(self, *, decode_thumbnail=None, request_screenshot=None):
        self._decode_thumbnail = decode_thumbnail or _decode_thumbnail_b64
        self._request_screenshot = request_screenshot or screenshot_bridge.request
        self._trigger_cb = None
        self._is_busy_cb = None
        self._active = False
        self._last_thumb = None
        self._last_action_ts = 0.0
        self._triggering = False

    @property
    def active(self) -> bool:
        return self._active

    def attach(self, trigger_cb, is_busy_cb) -> None:
        self._trigger_cb = trigger_cb
        self._is_busy_cb = is_busy_cb

    def detach(self) -> None:
        self._active = False
        self._trigger_cb = None
        self._is_busy_cb = None

    async def start_session(self) -> bool:
        self._active = True
        self._last_thumb = None
        self._last_action_ts = 0.0
        self._triggering = False
        return True

    async def stop_session(self) -> None:
        self._active = False

    async def handle_frame(self, thumbnail_data_url: str) -> bool:
        """Process one client-pushed thumbnail tick. Returns True if it
        triggered an agent turn."""
        if not self._active or self._triggering:
            return False
        if self._is_busy_cb and self._is_busy_cb():
            return False
        try:
            thumb = self._decode_thumbnail(thumbnail_data_url)
        except Exception:
            return False

        diff = norm_abs_diff(thumb, self._last_thumb)
        since_last = time.monotonic() - self._last_action_ts
        if not should_trigger(
            diff, None, since_last, busy=False,
            change_threshold=settings.COPILOT_CHANGE_THRESHOLD,
            idle_threshold=settings.COPILOT_IDLE_THRESHOLD_SECONDS,
            cooldown=settings.COPILOT_COOLDOWN_SECONDS,
        ):
            return False

        self._triggering = True
        try:
            image_data_url = await self._request_screenshot()
        except Exception as e:
            print(f"[Copilot] screenshot request failed: {e!r}")
            return False
        finally:
            self._triggering = False

        prompt = build_copilot_prompt("unknown")
        screenshot = {"data_url": image_data_url}
        self._last_thumb = thumb
        self._last_action_ts = time.monotonic()
        if self._trigger_cb:
            await self._trigger_cb(prompt, screenshot)
        return True


copilot_service = CopilotService()
