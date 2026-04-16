"""Screen capture and vision tools for the AI agent."""

import base64
import io

from langchain_core.tools import tool

from app.core.config import settings


def _capture_screen_b64(max_size: int = 1280) -> str:
    """Capture primary monitor and return as base64 JPEG string."""
    import mss
    from PIL import Image

    with mss.mss() as sct:
        monitor = sct.monitors[1]
        screenshot = sct.grab(monitor)

        img = Image.frombytes(
            "RGB", screenshot.size, screenshot.bgra, "raw", "BGRX"
        )

        w, h = img.size
        if max(w, h) > max_size:
            scale = max_size / max(w, h)
            img = img.resize(
                (int(w * scale), int(h * scale)), Image.LANCZOS
            )

        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=85)
        return base64.b64encode(buffer.getvalue()).decode("utf-8")


async def _analyze_with_primary_model(prompt: str, image_b64: str) -> str:
    """Send image to the primary LLM (multimodal, no VRAM swap)."""
    from app.services.llm_service import llm_service
    return await llm_service.generate_with_image(prompt, image_b64)


async def _analyze_with_hot_swap(prompt: str, image_b64: str) -> str:
    """Send image to a dedicated vision model via VRAM hot-swap."""
    from app.services.vram_manager import vram_manager
    return await vram_manager.request_vision_inference(
        image_b64=image_b64,
        prompt=prompt,
    )


@tool
async def capture_screen(prompt: str = "Describe what you see on the screen") -> str:
    """Capture the current screen and analyze it using a vision model.

    Args:
        prompt: What to look for or analyze in the screenshot.
    """
    try:
        image_b64 = _capture_screen_b64()

        if settings.VISION_USE_PRIMARY_MODEL:
            result = await _analyze_with_primary_model(prompt, image_b64)
        else:
            result = await _analyze_with_hot_swap(prompt, image_b64)

        return result if result else "Could not analyze the screen."
    except Exception as e:
        return f"Error capturing/analyzing screen: {e}"


@tool
async def analyze_screen(query: str) -> str:
    """Capture the user's current screen and use a Vision LLM to answer
    a question about what is visible on the display.

    Use this tool when the user asks about anything currently visible on their
    monitor, such as:
    - "What is on my screen?"
    - "Read the error message on my screen"
    - "What application am I looking at?"
    - "Summarize the text shown on the monitor"
    - "What code is open in my editor?"
    - "Describe what you see"

    Args:
        query: The user's question about what is on their screen. Be specific
               (e.g. "What error is shown in the terminal?" rather than just
               "Describe the screen") for more useful answers.
    """
    try:
        image_b64 = _capture_screen_b64()

        if settings.VISION_USE_PRIMARY_MODEL:
            result = await _analyze_with_primary_model(query, image_b64)
        else:
            result = await _analyze_with_hot_swap(query, image_b64)

        return result if result else "Vision model returned an empty response."
    except Exception as e:
        return f"Error: Unable to capture or analyze the screen. Details: {e}"
