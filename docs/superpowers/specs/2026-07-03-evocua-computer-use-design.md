# Computer Use via EvoCUA — Task-Driven Co-pilot Redesign

**Date:** 2026-07-03

**Status:** Approved design, not yet implemented

**Platform:** macOS desktop (Tauri client) only

## Goal

Let Shore perform real mouse/keyboard actions on the user's Mac. The user
gives Shore a task in Chat or the HUD; Shore (the primary model, in persona)
analyzes it and delegates concrete GUI operations to **EvoCUA-8B**, a
specialist open-weights computer-use model served by a second llama-server
instance. Shore composes the final answer from the sub-agent's result — the
same orchestrator/sub-agent pattern as `ask_claude`.

This replaces the proactive Screen Co-pilot: the frame-push diff/cooldown
gate is removed. Screen analysis now happens only when the user assigns a
task.

## Decisions already made

- Trigger: explicit user task only. No proactive, self-initiated actions.
- Executor: Tauri desktop app (Rust `enigo` crate), alongside the existing
  native screen capture. No new standalone service.
- Loop location: backend (`computer_use_service`), so policy, limits and
  audit stay server-side — consistent with the enforcement lessons from the
  Tauri migration review (TAURI-003).
- Model: `meituan/EvoCUA-8B-20260105` (Apache-2.0, stock Qwen3-VL
  architecture) as GGUF + `mmproj` F16 on llama-server. Official scaffold
  parameters: relative coordinates, `resize_factor 32`, `max_history_turns 4`.

## Architecture

```text
User task (Chat / HUD prompt)
  └─ agent_service (primary LLM, persona)
       └─ tool: computer_use(task, max_steps?)
            └─ computer_use_service loop (backend):
                 1. screenshot via screenshot_bridge (reuses shared MediaStream / native capture)
                 2. EvoCUA-8B chat completion (cua_client → llama-server #2)
                 3. parse action (EvoCUA scaffold parser, ported)
                 4. WS "cua_step" → desktop client
                      └─ overlay highlight → Tauri input_execute (enigo)
                        → settle CUA_SETTLE_MS → capture fresh frame
                      └─ WS "cua_step_result {screenshot | error}"
                 5. repeat until finished / call_user / abort / max steps
            └─ returns text summary of the run to the agent loop
```

One WS round-trip per step: the step result carries the next screenshot, so
there is no separate capture request after the first frame.

## Model serving

Second llama-server instance on the GPU machine:

```bash
llama-server \
  -m models/evocua-8b-20260105-q4_k_s.gguf \
  --mmproj models/mmproj-Evocua-F16.gguf \
  --jinja \
  --host 0.0.0.0 --port 8081 \
  --ctx-size 16384
```

- `mmproj` stays F16 — vision precision drives grounding accuracy.
- Q4_K_S is the available community quant; if click accuracy is poor during
  QA, self-convert Q6_K/Q8_0 from the BF16 weights before changing the design.
- Registered in `services.yaml` (kind `process` or `remote`) so the Dashboard
  can start/stop it like the primary llama-server.

## Backend components

### `services/ai_client` is unchanged; new `services/cua_client.py`

httpx client to `EVOCUA_BASE_URL` (OpenAI-compatible `/v1/chat/completions`,
non-streaming). Mirrors `cloud_llm_service.py` error style: connection /
timeout / HTTP errors return an error result, never raise into the agent
loop. No memory `ContextBundle`, no profile — the sub-agent sees only the
task text, the system prompt and screenshots, so stored personal data and
secrets cannot leak into typed text.

### `services/computer_use_service.py`

Owns one run at a time (module singleton, same convention as
`copilot_service` it replaces):

- **Loop state:** task text, step counter, per-step history capped at
  `CUA_HISTORY_MAX_TURNS` (default 4, per EvoCUA scaffold), abort flag.
- **Prompt:** ported from the meituan/EvoCUA reference agent
  (`prompts/computer_use.txt`), including the action-space definition.
- **Action parser:** pure functions ported from the EvoCUA repo
  (`mm_agents/evocua/`). The model responds in `## Thought / ## Action /
  ## Code` sections; the last fenced code block carries either a constrained
  PyAutoGUI subset (`click`, `doubleClick`, `tripleClick`, `rightClick`,
  `middleClick`, `moveTo`, `dragTo`, `scroll`, `hscroll`, `write`, `press`,
  `hotkey`, `keyDown`, `keyUp`) or a control call (`computer.wait`,
  `computer.terminate(status="success"|"failure", answer=...)`). Unknown or
  malformed output aborts the run with a parse error in the summary. The
  ported system prompt drops the reference scaffold's sudo-password line —
  Shore never provides credentials to the sub-agent.
- **Coordinate mapping:** pure function mapping EvoCUA's relative
  coordinates → captured-image pixels → the client's logical screen
  coordinates. Each `cua_step_result` includes the client's logical screen
  size and the screenshot's pixel dimensions so the mapping handles Retina
  scale factors explicitly.
- **Run summary:** ordered list of executed actions + terminal state
  (`finished` / `call_user` question / aborted / step limit / error),
  returned as the tool's string result.
- **Audit:** every dispatched action appended to `CUA_AUDIT_LOG`
  (timestamp, user, action, coordinates, outcome) — same pattern as
  `terminal_audit.log`.

### Tool `tools/computer_use.py`

`computer_use(task: str, max_steps: int = CUA_MAX_STEPS)` — LangChain tool,
selected by the embedding retriever (not always-available). Guards, checked
at execution time in this order, each returning a clear error string:

1. `ws_user_role == "admin"` (non-admin users cannot drive input).
2. A desktop client with an active screen-share/capture session is attached
   (see `cua_ready` below); otherwise: "Computer use requires the desktop
   app with screen sharing enabled."
3. No other computer-use run is in progress.

Notifications already run with `no_tools=True`, so scheduler/n8n prompts can
never trigger it.

## WebSocket protocol (additions to `/ws/chat`)

| Type | Direction | Payload |
|---|---|---|
| `cua_ready` | client → server | `{screen: {width, height}}` — sent by the desktop client when capture is available; cleared on disconnect/share end |
| `cua_step` | server → client | `{request_id, action, display_hint}` — one action to execute; `display_hint` is a short human-readable label for the overlay |
| `cua_step_result` | client → server | `{request_id, screenshot?: data_url, screen: {width, height}, error?}` — the backend derives image dimensions from the decoded screenshot |
| `cua_state` | server → client | `{running: bool, step, max_steps, task}` — drives Chat banner and HUD |
| `cua_abort` | client → server | `{}` — stop button / global shortcut |

`cua_step` follows the `screenshot_bridge` future-resolution pattern and the
same constraint: the executor awaits responses from a task separate from the
WS receive loop. Per-step deadline `CUA_STEP_TIMEOUT_SECONDS`; a timeout
aborts the run.

## Desktop executor (Tauri)

New Rust command `input_execute(action)` using `enigo`:

- Implements click/double/right-click/drag/scroll at logical coordinates,
  `type` (text entry), `hotkey` (modifier combos).
- Requires the macOS **Accessibility** permission; the command returns a
  typed error when the permission is missing, which flows into the run
  summary so Shore can tell the user how to grant it.
- Frontend `cua-executor.service.ts` handles `cua_step`: invokes
  `input_execute`, waits `CUA_SETTLE_MS`, captures a fresh frame through the
  existing `screen-capture.service.ts` path, and replies with
  `cua_step_result`. The Chat banner shows the current step and action label
  while a run is active.
- Global shortcut `Cmd+Shift+Escape` (registered only while a run is
  active) sends `cua_abort`.
- v1 controls the **primary display only** — the same display the native
  capture path records. Multi-monitor is out of scope.

Browser (non-Tauri) clients never send `cua_ready`, so the tool politely
refuses — same gating philosophy as HUD terminal approval.

## Co-pilot rework (removals)

- Remove the `copilot_frame` push loop, `norm_abs_diff` / `should_trigger`
  gating and their frontend interval; delete
  `COPILOT_CAPTURE_INTERVAL_SECONDS`, `COPILOT_CHANGE_THRESHOLD`,
  `COPILOT_COOLDOWN_SECONDS`, `COPILOT_IDLE_THRESHOLD_SECONDS`.
- `copilot_start` / `copilot_stop` remain as the screen-share session
  toggle (the `getDisplayMedia` / native-capture grant), because
  `screenshot_bridge`, `capture_screen`/`analyze_screen` and the CUA loop
  all consume that session. Rename in UI copy from "Co-pilot" to "Screen
  access".
- `run_copilot_pipeline` and `copilot_message` are removed; CUA runs stream
  through the normal agent event path (`AgentActionLog` shows each step).
- HUD: agent status `monitoring` now means "computer-use run active";
  the existing `stop_copilot` HUD action is rewired to send `cua_abort`.
  No HUD protocol change beyond relabeling.

## Safety model

- **Consent = the task itself.** A run starts only from an explicit user
  message in the same session; there is no confirmation dialog per action in
  v1 (the explicit task + visible overlay + abort switch are the controls).
- Admin-only, desktop-only, one run at a time, hard `CUA_MAX_STEPS` cap,
  per-step timeout, global-shortcut and UI abort.
- The sub-agent context excludes memory/profile, so typed text can never
  emit stored secrets. `computer.terminate` returns control to Shore; its
  `answer` payload is surfaced to the user verbatim.
- Screenshots remain ephemeral (never persisted), as today.
- Audit log of every action for post-hoc review.

## Error handling

| Failure | Behavior |
|---|---|
| EvoCUA server down/timeout | Tool returns error string; Shore explains and suggests Dashboard start |
| Action parse failure | Abort run, include raw model output tail in summary |
| Step timeout / client disconnect | Abort run, summary marks last completed step |
| Accessibility permission missing | `input_execute` error surfaces as setup instructions |
| Abort (button/shortcut) | Loop stops before dispatching the next action; summary marks user-aborted |

## Configuration

| Variable | Default | Description |
|---|---|---|
| EVOCUA_BASE_URL | http://localhost:8081 | EvoCUA llama-server URL |
| EVOCUA_TIMEOUT | 60 | Per-completion timeout (seconds) |
| CUA_MAX_STEPS | 15 | Hard cap on actions per run |
| CUA_STEP_TIMEOUT_SECONDS | 30 | Deadline for one execute+capture round-trip |
| CUA_SETTLE_MS | 800 | Wait after an action before recapture |
| CUA_HISTORY_MAX_TURNS | 4 | Screenshot/action turns kept in EvoCUA context |
| CUA_AUDIT_LOG | data/cua_audit.log | Action audit log |

`COPILOT_MAX_IMAGE_SIZE` (1280) is reused for CUA frame capture.

## Testing

- Unit (pure, no I/O): action parser fixtures from real EvoCUA outputs;
  coordinate mapping including Retina scale; run-summary reducer; guard
  ordering in the tool.
- Loop test with a fake CUA client + fake executor: finished path, step
  limit, abort, parse failure, timeout.
- Rust: `input_execute` argument validation; permission-missing error path.
- Manual macOS QA: Accessibility grant flow, overlay visibility, abort
  shortcut mid-run, a scripted end-to-end task ("open System Settings and
  search for X"), grounding accuracy spot-check to decide whether Q4_K_S
  suffices.

## Out of scope (v1)

- Multi-monitor support.
- Batched multi-action steps (design option C) — latency optimization.
- Proactive suggestions ("I noticed you might want…").
- Pause-on-user-input detection (taking the mouse back mid-run pauses
  nothing in v1; use the abort shortcut).
- On-screen highlight at the target point before each click — a DOM overlay
  cannot draw outside the app window; a HUD-window target dot is the future
  path.
- HUD-initiated per-action approval UI.
