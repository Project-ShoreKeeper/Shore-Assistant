"""WebSocket JSON-RPC 2.0 client to the shore-pty-service microservice."""

import asyncio
import json
import logging
from typing import Awaitable, Callable, Optional

from websockets.asyncio.client import ClientConnection, connect
from websockets.protocol import State
from websockets.exceptions import ConnectionClosed

log = logging.getLogger(__name__)


NotificationHandler = Callable[[str, dict], Awaitable[None]]


class NodePtyClient:

    def __init__(
        self,
        url: str,
        auth_token: str = "",
        ping_interval: float = 30.0,
        ping_timeout: float = 5.0,
        reconnect_base_ms: int = 1000,
        reconnect_max_ms: int = 30000,
    ):
        self.url = url
        self.auth_token = auth_token
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout
        self.reconnect_base_ms = reconnect_base_ms
        self.reconnect_max_ms = reconnect_max_ms

        self._ws: Optional[ClientConnection] = None
        self._next_id = 1
        self._pending: dict[int, asyncio.Future] = {}
        self._notification_handler: Optional[NotificationHandler] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._connect_lock = asyncio.Lock()

    @property
    def is_connected(self) -> bool:
        return self._ws is not None and self._ws.state == State.OPEN

    def on_notification(self, handler: NotificationHandler) -> None:
        self._notification_handler = handler

    async def connect(self) -> None:
        async with self._connect_lock:
            if self.is_connected:
                return
            headers = {}
            if self.auth_token:
                headers["Authorization"] = f"Bearer {self.auth_token}"
            self._ws = await connect(self.url, additional_headers=headers)
            self._reader_task = asyncio.create_task(self._read_loop())

    async def close(self) -> None:
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None
        if self._ws:
            await self._ws.close()
            self._ws = None
        self._reject_all_pending("client closed")

    async def _read_loop(self) -> None:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                await self._handle_message(raw)
        except ConnectionClosed:
            log.info("node-pty-service connection closed")
        finally:
            self._reject_all_pending("connection lost")

    async def _handle_message(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("bad JSON from node-pty-service: %s", raw[:200])
            return
        if "id" in msg and msg["id"] is not None:
            fut = self._pending.pop(msg["id"], None)
            if fut and not fut.done():
                if "error" in msg:
                    fut.set_exception(
                        NodePtyRpcError(msg["error"].get("code", -1), msg["error"].get("message", ""))
                    )
                else:
                    fut.set_result(msg.get("result"))
        else:
            method = msg.get("method")
            params = msg.get("params", {})
            if method and self._notification_handler:
                try:
                    await self._notification_handler(method, params)
                except Exception:
                    log.exception("notification handler error")

    def _reject_all_pending(self, reason: str) -> None:
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(NodePtyRpcError(-32603, reason))
        self._pending.clear()


class NodePtyRpcError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
