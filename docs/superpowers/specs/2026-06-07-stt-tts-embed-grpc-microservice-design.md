# Shore AI Service — gRPC Microservice Design

**Date:** 2026-06-07
**Status:** Draft for review
**Author brainstorm:** Luna + Claude

## Goal

Tách toàn bộ workload AI (STT, TTS, Embedding) khỏi backend FastAPI và đẩy sang
một microservice `shore-ai-service` chạy trên máy có GPU. Backend trở thành
**orchestrator thuần** — không còn import `torch`, `transformers`, `kokoro`,
hay `sentence-transformers`. Liên kết giữa backend và service dùng **gRPC over
TLS**.

## Non-Goals

- Hot-reload model size từ Dashboard UI (proto chừa chỗ, UI để sau).
- Streaming partial STT (Whisper không stream native).
- Direct frontend → shore-ai (cố tình bỏ qua để giữ cookie-auth + cancellation
  ở backend).
- Multi-instance / load balancing.
- mTLS (chừa chỗ qua reverse proxy upgrade sau).
- Đẩy LLM hoặc Vision sang microservice mới — chúng đã chạy qua `llama-server`
  HTTP rồi.

## Decisions chốt từ brainstorm

| # | Decision | Choice |
|---|---|---|
| 1 | Granularity | 1 microservice `shore-ai-service` cho cả STT + TTS + Embed |
| 2 | Lifecycle | Start/Stop cả process (container) |
| 3 | Control plane | Supervisor agent riêng `shore-ai-supervisor` |
| 4 | TTS path | Backend relay qua `/ws/chat` (giữ nguyên giao thức frontend) |
| 5 | Fallback | Graceful degrade (như `MemoryFacade`) |
| 6 | Auth | TLS reverse proxy + shared bearer token trong gRPC metadata |
| 7 | Hosting | Docker container trên GPU machine, `--gpus all` |
| 8 | Scope deps | Đẩy luôn `sentence-transformers` — backend 100% sạch AI deps |

## Architecture overview

```
┌─────────────────────────────────────────────────────────────┐
│ GPU machine (Docker host, NVIDIA Container Toolkit)         │
│                                                              │
│ shore-ai-supervisor (host process, gRPC :9101)              │
│   ├─ Service.Start()   → docker compose start shore-ai      │
│   ├─ Service.Stop()    → docker compose stop  shore-ai      │
│   └─ Service.Status()  → docker compose ps -q shore-ai      │
│                                                              │
│ shore-ai-service (Docker container, gRPC :9200, --gpus all) │
│   ├─ STT.Transcribe(audio, language)   unary                │
│   ├─ TTS.Synthesize(text, voice)       server-streaming     │
│   ├─ Embed.Encode(texts) -> vectors[]  unary (batch)        │
│   └─ Health.Get()                      unary                │
└─────────────────────────────────────────────────────────────┘
                              ↑
                       TLS (Caddy/nginx)
                       Bearer token in metadata
                              ↑
┌─────────────────────────────────────────────────────────────┐
│ Orchestrator backend (no torch/transformers/kokoro/ST)      │
│   app/services/ai_client/                                   │
│     ├─ channel.py     grpc.aio.secure_channel + keepalive   │
│     ├─ stt.py         stt_client.transcribe(...)            │
│     ├─ tts.py         tts_client.stream_pcm(...)            │
│     ├─ embed.py       embed_client.encode(...)              │
│     ├─ supervisor.py  supervisor_client.start/stop/status   │
│     └─ _pb/           generated proto stubs (gitignored)    │
│                                                              │
│   app/services/controllers/remote.py                        │
│     RemoteServiceController (kind="remote") thay             │
│     InternalController target=stt|tts trong services.yaml   │
└─────────────────────────────────────────────────────────────┘
```

### Khác biệt key so với hiện tại

- **`back-end/requirements.txt`** xóa: `torch`, `torchvision`, `torchaudio`,
  `transformers`, `kokoro`, `sentence-transformers`, `soundfile`. Thêm:
  `grpcio`, `grpcio-tools`, `protobuf`.
- **`back-end/app/services/`** xóa file: `stt_service.py`, `tts_service.py`,
  `embedding_service.py`. Thêm package `ai_client/`.
- **`tool_retriever.py`** và **`memory/embedder.py`** đổi từ in-process encode
  sang gRPC call (với LRU cache phía client để né round-trip lặp).
- **`InternalController`** mất 2 target `stt`, `tts`; embedding chưa từng có
  entry → thêm 1 entry `kind: remote` mới (`shore-ai`).
- **`/api/dashboard`** thêm nhóm `ai_components` (status-only) lộ trạng thái
  3 component STT/TTS/Embed.
- **Repo layout mới**: thêm `shore-ai-service/` (Python + Dockerfile) và
  `shore-ai-supervisor/` (Python, mỏng) song song với `shore-pty-service/`.

## gRPC proto + streaming contract

### Layout

```
shore-ai-service/proto/shore/ai/v1/
  ├─ stt.proto
  ├─ tts.proto
  ├─ embed.proto
  └─ health.proto

shore-ai-supervisor/proto/shore/supervisor/v1/
  └─ supervisor.proto
```

Backend copy proto qua build step và generate stub vào
`back-end/app/services/ai_client/_pb/` (gitignored, tái sinh bằng
`make proto`).

### `stt.proto` — unary

```proto
syntax = "proto3";
package shore.ai.v1;

service STT {
  rpc Transcribe(TranscribeRequest) returns (TranscribeResponse);
}

message TranscribeRequest {
  bytes  audio_f32  = 1;   // raw little-endian Float32 PCM, 16kHz mono
  string language   = 2;   // "en", "ja", "zh", "auto"
  string model_size = 3;   // optional: "base", "large-v3-turbo" (server default if empty)
}

message TranscribeSegment {
  double start = 1;
  double end   = 2;
  string text  = 3;
}

message TranscribeResponse {
  string text                         = 1;
  string language                     = 2;
  double language_prob                = 3;
  repeated TranscribeSegment segments = 4;
  string model                        = 5;
}
```

Rationale: utterance VAD-aligned ~2-10s = 64-320 KB float32 — gọn trong 1 unary
message (default gRPC 4MB limit). Không cần client-streaming.

### `tts.proto` — server-streaming

```proto
syntax = "proto3";
package shore.ai.v1;

service TTS {
  rpc Synthesize(SynthesizeRequest) returns (stream SynthesizeChunk);
}

message SynthesizeRequest {
  string text       = 1;   // 1 sentence per call
  string voice      = 2;   // "af_heart", "jf_alpha"... empty = server default
  string language   = 3;   // "en"|"ja"|"zh"
  uint32 chunk_size = 4;   // hint, default 8192
}

message SynthesizeChunk {
  bytes pcm_s16le = 1;     // 24kHz mono int16 PCM
  bool  is_last   = 2;
}
```

Rationale: giữ pattern hiện tại — `chat_ws.tts_worker` gọi 1 RPC cho mỗi
sentence. Backend relay từng `SynthesizeChunk.pcm_s16le` thẳng vào
`websocket.send_bytes`. Cancellation tự nhiên qua `grpc.aio.Call.cancel()`
khi user gửi message mới.

### `embed.proto` — unary batch

```proto
syntax = "proto3";
package shore.ai.v1;

service Embed {
  rpc Encode(EncodeRequest) returns (EncodeResponse);
}

message EncodeRequest {
  repeated string texts = 1;
  string          model = 2;   // optional override; default all-MiniLM-L6-v2
}

message Vector { repeated float values = 1; }

message EncodeResponse {
  repeated Vector vectors = 1;
  uint32          dim     = 2;
  string          model   = 3;
}
```

Rationale: batch để LOCOMO worker + canonicalizer chỉ tốn 1 round-trip cho
nhiều fact. Tool retriever vẫn dùng API batch với `len=1`.

### `health.proto` — unary

```proto
syntax = "proto3";
package shore.ai.v1;

service Health {
  rpc Get(GetRequest) returns (StatusResponse);
}

message GetRequest {}

message ComponentStatus {
  string name   = 1;   // "stt" | "tts" | "embed"
  bool   loaded = 2;
  string detail = 3;   // model size, voice...
}

message StatusResponse {
  bool                       ready      = 1;
  repeated ComponentStatus   components = 2;
  string                     version    = 3;
}
```

Dashboard poll qua backend (5s / 1s when transitioning) đã đủ; không cần
`Watch` streaming ở v1.

### `supervisor.proto` — control plane

```proto
syntax = "proto3";
package shore.supervisor.v1;

service Supervisor {
  rpc Start (TargetRequest) returns (ActionResponse);
  rpc Stop  (TargetRequest) returns (ActionResponse);
  rpc Status(TargetRequest) returns (StatusResponse);
}

message TargetRequest  { string target = 1; }   // "shore-ai"
message ActionResponse { bool ok = 1; string detail = 2; }
message StatusResponse {
  bool   running      = 1;
  string container_id = 2;
  string state        = 3;
}
```

`shore-ai-supervisor` chỉ shell ra
`docker compose -f /opt/shore-ai/docker-compose.yml {start|stop|ps -q} shore-ai`.
Path hard-code qua env, không nhận từ request — tránh command injection.

### Error mapping

| Scenario | gRPC code | Backend hành xử |
|---|---|---|
| Service không reach (network, dead) | `UNAVAILABLE` | STT: transcript rỗng + `status: "STT unreachable"`. TTS: skip silently. Embed: tool_retriever trả `ALWAYS_AVAILABLE` only; memory.embedder raise → MemoryFacade circuit breaker. |
| `RESOURCE_EXHAUSTED` (VRAM OOM) | `RESOURCE_EXHAUSTED` | Cùng nhánh `UNAVAILABLE`. |
| User cancel (mới gửi message) | `CANCELLED` | Bình thường, không log error. |
| Deadline | `DEADLINE_EXCEEDED` | Cùng nhánh `UNAVAILABLE`. |
| Bad request (audio rỗng…) | `INVALID_ARGUMENT` | Surface error string lên client. |

### Auth metadata

Backend gắn vào mọi call qua interceptor:

```python
metadata = (("authorization", f"Bearer {settings.SHORE_AI_TOKEN}"),)
```

Service-side: 1 server interceptor reject nếu thiếu/sai. Token rotate qua env
restart.

### Channel lifecycle

- 1 `grpc.aio.secure_channel` long-lived cho `shore-ai-service`, 1 cho
  `supervisor`.
- Keepalive: `grpc.keepalive_time_ms=20000`,
  `grpc.keepalive_timeout_ms=10000`.
- Reconnect: tự động qua gRPC channel state; backend không tự retry trên app
  layer (graceful degrade thay vì retry).

## Lifecycle, service control & Dashboard wiring

### `RemoteServiceController` (new file)

```
back-end/app/services/controllers/remote.py
```

`kind: "remote"`. Pattern giống các controller khác — atomic transitioning gate
đã được `ServiceManager` xử lý, nên không phải đụng `service_manager.py`.

```python
class RemoteServiceController(Controller):
    """Controls a remote service via shore-ai-supervisor over gRPC."""

    def __init__(self, name, *, display_name, target: str,
                 correlates_with: str | None = None,
                 supervisor_client=None):
        super().__init__(name, display_name=display_name,
                         correlates_with=correlates_with)
        self._target = target           # "shore-ai"
        self._sup    = supervisor_client

    @property
    def kind(self) -> ServiceKind: return "remote"

    async def is_running(self) -> bool:
        try:
            st = await self._sup().status(self._target)
            return st.running
        except grpc.aio.AioRpcError:
            return False

    async def start(self): await self._sup().start(self._target)
    async def stop (self): await self._sup().stop (self._target)
```

### `services.yaml` — 1 entry duy nhất

```yaml
services:
  shore-ai:
    kind: remote
    target: shore-ai
    display_name: "Shore AI (STT + TTS + Embed)"
    correlates_with: shore-ai
```

- 2 entry cũ `stt`, `tts` (kind=internal) **bị xóa**.
- 1 nút Start/Stop trên Dashboard → 1 action duy nhất (container up/down).

### `/api/dashboard` thay đổi

- **`services`**: thêm row `shore-ai` (control merged từ services.yaml).
- **`ai_components`** (nhóm mới, status-only — không control): 3 row `stt`,
  `tts`, `embed`, status từ 1 lần gọi `health_client.get()`/poll. Hiển thị
  `loaded=true/false`, `detail` (model size / voice). Nếu container down,
  nhóm này hiện "—" + ô màu xám.
- **`hardware`**: ô GPU mới cho GPU machine (mượn pattern
  `REMOTE_SERVER_GLANCES_URL` đã có).

### `back-end/.env` thêm config

```
SHORE_AI_GRPC_URL=ai.shore-keeper.com:443
SHORE_AI_SUPERVISOR_GRPC_URL=ai.shore-keeper.com:8443
SHORE_AI_TOKEN=<bearer>
SHORE_AI_TIMEOUT_SECONDS=30
SHORE_AI_EMBED_TIMEOUT_SECONDS=10
SHORE_AI_TTS_FIRST_CHUNK_TIMEOUT_SECONDS=15
```

`useDashboardPoll` không cần đổi — vẫn 5s / 1s when transitioning.

### Backend bootstrap thay đổi

**Xóa**:

- `stt_service.warmup()` / `load_model()` calls.
- `tts_service.warmup()` calls.
- `embedding_service` singleton init.

**Thêm**:

- `ai_client.channel.init()` — tạo 2 gRPC channel + interceptor bearer; KHÔNG
  block startup nếu service unreachable (channel sẽ tự reconnect).
- `ai_client.channel.close()` trong `app.on_event("shutdown")`.

`runtime_flags` STT_ENABLED, TTS_ENABLED **bỏ hoàn toàn**.
WORKER_ENABLED, CANONICALIZER_ENABLED giữ nguyên — vẫn in-process toggle.

### Frontend Dashboard

- Row `Shore AI (STT + TTS + Embed)` với nút Start/Stop (Stop qua Radix confirm
  dialog, giống hiện tại).
- Section "AI Components" (mới): 3 row read-only `STT base`, `TTS af_heart`,
  `Embed MiniLM-L6-v2` với chấm xanh/đỏ.
- Bỏ entry `STT`/`TTS` khỏi `services`.

### `tool_retriever.py` & `memory/embedder.py`

- Đổi `from app.services.embedding_service import ...` →
  `from app.services.ai_client.embed import embed_client`.
- Encode call sync → **async** (sentence-transformers là sync; gRPC.aio là
  async). Mọi caller của `tool_retriever.initialize/reindex/retrieve` phải
  `await`.
- Tool description matrix vẫn cache local — `initialize()` và `reindex()`
  gọi `embed_client.encode(texts)` 1 lần rồi convert sang numpy array
  `_tool_embeddings` (giữ y nguyên cosine math). Query encode lại mỗi turn,
  không cache.
- `memory.embedder`: encode trên write-path (LOCOMO worker batch nhiều fact)
  và read-path (assemble_context query). Không cần cache.
- gRPC trả `list[list[float]]`; convert sang `np.array(...)` ngay tại điểm
  nhận cho hot path cosine math.
- Khi service unreachable: `tool_retriever` fallback trả `ALWAYS_AVAILABLE`
  only; `memory.embedder` raise riêng để `MemoryFacade` apply circuit breaker
  có sẵn (500 ms per-layer).

### Cold-start UX

1. Backend up — chat keyboard sẵn sàng ngay (LLM via llama-server vẫn rời).
2. Nếu shore-ai container chưa chạy: dashboard row đỏ, user nhấn Start →
   supervisor `docker compose start` → ~5-15s sau model load xong →
   component chuyển xanh → STT/TTS hoạt động.
3. Nếu shore-ai down giữa chừng: voice input nhận transcript rỗng + status,
   chat tiếp tục bằng keyboard, TTS skip im lặng. Mọi thứ tự khôi phục khi
   service xanh lại — không cần restart backend.

## Testing strategy

| Layer | Approach |
|---|---|
| **Backend unit** | Mock gRPC stubs với dependency injection (đã có pattern ở `InternalController`). `ai_client.stt`/`tts`/`embed`/`supervisor` nhận `channel=` hoặc `stub=` cho test. Test cancellation, timeout, error mapping → ngoại lệ chuẩn (`UNAVAILABLE` → fallback empty). |
| **Backend integration** | `pytest` fixture chạy `FakeShoreAiServer` (Python stub gRPC trên `127.0.0.1:0`, echo dummy). STT trả text cố định, TTS yield 3 chunk PCM, Embed trả vector cố định, Supervisor đếm calls. Test cancel/relay/error paths. |
| **shore-ai-service unit** | Test trong package shore-ai-service riêng. STT: silent audio → `text=""`. TTS: `"hello"` → ít nhất 1 chunk > 0 byte. Embed: vector cùng `dim`. |
| **shore-ai-service smoke** | Script `make smoke` build Docker image + `docker run --gpus all` + gọi 1 lần mỗi RPC. Chạy trên GPU machine, không CI. |
| **E2E** | Manual `scripts/e2e_chat.py` — boot backend, mock frontend qua WS, gửi audio file, kiểm tra TTS PCM chảy về. Không CI. |

## Migration order

Mỗi bước phải bảo đảm `python -m uvicorn app.main:app` boot sạch trước khi
merge.

1. **Proto + skeleton service** — scaffold `shore-ai-service/` +
   `shore-ai-supervisor/`, sinh stub Python, Dockerfile, docker-compose;
   chưa wire backend.
2. **`ai_client` package + `FakeShoreAiServer` test fixture** — chưa thay
   trong backend; chỉ thêm.
3. **`RemoteServiceController`** — thêm class + test, chưa đăng ký vào
   `services.yaml`.
4. **Migrate Embedding** — đẩy `tool_retriever.py` và `memory/embedder.py`
   qua `embed_client`. Xóa `embedding_service.py`. Validate: tool retrieval +
   memory write vẫn work khi shore-ai chạy local container; degrade khi tắt.
5. **Migrate STT** — đổi `chat_ws.py` STT call site từ
   `stt_service.transcribe_async` → `stt_client.transcribe`. Xóa
   `stt_service.py`. Xóa target `stt` khỏi `InternalController` +
   `services.yaml`. Test voice input.
6. **Migrate TTS** — đổi `tts_worker` từ `tts_service.synthesize_stream_pcm`
   → `tts_client.stream_pcm`. Text sanitize vẫn ở backend. Xóa
   `tts_service.py` + target `tts`. Test voice output.
7. **Wire `shore-ai` vào `services.yaml`** + Dashboard frontend update.
8. **Cleanup `requirements.txt`** — xóa `torch`, `torchvision`, `torchaudio`,
   `transformers`, `kokoro`, `sentence-transformers`, `soundfile`. Kiểm tra
   `numpy` còn dùng ở `audio_utils` không trước khi xóa.
9. **Cleanup `runtime_flags`** — xóa `STT_ENABLED`, `TTS_ENABLED` keys + chỗ
   đọc.

Từ bước 4 trở đi, backend boot được không cần GPU machine (graceful degrade).

## Edge cases

| Tình huống | Hành xử |
|---|---|
| Container đang load model, user nhấn voice | STT `UNAVAILABLE` → transcript rỗng + status "STT loading". Frontend đã handle status bình thường. |
| Container restart giữa TTS stream | End-of-stream sớm → `tts_worker` đã `try/except`, send `tts_end`. User nghe câu cụt — chấp nhận được. |
| Backend restart giữa TTS stream | gRPC peer disconnect → container hủy task TTS local, không leak. |
| User gửi message mới khi TTS đang chảy | Backend `agent_task.cancel()` (đã có). `tts_worker` cancel → close gRPC call → container ngắt synth. |
| Bearer token rotation | Đổi `SHORE_AI_TOKEN` env → restart backend + container. Không hot-reload. |
| Audio Float32 > 4MB (default gRPC msg limit) | Reject `INVALID_ARGUMENT`. Thực tế utterance ~10s là 640KB — an toàn. Không nâng `max_send_message_length`. |
| Supervisor `Start` khi đã running | `docker compose start` idempotent. Trả `ok=true, detail="already running"`. ServiceManager `transitioning` set bảo vệ concurrent call. |
| Supervisor `Stop` khi đã stopped | Tương tự — idempotent. |
| shore-ai container OOM khi load model lớn | `Health.Get` trả `ready=false`, `detail="OOM loading large-v3"`. Dashboard hiện đỏ + tooltip. |
| Tool retriever cần embed nhưng shore-ai down | Trả chỉ `ALWAYS_AVAILABLE` tools. LLM vẫn chạy, chỉ thiếu domain tools. |
| LOCOMO worker fire khi embed unavailable | Per-step try/except + Redis lock TTL 60s. Skip extraction, retry idle sau. |
| Canonicalizer cron fire khi embed down | Job log lỗi, exit; APScheduler chạy lại sáng hôm sau. |

## Performance budget (LAN ~0.5ms RTT)

| Path | Overhead thêm |
|---|---|
| STT unary (1 utterance ~256KB) | ~3-5 ms TLS+serialize; Whisper compute 200-1500ms — overhead < 1%. |
| TTS server-streaming first chunk | ~5-10 ms first-byte latency thêm; chunks tiếp theo cùng tốc độ Kokoro CPU. |
| Embed batch | ~3-5 ms cho 1 vector dim 384. Tool description matrix encode 1 lần tại `initialize`/`reindex` — vẫn 0 overhead trên hot path query. |
| Supervisor Status (poll 5s) | ~3 ms, negligible. |

**Acceptable** — đặc biệt khi cùng LAN. GPU machine ở xa: TTS first-chunk
latency là điểm cần để ý sau.

## Dev experience không có GPU machine

- Boot 1 instance `shore-ai-service` trên Docker localhost (CPU fallback cho
  Whisper tiny + Kokoro; CPU embed). Chậm ~10x nhưng chạy.
- `SHORE_AI_GRPC_URL=localhost:9200`, không TLS, `SHORE_AI_TOKEN=dev`.
- Hoặc dùng `FakeShoreAiServer` qua fixture nếu chỉ dev frontend / chat
  keyboard.

## Files changed (summary)

### Thêm

- `shore-ai-service/` — Python service, Dockerfile, docker-compose, proto.
- `shore-ai-supervisor/` — Python supervisor, systemd unit hoặc launcher.
- `back-end/app/services/ai_client/` — package gRPC client.
- `back-end/app/services/controllers/remote.py` — `RemoteServiceController`.
- `docs/superpowers/specs/2026-06-07-stt-tts-embed-grpc-microservice-design.md`
  (file này).

### Sửa

- `back-end/requirements.txt` — bỏ AI deps, thêm gRPC.
- `back-end/app/main.py` — bootstrap đổi.
- `back-end/app/api/websockets/chat_ws.py` — STT/TTS call sites đổi imports.
- `back-end/app/api/endpoints/dashboard.py` — thêm `ai_components` group.
- `back-end/app/services/tool_retriever.py` — dùng `embed_client`.
- `back-end/app/services/memory/embedder.py` — dùng `embed_client`.
- `back-end/app/services/controllers/internal.py` — bỏ target `stt`, `tts`.
- `back-end/app/services/service_manager.py` — thêm kind `remote` vào loader.
- `back-end/app/core/runtime_flags.py` — bỏ STT_ENABLED, TTS_ENABLED.
- `back-end/app/core/config.py` — thêm `SHORE_AI_*` settings.
- `back-end/config/services.example.yaml` — thêm entry `shore-ai`.
- `front-end/src/services/dashboard.service.ts` — type cho `ai_components`.
- `front-end/src/pages/Dashboard/index.tsx` — render group mới.

### Xóa

- `back-end/app/services/stt_service.py`.
- `back-end/app/services/tts_service.py`.
- `back-end/app/services/embedding_service.py`.

## Open questions (chừa cho plan phase)

- Tên domain cuối cùng (gợi ý `ai.shore-keeper.com`) — phụ thuộc Caddy/nginx
  config hiện tại.
- Image base cho `shore-ai-service`: `nvidia/cuda:12.9.0-runtime-ubuntu24.04`
  hay `python:3.12-slim` + CUDA wheel? Quyết định khi build.
- `shore-ai-supervisor` đóng gói: systemd unit native hay Docker container
  (nhưng container cần `/var/run/docker.sock` mount — vẫn khả thi).
