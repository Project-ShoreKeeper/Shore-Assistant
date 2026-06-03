# Cloud Sub-Agent Design

**Date:** 2026-04-21  
**Branch:** feat/native-tool-calling  
**Status:** Approved

## Summary

Add cloud AI models (Claude, Gemini, OpenAI) as callable sub-agents that Gemma4:e4b can delegate hard tasks to. Gemma4 remains the orchestrator — it decides when to escalate via explicit tool calls, guided by system prompt instructions.

## Architecture

```
User voice/text
      ↓
  Gemma4:e4b (Orchestrator via Ollama)
      ↓ native tool call
  execute_tool() in agent_service.py
      ↓
  ask_claude / ask_gemini / ask_openai  ← new LangChain tools
      ↓
  CloudLLMService (cloud_llm_service.py)
      ├── AnthropicClient  → claude-sonnet-4-6 (primary)
      ├── GeminiClient     → gemini-2.0-flash
      └── OpenAIClient     → gpt-4o
      ↓ returns string answer
  Gemma4 receives result as tool_result, synthesizes final response → TTS
```

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Escalation trigger | Gemma4 explicit tool call + system prompt instruction (Option D) | Keeps Gemma4 as true orchestrator; avoids routing classifier latency on every request |
| Cloud interaction model | Context-aware single shot (Option C) | Full conversation history passed to cloud model for quality; no multi-step sub-agent complexity |
| Implementation pattern | Shared `CloudLLMService` + thin tool wrappers | Single place for context packing, API calls, and error handling |
| History injection | Python `contextvars.ContextVar` | Async-safe, no changes to `execute_tool()` signature, tools remain self-contained |
| Primary cloud model | Claude (Anthropic) — user has Pro plan | Fallbacks: Gemini, OpenAI |

## New Files

### `back-end/app/services/cloud_llm_service.py`

- `CloudLLMService` class with one async method per provider: `call_claude()`, `call_gemini()`, `call_openai()`
- Shared context packing: converts Shore's conversation history to each provider's message format
- Shore persona injected as system prompt so cloud models respond in-character as sub-agents
- History trimmed to last 10 turns (configurable via `CLOUD_HISTORY_MAX_TURNS`) to control token costs
- Error handling: API failures return descriptive error string; Gemma4 handles gracefully as tool result
- `current_history_var: ContextVar[list[dict]]` — set by agent_service before tool loop, read by tools

### `back-end/app/tools/cloud_tools.py`

Three `@tool` async functions: `ask_claude`, `ask_gemini`, `ask_openai`.

Each tool:
1. Reads history from `current_history_var`
2. Calls the corresponding `CloudLLMService` method
3. Returns the cloud model's answer as a plain string

Tool docstrings are written for embedding-based retrieval — they semantically match queries like "complex", "hard", "reason", "analyze", "write code".

```python
@tool
async def ask_claude(question: str) -> str:
    """Delegate a complex or difficult question to Claude (Anthropic).
    Use when the task requires deep reasoning, advanced coding, nuanced analysis,
    or when you are uncertain about your answer."""
    ...

@tool
async def ask_gemini(question: str) -> str:
    """Delegate to Gemini (Google). Best for large document analysis,
    long context tasks, or when Claude is unavailable."""
    ...

@tool
async def ask_openai(question: str) -> str:
    """Delegate to GPT-4o (OpenAI). Use as fallback when other cloud models
    are unavailable."""
    ...
```

## Changed Files

### `back-end/app/tools/__init__.py`
- Import and register `ask_claude`, `ask_gemini`, `ask_openai` in `ALL_TOOLS`

### `back-end/app/services/agent_service.py`
- Set `current_history_var` with current `messages` before each tool execution loop

### `back-end/app/prompts/kuudere.txt` (and `base.txt`)
- Append escalation instruction:
  > "You have access to ask_claude, ask_gemini, and ask_openai tools. When a task requires deep reasoning, complex code generation, nuanced writing, or you are not confident in your answer — delegate to ask_claude. Pass the user's full question as-is. Present the answer naturally."

### `back-end/app/core/config.py`
- Add: `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY`, `CLOUD_MAX_TOKENS` (default 4096), `CLOUD_HISTORY_MAX_TURNS` (default 10)

### `back-end/.env` (not committed)
- Add API key values

## Call Flow

1. User asks something hard (e.g. "write me a recursive descent parser in Rust")
2. Gemma4 emits `tool_call: ask_claude(question="write me a recursive descent parser in Rust")`
3. `agent_service` dispatches via `execute_tool("ask_claude", {"question": "..."})`
4. `ask_claude` reads history from `current_history_var`, calls `CloudLLMService.call_claude()`
5. Anthropic SDK sends request: Shore persona + trimmed history + question
6. Claude returns answer → returned as string tool result
7. Gemma4 receives result, synthesizes and presents to user → TTS

## Configuration Reference

| Variable | Default | Description |
|----------|---------|-------------|
| ANTHROPIC_API_KEY | "" | Anthropic API key |
| GEMINI_API_KEY | "" | Google Gemini API key |
| OPENAI_API_KEY | "" | OpenAI API key |
| CLOUD_MAX_TOKENS | 4096 | Max tokens per cloud response |
| CLOUD_HISTORY_MAX_TURNS | 10 | Conversation turns sent as context |

## Out of Scope

- Cloud models running their own tool loops (sub-agent B pattern) — deferred
- Automatic pre-routing classifier (C pattern) — may be added later if Gemma4 overconfidence becomes a problem
- Streaming cloud responses token-by-token to TTS — cloud tools return complete strings; Gemma4 narrates
- Voice selection or persona switching per provider
