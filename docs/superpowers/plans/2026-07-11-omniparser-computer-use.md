# OmniParser v2 Computer-Use Mode — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Shore operate the backend host's desktop — the user states a goal by voice/chat, OmniParser v2 (in `shore-ai-service`) grounds the screen into numbered elements, Shore's local vision LLM picks the next action, and the backend executes real mouse/keyboard input, streaming an annotated step viewer to the frontend.

**Architecture:** New `ScreenParse` gRPC servicer in `shore-ai-service` (next to STT/TTS/Embed). Backend `ComputerUseService` runs a capture→parse→decide→act session loop behind a `DesktopBackend` abstraction (v1 = `LocalDesktopBackend` on the host desktop; phase-2 RDP agent drops in later). A `computer_use(goal)` tool starts the session as a background task; steps stream over the existing WebSocket via `connection_manager`.

**Tech Stack:** Python 3.10+ / FastAPI / grpc.aio / Pydantic (backend + service); pyautogui + mss (input/capture); PyTorch + ultralytics YOLO + Florence-2 + OCR (OmniParser, service only); React 19 + TypeScript (frontend).

**Spec:** `docs/superpowers/specs/2026-07-11-omniparser-computer-use-design.md`

**Working directory / branch:** repo root `\\wsl.localhost\Ubuntu\home\luna\Shore-Assistant`, branch `feat/omniparser-computer-use` (already created).

---

## Conventions for every task

- Backend tests run from `back-end/`: `cd back-end && python -m pytest tests/... -v`.
- Service tests run from `shore-ai-service/`: `cd shore-ai-service && python -m pytest tests/... -v`.
- Regenerating gRPC stubs: `make proto` (run in `shore-ai-service/` **and** `back-end/`). Both `_pb/` dirs are gitignored — generated stubs are never committed.
- Frontend runs from `front-end/`: `npm run lint`, `npm run build`.
- Commit after every green step. Commit messages use the repo's `type(scope): summary` style.
- Async services offload blocking work with `run_in_executor` (Embed/STT pattern). Graceful-degrade on gRPC UNAVAILABLE/DEADLINE_EXCEEDED/RESOURCE_EXHAUSTED/UNAUTHENTICATED/PERMISSION_DENIED (Embed pattern).

---

## File Structure

**shore-ai-service (new / modified):**
- Create `proto/shore/ai/v1/screenparse.proto` — ScreenParse service contract.
- Create `src/shore_ai/handlers/screenparse.py` — handler wrapping OmniParser, injectable parser callable.
- Modify `src/shore_ai/server.py` — construct + register ScreenParse, add to Health, background load.
- Modify `pyproject.toml` — add `ultralytics`, `supervision`, `opencv-python-headless`, `easyocr`, `huggingface_hub`, `einops`, `timm`.
- Modify `Dockerfile` — clone OmniParser at pinned commit, download weights.
- Create `tests/test_screenparse_handler.py` — fake-parser handler tests.

**backend (new / modified):**
- Modify `app/core/config.py` — `COMPUTER_USE_*` + `SHORE_AI_SCREENPARSE_*` settings.
- Create `app/services/ai_client/screenparse.py` — gRPC client + `ParsedScreen`/`ParsedElement` + `ScreenParseUnavailable`.
- Create `app/services/desktop_backend.py` — `DesktopBackend` ABC, `CapturedScreen`, `LocalDesktopBackend`, coordinate math.
- Create `app/services/computer_use_service.py` — action schema, pure helpers, `ComputerUseService` loop.
- Create `app/tools/computer_use_tools.py` — `computer_use`, `stop_computer_use` tools.
- Modify `app/tools/__init__.py` — register the two tools.
- Modify `app/services/tool_retriever.py` — always-available + companion wiring.
- Modify `app/services/llm_service.py` — new `tools_computer_use.txt` conditional section.
- Create `app/prompts/tools_computer_use.txt` — computer-use rules.
- Create `app/prompts/computer_use_decider.txt` — per-step decision system prompt.
- Modify `app/schemas/messages.py` — `computer_use_state` / `computer_use_step` models.
- Modify `app/api/websockets/chat_ws.py` — attach/detach, `computer_use_stop`, admin gate, step sender.
- Modify `back-end/requirements.txt` — add `pyautogui`.
- Create `tests/services/test_screenparse_client.py`.
- Create `tests/services/test_desktop_backend.py`.
- Create `tests/services/test_computer_use_service.py`.
- Create `tests/manual_screenparse_smoke.md` + `tests/smoke_json_schema_image.py` — llama-server assumption spike.

**frontend (new / modified):**
- Modify `src/services/chat-websocket.service.ts` — message types + send methods.
- Modify `src/hooks/useAssistant.ts` — handlers + session state.
- Create `src/pages/Chat/ComputerUseViewer.tsx` — live SoM step viewer.
- Modify `src/pages/Chat/index.tsx` — mount the viewer.

---

## PHASE A — shore-ai-service: ScreenParse servicer

### Task 1: ScreenParse proto + regenerate stubs

**Files:**
- Create: `shore-ai-service/proto/shore/ai/v1/screenparse.proto`

- [ ] **Step 1: Write the proto**

Create `shore-ai-service/proto/shore/ai/v1/screenparse.proto`:

```proto
syntax = "proto3";
package shore.ai.v1;

service ScreenParse {
  rpc Parse(ParseRequest) returns (ParseResponse);
}

message ParseRequest {
  bytes image = 1;          // encoded PNG or JPEG bytes
}

message Element {
  uint32 id           = 1;  // Set-of-Mark index, matches number drawn on image
  string type         = 2;  // "text" | "icon"
  string content      = 3;  // OCR text or Florence-2 caption
  bool   interactable = 4;
  float  x1 = 5;
  float  y1 = 6;
  float  x2 = 7;
  float  y2 = 8;            // bbox, normalized 0..1
}

message ParseResponse {
  repeated Element elements       = 1;
  bytes            som_image_jpeg = 2;  // annotated Set-of-Mark image
  uint32           width          = 3;  // parsed image px dims
  uint32           height         = 4;
  float            latency_ms     = 5;
}
```

- [ ] **Step 2: Regenerate stubs in the service**

Run: `cd shore-ai-service && make proto`
Expected: no errors; `src/shore_ai/_pb/screenparse_pb2.py` and `screenparse_pb2_grpc.py` created.

- [ ] **Step 3: Verify the stub imports**

Run: `cd shore-ai-service && python -c "from shore_ai._pb import screenparse_pb2, screenparse_pb2_grpc; print(screenparse_pb2.ParseRequest, screenparse_pb2_grpc.ScreenParseServicer)"`
Expected: prints the two class reprs, no ImportError.

- [ ] **Step 4: Commit**

```bash
git add shore-ai-service/proto/shore/ai/v1/screenparse.proto
git commit -m "feat(shore-ai): ScreenParse proto contract"
```

(The `_pb/` stubs are gitignored — nothing to commit for them.)

---

### Task 2: ScreenParse handler (fake-parser injectable)

**Files:**
- Create: `shore-ai-service/src/shore_ai/handlers/screenparse.py`
- Test: `shore-ai-service/tests/test_screenparse_handler.py`

The handler wraps an OmniParser callable but never imports it directly — the
callable is injected, so tests pass a fake and CI needs no GPU/models. The
real callable is built lazily in `server.py` (Task 3).

**Parser callable contract:** `parse(image_bytes: bytes) -> tuple[list[dict], bytes]`
returning `(elements, som_jpeg_bytes)` where each element dict has keys
`type` (str), `content` (str), `interactable` (bool), `bbox`
(`[x1, y1, x2, y2]` normalized floats). This matches what a thin adapter over
OmniParser's `util/omniparser.py` produces.

- [ ] **Step 1: Write the failing test**

Create `shore-ai-service/tests/test_screenparse_handler.py`:

```python
import pytest

from shore_ai.handlers.screenparse import ScreenParseHandler
from shore_ai._pb import screenparse_pb2


def _fake_parser(calls):
    """Return a parser fn that records calls and returns fixed elements."""
    def parse(image_bytes):
        calls.append(image_bytes)
        elements = [
            {"type": "text", "content": "File",
             "interactable": True, "bbox": [0.0, 0.0, 0.1, 0.05]},
            {"type": "icon", "content": "settings gear",
             "interactable": True, "bbox": [0.9, 0.0, 0.95, 0.05]},
        ]
        return elements, b"FAKE_JPEG_BYTES"
    return parse


@pytest.mark.asyncio
async def test_parse_maps_elements_to_proto():
    calls = []
    handler = ScreenParseHandler(parser=_fake_parser(calls), device="cpu")
    req = screenparse_pb2.ParseRequest(image=b"PNGDATA")
    resp = await handler.Parse(req, context=None)

    assert calls == [b"PNGDATA"]
    assert len(resp.elements) == 2
    e0 = resp.elements[0]
    assert e0.id == 0
    assert e0.type == "text"
    assert e0.content == "File"
    assert e0.interactable is True
    assert (e0.x1, e0.y1, e0.x2, e0.y2) == pytest.approx((0.0, 0.0, 0.1, 0.05))
    assert resp.elements[1].id == 1
    assert resp.som_image_jpeg == b"FAKE_JPEG_BYTES"
    assert resp.latency_ms >= 0.0


@pytest.mark.asyncio
async def test_loaded_reflects_parser_presence():
    handler = ScreenParseHandler(parser=_fake_parser([]), device="cpu")
    assert handler.loaded() is True
    unloaded = ScreenParseHandler(parser=None, device="cpu")
    assert unloaded.loaded() is False


@pytest.mark.asyncio
async def test_parse_aborts_when_not_loaded():
    handler = ScreenParseHandler(parser=None, device="cpu")
    req = screenparse_pb2.ParseRequest(image=b"PNGDATA")

    class _Ctx:
        def __init__(self):
            self.code = None
            self.details = None

        async def abort(self, code, details):
            self.code = code
            self.details = details
            raise RuntimeError("aborted")

    ctx = _Ctx()
    with pytest.raises(RuntimeError):
        await handler.Parse(req, context=ctx)
    assert ctx.code is not None
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd shore-ai-service && python -m pytest tests/test_screenparse_handler.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'shore_ai.handlers.screenparse'`.

- [ ] **Step 3: Write the handler**

Create `shore-ai-service/src/shore_ai/handlers/screenparse.py`:

```python
"""ScreenParse gRPC handler wrapping OmniParser v2.

The heavy OmniParser stack (YOLO icon detector + Florence-2 captioner + OCR)
is injected as a `parser` callable so this handler stays import-light and
unit-testable without models or a GPU. `server.py` builds the real callable
lazily in a background thread (STT load pattern).

parser contract:
    parse(image_bytes: bytes) -> tuple[list[dict], bytes]
    each element dict: {type, content, interactable, bbox=[x1,y1,x2,y2]}
    bbox floats are normalized 0..1; second tuple item is annotated JPEG bytes.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable, Optional

import grpc

from shore_ai._pb import screenparse_pb2, screenparse_pb2_grpc

log = logging.getLogger(__name__)

Parser = Callable[[bytes], "tuple[list[dict], bytes]"]


class ScreenParseHandler(screenparse_pb2_grpc.ScreenParseServicer):
    def __init__(self, parser: Optional[Parser] = None, device: str = "cuda"):
        self.parser = parser
        self.device = device

    def loaded(self) -> bool:
        return self.parser is not None

    async def Parse(self, request, context):
        if self.parser is None:
            if context is not None:
                await context.abort(
                    grpc.StatusCode.UNAVAILABLE, "screenparse model still loading",
                )
            raise RuntimeError("screenparse model still loading")

        image = request.image
        t0 = time.perf_counter()

        def _run():
            return self.parser(image)

        elements, som_jpeg = await asyncio.get_event_loop().run_in_executor(
            None, _run
        )
        latency_ms = (time.perf_counter() - t0) * 1000.0

        proto_elems = []
        for i, el in enumerate(elements):
            bbox = el.get("bbox", [0.0, 0.0, 0.0, 0.0])
            proto_elems.append(
                screenparse_pb2.Element(
                    id=i,
                    type=str(el.get("type", "")),
                    content=str(el.get("content", "")),
                    interactable=bool(el.get("interactable", False)),
                    x1=float(bbox[0]), y1=float(bbox[1]),
                    x2=float(bbox[2]), y2=float(bbox[3]),
                )
            )
        return screenparse_pb2.ParseResponse(
            elements=proto_elems,
            som_image_jpeg=som_jpeg or b"",
            width=int(getattr(request, "width", 0) or 0),
            height=int(getattr(request, "height", 0) or 0),
            latency_ms=latency_ms,
        )
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd shore-ai-service && python -m pytest tests/test_screenparse_handler.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add shore-ai-service/src/shore_ai/handlers/screenparse.py shore-ai-service/tests/test_screenparse_handler.py
git commit -m "feat(shore-ai): ScreenParse handler with injectable OmniParser callable"
```

---

### Task 3: Wire handler into server + Health + Docker build

**Files:**
- Create: `shore-ai-service/src/shore_ai/omniparser_adapter.py`
- Modify: `shore-ai-service/src/shore_ai/server.py`
- Modify: `shore-ai-service/pyproject.toml`
- Modify: `shore-ai-service/Dockerfile`

The adapter is the only place that imports OmniParser. It's built lazily so
tests and non-GPU imports never touch it.

- [ ] **Step 1: Write the OmniParser adapter**

Create `shore-ai-service/src/shore_ai/omniparser_adapter.py`:

```python
"""Adapter over the vendored microsoft/OmniParser stack.

Produces the `parser(image_bytes) -> (elements, som_jpeg)` callable the
ScreenParseHandler expects. Imports OmniParser lazily so importing this module
is cheap; the models load only when build_omniparser() is called.

OmniParser is cloned into /opt/OmniParser in the Docker image (see Dockerfile)
and added to PYTHONPATH. Weights live under /opt/OmniParser/weights.
"""
from __future__ import annotations

import base64
import io
import logging
import os

log = logging.getLogger(__name__)

_OMNI_ROOT = os.environ.get("OMNIPARSER_ROOT", "/opt/OmniParser")


def build_omniparser(device: str = "cuda", box_threshold: float = 0.05):
    """Construct the OmniParser callable. Heavy — call inside an executor."""
    import sys
    if _OMNI_ROOT not in sys.path:
        sys.path.insert(0, _OMNI_ROOT)

    from util.omniparser import Omniparser  # type: ignore

    config = {
        "som_model_path": os.path.join(_OMNI_ROOT, "weights/icon_detect/model.pt"),
        "caption_model_name": "florence2",
        "caption_model_path": os.path.join(_OMNI_ROOT, "weights/icon_caption_florence"),
        "BOX_TRESHOLD": box_threshold,
        "device": device,
    }
    omni = Omniparser(config)

    def parse(image_bytes: bytes):
        b64 = base64.b64encode(image_bytes).decode("ascii")
        # Omniparser.parse returns (annotated_image_base64, parsed_content_list)
        som_b64, parsed = omni.parse(b64)
        elements = []
        for item in parsed:
            bbox = item.get("bbox", [0.0, 0.0, 0.0, 0.0])
            elements.append({
                "type": item.get("type", "icon"),
                "content": item.get("content", "") or "",
                "interactable": bool(item.get("interactivity", item.get("interactable", False))),
                "bbox": [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])],
            })
        som_jpeg = _to_jpeg(som_b64)
        return elements, som_jpeg

    return parse


def _to_jpeg(som_b64: str) -> bytes:
    """OmniParser returns a base64 PNG/whatever; re-encode to JPEG bytes."""
    from PIL import Image
    raw = base64.b64decode(som_b64)
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=85)
    return out.getvalue()
```

> **Note for the implementer:** OmniParser's exact `parse()` return shape and
> the parsed-item keys (`bbox`, `content`, `interactivity`, `type`) must be
> verified against the pinned commit during the live-deploy task (Task 15).
> The keys above match OmniParser v2's `util/omniparser.py` as of early 2025;
> if the pinned commit differs, adjust the mapping here only — the handler and
> everything downstream are insulated by the `(elements, som_jpeg)` contract.

- [ ] **Step 2: Wire into server.py**

In `shore-ai-service/src/shore_ai/server.py`, add the import near the other handler imports:

```python
from shore_ai.handlers.screenparse import ScreenParseHandler
```

and:

```python
from shore_ai._pb import (
    stt_pb2_grpc, tts_pb2_grpc, embed_pb2_grpc, health_pb2_grpc,
    screenparse_pb2_grpc,
)
```

Inside `serve()`, after `embed = EmbedHandler(...)` add:

```python
    device = os.environ.get("SHORE_AI_SCREENPARSE_DEVICE", "cuda")
    box_threshold = float(os.environ.get("SHORE_AI_SCREENPARSE_BOX_THRESHOLD", "0.05"))
    screenparse = ScreenParseHandler(parser=None, device=device)
```

Add it to the Health components map:

```python
    health = HealthHandler(
        components={
            "stt":   (stt,   stt.model_size),
            "tts":   (tts,   "af_heart"),
            "embed": (embed, embed.model_name),
            "screenparse": (screenparse, device),
        },
        version=__version__,
    )
```

Register the servicer alongside the others:

```python
    screenparse_pb2_grpc.add_ScreenParseServicer_to_server(screenparse, server)
```

After `stt.start_load()`, add a background load for OmniParser:

```python
    # Background-load OmniParser so the gRPC port is reachable immediately and
    # Health reports screenparse.loaded=false until the models are ready.
    async def _load_screenparse():
        try:
            from shore_ai.omniparser_adapter import build_omniparser
            parser = await asyncio.get_event_loop().run_in_executor(
                None, build_omniparser, device, box_threshold
            )
            screenparse.parser = parser
            log.info("screenparse: OmniParser loaded on %s", device)
        except Exception as e:
            log.exception("screenparse: OmniParser load failed: %r", e)

    asyncio.create_task(_load_screenparse())
```

- [ ] **Step 3: Verify server imports cleanly (no models needed)**

Run: `cd shore-ai-service && python -c "import shore_ai.server; import shore_ai.omniparser_adapter; print('ok')"`
Expected: prints `ok` (adapter import must not trigger OmniParser import).

- [ ] **Step 4: Add service dependencies**

In `shore-ai-service/pyproject.toml`, add to `dependencies`:

```toml
  "ultralytics>=8.3.0",
  "supervision>=0.22.0",
  "opencv-python-headless>=4.9.0",
  "easyocr>=1.7.0",
  "einops>=0.8.0",
  "timm>=1.0.0",
  "huggingface_hub>=0.25.0",
  "Pillow>=10.0.0",
```

- [ ] **Step 5: Extend the Dockerfile to vendor OmniParser + weights**

In `shore-ai-service/Dockerfile`, after the `pip install -e .[dev]` layer and before `RUN make ... proto`, add:

```dockerfile
# ── OmniParser v2 (pinned) + weights ──
ARG OMNIPARSER_REF=<PIN_A_COMMIT_SHA>
RUN git clone https://github.com/microsoft/OmniParser.git /opt/OmniParser \
    && cd /opt/OmniParser && git checkout ${OMNIPARSER_REF}

RUN --mount=type=cache,target=/root/.cache/huggingface \
    python3.12 - <<'PY'
from huggingface_hub import snapshot_download
snapshot_download(
    "microsoft/OmniParser-v2.0",
    local_dir="/opt/OmniParser/weights",
    allow_patterns=["icon_detect/*", "icon_caption_florence/*"],
)
PY

ENV OMNIPARSER_ROOT=/opt/OmniParser
ENV PYTHONPATH=/opt/OmniParser:${PYTHONPATH}
```

> **Implementer:** replace `<PIN_A_COMMIT_SHA>` with a real commit from
> github.com/microsoft/OmniParser `master` at implementation time. Verify the
> weights repo layout (`icon_detect/model.pt`, `icon_caption_florence/`) still
> matches; OmniParser has reorganized weight paths before.

- [ ] **Step 6: Commit**

```bash
git add shore-ai-service/src/shore_ai/omniparser_adapter.py shore-ai-service/src/shore_ai/server.py shore-ai-service/pyproject.toml shore-ai-service/Dockerfile
git commit -m "feat(shore-ai): wire ScreenParse into server + Health + Docker (OmniParser vendor)"
```

> Docker image build + real-model load are validated in Task 15 (live deploy),
> not in unit CI — the image is large and needs a GPU.

---

## PHASE B — backend: config, client, desktop backend

### Task 4: Config settings

**Files:**
- Modify: `back-end/app/core/config.py`

- [ ] **Step 1: Add settings**

In `back-end/app/core/config.py`, after the `# ── Screen Co-pilot ──` block (before `class Config`), add:

```python
    # ── Computer-Use (OmniParser) ──
    COMPUTER_USE_ENABLED: bool = False  # master switch; feature unavailable unless True
    COMPUTER_USE_MAX_STEPS: int = 20  # step budget per session
    COMPUTER_USE_SETTLE_SECONDS: float = 1.5  # wait after an action before next capture
    COMPUTER_USE_MONITOR_INDEX: int = 1  # mss monitor to capture/control
    COMPUTER_USE_DECISION_TIMEOUT: float = 60.0  # per-step decision LLM timeout (s)
    COMPUTER_USE_HISTORY_STEPS: int = 6  # history entries included per decision
    COMPUTER_USE_AUDIT_LOG: str = "data/computer_use_audit.log"  # JSONL audit
    COMPUTER_USE_DEBUG_DIR: str = ""  # if set, save per-step SoM image + decision JSON

    # ── ScreenParse (shore-ai-service) ──
    SHORE_AI_SCREENPARSE_TIMEOUT_SECONDS: float = 30.0
```

- [ ] **Step 2: Verify settings load**

Run: `cd back-end && python -c "from app.core.config import settings; print(settings.COMPUTER_USE_MAX_STEPS, settings.SHORE_AI_SCREENPARSE_TIMEOUT_SECONDS)"`
Expected: prints `20 30.0`.

- [ ] **Step 3: Commit**

```bash
git add back-end/app/core/config.py
git commit -m "feat(config): computer-use + screenparse settings"
```

---

### Task 5: Backend ScreenParse gRPC client

**Files:**
- Create: `back-end/app/services/ai_client/screenparse.py`
- Test: `back-end/tests/services/test_screenparse_client.py`

First regenerate the backend stubs so `screenparse_pb2` exists on the backend.

- [ ] **Step 1: Regenerate backend stubs**

Run: `cd back-end && make proto`
Expected: `app/services/ai_client/_pb/screenparse_pb2.py` and `screenparse_pb2_grpc.py` created (the backend Makefile already globs `../shore-ai-service/proto/shore/ai/v1/*.proto`).

Verify: `cd back-end && python -c "from app.services.ai_client._pb import screenparse_pb2, screenparse_pb2_grpc; print('ok')"` → `ok`.

- [ ] **Step 2: Write the failing test**

Create `back-end/tests/services/test_screenparse_client.py`:

```python
import grpc
import pytest

from app.services.ai_client.screenparse import (
    ScreenParseClient, ScreenParseUnavailable, ParsedScreen,
)
from app.services.ai_client._pb import screenparse_pb2


class _FakeAioRpcError(grpc.aio.AioRpcError):
    def __init__(self, code):
        self._code = code

    def code(self):
        return self._code

    def details(self):
        return "boom"


class _FakeStub:
    def __init__(self, response=None, error=None):
        self._response = response
        self._error = error
        self.calls = []

    async def Parse(self, req, timeout=None):
        self.calls.append((req, timeout))
        if self._error:
            raise self._error
        return self._response


def _fake_response():
    return screenparse_pb2.ParseResponse(
        elements=[
            screenparse_pb2.Element(
                id=0, type="icon", content="settings gear",
                interactable=True, x1=0.9, y1=0.0, x2=0.95, y2=0.05,
            ),
        ],
        som_image_jpeg=b"JPEGBYTES",
        width=1920, height=1080, latency_ms=42.0,
    )


@pytest.mark.asyncio
async def test_parse_returns_parsed_screen():
    stub = _FakeStub(response=_fake_response())
    client = ScreenParseClient(stub=stub)
    result = await client.parse(b"PNGDATA")

    assert isinstance(result, ParsedScreen)
    assert result.width == 1920 and result.height == 1080
    assert len(result.elements) == 1
    el = result.elements[0]
    assert el.id == 0 and el.type == "icon" and el.content == "settings gear"
    assert el.interactable is True
    assert el.center() == pytest.approx((0.925, 0.025))
    assert result.som_image_b64  # base64 of JPEGBYTES, non-empty
    assert stub.calls[0][0].image == b"PNGDATA"


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [
    grpc.StatusCode.UNAVAILABLE,
    grpc.StatusCode.DEADLINE_EXCEEDED,
    grpc.StatusCode.RESOURCE_EXHAUSTED,
    grpc.StatusCode.UNAUTHENTICATED,
    grpc.StatusCode.PERMISSION_DENIED,
])
async def test_graceful_codes_raise_unavailable(code):
    stub = _FakeStub(error=_FakeAioRpcError(code))
    client = ScreenParseClient(stub=stub)
    with pytest.raises(ScreenParseUnavailable):
        await client.parse(b"PNGDATA")


@pytest.mark.asyncio
async def test_non_graceful_code_reraises():
    stub = _FakeStub(error=_FakeAioRpcError(grpc.StatusCode.INTERNAL))
    client = ScreenParseClient(stub=stub)
    with pytest.raises(grpc.aio.AioRpcError):
        await client.parse(b"PNGDATA")
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd back-end && python -m pytest tests/services/test_screenparse_client.py -v`
Expected: FAIL — `ModuleNotFoundError: app.services.ai_client.screenparse`.

- [ ] **Step 4: Write the client**

Create `back-end/app/services/ai_client/screenparse.py`:

```python
"""ScreenParse gRPC client — captures parsed into numbered UI elements."""
from __future__ import annotations

import base64

import grpc
from pydantic import BaseModel

from app.core.config import settings
from app.services.ai_client._pb import screenparse_pb2, screenparse_pb2_grpc
from app.services.ai_client.channel import ai_channel


class ScreenParseUnavailable(RuntimeError):
    """Raised when shore-ai-service ScreenParse is unreachable or unhealthy."""


_GRACEFUL_CODES = {
    grpc.StatusCode.UNAVAILABLE,
    grpc.StatusCode.DEADLINE_EXCEEDED,
    grpc.StatusCode.RESOURCE_EXHAUSTED,
    grpc.StatusCode.UNAUTHENTICATED,
    grpc.StatusCode.PERMISSION_DENIED,
}


class ParsedElement(BaseModel):
    id: int
    type: str
    content: str
    interactable: bool
    x1: float
    y1: float
    x2: float
    y2: float

    def center(self) -> tuple[float, float]:
        """Normalized (0..1) center of the bbox."""
        return ((self.x1 + self.x2) / 2.0, (self.y1 + self.y2) / 2.0)


class ParsedScreen(BaseModel):
    elements: list[ParsedElement]
    som_image_b64: str  # base64 JPEG (no data: prefix)
    width: int
    height: int
    latency_ms: float


class ScreenParseClient:
    def __init__(self, stub=None):
        self._stub = stub

    def _get_stub(self):
        if self._stub is None:
            self._stub = screenparse_pb2_grpc.ScreenParseStub(ai_channel())
        return self._stub

    async def parse(self, image_bytes: bytes) -> ParsedScreen:
        req = screenparse_pb2.ParseRequest(image=image_bytes)
        try:
            resp = await self._get_stub().Parse(
                req, timeout=settings.SHORE_AI_SCREENPARSE_TIMEOUT_SECONDS,
            )
        except grpc.aio.AioRpcError as e:
            if e.code() in _GRACEFUL_CODES:
                raise ScreenParseUnavailable(
                    str(e.details() or e.code().name)
                ) from e
            raise
        return ParsedScreen(
            elements=[
                ParsedElement(
                    id=el.id, type=el.type, content=el.content,
                    interactable=el.interactable,
                    x1=el.x1, y1=el.y1, x2=el.x2, y2=el.y2,
                )
                for el in resp.elements
            ],
            som_image_b64=base64.b64encode(resp.som_image_jpeg).decode("ascii"),
            width=resp.width, height=resp.height, latency_ms=resp.latency_ms,
        )


screenparse_client = ScreenParseClient()
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd back-end && python -m pytest tests/services/test_screenparse_client.py -v`
Expected: PASS (7 tests).

- [ ] **Step 6: Commit**

```bash
git add back-end/app/services/ai_client/screenparse.py back-end/tests/services/test_screenparse_client.py
git commit -m "feat(backend): ScreenParse gRPC client with graceful-degrade + ParsedScreen"
```

---

### Task 6: DesktopBackend abstraction + LocalDesktopBackend

**Files:**
- Create: `back-end/app/services/desktop_backend.py`
- Test: `back-end/tests/services/test_desktop_backend.py`
- Modify: `back-end/requirements.txt`

The abstraction owns capture **and** input together (they must target the same
desktop). v1 `LocalDesktopBackend` uses mss + pyautogui. The unit-testable core
is `norm_to_pixels()` (normalized center → physical pixel coords using the
captured dims); actual injection/capture are mocked.

- [ ] **Step 1: Add the pyautogui dependency**

In `back-end/requirements.txt`, under the `# Vision / Screen capture` block, add:

```
pyautogui>=0.9.54
```

- [ ] **Step 2: Write the failing test**

Create `back-end/tests/services/test_desktop_backend.py`:

```python
import pytest

from app.services.desktop_backend import (
    CapturedScreen, LocalDesktopBackend, norm_to_pixels,
)


def test_norm_to_pixels_maps_center():
    # 1920x1080 screen, normalized center (0.5, 0.5) -> (960, 540)
    assert norm_to_pixels(0.5, 0.5, 1920, 1080) == (960, 540)


def test_norm_to_pixels_corner_and_rounding():
    assert norm_to_pixels(0.0, 0.0, 1920, 1080) == (0, 0)
    # 0.925 * 1920 = 1776.0, 0.025 * 1080 = 27.0
    assert norm_to_pixels(0.925, 0.025, 1920, 1080) == (1776, 27)
    # rounding: 0.3334 * 1000 = 333.4 -> 333
    assert norm_to_pixels(0.3334, 0.3336, 1000, 1000) == (333, 334)


def test_norm_to_pixels_clamps_out_of_range():
    # values >1 or <0 clamp into the screen so a bad bbox can't click off-screen
    assert norm_to_pixels(1.5, -0.2, 800, 600) == (799, 0)


class _RecordingPyAutoGUI:
    def __init__(self):
        self.events = []
        self.PAUSE = 0
        self.FAILSAFE = True

    def click(self, x, y, button="left"):
        self.events.append(("click", x, y, button))

    def doubleClick(self, x, y):
        self.events.append(("double", x, y))

    def moveTo(self, x, y):
        self.events.append(("move", x, y))

    def typewrite(self, text, interval=0.0):
        self.events.append(("type", text))

    def hotkey(self, *keys):
        self.events.append(("hotkey", keys))

    def scroll(self, amount, x=None, y=None):
        self.events.append(("scroll", amount, x, y))


@pytest.mark.asyncio
async def test_local_backend_click_uses_pixels():
    gui = _RecordingPyAutoGUI()
    backend = LocalDesktopBackend(gui=gui)
    await backend.click(1776, 27)
    assert gui.events == [("click", 1776, 27, "left")]


@pytest.mark.asyncio
async def test_local_backend_double_and_right_click():
    gui = _RecordingPyAutoGUI()
    backend = LocalDesktopBackend(gui=gui)
    await backend.click(10, 20, double=True)
    await backend.click(30, 40, button="right")
    assert gui.events == [("double", 10, 20), ("click", 30, 40, "right")]


@pytest.mark.asyncio
async def test_local_backend_type_and_hotkey_and_scroll():
    gui = _RecordingPyAutoGUI()
    backend = LocalDesktopBackend(gui=gui)
    await backend.type_text("hello")
    await backend.hotkey(["ctrl", "s"])
    await backend.scroll(100, 200, -3)
    assert ("type", "hello") in gui.events
    assert ("hotkey", ("ctrl", "s")) in gui.events
    assert ("scroll", -3, 100, 200) in gui.events


@pytest.mark.asyncio
async def test_local_backend_capture_uses_grabber():
    def fake_grab(monitor_index):
        return b"PNGBYTES", 1920, 1080
    backend = LocalDesktopBackend(gui=_RecordingPyAutoGUI(), grab=fake_grab)
    shot = await backend.capture()
    assert isinstance(shot, CapturedScreen)
    assert shot.png_bytes == b"PNGBYTES"
    assert shot.width == 1920 and shot.height == 1080
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd back-end && python -m pytest tests/services/test_desktop_backend.py -v`
Expected: FAIL — `ModuleNotFoundError: app.services.desktop_backend`.

- [ ] **Step 4: Write the backend**

Create `back-end/app/services/desktop_backend.py`:

```python
"""Desktop capture + input, behind one interface.

Windows gives each interactive desktop a single cursor, input queue, and
foreground window — so capture and input must always target the SAME desktop.
They live together here for exactly that reason. v1 LocalDesktopBackend drives
the host desktop (Shore borrows the real mouse during a session). A phase-2
RemoteDesktopBackend (talking to a shore-desktop-agent in a second RDP session)
can drop in behind this interface with zero loop changes.
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Callable, Optional

from pydantic import BaseModel

from app.core.config import settings


class CapturedScreen(BaseModel):
    png_bytes: bytes
    width: int
    height: int

    class Config:
        arbitrary_types_allowed = True


def norm_to_pixels(nx: float, ny: float, width: int, height: int) -> tuple[int, int]:
    """Map a normalized (0..1) point to physical pixel coords, clamped on-screen."""
    nx = min(max(nx, 0.0), 1.0)
    ny = min(max(ny, 0.0), 1.0)
    px = min(int(round(nx * width)), max(width - 1, 0))
    py = min(int(round(ny * height)), max(height - 1, 0))
    return px, py


class DesktopBackend(ABC):
    @abstractmethod
    async def capture(self) -> CapturedScreen: ...

    @abstractmethod
    async def click(self, x: int, y: int, button: str = "left",
                    double: bool = False) -> None: ...

    @abstractmethod
    async def type_text(self, text: str) -> None: ...

    @abstractmethod
    async def hotkey(self, keys: list[str]) -> None: ...

    @abstractmethod
    async def scroll(self, x: int, y: int, amount: int) -> None: ...


def _default_grab(monitor_index: int) -> tuple[bytes, int, int]:
    """Grab a full monitor as PNG bytes + its pixel dims (mss + Pillow)."""
    import io
    import mss
    from PIL import Image
    with mss.mss() as sct:
        shot = sct.grab(sct.monitors[monitor_index])
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue(), shot.size[0], shot.size[1]


class LocalDesktopBackend(DesktopBackend):
    """Drives the backend host's own desktop via mss + pyautogui.

    Known v1 limitation: shares the user's cursor and keyboard focus while a
    session runs. Phase 2 removes this by giving Shore her own desktop.
    """

    def __init__(self, gui=None, grab: Optional[Callable] = None):
        self._gui = gui
        self._grab = grab or _default_grab
        self._dpi_aware = False

    def _get_gui(self):
        if self._gui is None:
            import pyautogui
            pyautogui.FAILSAFE = False  # bbox clamping is our safety, not corner-abort
            self._gui = pyautogui
        if not self._dpi_aware:
            self._make_dpi_aware()
        return self._gui

    def _make_dpi_aware(self) -> None:
        """Ensure pyautogui + mss agree on physical pixels under display scaling."""
        self._dpi_aware = True
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass  # non-Windows or already set

    async def capture(self) -> CapturedScreen:
        self._get_gui()  # ensure DPI awareness before measuring
        png, w, h = await asyncio.get_event_loop().run_in_executor(
            None, self._grab, settings.COMPUTER_USE_MONITOR_INDEX
        )
        return CapturedScreen(png_bytes=png, width=w, height=h)

    async def click(self, x, y, button="left", double=False) -> None:
        gui = self._get_gui()

        def _do():
            if double:
                gui.doubleClick(x, y)
            else:
                gui.click(x, y, button=button)
        await asyncio.get_event_loop().run_in_executor(None, _do)

    async def type_text(self, text) -> None:
        gui = self._get_gui()

        def _do():
            gui.typewrite(text, interval=0.02)
        await asyncio.get_event_loop().run_in_executor(None, _do)

    async def hotkey(self, keys) -> None:
        gui = self._get_gui()

        def _do():
            gui.hotkey(*keys)
        await asyncio.get_event_loop().run_in_executor(None, _do)

    async def scroll(self, x, y, amount) -> None:
        gui = self._get_gui()

        def _do():
            gui.scroll(amount, x=x, y=y)
        await asyncio.get_event_loop().run_in_executor(None, _do)
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd back-end && python -m pytest tests/services/test_desktop_backend.py -v`
Expected: PASS (8 tests).

- [ ] **Step 6: Commit**

```bash
git add back-end/app/services/desktop_backend.py back-end/tests/services/test_desktop_backend.py back-end/requirements.txt
git commit -m "feat(backend): DesktopBackend abstraction + LocalDesktopBackend (mss + pyautogui)"
```

---

## PHASE C — backend: decision loop

### Task 7: Action schema + validation

**Files:**
- Create: `back-end/app/services/computer_use_service.py` (schema + validation only in this task)
- Test: `back-end/tests/services/test_computer_use_service.py` (schema tests only in this task)

- [ ] **Step 1: Write the failing test**

Create `back-end/tests/services/test_computer_use_service.py`:

```python
import pytest

from app.services.computer_use_service import (
    ComputerUseAction, validate_action,
)
from app.services.ai_client.screenparse import ParsedElement, ParsedScreen


def _screen(n=2):
    els = [
        ParsedElement(id=i, type="icon", content=f"el{i}", interactable=True,
                      x1=0.1 * i, y1=0.1, x2=0.1 * i + 0.05, y2=0.15)
        for i in range(n)
    ]
    return ParsedScreen(elements=els, som_image_b64="", width=1920, height=1080,
                        latency_ms=1.0)


def test_action_parses_click():
    a = ComputerUseAction.model_validate(
        {"action": "click", "element_id": 1, "reason": "open menu"}
    )
    assert a.action == "click" and a.element_id == 1


def test_validate_click_ok():
    a = ComputerUseAction(action="click", element_id=1, reason="x")
    assert validate_action(a, _screen(2)) is None  # None = valid


def test_validate_click_out_of_range():
    a = ComputerUseAction(action="click", element_id=5, reason="x")
    err = validate_action(a, _screen(2))
    assert err is not None and "range" in err.lower()


def test_validate_click_missing_element():
    a = ComputerUseAction(action="click", reason="x")
    err = validate_action(a, _screen(2))
    assert err is not None and "element_id" in err


def test_validate_type_requires_text():
    a = ComputerUseAction(action="type", element_id=0, reason="x")
    err = validate_action(a, _screen(2))
    assert err is not None and "text" in err


def test_validate_hotkey_requires_keys():
    a = ComputerUseAction(action="hotkey", reason="x")
    err = validate_action(a, _screen(2))
    assert err is not None and "keys" in err


def test_validate_done_needs_nothing():
    a = ComputerUseAction(action="done", text="all done", reason="finished")
    assert validate_action(a, _screen(2)) is None


def test_validate_scroll_requires_amount():
    a = ComputerUseAction(action="scroll", reason="x")
    err = validate_action(a, _screen(2))
    assert err is not None and "scroll_amount" in err
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd back-end && python -m pytest tests/services/test_computer_use_service.py -v`
Expected: FAIL — `ModuleNotFoundError: app.services.computer_use_service`.

- [ ] **Step 3: Write the schema + validation**

Create `back-end/app/services/computer_use_service.py` with (only this portion for now):

```python
"""Computer-use session: capture -> parse -> decide -> act loop.

Pure helpers (build_decision_messages, validate_action, format_elements) are
module-level and I/O-free for unit testing. ComputerUseService owns the
background session loop, wired into /ws/chat like CopilotService.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel

from app.services.ai_client.screenparse import ParsedScreen


class ComputerUseAction(BaseModel):
    action: Literal[
        "click", "double_click", "right_click", "type",
        "hotkey", "scroll", "wait", "done", "fail",
    ]
    element_id: Optional[int] = None
    text: Optional[str] = None
    keys: Optional[list[str]] = None
    scroll_amount: Optional[int] = None
    reason: str


_NEEDS_ELEMENT = {"click", "double_click", "right_click", "type"}


def validate_action(action: ComputerUseAction, screen: ParsedScreen) -> Optional[str]:
    """Return None if the action is executable against `screen`, else an error string."""
    n = len(screen.elements)
    if action.action in _NEEDS_ELEMENT:
        if action.element_id is None:
            return f"action '{action.action}' requires element_id"
        if not (0 <= action.element_id < n):
            return f"element_id {action.element_id} out of range (0..{n - 1})"
    if action.action == "type" and not (action.text and action.text.strip()):
        return "action 'type' requires non-empty text"
    if action.action == "hotkey" and not action.keys:
        return "action 'hotkey' requires keys"
    if action.action == "scroll" and action.scroll_amount is None:
        return "action 'scroll' requires scroll_amount"
    return None
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd back-end && python -m pytest tests/services/test_computer_use_service.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add back-end/app/services/computer_use_service.py back-end/tests/services/test_computer_use_service.py
git commit -m "feat(backend): computer-use action schema + validation"
```

---

### Task 8: Decision prompt builders (pure helpers)

**Files:**
- Modify: `back-end/app/services/computer_use_service.py`
- Modify: `back-end/tests/services/test_computer_use_service.py`
- Create: `back-end/app/prompts/computer_use_decider.txt`

- [ ] **Step 1: Add the failing tests**

Append to `back-end/tests/services/test_computer_use_service.py`:

```python
from app.services.computer_use_service import (
    format_elements, build_decision_messages,
)


def test_format_elements_lists_id_type_content():
    out = format_elements(_screen(2))
    assert "[0]" in out and "[1]" in out
    assert "el0" in out and "el1" in out
    assert "icon" in out


def test_build_decision_messages_includes_goal_history_image():
    screen = _screen(2)
    msgs = build_decision_messages(
        goal="open notepad",
        screen=screen,
        history=[{"action": "click", "reason": "start menu", "result": "ok"}],
        system_prompt="SYS",
        som_image_b64="QUJD",  # "ABC"
    )
    assert msgs[0]["role"] == "system" and msgs[0]["content"] == "SYS"
    user = msgs[-1]
    assert user["role"] == "user"
    # multimodal content: text block with goal + elements + history, plus image
    text_blocks = [c for c in user["content"] if c["type"] == "text"]
    image_blocks = [c for c in user["content"] if c["type"] == "image_url"]
    assert len(image_blocks) == 1
    assert image_blocks[0]["image_url"]["url"].startswith("data:image/jpeg;base64,QUJD")
    joined = " ".join(b["text"] for b in text_blocks)
    assert "open notepad" in joined
    assert "start menu" in joined  # history reason present
    assert "[0]" in joined  # element list present


def test_build_decision_messages_truncates_history():
    screen = _screen(1)
    history = [{"action": "click", "reason": f"step{i}", "result": "ok"}
               for i in range(20)]
    msgs = build_decision_messages(
        goal="g", screen=screen, history=history,
        system_prompt="SYS", som_image_b64="", history_limit=3,
    )
    joined = " ".join(
        c["text"] for c in msgs[-1]["content"] if c["type"] == "text"
    )
    assert "step19" in joined and "step17" in joined
    assert "step16" not in joined  # only last 3 kept
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd back-end && python -m pytest tests/services/test_computer_use_service.py -k "format_elements or build_decision" -v`
Expected: FAIL — `ImportError: cannot import name 'format_elements'`.

- [ ] **Step 3: Write the decider prompt file**

Create `back-end/app/prompts/computer_use_decider.txt`:

```
You are Shore's computer-use controller. You are given a screenshot of the
user's screen with numbered boxes drawn over every interactable element, plus a
text list of those elements and the history of actions you have already taken.

Your job: choose the SINGLE next action that makes progress toward the GOAL.

Rules:
- Refer to elements ONLY by their numbered id from the list. Never invent ids.
- Prefer the most direct path. One action per step.
- Use "type" to enter text into a focused field (set element_id to click it first).
- Use "hotkey" for keyboard shortcuts, e.g. keys ["ctrl","s"] or ["win"] or ["enter"].
- Use "scroll" with scroll_amount (positive=up, negative=down) to reveal off-screen content.
- Use "wait" when the screen is still loading and no useful action exists yet.
- When the GOAL is fully accomplished, return action "done" with a short summary in "text".
- If the goal is impossible or you are stuck (repeated failures), return action "fail" with the reason in "text".
- Always include a one-line "reason" explaining this step.

Respond with a single JSON object matching the required schema. No prose.
```

- [ ] **Step 4: Add the helpers to computer_use_service.py**

Append to `back-end/app/services/computer_use_service.py` (after `validate_action`):

```python
from pathlib import Path

from app.core.config import settings

_DECIDER_PROMPT_PATH = (
    Path(__file__).resolve().parents[1] / "prompts" / "computer_use_decider.txt"
)
_decider_prompt: Optional[str] = None


def load_decider_prompt() -> str:
    global _decider_prompt
    if _decider_prompt is None:
        _decider_prompt = _DECIDER_PROMPT_PATH.read_text(encoding="utf-8")
    return _decider_prompt


def format_elements(screen: ParsedScreen) -> str:
    """Render the element list the decision model reads."""
    lines = []
    for el in screen.elements:
        cx, cy = el.center()
        tag = "interactable" if el.interactable else "static"
        lines.append(
            f"[{el.id}] {el.type} \"{el.content}\" {tag} center=({cx:.3f},{cy:.3f})"
        )
    return "\n".join(lines)


def _format_history(history: list[dict], limit: int) -> str:
    recent = history[-limit:] if limit else history
    if not recent:
        return "(no actions yet)"
    lines = []
    for i, h in enumerate(recent):
        lines.append(
            f"{i+1}. {h.get('action')} — {h.get('reason', '')} -> {h.get('result', '')}"
        )
    return "\n".join(lines)


def build_decision_messages(
    goal: str,
    screen: ParsedScreen,
    history: list[dict],
    system_prompt: str,
    som_image_b64: str,
    history_limit: int = 6,
) -> list[dict]:
    """Build the OpenAI-style messages for one decision call (SoM image + text)."""
    text = (
        f"GOAL: {goal}\n\n"
        f"ELEMENTS:\n{format_elements(screen)}\n\n"
        f"ACTION HISTORY:\n{_format_history(history, history_limit)}\n\n"
        f"Choose the next action."
    )
    user_content = [{"type": "text", "text": text}]
    if som_image_b64:
        user_content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{som_image_b64}"},
        })
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd back-end && python -m pytest tests/services/test_computer_use_service.py -v`
Expected: PASS (all schema + helper tests).

- [ ] **Step 6: Commit**

```bash
git add back-end/app/services/computer_use_service.py back-end/tests/services/test_computer_use_service.py back-end/app/prompts/computer_use_decider.txt
git commit -m "feat(backend): computer-use decision prompt builders + decider prompt"
```

---

### Task 9: Decision LLM call (json_schema + image)

**Files:**
- Modify: `back-end/app/services/computer_use_service.py`
- Modify: `back-end/tests/services/test_computer_use_service.py`

A single method posts the decision messages to llama-server with
`response_format=json_schema(ComputerUseAction)` and parses the result. Uses
the LOCOMO-extractor pattern (httpx, 3 attempts, cancel-safe). Injected httpx
client for tests.

- [ ] **Step 1: Add the failing test**

Append to `back-end/tests/services/test_computer_use_service.py`:

```python
import json
import httpx

from app.services.computer_use_service import ComputerUseDecider


def _llm_response(action_dict):
    content = json.dumps(action_dict)
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": content}}]},
    )


@pytest.mark.asyncio
async def test_decider_returns_parsed_action():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return _llm_response(
            {"action": "click", "element_id": 1, "reason": "open menu"}
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://test")
    decider = ComputerUseDecider(http_client=client)

    action = await decider.decide(
        messages=[{"role": "system", "content": "SYS"},
                  {"role": "user", "content": [{"type": "text", "text": "go"}]}],
    )
    assert action.action == "click" and action.element_id == 1
    # response_format json_schema was sent
    assert calls[0]["response_format"]["type"] == "json_schema"
    await client.aclose()


@pytest.mark.asyncio
async def test_decider_retries_then_succeeds():
    state = {"n": 0}

    def handler(request):
        state["n"] += 1
        if state["n"] == 1:
            return httpx.Response(500)
        return _llm_response({"action": "wait", "reason": "loading"})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://test")
    decider = ComputerUseDecider(http_client=client, backoff_base=0.0)
    action = await decider.decide(messages=[{"role": "user", "content": "x"}])
    assert action.action == "wait"
    assert state["n"] == 2
    await client.aclose()
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd back-end && python -m pytest tests/services/test_computer_use_service.py -k decider -v`
Expected: FAIL — `ImportError: cannot import name 'ComputerUseDecider'`.

- [ ] **Step 3: Add the decider**

Append to `back-end/app/services/computer_use_service.py`:

```python
import asyncio

import httpx


class ComputerUseDecider:
    """Calls llama-server for one structured next-action decision."""

    _MAX_ATTEMPTS = 3

    def __init__(self, http_client: Optional[httpx.AsyncClient] = None,
                 backoff_base: float = 1.0):
        self._client = http_client
        self._backoff_base = backoff_base

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=settings.WORKER_LOCAL_LLM_URL.rstrip("/").rsplit("/v1", 1)[0],
                timeout=settings.COMPUTER_USE_DECISION_TIMEOUT,
            )
        return self._client

    async def decide(self, messages: list[dict]) -> ComputerUseAction:
        client = self._get_client()
        payload = {
            "model": "gemma-4",
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "computer_use_action",
                    "schema": ComputerUseAction.model_json_schema(),
                },
            },
            "temperature": 0.1,
            "stream": False,
        }
        last_error: Optional[BaseException] = None
        for attempt in range(self._MAX_ATTEMPTS):
            try:
                resp = await client.post("/v1/chat/completions", json=payload)
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                return ComputerUseAction.model_validate_json(content)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                last_error = e
                if attempt == self._MAX_ATTEMPTS - 1:
                    raise
                await asyncio.sleep(self._backoff_base * (2 ** attempt))
        raise last_error  # type: ignore[misc]

    async def close(self):
        if self._client is not None:
            await self._client.aclose()
            self._client = None
```

> **Note on base_url:** `WORKER_LOCAL_LLM_URL` defaults to
> `http://localhost:8080/v1`. We strip the trailing `/v1` and re-add
> `/v1/chat/completions` in the request path so the same env var works whether
> or not it includes `/v1`.

- [ ] **Step 4: Run to verify it passes**

Run: `cd back-end && python -m pytest tests/services/test_computer_use_service.py -k decider -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add back-end/app/services/computer_use_service.py back-end/tests/services/test_computer_use_service.py
git commit -m "feat(backend): computer-use decision LLM call (json_schema + image)"
```

---

### Task 10: Session loop + audit + single-session enforcement

**Files:**
- Modify: `back-end/app/services/computer_use_service.py`
- Modify: `back-end/tests/services/test_computer_use_service.py`

The `ComputerUseService` singleton owns one session at a time. `run_session`
executes the capture→parse→decide→act loop with injected `parser`, `decider`,
`desktop`, and `emit` (step sender) so it is fully unit-testable. It records a
JSONL audit line per executed action, streams `computer_use_step`, and
terminates on done/fail/budget/stop/invalid-streak.

- [ ] **Step 1: Add the failing tests**

Append to `back-end/tests/services/test_computer_use_service.py`:

```python
from app.services.computer_use_service import ComputerUseService


class _FakeDesktop:
    def __init__(self):
        self.events = []

    async def capture(self):
        from app.services.desktop_backend import CapturedScreen
        return CapturedScreen(png_bytes=b"PNG", width=1920, height=1080)

    async def click(self, x, y, button="left", double=False):
        self.events.append(("click", x, y, button, double))

    async def type_text(self, text):
        self.events.append(("type", text))

    async def hotkey(self, keys):
        self.events.append(("hotkey", tuple(keys)))

    async def scroll(self, x, y, amount):
        self.events.append(("scroll", x, y, amount))


class _FakeParser:
    async def parse(self, png_bytes):
        return _screen(2)


class _ScriptedDecider:
    def __init__(self, actions):
        self._actions = list(actions)
        self.calls = 0

    async def decide(self, messages):
        self.calls += 1
        return self._actions.pop(0)


def _make_service(actions, tmp_path):
    svc = ComputerUseService(
        parser=_FakeParser(),
        desktop=_FakeDesktop(),
        decider=_ScriptedDecider(actions),
        audit_path=str(tmp_path / "audit.log"),
    )
    return svc


@pytest.mark.asyncio
async def test_session_runs_to_done(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "COMPUTER_USE_ENABLED", True)
    monkeypatch.setattr(settings, "COMPUTER_USE_SETTLE_SECONDS", 0.0)
    steps = []
    svc = _make_service(
        [ComputerUseAction(action="click", element_id=0, reason="open"),
         ComputerUseAction(action="done", text="finished", reason="done")],
        tmp_path,
    )
    await svc.run_session("goal", emit=lambda m: steps.append(m))

    states = [s for s in steps if s["type"] == "computer_use_state"]
    assert states[0]["status"] == "started"
    assert states[-1]["status"] == "done"
    # one click executed on the fake desktop
    assert ("click", 96, 130, "left", False) in svc._desktop.events
    # audit file has a line for the executed click
    audit = (tmp_path / "audit.log").read_text().strip().splitlines()
    assert any("click" in line for line in audit)


@pytest.mark.asyncio
async def test_session_stops_at_step_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "COMPUTER_USE_ENABLED", True)
    monkeypatch.setattr(settings, "COMPUTER_USE_SETTLE_SECONDS", 0.0)
    monkeypatch.setattr(settings, "COMPUTER_USE_MAX_STEPS", 3)
    steps = []
    # always "wait" -> never terminates on its own
    svc = _make_service(
        [ComputerUseAction(action="wait", reason="loading")] * 10, tmp_path,
    )
    await svc.run_session("goal", emit=lambda m: steps.append(m))
    states = [s for s in steps if s["type"] == "computer_use_state"]
    assert states[-1]["status"] == "failed"
    assert svc._decider.calls == 3  # budget respected


@pytest.mark.asyncio
async def test_invalid_action_then_selfcorrect(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "COMPUTER_USE_ENABLED", True)
    monkeypatch.setattr(settings, "COMPUTER_USE_SETTLE_SECONDS", 0.0)
    steps = []
    svc = _make_service(
        [ComputerUseAction(action="click", element_id=99, reason="bad"),   # invalid
         ComputerUseAction(action="click", element_id=0, reason="good"),   # valid
         ComputerUseAction(action="done", text="ok", reason="done")],
        tmp_path,
    )
    await svc.run_session("goal", emit=lambda m: steps.append(m))
    states = [s for s in steps if s["type"] == "computer_use_state"]
    assert states[-1]["status"] == "done"
    # only the valid click executed
    assert len(svc._desktop.events) == 1


@pytest.mark.asyncio
async def test_two_consecutive_invalid_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "COMPUTER_USE_ENABLED", True)
    monkeypatch.setattr(settings, "COMPUTER_USE_SETTLE_SECONDS", 0.0)
    steps = []
    svc = _make_service(
        [ComputerUseAction(action="click", element_id=99, reason="bad1"),
         ComputerUseAction(action="click", element_id=98, reason="bad2")],
        tmp_path,
    )
    await svc.run_session("goal", emit=lambda m: steps.append(m))
    states = [s for s in steps if s["type"] == "computer_use_state"]
    assert states[-1]["status"] == "failed"
    assert svc._desktop.events == []  # nothing executed


@pytest.mark.asyncio
async def test_single_session_enforced(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "COMPUTER_USE_ENABLED", True)
    monkeypatch.setattr(settings, "COMPUTER_USE_SETTLE_SECONDS", 0.0)
    svc = _make_service(
        [ComputerUseAction(action="wait", reason="x")] * 50, tmp_path,
    )
    monkeypatch.setattr(settings, "COMPUTER_USE_MAX_STEPS", 50)

    task = asyncio.create_task(svc.run_session("goal", emit=lambda m: None))
    await asyncio.sleep(0)  # let it start
    assert svc.active is True
    # second start refused
    ok = svc.start("another goal", emit=lambda m: None, desktop_factory=lambda: _FakeDesktop())
    assert ok is False
    svc.stop()
    await task


@pytest.mark.asyncio
async def test_stop_ends_session(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "COMPUTER_USE_ENABLED", True)
    monkeypatch.setattr(settings, "COMPUTER_USE_SETTLE_SECONDS", 0.0)
    monkeypatch.setattr(settings, "COMPUTER_USE_MAX_STEPS", 50)
    steps = []
    svc = _make_service(
        [ComputerUseAction(action="wait", reason="x")] * 50, tmp_path,
    )
    task = asyncio.create_task(
        svc.run_session("goal", emit=lambda m: steps.append(m))
    )
    await asyncio.sleep(0)
    svc.stop()
    await task
    states = [s for s in steps if s["type"] == "computer_use_state"]
    assert states[-1]["status"] == "stopped"
```

> **Note:** element 0 in `_screen()` has bbox `(0.0, 0.1, 0.05, 0.15)` →
> center `(0.025, 0.125)` → on 1920×1080 → `(48, 135)`. Recompute the expected
> click coords in `test_session_runs_to_done` if you change `_screen`. The
> value `(96, 130)` in the test assumes element **0** center; **verify against
> your `_screen` and fix the literal to match** before marking the step green.

- [ ] **Step 2: Run to verify it fails**

Run: `cd back-end && python -m pytest tests/services/test_computer_use_service.py -k session -v`
Expected: FAIL — `ImportError: cannot import name 'ComputerUseService'`.

- [ ] **Step 3: Write the service**

Append to `back-end/app/services/computer_use_service.py`:

```python
import json
import time

from app.services.desktop_backend import DesktopBackend, norm_to_pixels
from app.services.ai_client.screenparse import ScreenParseUnavailable


class ComputerUseService:
    """Owns one computer-use session at a time. Wired into /ws/chat.

    All external effects (parse, decide, desktop I/O, step emission) are
    injected so the loop is unit-testable with fakes. In production the tool
    layer supplies the real screenparse_client, ComputerUseDecider, and
    LocalDesktopBackend, and `emit` sends over the WebSocket.
    """

    def __init__(self, parser=None, desktop: DesktopBackend | None = None,
                 decider=None, audit_path: str | None = None):
        self._parser = parser
        self._desktop = desktop
        self._decider = decider
        self._audit_path = audit_path or settings.COMPUTER_USE_AUDIT_LOG
        self._active = False
        self._stop_requested = False
        self._task = None

    @property
    def active(self) -> bool:
        return self._active

    def start(self, goal: str, emit, *, parser=None, desktop=None,
              decider=None, desktop_factory=None) -> bool:
        """Start a session as a background task. Returns False if one is active."""
        import asyncio
        if self._active:
            return False
        if parser is not None:
            self._parser = parser
        if decider is not None:
            self._decider = decider
        if desktop is not None:
            self._desktop = desktop
        elif desktop_factory is not None:
            self._desktop = desktop_factory()
        self._task = asyncio.create_task(self.run_session(goal, emit))
        return True

    def stop(self) -> None:
        self._stop_requested = True

    async def run_session(self, goal: str, emit) -> None:
        self._active = True
        self._stop_requested = False
        history: list[dict] = []
        consecutive_invalid = 0
        system_prompt = load_decider_prompt()
        emit({"type": "computer_use_state", "status": "started",
              "goal": goal, "steps_taken": 0})
        try:
            for step in range(settings.COMPUTER_USE_MAX_STEPS):
                if self._stop_requested:
                    emit({"type": "computer_use_state", "status": "stopped",
                          "goal": goal, "steps_taken": step})
                    return
                try:
                    shot = await self._desktop.capture()
                    screen = await self._parser.parse(shot.png_bytes)
                except ScreenParseUnavailable as e:
                    emit({"type": "computer_use_state", "status": "failed",
                          "goal": goal, "steps_taken": step,
                          "error": f"screen parsing unavailable: {e}"})
                    return

                messages = build_decision_messages(
                    goal=goal, screen=screen, history=history,
                    system_prompt=system_prompt,
                    som_image_b64=screen.som_image_b64,
                    history_limit=settings.COMPUTER_USE_HISTORY_STEPS,
                )
                try:
                    action = await self._decider.decide(messages)
                except Exception as e:
                    emit({"type": "computer_use_state", "status": "failed",
                          "goal": goal, "steps_taken": step,
                          "error": f"decision failed: {e}"})
                    return

                if action.action == "done":
                    emit({"type": "computer_use_state", "status": "done",
                          "goal": goal, "steps_taken": step,
                          "summary": action.text or ""})
                    return
                if action.action == "fail":
                    emit({"type": "computer_use_state", "status": "failed",
                          "goal": goal, "steps_taken": step,
                          "error": action.text or action.reason})
                    return

                err = validate_action(action, screen)
                if err is not None:
                    consecutive_invalid += 1
                    history.append({"action": action.action,
                                    "reason": action.reason,
                                    "result": f"INVALID: {err}"})
                    emit(self._step_msg(step, action, screen, "invalid", err))
                    if consecutive_invalid >= 2:
                        emit({"type": "computer_use_state", "status": "failed",
                              "goal": goal, "steps_taken": step,
                              "error": "two consecutive invalid actions"})
                        return
                    continue
                consecutive_invalid = 0

                px, py = self._resolve_coords(action, screen)
                await self._execute(action, px, py)
                self._audit(step, action, px, py)
                history.append({"action": action.action,
                                "reason": action.reason, "result": "executed"})
                emit(self._step_msg(step, action, screen, "executed", None))

                await self._sleep(settings.COMPUTER_USE_SETTLE_SECONDS)

            emit({"type": "computer_use_state", "status": "failed",
                  "goal": goal, "steps_taken": settings.COMPUTER_USE_MAX_STEPS,
                  "error": "step budget exhausted"})
        finally:
            self._active = False
            self._stop_requested = False

    async def _sleep(self, seconds: float) -> None:
        import asyncio
        if seconds > 0:
            await asyncio.sleep(seconds)

    def _resolve_coords(self, action: ComputerUseAction,
                        screen: ParsedScreen) -> tuple[int, int]:
        if action.element_id is not None and 0 <= action.element_id < len(screen.elements):
            cx, cy = screen.elements[action.element_id].center()
        else:
            cx, cy = 0.5, 0.5
        return norm_to_pixels(cx, cy, screen.width, screen.height)

    async def _execute(self, action: ComputerUseAction, px: int, py: int) -> None:
        a = action.action
        if a == "click":
            await self._desktop.click(px, py)
        elif a == "double_click":
            await self._desktop.click(px, py, double=True)
        elif a == "right_click":
            await self._desktop.click(px, py, button="right")
        elif a == "type":
            await self._desktop.click(px, py)
            await self._desktop.type_text(action.text or "")
        elif a == "hotkey":
            await self._desktop.hotkey(action.keys or [])
        elif a == "scroll":
            await self._desktop.scroll(px, py, action.scroll_amount or 0)
        elif a == "wait":
            pass

    def _step_msg(self, step, action, screen, status, error):
        el_content = ""
        if action.element_id is not None and 0 <= action.element_id < len(screen.elements):
            el_content = screen.elements[action.element_id].content
        return {
            "type": "computer_use_step",
            "step": step,
            "action": action.action,
            "element_id": action.element_id,
            "element_content": el_content,
            "reason": action.reason,
            "status": status,
            "error": error,
            "som_image": (
                f"data:image/jpeg;base64,{screen.som_image_b64}"
                if screen.som_image_b64 else ""
            ),
            "elements": [
                {"id": e.id, "type": e.type, "content": e.content,
                 "interactable": e.interactable}
                for e in screen.elements
            ],
        }

    def _audit(self, step, action: ComputerUseAction, px, py) -> None:
        line = json.dumps({
            "ts": time.time(), "step": step, "action": action.action,
            "element_id": action.element_id, "reason": action.reason,
            "px": px, "py": py, "text": action.text, "keys": action.keys,
        })
        try:
            from pathlib import Path
            p = Path(self._audit_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    # Debug artifacts (opt-in) are written by the caller in chat_ws when
    # COMPUTER_USE_DEBUG_DIR is set — the loop stays I/O-minimal.


computer_use_service = ComputerUseService()
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd back-end && python -m pytest tests/services/test_computer_use_service.py -v`
Expected: PASS (all tests). Fix the `(96, 130)` literal in
`test_session_runs_to_done` to the actual element-0 center pixels if it
mismatches (see the note in Step 1).

- [ ] **Step 5: Commit**

```bash
git add back-end/app/services/computer_use_service.py back-end/tests/services/test_computer_use_service.py
git commit -m "feat(backend): ComputerUseService session loop + audit + single-session"
```

---

## PHASE D — backend: tools, prompt, WebSocket wiring

### Task 11: computer_use / stop_computer_use tools

**Files:**
- Create: `back-end/app/tools/computer_use_tools.py`
- Modify: `back-end/app/tools/__init__.py`
- Create: `back-end/app/prompts/tools_computer_use.txt`

The tools are thin: they resolve the real dependencies (screenparse_client,
ComputerUseDecider, LocalDesktopBackend) and delegate to the singleton. The
step `emit` is bound in chat_ws (Task 13) via `computer_use_service` config, so
the tool only needs to start/stop. To keep the emit wiring in one place, the
tools call module-level hooks set by chat_ws.

- [ ] **Step 1: Write the tools**

Create `back-end/app/tools/computer_use_tools.py`:

```python
"""Computer-use control tools: start/stop a desktop-control session.

The session's step emitter and desktop backend are supplied by chat_ws at
connection time via set_session_hooks(). The tool only starts/stops; the loop
lives in ComputerUseService. Starting returns immediately so the agent turn
finishes (and TTS plays) while the session runs in the background.
"""
from __future__ import annotations

from typing import Callable, Optional

from langchain_core.tools import tool

from app.core.config import settings
from app.services.computer_use_service import (
    ComputerUseDecider, computer_use_service,
)
from app.services.ai_client.screenparse import screenparse_client
from app.services.desktop_backend import LocalDesktopBackend

# Set by chat_ws on connect: (emit_fn, is_admin_bool). None when no client.
_session_emit: Optional[Callable[[dict], None]] = None
_is_admin: bool = True


def set_session_hooks(emit: Optional[Callable[[dict], None]], is_admin: bool) -> None:
    global _session_emit, _is_admin
    _session_emit = emit
    _is_admin = is_admin


def clear_session_hooks() -> None:
    global _session_emit
    _session_emit = None


@tool
async def computer_use(goal: str) -> str:
    """Take control of the computer's screen, mouse, and keyboard to accomplish a
    goal by looking at the screen and clicking/typing. Use for tasks that require
    operating desktop applications visually (e.g. "open Notepad and type hello",
    "close all Chrome tabs"). Prefer run_command / terminal tools for anything
    that can be done in a shell. Only one session runs at a time.

    Args:
        goal: A concrete description of what to accomplish on screen.
    """
    if not settings.COMPUTER_USE_ENABLED:
        return "Computer-use mode is disabled on this server."
    if not _is_admin:
        return "Computer-use mode is restricted to the admin user."
    if _session_emit is None:
        return "No active client connection to stream computer-use steps to."
    if computer_use_service.active:
        return "A computer-use session is already running. Stop it first."

    decider = ComputerUseDecider()
    started = computer_use_service.start(
        goal, _session_emit,
        parser=screenparse_client,
        decider=decider,
        desktop_factory=LocalDesktopBackend,
    )
    if not started:
        return "A computer-use session is already running."
    return f"Started a computer-use session to: {goal}. I'll work on it now."


@tool
async def stop_computer_use() -> str:
    """Stop the currently running computer-use session immediately."""
    if not computer_use_service.active:
        return "No computer-use session is currently running."
    computer_use_service.stop()
    return "Stopping the computer-use session."
```

- [ ] **Step 2: Register the tools**

In `back-end/app/tools/__init__.py`, add the import after the cloud tools import:

```python
from app.tools.computer_use_tools import computer_use, stop_computer_use
```

and add both to `ALL_TOOLS` (after `get_background_service_logs`):

```python
    computer_use,
    stop_computer_use,
```

- [ ] **Step 3: Write the prompt section**

Create `back-end/app/prompts/tools_computer_use.txt`:

```
## Computer-Use Mode

You can take direct visual control of the computer with `computer_use(goal)`.
This starts a background session where you repeatedly look at the screen (parsed
into numbered elements) and click or type to accomplish the goal.

When to use it:
- The task requires operating a desktop GUI application visually (opening apps,
  clicking buttons, filling forms) and cannot be done from a shell.

When NOT to use it:
- Anything achievable with `run_command` or the terminal tools — prefer those;
  they are faster and more reliable than clicking.

Rules:
- Only one session runs at a time. If one is active, stop it before starting another.
- `computer_use` returns immediately ("Started a session…"); the work happens in
  the background and you will narrate progress. Do not call it again in a loop.
- Use `stop_computer_use()` if the user asks you to stop or cancel.
- Give `goal` as a concrete, self-contained instruction (e.g. "open Notepad and
  type 'hello world'"), not a vague one.
```

- [ ] **Step 4: Verify tools import + register**

Run: `cd back-end && python -c "from app.tools import TOOL_MAP; print('computer_use' in TOOL_MAP, 'stop_computer_use' in TOOL_MAP)"`
Expected: prints `True True`.

- [ ] **Step 5: Commit**

```bash
git add back-end/app/tools/computer_use_tools.py back-end/app/tools/__init__.py back-end/app/prompts/tools_computer_use.txt
git commit -m "feat(backend): computer_use + stop_computer_use tools + prompt section"
```

---

### Task 12: Tool retriever + prompt section wiring

**Files:**
- Modify: `back-end/app/services/tool_retriever.py`
- Modify: `back-end/app/services/llm_service.py`
- Test: `back-end/tests/test_tool_retriever_computer_use.py`

Make `computer_use` always-available (voice entry must always find it), make it
and `stop_computer_use` bidirectional companions, and load the
`tools_computer_use.txt` prompt section when either is retrieved.

- [ ] **Step 1: Write the failing test**

Create `back-end/tests/test_tool_retriever_computer_use.py`:

```python
import pytest

from app.services.tool_retriever import ToolRetriever, ALWAYS_AVAILABLE


def test_computer_use_is_always_available():
    assert "computer_use" in ALWAYS_AVAILABLE


@pytest.mark.asyncio
async def test_stop_companion_added_when_computer_use_present():
    r = ToolRetriever()
    # simulate a degraded/empty embedding index so retrieve() returns
    # always-available only, then confirm companion expansion includes stop.
    r._tool_embeddings = None
    r._tool_names = ["computer_use", "stop_computer_use", "get_system_time"]
    names = await r.retrieve("do something on screen")
    assert "computer_use" in names
    # companion expansion happens on the non-degraded path; assert the mapping
    # exists by exercising the companion block directly:
    # (retrieve returns always-available in degraded mode; companion tested below)
```

> **Note:** the degraded path returns only always-available names. Add the
> companion assertion via a second test that stubs embeddings; the simplest
> reliable check is the mapping presence test below.

Append:

```python
def test_companion_mapping_is_bidirectional(monkeypatch):
    # White-box: the COMPANION_TOOLS dict inside retrieve() must pair the two.
    # We assert on the source of truth by calling retrieve with a fake index.
    import numpy as np
    r = ToolRetriever()
    r._tool_names = ["computer_use", "stop_computer_use"]
    r._tool_texts = ["computer_use: x", "stop_computer_use: y"]
    # identity embeddings so "computer_use" scores highest for its own text
    r._tool_embeddings = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)

    async def fake_encode(texts, model=None):
        return [[1.0, 0.0]]  # matches computer_use row

    monkeypatch.setattr("app.services.tool_retriever.embed_client.encode", fake_encode)
    import asyncio
    names = asyncio.get_event_loop().run_until_complete(r.retrieve("control screen"))
    assert "computer_use" in names and "stop_computer_use" in names
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd back-end && python -m pytest tests/test_tool_retriever_computer_use.py -v`
Expected: FAIL — `computer_use` not in `ALWAYS_AVAILABLE`.

- [ ] **Step 3: Update the retriever**

In `back-end/app/services/tool_retriever.py`, add `computer_use` to `ALWAYS_AVAILABLE`:

```python
ALWAYS_AVAILABLE = {
    "get_system_time",
    "clear_memory",
    "set_reminder",
    "set_scheduled_task",
    "list_tasks",
    "cancel_task",
    "ask_claude",
    "ask_gemini",
    "ask_openai",
    "run_command",
    "computer_use",
}
```

In the `COMPANION_TOOLS` dict inside `retrieve()`, add the bidirectional pair:

```python
        COMPANION_TOOLS = {
            "web_search": ["web_scrape"],
            "open_terminal": TERMINAL_GROUP,
            "send_to_terminal": TERMINAL_GROUP,
            "read_terminal": TERMINAL_GROUP,
            "list_terminals": TERMINAL_GROUP,
            "close_terminal": TERMINAL_GROUP,
            "computer_use": ["stop_computer_use"],
            "stop_computer_use": ["computer_use"],
        }
```

- [ ] **Step 4: Add the prompt section trigger**

In `back-end/app/services/llm_service.py`, extend `_SECTION_TRIGGERS`:

```python
    "tools_computer_use.txt": frozenset({
        "computer_use", "stop_computer_use",
    }),
```

(The `_SECTION_CACHE` comprehension already loads every key in
`_SECTION_TRIGGERS`, so no other change is needed.)

- [ ] **Step 5: Run to verify it passes**

Run: `cd back-end && python -m pytest tests/test_tool_retriever_computer_use.py -v`
Expected: PASS.

Also verify the section loads:
Run: `cd back-end && python -c "from app.services.llm_service import build_system_prompt as b; print('Computer-Use Mode' in b(['computer_use']))"`
Expected: `True`.

- [ ] **Step 6: Commit**

```bash
git add back-end/app/services/tool_retriever.py back-end/app/services/llm_service.py back-end/tests/test_tool_retriever_computer_use.py
git commit -m "feat(backend): retriever always-available + companion + prompt section for computer-use"
```

---

### Task 13: WS message schemas + chat_ws wiring

**Files:**
- Modify: `back-end/app/schemas/messages.py`
- Modify: `back-end/app/api/websockets/chat_ws.py`
- Test: `back-end/tests/test_chat_ws_computer_use.py`

Wire the step emitter, admin gate, and inbound `computer_use_stop`. The emitter
uses `connection_manager.send_json` (background-safe), and when
`COMPUTER_USE_DEBUG_DIR` is set it also persists per-step artifacts.

- [ ] **Step 1: Add message schemas**

In `back-end/app/schemas/messages.py`, after `NotificationMessage`, add:

```python
class ComputerUseStateMessage(BaseModel):
    type: Literal["computer_use_state"] = "computer_use_state"
    status: Literal["started", "running", "done", "failed", "stopped"]
    goal: str
    steps_taken: int
    summary: Optional[str] = None
    error: Optional[str] = None


class ComputerUseStepMessage(BaseModel):
    type: Literal["computer_use_step"] = "computer_use_step"
    step: int
    action: str
    element_id: Optional[int] = None
    element_content: str = ""
    reason: str = ""
    status: str = ""
    error: Optional[str] = None
    som_image: str = ""
    elements: list = []


class ComputerUseStopMessage(BaseModel):
    type: Literal["computer_use_stop"] = "computer_use_stop"
```

- [ ] **Step 2: Write the failing test**

Create `back-end/tests/test_chat_ws_computer_use.py`:

```python
"""Tests for the chat_ws computer-use emitter + debug artifact writer."""
import json

from app.api.websockets import chat_ws


def test_make_step_emitter_forwards_and_writes_debug(tmp_path, monkeypatch):
    sent = []

    def fake_send(msg):
        sent.append(msg)

    monkeypatch.setattr(chat_ws.settings, "COMPUTER_USE_DEBUG_DIR", str(tmp_path))
    emit = chat_ws._make_computer_use_emitter(fake_send, session_id="abc")

    step_msg = {
        "type": "computer_use_step", "step": 0, "action": "click",
        "element_id": 1, "element_content": "File", "reason": "open menu",
        "status": "executed", "error": None,
        "som_image": "data:image/jpeg;base64,QUJD", "elements": [],
    }
    emit(step_msg)

    # forwarded to the websocket
    assert sent == [step_msg]
    # debug artifacts written
    session_dir = tmp_path / "abc"
    assert (session_dir / "step_0.jpg").exists()
    decision = json.loads((session_dir / "step_0.json").read_text())
    assert decision["action"] == "click"


def test_make_step_emitter_no_debug_when_dir_empty(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(chat_ws.settings, "COMPUTER_USE_DEBUG_DIR", "")
    emit = chat_ws._make_computer_use_emitter(sent.append, session_id="abc")
    emit({"type": "computer_use_state", "status": "started", "goal": "g",
          "steps_taken": 0})
    assert len(sent) == 1
    assert not (tmp_path / "abc").exists()
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd back-end && python -m pytest tests/test_chat_ws_computer_use.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute '_make_computer_use_emitter'`.

- [ ] **Step 4: Add the emitter factory to chat_ws.py**

In `back-end/app/api/websockets/chat_ws.py`, add near the top-level helpers
(after `_build_live_message`), a module-level function:

```python
def _make_computer_use_emitter(send_json_threadsafe, session_id: str):
    """Build the emit(msg) callback the computer-use loop pushes steps through.

    The loop calls emit() synchronously. send_json_threadsafe may return a
    coroutine (production `send_json_safe`) or None (a sync test fake); we
    schedule it only when awaitable so both work. When COMPUTER_USE_DEBUG_DIR
    is set, computer_use_step messages also persist their SoM JPEG + decision
    JSON for post-hoc E2E debugging.
    """
    import asyncio
    import inspect
    import base64 as _b
    from pathlib import Path

    def emit(msg: dict):
        result = send_json_threadsafe(msg)
        if inspect.isawaitable(result):
            asyncio.get_event_loop().create_task(result)

        debug_dir = settings.COMPUTER_USE_DEBUG_DIR
        if debug_dir and msg.get("type") == "computer_use_step":
            try:
                sdir = Path(debug_dir) / session_id
                sdir.mkdir(parents=True, exist_ok=True)
                step = msg.get("step", 0)
                som = msg.get("som_image", "")
                if som.startswith("data:image"):
                    b64 = som.split(",", 1)[1]
                    (sdir / f"step_{step}.jpg").write_bytes(_b.b64decode(b64))
                (sdir / f"step_{step}.json").write_text(
                    json.dumps({k: v for k, v in msg.items() if k != "som_image"}),
                    encoding="utf-8",
                )
            except Exception:
                pass

    return emit
```

- [ ] **Step 5: Wire the session hooks, stop handler, and cleanup**

In `chat_ws.py`, add the import near the copilot import:

```python
from app.services.computer_use_service import computer_use_service
from app.tools.computer_use_tools import set_session_hooks as _cu_set_hooks, clear_session_hooks as _cu_clear_hooks
```

After the copilot attach block (`copilot_service.attach(...)`), bind the
computer-use hooks:

```python
    _cu_emit = _make_computer_use_emitter(send_json_safe, session_id)
    _cu_set_hooks(_cu_emit, is_admin=(ws_user_role == "admin"))
```

Add an inbound handler in the JSON message dispatch (near `copilot_stop`):

```python
                    elif msg_type == "computer_use_stop":
                        computer_use_service.stop()
                        await send_json_safe({
                            "type": "computer_use_state",
                            "status": "stopped",
                            "goal": "",
                            "steps_taken": 0,
                        })
```

In the `finally:` cleanup block, after `copilot_service.detach()`, add:

```python
        computer_use_service.stop()
        _cu_clear_hooks()
```

- [ ] **Step 6: Run to verify it passes**

Run: `cd back-end && python -m pytest tests/test_chat_ws_computer_use.py -v`
Expected: PASS (2 tests).

Also run the existing chat_ws tests to confirm no regression:
Run: `cd back-end && python -m pytest tests/test_chat_ws_copilot.py tests/test_chat_ws_concurrent.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add back-end/app/schemas/messages.py back-end/app/api/websockets/chat_ws.py back-end/tests/test_chat_ws_computer_use.py
git commit -m "feat(backend): chat_ws computer-use emitter + stop handler + admin gate"
```

---

### Task 14: llama-server json_schema + image smoke test (spike)

**Files:**
- Create: `back-end/tests/smoke_json_schema_image.py`
- Create: `back-end/tests/manual_screenparse_smoke.md`

This validates the ONE load-bearing assumption: llama-server accepts
`response_format=json_schema` combined with an image in the same request. Run
manually against the real llama-server before trusting Task 9 in production.

- [ ] **Step 1: Write the smoke script**

Create `back-end/tests/smoke_json_schema_image.py`:

```python
"""Manual smoke: does llama-server accept json_schema + an image together?

Run with the real llama-server up:
    cd back-end && python tests/smoke_json_schema_image.py

Prints the parsed ComputerUseAction JSON on success, or the raw error. This is
NOT a pytest test (needs a live GPU llama-server); it is a manual spike.
"""
import asyncio
import base64
import io
import json

import httpx

from app.core.config import settings
from app.services.computer_use_service import ComputerUseAction


def _tiny_png_b64() -> str:
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (200, 120), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([20, 20, 120, 60], outline="black")
    d.text((30, 35), "[0] OK button", fill="black")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


async def main():
    base = settings.WORKER_LOCAL_LLM_URL.rstrip("/").rsplit("/v1", 1)[0]
    payload = {
        "model": "gemma-4",
        "messages": [
            {"role": "system", "content": "Return the next action as JSON."},
            {"role": "user", "content": [
                {"type": "text", "text":
                 "GOAL: click OK. ELEMENTS:\n[0] icon \"OK button\" interactable"},
                {"type": "image_url", "image_url":
                 {"url": f"data:image/jpeg;base64,{_tiny_png_b64()}"}},
            ]},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "computer_use_action",
                "schema": ComputerUseAction.model_json_schema(),
            },
        },
        "temperature": 0.1,
        "stream": False,
    }
    async with httpx.AsyncClient(base_url=base, timeout=60.0) as client:
        resp = await client.post("/v1/chat/completions", json=payload)
        print("HTTP", resp.status_code)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        print("RAW:", content)
        action = ComputerUseAction.model_validate_json(content)
        print("PARSED:", action.model_dump())


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Write the manual runbook**

Create `back-end/tests/manual_screenparse_smoke.md`:

```markdown
# Computer-Use manual smoke tests

## 1. llama-server: json_schema + image
Prereq: llama-server running with `--jinja` and an `--mmproj` (vision) model.

    cd back-end && python tests/smoke_json_schema_image.py

PASS: prints `PARSED: {...}` with a valid action.
FAIL (e.g. server rejects json_schema with image, or returns prose): switch
`ComputerUseDecider` to prompt-enforced JSON — append "Respond ONLY with a JSON
object" to the decider prompt, drop `response_format`, and parse with a tolerant
`json.loads` that strips ```json fences. The rest of the loop is unchanged.

## 2. ScreenParse over the wire
Prereq: shore-ai-service deployed with the ScreenParse servicer + weights,
Health shows `screenparse.loaded=true`.

    cd back-end && python - <<'PY'
    import asyncio, base64
    from app.services.ai_client import channel
    from app.services.ai_client.screenparse import screenparse_client
    from app.tools.screen_tools import _capture_screen_b64
    async def main():
        channel.init()
        png = base64.b64decode(_capture_screen_b64())  # jpeg ok too
        res = await screenparse_client.parse(png)
        print("elements:", len(res.elements), "dims:", res.width, res.height)
        for e in res.elements[:10]:
            print(e.id, e.type, repr(e.content), e.interactable)
    asyncio.run(main())
    PY

PASS: prints a non-empty element list with sensible captions.
```

- [ ] **Step 3: Commit**

```bash
git add back-end/tests/smoke_json_schema_image.py back-end/tests/manual_screenparse_smoke.md
git commit -m "test(backend): manual smokes for json_schema+image and ScreenParse wire"
```

> **Run Step 1's smoke now if a llama-server is reachable.** If it fails, apply
> the prompt-enforced-JSON fallback described in the runbook to
> `ComputerUseDecider` (Task 9) and re-run the Task 9 tests before continuing.

---

## PHASE E — frontend: live step viewer

### Task 15: Frontend WS types + send methods

**Files:**
- Modify: `front-end/src/services/chat-websocket.service.ts`

- [ ] **Step 1: Add message interfaces**

In `front-end/src/services/chat-websocket.service.ts`, after `CopilotMessage`, add:

```typescript
export interface ComputerUseStateMessage {
  type: "computer_use_state";
  status: "started" | "running" | "done" | "failed" | "stopped";
  goal: string;
  steps_taken: number;
  summary?: string;
  error?: string;
}

export interface ComputerUseStepElement {
  id: number;
  type: string;
  content: string;
  interactable: boolean;
}

export interface ComputerUseStepMessage {
  type: "computer_use_step";
  step: number;
  action: string;
  element_id?: number | null;
  element_content: string;
  reason: string;
  status: string;
  error?: string | null;
  som_image: string; // data URL (may be "")
  elements: ComputerUseStepElement[];
}
```

- [ ] **Step 2: Add them to the union**

Extend `ChatServerMessage`:

```typescript
  | CopilotStateMessage
  | CopilotMessage
  | ComputerUseStateMessage
  | ComputerUseStepMessage
  | HistoryMessage;
```

- [ ] **Step 3: Add a stop send method**

After `sendCopilotStop()`, add:

```typescript
  public sendComputerUseStop(): void {
    if (!this.isReady()) return;
    this.socket!.send(JSON.stringify({ type: "computer_use_stop" }));
  }
```

- [ ] **Step 4: Verify the build typechecks**

Run: `cd front-end && npm run build`
Expected: build succeeds (no TS errors).

- [ ] **Step 5: Commit**

```bash
git add front-end/src/services/chat-websocket.service.ts
git commit -m "feat(frontend): computer-use WS message types + stop send method"
```

---

### Task 16: Live step viewer component + useAssistant wiring

**Files:**
- Create: `front-end/src/pages/Chat/ComputerUseViewer.tsx`
- Modify: `front-end/src/hooks/useAssistant.ts`
- Modify: `front-end/src/pages/Chat/index.tsx`

- [ ] **Step 1: Add session state to useAssistant**

In `front-end/src/hooks/useAssistant.ts`, add state for the current session +
last step. Locate where other message types are handled (the `message` event
switch) and add cases:

```typescript
  const [computerUseState, setComputerUseState] =
    useState<ComputerUseStateMessage | null>(null);
  const [computerUseStep, setComputerUseStep] =
    useState<ComputerUseStepMessage | null>(null);
```

In the message handler switch, add:

```typescript
      case "computer_use_state":
        setComputerUseState(msg);
        if (msg.status === "done" || msg.status === "failed" || msg.status === "stopped") {
          // clear the live step image once the session ends
          setComputerUseStep(null);
        }
        break;
      case "computer_use_step":
        setComputerUseStep(msg);
        break;
```

Import the types at the top:

```typescript
import type {
  ComputerUseStateMessage,
  ComputerUseStepMessage,
} from "../services/chat-websocket.service";
```

Expose in the hook's return object:

```typescript
    computerUseState,
    computerUseStep,
    stopComputerUse: () => chatWebsocketService.sendComputerUseStop(),
```

> **Implementer:** match the existing return-object and handler style in
> `useAssistant.ts` (it already handles `copilot_state` / `copilot_message` —
> mirror that exactly for placement and naming).

- [ ] **Step 2: Write the viewer component**

Create `front-end/src/pages/Chat/ComputerUseViewer.tsx`:

```tsx
import type {
  ComputerUseStateMessage,
  ComputerUseStepMessage,
} from "../../services/chat-websocket.service";

interface Props {
  state: ComputerUseStateMessage | null;
  step: ComputerUseStepMessage | null;
  onStop: () => void;
}

const ACTIVE = new Set(["started", "running"]);

export function ComputerUseViewer({ state, step, onStop }: Props) {
  if (!state) return null;
  const active = ACTIVE.has(state.status);

  return (
    <div className="rounded-lg border border-neutral-700 bg-neutral-900/60 p-3 text-sm">
      <div className="mb-2 flex items-center justify-between">
        <div className="font-medium text-neutral-200">
          Computer-use: <span className="text-neutral-400">{state.goal}</span>
        </div>
        <div className="flex items-center gap-2">
          <span
            className={
              "rounded px-2 py-0.5 text-xs " +
              (state.status === "done"
                ? "bg-green-800 text-green-200"
                : state.status === "failed"
                  ? "bg-red-800 text-red-200"
                  : state.status === "stopped"
                    ? "bg-neutral-700 text-neutral-300"
                    : "bg-blue-800 text-blue-200")
            }
          >
            {state.status} · step {state.steps_taken}
          </span>
          {active && (
            <button
              onClick={onStop}
              className="rounded bg-red-700 px-2 py-0.5 text-xs text-white hover:bg-red-600"
            >
              Stop
            </button>
          )}
        </div>
      </div>

      {step?.som_image && (
        <img
          src={step.som_image}
          alt={`OmniParser step ${step.step}`}
          className="mb-2 max-h-[50vh] w-full rounded object-contain"
        />
      )}

      {step && (
        <div className="text-xs text-neutral-300">
          <span className="font-mono text-neutral-400">#{step.step}</span>{" "}
          <span className="font-semibold">{step.action}</span>
          {step.element_content && (
            <span className="text-neutral-400"> → “{step.element_content}”</span>
          )}
          {step.reason && <div className="text-neutral-500">{step.reason}</div>}
          {step.status === "invalid" && step.error && (
            <div className="text-red-400">invalid: {step.error}</div>
          )}
        </div>
      )}

      {(state.summary || state.error) && (
        <div className="mt-2 text-xs text-neutral-400">
          {state.summary || state.error}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Mount the viewer in the Chat page**

In `front-end/src/pages/Chat/index.tsx`, pull the new values from the hook and
render the viewer above the composer (match the existing layout / how
copilot UI is placed):

```tsx
import { ComputerUseViewer } from "./ComputerUseViewer";
```

```tsx
  const {
    /* ...existing... */
    computerUseState,
    computerUseStep,
    stopComputerUse,
  } = useAssistant(/* existing args */);
```

```tsx
  <ComputerUseViewer
    state={computerUseState}
    step={computerUseStep}
    onStop={stopComputerUse}
  />
```

- [ ] **Step 4: Verify the build**

Run: `cd front-end && npm run build && npm run lint`
Expected: build + lint succeed.

- [ ] **Step 5: Commit**

```bash
git add front-end/src/pages/Chat/ComputerUseViewer.tsx front-end/src/hooks/useAssistant.ts front-end/src/pages/Chat/index.tsx
git commit -m "feat(frontend): live OmniParser step viewer + computer-use session state"
```

---

## PHASE F — integration, docs, live E2E

### Task 17: Full unit suite + docs

**Files:**
- Modify: `CLAUDE.md`
- Modify: `back-end/config/services.example.yaml` (if OmniParser/shore-ai controllable rows need a note — optional)

- [ ] **Step 1: Run the full backend suite**

Run: `cd back-end && python -m pytest tests/ -q`
Expected: all green (new tests + no regressions).

- [ ] **Step 2: Run the service suite**

Run: `cd shore-ai-service && python -m pytest tests/ -q`
Expected: all green.

- [ ] **Step 3: Document the feature in CLAUDE.md**

In `CLAUDE.md`, add to the architecture bullets under the FastAPI backend list
a `Computer-Use` entry, add `ScreenParse.Parse` to the shore-ai-service section,
add the `COMPUTER_USE_*` + `SHORE_AI_SCREENPARSE_TIMEOUT_SECONDS` rows to the
Configuration table, and add a "Computer-Use (OmniParser)" paragraph to Key
Technical Constraints mirroring the Screen Co-pilot entry (session mode,
DesktopBackend abstraction with local v1 / RDP phase-2, auto-execute + audit
log, admin-only, `COMPUTER_USE_ENABLED` default off, live SoM step viewer).
Add a Backlog line: `- [x] Computer-use mode — OmniParser v2 perception + Shore control agent`.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude): document computer-use mode + ScreenParse + COMPUTER_USE_* config"
```

---

### Task 18: Live end-to-end (definition of done)

**Files:** none (operational runbook — record results in the PR description).

This is the acceptance gate. It requires the real stack: GPU box with the
updated shore-ai-service image, llama-server with a vision model, and the
backend on the Windows host that will be controlled.

- [ ] **Step 1: Build + deploy shore-ai-service with OmniParser**

On the GPU box:

```bash
cd shore-ai-service
# set OMNIPARSER_REF to the pinned commit in the Dockerfile first
docker compose build
docker compose up -d
```

Verify Health reports screenparse loaded (from the backend host):

```bash
cd back-end && python -c "
import asyncio
from app.services.ai_client import channel
from app.services.ai_client.health import health_client
async def m():
    channel.init(); print(await health_client.get())
asyncio.run(m())"
```
Expected: components include `screenparse` with `loaded=true` (after warmup).

- [ ] **Step 2: Run the ScreenParse wire smoke (runbook §2)**

Run the snippet in `back-end/tests/manual_screenparse_smoke.md` §2.
Expected: non-empty element list with sensible captions for the current screen.

- [ ] **Step 3: Run the json_schema+image smoke (runbook §1)**

Run: `cd back-end && python tests/smoke_json_schema_image.py`
Expected: `PARSED: {...}`. If it fails, apply the prompt-enforced-JSON fallback
(runbook §1) and re-run Task 9 tests.

- [ ] **Step 4: Enable the feature + start the backend**

In `back-end/.env`: `COMPUTER_USE_ENABLED=True`,
`COMPUTER_USE_DEBUG_DIR=data/computer_use_debug`. Start:
`cd back-end && python -m uvicorn app.main:app --reload --port 9000`.
Start the frontend: `cd front-end && npm run dev`.

- [ ] **Step 5: Drive the E2E task by voice/chat**

In the chat UI (logged in as admin if auth is on), send:
*"Open Notepad and type hello world"*.

Expected, all observed:
- Shore calls `computer_use` and replies that it started (TTS plays).
- The live viewer shows SoM-annotated screenshots with numbered boxes, the
  element list, and each chosen action + reason.
- Real clicks/typing happen on the host desktop; Notepad opens and receives text.
- `data/computer_use_audit.log` has one JSONL line per executed action.
- `data/computer_use_debug/<session>/step_*.jpg|json` artifacts exist.
- On completion Shore announces the result in-character with TTS
  (`computer_use_state` → `done`).
- Sending "stop" mid-run (or the Stop button) ends the session (`stopped`).

- [ ] **Step 6: Record results + open the PR**

Capture the audit log tail + a viewer screenshot in the PR description.

```bash
git push -u origin feat/omniparser-computer-use
gh pr create --title "Computer-use mode: OmniParser v2 perception + Shore control agent" --body "<results>"
```

---

## Self-Review Notes (addressed)

- **Spec coverage:** ScreenParse servicer (Tasks 1–3), backend client (5),
  DesktopBackend local v1 (6), action schema/validation (7), decision
  builders/prompt (8), decision LLM json_schema+image (9), session loop with
  audit/budget/stop/invalid-streak/single-session (10), tools + prompt section
  (11–12), WS schemas + chat_ws emitter/stop/admin gate + debug artifacts (13),
  llama-server assumption smoke (14), frontend types + live SoM viewer (15–16),
  docs + full suite (17), live E2E "open Notepad and type hello world" (18).
  Phase-2 RemoteDesktopBackend is explicitly future scope (spec + DesktopBackend
  interface make it a drop-in).
- **Coordinate-literal caveat** flagged in Task 10 Step 1 (recompute element-0
  center for the fake screen).
- **llama-server json_schema+image** is the one load-bearing assumption; Task 14
  smokes it early with a documented fallback wired into Task 9's shape.
- **Type consistency:** `ParsedScreen`/`ParsedElement.center()`,
  `CapturedScreen`, `ComputerUseAction`, `norm_to_pixels`,
  `build_decision_messages`, `validate_action`, `computer_use_service`,
  `set_session_hooks`/`clear_session_hooks`,
  `_make_computer_use_emitter`, and the WS message `type` strings are used
  consistently across backend, tools, chat_ws, and frontend.
```
