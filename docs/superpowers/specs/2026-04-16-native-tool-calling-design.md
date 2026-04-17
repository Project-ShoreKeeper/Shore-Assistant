# Native Tool Calling & Tool Action UI Redesign

**Date:** 2026-04-16
**Status:** Approved

## Problem

1. **Format pollution** — The LLM wraps tool calls in conversational text (e.g., "Let me search that for you: ```tool ...```"), breaking the regex parser in `agent_service.py`.
2. **Tool call skipping** — The LLM answers time-related questions from memory instead of calling `get_system_time`, despite prompt instructions.
3. **Dated UI** — The `AgentActionLog` component is a monospace terminal-style log with ASCII icons, not matching modern AI assistant UX patterns.

## Solution

Switch from prompt-based tool calling (` ```tool ``` ` markdown blocks parsed by regex) to **Ollama's native tool calling API** (`tools` parameter), and redesign the frontend tool action display as **collapsible inline cards**.

## Architecture

### Backend: Native Tool Calling

#### `tool_retriever.py`

- New method: `get_tool_schemas(tool_names: list[str], all_tools: list) -> list[dict]`
- Converts LangChain `@tool` definitions to OpenAI-compatible JSON schema format:
  ```json
  {
    "type": "function",
    "function": {
      "name": "search_web",
      "description": "Search the web for information using DuckDuckGo.",
      "parameters": {
        "type": "object",
        "properties": {
          "query": {"type": "string", "description": "The search query string."}
        },
        "required": ["query"]
      }
    }
  }
  ```
- Schema extraction uses LangChain's existing `.args_schema` on each tool
- `get_tool_descriptions()` kept for logging/debug only

#### `llm_service.py`

- `stream_chat()` and `stream_chat_sentences()` gain an optional `tools: list[dict] | None` parameter
- When `tools` is provided, it's included in the Ollama `/api/chat` payload
- Response parsing handles the `tool_calls` field in streamed messages:
  ```json
  {
    "message": {
      "role": "assistant",
      "content": "",
      "tool_calls": [{
        "function": {
          "name": "search_web",
          "arguments": {"query": "weather in tokyo"}
        }
      }]
    }
  }
  ```
- New yield event: `{"type": "tool_calls", "tool_calls": [...], "content": "..."}`
  - `content` may be non-empty if the model produced text alongside the tool call
- Arguments come pre-parsed as objects from Ollama (no JSON.loads needed)

#### `agent_service.py`

**Removed:**
- `TOOL_CALL_PATTERN` regex
- `parse_tool_call()` function
- Arg normalization hack in `execute_tool()` (lines 66-80)
- Fallback: parsing tool calls from thinking text

**Changed:**
- Agent loop receives tool schemas from `tool_retriever.get_tool_schemas()` and passes them to `llm_service.stream_chat_sentences()`
- After streaming completes, checks for `tool_calls` in the response object (not regex on text)
- If the model returns both text content AND tool calls: stream the text as normal `llm_token` events first, then execute the tool call
- Tool results sent back as `{"role": "tool", "content": "...", "tool_name": "search_web"}` (Ollama's expected format) instead of fake `{"role": "user", "content": "Tool result for ..."}` messages
- `execute_tool()` simplified — direct arg pass-through, no normalization

#### `prompts/tools.txt`

**Removed:**
- Tool call format instructions (the ` ```tool ``` ` block format section at the top)
- `{tools}` placeholder (tools are now passed via API, not embedded in prompt text)

**Kept (behavioral rules):**
- General Tool Protocol (must use tools, never pretend, respond in user's language)
- System & Vision Operations (always call `get_system_time`, use `capture_screen`)
- Web Research Protocol (search_web -> web_scrape follow-up)
- Scheduling Guidelines
- N8n Automation Engine Protocol

### Frontend: Tool Action Cards

#### Delete `AgentActionLog.tsx`

Replaced entirely by `ToolActionCard.tsx`.

#### New `ToolActionCard.tsx`

A collapsible card component for each tool call, rendered inline in the chat bubble.

**Structure:**
```
ToolActionCard
+-- Header: icon + tool name + status indicator + collapse toggle
|   +-- Running: animated spinner + "Running..." text
|   +-- Completed: green checkmark, collapsed by default
|   +-- Error: red X icon, expanded by default
+-- Args section: key-value pairs, clean formatting (not raw JSON)
+-- Result section (collapsible): truncated to ~4 lines with "Show more" toggle
```

**Props:**
```typescript
interface ToolActionCardProps {
  tool: string;
  args?: Record<string, unknown>;
  result?: string;
  status: "running" | "completed" | "error";
}
```

**Visual design:**
- Subtle border, rounded corners, consistent with Radix UI theme
- Tool icon: wrench/gear SVG from `@radix-ui/react-icons`
- Running state: CSS keyframe spinner animation
- Success: green accent color
- Error: red accent color, result section expanded by default
- Args displayed as `key: value` pairs, not `{"key": "value"}` JSON
- Result truncated to ~4 lines with expand/collapse

#### Changes to `useAssistant.ts`

**Updated `AgentAction` type:**
```typescript
export interface AgentAction {
  id: string;
  action: "tool_call" | "tool_result";  // removed "thinking"
  detail: string;
  tool?: string;
  args?: Record<string, unknown>;
  result?: string;
  status: "running" | "completed" | "error";
  timestamp: Date;
}
```

**Event handling changes:**
- `agent_action` with `action: "tool_call"` -> create action with `status: "running"`
- `agent_action` with `action: "tool_result"` -> find the last action with `status: "running"`, update to `status: "completed"` or `status: "error"` (if result starts with "Error:")
- Remove handling for `action: "thinking"` — the existing `isAssistantThinking` state (set on first `llm_token` arrival) handles this

#### Changes to `Chat/index.tsx`

- Remove `AgentActionLog` import and rendering block
- Render `ToolActionCard` components inline before message text for each entry in `msg.agentActions`
- "Processing..." thinking state: subtle pulsing dot on assistant avatar, not a log entry

### WebSocket Protocol

No breaking changes. Same event structure, richer data:

**`tool_call` event** (unchanged shape):
```json
{"type": "agent_action", "action": "tool_call", "tool": "search_web", "args": {"query": "..."}, "timestamp": 1234}
```

**`tool_result` event** (adds `status` field):
```json
{"type": "agent_action", "action": "tool_result", "tool": "search_web", "result": "...", "status": "completed", "timestamp": 1234}
```
`status` is `"completed"` on success or `"error"` on failure (matching the frontend `ToolActionCard` status vocabulary).

Text content alongside tool calls is streamed as normal `llm_token` events before the `tool_call` event.

## Files Changed

| File | Change |
|------|--------|
| `back-end/app/services/llm_service.py` | Add `tools` param, parse `tool_calls` from response |
| `back-end/app/services/agent_service.py` | Remove regex/normalization, use native tool calls, `role: "tool"` messages |
| `back-end/app/services/tool_retriever.py` | New `get_tool_schemas()` method |
| `back-end/app/prompts/tools.txt` | Remove format instructions, keep behavioral rules |
| `front-end/src/components/AgentActionLog.tsx` | Delete |
| `front-end/src/components/ToolActionCard.tsx` | New — collapsible tool action cards |
| `front-end/src/hooks/useAssistant.ts` | Add `status` to AgentAction, update event handling |
| `front-end/src/pages/Chat/index.tsx` | Replace AgentActionLog with ToolActionCard rendering |

## What Stays The Same

- Tool definitions (`@tool` decorator, LangChain tools) — unchanged
- Tool registry (`tools/__init__.py`, `register_dynamic_tools`, `unregister_dynamic_tools`) — unchanged
- Tool retriever embedding-based selection logic — unchanged
- TTS pipeline — unchanged
- WebSocket transport — same structure
- Persona system and prompt loading — unchanged (only `tools.txt` content changes)

## Risks

- **Gemma 4 + Ollama 0.20.7 tool call parser** — reported bugs in 0.20.0, may be fixed. Needs testing early in implementation.
- **Streaming + tool calls** — tool calls in streamed responses need verification. If tool calls arrive as a single chunk (documented behavior), parsing is straightforward.
- **`think: true` + `tools`** — currently thinking is disabled (`thinking = false` always), so no risk. If re-enabled later, needs testing.
