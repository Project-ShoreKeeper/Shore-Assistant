# UI-TARS CUA Format — Design

**Date:** 2026-07-08
**Status:** Approved

## Goal

Make the computer-use sub-agent's model format pluggable so Shore can run
UI-TARS-1.5-7B (open weights, Qwen2.5-VL-based, GGUF on llama-server) as an
alternative to EvoCUA-8B, switched by config. UI-TARS-2 weights are not
public (research-access only), so 1.5-7B is the target; the adapter seam
makes a future UI-TARS-2 module trivial if weights ship.

## Non-goals

- No frontend / Tauri executor changes. UI-TARS actions map onto the
  existing `cua_step` command set.
- No change to the run-loop safety model (admin-only, desktop-only,
  single run, `CUA_MAX_STEPS`, abort, JSONL audit).
- No Volcengine / cloud UI-TARS API client.

## Architecture

New package `back-end/app/services/cua/formats/` with one module per model
format. `actions.py` remains the shared helper module (`smart_resize`,
`process_screenshot`, `_project`, `CuaCommand`, `CuaParseError`, and the
EvoCUA code parser). `service.py` resolves the active adapter from
`settings.CUA_MODEL_FORMAT` at the start of each run.

### Adapter surface (module-level, per format)

| Attribute | evocua | ui_tars |
|---|---|---|
| `model_label` | `evocua-8b` | `ui-tars-1.5-7b` |
| `prompt_file` | `computer_use.txt` | `computer_use_ui_tars.txt` |
| `instruction_template` | existing `# Task Instruction:` block | `## User Instruction\n{task}` |
| `resize_factor` | 32 | 28 (Qwen2.5-VL patch size) |
| `wait_seconds` | 20 | 5 |
| `extra_params` | `{}` | `{"frequency_penalty": 1.0}` |
| `parse(text, model_size, screen_size)` | wraps existing `parse_cua_response` + `code_to_commands` + thought extraction | UI-TARS `Thought:`/`Action:` parser |

`formats/__init__.py` exposes `get_format(name)` (registry dict; unknown
name → error at run start with a clear message).

`parse` returns `(hint, thought, commands: list[CuaCommand])` — hint is the
one-line action description for the HUD/audit, thought feeds the audit log.

### UI-TARS parser (`formats/ui_tars.py`)

- Extract `Thought: ...` and `Action: ...` sections (regex, DOTALL;
  Action is required, Thought optional).
- Parse the action string with `ast.parse`; only bare calls with literal
  args are allowed (same no-eval policy as EvoCUA). Multiple calls
  separated by newlines are accepted.
- Coordinates: accept `'<point>x y</point>'` (UI-TARS-1.5) and legacy
  `'(x,y)'` / `<|box_start|>(x1,y1)<|box_end|>` string forms. Coordinates
  are absolute in the smart-resized image space; project via the existing
  `_project` (which also handles normalized 0..1).
- Action mapping:
  - `click(point)` → `click`
  - `left_double(point)` → `doubleClick`
  - `right_single(point)` → `rightClick`
  - `drag(start_point, end_point)` → `moveTo(start)` then `dragTo(end)`
  - `hotkey(key='ctrl c')` → `hotkey(keys=['ctrl','c'])` (space-split)
  - `type(content)` → `write(text)`; if content ends with `\n`, append
    `press(['enter'])` and strip the newline from the written text
  - `scroll(point, direction)` → `scroll` (up=+5 / down=-5 clicks) or
    `hscroll` (left/right) at the projected point
  - `wait()` → `wait`
  - `finished(content?)` → `terminate(status="success", answer=content)`
  - `call_user()` (defensive) → `terminate(status="failure",
    answer="the model asked for user help")`
  - anything else → `CuaParseError`

### Prompt

`back-end/app/prompts/computer_use_ui_tars.txt`: official UI-TARS-1.5
computer-use template — `Thought:/Action:` output format and the action
space above. The task itself goes into the first user turn via
`instruction_template`, matching ByteDance's reference agent.

### Service changes (`service.py`)

- Resolve adapter at run start; fail the run cleanly on unknown format.
- `process_screenshot(frame, factor=adapter.resize_factor)`.
- Replace direct `parse_cua_response`/`code_to_commands`/`_extract_thought`
  calls with `adapter.parse(...)`.
- `wait` command sleeps `adapter.wait_seconds`.
- System-prompt cache keyed by format name.
- Instruction text built from `adapter.instruction_template`.

### Client changes (`client.py`)

`next_step(messages, model_label, extra_params)` — model label and extra
sampling params come from the adapter; endpoint config stays
`EVOCUA_BASE_URL` / `EVOCUA_API_KEY` / `EVOCUA_TIMEOUT` (they configure the
CUA model server regardless of which model it serves).

### Config (`core/config.py`)

`CUA_MODEL_FORMAT: str = "evocua"` — values `evocua` | `ui_tars`.

## Testing

- `tests/cua/test_ui_tars_format.py`: one case per mapping row, drag →
  two commands, type-with-trailing-newline → write + press enter,
  scroll directions, finished with/without answer, coordinate projection
  from both point syntaxes, missing Action / garbage → `CuaParseError`.
- Service-level test with `CUA_MODEL_FORMAT=ui_tars` (monkeypatched):
  full step round-trip using a canned UI-TARS response.
- All existing `tests/cua/*` stay green (EvoCUA remains the default).

## Docs / ops

- CLAUDE.md: add `CUA_MODEL_FORMAT` to the config table; update the
  computer-use bullet to mention the pluggable format.
- Serving note: `llama-server -m <UI-TARS-1.5-7B GGUF> --mmproj <mmproj>
  --port 8081` (community GGUF quants exist; Qwen2.5-VL is supported by
  llama.cpp).
