# Dashboard Service Control — Design

**Date:** 2026-06-07
**Status:** Draft (pending user review)
**Scope:** Add Start/Stop buttons on the Dashboard for internal singletons, local external processes, and local Docker containers. Out of scope: remote DB server services, log streaming, runtime-flag persistence.

## Goal

Give an admin one-click Start/Stop of every controllable service that already appears on the Dashboard, with semantics that match user intent:

- **External process** (llama-server, shore-pty-service) — spawn / SIGTERM real process; release VRAM, RAM, ports
- **Docker container** (Postgres, Qdrant, Redis, n8n, FileBrowser) — `docker compose start/stop`
- **Internal model singleton** (Whisper STT, Kokoro TTS) — unload from VRAM via `gc + torch.cuda.empty_cache`, gate request entry
- **Internal worker** (LOCOMO worker, Canonicalizer) — flip a runtime flag; APScheduler job add/remove for canonicalizer

The user (not the LLM agent) drives this through the Dashboard UI. No new agent tool.

## Architecture

```
back-end/
├── config/
│   ├── services.yaml          # NEW — user-edited registry, gitignored
│   └── services.example.yaml  # NEW — committed presets template
├── app/
│   ├── services/
│   │   ├── service_manager.py # NEW — ServiceManager singleton (load yaml, dispatch)
│   │   ├── controllers/       # NEW
│   │   │   ├── __init__.py
│   │   │   ├── base.py        # abstract Controller, ServiceState dataclass
│   │   │   ├── process.py     # ProcessController (subprocess.Popen + PID file)
│   │   │   ├── docker.py      # DockerController (docker compose start/stop)
│   │   │   └── internal.py    # InternalController (calls into stt/tts/worker/canonicalizer)
│   │   ├── stt_service.py     # ADD unload() method, gate transcribe() on runtime_flags.STT_ENABLED
│   │   └── tts_service.py     # ADD load()/unload() methods
│   ├── core/
│   │   └── runtime_flags.py   # NEW — mutable runtime overrides initialized from settings
│   └── api/endpoints/
│       └── services.py        # NEW — GET /api/services, POST /api/services/{name}/{start|stop}
└── data/pids/                 # auto-created; one PID file per process-kind entry
```

`ServiceManager` is a singleton:

- On startup, parses `config/services.yaml`. Missing file → empty registry (failsafe). Parse error → log + empty registry.
- For each entry, instantiates one `Controller` of the appropriate kind.
- Holds an `asyncio.Lock` per service to serialize start/stop on the same name.
- Exposes `list_state() -> list[ServiceState]`, `start(name)`, `stop(name)`.

`Controller` ABC:

```python
class ServiceState(BaseModel):
    name: str
    display_name: str
    kind: Literal["process", "docker", "internal"]
    correlates_with: str | None
    running: bool
    transitioning: bool
    pid: int | None = None
    last_action: Literal["start", "stop"] | None = None
    last_action_at: float | None = None
    last_error: str | None = None

class Controller(ABC):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def state(self) -> ServiceState: ...
```

## Registry schema (`services.yaml`)

```yaml
services:
  llama-server:
    kind: process
    display_name: llama-server
    correlates_with: llama-server      # matches dashboard /services name
    start_cmd: 'D:\llama\llama-server.exe -m D:\models\foo.gguf --mmproj D:\models\mmproj.gguf --jinja --host 0.0.0.0 --port 8080 --ctx-size 8192'
    cwd: 'D:\llama'                    # optional
    env: {}                            # optional, merged into os.environ
    stop_signal: SIGTERM               # default SIGTERM; SIGKILL fallback after grace_seconds
    grace_seconds: 10
    # pid_file auto-derived: data/pids/llama-server.pid

  shore-pty-service:
    kind: process
    display_name: shore-pty-service
    correlates_with: shore-pty-service
    start_cmd: 'npm start'
    cwd: 'D:\Jupiter\Luna\ProjectShoreKeeper\Shore-Assistant\shore-pty-service'

  n8n:
    kind: docker
    display_name: n8n
    correlates_with: n8n
    compose_file: 'docker-compose.n8n.yml'
    compose_service: n8n
    use_up_on_start: true              # `up -d` instead of `start` for first-run container creation

  postgres:
    kind: docker
    display_name: Postgres
    correlates_with: Postgres
    compose_file: 'deploy/memory/docker-compose.yml'
    compose_service: postgres

  qdrant: { kind: docker, display_name: Qdrant, correlates_with: Qdrant, compose_file: 'deploy/memory/docker-compose.yml', compose_service: qdrant }
  redis:  { kind: docker, display_name: Redis,  correlates_with: Redis,  compose_file: 'deploy/memory/docker-compose.yml', compose_service: redis }

  whisper-stt:
    kind: internal
    display_name: Whisper STT
    correlates_with: Whisper STT
    target: stt                        # stt | tts | locomo_worker | canonicalizer

  kokoro-tts:
    kind: internal
    display_name: Kokoro TTS
    correlates_with: Kokoro TTS
    target: tts

  locomo-worker:
    kind: internal
    display_name: LOCOMO worker
    target: locomo_worker
    # no correlates_with → matched by display_name in Workers section card

  canonicalizer:
    kind: internal
    display_name: Canonicalizer
    target: canonicalizer
```

- `services.yaml` is gitignored. `services.example.yaml` is committed as a template with all presets and comments.
- Missing entry for a dashboard-visible service → card renders unchanged, no buttons.

## REST API

All endpoints sit under `/api/services`. Auth, CSRF, and admin-role behavior mirror `/api/memory/profile/change`.

### `GET /api/services`

Auth: `Depends(current_user)` (any logged-in user can read state).

```json
{
  "services": [
    {
      "name": "llama-server",
      "display_name": "llama-server",
      "kind": "process",
      "correlates_with": "llama-server",
      "running": true,
      "transitioning": false,
      "pid": 12345,
      "last_action": "start",
      "last_action_at": 1717689600.123,
      "last_error": null
    }
  ]
}
```

### `POST /api/services/{name}/start` and `POST /api/services/{name}/stop`

Auth: `Depends(current_user)` + `Depends(require_admin)` + `Depends(csrf_check)`. Body: empty.

**Returns 202** when the action is dispatched as a background task:
```json
{ "name": "llama-server", "transitioning": true, "action": "start" }
```

**Errors:**
- `404` — name not in registry
- `409` — already transitioning, or already in desired state (start when running, stop when stopped)
- `403` — not admin / missing CSRF
- `500` — controller raised; `last_error` set on state, message returned

### Dashboard endpoint augmentation

`/api/dashboard` services array adds one new field per row:

```json
{
  "name": "llama-server",
  "status": "up",
  "latency_ms": 12.3,
  "control": {
    "name": "llama-server",
    "kind": "process",
    "running": true,
    "transitioning": false,
    "last_error": null
  }
}
```

Workers section rows (LOCOMO worker, Canonicalizer) also gain `control`. Scheduler does not (no Stop semantics in v1).

`control` is `null` whenever the row is not represented in the registry.

## Controller behaviors

### ProcessController

- `start()`:
  - If PID file exists and process is alive → raise 409
  - Windows: `subprocess.Popen(start_cmd, cwd=cwd, env={**os.environ, **env}, shell=True, creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)`
  - Write PID to `data/pids/<name>.pid`
  - Do not block on the process (it is long-lived); set `transitioning=False` after PID is written
- `stop()`:
  - Read PID file. If missing or process dead → delete file, mark stopped, return.
  - Windows: send `CTRL_BREAK_EVENT` to the process group (SIGTERM equivalent for console apps)
  - Poll psutil every 250 ms up to `grace_seconds`. If still alive → `process.kill()` (SIGKILL equivalent)
  - Delete PID file.
- `state()`: PID file exists AND `psutil.pid_exists(pid)` AND `psutil.Process(pid).name()` matches the leading exe in `start_cmd` (defends against PID reuse). Mismatch → treat as stale, delete PID file, return `running=false`.

### DockerController

- `start()`: `docker compose -f <compose_file> {up -d | start} <compose_service>`. Choice driven by `use_up_on_start`. Non-zero exit → store stderr in `last_error`, raise.
- `stop()`: `docker compose -f <compose_file> stop <compose_service>`.
- `state()`: `docker compose -f <compose_file> ps --format json <compose_service>` → parse, return `State == "running"`.
- All subprocess calls use a 30 s timeout; on timeout → record failure, do not retry, do not touch docker.

### InternalController

| target | start | stop | state |
|---|---|---|---|
| `stt` | `stt_service.load_model()` (sync, run in executor) + `runtime_flags.set("STT_ENABLED", True)` | `stt_service.unload()` + `runtime_flags.set("STT_ENABLED", False)` | `stt_service.is_loaded` |
| `tts` | `tts_service.load()` + `runtime_flags.set("TTS_ENABLED", True)` | `tts_service.unload()` + `runtime_flags.set("TTS_ENABLED", False)` | `tts_service.is_available` |
| `locomo_worker` | `runtime_flags.set("WORKER_ENABLED", True)` | `runtime_flags.set("WORKER_ENABLED", False)` | `runtime_flags.get("WORKER_ENABLED")` |
| `canonicalizer` | `runtime_flags.set("CANONICALIZER_ENABLED", True)` + register APScheduler system job | `runtime_flags.set("CANONICALIZER_ENABLED", False)` + remove the APScheduler job | `runtime_flags.get("CANONICALIZER_ENABLED")` |

### New `unload()` methods

```python
# stt_service.py
def unload(self) -> None:
    with self._lock:
        self.pipe = None
        self._is_loaded = False
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
```

Same shape on `tts_service`.

`stt_service.transcribe()` currently auto-reloads on `pipe is None` (stt_service.py:121). Change: check `runtime_flags.get("STT_ENABLED")` first; if False, raise `STTDisabled`. Chat WS handler converts to a "STT is disabled" toast.

### `runtime_flags` (`core/runtime_flags.py`)

- Module-level `dict[str, Any]`, thread-safe `get`/`set` with a single lock
- Initialized from `settings` at startup for keys: `STT_ENABLED`, `TTS_ENABLED`, `WORKER_ENABLED`, `CANONICALIZER_ENABLED`
- Worker loop, canonicalizer registration, STT and TTS gate logic read from `runtime_flags` for these keys (not `settings`)
- Not persisted across restart — flags revert to `.env` defaults

## Frontend

### `ServiceCard` (`Dashboard/index.tsx:162`)

When `s.control != null`:

- Top-left badge mirrors top-right StatusBadge:
  - `running=true` → **Stop** button (red outline)
  - `running=false` → **Start** button (green outline)
  - `transitioning=true` → disabled, spinner, label `Starting…` / `Stopping…`
- If `last_error` is non-null → bottom border in error color + tooltip showing the error text (ellipsis)

### Confirm modal (Stop only)

Radix Dialog (already in project).

```
Stop "llama-server"?

This will terminate the process and release VRAM.
Active chats will fail until you start it again.

                       [Cancel]  [Stop service]
```

Start has no confirm.

### Click flow

1. Confirm (Stop) or direct (Start) → POST `/api/services/{name}/{stop|start}` with `X-CSRF-Token`
2. 202 returned → set local optimistic `transitioning=true` for that card
3. Toast `"Stopping llama-server…"` (info)
4. `DashboardContext.refresh()` runs immediately, then poll at 1 s intervals (instead of 5 s) until that card's `transitioning=false`. Hard timeout: 30 s total wall-clock, after which the hook stops accelerated polling and shows a "stuck transitioning" warning toast.
5. On stable state: toast `"llama-server stopped"` (success) or `"Failed to stop: <last_error>"` (error)
6. Reset poll interval to 5 s

### Workers section (`Dashboard/index.tsx:408`)

LOCOMO and Canonicalizer cards get a small Start/Stop button between name and StatusBadge. Scheduler card does not get a button.

### New services-api client

`front-end/src/services/services-api.service.ts` mirrors `memory-api.service.ts` for CSRF header injection.

### Service not in registry

`s.control == null` → card renders identical to today, no buttons.

## Edge cases

- **Backend restart with external process still running**: PID file from previous run still on disk. `state()` verifies process is alive and name matches → `running=true` reflects reality. No automatic adopt — admin can choose to Stop.
- **Orphan PID file**: process died externally, file remains. State check detects, deletes the file, marks `running=false`.
- **Docker compose service missing in file**: subprocess exits non-zero, stderr captured to `last_error`, frontend shows toast.
- **YAML parse error at startup**: error logged, registry empty, dashboard still renders, no buttons appear. `/health` unaffected.
- **STT/TTS unload while a transcribe is in flight**: `unload()` takes the same `self._lock` as `transcribe()` → waits for completion. Next audio frame is rejected because `runtime_flags.STT_ENABLED=False`.
- **Two admins click Stop simultaneously**: per-service `asyncio.Lock` → second request gets 409.
- **Stop Postgres while chat is open**: docker stops gracefully, asyncpg pool raises on next query. Memory facade's 500 ms per-layer circuit breaker (existing behavior) keeps chat alive with short-term-only context. This is the intended degradation.
- **Stop llama-server during a streaming token response**: WS stream fails mid-response. Frontend chat already handles WS errors. Acceptable — that is exactly what the admin asked for.

## Testing

**Backend unit tests:**
- `tests/services/test_service_manager.py` — YAML load, dispatch to controllers (controllers mocked)
- `tests/services/controllers/test_process_controller.py` — Popen mocked, PID file lifecycle, stale-PID detection via name mismatch
- `tests/services/controllers/test_docker_controller.py` — subprocess mocked, `ps --format json` parsing
- `tests/services/controllers/test_internal_controller.py` — runtime_flags toggle, stt/tts `unload` mocked
- `tests/api/test_services_endpoint.py` — auth gate, CSRF gate, 409 on concurrent action, 404 on unknown name

**Backend integration:** skipped (requires real docker / llama-server). Documented manual smoke test in CLAUDE.md.

**Frontend:** unit test for the polling-acceleration hook (`useServicesControl`). Visual check of the Radix dialog flow in dev browser.

**Manual end-to-end:** start/stop each kind at least once. Verify VRAM release via `nvidia-smi` after stopping llama-server and Whisper STT.

## Rollout

- **Phase A** — Backend: ServiceManager, controllers, runtime_flags, endpoints, tests.
- **Phase B** — Frontend: buttons, modal, polling acceleration.
- **Phase C** — Ship `services.example.yaml`, update CLAUDE.md (note about `config/services.yaml`), no new env vars.

**No breaking changes**: missing `services.yaml` preserves current behavior exactly.

## Out of scope (v1)

- Log streaming for start/stop
- Persistence of runtime flags across restart
- Remote DB server control (would need SSH or a remote agent)
- Restart shortcut (admin uses Stop then Start for now)
- Bulk "start all databases" group action
