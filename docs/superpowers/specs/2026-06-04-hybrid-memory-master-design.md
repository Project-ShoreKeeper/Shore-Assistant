# Hybrid Memory Architecture — Master Design

**Date:** 2026-06-04
**Status:** Design (approved, awaiting user spec review)
**Scope:** Shore Assistant back-end (Python / FastAPI)
**Author:** Luna + Shore Assistant brainstorming session

This is the **Master Spec**. It defines the overall architecture, data
contracts, runtime pipelines, and phase boundaries for replacing the current
JSON-file `memory_service.py` with a layered hybrid memory system built on
**Redis (short-term) + Postgres (profile) + Qdrant (episodic)** with a
**Gemini 2.5 Flash LOCOMO worker** for asynchronous fact / emotion extraction.

Each implementation phase below will have its own sub-spec that elaborates
the details left intentionally abstract here.

---

## 1. Goals and Non-Goals

### Goals

1. Define the overall architecture for a layered hybrid memory: Short-term
   (Redis) + Profile (Postgres JSONB + audit log) + Episodic (Qdrant
   distilled facts) + asynchronous LOCOMO worker.
2. Specify **data contracts** between layers (Redis list element shape,
   Postgres schema, Qdrant payload schema, Pydantic models) so each phase
   can be implemented independently and still interoperate.
3. Specify the **runtime pipelines** for the read path (chat turn,
   synchronous, target <100ms memory overhead) and the write path (worker,
   idle-triggered, asynchronous).
4. Carve **phase boundaries** so P1, P2, and P3 each ship standalone value
   and can be released incrementally with feature-flag rollback.
5. Identify risks and rollback paths.

### Non-Goals

- Per-phase code-level implementation detail — that belongs in each phase's
  sub-spec.
- Multi-user identity, auth, or tenancy. Shore Assistant remains
  single-user (the implicit "Luna").
- Migrating the existing `data/memory/default.json` sliding window. The
  legacy store is deprecated; old history is not preserved into the new
  system.
- Frontend UI for memory introspection (deferred to optional Phase 4).
- Disaster-recovery / backup tooling (separate ops spec).

### Non-negotiable constraints

- **VRAM budget**: the existing 16 GB budget is owned by Whisper + the
  primary multimodal llama-server model. The DB stack runs on a separate
  always-on LAN server (CPU only); no new GPU consumers are introduced on
  the AI machine.
- **Redis as source of truth for short-term**: AOF persistence is mandatory
  (`appendonly yes`, `appendfsync everysec`). Redis is not a cache here.
- **Async I/O everywhere**: all DB clients (`asyncpg`, `redis.asyncio`,
  `qdrant-client` async API) must not block the FastAPI event loop.

---

## 2. System Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                    AI MACHINE (RTX 5060 Ti, Windows)                  │
│                                                                       │
│  ┌────────────┐  ┌──────────────┐  ┌────────────┐  ┌────────────┐    │
│  │ llama-     │  │ Whisper STT  │  │ Kokoro TTS │  │ FastAPI    │    │
│  │ server     │  │ (Transformers│  │ (CPU)      │  │ back-end   │    │
│  │ (GPU)      │  │  GPU)        │  │            │  │ (Python)   │    │
│  └────────────┘  └──────────────┘  └────────────┘  └─────┬──────┘    │
│                                                          │           │
│       ┌──────────────────────────────────────────────────┴─────┐     │
│       │              app/services/memory/  (new package)        │     │
│       │                                                          │     │
│       │   ┌────────────────────────────────────────────────┐    │     │
│       │   │  MemoryFacade  (single entry-point for chat)   │    │     │
│       │   └─┬──────────────┬──────────────┬────────────┬───┘    │     │
│       │     │              │              │            │        │     │
│       │  ┌──▼──────┐  ┌────▼──────┐  ┌───▼──────┐  ┌──▼─────┐  │     │
│       │  │ short_  │  │ profile   │  │ episodic │  │worker  │  │     │
│       │  │ term.py │  │ .py       │  │ .py      │  │.py     │  │     │
│       │  └──┬──────┘  └────┬──────┘  └────┬─────┘  └────┬───┘  │     │
│       │     │              │              │             │      │     │
│       │  ┌──▼──────────────▼──────────────▼─────────────▼───┐  │     │
│       │  │ embedder.py    (reuses all-MiniLM-L6-v2)         │  │     │
│       │  │ canonicalizer.py (entity-tag dedup job)          │  │     │
│       │  │ types.py       (Pydantic schemas — contracts)    │  │     │
│       │  └──────────────────────────────────────────────────┘  │     │
│       └─────┬──────────────┬──────────────┬────────────┬───────┘     │
└─────────────┼──────────────┼──────────────┼────────────┼─────────────┘
              │              │              │            │
              │ asyncpg      │ redis.asyncio│ qdrant-    │ Gemini
              │              │              │ client     │ REST
              │              │              │            │
┌─────────────▼──────────────▼──────────────▼────────┐  │ ┌──────────┐
│              LAN SERVER 24/7 (Docker stack)         │  │ │ Google   │
│                                                     │  └─►│ Gemini   │
│  ┌──────────────┐ ┌──────────────┐ ┌────────────┐  │    │ 2.5 Flash│
│  │ Postgres 16  │ │ Redis 7      │ │ Qdrant     │  │    │ (cloud)  │
│  │ (profile +   │ │ (short-term  │ │ (episodic  │  │    └──────────┘
│  │  audit log)  │ │  AOF enabled)│ │  vectors)  │  │
│  └──────────────┘ └──────────────┘ └────────────┘  │
└─────────────────────────────────────────────────────┘
```

### Key architectural decisions

- **`app/services/memory/` package**, not a single `memory_service.py`. Each
  layer is its own module with a narrow async interface; `MemoryFacade` is
  the single façade that `chat_ws.py` and `agent_service.py` interact with.
- **`embedder.py` reuses the `all-MiniLM-L6-v2` model** that
  `tool_retriever` already loads, so no extra model is spawned.
- **All I/O async**: `asyncpg`, `redis.asyncio`, `qdrant-client` async.
- **Worker runs inside the FastAPI process** via `asyncio.Task`, not Celery
  or ARQ. Trade-off: a back-end restart mid-extraction loses that
  extraction, but because the worker is idle-triggered and idempotent
  (append-only), the next fire re-extracts the same turns.
- **LAN server is a single point of failure**. The `MemoryFacade` must
  implement per-layer circuit breakers so chat degrades gracefully rather
  than failing outright.
- **Gemini is a write-path dependency only**. The read path (chat turn)
  never calls Gemini; if Gemini is down only extraction is affected.

### Alternatives considered and rejected

- **External worker (Celery + Redis broker)**: adds a service for what is
  ultimately a single-user idle trigger. Rejected as overkill.
- **gRPC between back-end and DB stack**: native async clients are simpler
  and sufficient on LAN.
- **Reusing llama-server as the worker LLM**: considered, but cloud-API
  worker chosen so VRAM is not contended and extraction quality stays
  consistent regardless of which primary model is loaded.

---

## 3. Data Contracts

### 3.1 Redis (Short-term Memory)

Single key, LIST type, sliding window. Single-user so no namespacing is
required.

```
Key:    shore:short_term:messages
Type:   LIST  (LPUSH new, LTRIM to MEMORY_MAX_TURNS*2)
Window: MEMORY_MAX_TURNS = 15 turns = 30 messages
```

Each element is a JSON-encoded `Message`:

```json
{
  "role": "user" | "assistant" | "system",
  "content": "string",
  "timestamp": 1717459200.123,
  "extras": {
    "thinking": "...",
    "tool_calls": [...],
    "attachments": [{"type": "image", "mime": "...", "data_b64": "..."}]
  }
}
```

`extras` is optional and assistant-only.

**Operations:**

- `append(message)` → `LPUSH` + `LTRIM 0 (max*2 - 1)`
- `load()` → `LRANGE 0 -1`, then reverse (LPUSH places newest at index 0)
- `clear()` → `DEL`

**Persistence:** `appendonly yes`, `appendfsync everysec`. Worst case a
power loss costs ≤1 s of recent turns; that is acceptable.

### 3.2 Postgres (Profile Memory)

Two tables: a single-row snapshot of current state, plus an append-only
audit log.

```sql
-- Current profile snapshot (single row, JSONB)
CREATE TABLE profile (
    id          SMALLINT PRIMARY KEY DEFAULT 1
                CHECK (id = 1),                  -- enforce 1-row table
    data        JSONB NOT NULL DEFAULT '{}',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Append-only audit log
CREATE TABLE profile_history (
    id              BIGSERIAL PRIMARY KEY,
    key_path        TEXT NOT NULL,               -- e.g. 'favorite_coffee'
                                                 -- or  'projects.shore_assistant.status'
    old_value       JSONB,                       -- null on insert
    new_value       JSONB,                       -- null on delete
    source_turn_ts  DOUBLE PRECISION,            -- ts of the turn that produced this change
    confidence      REAL,                        -- Gemini self-reported (0-1)
    reason          TEXT,                        -- worker single-line explanation
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_profile_history_key
    ON profile_history(key_path, created_at DESC);
```

**Example `profile.data` JSONB** (free-form, no whitelist):

```json
{
  "name": "Luna",
  "favorite_coffee": "espresso no sugar",
  "tech_stack": ["python", "typescript", "cuda"],
  "current_projects": {
    "shore_assistant": {"status": "active", "phase": "hybrid memory"}
  }
}
```

The worker may invent new keys freely. The Phase 3 canonicalizer will
later dedup near-duplicate keys (e.g. `favorite_coffee` vs `coffee_pref`).

**Operations:**

- `read()` → `SELECT data FROM profile WHERE id = 1`
- `apply_change(ProfileChange)` → transactional: select current value,
  apply `jsonb_set`/`jsonb_path_set`, insert into `profile_history`,
  commit.
- `history(key_path, limit)` → audit log query for debug / rollback.

### 3.3 Qdrant (Episodic Memory)

```
Collection:  shore_episodic
Vector size: 384  (all-MiniLM-L6-v2)
Distance:    Cosine
On-disk:     true
```

**Point payload schema** — the contract between worker (writes) and
retriever (reads):

```python
{
    "fact": str,                       # distilled fact, 1-3 sentences
    "entity_tags": list[str],          # ["shore_assistant", "cuda"]
    "emotion": {                       # Plutchik 8 + intensity
        "joy": 0.0,
        "trust": 0.6,
        "fear": 0.0,
        "surprise": 0.1,
        "sadness": 0.0,
        "disgust": 0.0,
        "anger": 0.0,
        "anticipation": 0.4,
    },
    "valence": 0.5,                    # derived shortcut (-1..1)
    "source_turn_ts": 1717459200.123,
    "source_role": "user" | "assistant",
    "created_at": 1717459205.456,
    "confidence": 0.82,                # Gemini self-reported
    "embedding_model_version": "all-MiniLM-L6-v2",
}
```

**Indexed payload fields** for Qdrant filters: `entity_tags` (keyword
list), `created_at` (range), `valence` (range).

**Operations:**

- `upsert(EpisodicFact)` → embed `fact` → upsert point with deterministic
  point_id (see §4.2).
- `search(query_text, entity_filter=[], top_k=5, min_score=0.3)` → embed
  query → vector search with optional `entity_tags` filter.

### 3.4 Shared Pydantic types (`types.py`)

```python
class Message(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str
    timestamp: float
    extras: dict | None = None


class EmotionVector(BaseModel):
    joy: float = 0.0
    trust: float = 0.0
    fear: float = 0.0
    surprise: float = 0.0
    sadness: float = 0.0
    disgust: float = 0.0
    anger: float = 0.0
    anticipation: float = 0.0

    @property
    def valence(self) -> float:
        pos = self.joy + self.trust + self.anticipation
        neg = self.fear + self.sadness + self.disgust + self.anger
        return max(-1.0, min(1.0, (pos - neg) / 4.0))


class EpisodicFact(BaseModel):
    fact: str
    entity_tags: list[str]
    emotion: EmotionVector
    source_turn_ts: float
    source_role: Literal["user", "assistant"]
    confidence: float = Field(ge=0.0, le=1.0)


class ProfileChange(BaseModel):
    key_path: str
    new_value: Any | None              # None == delete
    source_turn_ts: float
    confidence: float
    reason: str


class WorkerOutput(BaseModel):
    profile_changes: list[ProfileChange]
    episodic_facts: list[EpisodicFact]
```

`WorkerOutput` is the sole contract between Gemini and the write side.

### 3.5 Settled defaults from brainstorming

- `MEMORY_MAX_TURNS = 15` (overriding the legacy default of 20, per design
  brief).
- Gemini self-reported `confidence` is accepted as-is. Calibration may be
  revisited in Phase 4 if extraction quality is poor.

---

## 4. Runtime Pipelines

Two pipelines run separately: a synchronous **read path** for chat turns
(latency-budgeted) and an asynchronous **write path** for the worker.

### 4.1 Read Path — Chat Turn Flow

```
User sends message
       │
       ▼
┌─────────────────────────────────────────────────────────────┐
│ chat_ws.py: receive text/audio                               │
│   1. STT if audio → user_text                                │
│   2. Reset idle-timer (cancel pending worker)                │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ MemoryFacade.assemble_context(user_text)                     │
│ — fire 3 queries in parallel (asyncio.gather):               │
│                                                              │
│   ┌──────────────────┐  ┌────────────┐  ┌────────────────┐  │
│   │ short_term.load()│  │ profile.   │  │ episodic.      │  │
│   │ → list[Message]  │  │ read()     │  │ search(        │  │
│   │   (15 turns)     │  │ → dict     │  │   user_text,   │  │
│   │                  │  │            │  │   top_k=5,     │  │
│   │                  │  │            │  │   min_score=.3)│  │
│   │                  │  │            │  │ → [Fact]       │  │
│   └──────────────────┘  └────────────┘  └────────────────┘  │
│                                                              │
│   → ContextBundle(profile, episodic_hits, short_term)        │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ agent_service.run() — build messages                         │
│                                                              │
│   system prompt =                                            │
│     base persona (kuudere.txt)                               │
│     + tools.txt                                              │
│     + auto-injected current time                             │
│     + "[Profile]\n<JSONB pretty-printed>"                    │
│     + "[Relevant memories]\n- fact1 (ent: shore, joy=0.6)    │
│                            \n- fact2 ..."                    │
│                                                              │
│   messages = [system] + short_term + [user_text]             │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ llama-server → token stream                                  │
│   ├─ frontend receives tokens (text)                         │
│   ├─ TTS sentence-by-sentence (Kokoro)                       │
│   └─ on completion: short_term.append(user) +                │
│                     short_term.append(assistant)             │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
                  Start idle-timer (30s)
```

**Latency budget (target, LAN local Docker stack):**

| Step | Budget |
|------|--------|
| `short_term.load` | <5 ms |
| `profile.read` | <10 ms |
| `episodic.search` (embed + Qdrant) | <50 ms |
| Total pre-LLM memory overhead | ~50-70 ms |

**Circuit breaker:** any of the 3 layers timing out (>500 ms) returns an
empty fragment for that layer and logs a warning. The agent still runs in
degraded mode rather than failing.

### 4.2 Write Path — Worker Flow (Idle-Triggered)

```
After assistant finishes streaming (read path ends)
       │
       ▼
┌─────────────────────────────────────────────────────────────┐
│ chat_ws.py:                                                  │
│   if pending_worker_task: pending_worker_task.cancel()       │
│   pending_worker_task = asyncio.create_task(                 │
│       worker.schedule_extract(delay=30.0)                    │
│   )                                                          │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
                   asyncio.sleep(30)
                   (cancelled if user sends a new turn)
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ worker.extract():                                            │
│                                                              │
│   1. Read short_term + last_extracted_ts                     │
│      (Redis key: shore:worker:last_extracted_ts).            │
│                                                              │
│   2. unprocessed = [m for m in short_term                    │
│                    if m.timestamp > last_extracted_ts]       │
│      If len(unprocessed) == 0 → return.                      │
│                                                              │
│   3. Build Gemini prompt:                                    │
│        - System: LOCOMO extractor instructions + JSON        │
│          schema (Plutchik 8 + intensity, ProfileChange).     │
│        - User: serialized turns.                             │
│        - Current profile (so worker can detect conflicts /   │
│          existing keys).                                     │
│                                                              │
│   4. Call Gemini 2.5 Flash with JSON mode →                  │
│      WorkerOutput(profile_changes, episodic_facts)            │
│                                                              │
│   5. Apply:                                                  │
│      - For each ProfileChange:                               │
│          profile.apply_change(...) (transactional)           │
│      - For each EpisodicFact:                                │
│          point_id = uuid5(NAMESPACE_FACT,                    │
│                           f"{turn_ts}:{role}:{fact_hash}")   │
│          embedding = embedder.encode(fact.fact)              │
│          episodic.upsert(point_id, embedding, payload)       │
│                                                              │
│   6. Set last_extracted_ts = max(unprocessed.timestamp).     │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
              Idempotent: if step 5 crashes, the next
              fire re-extracts the same turns; Postgres is
              latest-wins, Qdrant upsert by deterministic
              point_id avoids duplicate vectors.
```

**Idempotency:**

- `point_id = uuid5(NAMESPACE, f"{source_turn_ts}:{source_role}:{fact_hash}")`
  — re-runs do not create duplicates.
- `last_extracted_ts` is committed only after step 5 succeeds, so no turn
  is ever skipped because of a crash.

**Concurrency:**

- At most one worker task runs at any moment, guarded by `asyncio.Lock`
  plus a `SETNX shore:worker:lock` in Redis.
- If the user chats continuously for <30 s gaps the worker never fires —
  starvation risk. **Mitigation:** if
  `len(unprocessed) >= MAX_UNPROCESSED_MESSAGES`, fire immediately
  regardless of idle. `MAX_UNPROCESSED_MESSAGES = 20` (= 10 turns), which
  is well within the 30-message Redis window so no message can be evicted
  before extraction.

### 4.3 Canonicalizer (Phase 3)

Free-text entity tags can drift (`cuda`, `CUDA`, `cuda_12.9`,
`gpu_cuda`). A separate scheduled job (nightly, via existing APScheduler)
runs:

1. List all unique `entity_tags` in Qdrant payloads.
2. Embed each tag with MiniLM.
3. Greedy cluster: tags A and B with cosine >0.85 merge. The canonical
   form is the tag with the highest count.
4. Update affected Qdrant points: replace B with A in their payload.

Not on the chat-turn hot path, so it has no latency impact.

---

## 5. Phase Boundaries

### Phase 1 — Infra + Redis Short-term

**Goal:** Stand up the Docker stack on the LAN server, replace
`memory_service.py` JSON files with a Redis sliding window. When done, chat
behaves exactly as today; only the storage backend has changed.

**Scope:**

- `docker-compose.memory.yml`: Postgres 16, Redis 7 (AOF), Qdrant — all
  three brought up even though only Redis is used in P1 (avoids editing
  compose twice).
- `app/services/memory/` package skeleton: `types.py`, `short_term.py`,
  `embedder.py`, `MemoryFacade` (with stub Profile / Episodic).
- `short_term.py`: async wrapper over `redis.asyncio`. Methods:
  `load() -> list[Message]`, `append(Message)`, `clear()`, `health()`.
- Refactor `chat_ws.py` and `agent_service.py` to call `memory.short_term`
  instead of `memory_service`.
- Delete `app/services/memory_service.py`. Delete `data/memory/`. Remove
  `MEMORY_DIR` config.
- New config: `REDIS_URL`, `REDIS_SHORT_TERM_KEY`, `MEMORY_MAX_TURNS`
  (name preserved).
- `clear_memory` tool now `DEL`s the Redis key.

**Acceptance:**

- Chat WS works across back-end restart; context restored from Redis.
- `redis-cli FLUSHDB` mid-session → chat continues but loses history
  (degraded-mode test).
- Postgres + Qdrant containers UP, untouched by code, health endpoint
  green.
- `MemoryFacade.assemble_context()` returns a properly shaped
  `ContextBundle` with empty Profile and Episodic fragments.

**Out of scope:** retrieval, profile reads/writes, worker.

### Phase 2 — Profile (Postgres) + Episodic (Qdrant), manual population

**Goal:** Bring Profile and Episodic stores fully online and wire them
into the read path. The worker is **not** built yet — facts are seeded
manually via debug endpoints to verify retrieval.

**Scope:**

- `profile.py`: asyncpg pool. Methods: `read() -> dict`,
  `apply_change(ProfileChange)` transactional, `history(key_path, limit)`.
- `episodic.py`: async qdrant client. Methods: `upsert(EpisodicFact)`,
  `search(query, entity_filter, top_k, min_score) -> list[ScoredFact]`,
  `count()`.
- `embedder.py`: reuse `tool_retriever`'s `SentenceTransformer` (refactor
  to expose a shared `encode()`).
- SQL migrations: create `profile`, `profile_history`, seed the single
  `profile` row with `data='{}'`.
- Qdrant collection creation script (idempotent — check exists first).
- `MemoryFacade.assemble_context()` fully implemented — `asyncio.gather`
  the 3 sources, build the system-prompt injection block.
- **Debug endpoints** (gated by `DEBUG_MEMORY=True`):
  - `POST /api/memory/profile/change`
  - `POST /api/memory/episodic/upsert`
  - `GET  /api/memory/episodic/search?q=...`
- System-prompt formatting in `llm_service.build_system_prompt`:
  - `[Profile]\n<JSON pretty>\n\n[Relevant memories]\n- ...`
  - Cap Profile JSON size (~2 KB); if exceeded, prune by recency.
  - Cap Episodic hits at 5 facts, total ~500 tokens.
- Circuit breaker: 500 ms per-call timeout, fallback empty fragment.

**Acceptance:**

- Manual `ProfileChange` → next chat turn includes Profile in system
  prompt.
- Manual `EpisodicFact` upsert with an `entity_tag` → semantically related
  query retrieves it and includes it in the system prompt.
- Postgres DOWN → chat works, warning logged, Profile fragment empty.
- Qdrant DOWN → same, Episodic fragment empty.
- Total memory overhead p95 <100 ms on LAN.

**Out of scope:** automatic extraction, complex conflict resolution,
canonicalizer.

### Phase 3 — LOCOMO Worker (Gemini Flash)

**Status:** Shipped 2026-06-05 (plan: `docs/superpowers/plans/2026-06-05-hybrid-memory-phase-3.md`).

**Goal:** Automate the write path. 30 s of idle after a turn → Gemini
extracts → Profile / Episodic updated.

**Scope:**

- `worker.py`:
  - `schedule_extract(delay=30)` — `asyncio.Task` with cancel-on-new-turn.
  - `extract()` — diff unprocessed turns, prompt Gemini, parse JSON, apply.
  - Safety valve: if `len(unprocessed) >= MAX_UNPROCESSED_MESSAGES`, fire
    immediately.
  - Idempotent `point_id`:
    `uuid5(NAMESPACE_FACT, f"{turn_ts}:{role}:{fact_hash}")`.
- `app/prompts/locomo_extractor.txt`: Gemini system prompt with the JSON
  schema (exported from the `WorkerOutput` Pydantic model).
- Gemini client: async `httpx`, JSON mode, retry with exponential backoff
  (max 2).
- Config: `GEMINI_API_KEY`, `GEMINI_MODEL=gemini-2.5-flash`,
  `WORKER_IDLE_DELAY_SECONDS=30`, `MAX_UNPROCESSED_MESSAGES=20`,
  `WORKER_ENABLED` (kill switch).
- `canonicalizer.py`: nightly APScheduler job (use existing
  `scheduler_service`). Greedy cluster entity tags at cosine >0.85, update
  Qdrant payloads in place.
- Debug endpoints removed (or kept behind `DEBUG_MEMORY`).
- Optional minor frontend ping: "memory updated" indicator after worker
  fire (otherwise deferred to Phase 4).

**Acceptance:**

- Have 5 turns of chat, idle 30 s → log shows worker fired → Postgres has
  ProfileChange(s) + Qdrant has new points.
- User sends another turn within 30 s → log shows the pending task was
  cancelled and no fire occurred.
- 20+ messages of continuous chat with no idle pause → safety valve fires
  the worker before any message is evicted.
- Gemini API down → worker fails gracefully, logs, no chat impact.
- Re-run worker over the same turns → no duplicate Qdrant points
  (idempotency test).
- Conflict test: turn 1 "I like tea", turn 5 "I hate tea" → audit log has
  both entries; `profile.data` reflects latest.

**Out of scope:** UI introspection, confidence recalibration.

### Phase 4 — Polish (optional, deferrable)

Not required for feature-complete:

- Frontend memory panel — Profile JSON viewer, recent Episodic list, audit
  log browser.
- Conflict-review UI — surface low-confidence changes for user confirm.
- Prometheus metrics — per-layer latency, worker success rate, Gemini
  token cost.
- Re-embedding job for embedding-model migrations.
- Backup script (Postgres dump + Qdrant snapshot).

### Dependency graph

- P1 blocks P2 (P2 needs the Redis short-term and memory package skeleton).
- P2 blocks P3 (worker writes to Profile and Episodic, which P2 builds).
- P4 is independent and may run at any time after P3.

---

## 6. Risks and Mitigations

| #   | Risk | Severity | Mitigation |
|-----|------|----------|------------|
| R1  | Redis crash loses short-term turns (AOF `everysec` can lose ≤1 s). | Med | AOF `everysec` is adequate for single-user. Add RDB snapshot every 5 min as fallback. Document that a power loss may cost 1-2 turns. |
| R2  | Gemini API down or rate-limited → worker cannot extract; Profile / Episodic go stale. | Low | Worker retries twice with exponential backoff; failure logged. Next fire re-extracts from `last_extracted_ts`. Chat is independent of Gemini. |
| R3  | Gemini self-reported confidence is poorly calibrated → wrong facts overwrite right ones. | Med | Accepted as-is under latest-wins. Audit log enables manual rollback. P4 may add a secondary verifier. |
| R4  | Entity-tag explosion before canonicalizer runs in P3. | Low | Canonicalizer ships with P3. In P2 (manual seed only) tag count is small. |
| R5  | LAN server maintenance → all three DBs down simultaneously. | Med | Circuit breaker → degraded chat. Frontend shows "memory offline" banner. Need a Docker-stack restart playbook. |
| R6  | Embedding-model drift if `all-MiniLM-L6-v2` is replaced — old vectors no longer comparable. | Low | Every point payload tagged with `embedding_model_version`. P4 includes a re-embedding job. |
| R7  | Profile JSONB bloats — worker invents keys freely → system prompt blows token budget. | Med | Hard cap of ~2 KB when injecting into the prompt; if exceeded, prune top-N by `updated_at` desc. Canonicalizer dedups near-duplicate keys. |
| R8  | Worker race condition — two extractions fire concurrently from a cancel bug. | High if it occurs | `asyncio.Lock` around `extract()`, plus `SETNX shore:worker:lock` in Redis. Idempotent `point_id` is a second line of defence. |
| R9  | PII leak via Gemini — chat turns are sent to a cloud API. | High depending on user | Document explicitly that the worker sends raw turns to Gemini. Provide `WORKER_ENABLED=False` kill switch. P4 may add PII redaction before sending. |
| R10 | Single-user "lock-in" — schema changes hurt if multi-user is wanted later. | Low | Documented; a `user_id` column with `DEFAULT 'luna'` can be added non-breaking. Trade-off accepted in §1. |

### Overall rollback path

- P1 ships → problem → revert PR → chat returns to JSON-based
  `memory_service.py`. Keep a backup of `default.json` for at least one
  week post-P1.
- P2 ships → problem → set `MEMORY_FACADE_DISABLE_RETRIEVAL=True` → chat
  behaves as in P1.
- P3 ships → problem → set `WORKER_ENABLED=False` → Profile / Episodic
  freeze, but the read path keeps working.

Each phase must ship its feature flags so a rollback never requires a
redeploy.

---

## 7. Testing Strategy

Each phase gates on three test tiers; do not advance until the lower tier
passes.

### 7.1 Unit tests (mocked DB clients)

Per module, no Docker stack required:

- `tests/memory/test_short_term.py` — mock `redis.asyncio` → assert
  LPUSH / LTRIM / LRANGE order, JSON serialization matches `Message`.
- `tests/memory/test_profile.py` — mock asyncpg pool → assert
  `apply_change` writes both tables in one transaction; audit row has
  correct `old_value` / `new_value` / `reason`.
- `tests/memory/test_episodic.py` — mock qdrant client → assert payload
  matches `EpisodicFact`; entity filter built in the right Qdrant filter
  syntax.
- `tests/memory/test_types.py` — Pydantic validation; `EmotionVector.
  valence` math; `ProfileChange` accepts `None` as delete; edge cases.
- `tests/memory/test_facade.py` — `assemble_context` with three mocked
  layers; verify `asyncio.gather` parallelism (timing assertion); circuit
  breaker when one layer raises.
- `tests/memory/test_worker.py` — mock Gemini client, fake `WorkerOutput`
  → idempotent point_id; `last_extracted_ts` only committed after apply;
  cancel-on-new-turn behavior.

### 7.2 Integration tests (real Docker stack)

Requires `docker-compose.memory.yml` running locally or in CI:

- `tests/integration/test_short_term_redis.py` — append 30 turns →
  `load()` returns the 15 latest in reverse-LPUSH order. Kill Redis
  mid-session → restart → `load()` returns correct data (AOF works).
- `tests/integration/test_profile_postgres.py` — apply 3 changes to the
  same key → final `data` is latest; `profile_history` has 3 rows in
  order; rollback by query works.
- `tests/integration/test_episodic_qdrant.py` — upsert 20 facts with
  mixed entity tags → search returns correct top-K by cosine + filter.
- `tests/integration/test_worker_pipeline.py` (Phase 3) — fake
  conversation, let worker fire, verify Postgres and Qdrant contents.
  Conflict scenario covered.

### 7.3 End-to-end / manual smoke (after every PR from P1 onward)

Run with real llama-server + chat UI:

- Start back-end → open chat UI → say "Tôi tên Luna, thích espresso,
  đang làm Shore Assistant".
- Wait 30 s → inspect Postgres `profile.data` → expect `name`,
  `favorite_coffee`, `current_projects.shore_assistant`.
- Inspect Qdrant → expect ≥1 `EpisodicFact` with `entity_tags` containing
  `shore_assistant` or `coffee`.
- Restart back-end → reopen chat → ask "Tôi thích uống gì?" → response
  must mention espresso.
- Verify via devtools: pre-LLM memory overhead <100 ms.

Negative path:

- `docker stop shore-redis` → send chat → response still streams, warning
  in log, optional frontend banner.
- `docker stop shore-qdrant` → response still streams; Profile still
  injected (Postgres up); Episodic block empty.

### 7.4 Test data and fixtures

- `tests/fixtures/sample_messages.json` — 30 realistic chat turns.
- `tests/fixtures/sample_worker_output.json` — expected `WorkerOutput`
  for the messages above (golden test for prompt regression).
- `tests/fixtures/sample_profile.sql` — seed `profile.data` for retrieval
  tests.

### 7.5 Performance budget (PR gate)

Each phase PR runs a simple perf check (not a formal benchmark):

| Metric | Budget |
|--------|--------|
| `short_term.load()` p95 | <10 ms |
| `profile.read()` p95 | <15 ms |
| `episodic.search(top_k=5)` p95 (includes embed) | <60 ms |
| `MemoryFacade.assemble_context()` p95 | <80 ms |
| Worker extract end-to-end | <8 s (Gemini dominates) |

Over budget → flag in PR description; decide ship-or-tune.

### 7.6 Explicitly out of scope for tests

- Gemini output correctness (that is model behavior, not code). Golden
  tests cover the **JSON shape** only, not content.
- Multi-user concurrency — single-user, skip.
- Distributed failure modes (network partition) — LAN trust model.

---

## 8. Open Items and Future Sub-Specs

- **Phase 1 sub-spec** — `2026-XX-XX-hybrid-memory-phase-1-design.md`
  (next, to be brainstormed after this Master Spec is approved).
- **Phase 2 sub-spec** — after Phase 1 ships.
- **Phase 3 sub-spec** — after Phase 2 ships.
- **Phase 4 sub-spec** — optional, only if and when polish work is
  prioritized.

### Items intentionally deferred

- Gemini prompt engineering specifics (token counts, few-shot examples)
  → Phase 3 sub-spec.
- Exact Qdrant HNSW / quantization tuning → Phase 2 sub-spec.
- Backup and restore tooling → ops spec, post-P3.
- PII redaction pipeline → Phase 4 if R9 becomes material.
