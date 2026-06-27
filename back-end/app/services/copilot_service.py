"""Screen co-pilot: server-side watch loop + action-first triggering.

Pure helpers (norm_abs_diff, should_trigger, summarize_copilot_run,
build_copilot_prompt) are kept module-level and I/O-free so they can be unit
tested. The CopilotService singleton owns the background watch loop and is wired
into the /ws/chat handler the same way NotificationService is.
"""

import numpy as np

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
