# Shore Assistant

A voice-first AI assistant running locally with LLM reasoning, tool execution, vision capabilities, and streaming TTS.

## Working Rules

- Do not make any changes until you have 95% confidence in what you need to build. Ask follow-up questions until you reach that confidence.

## Architecture

```
Browser (React + TypeScript + Vite)
  ├── Silero VAD (in-browser ONNX, 16kHz/512-sample chunks)
  ├── Chat WebSocket client → ws://localhost:9000/ws/chat
  └── TTS PCM audio player (AudioContext)

FastAPI Backend (Python)
  ├── /ws/chat    — Full pipeline: Audio/Text → STT → Agent → LLM → TTS (cookie-auth at upgrade)
  ├── /api/auth/{login,callback,logout,me} — Google OAuth + Redis-backed sessions, gated by AUTH_ENABLED
  ├── /api/dashboard — Aggregated status: services, databases, hardware (psutil + nvidia-smi), workers; rows include `control` when a service appears in services.yaml
  ├── /api/services — GET list + POST {name}/{start,stop} for registered services (admin + CSRF on writes)
  ├── Whisper STT (HuggingFace Transformers, GPU/CPU auto-detect)
  ├── LLM Agent   (llama.cpp llama-server, OpenAI-compatible /v1/chat/completions, LangGraph StateGraph)
  ├── Tool Retriever (sentence-transformers embedding-based selection, all-MiniLM-L6-v2)
  ├── Tools        (system_time, read_file, list_directory, clear_memory, search_web, web_scrape, capture_screen, analyze_screen, set_reminder, set_scheduled_task, cancel_task, list_tasks, run_command + PTY tools, start_background_service + list/stop/logs + dynamic n8n workflow tools)
  ├── Scheduler    (APScheduler — one-shot reminders + recurring tasks, persisted to JSON)
  ├── Notifications (proactive push via ConnectionManager → agent pipeline → TTS; sources: scheduler, n8n webhooks)
  ├── Memory       (Hybrid: Redis short-term + Postgres profile + Qdrant episodic; circuit-broken per layer; LOCOMO worker auto-extracts via Gemini 2.5 Flash on 30s idle; nightly canonicalizer dedupes entity tags)
  ├── TTS          (Kokoro TTS → Int16 PCM streaming, local/offline, multi-language)
  ├── Vision       (mss screen capture → primary multimodal model via /v1/chat/completions)
  └── n8n          (two-way integration: dynamic workflow tools + inbound webhook notifications)

Node PTY microservice (shore-pty-service)
  └── node-pty executor — PTY/process host at ws://127.0.0.1:9100 (sole backend for terminal_service)
```

## Project Structure

```
Shore-Assistant/
├── shore-pty-service/    # Node + TypeScript microservice: node-pty + child_process executor (ws://127.0.0.1:9100)
├── back-end/
│   └── app/
│       ├── main.py                     # FastAPI app factory + router includes
│       ├── core/
│       │   ├── config.py               # Pydantic settings (llama-server, TTS, Vision, Auth)
│       │   ├── runtime_flags.py        # Mutable runtime overrides for STT/TTS/WORKER/CANONICALIZER (toggled by service control)
│       │   ├── auth.py                 # User / Session types + Redis-backed SessionStore + current_user_id ContextVar
│       │   └── allowlist.py            # Parse AUTH_ALLOWED_EMAILS + resolve_role (first email = admin)
│       ├── api/
│       │   ├── deps.py                 # FastAPI Depends: current_user, csrf_check, require_admin
│       │   ├── endpoints/
│       │   │   ├── health.py           # GET / and /health (tri-state: healthy/degraded/unhealthy)
│       │   │   ├── auth.py             # /api/auth/{login,callback,logout,me} — Google OAuth + session lifecycle
│       │   │   ├── memory.py           # /api/memory/* — Profile, Episodic, Audit admin API (admin-only when auth enabled)
│       │   │   ├── dashboard.py        # GET /api/dashboard — services + databases + hardware + workers snapshot; merges service-control state per row
│       │   │   ├── services.py         # /api/services/* — list + admin-only start/stop endpoints, 202 fire-and-forget
│       │   │   ├── chronicles.py       # GET /api/chronicles + /{slug} — serves docs/chronicles/*.md with YAML frontmatter
│       │   │   └── n8n_webhook.py      # POST /api/n8n/webhook, /refresh, GET /status
│       │   └── websockets/
│       │       └── chat_ws.py          # /ws/chat (full pipeline + TTS)
│       ├── schemas/messages.py         # Pydantic WS message models
│       ├── prompts/
│       │   ├── base.txt                # Base persona system prompt template
│       │   ├── kuudere.txt             # Kuudere persona system prompt template
│       │   ├── tools_core.txt          # Always-loaded tool rules (general protocol + always-available tools + run_command)
│       │   ├── tools_terminal.txt      # PTY/session rules (loaded only when terminal tools retrieved)
│       │   ├── tools_background.txt    # Background service rules (loaded only when background tools retrieved)
│       │   ├── tools_n8n.txt           # n8n workflow rules (loaded only when an n8n_ tool is retrieved)
│       │   └── user.txt                # Optional user context appended to persona
│       ├── services/
│       │   ├── service_manager.py      # Registry loader + per-service asyncio lock; dispatches start/stop to controllers
│       │   ├── controllers/             # Service-control backends
│       │   │   ├── base.py              # Controller ABC + ServiceState model
│       │   │   ├── process.py           # ProcessController (subprocess.Popen + PID file w/ create_time verification)
│       │   │   ├── docker.py            # DockerController (`docker compose start/stop/up -d/ps`)
│       │   │   └── internal.py          # InternalController (stt/tts/locomo/canonicalizer toggles + unload)
│       │   ├── stt_service.py          # Whisper via Transformers; gated by runtime_flags.STT_ENABLED, supports unload()
│       │   ├── llm_service.py          # llama-server OpenAI-compatible streaming client (httpx), persona + memory block loader
│       │   ├── agent_service.py        # LangGraph StateGraph agent loop (accepts memory_bundle)
│       │   ├── tts_service.py          # Kokoro TTS; gated by runtime_flags.TTS_ENABLED, supports load()/unload()
│       │   ├── embedding_service.py    # Shared SentenceTransformer singleton (used by tool_retriever + memory.embedder)
│       │   ├── memory/                  # Hybrid memory package
│       │   │   ├── __init__.py          # exposes memory_facade singleton
│       │   │   ├── types.py             # Pydantic contracts for every layer
│       │   │   ├── short_term.py        # Redis sliding window
│       │   │   ├── embedder.py          # Async wrapper over embedding_service
│       │   │   ├── profile.py           # Postgres JSONB single-row snapshot + append-only audit log
│       │   │   ├── episodic.py          # Qdrant async client; deterministic uuid5 point_id for idempotent worker writes
│       │   │   ├── pruning.py           # Prune Profile JSON by oldest top-level key until ≤ MEMORY_PROFILE_MAX_BYTES
│       │   │   └── facade.py            # MemoryFacade — single entry-point; 500ms per-layer circuit breaker
│       │   ├── scheduler_service.py    # APScheduler: one-shot & recurring tasks
│       │   ├── notification_service.py # Scheduler/n8n → agent pipeline → proactive TTS
│       │   ├── connection_manager.py   # Singleton WebSocket send handle for background push
│       │   ├── tool_retriever.py       # Embedding-based tool selection (uses shared embedding_service)
│       │   └── n8n_service.py          # n8n workflow discovery, dynamic tool creation, webhook trigger
│       ├── tools/
│       │   ├── __init__.py             # Tool registry (ALL_TOOLS, TOOL_MAP, register/unregister dynamic tools)
│       │   ├── system_tools.py         # get_system_time, read_file, list_directory, clear_memory
│       │   ├── web_tools.py            # search_web (DuckDuckGo), web_scrape (readability-lxml)
│       │   ├── screen_tools.py         # capture_screen, analyze_screen (primary model or hot-swap)
│       │   └── scheduler_tools.py      # set_reminder, set_scheduled_task, cancel_task, list_tasks
│       └── utils/audio_utils.py        # PCM/float32 conversion
│
└── front-end/
    └── src/
        ├── routers/
        │   └── PublicRoutes.tsx             # React Router route definitions
        ├── layouts/
        │   └── AppLayout/
        │       ├── index.tsx               # Shell layout wrapper
        │       ├── Footer.tsx              # Bottom bar
        │       └── Sidebar.tsx             # Left sidebar
        ├── services/
        │   ├── vad.service.ts              # Silero VAD (ONNX)
        │   ├── chat-websocket.service.ts   # Chat WebSocket (/ws/chat)
        │   ├── memory-api.service.ts       # Memory admin REST client
        │   ├── dashboard.service.ts        # Dashboard snapshot fetcher
        │   └── chronicles.service.ts       # Chronicles list + single-entry fetcher
        ├── hooks/
        │   ├── useAssistant.ts             # Full assistant hook (VAD + LLM + TTS)
        │   └── useDashboardPoll.ts         # 5s poll for /api/dashboard, pauses on tab hidden
        ├── components/
        │   └── AgentActionLog.tsx           # Real-time agent action display
        ├── pages/
        │   ├── Dashboard/index.tsx         # Service / DB / hardware / worker status page (default route)
        │   ├── Memory/                     # Profile + Episodic + Audit panel (Phase 4)
        │   ├── Chronicles/index.tsx        # Versioned changelog, rendered from docs/chronicles/*.md
        │   └── Chat/
        │       ├── index.tsx               # Assistant chat page
        │       └── SettingsPanel.tsx        # Right sidebar settings
        ├── utils/
        │   ├── audio.util.ts               # Float32 → WAV conversion
        │   └── tts-player.util.ts          # Browser PCM audio queue player
        ├── models/stt.model.ts             # TypeScript config interfaces
        └── constants/stt.constant.ts       # WS URLs, languages, models

## Commands

### Backend
```bash
cd back-end

# First time: install PyTorch for RTX 5060 Ti (CUDA 12.9)
pip install torch==2.8.0 torchvision==0.23.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cu129

# Install remaining dependencies
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

# espeak-ng (required for Kokoro TTS English phonemes)
winget install espeak-ng.espeak-ng
```

docker compose -f docker-compose.n8n.yml up -d

## Key Technical Constraints

- **16GB VRAM budget**: Whisper (~1.5GB) + primary LLM. Vision runs through the primary multimodal model via llama-server's `/v1/chat/completions` (no hot-swap). The primary model must be multimodal with an mmproj loaded.
- **Audio pipeline**: 16kHz sample rate, Float32 format, 512-sample VAD chunks (Silero requirement).
- **Two WebSocket endpoints**: `/ws/audio` (binary-only STT) and `/ws/chat` (mixed JSON + binary for full pipeline). Don't merge them.
- **Tool call format**: LLM outputs ` ```tool\n{"tool": "name", "args": {...}}\n``` ` blocks. Parsed by regex in `agent_service.py`. Agent loop is a LangGraph `StateGraph`.
- **Tool retrieval**: Only relevant tools are injected per request via embedding cosine similarity (`tool_retriever.py`). Always-available tools: `get_system_time`, `clear_memory`, `set_reminder`, `set_scheduled_task`, `list_tasks`, `cancel_task`. Companion tools: `web_search` always includes `web_scrape`. Dynamic n8n tools are auto-registered at startup.
- **Fresh time via tool**: `get_system_time` is in `ALWAYS_AVAILABLE` (always injected as a tool); `tools.txt` instructs the LLM to call it for any time-related question instead of trusting conversation history.
- **Thinking mode**: Frontend toggle sends `thinking` config via WebSocket → passed to llama-server as `reasoning_effort: "medium"`. Reasoning tokens stream into collapsible UI block.
- **Persona system**: System prompt = `prompts/{PERSONA}.txt` + `tools_core.txt` + conditional section files (`tools_terminal.txt`, `tools_background.txt`, `tools_n8n.txt`) + optional `user.txt`. Section files are appended only when their trigger tools appear in the retrieved set, keeping notification/simple prompts small. Configured via `PERSONA` env var (`base` or `kuudere`).
- **Scheduler**: APScheduler manages one-shot reminders and recurring tasks. Tasks persist to `data/scheduled_tasks.json`. Missed tasks fire immediately on restart.
- **Proactive notifications**: When a task fires, `NotificationService` feeds a prompt to the agent pipeline so Shore responds in-character with TTS. Queued to disk if no client is connected, drained on reconnect.
- **TTS pipeline**: LLM tokens accumulate → sentence boundary detected → sentence queued → Kokoro synthesizes on CPU → Int16 PCM binary frames sent over WebSocket. Single `tts_start`/`tts_end` per response.
- **TTS cancellation**: Frontend stops TTS player immediately when user sends a new message (voice or keyboard).
- **TTS sanitization**: Strips code blocks, math expressions (`$...$`, `$$...$$`), JSON, URLs, markdown before synthesis.
- **Notification tools disabled**: When notification prompts (scheduler/n8n) run through the agent, tools are not injected (`no_tools=True`) to prevent the LLM from re-triggering reminders in a loop.
- **Math rendering**: Chat uses remark-math + rehype-katex for inline (`$...$`) and block (`$$...$$`) LaTeX formulas.
- **analyze_screen captures server display**, not the client's browser screen. For client-side screen capture, `getDisplayMedia` would be needed.
- **n8n integration**: Two-way — Shore discovers active n8n webhook workflows via REST API at startup and registers them as dynamic tools; n8n can push notifications to Shore via `POST /api/n8n/webhook`. Opt-in via `N8N_ENABLED=True`.
- **Conversation memory**: Three layers behind `MemoryFacade.assemble_context()`. Short-term (Redis LIST `shore:short_term:messages`, 15 turns, AOF). Profile (Postgres JSONB single-row + append-only audit log). Episodic (Qdrant `shore_episodic` collection with payload-indexed `entity_tags`/`created_at`/`valence`). Per-layer 500 ms circuit breaker; chat degrades to short-term only if Postgres / Qdrant are down. Phase 3 will add a LOCOMO worker that writes to Profile + Episodic from chat history.
- **Memory injection into system prompt**: `chat_ws` calls `memory_facade.assemble_context(user_text)` per turn and threads the `ContextBundle` into `agent_service.run`, which passes it to `build_system_prompt`. The system prompt then appends `[Profile]` (compact JSON, capped at `MEMORY_PROFILE_MAX_BYTES`, pruned by per-key `updated_at`) and `[Relevant memories]` (top-K bullet list by cosine similarity — fact + tags only, no emotion in P2). Notifications (`no_tools=True`) drop the bundle to keep proactive nudges free of identity content.
- **Memory admin API**: `/api/memory/*` endpoints (always mounted). Profile: `GET /profile`, `POST /profile/change`, `GET /profile/history?key=...`, `GET /profile/audit?limit=`, `POST /profile/restore {audit_id, reason?}`. Episodic: `GET /episodic/recent?limit=`, `GET /episodic/search?q=&top_k=`, `POST /episodic/upsert`, `DELETE /episodic/{point_id}`. Backs the frontend Memory page at `/memory`. Admin-only (CSRF on writes) when `AUTH_ENABLED=True`; open when disabled.
- **Auth (Google OAuth + Redis sessions)**: Master switch `AUTH_ENABLED` (default False — legacy synthetic-admin mode preserves pre-auth behavior). When enabled: `/api/auth/login` → Google consent → `/api/auth/callback` checks email against `AUTH_ALLOWED_EMAILS` (comma-separated, first email = admin role), creates a session in Redis under `shore:session:<sid>` with sliding TTL, sets an HttpOnly cookie. `/api/auth/me` returns `{email, role, csrf}`; the frontend stores the CSRF token in memory and sends it as `X-CSRF-Token` on writes. `/api/auth/logout` deletes the Redis key + clears the cookie. WS upgrades validate the cookie and close with code 4401 if unauthenticated. **Short-term memory becomes per-user** (`shore:short_term:<user_id>:messages`); Profile and Episodic stay global. **LOCOMO worker only extracts from admin turns** — non-admin allowlisted users can chat without their words reaching Luna's shared identity profile. Public-no-login routes when auth is on: `/health`, `/api/chronicles`.
- **LOCOMO worker (Phase 3)**: Gemini 2.5 Flash with `response_schema=WorkerOutput` runs after 30 s of chat idle. Debounced via `WorkerService.on_turn_completed()` (cancel-on-new-turn). Safety valve fires immediately at `WORKER_MAX_UNPROCESSED_MESSAGES`. Dual-locked via `asyncio.Lock` + Redis `SETNX shore:worker:lock` (TTL 60 s). Disabled by `WORKER_ENABLED=False`. Notifications skip the trigger.
- **Canonicalizer**: Internal APScheduler job (registered via `scheduler_service.add_system_job`, invisible to `list_tasks`). Cron `0 4 * * *` by default. Greedy single-pass clustering on entity tags at cosine ≥0.85; rewrites Qdrant point payloads in place.
- **Service control (Dashboard buttons)**: `back-end/config/services.yaml` (gitignored; example at `services.example.yaml`) registers controllable services across three kinds. `process` → `subprocess.Popen` with PID file under `data/pids/<name>.pid` (verified by `create_time` to defend against PID reuse); SIGTERM → grace → SIGKILL. `docker` → `docker compose -f <file> {up -d|start|stop|ps} <service>`. `internal` → `runtime_flags` toggle for STT/TTS/WORKER/CANONICALIZER, plus model `unload()` for stt/tts. ServiceManager uses a `transitioning` set as a synchronization gate (atomic without `await`) so two concurrent requests on the same name can never both pass. Endpoints: `GET /api/services` (any logged-in user), `POST /api/services/{name}/{start,stop}` returns 202 with admin + CSRF guards. `/api/dashboard` rows include a `control` field merged by `correlates_with` (services/databases) or `display_name` (workers). Frontend `useDashboardPoll` accelerates to 1 s while any service is transitioning, returning to 5 s once stable; Stop shows a Radix confirm dialog, Start does not.

## Configuration

All backend config via environment variables or `.env` file in `back-end/`:

| Variable | Default | Description |
|----------|---------|-------------|
| LLAMA_BASE_URL | http://localhost:8080 | llama-server URL |
| LLAMA_MODEL | (empty) | Optional label sent in the `model` field (llama-server typically ignores) |
| LLAMA_TIMEOUT | 120 | Request timeout (seconds) |
| PERSONA | kuudere | Persona template to load (`base` or `kuudere`) |
| MEMORY_MAX_TURNS | 15 | Max conversation turns retained per session |
| REDIS_URL | redis://localhost:6379/0 | Redis URL for short-term memory |
| REDIS_SHORT_TERM_KEY | shore:short_term | Base prefix; per-user window stored at `{prefix}:{user_id}:messages` |
| AUTH_ENABLED | False | Master switch. When False, app runs as a synthetic admin (pre-auth behavior). |
| AUTH_ALLOWED_EMAILS | (empty) | Comma-separated Google emails. First entry gets `admin` role; others `user`. |
| AUTH_GOOGLE_CLIENT_ID | (empty) | Google OAuth client id (from Google Cloud Console) |
| AUTH_GOOGLE_CLIENT_SECRET | (empty) | Google OAuth client secret |
| AUTH_SESSION_SECRET | (empty) | Reserved for future cookie signing (32+ bytes recommended) |
| AUTH_SESSION_TTL_SECONDS | 604800 | Session sliding TTL (7 days) |
| AUTH_SESSION_KEY_PREFIX | shore:session: | Redis key prefix for sessions |
| AUTH_OAUTH_STATE_KEY_PREFIX | shore:oauth_state: | Redis key prefix for one-shot OAuth state tokens |
| AUTH_OAUTH_STATE_TTL_SECONDS | 300 | TTL on OAuth state token (5 min) |
| AUTH_COOKIE_NAME | shore_session | Session cookie name |
| AUTH_COOKIE_SECURE | True | Set False for local http dev |
| AUTH_COOKIE_SAMESITE | lax | SameSite attribute on the session cookie |
| AUTH_COOKIE_DOMAIN | (empty) | Set to `.shore-keeper.com` for cross-subdomain (bearer↔api) cookie sharing |
| AUTH_FRONTEND_ORIGINS | http://localhost:5173 | Comma-separated origins allowed by CORS when AUTH_ENABLED |
| AUTH_OAUTH_REDIRECT_URL | http://localhost:9000/api/auth/callback | Backend callback URL (must match Google client config) |
| AUTH_POST_LOGIN_REDIRECT_URL | / | Where the OAuth callback redirects after setting the cookie. Absolute URL for cross-origin deploys. |
| POSTGRES_URL | postgresql://shore:changeme@localhost:5432/shore_memory | Postgres DSN for Profile (Phase 2) |
| POSTGRES_POOL_MIN | 1 | asyncpg pool min size |
| POSTGRES_POOL_MAX | 5 | asyncpg pool max size |
| QDRANT_URL | http://localhost:6333 | Qdrant URL for Episodic (Phase 2) |
| QDRANT_COLLECTION | shore_episodic | Qdrant collection name for episodic facts |
| MEMORY_EPISODIC_TOP_K | 5 | Max episodic facts injected into system prompt per turn |
| MEMORY_EPISODIC_MIN_SCORE | 0.3 | Minimum cosine score for episodic retrieval |
| MEMORY_PROFILE_MAX_BYTES | 2048 | Hard cap for Profile JSON injected into system prompt (compact bytes) |
| SCHEDULER_TASKS_FILE | data/scheduled_tasks.json | Persisted scheduler task list |
| SCHEDULER_PENDING_FILE | data/pending_notifications.json | Queued notifications for offline client |
| TOOL_RETRIEVER_MODEL | all-MiniLM-L6-v2 | Sentence-transformers model for tool embedding |
| TOOL_RETRIEVER_TOP_K | 3 | Max tools retrieved per query |
| TOOL_RETRIEVER_THRESHOLD | 0.3 | Minimum cosine similarity to include a tool |
| N8N_ENABLED | False | Enable n8n integration (workflow tools + inbound webhook) |
| N8N_BASE_URL | http://localhost:5678 | n8n instance URL |
| N8N_API_KEY | (empty) | n8n REST API key (Settings → API in n8n UI) |
| N8N_WEBHOOK_SECRET | (empty) | Shared secret for n8n → Shore webhook auth |
| N8N_REFRESH_INTERVAL_MINUTES | 0 | Auto-refresh workflow discovery (0 = disabled) |
| NODE_PTY_WS_URL | wss://terminal.shore-keeper.com | URL of shore-pty-service WS endpoint (reverse-proxied TLS) |
| NODE_PTY_AUTH_TOKEN | (empty) | Optional Bearer token required by shore-pty-service |
| NODE_PTY_RECONNECT_BASE_MS | 1000 | Initial reconnect backoff (milliseconds) |
| NODE_PTY_RECONNECT_MAX_MS | 30000 | Max reconnect backoff (milliseconds) |
| NODE_PTY_PING_INTERVAL_SECONDS | 30 | Heartbeat ping interval |
| NODE_PTY_PING_TIMEOUT_SECONDS | 5 | Pong deadline before treating connection as disconnected |
| WORKER_ENABLED | True | Enable LOCOMO worker (Phase 3 auto-extraction) |
| WORKER_IDLE_DELAY_SECONDS | 30.0 | Idle gap after a turn before the worker fires |
| WORKER_MAX_UNPROCESSED_MESSAGES | 20 | Safety valve: fire immediately at this many unprocessed turns |
| WORKER_LOCAL_LLM_URL | http://localhost:8080/v1 | OpenAI-compatible local API base URL for LOCOMO extraction |
| WORKER_LOCAL_TIMEOUT | 60.0 | Per-attempt local API timeout (seconds) |
| WORKER_LOCK_KEY | shore:worker:lock | Redis SETNX key for cross-process worker mutex |
| WORKER_LOCK_TTL_SECONDS | 60 | TTL on the Redis lock (auto-release on crash) |
| WORKER_LAST_TS_KEY | shore:worker:last_extracted_ts | Redis key tracking the newest processed turn timestamp |
| CANONICALIZER_ENABLED | True | Enable nightly entity-tag dedup job |
| CANONICALIZER_CRON | 0 4 * * * | When to run the canonicalizer (local time) |
| CANONICALIZER_SIMILARITY_THRESHOLD | 0.85 | Cosine threshold for merging entity tags |
| REMOTE_SERVER_ENABLED | False | Enable remote server hardware probe in Dashboard |
| REMOTE_SERVER_NAME | DB Server | Display name for the remote server card |
| REMOTE_SERVER_GLANCES_URL | (empty) | Glances JSON API base URL, e.g. `http://192.168.1.50:61208` |

## Conventions

- Backend: Python 3.10+, FastAPI, async everywhere, singleton services
- Frontend: React 19, TypeScript strict, Radix UI + TailwindCSS 4, Vite
- WebSocket messages are JSON with `type` field for routing
- Binary WebSocket frames are raw audio (Float32 PCM from frontend, Int16 PCM from TTS)
- All tools use `@tool` decorator from `langchain_core.tools`
- Async tools use `ainvoke()`, sync tools use `invoke()` (see `agent_service.py:execute_tool`)
- TTS text is sanitized before synthesis: strip tool blocks, code blocks, math expressions, URLs, markdown
- Agent is a LangGraph `StateGraph` with typed `AgentState` (messages, intent, tool_name, tool_args, tool_result, llm_response, actions_log)
- Tool retriever always injects core tools; others selected by cosine similarity to user query
- Persona and tool instructions are file-based (`prompts/`), not hardcoded in Python

## Backlog

- [ ] Client-side screen capture — use `getDisplayMedia` in browser, send image over WebSocket for vision analysis
- [x] Memory backend Phase 1 — Redis short-term + Docker stack
- [x] Memory backend Phase 2 — Profile (Postgres) + Episodic (Qdrant) + read-path integration + debug API + /health probes + frontend banner
- [x] Memory backend Phase 3 — LOCOMO worker (Gemini 2.5 Flash) + canonicalizer (auto-extract facts from chat history)
- [x] Memory frontend panel (Phase 4) — `/memory` route with Profile tree view, Episodic browser, Audit log + restore
- [ ] Wake word detection — trigger VAD only on a keyword (e.g. "Hey Shore")
- [ ] Tool result streaming — show tool output progressively in the agent log
- [ ] Voice selection UI — let user pick Kokoro voice from settings panel
- [ ] Multi-language TTS — auto-detect language from LLM response and switch Kokoro voice
- [x] Thinking mode toggle — frontend switch to enable/disable LLM extended thinking
- [x] Math rendering — KaTeX support for inline/block LaTeX in chat
- [x] Fresh time via always-available `get_system_time` tool — prompt instructs LLM to call it instead of trusting history
- [x] Web search → scrape chaining — companion tools + prompt rule for automatic follow-up
- [x] Vision via primary model — multimodal primary served by llama-server, no hot-swap
- [x] Terminal interaction — PTY sessions + one-shot commands via shore-pty-service (node-pty) + xterm.js UI
- [x] Dashboard service control — Start/Stop buttons for processes, docker containers, and internal singletons via `back-end/config/services.yaml`

### Proactive Agent (Event Loop)
- [x] Scheduled tasks — set_reminder (one-shot) + set_scheduled_task (recurring) tools with APScheduler
- [x] Proactive notifications — NotificationService feeds scheduler events through agent pipeline → TTS
- [x] n8n integration — two-way: Shore triggers n8n workflows as tools, n8n pushes notifications to Shore
- [ ] Background monitoring — watch files, processes, or logs and notify on changes
- [ ] Deferred goals — multi-step plans the agent works through over time, persisted to disk
