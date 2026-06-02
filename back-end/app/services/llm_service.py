"""
Ollama LLM streaming client using httpx.AsyncClient.
Streams tokens from Qwen2.5-7B and detects sentence boundaries for TTS chunking.
"""

import copy
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

    return template


SYSTEM_PROMPT_TEMPLATE = _load_persona_template()


def build_system_prompt() -> str:
    """Build the system prompt from persona + tool instructions."""
    return SYSTEM_PROMPT_TEMPLATE


SYSTEM_PROMPT = build_system_prompt()

# Punctuation marks that signal a sentence boundary for TTS
SENTENCE_DELIMITERS = frozenset(".!?;\n")
# Pause delimiters (comma, colon) - only split if accumulated text is long enough
PAUSE_DELIMITERS = frozenset(",:")
PAUSE_MIN_LENGTH = 40


def _parse_sse_line(line: str) -> "dict | str | None":
    """
    Parse one raw line of a Server-Sent Events stream from llama-server.

    Returns:
      - the string "[DONE]" when the server signals end-of-stream
      - a dict for a parsed JSON payload
      - None for blank lines, heartbeat/comment lines, non-data events,
        or malformed JSON (which is tolerated, not raised)
    """
    if not line or not line.strip():
        return None
    if not line.startswith("data:"):
        return None
    payload = line[len("data:"):].strip()
    if payload == "[DONE]":
        return "[DONE]"
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None


class _ToolCallAccumulator:
    """
    Absorbs tool_call deltas from an OpenAI-style streaming response.

    OpenAI sends tool_calls in increments keyed by `index`. `id`, `type`,
    and `function.name` may appear on any single delta; `function.arguments`
    arrives as concatenated string fragments. After the stream ends, call
    `finalize()` to get the assembled list with arguments parsed as a dict.
    """

    def __init__(self):
        self._by_index: dict[int, dict] = {}

    def absorb(self, deltas: list[dict]) -> None:
        for delta in deltas or []:
            idx = delta.get("index", 0)
            slot = self._by_index.setdefault(
                idx,
                {"id": None, "type": "function",
                 "function": {"name": None, "arguments_buffer": ""}},
            )
            if delta.get("id") is not None:
                slot["id"] = delta["id"]
            if delta.get("type") is not None:
                slot["type"] = delta["type"]
            fn = delta.get("function") or {}
            if fn.get("name") is not None:
                slot["function"]["name"] = fn["name"]
            if fn.get("arguments") is not None:
                slot["function"]["arguments_buffer"] += fn["arguments"]

    def finalize(self) -> list[dict]:
        out = []
        for idx in sorted(self._by_index.keys()):
            slot = self._by_index[idx]
            raw = slot["function"]["arguments_buffer"]
            try:
                parsed_args = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                parsed_args = raw  # surface malformed JSON to the caller
            out.append({
                "id": slot["id"],
                "type": slot["type"],
                "function": {
                    "name": slot["function"]["name"],
                    "arguments": parsed_args,
                },
            })
        return out

    def is_empty(self) -> bool:
        return not self._by_index


def _normalize_outgoing_messages(messages: list[dict]) -> list[dict]:
    """
    Return a deep-copied messages list where any assistant tool_calls have
    their `function.arguments` JSON-encoded to a string. OpenAI requires the
    wire format to be a string; our internal shape stores it as a dict for
    direct tool execution. The input list is not mutated.
    """
    out = copy.deepcopy(messages)
    for msg in out:
        if msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            args = fn.get("arguments")
            if isinstance(args, dict):
                fn["arguments"] = json.dumps(args)
    return out


class LLMService:
    def __init__(self):
        self.base_url = settings.LLAMA_BASE_URL
        self.model = settings.LLAMA_MODEL
        self.timeout = settings.LLAMA_TIMEOUT
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
        thinking: bool = False,
        tools: Optional[list[dict]] = None,
    ) -> AsyncGenerator[dict, None]:
        """
        Stream tokens from llama-server's OpenAI-compatible /v1/chat/completions.
        Yields dicts:
          {"type": "thinking", "token": "..."}  (from delta.reasoning_content)
          {"type": "content",  "token": "..."}  (from delta.content)
          {"type": "tool_calls", "tool_calls": [...]}  (once, after stream ends)
        """
        client = await self._get_client()

        all_messages = _normalize_outgoing_messages([
            {"role": "system", "content": system_prompt or SYSTEM_PROMPT},
            *messages,
        ])

        payload = {
            "model": self.model,
            "messages": all_messages,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
        if thinking:
            payload["reasoning_effort"] = "medium"

        accumulator = _ToolCallAccumulator()

        async with client.stream("POST", "/v1/chat/completions", json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                parsed = _parse_sse_line(line)
                if parsed is None:
                    continue
                if parsed == "[DONE]":
                    break

                choices = parsed.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}

                reasoning = delta.get("reasoning_content")
                if reasoning:
                    yield {"type": "thinking", "token": reasoning}

                content = delta.get("content")
                if content:
                    yield {"type": "content", "token": content}

                tool_call_deltas = delta.get("tool_calls")
                if tool_call_deltas:
                    accumulator.absorb(tool_call_deltas)

        if not accumulator.is_empty():
            yield {"type": "tool_calls", "tool_calls": accumulator.finalize()}



    async def stream_chat_sentences(
        self,
        messages: list[dict],
        system_prompt: Optional[str] = None,
        thinking: bool = False,
        tools: Optional[list[dict]] = None,
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

        async for chunk in self.stream_chat(messages, system_prompt, thinking=thinking, tools=tools):
            # tool_calls are yielded by stream_chat only after the stream ends,
            # so was_thinking is guaranteed to already be resolved here.
            if chunk["type"] == "tool_calls":
                yield {"type": "tool_calls", "tool_calls": chunk["tool_calls"]}
                continue

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

    async def generate_with_image(self, prompt: str, image_b64: str) -> str:
        """Send an image + prompt to the primary model for vision analysis."""
        client = await self._get_client()
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "images": [image_b64],
                }
            ],
            "stream": False,
            "options": {"num_ctx": settings.OLLAMA_NUM_CTX},
        }
        response = await client.post("/api/chat", json=payload)
        response.raise_for_status()
        return response.json().get("message", {}).get("content", "")

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
