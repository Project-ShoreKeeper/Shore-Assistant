# Shore Assistant

A voice-first AI assistant running locally with LLM reasoning, tool execution, vision capabilities, and streaming TTS.

## Architecture

```
Browser (React + TypeScript + Vite)
  ├── Silero VAD (in-browser ONNX, 16kHz/512-sample chunks)
  ├── Chat WebSocket client → ws://localhost:8000/ws/chat
  └── TTS PCM audio player (AudioContext)

FastAPI Backend (Python)
  ├── /ws/audio   — STT-only endpoint (legacy, used by VAD Test page)
  ├── /ws/chat    — Full pipeline: Audio/Text → STT → Agent → LLM → TTS
  ├── Whisper STT (HuggingFace Transformers, GPU/CPU auto-detect)
  ├── LLM Agent   (Ollama Qwen2.5-14B via httpx streaming)
  ├── Tools        (system_time, read_file, list_directory, search_web, web_scrape, capture_screen, analyze_screen)
  ├── TTS          (Kokoro TTS → Int16 PCM streaming, local/offline)
  └── Vision       (mss screen capture → Ollama qwen2.5vl:7b hot-swap)
```

## Project Structure

```
Shore-Assistant/
├── back-end/
│   └── app/
│       ├── main.py                     # FastAPI app factory + router includes
│       ├── core/config.py              # Pydantic settings (Ollama, TTS, Vision)
│       ├── api/
│       │   ├── endpoints/health.py     # GET / and /health
│       │   └── websockets/
│       │       ├── stt_ws.py           # /ws/audio (STT only)
│       │       └── chat_ws.py          # /ws/chat (full pipeline + TTS)
│       ├── schemas/messages.py         # Pydantic WS message models
│       ├── services/
│       │   ├── stt_service.py          # Whisper via Transformers
│       │   ├── llm_service.py          # Ollama streaming client (httpx)
│       │   ├── agent_service.py        # Agent loop with tool call parsing
│       │   ├── tts_service.py          # Kokoro TTS, CPU inference, 24kHz PCM
│       │   ├── vision_service.py       # Screen capture (mss) + vision inference
│       │   └── vram_manager.py         # VRAM hot-swap orchestration
│       ├── tools/
│       │   ├── __init__.py             # Tool registry (ALL_TOOLS, TOOL_MAP)
│       │   ├── system_tools.py         # get_system_time, read_file, list_directory
│       │   ├── web_tools.py            # search_web (DuckDuckGo), web_scrape (readability-lxml)
│       │   └── screen_tools.py         # capture_screen, analyze_screen (vision hot-swap)
│       └── utils/audio_utils.py        # PCM/float32 conversion
│
└── front-end/
    └── src/
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
python -m uvicorn app.main:app --reload --port 8000
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
# Ollama (required for LLM + Vision)
ollama pull qwen2.5:14b
ollama pull qwen2.5vl:7b
ollama serve

# espeak-ng (required for Kokoro TTS English phonemes)
winget install espeak-ng.espeak-ng
```

## Key Technical Constraints

- **16GB VRAM budget**: Whisper (~1.5GB) + Qwen2.5-14B (~9-10GB). Vision model hot-swaps by unloading LLM first.
- **Audio pipeline**: 16kHz sample rate, Float32 format, 512-sample VAD chunks (Silero requirement).
- **Two WebSocket endpoints**: `/ws/audio` (binary-only STT) and `/ws/chat` (mixed JSON + binary for full pipeline). Don't merge them.
- **Tool call format**: LLM outputs ` ```tool\n{"tool": "name", "args": {...}}\n``` ` blocks. Parsed by regex in `agent_service.py`.
- **TTS pipeline**: LLM tokens accumulate → sentence boundary detected → sentence queued → Kokoro synthesizes on CPU → Int16 PCM binary frames sent over WebSocket. Single `tts_start`/`tts_end` per response.
- **TTS cancellation**: Frontend stops TTS player immediately when user sends a new message (voice or keyboard).
- **analyze_screen captures server display**, not the client's browser screen. For client-side screen capture, `getDisplayMedia` would be needed.

## Configuration

All backend config via environment variables or `.env` file in `back-end/`:

| Variable | Default | Description |
|----------|---------|-------------|
| OLLAMA_BASE_URL | http://localhost:11434 | Ollama API URL |
| OLLAMA_MODEL | qwen2.5:14b | Primary LLM model |
| OLLAMA_TIMEOUT | 120 | Request timeout (seconds) |
| VISION_MODEL | qwen2.5vl:7b | Vision model for screen analysis |

## Conventions

- Backend: Python 3.10+, FastAPI, async everywhere, singleton services
- Frontend: React 19, TypeScript strict, Radix UI + TailwindCSS 4, Vite
- WebSocket messages are JSON with `type` field for routing
- Binary WebSocket frames are raw audio (Float32 PCM from frontend, Int16 PCM from TTS)
- All tools use `@tool` decorator from `langchain_core.tools`
- Async tools use `ainvoke()`, sync tools use `invoke()` (see `agent_service.py:execute_tool`)
- TTS text is sanitized before synthesis: strip tool blocks, code blocks, URLs, markdown

## Backlog

- [ ] Client-side screen capture — use `getDisplayMedia` in browser, send image over WebSocket for vision analysis
- [x] Conversation memory — persist history to disk so context survives server restarts
- [ ] Wake word detection — trigger VAD only on a keyword (e.g. "Hey Shore")
- [ ] Tool result streaming — show tool output progressively in the agent log
- [ ] Voice selection UI — let user pick Kokoro voice from settings panel
- [ ] Multi-language TTS — auto-detect language from LLM response and switch Kokoro voice

### Proactive Agent (Event Loop)
- [ ] Scheduled tasks — "remind me in 10 minutes", "check X every hour" (background timer + task queue)
- [ ] Background monitoring — watch files, processes, or logs and notify on changes
- [ ] Proactive notifications — push alerts to frontend over WebSocket without user prompt (e.g. "build finished")
- [ ] Deferred goals — multi-step plans the agent works through over time, persisted to disk
