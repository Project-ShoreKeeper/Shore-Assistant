"""Screen capture and vision tools for the AI agent.

Screen capture happens client-side (browser getDisplayMedia) and is relayed
over /ws/chat via screenshot_bridge -- the backend host has no guaranteed
display of its own.
"""

from langchain_core.tools import tool

from app.services.screenshot_bridge import ScreenshotUnavailable, screenshot_bridge


async def _capture_screen_b64() -> str:
    """Request a screenshot from the connected client; return raw base64 (no data: prefix)."""
    data_url = await screenshot_bridge.request()
    return data_url.split(",", 1)[1] if "," in data_url else data_url


async def _analyze(prompt: str, image_b64: str) -> str:
    """Send image to the primary multimodal LLM via llama-server."""
    from app.services.llm_service import llm_service
    return await llm_service.generate_with_image(prompt, image_b64)


@tool
async def capture_screen(prompt: str = "Describe what you see on the screen") -> str:
    """Capture the current screen and analyze it using the vision-capable primary model.

    Args:
        prompt: What to look for or analyze in the screenshot.
    """
    try:
        image_b64 = await _capture_screen_b64()
        result = await _analyze(prompt, image_b64)
        return result if result else "Could not analyze the screen."
    except ScreenshotUnavailable as e:
        return f"Error: Unable to capture the screen. {e}"
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
        image_b64 = await _capture_screen_b64()
        result = await _analyze(query, image_b64)
        return result if result else "Vision model returned an empty response."
    except ScreenshotUnavailable as e:
        return f"Error: Unable to capture the screen. {e}"
    except Exception as e:
        return f"Error: Unable to capture or analyze the screen. Details: {e}"
