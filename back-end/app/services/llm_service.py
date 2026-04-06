"""
Ollama LLM streaming client using httpx.AsyncClient.
Streams tokens from Qwen2.5-7B and detects sentence boundaries for TTS chunking.
"""

import json
import httpx
from pathlib import Path
from typing import AsyncGenerator, Optional

from app.core.config import settings

# Load persona template from file
PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _load_persona_template() -> str:
    """Load the system prompt template for the configured persona, plus tool instructions and user context."""
    persona_file = PROMPTS_DIR / f"{settings.PERSONA}.txt"
    if not persona_file.exists():
        print(f"[LLM] Persona '{settings.PERSONA}' not found, falling back to 'base'")
        persona_file = PROMPTS_DIR / "base.txt"
    template = persona_file.read_text(encoding="utf-8")

    # Append tool instructions
    tools_file = PROMPTS_DIR / "tools.txt"
    if tools_file.exists():
        template += "\n\n" + tools_file.read_text(encoding="utf-8")

    # Append user context if it exists
    user_file = PROMPTS_DIR / "user.txt"
    if user_file.exists():
        template += "\n\n" + user_file.read_text(encoding="utf-8")

    print(f"[LLM] Loaded persona: {settings.PERSONA}")
    return template


SYSTEM_PROMPT_TEMPLATE = _load_persona_template()


def build_system_prompt(tool_descriptions: str) -> str:
    """Build a system prompt with only the relevant tool descriptions."""
    return SYSTEM_PROMPT_TEMPLATE.replace("{tools}", tool_descriptions)


# Legacy fallback
SYSTEM_PROMPT = build_system_prompt("(no tools loaded)")

# Punctuation marks that signal a sentence boundary for TTS
SENTENCE_DELIMITERS = frozenset(".!?;\n")
# Pause delimiters (comma, colon) - only split if accumulated text is long enough
PAUSE_DELIMITERS = frozenset(",:")
PAUSE_MIN_LENGTH = 40


class LLMService:
    def __init__(self):
        self.base_url = settings.OLLAMA_BASE_URL
        self.model = settings.OLLAMA_MODEL
        self.timeout = settings.OLLAMA_TIMEOUT
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout, connect=10.0),
            )
        return self._client

    async def stream_chat(
        self,
        messages: list[dict],
        system_prompt: Optional[str] = None,
    ) -> AsyncGenerator[dict, None]:
        """
        Stream tokens from Ollama chat API.
        Yields dicts: {"type": "thinking"|"content", "token": "..."}
        """
        client = await self._get_client()

        all_messages = [
            {"role": "system", "content": system_prompt or SYSTEM_PROMPT},
            *messages,
        ]

        payload = {
            "model": self.model,
            "messages": all_messages,
            "stream": True,
            "options": {"num_ctx": settings.OLLAMA_NUM_CTX},
            "think": False,
        }

        # ── DEBUG: dump what we send to Ollama ──
        print(f"\n{'='*60}")
        print(f"[LLM] REQUEST to Ollama ({self.model})")
        print(f"[LLM]   Message count: {len(all_messages)}")
        for i, m in enumerate(all_messages):
            role = m["role"]
            content = m["content"]
            preview = content[:120].replace("\n", "\\n")
            print(f"[LLM]   [{i}] {role}: {preview}...")
        print(f"{'='*60}\n")

        token_count = 0
        thinking_token_count = 0
        line_count = 0
        async with client.stream("POST", "/api/chat", json=payload) as response:
            print(f"[LLM] HTTP status: {response.status_code}")
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                line_count += 1
                try:
                    data = json.loads(line)

                    # Log first few lines and the done line raw
                    if line_count <= 3 or data.get("done"):
                        print(f"[LLM] RAW line {line_count}: {line[:300]}")

                    if data.get("done"):
                        done_reason = data.get("done_reason", "unknown")
                        eval_count = data.get("eval_count", "?")
                        prompt_eval_count = data.get("prompt_eval_count", "?")
                        print(f"[LLM] DONE — reason: {done_reason}, content tokens: {token_count}, thinking tokens: {thinking_token_count}")
                        print(f"[LLM]   prompt_eval_count: {prompt_eval_count}, eval_count: {eval_count}")
                        break

                    msg = data.get("message", {})
                    thinking_token = msg.get("thinking", "")
                    content_token = msg.get("content", "")

                    if thinking_token:
                        thinking_token_count += 1
                        yield {"type": "thinking", "token": thinking_token}
                    if content_token:
                        token_count += 1
                        yield {"type": "content", "token": content_token}
                except json.JSONDecodeError:
                    print(f"[LLM] WARNING: JSON decode error on line: {line[:200]}")
                    continue

        if token_count == 0 and thinking_token_count == 0:
            print(f"[LLM] WARNING: LLM produced ZERO tokens! (lines received: {line_count})")

    async def stream_chat_sentences(
        self,
        messages: list[dict],
        system_prompt: Optional[str] = None,
    ) -> AsyncGenerator[dict, None]:
        """
        Stream from Ollama, yielding individual tokens (thinking + content)
        and completed sentences (content only, for TTS).

        Yields dicts:
          {"type": "thinking_token", "token": "...", "accumulated": "..."}
          {"type": "thinking_done", "text": "..."}  (when thinking phase ends)
          {"type": "token", "token": "...", "accumulated": "..."}
          {"type": "sentence", "text": "..."}
          {"type": "done", "full_text": "..."}
        """
        accumulated = ""
        thinking_accumulated = ""
        sentence_buffer = ""
        was_thinking = False

        async for chunk in self.stream_chat(messages, system_prompt):
            token = chunk["token"]

            if chunk["type"] == "thinking":
                thinking_accumulated += token
                was_thinking = True
                yield {"type": "thinking_token", "token": token, "accumulated": thinking_accumulated}
                continue

            # If we were thinking and now got a content token, emit thinking_done
            if was_thinking:
                was_thinking = False
                yield {"type": "thinking_done", "text": thinking_accumulated}

            # Content token
            accumulated += token
            sentence_buffer += token

            yield {"type": "token", "token": token, "accumulated": accumulated}

            # Check for sentence boundaries
            if any(c in token for c in SENTENCE_DELIMITERS):
                sentence = sentence_buffer.strip()
                if sentence:
                    yield {"type": "sentence", "text": sentence}
                sentence_buffer = ""
            elif (
                any(c in token for c in PAUSE_DELIMITERS)
                and len(sentence_buffer) >= PAUSE_MIN_LENGTH
            ):
                sentence = sentence_buffer.strip()
                if sentence:
                    yield {"type": "sentence", "text": sentence}
                sentence_buffer = ""

        # If the model only produced thinking tokens (no content), emit thinking_done
        if was_thinking:
            yield {"type": "thinking_done", "text": thinking_accumulated}

        # Flush remaining buffer
        if sentence_buffer.strip():
            yield {"type": "sentence", "text": sentence_buffer.strip()}

        yield {"type": "done", "full_text": accumulated, "thinking_text": thinking_accumulated}

    async def generate_once(
        self,
        messages: list[dict],
        system_prompt: Optional[str] = None,
    ) -> str:
        """Non-streaming single response (for intent classification, etc.)."""
        client = await self._get_client()

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt or SYSTEM_PROMPT},
                *messages,
            ],
            "stream": False,
            "options": {"num_ctx": settings.OLLAMA_NUM_CTX},
            "think": False,
        }

        response = await client.post("/api/chat", json=payload)
        response.raise_for_status()
        data = response.json()
        return data.get("message", {}).get("content", "")

    async def unload_model(self, model: Optional[str] = None):
        """Unload a model from VRAM using keep_alive=0."""
        client = await self._get_client()
        payload = {
            "model": model or self.model,
            "keep_alive": 0,
        }
        response = await client.post("/api/generate", json=payload)
        response.raise_for_status()

    async def preload_model(self, model: Optional[str] = None):
        """Preload a model into VRAM."""
        client = await self._get_client()
        payload = {
            "model": model or self.model,
            "keep_alive": "5m",
        }
        response = await client.post("/api/generate", json=payload)
        response.raise_for_status()

    async def list_running_models(self) -> list[dict]:
        """List models currently loaded in VRAM."""
        client = await self._get_client()
        response = await client.get("/api/ps")
        response.raise_for_status()
        return response.json().get("models", [])

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None


llm_service = LLMService()
