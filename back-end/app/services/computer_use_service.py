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


from pathlib import Path

from app.core.config import settings

_DECIDER_PROMPT_PATH = (
    Path(__file__).resolve().parents[1] / "prompts" / "computer_use_decider.txt"
)
_decider_prompt: Optional[str] = None


def load_decider_prompt() -> str:
    global _decider_prompt
    if _decider_prompt is None:
        _decider_prompt = _DECIDER_PROMPT_PATH.read_text(encoding="utf-8")
    return _decider_prompt


def format_elements(screen: ParsedScreen) -> str:
    """Render the element list the decision model reads."""
    lines = []
    for el in screen.elements:
        cx, cy = el.center()
        tag = "interactable" if el.interactable else "static"
        lines.append(
            f"[{el.id}] {el.type} \"{el.content}\" {tag} center=({cx:.3f},{cy:.3f})"
        )
    return "\n".join(lines)


def _format_history(history: list[dict], limit: int) -> str:
    recent = history[-limit:] if limit else history
    if not recent:
        return "(no actions yet)"
    lines = []
    for i, h in enumerate(recent):
        lines.append(
            f"{i+1}. {h.get('action')} — {h.get('reason', '')} -> {h.get('result', '')}"
        )
    return "\n".join(lines)


def build_decision_messages(
    goal: str,
    screen: ParsedScreen,
    history: list[dict],
    system_prompt: str,
    som_image_b64: str,
    history_limit: int = 6,
) -> list[dict]:
    """Build the OpenAI-style messages for one decision call (SoM image + text)."""
    text = (
        f"GOAL: {goal}\n\n"
        f"ELEMENTS:\n{format_elements(screen)}\n\n"
        f"ACTION HISTORY:\n{_format_history(history, history_limit)}\n\n"
        f"Choose the next action."
    )
    user_content = [{"type": "text", "text": text}]
    if som_image_b64:
        user_content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{som_image_b64}"},
        })
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]


import asyncio

import httpx


class ComputerUseDecider:
    """Calls llama-server for one structured next-action decision."""

    _MAX_ATTEMPTS = 3

    def __init__(self, http_client: Optional[httpx.AsyncClient] = None,
                 backoff_base: float = 1.0):
        self._client = http_client
        self._backoff_base = backoff_base

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=settings.WORKER_LOCAL_LLM_URL.rstrip("/").rsplit("/v1", 1)[0],
                timeout=settings.COMPUTER_USE_DECISION_TIMEOUT,
            )
        return self._client

    async def decide(self, messages: list[dict]) -> ComputerUseAction:
        client = self._get_client()
        payload = {
            "model": "gemma-4",
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "computer_use_action",
                    "schema": ComputerUseAction.model_json_schema(),
                },
            },
            "temperature": 0.1,
            "stream": False,
        }
        last_error: Optional[BaseException] = None
        for attempt in range(self._MAX_ATTEMPTS):
            try:
                resp = await client.post("/v1/chat/completions", json=payload)
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                return ComputerUseAction.model_validate_json(content)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                last_error = e
                if attempt == self._MAX_ATTEMPTS - 1:
                    raise
                await asyncio.sleep(self._backoff_base * (2 ** attempt))
        raise last_error  # type: ignore[misc]

    async def close(self):
        if self._client is not None:
            await self._client.aclose()
            self._client = None


import json
import time

from app.services.desktop_backend import DesktopBackend, DisplayUnavailableError, norm_to_pixels
from app.services.ai_client.screenparse import ScreenParseUnavailable


class ComputerUseService:
    """Owns one computer-use session at a time. Wired into /ws/chat.

    All external effects (parse, decide, desktop I/O, step emission) are
    injected so the loop is unit-testable with fakes. In production the tool
    layer supplies the real screenparse_client, ComputerUseDecider, and
    LocalDesktopBackend, and `emit` sends over the WebSocket.
    """

    def __init__(self, parser=None, desktop: DesktopBackend | None = None,
                 decider=None, audit_path: str | None = None):
        self._parser = parser
        self._desktop = desktop
        self._decider = decider
        self._audit_path = audit_path or settings.COMPUTER_USE_AUDIT_LOG
        self._active = False
        self._stop_requested = False
        self._task = None

    @property
    def active(self) -> bool:
        return self._active

    def start(self, goal: str, emit, *, parser=None, desktop=None,
              decider=None, desktop_factory=None) -> bool:
        """Start a session as a background task. Returns False if one is active."""
        import asyncio
        if self._active:
            return False
        if parser is not None:
            self._parser = parser
        if decider is not None:
            self._decider = decider
        if desktop is not None:
            self._desktop = desktop
        elif desktop_factory is not None:
            self._desktop = desktop_factory()
        self._task = asyncio.create_task(self.run_session(goal, emit))
        return True

    def stop(self) -> None:
        self._stop_requested = True

    async def run_session(self, goal: str, emit) -> None:
        self._active = True
        self._stop_requested = False
        history: list[dict] = []
        consecutive_invalid = 0
        system_prompt = load_decider_prompt()
        emit({"type": "computer_use_state", "status": "started",
              "goal": goal, "steps_taken": 0})
        try:
            for step in range(settings.COMPUTER_USE_MAX_STEPS):
                if self._stop_requested:
                    emit({"type": "computer_use_state", "status": "stopped",
                          "goal": goal, "steps_taken": step})
                    return
                try:
                    shot = await self._desktop.capture()
                    screen = await self._parser.parse(shot.png_bytes)
                except ScreenParseUnavailable as e:
                    emit({"type": "computer_use_state", "status": "failed",
                          "goal": goal, "steps_taken": step,
                          "error": f"screen parsing unavailable: {e}"})
                    return
                except DisplayUnavailableError as e:
                    emit({"type": "computer_use_state", "status": "failed",
                          "goal": goal, "steps_taken": step,
                          "error": f"no display available: {e}"})
                    return
                except Exception as e:
                    emit({"type": "computer_use_state", "status": "failed",
                          "goal": goal, "steps_taken": step,
                          "error": f"capture or parse failed: {e}"})
                    return

                messages = build_decision_messages(
                    goal=goal, screen=screen, history=history,
                    system_prompt=system_prompt,
                    som_image_b64=screen.som_image_b64,
                    history_limit=settings.COMPUTER_USE_HISTORY_STEPS,
                )
                try:
                    action = await self._decider.decide(messages)
                except Exception as e:
                    emit({"type": "computer_use_state", "status": "failed",
                          "goal": goal, "steps_taken": step,
                          "error": f"decision failed: {e}"})
                    return

                if action.action == "done":
                    emit({"type": "computer_use_state", "status": "done",
                          "goal": goal, "steps_taken": step,
                          "summary": action.text or ""})
                    return
                if action.action == "fail":
                    emit({"type": "computer_use_state", "status": "failed",
                          "goal": goal, "steps_taken": step,
                          "error": action.text or action.reason})
                    return

                err = validate_action(action, screen)
                if err is not None:
                    consecutive_invalid += 1
                    history.append({"action": action.action,
                                    "reason": action.reason,
                                    "result": f"INVALID: {err}"})
                    emit(self._step_msg(step, action, screen, "invalid", err))
                    if consecutive_invalid >= 2:
                        emit({"type": "computer_use_state", "status": "failed",
                              "goal": goal, "steps_taken": step,
                              "error": "two consecutive invalid actions"})
                        return
                    continue
                consecutive_invalid = 0

                px, py = self._resolve_coords(action, screen)
                try:
                    await self._execute(action, px, py)
                except Exception as e:
                    emit({"type": "computer_use_state", "status": "failed",
                          "goal": goal, "steps_taken": step,
                          "error": f"action execution failed: {e}"})
                    return
                self._audit(step, action, px, py)
                history.append({"action": action.action,
                                "reason": action.reason, "result": "executed"})
                emit(self._step_msg(step, action, screen, "executed", None))

                await self._sleep(settings.COMPUTER_USE_SETTLE_SECONDS)

            emit({"type": "computer_use_state", "status": "failed",
                  "goal": goal, "steps_taken": settings.COMPUTER_USE_MAX_STEPS,
                  "error": "step budget exhausted"})
        finally:
            self._active = False
            self._stop_requested = False

    async def _sleep(self, seconds: float) -> None:
        import asyncio
        if seconds > 0:
            await asyncio.sleep(seconds)

    def _resolve_coords(self, action: ComputerUseAction,
                        screen: ParsedScreen) -> tuple[int, int]:
        if action.element_id is not None and 0 <= action.element_id < len(screen.elements):
            cx, cy = screen.elements[action.element_id].center()
        else:
            cx, cy = 0.5, 0.5
        return norm_to_pixels(cx, cy, screen.width, screen.height)

    async def _execute(self, action: ComputerUseAction, px: int, py: int) -> None:
        a = action.action
        if a == "click":
            await self._desktop.click(px, py)
        elif a == "double_click":
            await self._desktop.click(px, py, double=True)
        elif a == "right_click":
            await self._desktop.click(px, py, button="right")
        elif a == "type":
            await self._desktop.click(px, py)
            await self._desktop.type_text(action.text or "")
        elif a == "hotkey":
            await self._desktop.hotkey(action.keys or [])
        elif a == "scroll":
            await self._desktop.scroll(px, py, action.scroll_amount or 0)
        elif a == "wait":
            pass

    def _step_msg(self, step, action, screen, status, error):
        el_content = ""
        if action.element_id is not None and 0 <= action.element_id < len(screen.elements):
            el_content = screen.elements[action.element_id].content
        return {
            "type": "computer_use_step",
            "step": step,
            "action": action.action,
            "element_id": action.element_id,
            "element_content": el_content,
            "reason": action.reason,
            "status": status,
            "error": error,
            "som_image": (
                f"data:image/jpeg;base64,{screen.som_image_b64}"
                if screen.som_image_b64 else ""
            ),
            "elements": [
                {"id": e.id, "type": e.type, "content": e.content,
                 "interactable": e.interactable}
                for e in screen.elements
            ],
        }

    def _audit(self, step, action: ComputerUseAction, px, py) -> None:
        line = json.dumps({
            "ts": time.time(), "step": step, "action": action.action,
            "element_id": action.element_id, "reason": action.reason,
            "px": px, "py": py, "text": action.text, "keys": action.keys,
        })
        try:
            from pathlib import Path
            p = Path(self._audit_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass


computer_use_service = ComputerUseService()
