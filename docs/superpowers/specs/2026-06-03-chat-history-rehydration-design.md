# Chat History Rehydration Design

**Date:** 2026-06-03
**Status:** Draft — awaiting user review

## Problem

Backend already persists conversation history to `data/memory/default.json`, but the frontend starts every page load with an empty `messages: []` state. Reloading the browser tab makes the chat appear lost, even though the data survives on disk and the backend continues to feed it into the LLM context.

In addition, persisted entries currently store only `role`, `content`, and `timestamp`. Thinking blocks and tool action cards — the most informative parts of the assistant UI — exist only during the live session and disappear once the bubble is rendered.

## Goal

After a browser reload (or WebSocket reconnect), the chat view should display the full prior conversation exactly as it appeared live: text, thinking blocks (collapsed), and tool action cards.

Scope is intentionally narrow: **single session only.** No sidebar of multiple conversations, no active-connection viewer, no per-user session IDs — the hardcoded `session_id="default"` stays.

## Non-Goals

- Multi-session/multi-conversation support (ChatGPT-style sidebar).
- Active-connection viewer (which browser tabs are connected).
- Per-user session identity.
- Voice message audio playback after reload (blob URLs cannot be persisted; the transcript text remains).
- Restoring an in-flight streaming response that was interrupted by disconnect.

## Approach

Push the persisted history through the existing chat WebSocket as a single `history` message right after the connection opens. The frontend replaces its `messages` state with the hydrated snapshot before any live events arrive.

Considered alternatives:

- **REST endpoint** (`GET /api/chat/history`) — cleaner separation but introduces a race condition with live WS events, requires a new HTTP surface, and duplicates session-id plumbing.
- **Hybrid (REST + WS)** — overkill for a single session capped at 40 messages.

The WS-on-open approach reuses an already-loaded variable (`persisted` in `chat_ws.py:92`), adds one message type, and avoids any new endpoint.

## Persistence Schema

`data/memory/default.json` becomes a list of message dicts. User messages remain minimal; assistant messages gain optional metadata fields.

```json
[
  {
    "role": "user",
    "content": "what time is it",
    "timestamp": 1735900000.123
  },
  {
    "role": "assistant",
    "content": "It's 3:14 PM.",
    "timestamp": 1735900005.456,
    "thinking_text": "User asks time, I should call get_system_time...",
    "agent_actions": [
      {
        "action": "tool_call",
        "tool": "get_system_time",
        "args": {},
        "result": "2026-06-03 15:14:00",
        "status": "completed",
        "timestamp": 1735900002.789
      }
    ],
    "is_notification": false,
    "task_id": null
  }
]
```

Rules:

- User entries keep the original 3 fields (`role`, `content`, `timestamp`). No new fields written for user messages.
- Assistant entries may carry `thinking_text` (string or null), `agent_actions` (list or null), `is_notification` (bool, default false), `task_id` (string or null).
- **Backward compatible:** existing `default.json` files load unchanged. Missing optional fields are treated as null/empty.
- `conversation_history` (the in-memory list fed to the LLM each turn) continues to hold only `{role, content}` — tool action metadata is not replayed to the LLM.

## Backend Changes

### `app/services/memory_service.py`

- `append(session_id, role, content, extras: dict | None = None)` — when `extras` is provided, merge those keys into the persisted message dict alongside `role`, `content`, `timestamp`. No filtering or validation; the caller controls the shape.
- `load(session_id)` returns the full message dicts (not stripped to role+content). Caller decides what to use.
- No schema migration step. Old files simply lack the optional fields.

### `app/api/websockets/chat_ws.py`

**On connect** (immediately after `persisted = memory_service.load(...)`, before entering `while True`):

```python
await send_json_safe({"type": "history", "messages": persisted})
```

Always send, even when `persisted` is `[]`, so the frontend has a clear "sync complete" signal.

**Update `conversation_history` build** to strip extras (LLM only needs role + content):

```python
conversation_history: list[dict] = [
    {"role": m["role"], "content": m["content"]} for m in persisted
]
```

This is already the current shape — no change needed.

**Inside `run_agent_pipeline`**, add per-call accumulators:

```python
current_thinking: str = ""
current_actions: list[dict] = []
```

Wire them into the existing event loop:

- On `llm_thinking_done` event: `current_thinking = event["text"]`.
- On `agent_action` with `action == "tool_call"`: append `{action, tool, args, result: None, status: "running", timestamp}` to `current_actions`.
- On `agent_action` with `action == "tool_result"`: find the last entry in `current_actions` with matching `tool` and `status == "running"`; set its `result` and `status` (`"completed"` or `"error"`).

**On `llm_complete`** (and `assistant_text.strip()` truthy):

```python
extras = {
    "thinking_text": current_thinking or None,
    "agent_actions": current_actions or None,
    "is_notification": is_notification,
    "task_id": notification_task_id,
}
memory_service.append("default", "assistant", assistant_text, extras=extras)
```

`notification_task_id` requires plumbing the task ID into `run_agent_pipeline`. Path: `notification_service.set_agent_callback(run_notification)` currently passes only the prompt string. Extend the callback signature so notification dispatch passes `(prompt, task_id)`, then `run_agent_pipeline` accepts an optional `notification_task_id` param and forwards it into extras.

Notification user-side message is still not persisted (current behavior preserved).

## WebSocket Protocol

New server→client message added to the `ChatServerMessage` union:

```typescript
export interface HistoryMessage {
  type: "history";
  messages: Array<{
    role: "user" | "assistant";
    content: string;
    timestamp: number;  // unix seconds (float)
    thinking_text?: string | null;
    agent_actions?: Array<{
      action: "tool_call";
      tool: string;
      args: Record<string, unknown>;
      result?: string;
      status: "completed" | "error" | "running";
      timestamp: number;
    }> | null;
    is_notification?: boolean;
    task_id?: string | null;
  }>;
}
```

Semantics:

- Sent **exactly once per WS connection**, immediately after accept, before any other server-originated message.
- Frontend treats receipt as a **replace** of the entire `messages` state, not an append.
- On auto-reconnect (the service retries up to 3 times), a fresh `history` snapshot arrives and replaces whatever was on screen. In-flight streaming messages that were not persisted are lost — accepted trade-off.

## Frontend Changes

### `front-end/src/services/chat-websocket.service.ts`

- Add `HistoryMessage` interface.
- Add to `ChatServerMessage` union.

### `front-end/src/hooks/useAssistant.ts`

New case in the WS message handler:

```typescript
case "history": {
  const hydrated: ChatMessage[] = msg.messages.map((m) => ({
    id: `hist-${m.timestamp}-${Math.random().toString(36).slice(2, 7)}`,
    role: m.role,
    text: m.content,
    thinkingText: m.thinking_text || undefined,
    isThinkingPhase: false,
    isStreaming: false,
    isNotification: m.is_notification || false,
    taskId: m.task_id || undefined,
    timestamp: new Date(m.timestamp * 1000),
    agentActions: (m.agent_actions || []).map((a) => ({
      id: `hist-act-${a.timestamp}-${Math.random().toString(36).slice(2, 7)}`,
      action: a.action,
      detail: "",
      tool: a.tool,
      args: a.args,
      result: a.result,
      status: a.status,
      timestamp: new Date(a.timestamp * 1000),
    })),
  }));
  setMessages(hydrated);
  break;
}
```

Voice messages: no `audioUrl` for hydrated entries (blob URLs do not survive reload). Transcript text from `content` is enough.

### Rendering

No changes to `pages/Chat/index.tsx`. The existing `renderMessage()` already handles `thinkingText` (collapsed by default when `isThinkingPhase: false`), `agentActions` (rendered via `ToolActionCard`), and `isNotification`. Hydrated `ChatMessage` objects share the same shape as live ones, so they render identically.

### Clear Memory flow

Unchanged. `clearMessages()` → `setMessages([])` + WS `clear_memory` → backend deletes the file → next reconnect delivers `{type: "history", messages: []}`.

## Edge Cases

- **Empty history:** backend still sends `{type: "history", messages: []}`. Frontend `setMessages([])` is a no-op visually.
- **Corrupted JSON file:** `memory_service.load()` already returns `[]` on `JSONDecodeError`. Frontend gets an empty history — no crash.
- **Schema missing fields:** `m.get("thinking_text")` semantics in Python and `m.thinking_text || undefined` in TypeScript handle absence gracefully.
- **Reconnect during streaming:** the in-flight assistant message has not been persisted yet, so it vanishes when the replace happens. User can resend.
- **Max turns:** `memory_service.load()` already trims to `MEMORY_MAX_TURNS * 2 = 40` messages. The `history` message inherits that cap.

## Testing Plan

- Unit: `memory_service.append` with and without `extras`, verify JSON shape on disk.
- Unit: `memory_service.load` against an old-format file (no extras) — confirm backward compatibility.
- Integration: connect to `/ws/chat`, assert first message is `{type: "history", messages: [...]}`.
- Manual: chat with tool calls + thinking enabled → reload → verify cards and thinking block appear.
- Manual: trigger a notification → reload → verify notification message has appropriate marker.
- Manual: clear memory → reload → verify empty chat view.

## Files Touched

- `back-end/app/services/memory_service.py` — `append` accepts `extras`, `load` returns full dicts.
- `back-end/app/api/websockets/chat_ws.py` — send `history` on connect; accumulate thinking + actions; pass extras to `append`.
- `back-end/app/services/notification_service.py` — callback signature extension to pass `task_id`.
- `front-end/src/services/chat-websocket.service.ts` — new `HistoryMessage` interface and union member.
- `front-end/src/hooks/useAssistant.ts` — handle `history` case, hydrate state.
- `back-end/tests/test_ws.py` — extend with history-on-connect test.
