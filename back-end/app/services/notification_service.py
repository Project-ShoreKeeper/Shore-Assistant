"""
Notification service for proactive agent.
Bridges the scheduler to the LLM agent pipeline.
When a task fires, it feeds a prompt to the agent so Shore responds in-character.
Queues notifications when no client is connected.
"""

import json
import asyncio
import time
from pathlib import Path
from typing import Optional, Callable, Awaitable

from app.services.connection_manager import connection_manager
from app.core.config import settings


class NotificationService:

    def __init__(self):
        self._pending_file = Path(settings.SCHEDULER_PENDING_FILE)
        self.tts_lock = asyncio.Lock()
        self._run_agent: Optional[Callable[[str], Awaitable[None]]] = None

    def set_agent_callback(self, callback: Callable[[str], Awaitable[None]]):
        """
        Register the function that runs a prompt through the full agent pipeline
        (LLM + streaming + TTS). Called by chat_ws.py on connect.
        """
        self._run_agent = callback

    def clear_agent_callback(self):
        """Clear the callback on disconnect."""
        self._run_agent = None

    async def notify(self, task: dict):
        """
        Handle a fired task. If connected, run it through the agent pipeline
        so Shore responds in-character. If disconnected, queue it.
        """
        notification = {
            "type": "notification",
            "task_id": task["task_id"],
            "task_type": task["type"],
            "message": task["message"],
            "timestamp": time.time(),
        }

        if connection_manager.is_connected and self._run_agent:
            # Run through the full agent pipeline — the LLM response IS the notification
            prompt = self._build_reminder_prompt(task)
            print(f"[Notification] Firing through agent: {task['message']}")
            await self._run_agent(prompt)
        else:
            self._queue(notification)
            print(f"[Notification] Queued (no client): {task['message']}")

    async def drain_pending(self):
        """Deliver any queued notifications. Called when a client connects."""
        pending = self._load_pending()
        if not pending:
            return

        print(f"[Notification] Draining {len(pending)} pending notifications")
        for item in pending:
            task = {
                "task_id": item.get("task_id", "unknown"),
                "type": item.get("task_type", "reminder"),
                "message": item.get("message", ""),
            }
            if self._run_agent:
                prompt = self._build_reminder_prompt(task)
                await self._run_agent(prompt)
            else:
                # Fallback: just push the raw notification
                await connection_manager.send_json(item)
        self._clear_pending()

    def _build_reminder_prompt(self, task: dict) -> str:
        """Build a prompt that tells the LLM to deliver a reminder in-character."""
        task_type = task.get("type", "reminder")
        message = task["message"]

        if task_type == "reminder":
            return (
                f"[SYSTEM: A one-time reminder you set earlier has triggered. "
                f"The reminder message is: \"{message}\". "
                f"This reminder has been automatically deleted from your task list. "
                f"Deliver this reminder to the user naturally, in your own voice and personality. "
                f"Do not use any tools. Keep it brief.]"
            )
        else:
            return (
                f"[SYSTEM: A recurring scheduled task has triggered. "
                f"The task is: \"{message}\". "
                f"This task is still active and will fire again on schedule. "
                f"Notify the user about this naturally, in your own voice and personality. "
                f"Do not use any tools. Keep it brief.]"
            )

    def _queue(self, notification: dict):
        """Save notification to disk for later delivery."""
        pending = self._load_pending()
        pending.append(notification)
        self._pending_file.parent.mkdir(parents=True, exist_ok=True)
        self._pending_file.write_text(
            json.dumps(pending, indent=2, default=str),
            encoding="utf-8",
        )

    def _load_pending(self) -> list:
        """Load pending notifications from disk."""
        if not self._pending_file.exists():
            return []
        try:
            return json.loads(self._pending_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, Exception):
            return []

    def _clear_pending(self):
        """Remove the pending notifications file."""
        if self._pending_file.exists():
            self._pending_file.unlink()


notification_service = NotificationService()
