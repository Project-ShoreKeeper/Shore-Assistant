"""Bridge for requesting a client-captured screenshot over /ws/chat.

The backend host has no guaranteed display (it may be a headless Linux box),
so screen capture happens in the browser via getDisplayMedia. This mirrors
TerminalService's confirm-request pattern: broadcast a request, then await a
Future that the chat_ws receive loop resolves when the matching
screenshot_response arrives. Callers must run in a task separate from the WS
receive loop, or the wait for that response deadlocks the connection.
"""

import asyncio
import uuid

from app.core.config import settings


class ScreenshotUnavailable(Exception):
    """No client attached, the client failed to capture, or the request timed out."""


class ScreenshotBridge:
    def __init__(self, timeout_seconds: float = 15.0):
        self.timeout_seconds = timeout_seconds
        self.broadcast = None  # async callable(dict), set by chat_ws on connect
        self._pending: dict[str, asyncio.Future] = {}

    def resolve(self, request_id: str, data_url: str | None = None, error: str | None = None) -> bool:
        fut = self._pending.pop(request_id, None)
        if not fut or fut.done():
            return False
        if error:
            fut.set_exception(ScreenshotUnavailable(error))
        else:
            fut.set_result(data_url)
        return True

    async def request(self, max_size: int | None = None) -> str:
        """Ask the connected client for a fresh screenshot. Returns a data: URL."""
        if not self.broadcast:
            raise ScreenshotUnavailable("No client connected to capture a screenshot.")
        request_id = uuid.uuid4().hex[:12]
        fut = asyncio.get_running_loop().create_future()
        self._pending[request_id] = fut
        await self.broadcast({
            "type": "request_screenshot",
            "request_id": request_id,
            "max_size": max_size or settings.COPILOT_MAX_IMAGE_SIZE,
        })
        try:
            return await asyncio.wait_for(fut, timeout=self.timeout_seconds)
        except asyncio.TimeoutError:
            self._pending.pop(request_id, None)
            raise ScreenshotUnavailable("Timed out waiting for the client to capture a screenshot.")


screenshot_bridge = ScreenshotBridge()
