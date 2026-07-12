"""Manual smoke: does llama-server accept json_schema + an image together?

Run with the real llama-server up:
    cd back-end && python tests/smoke_json_schema_image.py

Prints the parsed ComputerUseAction JSON on success, or the raw error. This is
NOT a pytest test (needs a live GPU llama-server); it is a manual spike.
"""
import asyncio
import base64
import io
import json

import httpx

from app.core.config import settings
from app.services.computer_use_service import ComputerUseAction


def _tiny_png_b64() -> str:
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (200, 120), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([20, 20, 120, 60], outline="black")
    d.text((30, 35), "[0] OK button", fill="black")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


async def main():
    base = settings.WORKER_LOCAL_LLM_URL.rstrip("/").rsplit("/v1", 1)[0]
    payload = {
        "model": "gemma-4",
        "messages": [
            {"role": "system", "content": "Return the next action as JSON."},
            {"role": "user", "content": [
                {"type": "text", "text":
                 "GOAL: click OK. ELEMENTS:\n[0] icon \"OK button\" interactable"},
                {"type": "image_url", "image_url":
                 {"url": f"data:image/jpeg;base64,{_tiny_png_b64()}"}},
            ]},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "computer_use_action",
                "schema": ComputerUseAction.model_json_schema(),
            },
        },
        "temperature": 0.1,
        "stream": False,
    }
    async with httpx.AsyncClient(base_url=base, timeout=60.0) as client:
        resp = await client.post("/v1/chat/completions", json=payload)
        print("HTTP", resp.status_code)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        print("RAW:", content)
        action = ComputerUseAction.model_validate_json(content)
        print("PARSED:", action.model_dump())


if __name__ == "__main__":
    asyncio.run(main())
