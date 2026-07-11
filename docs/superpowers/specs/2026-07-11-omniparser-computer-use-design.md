# OmniParser v2 Computer-Use Mode — Design

**Date:** 2026-07-11
**Status:** Draft — pending user review

## Goal

Let Shore operate the backend host's desktop. The user states a goal by voice or
chat ("open Notepad and type hello"); Shore captures the screen, **OmniParser v2**
(running in `shore-ai-service`) grounds the screenshot into numbered interactable
elements, Shore's own local vision LLM decides the next action, and the backend
executes real mouse/keyboard input. The loop repeats until the goal is done,
fails, hits a step budget, or the user stops it.

This replaces a dedicated CUA model with **OmniParser for perception + Shore for
policy** — the standard Set-of-Mark (SoM) flow from the OmniParser paper, with
llama-server as the decision model instead of GPT-4V.

## Decisions (from brainstorming)

| Question | Decision |
|---|---|
| Where does OmniParser run? | New `ScreenParse` gRPC servicer inside `shore-ai-service`, next to STT/TTS/Embed |
| Agent surface | Dedicated computer-use **session mode** (like Copilot), not free-floating chat tools |
| Session entry | Chat/voice via a `computer_use(goal)` tool *(defaulted — user AFK; recommended option)* |
| Decision input | SoM-annotated image + text element list per step *(defaulted — user AFK; recommended option)* |
| Safety model | **Auto-execute** all actions; JSONL audit log of every action |
| Definition of done | Unit tests (existing fake-based style) + live E2E task on the real stack |
| Mouse contention | `DesktopBackend` abstraction from day one. v1 = `LocalDesktopBackend` (host desktop — Shore borrows the real cursor during a session). Phase 2 = `shore-desktop-agent` in a second RDP session so Shore works in parallel without touching the user's mouse. Windows allows one cursor/input queue/foreground per desktop, so same-desktop parallelism is impossible — capture and input must always target the same desktop, hence one interface owning both. |

## Architecture

```
User (voice/chat): "open Notepad and type hello"
  └─ agent loop retrieves computer_use tool → starts session (background task)

ComputerUseService loop (backend, one session at a time, max N steps):
  1. DesktopBackend.capture() → native-res PNG bytes
  2. gRPC ScreenParse.Parse → elements[] + SoM-annotated JPEG
  3. decision call → llama-server /v1/chat/completions
       (SoM image + goal + action history + element list,
        response_format=json_schema(ComputerUseAction))
  4. validate + execute action via DesktopBackend → audit log line
  5. push computer_use_step to frontend; settle delay; repeat
  ── until action=done | action=fail | step budget | stop | WS disconnect

On done/fail: summary fed through the persona pipeline (NotificationService
style, no_tools=True) → Shore announces the outcome in-character with TTS.
```

## Components

### 1. shore-ai-service: `ScreenParse` servicer

**Proto** — `proto/shore/ai/v1/screenparse.proto`:

```proto
service ScreenParse {
  rpc Parse(ParseRequest) returns (ParseResponse);
}
message ParseRequest {
  bytes image = 1;          // encoded PNG or JPEG
}
message Element {
  uint32 id           = 1;  // SoM index, matches the number drawn on the image
  string type         = 2;  // "text" | "icon"
  string content      = 3;  // OCR text or Florence-2 caption
  bool   interactable = 4;
  float  x1 = 5; float y1 = 6; float x2 = 7; float y2 = 8;  // normalized 0..1
}
message ParseResponse {
  repeated Element elements      = 1;
  bytes            som_image_jpeg = 2;  // annotated Set-of-Mark image
  uint32           width  = 3;          // parsed image dims (px)
  uint32           height = 4;
  float            latency_ms = 5;
}
```

**Handler** — `src/shore_ai/handlers/screenparse.py`:
- Wraps the vendored OmniParser v2 stack: YOLO `icon_detect` + Florence-2
  `icon_caption` + OCR (repo default), i.e. the same path as
  `util/omniparser.py` in microsoft/OmniParser.
- Inference runs via `run_in_executor` (Embed pattern); heavy load happens in a
  background `start_load()` (STT pattern) so the port is reachable immediately.
- Registered in `server.py`; added to `HealthHandler` components as
  `"screenparse"` so the Dashboard shows its loaded state.
- The handler takes the omniparser callable as an injectable dependency so
  tests can pass a fake (existing handler-test style).

**Docker** — extend the shore-ai-service image:
- Clone `microsoft/OmniParser` at a **pinned commit** into the image.
- Install extra deps: `ultralytics`, `supervision`, OCR backend,
  `opencv-python-headless` (torch/transformers already present).
- Download `microsoft/OmniParser-v2.0` weights via `huggingface_hub` at build
  time (deterministic image; ~1.5–2 GB extra VRAM at runtime).

**Env (service):** `SHORE_AI_SCREENPARSE_DEVICE` (default `cuda`),
`SHORE_AI_SCREENPARSE_BOX_THRESHOLD` (default `0.05`, upstream default).

### 2. Backend gRPC client — `app/services/ai_client/screenparse.py`

Mirror of `embed.py`:
- `screenparse_client.parse(image_bytes) -> ParsedScreen` where `ParsedScreen`
  is a Pydantic model (`elements`, `som_image_b64`, `width`, `height`).
- Raises `ScreenParseUnavailable` on graceful codes (UNAVAILABLE,
  DEADLINE_EXCEEDED, RESOURCE_EXHAUSTED, UNAUTHENTICATED, PERMISSION_DENIED);
  the session fails gracefully with a spoken message instead of crashing chat.
- Timeout: `SHORE_AI_SCREENPARSE_TIMEOUT_SECONDS` (default 30).

### 3. Backend `ComputerUseService` — `app/services/computer_use_service.py`

Singleton, wired into `/ws/chat` like `CopilotService` (attach/detach on
connect/disconnect). **One session at a time**; a second `computer_use` call
while active returns an error string to the agent.

**Session loop** (background `asyncio.Task`):
1. `desktop_backend.capture()` — the full monitor
   (`COMPUTER_USE_MONITOR_INDEX`) at native resolution as PNG bytes — no
   downscaling; OmniParser handles sizing and normalized bboxes make coords
   resolution-independent.
2. `screenparse_client.parse(...)`.
3. Build the decision request: system prompt from `prompts/computer_use.txt`
   (goal, rules, output contract) + user content containing the numbered
   element list (`[3] icon "settings gear" interactable, center (0.91, 0.05)`),
   the last `K` history entries (action + reason + result), and the SoM image.
   Sent to llama-server with `response_format=json_schema(ComputerUseAction)`
   — the LOCOMO-extractor pattern (httpx, 3 attempts, cancel-safe).
4. Validate (`element_id` in range, required fields per action) and execute via
   the `DesktopBackend`. Append a JSONL line to the audit log.
5. Push `computer_use_step` to the frontend, sleep
   `COMPUTER_USE_SETTLE_SECONDS`, loop.

**Action schema** (Pydantic → json_schema):

```python
class ComputerUseAction(BaseModel):
    action: Literal["click", "double_click", "right_click", "type",
                    "hotkey", "scroll", "wait", "done", "fail"]
    element_id: int | None = None    # click*/type target
    text: str | None = None          # type payload; done/fail summary
    keys: list[str] | None = None    # hotkey, e.g. ["ctrl", "s"]
    scroll_amount: int | None = None # positive=up, negative=down
    reason: str                      # one-line why (shown in UI + audit)
```

`type` clicks its target element first when `element_id` is set, then types.
`scroll` moves the cursor to the element center first when `element_id` is
set (else screen center), then scrolls. `wait` executes nothing — it just
waits one extra settle interval (for loading screens). v1 has **no
raw-coordinate click** — element ids only (simpler, safer; raw-xy fallback is
a noted future extension).

**Termination:** `done` (announce summary), `fail` (announce reason),
`COMPUTER_USE_MAX_STEPS` reached, explicit stop (frontend Stop button →
`computer_use_stop` WS message, or the `stop_computer_use` tool by voice),
WebSocket disconnect, or ScreenParse/LLM unavailable. A new chat message does
**not** auto-cancel the session — the user may just be asking for status;
stopping is always explicit.

**Interplay:** while a session is active the pipeline reports busy, so the
Screen Co-pilot watch loop cannot trigger concurrently. Step traffic never
touches memory (no `on_turn_completed`); only the final persona-voiced summary
behaves like a notification (`no_tools=True`, bundle dropped).

**Auth:** when `AUTH_ENABLED=True`, only the **admin** user can start a
session — this is full desktop control of Luna's machine.

### 4. Desktop backend — `app/services/desktop_backend.py`

**Why an abstraction:** Windows gives each interactive desktop one cursor, one
input queue, and one foreground window — a session on the user's desktop
necessarily borrows the real mouse and focus, and capture sees whatever
windows the user has on top. True "user works while Shore works" parallelism
requires Shore to own a *different* desktop (second RDP session or VM). The
loop must not care which — so capture and input live together behind one
interface (they must always target the same desktop), mirroring the existing
`terminal_backend.py` contract convention.

```python
class DesktopBackend(ABC):
    async def capture(self) -> CapturedScreen: ...   # png_bytes, width, height
    async def click(self, x: int, y: int, button: str = "left",
                    double: bool = False) -> None: ...
    async def type_text(self, text: str) -> None: ...
    async def hotkey(self, keys: list[str]) -> None: ...
    async def scroll(self, x: int, y: int, amount: int) -> None: ...
```

**v1 — `LocalDesktopBackend`:**
- Capture: mss on `COMPUTER_USE_MONITOR_INDEX` (native resolution, PNG).
- Input: `pyautogui` — interval-typed text, `hotkey(*keys)`, scroll at coords.
  Sync pyautogui calls run via `run_in_executor` to keep the loop async.
- Coordinate mapping: element bbox center (normalized) × monitor native pixel
  dims. Calls `SetProcessDPIAware()` once at init so pyautogui and mss agree
  on physical pixels under display scaling.
- **Known limitation (accepted for v1):** Shore shares the user's cursor and
  focus while a session runs — the user pauses briefly. Phase 2 (see Future)
  removes this.
- New backend dep: `pyautogui` (pure input injection — no torch, allowed).
- The backend instance is injectable into `ComputerUseService` so loop tests
  use a single recording fake for both capture and input.

### 5. Tools — `app/tools/computer_use_tools.py`

- `computer_use(goal: str)` — starts the session as a background task and
  returns immediately ("session started…"), so the agent's turn finishes and
  TTS plays while the session runs. Refuses when disabled, non-admin, or
  already active.
- `stop_computer_use()` — stops the active session (voice-friendly stop).
- Both retrievable by embedding; companion rule: `computer_use` brings
  `stop_computer_use` (and vice versa). New prompt section
  `prompts/tools_computer_use.txt` loaded only when these tools are retrieved
  (existing conditional-section mechanism): when to use it, one session at a
  time, prefer `run_command`/terminal tools for shell-appropriate work.

### 6. WS messages + frontend

`schemas/messages.py` additions:
- `computer_use_state` — `{status: started|running|done|failed|stopped, goal, steps_taken}`
- `computer_use_step` — `{step, action, element_content, reason, status}`
- Inbound `computer_use_stop` handled in `chat_ws.py`.

Frontend (minimal, chat-entry choice): extend WS types + `useAssistant`
handlers; render steps in the existing `AgentActionLog` style; show a Stop
button while a session is active.

### 7. Config (backend `.env`)

| Variable | Default | Description |
|---|---|---|
| COMPUTER_USE_ENABLED | False | Master switch for the computer-use mode |
| COMPUTER_USE_MAX_STEPS | 20 | Step budget per session |
| COMPUTER_USE_SETTLE_SECONDS | 1.5 | Wait after an action before next capture |
| COMPUTER_USE_MONITOR_INDEX | 1 | mss monitor to capture/control |
| COMPUTER_USE_DECISION_TIMEOUT | 60.0 | Per-step decision LLM timeout (s) |
| COMPUTER_USE_HISTORY_STEPS | 6 | History entries included per decision |
| COMPUTER_USE_AUDIT_LOG | data/computer_use_audit.log | JSONL audit of every action |
| SHORE_AI_SCREENPARSE_TIMEOUT_SECONDS | 30.0 | ScreenParse RPC timeout |

## Error handling

- **ScreenParse unavailable** → session ends as `failed` with a spoken
  explanation; chat keeps working (graceful-degrade convention).
- **Decision LLM invalid/unparseable output** → retry (3 attempts, extractor
  pattern); still bad → `failed`.
- **Invalid action** (element id out of range, missing field) → not executed;
  error is appended to history so the model can self-correct next step; two
  consecutive invalid actions → `failed`.
- **Every executed action** → one JSONL audit line: timestamp, step, action,
  element id + content, resolved pixel coords, reason.

## Testing

**shore-ai-service** (`tests/test_screenparse_handler.py`): fake omniparser
callable → proto mapping, normalized bboxes, `loaded()` flag, executor path.

**Backend unit tests** (existing fake-based style):
- `test_screenparse_client.py` — graceful-code → `ScreenParseUnavailable`.
- `test_desktop_backend.py` — normalized-center → pixel math, DPI-scaled dims
  (pyautogui/mss mocked).
- `test_computer_use_service.py` — scripted decision sequences through the loop
  with fake parser/LLM/desktop-backend: happy path to `done`, step budget,
  explicit stop, invalid-action self-correction then failure, audit lines
  written, single session enforcement, admin gating.
- Action schema validation cases.

**Early smoke test (before building the loop):** verify llama-server accepts
`response_format=json_schema` **combined with an image** in one request — this
is the one load-bearing assumption about llama.cpp. Fallback if unsupported:
prompt-enforced JSON + tolerant parsing.

**Live E2E (definition of done):** deploy the updated shore-ai-service on the
GPU box (Health shows `screenparse` loaded), set `COMPUTER_USE_ENABLED=True`,
then by chat/voice: *"Open Notepad and type hello world"* — observe streamed
steps, real clicks/typing, the audit log, and Shore's spoken completion summary.

## Risks / notes

- **Small local vision models are weak CUA policies.** SoM grounding is
  exactly the mitigation, but expectations for v1 are simple, short tasks.
  The step budget and audit log bound the blast radius of bad decisions.
- **VRAM:** +~1.5–2 GB on the GPU box next to Whisper/Kokoro/embeddings.
- **DPI scaling** is the classic silent killer for click coords — handled via
  `SetProcessDPIAware` + normalized bboxes, and covered by a unit test.
- **Auto-execute** means a misidentified element gets clicked with no gate;
  accepted by design (audit log + `COMPUTER_USE_ENABLED` default-off + admin-only).
- **v1 shares the user's cursor/focus** while a session runs (single input
  queue per Windows desktop). Accepted for v1; phase 2 gives Shore her own
  desktop.

## Future (explicitly out of scope for v1)

- **Phase 2 — `shore-desktop-agent` (parallel desktop for Shore):** a small
  capture+input WS service (mss + pyautogui + websockets — the
  `shore-pty-service` pattern) running inside a desktop Shore owns: a second
  local Windows user's RDP loopback session (or a Hyper-V VM). The backend
  gets a `RemoteDesktopBackend` (client modeled on `node_pty_client.py`)
  behind the same `DesktopBackend` interface — no loop changes. Known ops
  quirks to solve then: RDP session keep-alive, rendering while
  minimized/disconnected (registry workarounds), agent auto-start in-session.
- Raw-coordinate click fallback when OmniParser misses an element.
- Copilot-loop integration (proactive parse+act).
- Frontend goal-input panel; per-action confirm mode; non-Windows input backends.
