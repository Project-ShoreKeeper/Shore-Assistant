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
  ├── /ws/audio   — STT-only endpoint (legacy, used by VAD Test page)
  ├── /ws/chat    — Full pipeline: Audio/Text → STT → Agent → LLM → TTS
  ├── Whisper STT (HuggingFace Transformers, GPU/CPU auto-detect)
  ├── LLM Agent   (llama.cpp llama-server, OpenAI-compatible /v1/chat/completions, LangGraph StateGraph)
  ├── Tool Retriever (sentence-transformers embedding-based selection, all-MiniLM-L6-v2)
  ├── Tools        (system_time, read_file, list_directory, clear_memory, search_web, web_scrape, capture_screen, analyze_screen, set_reminder, set_scheduled_task, cancel_task, list_tasks + dynamic n8n workflow tools)
  ├── Scheduler    (APScheduler — one-shot reminders + recurring tasks, persisted to JSON)
  ├── Notifications (proactive push via ConnectionManager → agent pipeline → TTS; sources: scheduler, n8n webhooks)
  ├── Memory       (per-session JSON history, survives restarts, max 20 turns)
  ├── TTS          (Kokoro TTS → Int16 PCM streaming, local/offline, multi-language)
  ├── Vision       (mss screen capture → primary multimodal model via /v1/chat/completions)
  └── n8n          (two-way integration: dynamic workflow tools + inbound webhook notifications)

Node PTY microservice (shore-pty-service)
  └── node-pty executor — PTY/process host at ws://127.0.0.1:9100 (used by terminal_service when TERMINAL_BACKEND=node)
```

## Project Structure

```
Shore-Assistant/
├── shore-pty-service/    # Node + TypeScript microservice: node-pty + child_process executor (ws://127.0.0.1:9100)
├── back-end/
│   └── app/
│       ├── main.py                     # FastAPI app factory + router includes
│       ├── core/config.py              # Pydantic settings (llama-server, TTS, Vision)
│       ├── api/
│       │   ├── endpoints/
│       │   │   ├── health.py           # GET / and /health
│       │   │   └── n8n_webhook.py      # POST /api/n8n/webhook, /refresh, GET /status
│       │   └── websockets/
│       │       ├── stt_ws.py           # /ws/audio (STT only)
│       │       └── chat_ws.py          # /ws/chat (full pipeline + TTS)
│       ├── schemas/messages.py         # Pydantic WS message models
│       ├── prompts/
│       │   ├── base.txt                # Base persona system prompt template
│       │   ├── kuudere.txt             # Kuudere persona system prompt template
│       │   ├── tools.txt               # Tool usage instructions appended to persona
│       │   └── user.txt                # Optional user context appended to persona
│       ├── services/
│       │   ├── stt_service.py          # Whisper via Transformers
│       │   ├── llm_service.py          # llama-server OpenAI-compatible streaming client (httpx), persona loader
│       │   ├── agent_service.py        # LangGraph StateGraph agent loop
│       │   ├── tts_service.py          # Kokoro TTS, CPU inference, 24kHz PCM, en/ja/zh voices
│       │   ├── memory_service.py       # Per-session JSON conversation history
│       │   ├── scheduler_service.py    # APScheduler: one-shot & recurring tasks
│       │   ├── notification_service.py # Scheduler/n8n → agent pipeline → proactive TTS
│       │   ├── connection_manager.py   # Singleton WebSocket send handle for background push
│       │   ├── tool_retriever.py       # Embedding-based tool selection (sentence-transformers)
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
        │       ├── Header.tsx              # Top navigation bar
        │       ├── Footer.tsx              # Bottom bar
        │       └── Sidebar.tsx             # Left sidebar
        ├── services/
        │   ├── vad.service.ts              # Silero VAD (ONNX)
        │   ├── websocket.service.ts        # STT WebSocket (/ws/audio)
        │   └── chat-websocket.service.ts   # Chat WebSocket (/ws/chat)
        ├── hooks/
        │   ├── useSTT.ts                   # STT-only hook (VAD Test page)
        │   ├── useVADAudio.ts              # VAD-only hook
        │   └── useAssistant.ts             # Full assistant hook (VAD + LLM + TTS)
        ├── components/
        │   └── AgentActionLog.tsx           # Real-time agent action display
        ├── pages/
        │   ├── Main/index.tsx              # VAD Test page
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
- **Auto-injected time**: Current timestamp is prepended to the system prompt every request so the LLM always has fresh time.
- **Thinking mode**: Frontend toggle sends `thinking` config via WebSocket → passed to llama-server as `reasoning_effort: "medium"`. Reasoning tokens stream into collapsible UI block.
- **Persona system**: System prompt loaded from `prompts/{PERSONA}.txt`, with `tools.txt` and optional `user.txt` appended. Configured via `PERSONA` env var (`base` or `kuudere`).
- **Scheduler**: APScheduler manages one-shot reminders and recurring tasks. Tasks persist to `data/scheduled_tasks.json`. Missed tasks fire immediately on restart.
- **Proactive notifications**: When a task fires, `NotificationService` feeds a prompt to the agent pipeline so Shore responds in-character with TTS. Queued to disk if no client is connected, drained on reconnect.
- **TTS pipeline**: LLM tokens accumulate → sentence boundary detected → sentence queued → Kokoro synthesizes on CPU → Int16 PCM binary frames sent over WebSocket. Single `tts_start`/`tts_end` per response.
- **TTS cancellation**: Frontend stops TTS player immediately when user sends a new message (voice or keyboard).
- **TTS sanitization**: Strips code blocks, math expressions (`$...$`, `$$...$$`), JSON, URLs, markdown before synthesis.
- **Notification tools disabled**: When notification prompts (scheduler/n8n) run through the agent, tools are not injected (`no_tools=True`) to prevent the LLM from re-triggering reminders in a loop.
- **Math rendering**: Chat uses remark-math + rehype-katex for inline (`$...$`) and block (`$$...$$`) LaTeX formulas.
- **analyze_screen captures server display**, not the client's browser screen. For client-side screen capture, `getDisplayMedia` would be needed.
- **n8n integration**: Two-way — Shore discovers active n8n webhook workflows via REST API at startup and registers them as dynamic tools; n8n can push notifications to Shore via `POST /api/n8n/webhook`. Opt-in via `N8N_ENABLED=True`.

## Configuration

All backend config via environment variables or `.env` file in `back-end/`:

| Variable | Default | Description |
|----------|---------|-------------|
| LLAMA_BASE_URL | http://localhost:8080 | llama-server URL |
| LLAMA_MODEL | (empty) | Optional label sent in the `model` field (llama-server typically ignores) |
| LLAMA_TIMEOUT | 120 | Request timeout (seconds) |
| PERSONA | kuudere | Persona template to load (`base` or `kuudere`) |
| MEMORY_DIR | data/memory | Directory for per-session conversation JSON files |
| MEMORY_MAX_TURNS | 20 | Max conversation turns retained per session |
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
| TERMINAL_BACKEND | node | `node` or `pywinpty` — which PTY executor backend to use |
| NODE_PTY_WS_URL | ws://127.0.0.1:9100 | URL of shore-pty-service WS endpoint |
| NODE_PTY_AUTH_TOKEN | (empty) | Optional Bearer token required by shore-pty-service |
| NODE_PTY_RECONNECT_BASE_MS | 1000 | Initial reconnect backoff (milliseconds) |
| NODE_PTY_RECONNECT_MAX_MS | 30000 | Max reconnect backoff (milliseconds) |
| NODE_PTY_PING_INTERVAL_SECONDS | 30 | Heartbeat ping interval |
| NODE_PTY_PING_TIMEOUT_SECONDS | 5 | Pong deadline before treating connection as disconnected |

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
- [x] Conversation memory — persist history to disk so context survives server restarts
- [ ] Wake word detection — trigger VAD only on a keyword (e.g. "Hey Shore")
- [ ] Tool result streaming — show tool output progressively in the agent log
- [ ] Voice selection UI — let user pick Kokoro voice from settings panel
- [ ] Multi-language TTS — auto-detect language from LLM response and switch Kokoro voice
- [x] Thinking mode toggle — frontend switch to enable/disable LLM extended thinking
- [x] Math rendering — KaTeX support for inline/block LaTeX in chat
- [x] Auto-inject time — current timestamp in system prompt prevents stale time answers
- [x] Web search → scrape chaining — companion tools + prompt rule for automatic follow-up
- [x] Vision via primary model — multimodal primary served by llama-server, no hot-swap
- [x] Terminal interaction — PTY sessions + one-shot commands via shore-pty-service (node-pty) + xterm.js UI

### Proactive Agent (Event Loop)
- [x] Scheduled tasks — set_reminder (one-shot) + set_scheduled_task (recurring) tools with APScheduler
- [x] Proactive notifications — NotificationService feeds scheduler events through agent pipeline → TTS
- [x] n8n integration — two-way: Shore triggers n8n workflows as tools, n8n pushes notifications to Shore
- [ ] Background monitoring — watch files, processes, or logs and notify on changes
- [ ] Deferred goals — multi-step plans the agent works through over time, persisted to disk
