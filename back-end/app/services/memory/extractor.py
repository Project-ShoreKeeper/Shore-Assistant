"""LOCOMO extractor — Gemini 2.5 Flash with JSON-mode structured output."""
import asyncio
import json
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types as genai_types

from app.core.config import settings
from app.services.memory.types import Message, WorkerOutput


class ExtractorDisabled(RuntimeError):
    """Raised when WORKER_ENABLED=False or GEMINI_API_KEY missing."""


_PROMPT_PATH = Path(__file__).parent.parent.parent / "prompts" / "locomo_extractor.txt"

_MAX_ATTEMPTS = 3       # initial + 2 retries
_BACKOFF_BASE_SECONDS = 1.0


class LocomoExtractor:
    def __init__(self):
        self._client: Optional["genai.Client"] = None
        self._system_prompt: Optional[str] = None

    def _ensure_client(self) -> "genai.Client":
        if not settings.WORKER_ENABLED:
            raise ExtractorDisabled("WORKER_ENABLED is False")
        if not settings.GEMINI_API_KEY:
            raise ExtractorDisabled("GEMINI_API_KEY is empty")
        if self._client is None:
            self._client = genai.Client(api_key=settings.GEMINI_API_KEY)
        return self._client

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

        last_error: Optional[BaseException] = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                response = await asyncio.wait_for(
                    client.aio.models.generate_content(
                        model=settings.WORKER_GEMINI_MODEL,
                        contents=[
                            genai_types.Content(
                                role="user",
                                parts=[genai_types.Part(text=user_content)],
                            )
                        ],
                        config=genai_types.GenerateContentConfig(
                            system_instruction=self._load_prompt(),
                            response_mime_type="application/json",
                            response_schema=WorkerOutput,
                        ),
                    ),
                    timeout=settings.WORKER_GEMINI_TIMEOUT,
                )
                return WorkerOutput.model_validate_json(response.text)
            except (asyncio.TimeoutError, Exception) as e:
                last_error = e
                if attempt == _MAX_ATTEMPTS - 1:
                    raise
                await asyncio.sleep(_BACKOFF_BASE_SECONDS * (2 ** attempt))
        # unreachable
        raise last_error  # type: ignore[misc]
