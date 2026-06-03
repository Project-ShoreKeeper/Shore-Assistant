# Terminal Interaction Feature — Design Spec

**Date:** 2026-06-03
**Author:** Luna (with Shore Assistant brainstorming)
**Status:** Approved (pending user review of written spec)

## Goal

Give Shore the ability to interact with the local terminal — both one-shot commands and persistent interactive sessions — exposed as agent tools and visible in a dedicated terminal panel on the Chat page. The user retains safety control through a whitelist + confirm flow, and can also type into the panel themselves.

## Scope decisions (from brainstorming)

| Decision | Choice |
|---|---|
| Modes | Both one-shot and interactive |
| Shell selection | LLM picks per call (`powershell` / `cmd` / `bash`) |
| Safety | Whitelist auto-run; non-whitelisted prompts user confirm; hard blacklist always blocked |
| UI placement | Split panel on Chat page: chat left, terminal right (resizable) |
| Default CWD | Configurable via env var (`TERMINAL_DEFAULT_CWD`) |
| Output streaming | Realtime stream over existing `/ws/chat` |
| Session model | Auto-managed pool of named sessions (idle timeout) |

## Architecture

```
LLM Agent (LangGraph)
   │
   ├── run_command(cmd, shell, cwd, timeout, reason)   ← one-shot subprocess
   │       └── TerminalService.run_oneshot()
   │             ├── WhitelistGuard.check(cmd, shell)
   │             ├── (if needs confirm) emit terminal_confirm_request → await response
   │             └── asyncio.create_subprocess_exec → stream stdout/stderr frames
   │
   └── open_terminal / send_to_terminal / list_terminals / close_terminal
           └── TerminalService.session_pool[name] = WinPtySession
                 └── pywinpty.PtyProcess.spawn(shell)
                      ├── read loop → push raw frames to /ws/chat
                      └── write input from LLM or user keyboard

ConnectionManager (existing singleton)
   └── routes all terminal messages over /ws/chat

Frontend (Chat page, split layout)
   ├── Left: existing Chat UI
   └── Right: TerminalPanel
         ├── Session tabs (auto-managed)
         ├── xterm.js view for active session
         ├── One-shot history pane (clean output)
         └── Confirm banner (Approve / Deny / Always allow)
```

### New backend files

- `app/services/terminal_service.py` — singleton with `run_oneshot()`, `open_session()`, `send_to_session()`, `close_session()`, `list_sessions()`. Manages pool, idle reaper, audit log.
- `app/services/terminal_whitelist.py` — loads whitelist from `data/terminal_whitelist.json` plus user-extended `data/terminal_whitelist_user.json`. Pure function `check(cmd, shell) → "allow" | "confirm" | "block"`.
- `app/tools/terminal_tools.py` — 5 LangChain `@tool`s: `run_command`, `open_terminal`, `send_to_terminal`, `list_terminals`, `close_terminal`.

### New frontend files

- `src/services/terminal-websocket.service.ts` — routes terminal message types from existing chat WS.
- `src/hooks/useTerminal.ts` — state for sessions, active session, pending confirms.
- `src/components/Terminal/TerminalPanel.tsx`
- `src/components/Terminal/XtermView.tsx`
- `src/components/Terminal/OneShotHistory.tsx`
- `src/components/Terminal/ConfirmBanner.tsx`

### Modified files

- `back-end/app/core/config.py` — add `TERMINAL_DEFAULT_CWD`, `TERMINAL_DEFAULT_SHELL`, `TERMINAL_ONESHOT_TIMEOUT_SECONDS` (default 60), `TERMINAL_SESSION_IDLE_MINUTES` (default 30), `TERMINAL_ORPHAN_TIMEOUT_MINUTES` (default 5), `TERMINAL_CONFIRM_TIMEOUT_SECONDS` (default 60), `TERMINAL_MAX_OUTPUT_BYTES` (default 1_048_576).
- `back-end/app/tools/__init__.py` — register the 5 new terminal tools in `ALL_TOOLS`.
- `back-end/app/api/websockets/chat_ws.py` — handle new client→server message types.
- `back-end/app/main.py` — lifespan hook to close all terminal sessions on shutdown.
- `back-end/requirements.txt` — add `pywinpty` (Windows-only).
- `back-end/app/services/tool_retriever.py` — terminal tools likely belong in "always available" or be retriever-selected; default to retriever-selected because users won't always need them.
- `front-end/src/pages/Chat/index.tsx` — switch to resizable split layout (`react-resizable-panels`).
- `front-end/package.json` — add `xterm`, `xterm-addon-fit`, `react-resizable-panels`.

## Data flow & message contract

All over existing `/ws/chat`. Existing message types unchanged.

### Server → Client (new)

| `type` | Payload | When |
|---|---|---|
| `terminal_confirm_request` | `{request_id, command, shell, cwd, reason}` | Command outside whitelist; awaiting user |
| `terminal_oneshot_start` | `{run_id, command, shell, cwd}` | `run_command` begins |
| `terminal_oneshot_output` | `{run_id, stream: "stdout" \| "stderr", data}` | Streaming chunk |
| `terminal_oneshot_end` | `{run_id, exit_code, duration_ms, truncated}` | Done or timed out |
| `terminal_session_opened` | `{session_id, name, shell, cwd, pid}` | `open_terminal` ok |
| `terminal_session_output` | `{session_id, data}` | Raw PTY bytes (ANSI preserved for xterm.js) |
| `terminal_session_closed` | `{session_id, reason: "llm"\|"user"\|"idle"\|"crash", exit_code?}` | Session ends |

### Client → Server (new)

| `type` | Payload | When |
|---|---|---|
| `terminal_confirm_response` | `{request_id, decision: "approve"\|"deny"\|"always_allow"}` | User clicks button |
| `terminal_user_input` | `{session_id, data}` | User types into xterm panel |
| `terminal_resize` | `{session_id, cols, rows}` | xterm dimension change |
| `terminal_close_session` | `{session_id}` | User closes session via tab |
| `terminal_resync` | `{}` | After reconnect, ask backend for current sessions |

### LLM tool result contracts

All tools return JSON-serializable dicts; never raise.

- `run_command(command, shell="powershell", cwd=None, timeout=60, reason="")` → `{exit_code, stdout, stderr, truncated, duration_ms, log_path}`. stdout/stderr trimmed to ~8KB each in the dict returned to the LLM (separate from the streamed-to-UI bytes, which are bounded by `TERMINAL_MAX_OUTPUT_BYTES`). Full output is persisted to `log_path` regardless.
- `open_terminal(name=None, shell="powershell", cwd=None)` → `{session_id, name, message}`. If `name` omitted, server picks (`session-1`, ...). If name already exists, error.
- `send_to_terminal(name, input, wait_seconds=2)` → `{output, ansi_stripped, exit_code_if_dead}`. Waits up to `wait_seconds` for output, returns ANSI-stripped slice for LLM. Frontend still gets raw bytes via stream.
- `list_terminals()` → `[{name, shell, cwd, idle_seconds, last_output_preview}]`.
- `close_terminal(name)` → `{closed: bool, message}`.

## Whitelist & safety

### Default whitelist (read-mostly + dev tooling)

```
Read-only / inspection:
  dir, ls, pwd, cd, cat, type, head, tail, less, more,
  Get-ChildItem, Get-Location, Get-Content, Get-Process,
  echo, Write-Output, Write-Host,
  whoami, hostname, ipconfig, ifconfig,
  where, which, Get-Command

Dev common:
  git (any subcommand EXCEPT: push --force, reset --hard, clean -f, branch -D),
  npm (EXCEPT: npm publish),
  pnpm, yarn, bun,
  python, python3, py, pip,
  node, npx, deno,
  cargo, go, rustc,
  tsc, vite, eslint

Project tools:
  uvicorn, fastapi, pytest, jupyter

File listing (read-only):
  tree, fd, rg,
  find (EXCEPT: -delete, -exec)
```

### Hard blacklist (cannot be allowed even by user)

```
rm -rf /, rm -rf C:\, Remove-Item C:\ -Recurse,
format, diskpart, shutdown, restart-computer,
del /S /Q C:\*, rd /S /Q C:\,
reg delete HKLM,
takeown /F C:\, icacls C:\ /grant Everyone
```

Match strategy: tokenize first segment of each chained sub-command (split on `&&`, `||`, `;`, `|`), unwrap shell wrappers (`powershell -c "..."`, `cmd /c "..."`, `bash -c "..."`), apply regex against the head token plus argument patterns. Blacklist patterns take precedence.

### Confirm flow

```
1. Parse command, unwrap shell wrappers.
2. For each sub-segment:
   a. Blacklist match → return {error: "Blocked: <reason>"}; NO user prompt; audit-log "blocked".
   b. Whitelist match → ok.
   c. Otherwise → mark "needs_confirm".
3. If any segment needs confirm:
   - emit terminal_confirm_request with full command, shell, cwd, reason
   - await terminal_confirm_response (timeout = TERMINAL_CONFIRM_TIMEOUT_SECONDS)
   - approve → run once
   - always_allow → append leading token to data/terminal_whitelist_user.json, run
   - deny / timeout → return {error: "User denied execution"}
4. Run via subprocess (one-shot) or send into PTY (already-open session).
5. Append audit-log entry.
```

### Interactive session safety

- `open_terminal(shell=...)` only accepts shells in `{powershell, cmd, bash}`.
- Content sent via `send_to_terminal` or user keyboard is NOT whitelist-checked. Rationale: REPLs eval arbitrary code anyway, and the user can see live output in xterm.
- Mitigation: idle auto-close; sessions are visible at all times; spec documents this as an explicit trust boundary.

## Error handling

| Situation | Behaviour |
|---|---|
| Shell binary missing (e.g. user picked `bash` without Git Bash/WSL) | One-shot: `{exit_code: -1, stderr: "Shell 'bash' not found. Available: powershell, cmd"}`. Interactive: tool returns error dict. |
| CWD not found | Tool returns `{error: "CWD not found: <path>"}`; no spawn. |
| One-shot timeout | Kill process tree (`taskkill /T /F` on Windows), return partial output with `truncated: true`. |
| Output > `TERMINAL_MAX_OUTPUT_BYTES` | Truncate in-memory; persist full to `data/terminal_runs/<run_id>.log`; `truncated: true`. |
| PTY crashes | Emit `terminal_session_closed` with `reason: "crash", exit_code`. Subsequent `send_to_terminal` returns `{error: "Session <name> is no longer alive"}`. |
| Send to unknown session | `{error: "No terminal named '<name>'. Open one first.", available: [...]}`. |
| Spawn permission/AV error | Caught, returned as clean error message. |
| Backend shutdown | Lifespan event iterates pool, closes all PTYs gracefully then kills if needed. |
| Frontend WS disconnect | Sessions stay alive `TERMINAL_ORPHAN_TIMEOUT_MINUTES`. UI shows "Reconnecting…"; on reconnect, sends `terminal_resync` and rebuilds tabs. |
| Orphaned confirm request after page reload | Backend's 60s timeout auto-denies. |
| xterm.js mount failure | Fallback `<pre>` element with raw text. |

All command attempts (allowed, blocked, denied, executed) are appended to `data/terminal_audit.log` as JSON lines:
```
{"ts": "2026-06-03T14:22:01Z", "run_id": "...", "kind": "oneshot"|"session_input", "command": "...", "shell": "...", "cwd": "...", "decision": "auto-allow"|"user-approve"|"user-deny"|"blocked", "exit_code": 0, "duration_ms": 124}
```

## Testing strategy

### Backend (`back-end/tests/`)

| Target | Style | Coverage |
|---|---|---|
| `terminal_whitelist.py` | unit (pure) | shell wrappers, chained commands, blacklist precedence, runtime user-whitelist persistence |
| `terminal_service.run_oneshot` | integration | real subprocess, stdout/stderr, exit code, timeout kill, truncation |
| `terminal_service` session pool | integration | open PTY, send input, read output, close. Idle timeout via short config override (2s) |
| `terminal_tools.py` | integration | `.ainvoke()` like agent does, assert dict contracts; mock ConnectionManager to verify emitted messages |
| Confirm flow | integration | mock approve / deny / always_allow / timeout responses |
| Audit log | unit | format is one JSON object per line, all fields present |

### Frontend

No automated tests (project doesn't have a frontend test suite). Manual smoke checklist lives in this spec.

### Manual E2E checklist

1. `run_command("dir")` → streams into terminal panel, agent log entry, exit 0.
2. `run_command("npm install lodash")` → confirm banner; Approve → runs, streams progress, LLM gets output.
3. `open_terminal(name="py", shell="powershell")` then `send_to_terminal("py", "python\n")` → REPL prompt. Then `send_to_terminal("py", "print(2+2)\n")` → `4` visible.
4. Blacklisted command (e.g. `rm -rf C:\\`) → instant block, no banner, LLM gets clear error.
5. Idle session past timeout (set to 60s for test) → auto-close, banner appears.
6. Restart backend with sessions open → sessions gone; `send_to_terminal` returns clean error.
7. User types directly into xterm panel without LLM driving → input reaches PTY, output streams back. Terminal usable as a normal terminal.
8. Reload frontend mid-session → reconnect, `terminal_resync` repopulates session tabs.
9. Split panel resize handle works; min widths respected.

## Configuration additions

| Variable | Default | Description |
|---|---|---|
| `TERMINAL_DEFAULT_CWD` | (back-end repo root) | Default working directory for new terminals |
| `TERMINAL_DEFAULT_SHELL` | `powershell` | Shell when LLM/user omits one |
| `TERMINAL_ONESHOT_TIMEOUT_SECONDS` | 60 | One-shot command timeout |
| `TERMINAL_SESSION_IDLE_MINUTES` | 30 | Auto-close idle PTY sessions |
| `TERMINAL_ORPHAN_TIMEOUT_MINUTES` | 5 | Keep sessions alive this long after WS disconnect |
| `TERMINAL_CONFIRM_TIMEOUT_SECONDS` | 60 | Auto-deny if user doesn't respond |
| `TERMINAL_MAX_OUTPUT_BYTES` | 1048576 | Truncate one-shot output past this size |

## Out of scope (deferred)

- Persisting interactive sessions across backend restarts (would need detached PTY supervisor).
- Per-session shell customization beyond the three supported.
- Remote terminal (SSH) as a native concept — user can `ssh` from within a session, no special tool needed.
- Frontend test suite — not in this feature.
- macOS / Linux PTY backends — current target is Windows-only (pywinpty). Linux/macOS would use `ptyprocess` and a different code path.

## Persona note

`prompts/tools.txt` will gain a short section describing the terminal tools. Persona prompts (`base.txt`, `kuudere.txt`) don't change, but the kuudere persona's natural deadpan reaction to denied or blocked commands fits well.
