"""Computer-use session: capture -> parse -> decide -> act loop.

Pure helpers (build_decision_messages, validate_action, format_elements) are
module-level and I/O-free for unit testing. ComputerUseService owns the
background session loop, wired into /ws/chat like CopilotService.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel

from app.services.ai_client.screenparse import ParsedScreen


class ComputerUseAction(BaseModel):
    action: Literal[
        "click", "double_click", "right_click", "type",
        "hotkey", "scroll", "wait", "done", "fail",
    ]
    element_id: Optional[int] = None
    text: Optional[str] = None
    keys: Optional[list[str]] = None
    scroll_amount: Optional[int] = None
    reason: str


_NEEDS_ELEMENT = {"click", "double_click", "right_click", "type"}


def validate_action(action: ComputerUseAction, screen: ParsedScreen) -> Optional[str]:
    """Return None if the action is executable against `screen`, else an error string."""
    n = len(screen.elements)
    if action.action in _NEEDS_ELEMENT:
        if action.element_id is None:
            return f"action '{action.action}' requires element_id"
        if not (0 <= action.element_id < n):
            return f"element_id {action.element_id} out of range (0..{n - 1})"
    if action.action == "type" and not (action.text and action.text.strip()):
        return "action 'type' requires non-empty text"
    if action.action == "hotkey" and not action.keys:
        return "action 'hotkey' requires keys"
    if action.action == "scroll" and action.scroll_amount is None:
        return "action 'scroll' requires scroll_amount"
    return None
