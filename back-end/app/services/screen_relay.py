"""WebSocket relay for client-side screen capture.

The backend is often headless — no X11 display. Instead of capturing
locally with mss, we ask the connected frontend to grab a frame and send
it back over the chat WebSocket.

Protocol:
  Backend -> Frontend:  {"type": "capture_request", "request_id": "...", "max_size": 1280}
  Frontend -> Backend:  {"type": "capture_response", "request_id": "...", "data_url": "data:image/jpeg;base64,...", "error": null}
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Callable, Optional, Awaitable

log = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 10.0  # seconds


class ScreenCaptureRelay:
    """Singleton relay: backend requests screenshots from the frontend."""

    def __init__(self):
        self._send_fn: Optional[Callable[[dict], Awaitable[None]]] = None
        self._pending: dict[str, asyncio.Future[str]] = {}

    @property
    def attached(self) -> bool:
        return self._send_fn is not None

    def attach(self, send_fn: Callable[[dict], Awaitable[None]]) -> None:
        self._send_fn = send_fn

    def detach(self) -> None:
        self._send_fn = None
        # Cancel any pending requests
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(RuntimeError("Client disconnected"))
        self._pending.clear()

    async def request_capture(
        self, max_size: int = 1280, timeout: float = _DEFAULT_TIMEOUT,
    ) -> str:
        """Ask the frontend for a screenshot. Returns base64 JPEG string.

        Raises RuntimeError if no client is connected or the request times out.
        """
        if self._send_fn is None:
            raise RuntimeError("No client connected for screen capture relay.")

        request_id = uuid.uuid4().hex[:12]
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[str] = loop.create_future()
        self._pending[request_id] = fut

        try:
            await self._send_fn({
                "type": "capture_request",
                "request_id": request_id,
                "max_size": max_size,
            })
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            raise RuntimeError(
                f"Screen capture request timed out after {timeout}s. "
                "Is screen access enabled on the frontend?"
            )
        finally:
            self._pending.pop(request_id, None)

    def resolve(self, request_id: str, data_url: Optional[str], error: Optional[str]) -> None:
        """Called by chat_ws when a capture_response arrives from the frontend."""
        fut = self._pending.get(request_id)
        if fut is None or fut.done():
            log.warning("capture_response for unknown/expired request_id=%s", request_id)
            return
        if error:
            fut.set_exception(RuntimeError(f"Client capture failed: {error}"))
        elif data_url:
            # Strip the data URL prefix to get raw base64
            if "," in data_url:
                b64 = data_url.split(",", 1)[1]
            else:
                b64 = data_url
            fut.set_result(b64)
        else:
            fut.set_exception(RuntimeError("Client returned empty capture."))


screen_relay = ScreenCaptureRelay()
