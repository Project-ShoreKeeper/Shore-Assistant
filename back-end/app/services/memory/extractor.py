"""LOCOMO extractor — Local Gemma 4 API with JSON Schema/Grammar structured output."""
import asyncio
import json
import time
from pathlib import Path
from typing import Optional

import httpx

from app.core.config import settings
from app.services.memory.types import Message, WorkerOutput


class ExtractorDisabled(RuntimeError):
    """Raised when WORKER_ENABLED=False."""


_PROMPT_PATH = Path(__file__).parent.parent.parent / "prompts" / "locomo_extractor.txt"

_MAX_ATTEMPTS = 3       # initial + 2 retries
_BACKOFF_BASE_SECONDS = 1.0


class LocomoExtractor:
    def __init__(self):
        self._system_prompt: Optional[str] = None
        self._http_client: Optional[httpx.AsyncClient] = None
        
    def _ensure_client(self) -> httpx.AsyncClient:
        if not settings.WORKER_ENABLED:
            raise ExtractorDisabled("WORKER_ENABLED is False")
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=settings.WORKER_LOCAL_TIMEOUT)
        return self._http_client

    def _load_prompt(self) -> str:
        if self._system_prompt is None:
            self._system_prompt = _PROMPT_PATH.read_text(encoding="utf-8")
        return self._system_prompt

    def _build_user_content(
        self, turns: list[Message], profile_snapshot: dict,
    ) -> str:
        turns_text = "\n".join(
            f"[{m.timestamp:.2f}] {m.role}: {m.content}" for m in turns
        )
        return (
            f"Current profile snapshot (JSON):\n"
            f"{json.dumps(profile_snapshot, ensure_ascii=False)}\n\n"
            f"New turns to extract from:\n{turns_text}"
        )

    async def extract(
        self, turns: list[Message], profile_snapshot: dict,
    ) -> WorkerOutput:
        client = self._ensure_client()
        user_content = self._build_user_content(turns, profile_snapshot)

        payload = {
            "model": "gemma-4", # Name usually ignored by local llama-server
            "messages": [
                {"role": "system", "content": self._load_prompt()},
                {"role": "user", "content": user_content}
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "worker_output",
                    "schema": WorkerOutput.model_json_schema()
                }
            },
            "temperature": 0.1
        }
        
        endpoint = f"{settings.WORKER_LOCAL_LLM_URL.rstrip('/')}/chat/completions"

        last_error: Optional[BaseException] = None
        for attempt in range(_MAX_ATTEMPTS):
            started = time.monotonic()
            try:
                response = await client.post(endpoint, json=payload)
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                print(
                    f"[Extractor] attempt {attempt + 1}/{_MAX_ATTEMPTS} ok "
                    f"in {time.monotonic() - started:.1f}s "
                    f"(usage={data.get('usage')})"
                )
                return WorkerOutput.model_validate_json(content)
            except asyncio.CancelledError:
                # IMPORTANT: If the task is cancelled (e.g. new user turn), abort immediately.
                # httpx natively handles CancelledError by dropping the connection,
                # signaling the llama-server to abort inference to prevent compute contention.
                raise
            except Exception as e:
                print(
                    f"[Extractor] attempt {attempt + 1}/{_MAX_ATTEMPTS} failed "
                    f"after {time.monotonic() - started:.1f}s: {e!r}"
                )
                last_error = e
                if attempt == _MAX_ATTEMPTS - 1:
                    raise
                await asyncio.sleep(_BACKOFF_BASE_SECONDS * (2 ** attempt))
        
        # unreachable
        raise last_error  # type: ignore[misc]

    async def close(self):
        """Clean up HTTP client resources."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

