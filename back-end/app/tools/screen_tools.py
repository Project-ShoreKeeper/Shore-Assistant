"""Screen capture and vision tools for the AI agent.

Screenshots come from the connected browser via RemoteCaptureService
(getDisplayMedia in the frontend), not from the backend host's display.
"""

from langchain_core.tools import tool

from app.services.remote_capture import remote_capture_service


async def _capture_screen_b64() -> str | None:
    """Request a full-resolution screenshot from the connected browser.

    Returns the base64 JPEG payload, or None if the user declined the
    consent prompt / getDisplayMedia, or the request timed out.
    """
    result = await remote_capture_service.request("full")
    if result is None:
        return None
    return result["data_url"].split(",", 1)[1]


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
        if image_b64 is None:
            return "Screen sharing was declined or timed out."
        result = await _analyze(prompt, image_b64)
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
        image_b64 = await _capture_screen_b64()
        if image_b64 is None:
            return "Screen sharing was declined or timed out."
        result = await _analyze(query, image_b64)
        return result if result else "Vision model returned an empty response."
    except Exception as e:
        return f"Error: Unable to capture or analyze the screen. Details: {e}"
