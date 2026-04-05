"""Screen capture and vision tools for the AI agent."""

from langchain_core.tools import tool


@tool
async def capture_screen(prompt: str = "Describe what you see on the screen") -> str:
    """Capture the current screen and analyze it using a vision model.
    This triggers a model hot-swap (LLM unloads, vision model loads, then swaps back).

    Args:
        prompt: What to look for or analyze in the screenshot.
    """
    from app.services.vision_service import vision_service

    try:
        result = await vision_service.analyze_screen(prompt=prompt)
        return result if result else "Could not analyze the screen."
    except Exception as e:
        return f"Error capturing/analyzing screen: {e}"


@tool
async def analyze_screen(query: str) -> str:
    """Capture the user's current screen and use a local Vision LLM to answer
    a question about what is visible on the display.

    Use this tool when the user asks about anything currently visible on their
    monitor, such as:
    - "What is on my screen?"
    - "Read the error message on my screen"
    - "What application am I looking at?"
    - "Summarize the text shown on the monitor"
    - "What code is open in my editor?"
    - "Describe what you see"

    This tool performs a full VRAM hot-swap cycle: it unloads the primary text
    model from VRAM, loads a vision model to analyze the screenshot, then
    restores the text model. This is necessary to stay within the 16GB VRAM
    budget and avoid OOM errors.

    Args:
        query: The user's question about what is on their screen. Be specific
               (e.g. "What error is shown in the terminal?" rather than just
               "Describe the screen") for more useful answers.
    """
    import base64
    import io

    try:
        import mss
        from PIL import Image
    except ImportError:
        return "Error: Required libraries (mss, Pillow) are not installed."

    try:
        # --- Step 1: Screen Capture → base64 JPEG (no disk I/O) ---
        with mss.mss() as sct:
            monitor = sct.monitors[1]  # primary monitor
            screenshot = sct.grab(monitor)

            img = Image.frombytes(
                "RGB", screenshot.size, screenshot.bgra, "raw", "BGRX"
            )

            # Down-scale to reduce token cost / inference time
            max_size = 1280
            w, h = img.size
            if max(w, h) > max_size:
                scale = max_size / max(w, h)
                img = img.resize(
                    (int(w * scale), int(h * scale)), Image.LANCZOS
                )

            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=85)
            image_b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

        # --- Steps 2-5: Hot-swap via VRAMManager ---
        from app.services.vram_manager import vram_manager

        result = await vram_manager.request_vision_inference(
            image_b64=image_b64,
            prompt=query,
        )

        return result if result else "Vision model returned an empty response."

    except Exception as e:
        return f"Error: Unable to capture or analyze the screen. Details: {e}"
