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
