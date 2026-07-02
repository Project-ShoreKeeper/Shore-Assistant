# Shore Assistant

A voice-first AI assistant. The FastAPI backend is an **orchestrator only** — all
GPU/ML workloads (STT, TTS, embeddings) run in a separate `shore-ai-service`
gRPC microservice; LLM + Vision run in `llama-server`. The backend ships no
`torch`/`transformers`/`kokoro`/`sentence-transformers`.

## Working Rules

- Do not make any changes until you have 95% confidence in what you need to build. Ask follow-up questions until you reach that confidence.

## Architecture

```
Browser (React + TypeScript + Vite)
  ├── Silero VAD (in-browser ONNX, 16kHz/512-sample chunks)
  ├── Chat WebSocket client → ws://localhost:9000/ws/chat
  └── TTS PCM audio player (AudioContext)

FastAPI Backend (Python) — orchestrator, no local AI/ML deps
  ├── /ws/chat    — Full pipeline: Audio/Text → STT → Agent → LLM → TTS (cookie-auth at upgrade)
  ├── /api/auth/{login,callback,logout,me} — Google OAuth + Redis-backed sessions, gated by AUTH_ENABLED
  ├── /api/dashboard — Aggregated status: services, databases, hardware (psutil + nvidia-smi), workers, shore-ai components; rows include `control` when a service appears in services.yaml
  ├── /api/services — GET list + POST {name}/{start,stop} for registered services (admin + CSRF on writes)
  ├── ai_client (gRPC) — STT.Transcribe / TTS.Synthesize (server-streaming PCM) / Embed.Encode / Health.Get → shore-ai-service; Start/Stop/Status → shore-ai-supervisor
  ├── LLM Agent   (llama.cpp llama-server, OpenAI-compatible /v1/chat/completions, native tool calling, bounded multi-round loop)
  ├── Tool Retriever (embedding cosine similarity via shore-ai-service Embed, all-MiniLM-L6-v2)
  ├── Cloud sub-agents (ask_claude / ask_gemini / ask_openai — escalate a task to Claude / Gemini / GPT)
  ├── Tools        (system_time, read_file, list_directory, clear_memory, search_web, web_scrape, capture_screen, analyze_screen, set_reminder, set_scheduled_task, cancel_task, list_tasks, ask_claude/ask_gemini/ask_openai, run_command + PTY tools, start_background_service + list/stop/logs + dynamic n8n workflow tools)
  ├── Scheduler    (APScheduler — one-shot reminders + recurring tasks, persisted to JSON)
  ├── Notifications (proactive push via ConnectionManager → agent pipeline → TTS; sources: scheduler, n8n webhooks)
  ├── Memory       (Hybrid: Redis short-term + Postgres profile + Qdrant episodic; circuit-broken per layer; LOCOMO worker auto-extracts via a LOCAL LLM on 30s idle; nightly canonicalizer dedupes entity tags)
  ├── Vision       (client-side getDisplayMedia capture → primary multimodal model via /v1/chat/completions)
  └── n8n          (two-way integration: dynamic workflow tools + inbound webhook notifications)

shore-ai-service (Docker container, GPU, gRPC)
  ├── STT.Transcribe   — Whisper (unary)
  ├── TTS.Synthesize   — Kokoro → Int16 PCM (server-streaming)
  ├── Embed.Encode     — sentence-transformers all-MiniLM-L6-v2 (unary, batch)
  └── Health.Get       — readiness + per-component loaded flags

shore-ai-supervisor (host process, gRPC control plane)
  └── docker compose start / stop / ps for the shore-ai container

Node PTY microservice (shore-pty-service)
  └── node-pty executor — PTY/process host at ws://127.0.0.1:9100 (sole backend for terminal_service)
```

## Project Structure

```
Shore-Assistant/
├── shore-ai-service/       # Docker gRPC microservice: STT (Whisper) + TTS (Kokoro) + Embed (sentence-transformers), --gpus all
├── shore-ai-supervisor/    # Host gRPC control plane: docker compose start/stop/ps for shore-ai
├── shore-pty-service/      # Node + TypeScript microservice: node-pty + child_process executor (ws://127.0.0.1:9100)
├── back-end/
│   ├── config/services.yaml            # Service-control registry (gitignored; example at services.example.yaml)
│   └── app/
│       ├── main.py                     # FastAPI app factory + lifespan + router includes
│       ├── core/
│       │   ├── config.py               # Pydantic settings (llama-server, shore-ai gRPC, cloud, terminal, auth, memory)
│       │   ├── runtime_flags.py        # Mutable runtime overrides for WORKER_ENABLED / CANONICALIZER_ENABLED (toggled by service control)
│       │   ├── auth.py                 # User / Session types + Redis-backed SessionStore + current_user_id ContextVar
│       │   └── allowlist.py            # Parse AUTH_ALLOWED_EMAILS + resolve_role (first email = admin)
│       ├── api/
│       │   ├── deps.py                 # FastAPI Depends: current_user, csrf_check, require_admin
│       │   ├── endpoints/
│       │   │   ├── health.py           # GET / and /health (tri-state: healthy/degraded/unhealthy)
│       │   │   ├── auth.py             # /api/auth/{login,callback,logout,me} — Google OAuth + session lifecycle
│       │   │   ├── memory.py           # /api/memory/* — Profile, Episodic, Audit admin API (admin-only when auth enabled)
│       │   │   ├── dashboard.py        # GET /api/dashboard — services + databases + hardware + workers + ai_components snapshot
│       │   │   ├── services.py         # /api/services/* — list + admin-only start/stop endpoints, 202 fire-and-forget
│       │   │   ├── chronicles.py       # GET /api/chronicles + /{slug} — serves docs/chronicles/*.md with YAML frontmatter
│       │   │   ├── voices.py           # /api/voices/* — Fish Speech reference-voice CRUD (EXPERIMENTAL, not mounted in main.py)
│       │   │   └── n8n_webhook.py      # POST /api/n8n/webhook, /refresh, GET /status
│       │   └── websockets/
│       │       └── chat_ws.py          # /ws/chat (full pipeline + TTS relay)
│       ├── schemas/messages.py         # Pydantic WS message models
│       ├── prompts/
│       │   ├── base.txt                # Base persona system prompt template
│       │   ├── kuudere.txt             # Kuudere persona system prompt template
│       │   ├── tools_core.txt          # Always-loaded tool rules (general protocol + always-available tools + run_command)
│       │   ├── tools_terminal.txt      # PTY/session rules (loaded only when terminal tools retrieved)
│       │   ├── tools_background.txt    # Background service rules (loaded only when background tools retrieved)
│       │   ├── tools_n8n.txt           # n8n workflow rules (loaded only when an n8n_ tool is retrieved)
│       │   ├── locomo_extractor.txt    # System prompt for the LOCOMO extraction worker
│       │   └── user.txt                # Optional user context appended to persona
│       ├── services/
│       │   ├── ai_client/               # gRPC clients to shore-ai-service + shore-ai-supervisor
│       │   │   ├── channel.py           # Long-lived grpc.aio channels (TLS + Bearer metadata + keepalive)
│       │   │   ├── stt.py               # stt_client.transcribe() — graceful-degrade on UNAVAILABLE/DEADLINE/RESOURCE
│       │   │   ├── tts.py               # tts_client.stream_pcm() — two-tier deadline (first-chunk + overall)
│       │   │   ├── embed.py             # embed_client.encode() — raises EmbedUnavailable on graceful codes
│       │   │   ├── health.py            # health_client.get() — readiness + components
│       │   │   ├── supervisor.py        # supervisor_client.start/stop/status (shore-ai container)
│       │   │   └── _pb/                 # generated proto stubs (gitignored)
│       │   ├── service_manager.py      # Registry loader + per-service asyncio lock; dispatches start/stop to controllers
│       │   ├── controllers/             # Service-control backends
│       │   │   ├── base.py              # Controller ABC + ServiceState model (kind: process|docker|internal|remote)
│       │   │   ├── process.py           # ProcessController (subprocess.Popen + PID file w/ create_time verification + tree-kill)
│       │   │   ├── docker.py            # DockerController (`docker compose start/stop/up -d/ps`)
│       │   │   ├── internal.py          # InternalController (locomo_worker / canonicalizer toggles)
│       │   │   └── remote.py            # RemoteServiceController (start/stop/status via shore-ai-supervisor)
│       │   ├── llm_service.py          # llama-server OpenAI-compatible streaming client (httpx), native tool calling, persona + memory block loader
│       │   ├── agent_service.py        # Bounded multi-round tool-calling loop (typed AgentState; MAX_TOOL_ROUNDS=50)
│       │   ├── cloud_llm_service.py    # Cloud sub-agents: call_claude / call_gemini / call_openai (history via ContextVar)
│       │   ├── fish_tts_service.py     # Fish Speech voice-cloning TTS client (EXPERIMENTAL; not wired into the pipeline)
│       │   ├── memory/                  # Hybrid memory package
│       │   │   ├── __init__.py          # exposes memory_facade + worker_service singletons
│       │   │   ├── types.py             # Pydantic contracts for every layer (Message, ContextBundle, WorkerOutput, ...)
│       │   │   ├── short_term.py        # Redis sliding window (per-user)
│       │   │   ├── embedder.py          # Async wrapper over ai_client embed_client
│       │   │   ├── profile.py           # Postgres JSONB single-row snapshot + append-only audit log
│       │   │   ├── episodic.py          # Qdrant async client; deterministic uuid5 point_id for idempotent worker writes
│       │   │   ├── pruning.py           # Prune Profile JSON by oldest top-level key until ≤ MEMORY_PROFILE_MAX_BYTES
│       │   │   ├── facade.py            # MemoryFacade — single entry-point; 500ms per-layer circuit breaker
│       │   │   ├── worker.py            # WorkerService — debounced LOCOMO extraction (idle + safety valve; dual lock)
│       │   │   ├── extractor.py         # LocomoExtractor — local LLM structured output (json_schema), 3-attempt retry
│       │   │   └── canonicalizer.py     # Nightly entity-tag dedup (cosine clustering)
│       │   ├── scheduler_service.py    # APScheduler: one-shot & recurring tasks + internal system jobs
│       │   ├── notification_service.py # Scheduler/n8n → agent pipeline → proactive TTS
│       │   ├── connection_manager.py   # Singleton WebSocket send handle for background push
│       │   ├── tool_retriever.py       # Embedding-based tool selection (uses ai_client embed_client)
│       │   ├── terminal_service.py     # Policy + broadcast + ANSI-strip layer over a TerminalBackend
│       │   ├── terminal_backend.py     # Abstract terminal backend contract
│       │   ├── node_pty_client.py      # WS client to shore-pty-service (reconnect/heartbeat)
│       │   ├── terminal_whitelist.py   # Command allowlist for run_command / PTY tools
│       │   ├── background_service.py   # Long-running background service registry + log capture
│       │   ├── n8n_service.py          # n8n workflow discovery, dynamic tool creation, webhook trigger
│       │   └── n8n_workflow_service.py # n8n workflow authoring (n8nac) backing the n8n_* authoring tools
│       ├── tools/
│       │   ├── __init__.py             # Tool registry (ALL_TOOLS, TOOL_MAP, register/unregister dynamic tools)
│       │   ├── system_tools.py         # get_system_time, read_file, list_directory, clear_memory
│       │   ├── web_tools.py            # search_web (DuckDuckGo), web_scrape (readability-lxml)
│       │   ├── screen_tools.py         # capture_screen, analyze_screen (primary multimodal model)
│       │   ├── scheduler_tools.py      # set_reminder, set_scheduled_task, cancel_task, list_tasks
│       │   ├── cloud_tools.py          # ask_claude, ask_gemini, ask_openai
│       │   ├── terminal_tools.py       # run_command + open/send/read/list/close_terminal
│       │   ├── background_tools.py     # start/list/stop/get_logs background_service
│       │   └── n8n_workflow_tools.py   # n8n_search_nodes / get_node_schema / search_templates / create / build_complex / manage
│       └── utils/audio_utils.py        # PCM/float32 conversion
│
└── front-end/
    └── src/
        ├── routers/PublicRoutes.tsx        # React Router route definitions
        ├── layouts/AppLayout/              # Shell layout (index, Footer, Sidebar)
        ├── services/                       # vad, chat-websocket, memory-api, dashboard, chronicles clients
        ├── hooks/                          # useAssistant (VAD+LLM+TTS), useDashboardPoll
        ├── components/AgentActionLog.tsx   # Real-time agent action display
        ├── pages/                          # Dashboard, Memory, Chronicles, Chat (+ SettingsPanel)
        ├── utils/                          # audio.util, tts-player.util
        ├── models/stt.model.ts             # TypeScript config interfaces
        └── constants/stt.constant.ts       # WS URLs, languages, models
```

## Commands

### Backend
```bash
cd back-end

# Install dependencies (orchestrator only — no torch/transformers/kokoro/sentence-transformers)
pip install -r requirements.txt

# Start server (must run from back-end/ directory)
python -m uvicorn app.main:app --reload --port 9000

# Start memory stack (on the LAN DB server, once)
ssh <server>
cd Shore-Assistant/deploy/memory && docker compose up -d

# (Optional) Expose Glances JSON API on the LAN DB server so the Dashboard
# can probe its CPU/RAM/disk/GPU. One-time install on the server:
ssh <server>
pip install glances[web]
# Run (background — wrap in tmux/systemd for persistence):
glances -w --disable-webui --port 61208 --bind 0.0.0.0
# Then in back-end/.env: REMOTE_SERVER_ENABLED=True,
# REMOTE_SERVER_GLANCES_URL=http://<server>:61208, REMOTE_SERVER_NAME="DB Server"
```

### Shore AI Service (STT + TTS + Embed) — GPU machine
```bash
# gRPC microservice owning all ML workloads. Runs as a Docker container with
# --gpus all. The shore-ai-supervisor host process exposes Start/Stop/Status
# so the backend (RemoteServiceController) can control it from the Dashboard.
cd shore-ai-service
make proto            # regenerate gRPC stubs (also consumed by the backend)
docker compose up -d  # build + run the container (see shore-ai-service/README.md)

cd ../shore-ai-supervisor
# Run the supervisor gRPC control plane on the host (see its README.md)
```
Backend connects via `SHORE_AI_GRPC_URL` / `SHORE_AI_SUPERVISOR_GRPC_URL`
(TLS + shared Bearer token in gRPC metadata; see Configuration).

### Terminal Microservice (shore-pty-service)
```bash
cd shore-pty-service
npm install
npm run build
npm start          # Starts WS server at ws://127.0.0.1:9100
```

### Frontend
```bash
cd front-end
npm install
npm run dev          # Dev server at http://localhost:5173
npm run build        # Production build
npm run lint         # ESLint
```

### External Dependencies
```bash
# llama.cpp llama-server (required for LLM + Vision)
# Build llama.cpp with CUDA + vision (mmproj) support, then run:
llama-server \
  -m models/<your-multimodal-model>.gguf \
  --mmproj models/<your-mmproj>.gguf \
  --jinja \
  --host 0.0.0.0 --port 8080 \
  --ctx-size 8192

# --jinja is required for tool calling.
# --mmproj is required for capture_screen / analyze_screen.
# STT (Whisper), TTS (Kokoro), and embeddings now live in shore-ai-service,
# NOT in the backend — no PyTorch / espeak-ng install needed on the backend host.

# n8n (optional)
docker compose -f docker-compose.n8n.yml up -d
```

## Key Technical Constraints

- **AI workloads are remote**: STT/TTS/Embed run in `shore-ai-service` over gRPC. The backend degrades gracefully (like `MemoryFacade`) when the service is `UNAVAILABLE` / `DEADLINE_EXCEEDED` / `RESOURCE_EXHAUSTED` — chat keeps working, the missing capability is skipped. `embed.py` additionally treats `UNAUTHENTICATED` / `PERMISSION_DENIED` as degradable. The backend ships no `torch`/`transformers`/`kokoro`/`sentence-transformers`.
- **gRPC auth**: TLS (reverse proxy) + a shared Bearer token in call metadata. Call credentials are only attached on TLS channels (`SHORE_AI_USE_TLS=True`); an insecure channel sends no token.
- **Audio pipeline**: 16kHz sample rate, Float32 format, 512-sample VAD chunks (Silero requirement).
- **WebSocket endpoint**: `/ws/chat` only (mixed JSON + binary for the full pipeline). Binary in = Float32 PCM from VAD; binary out = Int16 PCM TTS frames relayed from shore-ai-service.
- **Tool call format**: native OpenAI tool calling. `tool_retriever.get_tool_schemas()` builds `{"type":"function",...}` schemas from each LangChain tool's `args_schema`; llama-server streams `tool_calls` deltas which `_ToolCallAccumulator` (in `llm_service.py`) reassembles and JSON-parses into dict `arguments`. `agent_service.run` is a bounded multi-round loop (`MAX_TOOL_ROUNDS=50`) with a typed `AgentState` dict.
- **Tool retrieval**: Only relevant tools are injected per request via embedding cosine similarity (`tool_retriever.py`, embeddings from shore-ai-service). Always-available tools: `get_system_time`, `clear_memory`, `set_reminder`, `set_scheduled_task`, `list_tasks`, `cancel_task`, `ask_claude`, `ask_gemini`, `ask_openai`, `run_command`. Companion tools: `web_search` always brings `web_scrape`; any terminal tool brings the whole terminal group. Dynamic n8n tools are auto-registered at startup. If the embed service is down, retrieval degrades to always-available tools only.
- **Fresh time via tool**: `get_system_time` is always injected; `tools_core.txt` instructs the LLM to call it for any time question instead of trusting history.
- **Cloud sub-agents**: `ask_claude` (claude-sonnet-4-6), `ask_gemini` (gemini-2.0-flash), `ask_openai` (gpt-4o) escalate a task with recent conversation history (`cloud_llm_service.py`). Each returns an error string (not a raise) when its API key is missing or the call fails. Keys via `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` / `OPENAI_API_KEY`.
- **Thinking mode**: Frontend toggle sends `thinking` config via WebSocket → passed to llama-server as `reasoning_effort: "medium"`. Reasoning tokens stream into a collapsible UI block.
- **Persona system**: System prompt = `prompts/{PERSONA}.txt` + `tools_core.txt` + conditional section files (`tools_terminal.txt`, `tools_background.txt`, `tools_n8n.txt`) + optional `user.txt`. Section files are appended only when their trigger tools appear in the retrieved set. Configured via `PERSONA` env var (`base` or `kuudere`).
- **Scheduler**: APScheduler manages one-shot reminders and recurring tasks. Tasks persist to `data/scheduled_tasks.json`. Missed tasks fire immediately on restart. Internal system jobs (e.g. canonicalizer) are registered via `add_system_job` and stay invisible to `list_tasks`.
- **Proactive notifications**: When a task fires, `NotificationService` feeds a prompt to the agent pipeline so Shore responds in-character with TTS. Queued to disk if no client is connected, drained on reconnect.
- **TTS pipeline**: LLM tokens accumulate → sentence boundary detected → sentence sanitized + queued → `tts_client.stream_pcm` requests Kokoro synthesis from shore-ai-service → Int16 PCM binary frames relayed over the WebSocket. Two-tier deadline: a short first-chunk timeout (`SHORE_AI_TTS_FIRST_CHUNK_TIMEOUT_SECONDS`) then the overall stream timeout. Single `tts_start`/`tts_end` per response.
- **TTS cancellation**: Frontend stops the TTS player immediately when the user sends a new message (voice or keyboard).
- **TTS sanitization**: Strips code blocks, math expressions (`$...$`, `$$...$$`), JSON, URLs, markdown before synthesis.
- **Notification tools disabled**: When notification prompts (scheduler/n8n) run through the agent, tools are not injected (`no_tools=True`) to prevent re-triggering reminders in a loop.
- **Math rendering**: Chat uses remark-math + rehype-katex for inline (`$...$`) and block (`$$...$$`) LaTeX formulas.
- **analyze_screen / capture_screen / Screen Co-pilot all capture the client's browser screen** via `getDisplayMedia`, sent over `/ws/chat` (`RemoteCaptureService`, `app/services/remote_capture.py`) — not the backend host's display. First use in a session shows a "Shore wants to see your screen" consent prompt (getDisplayMedia requires a direct user click; it cannot be triggered silently by an agent-initiated request). Screenshots are never persisted.
- **n8n integration**: Two-way — Shore discovers active n8n webhook workflows via REST API at startup and registers them as dynamic tools; n8n can push notifications to Shore via `POST /api/n8n/webhook`. Opt-in via `N8N_ENABLED=True`.
- **Conversation memory**: Three layers behind `MemoryFacade.assemble_context()`. Short-term (per-user Redis LIST, 15 turns, AOF). Profile (Postgres JSONB single-row + append-only audit log). Episodic (Qdrant `shore_episodic` collection with payload-indexed `entity_tags`/`created_at`/`valence`). Per-layer 500 ms circuit breaker; chat degrades to short-term only if Postgres / Qdrant are down.
- **Memory injection into system prompt**: `chat_ws` calls `memory_facade.assemble_context(user_text, user_id)` per turn and threads the `ContextBundle` into `agent_service.run`, which passes it to `build_system_prompt`. The prompt appends `[Profile]` (compact JSON, capped at `MEMORY_PROFILE_MAX_BYTES`, pruned by per-key `updated_at`) and `[Relevant memories]` (top-K bullet list by cosine similarity — fact + tags). Notifications (`no_tools=True`) drop the bundle to keep proactive nudges free of identity content.
- **Memory admin API**: `/api/memory/*` endpoints (always mounted). Profile: `GET /profile`, `POST /profile/change`, `GET /profile/history?key=...`, `GET /profile/audit?limit=`, `POST /profile/restore {audit_id, reason?}`. Episodic: `GET /episodic/recent?limit=`, `GET /episodic/search?q=&top_k=`, `POST /episodic/upsert`, `DELETE /episodic/{point_id}`. Admin-only (CSRF on writes) when `AUTH_ENABLED=True`; open when disabled.
- **Auth (Google OAuth + Redis sessions)**: Master switch `AUTH_ENABLED` (default False — legacy synthetic-admin mode preserves pre-auth behavior). When enabled: `/api/auth/login` → Google consent → `/api/auth/callback` checks email against `AUTH_ALLOWED_EMAILS` (comma-separated, first email = admin role), creates a session in Redis under `shore:session:<sid>` with sliding TTL, sets an HttpOnly cookie. `/api/auth/me` returns `{email, role, csrf}`; the frontend stores the CSRF token in memory and sends it as `X-CSRF-Token` on writes. `/api/auth/logout` deletes the Redis key + clears the cookie. WS upgrades validate the cookie and close with code 4401 if unauthenticated. **Short-term memory becomes per-user** (`shore:short_term:<user_id>:messages`); Profile and Episodic stay global. **LOCOMO worker only extracts from admin turns** — non-admin allowlisted users can chat without their words reaching Luna's shared identity profile. Public-no-login routes when auth is on: `/health`, `/api/chronicles`.
- **LOCOMO worker**: a **local LLM** (served at `WORKER_LOCAL_LLM_URL`, default the same llama-server) with `response_format=json_schema(WorkerOutput)` runs after `WORKER_IDLE_DELAY_SECONDS` of chat idle. Debounced via `WorkerService.on_turn_completed()` (cancel-on-new-turn). Safety valve fires immediately at `WORKER_MAX_UNPROCESSED_MESSAGES`. Dual-locked via `asyncio.Lock` + Redis `SETNX shore:worker:lock`. Disabled via `WORKER_ENABLED=False`; the Dashboard toggle flips `runtime_flags.WORKER_ENABLED`. Notifications skip the trigger. NOTE: if `WORKER_ENABLED=False` at startup the worker's deps are never wired, so toggling it on at runtime is a no-op until restart.
- **Canonicalizer**: Internal APScheduler job (registered via `scheduler_service.add_system_job`, invisible to `list_tasks`). Cron `0 4 * * *` by default. Greedy single-pass clustering on entity tags at cosine ≥0.85; rewrites Qdrant point payloads in place.
- **Screen Co-pilot**: A toggleable, **action-first** mode. `CopilotService` runs a watch loop that requests frames from the connected browser via `RemoteCaptureService` (`getDisplayMedia`, armed when the user toggles Co-pilot on — the click itself satisfies the browser's user-gesture requirement, so no further prompts appear during the session), and on a meaningful change while the user is idle + past a cooldown, feeds the screenshot to the vision model via a dedicated `run_copilot_pipeline`. Idle detection degrades open (`None`) since browsers cannot read system-wide idle time — only the change-threshold and cooldown gates apply. The agent takes a concrete action; safe commands auto-run and risky ones confirm via the existing `WhitelistGuard` (`allow`/`confirm`/`block`). Output is buffered into one `copilot_message` (silent on the `__NOOP__` sentinel). Off by default (`COPILOT_ENABLED`); the loop runs only inside an explicit session and only while a client is connected; screenshots are ephemeral (never persisted). The browser's native "Stop sharing" control ends the session from the client side too.
- **Service control (Dashboard buttons)**: `back-end/config/services.yaml` (gitignored; example at `services.example.yaml`) registers controllable services across four kinds. `process` → `subprocess.Popen` with PID file under `data/pids/<name>.pid` (verified by `create_time`; optional `pre_stop_cmd`; SIGTERM/CTRL_BREAK → grace → snapshot-based descendant tree SIGKILL). `docker` → `docker compose -f <file> {up -d|start|stop|ps} <service>`. `internal` → `runtime_flags` toggle for `locomo_worker` / `canonicalizer`. `remote` → `shore-ai-supervisor` Start/Stop/Status for the `shore-ai` container. ServiceManager uses a `transitioning` set as a synchronization gate (atomic without `await`) so two concurrent requests on the same name can never both pass. Endpoints: `GET /api/services` (any logged-in user), `POST /api/services/{name}/{start,stop}` returns 202 with admin + CSRF guards. `/api/dashboard` rows include a `control` field merged by `correlates_with` (services/databases) or `display_name` (workers). Frontend `useDashboardPoll` accelerates to 1 s while any service is transitioning, returning to 5 s once stable; Stop shows a Radix confirm dialog, Start does not.

## Configuration

All backend config via environment variables or `.env` file in `back-end/`:

| Variable | Default | Description |
|----------|---------|-------------|
| LLAMA_BASE_URL | http://localhost:8080 | llama-server URL |
| LLAMA_MODEL | gemma-4-26B-A4B-it-UD-Q5_K_M | Optional label sent in the `model` field (llama-server typically ignores) |
| LLAMA_TIMEOUT | 120 | Request timeout (seconds) |
| PERSONA | kuudere | Persona template to load (`base` or `kuudere`) |
| MULTIMODAL_ENABLED | True | Allow image attachments in chat |
| MAX_IMAGES_PER_MESSAGE | 6 | Max images per user message |
| MAX_IMAGE_BYTES | 6291456 | Max image size after base64 decode (6 MB) |
| FILEBROWSER_URL | http://image.shore-keeper.com | FileBrowser URL (probed by Dashboard) |
| **Shore AI microservice** | | |
| SHORE_AI_GRPC_URL | ai.shore-keeper.com:443 | shore-ai-service gRPC target |
| SHORE_AI_SUPERVISOR_GRPC_URL | ai.shore-keeper.com:8443 | shore-ai-supervisor gRPC target |
| SHORE_AI_TOKEN | (empty) | Shared Bearer token sent in gRPC metadata |
| SHORE_AI_USE_TLS | True | Use a TLS channel (token only attached on TLS) |
| SHORE_AI_TIMEOUT_SECONDS | 30.0 | STT + TTS overall RPC timeout |
| SHORE_AI_EMBED_TIMEOUT_SECONDS | 10.0 | Embed RPC timeout |
| SHORE_AI_TTS_FIRST_CHUNK_TIMEOUT_SECONDS | 15.0 | Deadline for the first TTS PCM chunk |
| **Cloud sub-agents** | | |
| ANTHROPIC_API_KEY | (empty) | Key for `ask_claude` (claude-sonnet-4-6) |
| GEMINI_API_KEY | (empty) | Key for `ask_gemini` (gemini-2.0-flash) |
| OPENAI_API_KEY | (empty) | Key for `ask_openai` (gpt-4o) |
| CLOUD_MAX_TOKENS | 4096 | Max output tokens for cloud sub-agents |
| CLOUD_HISTORY_MAX_TURNS | 10 | Conversation turns passed as context to cloud sub-agents |
| **Memory** | | |
| MEMORY_MAX_TURNS | 15 | Max conversation turns retained per session |
| REDIS_URL | redis://localhost:6379/0 | Redis URL for short-term memory |
| REDIS_SHORT_TERM_KEY | shore:short_term | Base prefix; per-user window stored at `{prefix}:{user_id}:messages` |
| POSTGRES_URL | postgresql://shore:changeme@localhost:5432/shore_memory | Postgres DSN for Profile |
| POSTGRES_POOL_MIN | 1 | asyncpg pool min size |
| POSTGRES_POOL_MAX | 5 | asyncpg pool max size |
| QDRANT_URL | http://localhost:6333 | Qdrant URL for Episodic |
| QDRANT_COLLECTION | shore_episodic | Qdrant collection name for episodic facts |
| MEMORY_EPISODIC_TOP_K | 5 | Max episodic facts injected into system prompt per turn |
| MEMORY_EPISODIC_MIN_SCORE | 0.3 | Minimum cosine score for episodic retrieval |
| MEMORY_PROFILE_MAX_BYTES | 2048 | Hard cap for Profile JSON injected into system prompt (compact bytes) |
| **LOCOMO worker + canonicalizer** | | |
| WORKER_ENABLED | True | Enable LOCOMO worker (startup wiring; Dashboard toggles the runtime flag) |
| WORKER_IDLE_DELAY_SECONDS | 30.0 | Idle gap after a turn before the worker fires |
| WORKER_MAX_UNPROCESSED_MESSAGES | 20 | Safety valve: fire immediately at this many unprocessed turns |
| WORKER_LOCAL_LLM_URL | http://localhost:8080/v1 | OpenAI-compatible local API base URL for LOCOMO extraction |
| WORKER_LOCAL_TIMEOUT | 60.0 | Per-attempt local API timeout (seconds) |
| WORKER_LOCK_KEY | shore:worker:lock | Redis SETNX key for cross-process worker mutex |
| WORKER_LOCK_TTL_SECONDS | 120 | TTL on the Redis lock (must exceed 3 attempts + margin) |
| WORKER_LAST_TS_KEY | shore:worker:last_extracted_ts | Redis key tracking the newest processed turn timestamp |
| CANONICALIZER_ENABLED | True | Enable nightly entity-tag dedup job |
| CANONICALIZER_CRON | 0 4 * * * | When to run the canonicalizer (local time) |
| CANONICALIZER_SIMILARITY_THRESHOLD | 0.85 | Cosine threshold for merging entity tags |
| **Scheduler** | | |
| SCHEDULER_TASKS_FILE | data/scheduled_tasks.json | Persisted scheduler task list |
| SCHEDULER_PENDING_FILE | data/pending_notifications.json | Queued notifications for offline client |
| **Tool retriever** | | |
| TOOL_RETRIEVER_MODEL | all-MiniLM-L6-v2 | Embedding model label (served by shore-ai-service) |
| TOOL_RETRIEVER_TOP_K | 3 | Max tools retrieved per query |
| TOOL_RETRIEVER_THRESHOLD | 0.3 | Minimum cosine similarity to include a tool |
| **n8n** | | |
| N8N_ENABLED | False | Enable n8n integration (workflow tools + inbound webhook) |
| N8N_BASE_URL | http://localhost:5678 | n8n instance URL |
| N8N_API_KEY | (empty) | n8n REST API key (Settings → API in n8n UI) |
| N8N_WEBHOOK_SECRET | (empty) | Shared secret for n8n → Shore webhook auth |
| N8N_REFRESH_INTERVAL_MINUTES | 0 | Auto-refresh workflow discovery (0 = disabled) |
| N8N_WORKFLOWS_DIR | data/n8n-workflows | Local dir for n8n workflow authoring artifacts |
| **Node PTY microservice** | | |
| NODE_PTY_WS_URL | wss://terminal.shore-keeper.com | URL of shore-pty-service WS endpoint (reverse-proxied TLS) |
| NODE_PTY_AUTH_TOKEN | (empty) | Optional Bearer token required by shore-pty-service |
| NODE_PTY_RECONNECT_BASE_MS | 1000 | Initial reconnect backoff (milliseconds) |
| NODE_PTY_RECONNECT_MAX_MS | 30000 | Max reconnect backoff (milliseconds) |
| NODE_PTY_PING_INTERVAL_SECONDS | 30 | Heartbeat ping interval |
| NODE_PTY_PING_TIMEOUT_SECONDS | 5 | Pong deadline before treating connection as disconnected |
| **Screen Co-pilot** | | |
| COPILOT_ENABLED | False | Master switch for the action-first screen co-pilot |
| COPILOT_CAPTURE_INTERVAL_SECONDS | 4 | Watch-loop tick interval |
| COPILOT_IDLE_THRESHOLD_SECONDS | 3 | Minimum hands-off idle before analyzing |
| COPILOT_CHANGE_THRESHOLD | 0.06 | Normalized thumbnail diff treated as "changed" |
| COPILOT_COOLDOWN_SECONDS | 45 | Minimum gap between triggers |
| SCREEN_CAPTURE_THUMBNAIL_TIMEOUT_SECONDS | 2.0 | Timeout for the per-tick cheap-thumbnail round trip to the browser |
| SCREEN_CAPTURE_FULL_TIMEOUT_SECONDS | 20.0 | Timeout for a full-resolution frame (generous — covers time to read the consent prompt) |
| COPILOT_MAX_IMAGE_SIZE | 1280 | Longest edge of the JPEG sent to the vision model |
| **Terminal** | | |
| TERMINAL_DEFAULT_CWD | D:\Jupiter | Default working directory for terminal sessions |
| TERMINAL_DEFAULT_SHELL | powershell | Default shell |
| TERMINAL_ONESHOT_TIMEOUT_SECONDS | 60 | Timeout for `run_command` one-shots |
| TERMINAL_SESSION_IDLE_MINUTES | 30 | Idle reaper threshold for sessions |
| TERMINAL_ORPHAN_TIMEOUT_MINUTES | 5 | Orphaned session cleanup threshold |
| TERMINAL_CONFIRM_TIMEOUT_SECONDS | 300 | Time to wait for a terminal confirm response |
| TERMINAL_MAX_OUTPUT_BYTES | 1048576 | Max captured output per command |
| TERMINAL_LLM_OUTPUT_PREVIEW_BYTES | 8192 | Output preview size fed back to the LLM |
| TERMINAL_WHITELIST_FILE | data/terminal_whitelist.json | Built-in command allowlist |
| TERMINAL_USER_WHITELIST_FILE | data/terminal_whitelist_user.json | User-added command allowlist |
| TERMINAL_RUNS_DIR | data/terminal_runs | Per-run output artifacts |
| TERMINAL_AUDIT_LOG | data/terminal_audit.log | Terminal command audit log |
| BACKGROUND_SERVICES_LOG_DIR | data/background_services | Background service log capture dir |
| **Auth** | | |
| AUTH_ENABLED | False | Master switch. When False, app runs as a synthetic admin (pre-auth behavior). |
| AUTH_ALLOWED_EMAILS | (empty) | Comma-separated Google emails. First entry gets `admin` role; others `user`. |
| AUTH_GOOGLE_CLIENT_ID | (empty) | Google OAuth client id |
| AUTH_GOOGLE_CLIENT_SECRET | (empty) | Google OAuth client secret |
| AUTH_SESSION_SECRET | (empty) | Reserved for future cookie signing (32+ bytes recommended) |
| AUTH_SESSION_TTL_SECONDS | 604800 | Session sliding TTL (7 days) |
| AUTH_SESSION_KEY_PREFIX | shore:session: | Redis key prefix for sessions |
| AUTH_OAUTH_STATE_KEY_PREFIX | shore:oauth_state: | Redis key prefix for one-shot OAuth state tokens |
| AUTH_OAUTH_STATE_TTL_SECONDS | 300 | TTL on OAuth state token (5 min) |
| AUTH_COOKIE_NAME | shore_session | Session cookie name |
| AUTH_COOKIE_SECURE | True | Set False for local http dev |
| AUTH_COOKIE_SAMESITE | lax | SameSite attribute on the session cookie |
| AUTH_COOKIE_DOMAIN | (empty) | Set to `.shore-keeper.com` for cross-subdomain cookie sharing |
| AUTH_FRONTEND_ORIGINS | http://localhost:5173 | Comma-separated origins allowed by CORS when AUTH_ENABLED |
| AUTH_OAUTH_REDIRECT_URL | http://localhost:9000/api/auth/callback | Backend callback URL (must match Google client config) |
| AUTH_POST_LOGIN_REDIRECT_URL | / | Where the OAuth callback redirects after setting the cookie. Absolute URL for cross-origin deploys. |
| **Remote hardware probe** | | |
| REMOTE_SERVER_ENABLED | False | Enable remote server hardware probe in Dashboard |
| REMOTE_SERVER_NAME | DB Server | Display name for the remote server card |
| REMOTE_SERVER_GLANCES_URL | (empty) | Glances JSON API base URL, e.g. `http://192.168.1.50:61208` |

## Conventions

- Backend: Python 3.10+, FastAPI, async everywhere, singleton services
- Frontend: React 19, TypeScript strict, Radix UI + TailwindCSS 4, Vite
- WebSocket messages are JSON with a `type` field for routing
- Binary WebSocket frames are raw audio (Float32 PCM from frontend, Int16 PCM from TTS)
- All tools use the `@tool` decorator from `langchain_core.tools`
- Async tools use `ainvoke()`, sync tools use `invoke()` (see `agent_service.py:execute_tool`)
- TTS text is sanitized before synthesis: strip tool blocks, code blocks, math expressions, URLs, markdown
- Agent loop is a bounded multi-round tool-calling loop with a typed `AgentState` dict; tools use native OpenAI tool-calling schemas
- Tool retriever always injects always-available tools; others selected by cosine similarity to the user query
- Persona and tool instructions are file-based (`prompts/`), not hardcoded in Python
- gRPC clients live in `app/services/ai_client/`; never import `torch`/`transformers`/`kokoro`/`sentence-transformers` into the backend

## Backlog

- [ ] Client-side screen capture — use `getDisplayMedia` in browser, send image over WebSocket for vision analysis
- [x] Memory backend Phase 1 — Redis short-term + Docker stack
- [x] Memory backend Phase 2 — Profile (Postgres) + Episodic (Qdrant) + read-path integration + debug API + /health probes + frontend banner
- [x] Memory backend Phase 3 — LOCOMO worker + canonicalizer (auto-extract facts from chat history)
- [x] Memory frontend panel (Phase 4) — `/memory` route with Profile tree view, Episodic browser, Audit log + restore
- [ ] Wake word detection — trigger VAD only on a keyword (e.g. "Hey Shore")
- [ ] Tool result streaming — show tool output progressively in the agent log
- [ ] Voice selection UI — let user pick TTS voice from settings panel
- [ ] Multi-language TTS — auto-detect language from LLM response and switch voice
- [x] Thinking mode toggle — frontend switch to enable/disable LLM extended thinking
- [x] Math rendering — KaTeX support for inline/block LaTeX in chat
- [x] Fresh time via always-available `get_system_time` tool — prompt instructs LLM to call it instead of trusting history
- [x] Web search → scrape chaining — companion tools + prompt rule for automatic follow-up
- [x] Vision via primary model — multimodal primary served by llama-server, no hot-swap
- [x] Native tool calling — OpenAI-style tool schemas + streaming tool_call accumulator (replaced regex tool blocks)
- [x] Terminal interaction — PTY sessions + one-shot commands via shore-pty-service (node-pty) + xterm.js UI
- [x] Dashboard service control — Start/Stop buttons for processes, docker containers, internal singletons, and remote services via `back-end/config/services.yaml`
- [x] Cloud sub-agents — escalate to Claude / Gemini / GPT via `ask_claude` / `ask_gemini` / `ask_openai`
- [x] STT/TTS/Embed gRPC microservice — moved all GPU/ML workloads to `shore-ai-service` (+ `shore-ai-supervisor` control plane); backend is orchestrator-only

### Proactive Agent (Event Loop)
- [x] Scheduled tasks — set_reminder (one-shot) + set_scheduled_task (recurring) tools with APScheduler
- [x] Proactive notifications — NotificationService feeds scheduler events through agent pipeline → TTS
- [x] n8n integration — two-way: Shore triggers n8n workflows as tools, n8n pushes notifications to Shore
- [ ] Background monitoring — watch files, processes, or logs and notify on changes
- [ ] Deferred goals — multi-step plans the agent works through over time, persisted to disk
```