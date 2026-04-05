"""
Vision service - screen capture and vision model inference.
Uses mss for fast screen capture and delegates to VRAMManager for model orchestration.
"""

import base64
import io
from typing import Optional

from app.services.vram_manager import vram_manager


class VisionService:
    def capture_screen(self, monitor_index: int = 1, max_size: int = 1280) -> bytes:
        """
        Capture the screen and return as JPEG bytes.

        Args:
            monitor_index: Which monitor to capture (1 = primary)
            max_size: Max dimension (width or height) for the captured image

        Returns:
            JPEG-encoded image bytes
        """
        import mss
        from PIL import Image

        with mss.mss() as sct:
            monitor = sct.monitors[monitor_index]
            screenshot = sct.grab(monitor)

            # Convert to PIL Image
            img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")

            # Resize to manageable size
            w, h = img.size
            if max(w, h) > max_size:
                scale = max_size / max(w, h)
                img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

            # Encode as JPEG
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=85)
            return buffer.getvalue()

    def capture_screen_b64(self, monitor_index: int = 1, max_size: int = 1280) -> str:
        """Capture screen and return as base64-encoded JPEG string."""
        jpeg_bytes = self.capture_screen(monitor_index, max_size)
        return base64.b64encode(jpeg_bytes).decode("utf-8")

    async def analyze_screen(
        self,
        prompt: str,
        monitor_index: int = 1,
        on_status: Optional[callable] = None,
    ) -> str:
        """
        Capture screen and analyze it using the vision model via hot-swap.

        Args:
            prompt: What to look for or analyze in the screenshot
            monitor_index: Which monitor to capture
            on_status: Optional callback for status updates

        Returns:
            Vision model's text description/analysis
        """
        image_b64 = self.capture_screen_b64(monitor_index)
        return await vram_manager.request_vision_inference(
            image_b64=image_b64,
            prompt=prompt,
            on_status=on_status,
        )


vision_service = VisionService()
