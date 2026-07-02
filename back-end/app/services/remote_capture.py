"""Screen capture request/response over the active /ws/chat connection.

Mirrors terminal_service._request_confirm: send a request, register an
asyncio.Future, await it with a timeout. Single active connection at a time,
the same assumption CopilotService's own docstring already makes — chat_ws
assigns remote_capture_service.send_json once per connection, exactly like
the existing terminal_service.broadcast = send_json_safe line.
"""

import asyncio
import base64
import uuid
from typing import Awaitable, Callable, Optional

from app.core.config import settings

SendJson = Callable[[dict], Awaitable[None]]

THUMBNAIL_MAX_SIZE = 64


def _within_size_limit(data_url: str) -> bool:
    """Reject malformed or oversized data URLs, mirroring chat_ws._validate_images's
    MAX_IMAGE_BYTES cap for manually-attached images."""
    try:
        payload = data_url.split(",", 1)[1]
        size = len(base64.b64decode(payload, validate=False))
    except Exception:
        return False
    return size <= settings.MAX_IMAGE_BYTES


class RemoteCaptureService:
    def __init__(self) -> None:
        self.send_json: Optional[SendJson] = None
        self.last_label: str = ""
        self._pending: dict[str, asyncio.Future] = {}

    async def request(self, kind: str) -> Optional[dict]:
        """Ask the connected browser for a frame.

        Returns {"data_url": str, "label": str} on success, or None if there
        is no active connection, the user declined, or the request timed out.
        """
        if self.send_json is None:
            return None

        request_id = uuid.uuid4().hex[:12]
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = fut

        max_size = THUMBNAIL_MAX_SIZE if kind == "thumbnail" else settings.COPILOT_MAX_IMAGE_SIZE
        timeout = (
            settings.SCREEN_CAPTURE_THUMBNAIL_TIMEOUT_SECONDS
            if kind == "thumbnail"
            else settings.SCREEN_CAPTURE_FULL_TIMEOUT_SECONDS
        )

        await self.send_json({
            "type": "screen_capture_request",
            "request_id": request_id,
            "kind": kind,
            "max_size": max_size,
        })

        try:
            result = await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            result = None
        finally:
            self._pending.pop(request_id, None)

        if result and result.get("label"):
            self.last_label = result["label"]
        return result

    def resolve(self, request_id: str, data_url: Optional[str], label: str = "") -> bool:
        fut = self._pending.get(request_id)
        if fut is None or fut.done():
            return False
        result = None
        if data_url is not None and _within_size_limit(data_url):
            result = {"data_url": data_url, "label": label}
        fut.set_result(result)
        return True


remote_capture_service = RemoteCaptureService()
