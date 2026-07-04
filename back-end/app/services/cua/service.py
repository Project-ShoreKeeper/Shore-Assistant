"""Task-driven computer-use loop: screenshot -> EvoCUA -> action -> repeat.

The service owns one run at a time. ``run`` must execute in a task separate
from the WebSocket receive loop so step results can resolve its futures.
"""

import asyncio
import collections
import json
import time
import uuid
from pathlib import Path

from app.core.auth import current_user_role
from app.core.config import settings
from app.services.cua.actions import (
    CuaParseError,
    code_to_commands,
    parse_cua_response,
    process_screenshot,
)
from app.services.cua.client import CuaUnavailable, cua_client
from app.services.screenshot_bridge import screenshot_bridge

_PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "computer_use.txt"
_INSTRUCTION_TEMPLATE = (
    "# Task Instruction:\n{task}\n\n"
    "Please generate the next move according to the screenshot, task "
    "instruction and previous steps (if provided).\n"
)
_WAIT_SECONDS = 20


class ComputerUseService:
    def __init__(self, *, client=None, request_screenshot=None, audit_path=None):
        self._client = client or cua_client
        self._request_screenshot = request_screenshot or screenshot_bridge.request
        self._audit_path = audit_path or settings.CUA_AUDIT_LOG
        self.broadcast = None
        self._screen: dict | None = None
        self._running = False
        self._aborted = False
        self._pending: dict[str, asyncio.Future] = {}
        self._system_prompt: str | None = None

    def attach(self, broadcast) -> bool:
        """Adopt a connection unless another connection owns an active run."""
        if (
            self._running
            and self.broadcast is not None
            and broadcast is not self.broadcast
        ):
            return False
        self.broadcast = broadcast
        return True

    def _owned_by(self, owner) -> bool:
        return owner is None or owner is self.broadcast

    def detach(self, owner=None) -> None:
        if not self._owned_by(owner):
            return
        self.broadcast = None
        self._screen = None
        self._aborted = True
        self._fail_pending("Client disconnected.")

    def set_ready(self, screen: dict | None, owner=None) -> None:
        if not self._owned_by(owner):
            return
        self._screen = screen if screen and screen.get("width") else None

    def _fail_pending(self, reason: str) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(RuntimeError(reason))
        self._pending.clear()

    @property
    def ready(self) -> bool:
        return self._screen is not None and self.broadcast is not None

    @property
    def running(self) -> bool:
        return self._running

    def abort(self, owner=None) -> None:
        if not self._owned_by(owner):
            return
        self._aborted = True
        self._fail_pending("aborted by the user")

    def resolve_step(
        self,
        request_id: str,
        *,
        screenshot=None,
        screen=None,
        error=None,
        owner=None,
    ) -> bool:
        if not self._owned_by(owner):
            return False
        future = self._pending.pop(request_id, None)
        if not future or future.done():
            return False
        if screen and self._screen is not None:
            self.set_ready(screen)
        if error:
            future.set_exception(RuntimeError(error))
        else:
            future.set_result(screenshot)
        return True

    async def run(self, task: str, max_steps: int) -> str:
        if current_user_role.get() != "admin":
            return "Computer use is restricted to the admin user."
        if not self.ready:
            return (
                "Computer use requires the desktop app with screen sharing "
                "enabled. Ask the user to enable Screen access."
            )
        if self._running:
            return "A computer-use run is already in progress."

        self._running = True
        self._aborted = False
        executed: list[str] = []
        try:
            frame = await self._request_screenshot()
            history: collections.deque[dict] = collections.deque(
                maxlen=settings.CUA_HISTORY_MAX_TURNS
            )
            for step in range(1, max_steps + 1):
                if self._aborted:
                    return self._summary(executed, "aborted by the user")

                image_url, model_width, model_height = await asyncio.to_thread(
                    process_screenshot,
                    frame,
                )
                screen = (self._screen["width"], self._screen["height"])
                messages = self._build_messages(task, history, image_url)
                await self._state(True, step, max_steps, task)

                try:
                    response = await self._client.next_step(messages)
                except CuaUnavailable as exc:
                    return self._summary(
                        executed,
                        f"EvoCUA is unavailable: {exc}",
                    )

                try:
                    hint, code = parse_cua_response(response)
                    commands = code_to_commands(
                        code,
                        (model_width, model_height),
                        screen,
                    )
                except CuaParseError as exc:
                    return self._summary(
                        executed,
                        "could not parse the model's action: "
                        f"{exc}. Raw tail: {response[-200:]}",
                    )

                history.append({"response": response, "image_url": image_url})
                for command in commands:
                    if self._aborted:
                        return self._summary(executed, "aborted by the user")
                    self._audit(task, command)
                    if command.func == "terminate":
                        outcome = f"finished with status={command.status}"
                        if command.answer:
                            outcome += f'; answer: "{command.answer}"'
                        executed.append(hint or "terminate")
                        return self._summary(executed, outcome)
                    if command.func == "wait":
                        executed.append("wait")
                        await asyncio.sleep(_WAIT_SECONDS)
                        frame = await self._request_screenshot()
                        continue
                    frame = await self._dispatch(command, hint)
                    executed.append(hint or command.func)

            return self._summary(
                executed,
                "stopped: step limit reached before the task finished",
            )
        except Exception as exc:
            if self._aborted:
                return self._summary(executed, "aborted by the user")
            return self._summary(executed, f"stopped on error: {exc}")
        finally:
            self._running = False
            self._aborted = False
            await self._state(False, 0, max_steps, task)

    async def _dispatch(self, command, hint: str) -> str:
        request_id = uuid.uuid4().hex[:12]
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        await self.broadcast(
            {
                "type": "cua_step",
                "request_id": request_id,
                "action": {"func": command.func, **command.args},
                "display_hint": hint,
                "settle_ms": settings.CUA_SETTLE_MS,
            }
        )
        try:
            return await asyncio.wait_for(
                future,
                timeout=settings.CUA_STEP_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as exc:
            self._pending.pop(request_id, None)
            raise RuntimeError(
                "timed out waiting for the desktop to execute the action"
            ) from exc

    def _build_messages(
        self,
        task: str,
        history: collections.deque[dict],
        image_url: str,
    ) -> list[dict]:
        if self._system_prompt is None:
            self._system_prompt = _PROMPT_PATH.read_text(encoding="utf-8")
        messages = [{"role": "system", "content": self._system_prompt}]
        kept = list(history)
        for index, turn in enumerate(kept):
            content = [
                {"type": "image_url", "image_url": {"url": turn["image_url"]}}
            ]
            if index == 0:
                content.insert(
                    0,
                    {
                        "type": "text",
                        "text": _INSTRUCTION_TEMPLATE.format(task=task),
                    },
                )
            messages.append({"role": "user", "content": content})
            messages.append({"role": "assistant", "content": turn["response"]})
        tail = [{"type": "image_url", "image_url": {"url": image_url}}]
        if not kept:
            tail.insert(
                0,
                {
                    "type": "text",
                    "text": _INSTRUCTION_TEMPLATE.format(task=task),
                },
            )
        messages.append({"role": "user", "content": tail})
        return messages

    async def _state(
        self,
        running: bool,
        step: int,
        max_steps: int,
        task: str,
    ) -> None:
        if self.broadcast:
            try:
                await self.broadcast(
                    {
                        "type": "cua_state",
                        "running": running,
                        "step": step,
                        "max_steps": max_steps,
                        "task": task,
                    }
                )
            except Exception:
                pass

    def _audit(self, task: str, command) -> None:
        try:
            path = Path(self._audit_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as file:
                file.write(
                    json.dumps(
                        {
                            "ts": time.time(),
                            "task": task[:200],
                            "func": command.func,
                            "args": command.args,
                            "status": command.status,
                            "answer": command.answer,
                        }
                    )
                    + "\n"
                )
        except OSError as exc:
            print(f"[CUA] audit write failed: {exc!r}")

    @staticmethod
    def _summary(executed: list[str], outcome: str) -> str:
        lines = [f"Computer-use run {outcome}."]
        if executed:
            lines.append("Actions executed:")
            lines.extend(
                f"{index}. {action}"
                for index, action in enumerate(executed, 1)
            )
        else:
            lines.append("No actions were executed.")
        return "\n".join(lines)


computer_use_service = ComputerUseService()
