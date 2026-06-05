# file_tool — AI Agent System Core

**System Core** is the foundation layer of an AI Agent system, written in Rust. It gives the agent eyes and hands on the real machine — reading/writing files, managing processes, executing commands — through two parallel interfaces:

| Mode | When to use |
|------|-------------|
| **CLI** (`file_tool <command>`) | Local use, scripting, debugging |
| **HTTP Server** (`file_tool --serve`) | Agent orchestrator or Docker containers calling in |

---

## Design Philosophy

A tool does not just execute — it must **return enough context** for the LLM to make the next decision without guessing.

```
Bad:   "file content here..."

Good:  {
  "content": "...",
  "size_bytes": 4200,
  "lines": 134,
  "encoding": "utf-8",
  "is_binary": false,
  "truncated": false,
  "git_status": "modified",
  "workspace_relative": "src/main.rs"
}
```

The LLM now knows: the file is small, text, currently modified in git — it can confidently decide the next step.

Every response is wrapped in a standard **ToolEnvelope** — see [details below](#tool-envelope-response-format).

---

## Architecture in an Agent System

```
┌─────────────────────────────────────────────┐
│           Docker Microservices              │
│                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │  Memory  │  │   RAG    │  │  Agent   │  │
│  │ :8001    │  │  :8002   │  │  Core    │  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  │
│       └──────────────┴──────────────┘        │
│                      │ host.docker.internal  │
└──────────────────────┼──────────────────────┘
                       │ HTTP POST
         ┌─────────────▼──────────────┐
         │   file_tool --serve :9000  │  ← runs on Windows host
         │  /api/filesystem/*         │
         │  /api/process/*            │
         │  /api/shell/*              │
         └─────────────┬──────────────┘
                       │ direct OS calls
                  Windows Host
```

**Key principle**: Only `file_tool` touches the host OS. Every other container communicates through this single HTTP API. Allowlists, audit logging, and rate limiting are centralized in one place.

---

## Requirements

- **Rust** 1.85+ (edition 2024)
- **Windows 10/11** (tested), Linux/macOS (compatible)
- **Docker Desktop** (only needed for `run-in-container`)
- **Git** in PATH (for git status detection in filesystem tools)

---

## Build & Install

```bash
# Build release binary
cargo build --release

# Output:
# Windows: target\release\file_tool.exe
# Linux:   target/release/file_tool
```

Add to PATH or invoke with the full path.

---

## Server Mode (HTTP API)

### Starting the server

```bash
file_tool --serve --port 9000 --token my-secret-token --workspace C:\projects\myapp
```

| Flag | Default | Description |
|------|---------|-------------|
| `--serve` | — | Enable server mode |
| `--port` | `9000` | Port to listen on |
| `--token` | (empty) | Bearer token for auth. Empty = no auth (localhost-only recommended) |
| `--workspace` | `.` | Root directory — all file operations are confined here |

The server binds to `127.0.0.1:<port>` — accessible only from localhost and Docker containers via `host.docker.internal`.

### Authentication

All requests to `/api/*` require the header:
```
Authorization: Bearer my-secret-token
```

The `/health` endpoint is public and requires no auth.

### Calling from a Docker container

```bash
# Inside a container, the host machine is reachable at:
host.docker.internal:9000
```

Example from Python inside a container:
```python
import requests

res = requests.post(
    "http://host.docker.internal:9000/api/filesystem/read",
    headers={"Authorization": "Bearer my-secret-token"},
    json={"path": "src/main.rs"}
)
print(res.json()["result"]["content"])
```

---

## CLI Mode

```bash
file_tool [--workspace <path>] <COMMAND> [OPTIONS]
```

`--workspace` is a global flag that sets the root directory for all commands.

---

## Command & API Reference

### Filesystem

#### `read` / `POST /api/filesystem/read`

Read a file and return its content with full metadata.

```bash
# CLI
file_tool read --path src/main.rs

# API
curl -X POST http://localhost:9000/api/filesystem/read \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"path": "src/main.rs"}'
```

`result` shape:
```json
{
  "content": "fn main() { ... }",
  "path": "C:\\projects\\myapp\\src\\main.rs",
  "workspace_relative": "src/main.rs",
  "size_bytes": 4200,
  "lines": 134,
  "encoding": "utf-8",
  "is_binary": false,
  "truncated": false,
  "truncated_at_byte": null,
  "last_modified": "2026-06-01T09:10:00Z",
  "git_status": "modified"
}
```

---

#### `list` / `POST /api/filesystem/list`

List directory contents.

```bash
file_tool list --path src/
```

API body: `{"path": "src/"}`

`result` shape:
```json
{
  "path": "C:\\projects\\myapp\\src",
  "entries": [
    { "name": "main.rs", "type": "file", "size_bytes": 4200, "last_modified": "...", "git_status": "modified" },
    { "name": "utils/",  "type": "dir",  "children_count": 3 }
  ],
  "total_entries": 2,
  "hidden_entries_omitted": 1,
  "workspace_root": "C:\\projects\\myapp"
}
```

---

#### `exists` / `POST /api/filesystem/exists`

```bash
file_tool exists --path src/config.json
```

API body: `{"path": "src/config.json"}`

---

#### `write` / `POST /api/filesystem/write`

Write a file. Automatically backs up the old file before overwriting.

```bash
file_tool write --path src/config.json --content '{"debug": true}'
# Or from a file
file_tool write --path src/config.json --from-file /tmp/new_config.json
# Or from stdin
echo '{"debug": true}' | file_tool write --path src/config.json
```

API body: `{"path": "src/config.json", "content": "{\"debug\": true}"}`

`result` shape:
```json
{
  "success": true,
  "path": "...",
  "bytes_written": 16,
  "previous_size_bytes": 14,
  "backup_created_at": "C:\\projects\\myapp\\.agent_backups\\config.json.20260601_091500",
  "diff_summary": "+1 lines, -1 lines"
}
```

---

#### `create-dir` / `POST /api/filesystem/create-dir`

```bash
file_tool create-dir --path src/new_module/
```

API body: `{"path": "src/new_module/"}`

---

#### `move` / `POST /api/filesystem/move`

```bash
file_tool move --src old_name.rs --dst new_name.rs
file_tool move --src old_name.rs --dst new_name.rs --force  # overwrite if dst exists
```

API body: `{"src": "old_name.rs", "dst": "new_name.rs", "force": false}`

---

#### `copy` / `POST /api/filesystem/copy`

```bash
file_tool copy --src template.rs --dst new_module.rs
```

API body: `{"src": "template.rs", "dst": "new_module.rs", "force": false}`

---

#### `delete` / `POST /api/filesystem/delete`

Soft-delete — moves to `.agent_trash/`, never permanently deleted.

```bash
file_tool delete --path old_config.json
```

API body: `{"path": "old_config.json"}`

`result` shape:
```json
{
  "success": true,
  "path": "...",
  "moved_to_trash": "C:\\projects\\myapp\\.agent_trash\\old_config.json.20260601",
  "recoverable": true
}
```

---

#### `search` / `POST /api/filesystem/search`

Search file contents across the workspace. Supports literal and regex, respects `.gitignore`.

```bash
file_tool search --query "fn main" --regex false
file_tool search --query "async fn \w+" --regex --ignore-case --include "*.rs" --context 2
```

API body:
```json
{
  "query": "fn main",
  "regex": false,
  "max_results": 100,
  "include": "*.rs",
  "ignore_case": false,
  "context": 1
}
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `query` | required | Search string |
| `regex` | `false` | Treat query as regex |
| `max_results` | `100` | Result cap |
| `include` | (all files) | Glob pattern, e.g. `"*.rs"` |
| `ignore_case` | `false` | Case-insensitive matching |
| `context` | `1` | Lines of context before/after each match |

---

#### `diff` / `POST /api/filesystem/diff`

Compare two files and return a unified diff.

```bash
file_tool diff --path-a src/v1.rs --path-b src/v2.rs
```

API body: `{"path_a": "src/v1.rs", "path_b": "src/v2.rs"}`

---

#### `patch` / `POST /api/filesystem/patch`

Apply a unified diff patch to a file.

```bash
file_tool patch --path src/main.rs --patch-file changes.patch
```

API body: `{"path": "src/main.rs", "patch_content": "--- a/...\n+++ b/...\n@@..."}`

---

### Process Manager

#### `list-processes` / `POST /api/process/list`

List processes owned by the current user (other users' processes are hidden).

```bash
file_tool list-processes
```

API body: `{}` (empty)

`result` shape:
```json
{
  "processes": [
    {
      "pid": 1234,
      "name": "python",
      "cmdline": "python server.py --port 8080",
      "cpu_percent": 2.1,
      "memory_mb": 145,
      "status": "running",
      "started_at": "2026-06-01T08:00:00Z"
    }
  ],
  "system_load": { "one_m": 0.4, "five_m": 0.6, "fifteen_m": 0.5 },
  "memory_available_mb": 3200
}
```

---

#### `process-info` / `POST /api/process/info`

```bash
file_tool process-info --pid 1234
```

API body: `{"pid": 1234}`

---

#### `kill-process` / `POST /api/process/kill`

Only kills processes spawned by the agent itself. Refuses to kill PID 0, PID 1, the parent orchestrator, or itself.

```bash
file_tool kill-process --pid 1234
file_tool kill-process --pid 1234 --force  # SIGKILL instead of SIGTERM
```

API body: `{"pid": 1234, "force": false}`

---

#### `spawn-process` / `POST /api/process/spawn`

Spawn a process with a mandatory timeout. A watchdog thread force-kills the process when the timeout expires.

```bash
file_tool spawn-process --cmd python worker.py --timeout 60
```

API body: `{"cmd": ["python", "worker.py"], "timeout": 60}`

**Allowed commands**: `python`, `python3`, `node`, `npm`, `npx`, `cargo`, `rustc`, `git`, `pytest`, `java`, `javac`, `echo`

`result` shape:
```json
{
  "pid": 5678,
  "cmdline": ["python", "worker.py"],
  "started_at": "2026-06-01T09:15:00Z",
  "stdout_log": "C:\\Temp\\agent_proc_5678.log",
  "timeout_set_seconds": 60,
  "will_auto_kill_at": "2026-06-01T09:16:00Z"
}
```

---

#### `resource-usage` / `POST /api/process/resource-usage`

System-wide CPU, memory, and uptime snapshot.

```bash
file_tool resource-usage
```

API body: `{}` (empty)

---

#### `watch-process` / `POST /api/process/watch`

Monitor a process's CPU and memory usage over time, collecting time-series samples.

```bash
file_tool watch-process --pid 1234 --duration 10
```

API body: `{"pid": 1234, "duration": 5}` — max duration: 30 seconds.

---

### Shell Executor

> **Warning**: This is the highest-risk group. Use only when necessary. Prefer `run-in-container` for the strongest isolation.

#### `run-command` / `POST /api/shell/run-command`

Execute a command directly on the host without a shell wrapper (no `shell=true`, no interpolation).

```bash
file_tool run-command --cmd git status
file_tool run-command --cmd python -m pytest tests/ --timeout 30
```

API body: `{"cmd": ["git", "status"], "timeout": 10}`

**Allowed commands**: `git`, `ls`, `dir`, `cat`, `type`, `grep`, `python`, `python3`, `pip`, `pip3`, `cargo`, `rustc`, `npm`, `node`, `pytest`, `java`, `javac`, `echo`, `pwd`, `whoami`, `where`, `which`

| Parameter | Default | Max |
|-----------|---------|-----|
| `timeout` | 10s | 60s |

`result` shape:
```json
{
  "command": ["git", "status"],
  "stdout": "On branch main\nnothing to commit",
  "stderr": "",
  "exit_code": 0,
  "duration_ms": 45,
  "working_dir": "C:\\projects\\myapp",
  "timed_out": false,
  "timeout_was": 10,
  "resource_usage": { "cpu_seconds": 0.04, "peak_memory_mb": 18 },
  "network_calls_blocked": false
}
```

---

#### `run-script` / `POST /api/shell/run-script`

Run a script file inside the workspace. The script must be located within `--workspace` — symlink traversal is blocked via `canonicalize()` + `starts_with()`.

```bash
file_tool run-script --path scripts/build.py --timeout 30
```

API body: `{"path": "scripts/build.py", "timeout": 30}`

**Supported extensions**: `.py` → `python`, `.js` → `node`

---

#### `run-in-container` / `POST /api/shell/run-in-container`

Run a command inside a Docker container with the strictest isolation.

```bash
file_tool run-in-container --cmd python -c "import sys; print(sys.version)"
file_tool run-in-container --cmd python script.py --image python:3.12-slim --timeout 60
```

API body:
```json
{
  "cmd": ["python", "-c", "print('hello')"],
  "image": "python:3.12-slim",
  "timeout": 30
}
```

Docker flags applied automatically:
```
--network none          # no outbound network
--read-only             # container filesystem is read-only
--tmpfs /tmp            # ephemeral writable scratch space
--memory 512m           # RAM cap
--cpus 0.5              # CPU cap
-v workspace:/workspace:ro  # workspace mounted read-only
```

| Parameter | Default | Max |
|-----------|---------|-----|
| `image` | `python:3.12-slim` | — |
| `timeout` | 30s | 120s |

---

## Tool Envelope — Response Format

Every response (CLI and API) is wrapped in a `ToolEnvelope`:

```json
{
  "tool": "read_file",
  "status": "success",
  "duration_ms": 23,
  "risk_level": "low",
  "reversible": true,
  "result": { "...": "actual result data here" },
  "suggested_next_actions": [
    "Use /api/filesystem/write to modify after review."
  ],
  "warnings": []
}
```

| Field | Purpose |
|-------|---------|
| `tool` | Name of the tool that executed |
| `status` | `"success"` or `"error"` |
| `duration_ms` | Execution time in milliseconds |
| `risk_level` | `"low"` / `"medium"` / `"high"` — the LLM knows how cautious to be |
| `reversible` | Whether the action can be undone |
| `result` | The actual result payload |
| `suggested_next_actions` | Optional hints to guide the LLM's next step |
| `warnings` | Any warnings relevant to the action taken |

**On error** (HTTP 500):
```json
{
  "status": "error",
  "tool": "read_file",
  "message": "Path 'C:\\Windows\\System32' is outside the workspace..."
}
```

---

## Safety Model

### Path Sandbox
Every file operation is confined to `--workspace`. Paths are resolved with `canonicalize()` to prevent symlink-based traversal before the `starts_with(workspace_root)` check.

### Process Guardrails
- `list-processes`: Only shows processes owned by the current user
- `kill-process`: Refuses PID 0, PID 1, the orchestrator's PID, and the tool's own PID
- `spawn-process`: A background watchdog thread force-kills the child after timeout expires

### Command Allowlists
Both `run-command` and `spawn-process` enforce a hardcoded allowlist. Matching is done on the filename stem (lowercase), so `python.exe` matches `python`.

### Output Cap
All stdout/stderr is capped at 1 MB per stream to prevent context flooding for the LLM.

### Pipe Deadlock Prevention
`run-command` and `run-in-container` spawn concurrent reader threads for stdout and stderr, preventing deadlocks when a process writes more than the OS pipe buffer (~64 KB).

---

## Development

### Running tests

```bash
cargo test
```

20 tests currently:
- 3 safety allowlist tests
- 4 process manager tests (list, info, kill protection, resource usage)
- 3 spawn/watch tests
- 4 shell executor tests (allowlist, empty command, workspace boundary, unsupported extension)
- 6 integration tests (git version, script extension rejection, container empty command...)

### Module structure

```
src/
├── main.rs                      ← CLI entry point (clap) + serve mode
├── server/
│   └── mod.rs                   ← HTTP server (axum) — 21 endpoints
├── models/
│   └── mod.rs                   ← ToolEnvelope<T> + all response structs
├── commands/
│   ├── mod.rs
│   ├── read.rs                  ← read_file, file_exists
│   ├── list.rs                  ← list_dir
│   ├── write.rs                 ← write_file, create_dir
│   ├── delete.rs                ← delete_file (soft, to trash)
│   ├── mutate.rs                ← move_file, copy_file
│   ├── search.rs                ← search_files
│   ├── diff.rs                  ← diff_file, patch_file
│   ├── process_manager/
│   │   ├── mod.rs
│   │   ├── list.rs              ← list_processes
│   │   ├── info.rs              ← get_process_info
│   │   ├── kill.rs              ← kill_process
│   │   ├── spawn.rs             ← spawn_process + watchdog thread
│   │   ├── resource.rs          ← get_resource_usage
│   │   └── watch.rs             ← watch_process
│   └── shell_executor/
│       ├── mod.rs
│       ├── run_command.rs       ← run_command + allowlist
│       ├── run_script.rs        ← run_script + workspace boundary
│       └── run_in_container.rs  ← run_in_container + Docker isolation
├── safety/
│   ├── mod.rs
│   └── allowlist.rs             ← assert_within_workspace()
└── utils/
    └── mod.rs
```

### Key dependencies

| Crate | Purpose |
|-------|---------|
| `axum 0.8` | HTTP server (server mode) |
| `tokio 1` | Async runtime for axum |
| `clap 4` | CLI argument parsing |
| `serde / serde_json` | JSON serialization |
| `sysinfo 0.38` | Process info and resource monitoring |
| `git2` | Git status detection |
| `similar` | Diff generation |
| `ignore` | Workspace file walking (respects .gitignore) |
| `anyhow` | Error handling |

---

## Roadmap

This project is **Group 1 — System Core** in a larger AI Agent Tool roadmap. See `tool_build_roadmap.md` for the full plan.

| Group | Status | Description |
|-------|--------|-------------|
| **Group 1 — System Core** | ✅ Complete | FileSystem, Process Manager, Shell Executor + HTTP Server |
| Group 2 — Context & Retrieval | Not started | Web Search, RAG, Memory, Log Reader |
| Group 3 — UI & Automation | Not started | Browser Controller, API Integration, Desktop Automation |
| Group 4 — Heavy AI Workers | Not started | Vision, Audio, Code Interpreter |
