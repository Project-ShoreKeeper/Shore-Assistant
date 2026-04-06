"""
Conversation memory service.
Persists chat history to JSON files on disk so context survives server restarts.
"""

import json
import os
import time
from pathlib import Path
from typing import Optional

from app.core.config import settings


class MemoryService:
    """Load, save, and manage per-session conversation history."""

    def __init__(self):
        self.memory_dir = Path(settings.MEMORY_DIR)
        self.max_turns = settings.MEMORY_MAX_TURNS
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    def _session_path(self, session_id: str) -> Path:
        return self.memory_dir / f"{session_id}.json"

    def load(self, session_id: str) -> list[dict]:
        """Load conversation history for a session. Returns last N turn pairs."""
        path = self._session_path(session_id)
        if not path.exists():
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                messages = json.load(f)
            # Return last max_turns * 2 messages (each turn = user + assistant)
            limit = self.max_turns * 2
            if len(messages) > limit:
                messages = messages[-limit:]
            return messages
        except (json.JSONDecodeError, Exception) as e:
            print(f"[Memory] Error loading session {session_id}: {e}")
            return []

    def append(self, session_id: str, role: str, content: str):
        """Append a single message to the session history."""
        path = self._session_path(session_id)
        messages = []
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    messages = json.load(f)
            except (json.JSONDecodeError, Exception):
                messages = []

        messages.append({
            "role": role,
            "content": content,
            "timestamp": time.time(),
        })

        with open(path, "w", encoding="utf-8") as f:
            json.dump(messages, f, ensure_ascii=False, indent=2)

    def clear(self, session_id: str) -> bool:
        """Clear all history for a session. Returns True if a file was deleted."""
        path = self._session_path(session_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def list_sessions(self) -> list[str]:
        """List all session IDs with saved history."""
        return [
            p.stem for p in self.memory_dir.glob("*.json")
        ]


memory_service = MemoryService()
