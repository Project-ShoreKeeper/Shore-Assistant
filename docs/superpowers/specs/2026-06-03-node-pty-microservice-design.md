# Node-pty Terminal Microservice — Design

**Date:** 2026-06-03
**Status:** Draft (awaiting user review)
**Author:** Luna + Claude

## Goal

Replace `pywinpty` in the Shore Assistant backend with a standalone Node.js microservice (`shore-pty-service`) that wraps `node-pty` for interactive PTY sessions and `child_process` for one-shot commands. The microservice is a "dumb executor": all policy (whitelist, confirm dialog, audit log) stays in the Python `TerminalService`. The browser-facing WebSocket contract (`/ws/chat`) does not change — the microservice is invisible to the frontend.

### Why
1. **Stability** — `pywinpty` has build/runtime quirks on Windows; `node-pty` is the same backend VS Code uses, well-maintained.
2. **Isolation** — terminal crashes no longer take FastAPI down; the executor can restart independently.
3. **Node ecosystem** — opens the door to `xterm-headless` server-side buffer serialization and other Node-only terminal tooling.

## Non-Goals

- Multi-tenant access: the service binds to `127.0.0.1` only.
- Cross-host PTY: out of scope.
- Replacing the browser-facing `/ws/chat` contract: unchanged.
- Sharing the executor with other clients: a single FastAPI instance is the only client for now.

## 1. Architecture

```
Browser (xterm.js)
   │  ws://localhost:9000/ws/chat   (existing — unchanged)
   ▼
FastAPI (back-end, Python)
   │  ┌─────────────────────────────────────┐
   │  │ TerminalService (Python)            │
   │  │  - whitelist gate                   │
   │  │  - confirm dialog round-trip        │
   │  │  - audit log                        │
   │  │  - NodePtyClient (WS to Node)       │
   │  │  - broadcast translator             │
   │  └─────────────────────────────────────┘
   │           │
   │           │  ws://127.0.0.1:9100  (NEW — JSON-RPC 2.0)
   ▼           ▼
Node microservice (shore-pty-service, TypeScript)
   - WebSocketServer (ws package)
   - SessionManager
   - PtySession (wraps node-pty.spawn)
   - OneShotRunner (wraps child_process.spawn)
   - heartbeat + clean shutdown
```

### Roles
- **Browser**: unchanged — still talks to FastAPI over `/ws/chat`.
- **FastAPI / Python**: *control plane + policy*. Owns whitelist, confirm flow, audit log, broadcasts to browser. `WinPtySession` is replaced by `NodePtyClient`, a WS client that issues JSON-RPC calls to Node.
- **Node microservice**: *execution plane*. Knows nothing about whitelist or confirm. Three responsibilities: spawn PTY/process, stream output, kill on close. Independent process — restart does not affect FastAPI.

### Boundary
- All input from user/LLM flows through Python and is gated before reaching Node.
- After gating, Python forwards raw execution intent to Node.
- Output produced by Node → Python → re-broadcast to browser using the existing chat_ws wire format.

The browser never knows Node exists. The entire existing frontend continues to work without changes.

## 2. Components

### Node microservice — `shore-pty-service/`

```
shore-pty-service/
├── package.json
├── tsconfig.json
├── src/
│   ├── index.ts            # entrypoint: parse env, start WSS, handle SIGINT
│   ├── server.ts           # WebSocketServer wiring, per-connection dispatcher
│   ├── rpc.ts              # JSON-RPC 2.0 framing: parse, validate, response/error builders
│   ├── methods.ts          # method handlers map (oneshot.run, session.open, ...)
│   ├── sessionManager.ts   # Map<sessionId, PtySession>, lifecycle, idle reaper
│   ├── ptySession.ts       # wraps node-pty.spawn — write, resize, kill, stream onData
│   ├── oneshotRunner.ts    # wraps child_process.spawn — collect stdout/stderr, timeout
│   ├── shellResolver.ts    # maps "powershell"|"pwsh"|"cmd"|"bash" → exe path + args
│   └── logger.ts           # pino, JSONL to stdout
└── README.md
```

Single-responsibility files:
- `rpc.ts` does not know about PTY — only encode/decode JSON-RPC.
- `ptySession.ts` does not know about WS — only wraps node-pty and emits events.
- `methods.ts` is the bridge: receives decoded RPC, calls sessionManager / oneshotRunner, returns a response.

### Python side — minimal changes

```
back-end/app/services/
├── terminal_service.py        # MOSTLY UNCHANGED — still whitelist, audit, broadcast
├── terminal_session.py        # DELETED at the end of migration (replaced by RPC call)
└── node_pty_client.py         # NEW — WS client to Node, JSON-RPC, reconnect, event router
```

`terminal_service.py` loses the `WinPtySession` import in favour of `node_pty_client.call("session.open", ...)`. The public methods of `TerminalService` (used by `terminal_tools.py` and `chat_ws.py`) **keep the same signatures** → no changes needed in those two files. `node_pty_client.py` is the only module that knows about the Node service.

### Boundaries
- Node service: standalone, testable with `wscat` — no Python dependency.
- `node_pty_client.py`: standalone, testable with a mock WS server — no `terminal_service` dependency.
- `terminal_service.py`: depends only on the interface of `node_pty_client.py` (5–6 async methods).

## 3. Wire Protocol — JSON-RPC 2.0

All messages are JSON objects. Three kinds: **Request** (Python→Node, has `id`), **Response** (Node→Python, same `id`), **Notification** (Node→Python, no `id` — server-initiated event).

### Methods (Python → Node)

| Method | Params | Result |
|---|---|---|
| `oneshot.run` | `{run_id, command, shell, cwd, timeout_ms}` | `{exit_code, stdout, stderr, duration_ms, truncated}` |
| `session.open` | `{name, shell, cwd, cols, rows}` | `{session_id, pid}` |
| `session.send` | `{session_id, data}` | `{ok: true}` |
| `session.resize` | `{session_id, cols, rows}` | `{ok: true}` |
| `session.close` | `{session_id}` | `{closed: true, exit_code}` |
| `session.list` | `{}` | `[{session_id, name, shell, cwd, pid, idle_seconds}, ...]` |
| `ping` | `{}` | `{pong: true, version}` |

### Notifications (Node → Python, no response)

| Method | Params |
|---|---|
| `oneshot.output` | `{run_id, stream: "stdout"\|"stderr", data}` |
| `oneshot.exit`   | `{run_id, exit_code, signal?}` |
| `session.output` | `{session_id, data}` |
| `session.exit`   | `{session_id, exit_code, signal?, reason}` |
| `session.output_dropped` | `{session_id, dropped_bytes}` — emitted when backpressure forces Node to discard PTY output (see 5.4) |

### Errors

| Code | Meaning |
|---|---|
| `-32600` | Invalid Request (JSON-RPC standard) |
| `-32601` | Method not found |
| `-32602` | Invalid params |
| `-32603` | Internal error / connection lost |
| `-32001` | Shell binary not found |
| `-32002` | Session not found |
| `-32003` | Session already exists (duplicate `name`) |
| `-32004` | Spawn failed (node-pty rejected) |
| `-32005` | Write to dead session |

### ID correlation
- `run_id` (one-shot) and `session_id` (PTY session) are **generated by Python** (UUID hex, 12 chars, same as current code) and passed to Node. Reason: Python's audit log and broadcast events already reference these IDs; having Node generate them would force Python to maintain a translation map.
- JSON-RPC `id` is independent — used only for request/response correlation on the WS wire.

### Output encoding
- Notification `data` is always a **UTF-8 string**, may contain ANSI escapes (Node does NOT strip). Python applies `strip_ansi` for LLM previews and keeps ANSI when broadcasting to xterm — matches current behaviour.
- If node-pty reads bytes that are not valid UTF-8 (rare), Node decodes with `replace` so the message never fails.

### Heartbeat
- Python sends `ping` every 30s. No response within 5s → close socket and trigger reconnect.
- Node closes the socket if it receives nothing for 60s (defensive — Python should have pinged).

## 4. Data Flow

### 4.1 One-shot (`run_command` tool)

```
LLM tool call
  → terminal_tools.run_command()
  → TerminalService.run_oneshot(cmd, shell, cwd, reason)
      ├─ whitelist.check(cmd, shell)
      │     ├─ block  → return error, no Node call
      │     ├─ confirm → broadcast terminal_confirm_request → await user
      │     │            (deny → return error)
      │     └─ allow
      ├─ run_id = uuid12
      ├─ broadcast {type: "terminal_oneshot_start", run_id, command, shell, cwd}
      ├─ node_pty_client.call("oneshot.run", {run_id, command, shell, cwd, timeout_ms})
      │     │
      │     │  (Node executes via child_process.spawn)
      │     │
      │     ├─ Node sends "oneshot.output" notifications as data arrives
      │     │     Python event router → broadcast {type: "terminal_oneshot_output", run_id, stream, data}
      │     │                         → append to stdout_buf / stderr_buf for LLM
      │     │
      │     └─ Node sends RPC response {exit_code, duration_ms, ...} when process exits
      ├─ broadcast {type: "terminal_oneshot_end", run_id, exit_code, duration_ms, truncated}
      ├─ audit({kind: "oneshot", ...})
      └─ return {exit_code, stdout (stripped+truncated), stderr, ..., log_path}
```

### 4.2 Session lifecycle (`open_terminal`)

```
open_terminal("dev", "powershell")
  → TerminalService.open_session("dev", "powershell", cwd)
      ├─ check name not duplicated locally
      ├─ node_pty_client.call("session.open", {name, shell, cwd, cols:80, rows:24})
      │     → returns {session_id, pid}
      ├─ register self.sessions["dev"] = SessionHandle(session_id, shell, cwd, pid, last_activity)
      ├─ broadcast {type: "terminal_session_opened", session_id, name, shell, cwd, pid}
      ├─ audit
      └─ return {session_id, name, message}

(asynchronously, Node streams notifications:)
  "session.output" {session_id, data}
      → node_pty_client event router
      → look up session by session_id → name
      → broadcast {type: "terminal_session_output", session_id, data}
      → update SessionHandle.last_activity

  "session.exit" {session_id, exit_code, reason}
      → remove from self.sessions
      → broadcast {type: "terminal_session_closed", session_id, name, reason, exit_code}
      → audit
```

### 4.3 User-driven inputs (xterm.js)

Unchanged routing through chat_ws:
- `terminal_user_input` → `TerminalService.send_to_session(name, data, wait_seconds=0)` → `session.send` RPC.
- `terminal_resize` → `session.resize` RPC.
- `terminal_close_session` → `session.close` RPC.
- `terminal_resync` (frontend reconnect) → `list_sessions()` reads from `self.sessions` (local cache). No Node call needed — Python is the source of truth for session state.

### 4.4 Reconnect (Python ↔ Node)

```
NodePtyClient state machine:
  DISCONNECTED → on first call() → connecting
                                     ├─ success → CONNECTED
                                     └─ fail → backoff, retry (1s, 2s, 4s, ... cap 30s)

  CONNECTED → on socket close →  mark all in-flight Futures with error -32603
                                  for every tracked session: broadcast terminal_session_closed
                                    {reason: "node_disconnect", exit_code: null} to frontend
                                  clear self.sessions
                                  DISCONNECTED

  while DISCONNECTED:
    any tool call returns error "terminal service unavailable; will retry"
    background reconnector keeps trying
```

When Node restarts, every PTY child process dies with it — there is no way to restore. Python treats sessions as lost, broadcasts `terminal_session_closed` to the frontend, and the frontend cleans up its tabs. This is intentional: we do not pretend "the session is still alive".

### 4.5 Confirm flow
100% in Python — frontend does not know Node exists, confirm dialog flow is unchanged.

## 5. Error Handling & Resilience

### 5.1 Errors from Node to Python
| Situation | Node returns | Python handles |
|---|---|---|
| Shell binary missing | RPC error `-32001` | `run_oneshot` returns `{exit_code: -1, stderr: "Shell binary not found: ..."}` (matches current behaviour) |
| `session.open` with duplicate name at Node | `-32003` | Should not happen (Python checks first) — log warning, return error to LLM |
| `session.send` to dead session | `-32005` | Remove from `self.sessions`, broadcast `terminal_session_closed`, return error to caller |
| Spawn failure (e.g. missing cwd) | `-32004` | Forward error message in the tool response |
| One-shot timeout | RPC response `{exit_code: -1, stderr: "[Timed out after Ns]"}` | Forward as-is |

### 5.2 Errors from Python to frontend
Broadcast schema for the frontend is unchanged. One new event added:
- `terminal_service_unavailable` broadcast when NodePtyClient transitions to DISCONNECTED. Frontend may show a banner "Terminal backend offline" (optional UX improvement, not required for v1).

### 5.3 In-flight requests when connection drops
- Every `Future` in the `pending_requests` map is rejected with `-32603 "connection lost"`.
- Running tools return `{exit_code: -1, stderr: "Lost connection to terminal service"}` to the LLM.

### 5.4 Backpressure
- node-pty reads quickly; if Python processes slowly, the WS buffer grows.
- Node enforces a limit: if WS `bufferedAmount > 4 MB` for a single session, output is dropped and a `session.output_dropped` notification is sent (see Section 3 catalog). Python broadcasts a `terminal_output_dropped` warning event to the frontend.
- Unlikely to matter for local loopback in dev, but prevents OOM when a user runs `cat huge_file`.

### 5.5 Idle session reaper
- Stays in Python (matches current behaviour): checks `last_activity` every minute, closes sessions idle for more than 30 minutes via `session.close` RPC.
- Node has a defensive timer of its own (close PTY if no Python ping for 60s) — does not replace the primary logic.

### 5.6 Unrecoverable errors
- Node WS server cannot bind to its port: exit code 2 + log error → user sees the failure when running `npm start`.
- OOM at Node: process crashes; if managed by PM2/systemd it restarts, otherwise the user restarts it manually.

## 6. Configuration

### Node service (`shore-pty-service/.env` or env vars)
| Var | Default | Description |
|---|---|---|
| `PTY_WS_HOST` | `127.0.0.1` | Bind host. Localhost only — never exposed to the network. |
| `PTY_WS_PORT` | `9100` | WS port. |
| `PTY_AUTH_TOKEN` | (empty) | Optional shared secret; client must send `Authorization: Bearer <token>` on handshake. Empty = no auth (dev mode). |
| `PTY_SESSION_IDLE_GUARD_SECONDS` | `60` | Close PTY if no Python ping for N seconds. |
| `PTY_MAX_BUFFERED_BYTES` | `4194304` | Per-session backpressure threshold (4 MB). |
| `PTY_LOG_LEVEL` | `info` | pino level. |

### Python side (add to `back-end/.env`)
| Var | Default | Description |
|---|---|---|
| `TERMINAL_BACKEND` | `node` | `node` \| `pywinpty`. Allows fallback during the migration window. |
| `NODE_PTY_WS_URL` | `ws://127.0.0.1:9100` | Node service URL. |
| `NODE_PTY_AUTH_TOKEN` | (empty) | Must match `PTY_AUTH_TOKEN` on Node. |
| `NODE_PTY_RECONNECT_BASE_MS` | `1000` | Initial backoff. |
| `NODE_PTY_RECONNECT_MAX_MS` | `30000` | Backoff cap. |
| `NODE_PTY_PING_INTERVAL_SECONDS` | `30` | Heartbeat interval. |
| `NODE_PTY_PING_TIMEOUT_SECONDS` | `5` | Pong deadline. |

The existing `TERMINAL_*` variables (`TERMINAL_WHITELIST_FILE`, `TERMINAL_DEFAULT_CWD`, `TERMINAL_RUNS_DIR`, `TERMINAL_AUDIT_LOG`, `TERMINAL_ONESHOT_TIMEOUT_SECONDS`, `TERMINAL_MAX_OUTPUT_BYTES`, `TERMINAL_LLM_OUTPUT_PREVIEW_BYTES`, `TERMINAL_CONFIRM_TIMEOUT_SECONDS`, `TERMINAL_SESSION_IDLE_MINUTES`) **stay unchanged** — they belong to policy/audit, which remains in Python.

### `TERMINAL_BACKEND=pywinpty` fallback (temporary)
During rollout, setting `TERMINAL_BACKEND=pywinpty` keeps the old code path (`WinPtySession` + `asyncio.create_subprocess_*` for one-shot) operational. After 1–2 weeks of stable `node` backend usage, the env var and `pywinpty` code path are removed.

## 7. Testing

### 7.1 Node service — standalone tests (Vitest)

```
shore-pty-service/test/
├── rpc.test.ts             # parse/encode JSON-RPC, error builder, invalid payloads
├── shellResolver.test.ts   # correct exe path per shell, unknown → throw
├── ptySession.test.ts      # spawn, write, resize, kill — uses powershell echo
├── oneshotRunner.test.ts   # exit code 0, non-zero, timeout, stderr separation
├── sessionManager.test.ts  # dedup name, list, close-all
└── server.test.ts          # WSS end-to-end: connect, RPC roundtrip, notifications
```

Tests use the `ws` package as a client (same package the server uses). No mocking of node-pty — we want real PTY behaviour because that is the whole point.

### 7.2 Python — `node_pty_client` (pytest + pytest-asyncio)

```
back-end/tests/test_node_pty_client.py
  - connect/disconnect lifecycle
  - call() ↔ response correlation
  - notification dispatch to registered handlers
  - reconnect when socket closes
  - in-flight futures rejected when connection drops
  - ping timeout → reconnect
```

A `websockets` server stub plays the role of "fake Node" — replies according to a script. Real Node is not started in unit tests.

### 7.3 Python — `terminal_service` integration

```
back-end/tests/test_terminal_service.py  (update existing file)
  - run_oneshot: whitelist allow/confirm/block paths
  - run_oneshot: confirm dialog flow
  - session lifecycle
  - audit log content
```

`NodePtyClient` is mocked to avoid needing real Node. These tests verify the policy layer; PTY execution is verified in 7.1.

### 7.4 End-to-end smoke (manual, documented in `back-end/tests/manual.md`)

1. `npm start` in `shore-pty-service`.
2. `python -m uvicorn app.main:app --port 9000` in `back-end`.
3. Open frontend, run `git status` from chat → verify output.
4. Open a powershell session, run `Get-Process | Select-Object -First 5` in xterm → verify ANSI rendering.
5. Kill the Node process mid-flight → verify frontend receives `terminal_session_closed` and the offline banner appears.
6. Restart Node → verify Python reconnects automatically and `run_command` works again.

### 7.5 Not tested
- node-pty internals (Microsoft maintains them).
- Frontend xterm (no changes).
- Automated backpressure stress test — verified manually with a noisy command like `Get-EventLog Application -Newest 50000`.

## 8. Migration Plan

Four steps, each leaving `main` in a working state:

### Step 1 — Build Node service (Python untouched)
- Create `shore-pty-service/` at the repo root (sibling to `back-end/` and `front-end/`).
- Implement all modules + tests from 7.1.
- Manual verification with `wscat -c ws://127.0.0.1:9100`: send `oneshot.run`, `session.open`, `session.send` → confirm responses/notifications match the schema.
- Commit. Python backend still does not know Node exists — nothing is affected.

### Step 2 — Write `node_pty_client.py` (not wired yet)
- New module with its own tests (7.2, using a fake WS server).
- No import from `terminal_service.py` yet. No behaviour change.
- Commit.

### Step 3 — Wire into `terminal_service.py` behind a `TERMINAL_BACKEND` flag
- Refactor `terminal_service.py`: extract the "execute" part (one-shot + sessions) into a small interface:

  ```python
  class TerminalBackend(Protocol):
      async def run_oneshot_exec(...) -> ExecResult
      async def open_session_exec(...) -> SessionHandle
      async def send_to_session_exec(...)
      async def resize_session_exec(...)
      async def close_session_exec(...)
  ```

- Two implementations:
  - `PywinptyBackend` — current code, extracted from `terminal_session.py` + `asyncio.create_subprocess_*`.
  - `NodePtyBackend` — calls `NodePtyClient`.
- `TerminalService` picks the backend via the `TERMINAL_BACKEND` env var (default `node`).
- Whitelist/confirm/audit/broadcast in `TerminalService` are not relocated — only the execution path moves.
- Update `test_terminal_service.py` to run against `NodePtyBackend(mocked NodePtyClient)`.
- Manual smoke E2E (7.4).
- Commit.

### Step 4 — Cleanup after stabilisation
After ~1–2 weeks of using `TERMINAL_BACKEND=node` without regressions:
- Delete `app/services/terminal_session.py`.
- Delete `PywinptyBackend` and the `TERMINAL_BACKEND` env var.
- Remove `winpty` from `requirements.txt`.
- Update `CLAUDE.md` and the backend README.
- Commit. This PR closes the migration loop.

### Risks
- **Node service not started on first launch** → mitigation: backend README clearly states "run `npm start` in `shore-pty-service/` first", and tool errors carry an actionable message.
- **node-pty needs Visual Studio Build Tools to compile native bindings** on Windows first install — README documents installing Visual Studio Build Tools 2022 with the "Desktop development with C++" workload.
- **Frontend cannot detect Node directly** → the "Terminal backend offline" banner lets users self-recover (check Node logs, restart `npm start`).

### Rollback
If Step 3 surfaces an unrecoverable regression: set `TERMINAL_BACKEND=pywinpty` → instant revert to the old behaviour without reverting commits.
