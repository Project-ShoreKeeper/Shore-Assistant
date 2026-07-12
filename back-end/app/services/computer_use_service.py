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
