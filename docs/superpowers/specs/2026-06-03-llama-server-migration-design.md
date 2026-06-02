# Migrate LLM client from Ollama to llama-server

**Date:** 2026-06-03
**Branch:** `feat/llama-server-migration` (from `feat/native-tool-calling`)
**Status:** Draft

## Summary

Replace the Ollama HTTP client with llama.cpp `llama-server` using its
OpenAI-compatible `/v1/chat/completions` endpoint. Remove the VRAM hot-swap
subsystem because llama-server hosts one model per instance. Vision continues
to work by sending images to the primary model (which must be multimodal).

This is a clean break — Ollama support is removed entirely, no compatibility
flag.

## Goals

- Backend talks to llama-server (OpenAI-compatible) instead of Ollama.
- Streaming, tool calling, thinking/reasoning, and vision all keep working.
- Public surface of `LLMService` (the methods agent_service consumes) stays
  the same shape so the agent loop doesn't need restructuring.

## Non-goals

- No backward compatibility with Ollama.
- No multi-instance / multi-port setup for separate vision model. Vision
  uses the primary model only.
- No changes to STT, TTS, scheduler, n8n, memory, or frontend.

## Architecture changes

### Before

```
agent_service ──► llm_service ──HTTP──► Ollama (/api/chat, /api/generate, /api/ps)
                       ▲
vram_manager ──────────┘  (hot-swap unload/preload via /api/generate keep_alive)
screen_tools ──► vram_manager OR llm_service.generate_with_image
```

### After

```
agent_service ──► llm_service ──HTTP──► llama-server (/v1/chat/completions)
screen_tools  ──► llm_service.generate_with_image
```

`vram_manager.py` is deleted. `screen_tools.py` always routes vision through
`llm_service.generate_with_image`.

## File-by-file changes

### `app/core/config.py`

Remove:

- `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `OLLAMA_TIMEOUT`, `OLLAMA_NUM_CTX`
- `VISION_MODEL`, `VISION_USE_PRIMARY_MODEL`

Add:

- `LLAMA_BASE_URL: str = "http://localhost:8080"`
- `LLAMA_MODEL: str = ""` — llama-server typically ignores the `model` field
  (one model per instance). Kept as a configurable label that is sent in the
  payload and displayed via `/config`.
- `LLAMA_TIMEOUT: int = 120`

Note: `num_ctx` is dropped from the per-request payload because llama-server
sets `n_ctx` at process startup (`--ctx-size`). It is not a request-level
parameter in the OpenAI API.

### `app/services/llm_service.py`

Rewrite the HTTP layer. Keep the public methods (`stream_chat`,
`stream_chat_sentences`, `generate_once`, `generate_with_image`, `close`)
and their output shapes unchanged so `agent_service.py` only needs the small
edit described below.

Remove: `unload_model`, `preload_model`, `list_running_models`.

**Endpoint:** `POST /v1/chat/completions`.

**Request payload (streaming):**

```json
{
  "model": "<settings.LLAMA_MODEL>",
  "messages": [...],
  "stream": true,
  "tools": [...],
  "reasoning_effort": "medium"   // only when thinking=true; omit otherwise
}
```

**Thinking:** map `thinking=True` → `reasoning_effort: "medium"`. Omit the
field when `thinking=False`. This is the OpenAI extension that llama.cpp
respects for reasoning models. If a specific model needs
`chat_template_kwargs: {enable_thinking: true}` instead, that is a follow-up
tweak — not done by default to keep the payload OpenAI-clean.

**SSE parsing:**

- Read lines with `response.aiter_lines()`.
- Strip the `data: ` prefix on each non-empty line.
- Stop on `data: [DONE]`.
- Parse each remaining line as JSON.

**Per-chunk extraction from `choices[0].delta`:**

- `content` → yield `{"type": "content", "token": ...}`
- `reasoning_content` → yield `{"type": "thinking", "token": ...}`
- `tool_calls[]` → accumulate (see below); do **not** yield per chunk.

**Tool call accumulation:**

OpenAI streams tool calls as deltas keyed by `index`. The `arguments` field
arrives as incremental string fragments. The accumulator:

1. Maintain a dict `accum: {int_index: {"id": str, "type": "function",
   "function": {"name": str, "arguments_buffer": str}}}`.
2. For each delta tool_call, fill in `id` and `function.name` when they
   appear; append `function.arguments` fragments to `arguments_buffer`.
3. After the stream ends (or on `finish_reason=="tool_calls"`), convert
   each accumulator entry to:
   `{"id": ..., "function": {"name": ..., "arguments": <json.loads(buffer)>}}`
   and yield as `{"type": "tool_calls", "tool_calls": [...]}`.

`json.loads` is wrapped in try/except — if a model emits malformed JSON the
raw string is passed through and the tool layer logs the error.

This keeps the yielded shape identical to what the current Ollama path
produces (a list of `{id, function:{name, arguments:dict}}` dicts), so
`agent_service.py` keeps reading `tc.get("function", {}).get("arguments", {})`
as a dict.

**Outgoing normalization.** OpenAI requires `function.arguments` to be a
JSON **string** on the request wire, but our internal shape stores it as a
dict (so agent_service can pass it directly to tool execution). Before
posting the request, `stream_chat` walks `all_messages` and, for any
assistant message with `tool_calls`, replaces dict `function.arguments`
with `json.dumps(arguments)`. This is a small helper applied to a copy of
the messages list so the in-memory history (kept by agent_service) is not
mutated. `generate_once` applies the same helper.

**`generate_once`:** `POST /v1/chat/completions` with `stream: false`. Read
`choices[0].message.content`.

**`generate_with_image`:** same endpoint with a content array:

```json
{
  "role": "user",
  "content": [
    {"type": "text", "text": "<prompt>"},
    {"type": "image_url",
     "image_url": {"url": "data:image/jpeg;base64,<image_b64>"}}
  ]
}
```

Requires llama-server built with vision support and an mmproj loaded.

### `app/services/vram_manager.py`

Delete entirely.

### `app/services/agent_service.py`

Single edit: the tool-result message append. Currently:

```python
messages.append({"role": "tool", "content": result, "tool_name": tool_name})
```

Change to:

```python
messages.append({"role": "tool", "content": result, "tool_call_id": tc["id"]})
```

This is the OpenAI tool-result format. `tc["id"]` comes from the accumulated
tool_calls (each `id` is preserved by the accumulator). Loop variable
restructuring is minimal — the inner loop already iterates over
`pending_tool_calls`.

### `app/tools/screen_tools.py`

- Delete `_analyze_with_hot_swap`.
- Delete the `settings.VISION_USE_PRIMARY_MODEL` branch in both
  `capture_screen` and `analyze_screen`.
- Both tools call `_analyze_with_primary_model` unconditionally.

### `app/api/endpoints/health.py`

`settings.OLLAMA_MODEL` → `settings.LLAMA_MODEL` in the `/config` response.

### `CLAUDE.md`

Update the docs:

- Replace "Ollama" mentions in the architecture diagram and "External
  Dependencies" with llama-server.
- Replace the config table rows for `OLLAMA_*` and `VISION_*` with the new
  `LLAMA_*` rows.
- Remove the "VRAM hot-swap" / "Vision via primary model" entries from the
  Backlog "done" list — replace with a single line about llama-server +
  multimodal primary.
- Note that llama-server must be started with `--jinja` (tool calling) and
  with vision support (mmproj) for the screen tools to work.

### `.env` / `.env.example`

If present, swap `OLLAMA_*` keys to `LLAMA_*`. Not committing real `.env`.

## Out of scope

- A new test file for `llm_service.py`. Existing tests stay; if any break,
  fix during implementation. New unit tests for SSE parsing / tool-call
  accumulation are nice-to-have but not required for this migration.
- Multi-instance setup for separate vision model.
- Switching cloud sub-agent services (Anthropic / Gemini / OpenAI) —
  unaffected.

## Risks and verification

1. **`reasoning_effort` not honored by some builds.** If thinking doesn't
   stream, the fallback is to set `chat_template_kwargs.enable_thinking=true`
   (Qwen-style) or to ensure the server is launched with the right flags.
   Documented inline in the code.
2. **Tool calling requires `--jinja`.** llama-server only emits tool_calls
   when launched with `--jinja` and a chat template that supports tools
   (Qwen2.5, Llama 3.1+, Hermes, etc.). To be called out in CLAUDE.md.
3. **Vision requires mmproj.** Without an mmproj loaded, `image_url`
   content is ignored and the model will hallucinate. To be called out in
   CLAUDE.md.
4. **Streaming JSON arguments may be malformed mid-stream.** Only
   `json.loads` once after the full string is assembled, never on partial
   buffers.

## Acceptance criteria

- Backend boots without importing Ollama anywhere (`grep -ri "ollama" back-end/app`
  returns no source-level hits other than comments removed by this PR).
- `agent_service` streams tokens, executes a tool round-trip, and returns a
  final answer against a running llama-server.
- `analyze_screen` returns a plausible description when the primary model
  is multimodal.
- `/config` returns `{"llm_model": "<LLAMA_MODEL value>"}`.
- `vram_manager.py` is gone; no import remains.
