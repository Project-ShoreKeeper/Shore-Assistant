# Screen Co-pilot — Design

**Date:** 2026-06-27
**Status:** Draft (pending user review)
**Scope:** A toggleable, server-side **action-first** screen co-pilot. When the user
enables a session, the backend watches the host display, and on a meaningful change
+ user idle, captures the screen, sends it to the vision model, and lets the agent
take a **concrete action** (run a command, read a log, etc.). Safe (whitelisted)
actions auto-run; risky actions go through the existing terminal confirm dialog.
**Out of scope:** OS toast / global-hotkey approval while in another app, multi-monitor
selection UI, lock-screen detection, client-side (`getDisplayMedia`) capture, voice
delivery of suggestions (TTS is off for co-pilot turns).

## Goal

Make Shore work *alongside* the user through the screen. The user turns on "Co-pilot
mode", then keeps working in their IDE / terminal / browser. The backend observes the
physical display (via `mss` — same host that runs the backend, i.e. the user's own
machine), and when it detects the user has paused after changing something on screen,
it asks the vision model what's happening and lets the agent **do a useful concrete
thing** rather than narrate.

Key properties:

- **Server-side capture + loop.** Capture and the watch loop run in Python on the
  backend host, NOT in the browser. Switching browser tabs or working in another
  application does not break it — the loop is immune to background-tab throttling, and
  `mss` grabs whatever is on the physical monitor. This is the decisive advantage over
  a browser `getDisplayMedia` approach.
- **Action-first, not voice-first.** The unit of output is a concrete action surfaced
  in the existing `AgentActionLog`, not a spoken sentence. TTS is forced off for
  co-pilot turns.
- **Tiered autonomy via the existing whitelist.** No new autonomy mechanism. The agent
  calls `run_command`; `WhitelistGuard.check` already returns `allow` (auto-run) /
  `confirm` (dialog) / `block` (refuse). Safe diagnostics run automatically; writes and
  deletes prompt for confirmation.
- **Quiet by default.** Gated by screen-change + idle + cooldown, and a `__NOOP__`
  sentinel lets the model stay silent when there is nothing useful to do.

The user (not the LLM) drives the on/off via a UI toggle (chat header or
`SettingsPanel`). Each connection is inactive by default and starts only after
an explicit client request.

## Architecture

```
back-end/app/
├── services/
│   ├── copilot_service.py        # NEW — CopilotService singleton: watch loop + gating
│   ├── notification_service.py   # (pattern reference — attach/callback wiring)
│   ├── connection_manager.py     # (reuse — single-user send handle)
│   ├── terminal_service.py       # (reuse — run_oneshot applies WhitelistGuard + confirm)
│   └── terminal_whitelist.py     # (reuse — allow/confirm/block decision)
├── tools/
│   └── screen_tools.py           # reuse _capture_screen_b64(); extract a thumbnail helper
├── api/websockets/
│   └── chat_ws.py                # MODIFY — wire copilot_service; copilot_start/stop msgs;
│                                 #          source="copilot" branch in run_agent_pipeline
└── core/
    └── config.py                 # ADD COPILOT_* settings
```

No new endpoints, no new microservice, no new ML dependency. `mss` + `PIL` are already
present (used by `screen_tools.py`); `numpy` is already used by `chat_ws.py`. Idle and
active-window detection use stdlib `ctypes` (Windows `user32`).

### CopilotService (new singleton)

Mirrors `NotificationService`'s attach/callback pattern and `ConnectionManager`'s
single-user assumption (at most one connection / one session at a time).

```python
class CopilotService:
    def attach(self, trigger_cb, is_busy_cb) -> None: ...   # wired by chat_ws on connect
    def detach(self) -> None: ...                           # on disconnect → stop session
    async def start_session(self) -> None: ...              # spawn _run_loop()
    async def stop_session(self) -> None: ...               # cancel loop
    @property
    def active(self) -> bool: ...
    async def _run_loop(self) -> None: ...                  # the watch loop (see Data Flow)
```

State: `_active`, `_loop_task`, `_trigger_cb`, `_is_busy_cb`, `_last_thumb` (numpy
grayscale thumbnail), `_last_action_ts`.

Platform shims (small, individually monkeypatchable for tests):

- `_os_idle_seconds() -> float | None` — `ctypes.windll.user32.GetLastInputInfo`;
  returns `None` on non-Windows → idle gate is skipped (degrade open).
- `_active_window_title() -> str` — `GetForegroundWindow` + `GetWindowText`; `""` on
  failure.
- `_grab_thumbnail() -> np.ndarray` — small (e.g. 64×64) grayscale array for cheap diff.
- Full capture reuses `screen_tools._capture_screen_b64(max_size=COPILOT_MAX_IMAGE_SIZE)`.

### Gating decision (pure, testable)

Extracted from I/O so it can be unit-tested exhaustively:

```python
def _should_trigger(diff: float, idle: float | None, since_last: float,
                    busy: bool, *, change_threshold, idle_threshold,
                    cooldown) -> bool:
    if busy:
        return False
    if since_last < cooldown:
        return False
    if diff < change_threshold:
        return False
    if idle is not None and idle < idle_threshold:
        return False
    return True
```

`diff` is the normalized mean absolute difference between the current and last-analyzed
thumbnails (0..1).

## Data Flow — one loop tick

```
every COPILOT_CAPTURE_INTERVAL seconds (while session active):
  busy?  (is_busy_cb(): an agent task is already running)  ──► skip
  thumb = _grab_thumbnail();  diff = norm_abs_diff(thumb, _last_thumb)
  idle  = _os_idle_seconds()
  _should_trigger(diff, idle, now - _last_action_ts, busy, ...) ?
     │ no  ──► skip (static screen / still typing / within cooldown)
     ▼ yes
  image_b64 = _capture_screen_b64();  title = _active_window_title()
  prompt = build_copilot_prompt(title)            # ephemeral framing
  screenshot = {"data_url": f"data:image/jpeg;base64,{image_b64}", ...}
  await trigger_cb(prompt, screenshot)            # → run_copilot_pipeline (own agent_task)
      ├─ agent observes screen, decides a concrete action
      ├─ run_command (allow)   → auto-run; action buffered into final copilot_message
      ├─ run_command (confirm) → terminal_confirm dialog broadcast live (waits for user)
      ├─ run_command (block)   → refused by guard
      └─ nothing useful        → model returns "__NOOP__" → swallowed (no message/persist)
  _last_thumb = thumb;  _last_action_ts = now
```

The trigger callback updates `_last_action_ts` even on `__NOOP__` so cooldown applies to
every analysis, not just acted-upon ones (prevents re-analyzing a static screen every
few seconds).

### chat_ws.py wiring

- New callback inside the handler:
  ```python
  async def run_copilot(prompt: str, screenshot: dict):
      await _start_agent(prompt, source="copilot", images=[screenshot])
  ```
- On connect: `copilot_service.attach(run_copilot,
  is_busy_cb=lambda: bool(agent_task and not agent_task.done()))`.
- In `finally` (and only when still the active connection):
  `copilot_service.detach()`.
- New inbound WS messages:
  - `{"type": "copilot_start"}` → `await copilot_service.start_session()`
  - `{"type": "copilot_stop"}`  → `await copilot_service.stop_session()`
  - Both echo `{"type": "copilot_state", "active": <bool>}` for the UI.

### run_copilot_pipeline (dedicated path)

A co-pilot turn behaves like a user turn for *tooling* but like a notification for
*memory*, and **buffers its output** so a `__NOOP__` stays completely silent. It is a
dedicated function (not a third `source` branch in `run_agent_pipeline`) to keep both
paths focused:

- Build a transient history `list(conversation_history) + [{"role":"user","content":
  framing}]` and a multimodal `live_user_message` from the framing text + screenshot.
  The framing/screenshot are **ephemeral** — never appended to the real
  `conversation_history`, short-term memory, or sent to the LOCOMO worker. (Passing a
  transient history is safe: `agent_service.run` builds its own message list and never
  mutates the list it is given.)
- Run **with tools** (`no_tools=False`) so `run_command` and the whitelist/confirm path
  work. No TTS (action-first).
- **Buffer** the agent events: collect `agent_action` items into `current_actions` and
  capture the final text from `llm_complete`. Do **not** forward `llm_token` /
  `llm_sentence` to the client.
- After the run:
  - `clean = final_text.strip()`. If `clean == "__NOOP__"` (or `clean == ""` with no
    actions) → **swallow**: emit nothing, persist nothing.
  - Otherwise emit a single `{"type": "copilot_message", "text": ..., "agent_actions":
    current_actions, "timestamp": ...}` and persist a **compact co-pilot record**
    (assistant text + `agent_actions`, tagged `is_copilot: True`) so the user can follow
    up ("undo that"). The screenshot is never persisted.
- **Live exception:** confirm dialogs are not buffered. When a risky `run_command` hits
  `confirm`, `terminal_service` broadcasts the `terminal_confirm` request over the same
  WebSocket immediately (independent of the buffered co-pilot events), so the user can
  approve/reject in real time. The receive loop stays free to deliver
  `terminal_confirm_response` because the co-pilot pipeline runs as a separate
  `agent_task`.

### Framing prompt (ephemeral)

Approximate content (final wording lives in a `prompts/` file for consistency with the
persona system):

> This is the user's current screen (focused window: `<title>`). You are an
> **action** co-pilot. If there is a specific, useful thing to do right now — run the
> tests after a code change, read the log when an error is visible, `git status`, lint,
> build — **do it with a tool**. Safe commands run automatically; commands that write or
> delete will ask the user to confirm. **Do not just describe the screen.** If there is
> no genuinely useful action to take right now, reply with exactly `__NOOP__` and do
> nothing.

## Anti-nag / runaway control

- **`__NOOP__` sentinel** — primary "stay quiet" valve.
- **Cooldown** (`COPILOT_COOLDOWN_SECONDS`, default 45s) — minimum gap between triggers,
  enforced even when change+idle keep passing. `_last_action_ts` is updated on every
  trigger (including `__NOOP__`), so a static screen is not re-analyzed every few seconds.
- **Change gate** — `_last_thumb` only updates on a trigger, so the diff is measured
  against the last *analyzed* frame; a screen that stops changing stops triggering.
- **Busy gate** — never overlaps a user chat turn or a prior co-pilot turn.

## Configuration

Added to `core/config.py` and the `.env` table in `CLAUDE.md`:

| Variable | Default | Description |
|----------|---------|-------------|
| COPILOT_CAPTURE_INTERVAL_SECONDS | 4 | Watch-loop tick interval |
| COPILOT_IDLE_THRESHOLD_SECONDS | 3 | Minimum "hands-off" idle before analyzing |
| COPILOT_CHANGE_THRESHOLD | 0.06 | Normalized thumbnail diff treated as "changed" |
| COPILOT_COOLDOWN_SECONDS | 45 | Minimum gap between triggers |
| COPILOT_MONITOR_INDEX | 1 | `mss` monitor index to capture |
| COPILOT_MAX_IMAGE_SIZE | 1280 | Longest edge of the JPEG sent to the vision model |

## Frontend

- A "Co-pilot" toggle (chat header or `SettingsPanel`) sends `copilot_start` /
  `copilot_stop` and reflects an "active" pill driven by `copilot_state`.
- No new visualization surface — the existing `AgentActionLog` already renders
  `agent_action` / `tool_result` events, which is exactly what the user needs to see.
- Risky-action confirms reuse the existing terminal confirm dialog. (OS toast / hotkey
  approval while focused on another app is a v2 follow-up.)

## Privacy

- Inactive by default; only an explicit client request starts a session.
- Vision runs **locally** on llama-server; no screen data leaves the host.
- Screenshots are ephemeral: never written to disk, short-term memory, Profile,
  Episodic, or the LOCOMO worker.
- The loop only runs while a client is connected; disconnect stops the session.

## Testing

- **`_should_trigger`** — pure function; unit-test every branch (busy, cooldown,
  static screen, still-typing, idle unknown/None, all-pass).
- **Diff** — `norm_abs_diff` on two known small numpy arrays → deterministic value.
- **`__NOOP__` suppression** — fake agent yielding `llm_complete` with `__NOOP__` vs a
  real action; assert no client bubble and no persistence on `__NOOP__`, and a compact
  record on a real action.
- **Whitelist mapping** — assert a whitelisted command is `allow` (auto) and a
  non-whitelisted one is `confirm` through `terminal_service.run_oneshot` (guard already
  has coverage; add a co-pilot-path integration check).
- **Platform shims** — monkeypatch `_os_idle_seconds`, `_grab_thumbnail`,
  `_capture_screen_b64`, `_active_window_title` so tests run headless on CI.

## Open Questions / v2 follow-ups

- OS toast + global hotkey to approve a risky action without leaving the focused app.
- Lock-screen / screensaver detection (skip analysis).
- Multi-monitor selection UI (config index covers the common case for now).
- Optional per-session action budget if cooldown proves insufficient in practice.
- Action-signature dedupe (`hash(tool + args)` of the last co-pilot action) to suppress
  identical repeated actions — needs pipeline→service feedback; deferred since NOOP +
  cooldown + change gate already prevent runaway.
- Live streaming of co-pilot tool activity (currently bundled into the final
  `copilot_message`).
