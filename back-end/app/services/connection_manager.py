"""
Connection manager for proactive notifications.
Holds a reference to the active WebSocket's send functions so background tasks
can push messages to the client without being inside the handler scope.

Single-user system: at most one connection at a time.
"""

import asyncio
from typing import Optional, Callable, Awaitable


class ConnectionManager:

    def __init__(self):
        self._send_json: Optional[Callable[[dict], Awaitable[None]]] = None
        self._send_binary: Optional[Callable[[bytes], Awaitable[None]]] = None
        self._connected = asyncio.Event()

    @property
    def is_connected(self) -> bool:
        return self._send_json is not None

    def register(
        self,
        send_json: Callable[[dict], Awaitable[None]],
        send_binary: Callable[[bytes], Awaitable[None]],
    ):
        """Register the active WebSocket's send functions."""
        self._send_json = send_json
        self._send_binary = send_binary
        self._connected.set()
        print("[ConnectionManager] Client registered")

    def unregister(self):
        """Clear send functions on disconnect."""
        self._send_json = None
        self._send_binary = None
        self._connected.clear()
        print("[ConnectionManager] Client unregistered")

    async def send_json(self, data: dict) -> bool:
        """Push JSON to the client. Returns False if no client connected."""
        if self._send_json:
            await self._send_json(data)
            return True
        return False

    async def send_binary(self, data: bytes) -> bool:
        """Push binary data to the client. Returns False if no client connected."""
        if self._send_binary:
            await self._send_binary(data)
            return True
        return False


connection_manager = ConnectionManager()
