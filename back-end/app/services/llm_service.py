"""
Ollama LLM streaming client using httpx.AsyncClient.
Streams tokens from Qwen2.5-7B and detects sentence boundaries for TTS chunking.
"""

import json
import httpx
from typing import AsyncGenerator, Optional

from app.core.config import settings

SYSTEM_PROMPT = """You are Shore, a personal AI assistant running locally on the user's computer. You have access to the user's system through tools.

When you need to use a tool, respond with a JSON block in this exact format:
```tool
{"tool": "tool_name", "args": {"arg1": "value1"}}
```

Available tools:
- get_system_time: Get the current system date and time. No arguments needed.
- read_file: Read the contents of a file. Args: {"file_path": "path/to/file"}
- list_directory: List files and folders in a directory. Args: {"directory_path": "path/to/dir"}
- search_web: Search the web using DuckDuckGo. Args: {"query": "search query"}
- web_scrape: Fetch a web page and extract its full text content. Use after search_web when a snippet isn't enough, or when the user gives you a URL to read. Args: {"url": "https://example.com/page"}
- capture_screen: Capture and analyze what's on screen. Args: {"prompt": "what to look for"}
- analyze_screen: Capture the screen and answer a question about what is visible. Use when the user asks "what's on my screen", "read this error", "what app am I looking at", etc. Args: {"query": "specific question about the screen"} — query MUST NOT be empty.

Rules:
- Be concise and helpful.
- Only use tools when necessary.
- After receiving a tool result, synthesize it into a natural response.
- Respond in the same language the user speaks."""

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
    ) -> AsyncGenerator[str, None]:
        """
        Stream tokens from Ollama chat API.
        Yields individual tokens as they arrive.
        """
        client = await self._get_client()

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt or SYSTEM_PROMPT},
                *messages,
            ],
            "stream": True,
        }

        async with client.stream("POST", "/api/chat", json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    if data.get("done"):
                        break
                    token = data.get("message", {}).get("content", "")
                    if token:
                        yield token
                except json.JSONDecodeError:
                    continue

    async def stream_chat_sentences(
        self,
        messages: list[dict],
        system_prompt: Optional[str] = None,
    ) -> AsyncGenerator[dict, None]:
        """
        Stream from Ollama, yielding both individual tokens and completed sentences.

        Yields dicts:
          {"type": "token", "token": "...", "accumulated": "..."}
          {"type": "sentence", "text": "..."}
          {"type": "done", "full_text": "..."}
        """
        accumulated = ""
        sentence_buffer = ""

        async for token in self.stream_chat(messages, system_prompt):
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

        # Flush remaining buffer
        if sentence_buffer.strip():
            yield {"type": "sentence", "text": sentence_buffer.strip()}

        yield {"type": "done", "full_text": accumulated}

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
