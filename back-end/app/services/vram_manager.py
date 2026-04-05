"""
VRAM Manager - orchestrates model loading/unloading within the 16GB budget.
Handles the hot-swap cycle for vision inference.
"""

import asyncio
from typing import Optional

from app.services.llm_service import llm_service
from app.core.config import settings


class VRAMManager:
    """
    Singleton that coordinates VRAM usage across all model-loading services.

    VRAM budget (16GB):
      - Faster-Whisper (base/float16): ~1.5GB (always loaded)
      - Qwen2.5-7B (Q4 via Ollama):   ~5-6GB (default, can be swapped)
      - Vision model (during swap):     ~5-6GB (temporary)
      - OS/CUDA overhead:              ~1-2GB
    """

    def __init__(self):
        self._swap_lock = asyncio.Lock()
        self.primary_model = settings.OLLAMA_MODEL
        self.vision_model = settings.VISION_MODEL

    async def _wait_for_model_unload(self, model_name: str, timeout: float = 30.0):
        """Poll Ollama /api/ps until the model is no longer loaded."""
        elapsed = 0.0
        poll_interval = 0.5
        while elapsed < timeout:
            running = await llm_service.list_running_models()
            model_names = [m.get("name", "") for m in running]
            if not any(model_name in name for name in model_names):
                return True
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
        return False

    async def request_vision_inference(
        self,
        image_b64: str,
        prompt: str,
        on_status: Optional[callable] = None,
    ) -> str:
        """
        Orchestrate the full hot-swap cycle for vision inference.

        Steps:
          1. Unload primary LLM (keep_alive=0)
          2. Wait for VRAM release
          3. Load vision model + send image
          4. Get vision response
          5. Unload vision model
          6. Reload primary LLM

        Args:
            image_b64: Base64-encoded JPEG image
            prompt: What to analyze in the image
            on_status: Optional callback for status updates

        Returns:
            Vision model's text response
        """
        async with self._swap_lock:
            import httpx

            async def emit(msg: str):
                if on_status:
                    await on_status(msg)
                print(f"[VRAM] {msg}")

            try:
                # Step 1: Unload primary LLM
                await emit("Unloading primary LLM from VRAM...")
                await llm_service.unload_model(self.primary_model)

                # Step 2: Wait for VRAM release
                await emit("Waiting for VRAM release...")
                unloaded = await self._wait_for_model_unload(self.primary_model)
                if not unloaded:
                    await emit("Warning: Primary model may not have fully unloaded")

                # Step 3-4: Load vision model and run inference
                await emit(f"Loading vision model ({self.vision_model})...")
                client = await llm_service._get_client()

                vision_response = await client.post(
                    "/api/generate",
                    json={
                        "model": self.vision_model,
                        "prompt": prompt,
                        "images": [image_b64],
                        "stream": False,
                    },
                    timeout=120.0,
                )
                vision_response.raise_for_status()
                result_text = vision_response.json().get("response", "")

                # Step 5: Unload vision model
                await emit("Unloading vision model...")
                await llm_service.unload_model(self.vision_model)
                await self._wait_for_model_unload(self.vision_model)

                # Step 6: Reload primary LLM
                await emit("Reloading primary LLM...")
                await llm_service.preload_model(self.primary_model)

                await emit("Hot-swap complete")
                return result_text

            except Exception as e:
                # Try to reload primary model even on failure
                await emit(f"Error during vision swap: {e}. Recovering...")
                try:
                    await llm_service.preload_model(self.primary_model)
                except Exception:
                    pass
                raise


vram_manager = VRAMManager()
