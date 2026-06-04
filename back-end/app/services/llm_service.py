"""
llama-server LLM streaming client using httpx.AsyncClient.
Streams tokens via the OpenAI-compatible /v1/chat/completions endpoint and
detects sentence boundaries for TTS chunking.
"""

import copy
import json
import httpx
from pathlib import Path
from typing import AsyncGenerator, Optional

from app.core.config import settings
from app.services.memory.types import ContextBundle

# Load persona template from file
PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _read_prompt(name: str) -> str:
    path = PROMPTS_DIR / name
    return path.read_text(encoding="utf-8") if path.exists() else ""


# Section files appended only when at least one of their trigger tool names is
# in the retrieved tool set. This keeps the system prompt small for queries that
# don't touch the section's tools (e.g. terminal rules aren't loaded for a
# simple time question).
_SECTION_TRIGGERS: dict[str, frozenset[str]] = {
    "tools_terminal.txt": frozenset({
        "open_terminal", "send_to_terminal", "read_terminal",
        "list_terminals", "close_terminal",
    }),
    "tools_background.txt": frozenset({
        "start_background_service", "list_background_services",
        "get_background_service_logs", "stop_background_service",
    }),
}
# n8n workflow tools have dynamic names (n8n_<workflow>), so they're matched by prefix.
_N8N_SECTION = "tools_n8n.txt"

# Cache file contents at import time so we don't hit disk per request.
_PERSONA_TEXT = _read_prompt(f"{settings.PERSONA}.txt") or _read_prompt("base.txt")
_USER_TEXT = _read_prompt("user.txt")
_CORE_TOOLS_TEXT = _read_prompt("tools_core.txt")
_SECTION_CACHE: dict[str, str] = {name: _read_prompt(name) for name in _SECTION_TRIGGERS}
_SECTION_CACHE[_N8N_SECTION] = _read_prompt(_N8N_SECTION)


def _format_memory_block(bundle: "ContextBundle") -> str:
    """Render the [Profile] + [Relevant memories] section appended to system prompt."""
    lines: list[str] = []
    if bundle.profile:
        lines.append("[Profile]")
        # Compact JSON: prune_profile caps size by compact bytes, so render the
        # same way to keep the cap honest. ensure_ascii=False keeps Vietnamese
        # / non-ASCII content readable to the LLM (vs \uXXXX escapes).
        lines.append(json.dumps(bundle.profile, ensure_ascii=False))
    if bundle.episodic_hits:
        if lines:
            lines.append("")
        lines.append("[Relevant memories]")
        for sf in bundle.episodic_hits:
            tags = ", ".join(sf.fact.entity_tags) if sf.fact.entity_tags else "—"
            lines.append(f"- {sf.fact.fact} [tags: {tags}]")
    return "\n".join(lines)


def build_system_prompt(
    retrieved_tool_names: list[str] | None = None,
    memory_bundle: "ContextBundle | None" = None,
) -> str:
    """Assemble the system prompt.

    retrieved_tool_names=None signals no-tools mode (notifications): persona +
    user context only, no tool rules. memory_bundle=None means no memory
    block; otherwise append [Profile] + [Relevant memories].
    """
    parts = [_PERSONA_TEXT]
    if retrieved_tool_names is not None:
        if _CORE_TOOLS_TEXT:
            parts.append(_CORE_TOOLS_TEXT)
        names = set(retrieved_tool_names)
        for section_name, triggers in _SECTION_TRIGGERS.items():
            if names & triggers and _SECTION_CACHE[section_name]:
                parts.append(_SECTION_CACHE[section_name])
        if _SECTION_CACHE[_N8N_SECTION] and any(
            n.startswith("n8n_") for n in names
        ):
            parts.append(_SECTION_CACHE[_N8N_SECTION])
    if _USER_TEXT:
        parts.append(_USER_TEXT)
    if memory_bundle is not None:
        mem_block = _format_memory_block(memory_bundle)
        if mem_block:
            parts.append(mem_block)
    return "\n\n".join(p for p in parts if p)


# Fallback used when stream_chat / generate_once are called without an explicit
# system prompt. Defaults to persona + user context (no tool rules).
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
        Stream from llama-server, yielding individual tokens (thinking + content)
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

        all_messages = _normalize_outgoing_messages([
            {"role": "system", "content": system_prompt or SYSTEM_PROMPT},
            *messages,
        ])
        payload = {
            "model": self.model,
            "messages": all_messages,
            "stream": False,
        }

        response = await client.post("/v1/chat/completions", json=payload)
        response.raise_for_status()
        data = response.json()
        choices = data.get("choices") or [{}]
        return choices[0].get("message", {}).get("content", "")

    async def generate_with_image(self, prompt: str, image_b64: str) -> str:
        """Send a prompt + base64 JPEG to the primary multimodal LLM."""
        client = await self._get_client()
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                        },
                    ],
                }
            ],
            "stream": False,
        }
        response = await client.post("/v1/chat/completions", json=payload)
        response.raise_for_status()
        data = response.json()
        choices = data.get("choices") or [{}]
        return choices[0].get("message", {}).get("content", "")

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None


llm_service = LLMService()
