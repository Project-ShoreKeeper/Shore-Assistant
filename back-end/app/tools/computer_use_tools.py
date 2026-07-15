"""Computer-use control tools: start/stop a desktop-control session.

The session's step emitter and desktop backend are supplied by chat_ws at
connection time via set_session_hooks(). The tool only starts/stops; the loop
lives in ComputerUseService. Starting returns immediately so the agent turn
finish (and TTS plays) while the session runs in the background.
"""
from __future__ import annotations

from typing import Callable, Optional

from langchain_core.tools import tool

from app.core.config import settings
from app.services.computer_use_service import (
    ComputerUseDecider, computer_use_service,
)
from app.services.ai_client.screenparse import screenparse_client
from app.services.desktop_backend import LocalDesktopBackend

# Set by chat_ws on connect: (emit_fn, is_admin_bool). None when no client.
_session_emit: Optional[Callable[[dict], None]] = None
_is_admin: bool = True


def set_session_hooks(emit: Optional[Callable[[dict], None]], is_admin: bool) -> None:
    global _session_emit, _is_admin
    _session_emit = emit
    _is_admin = is_admin


def clear_session_hooks() -> None:
    global _session_emit
    _session_emit = None


@tool
async def computer_use(goal: str) -> str:
    """Take control of the computer's screen, mouse, and keyboard to accomplish a
    goal by looking at the screen and clicking/typing. Use for tasks that require
    operating desktop applications visually (e.g. "open Notepad and type hello",
    "close all Chrome tabs"). Prefer run_command / terminal tools for anything
    that can be done in a shell. Only one session runs at a time.

    Args:
        goal: A concrete description of what to accomplish on screen.
    """
    if not settings.COMPUTER_USE_ENABLED:
        return "Computer-use mode is disabled on this server."
    if not _is_admin:
        return "Computer-use mode is restricted to the admin user."
    if _session_emit is None:
        return "No active client connection to stream computer-use steps to."
    if computer_use_service.active:
        return "A computer-use session is already running. Stop it first."

    from app.services.screen_relay import screen_relay
    from app.services.desktop_backend import ClientDesktopBackend, LocalDesktopBackend

    desktop_factory = ClientDesktopBackend if screen_relay.attached else LocalDesktopBackend

    decider = ComputerUseDecider()
    started = computer_use_service.start(
        goal, _session_emit,
        parser=screenparse_client,
        decider=decider,
        desktop_factory=desktop_factory,
    )
    if not started:
        return "A computer-use session is already running."
    return f"Started a computer-use session to: {goal}. I'll work on it now."


@tool
async def stop_computer_use() -> str:
    """Stop the currently running computer-use session immediately."""
    if not computer_use_service.active:
        return "No computer-use session is currently running."
    computer_use_service.stop()
    return "Stopping the computer-use session."
