# Hybrid Memory — Phase 2: Profile (Postgres) + Episodic (Qdrant)

**Date:** 2026-06-04
**Status:** Design (approved, awaiting user spec review)
**Parent spec:** `2026-06-04-hybrid-memory-master-design.md`
**Depends on:** Phase 1 shipped (Redis short-term + Docker stack on LAN DB
server + `MemoryFacade` with stubs).

This sub-spec elaborates **Phase 2** of the Hybrid Memory roadmap. The
goal is to bring Profile and Episodic stores fully online and wire them
into the read path. The LOCOMO worker (Phase 3) is **not** built here —
facts are seeded manually via debug endpoints to verify retrieval.

Phase 3 (worker) and Phase 4 (polish) are out of scope.

---

## 1. Deliverables and Acceptance

### 1.1 Deliverables

1. **Postgres tables** (`profile`, `profile_history`) + seed row created
   by `deploy/memory/postgres/init.sql`, mounted into
   `/docker-entrypoint-initdb.d/`. `docker-compose.yml` updated to bind
   the init volume.
2. **`app/services/embedding_service.py`** — singleton
   `SentenceTransformer` shared by `tool_retriever` and
   `memory.embedder`.
3. **`memory/profile.py`** — real `asyncpg`-backed implementation.
   Methods: `startup()`, `shutdown()`, `read()`,
   `apply_change(ProfileChange)` (transactional, writes both tables),
   `history(key_path, limit)`, `key_updated_at_map()` (for pruning),
   `health()`.
4. **`memory/episodic.py`** — real `qdrant-client` async
   implementation. Methods: `startup()`, `shutdown()`,
   `_ensure_collection()` (idempotent — runs in startup), `upsert(fact)`
   (deterministic uuid5 point_id), `search(query, entity_filter, top_k,
   min_score)`, `count()`, `health()`.
5. **`memory/embedder.py`** — thin wrapper over
   `embedding_service.aencode`. Exposes constant `DIM=384`.
6. **`memory/pruning.py`** — `prune_profile(data, ts_map, max_bytes)`
   helper that drops top-level keys with the oldest `updated_at` until
   the JSON fits the cap.
7. **`MemoryFacade.assemble_context()`** returns actual data (was
   returning empty fragments in Phase 1 due to stubs).
8. **`chat_ws.py`** per-turn path calls
   `memory_facade.assemble_context(user_text)` once and threads the
   `ContextBundle` into `agent_service.run(...)`. Initial WS-connect
   rehydration still calls `short_term.load()` directly (no `user_text`
   to query Episodic with).
9. **`agent_service.run()`** accepts `memory_bundle: ContextBundle |
   None` and forwards it to `build_system_prompt`.
   `notifications`/`no_tools=True` path passes `None` (no memory in
   proactive nudges).
10. **`llm_service.build_system_prompt(retrieved_tool_names,
    memory_bundle=None)`** appends a `[Profile]` JSON block and a
    `[Relevant memories]` bullet list when the bundle is non-empty.
    Empty Profile / zero Episodic hits → block omitted entirely.
11. **`/health`** extended: `memory.redis`, `memory.postgres`,
    `memory.qdrant`. Overall `healthy | degraded | unhealthy`
    (`degraded` = Redis up but Postgres or Qdrant down).
12. **Debug REST API** under `/api/memory/...`, included only when
    `DEBUG_MEMORY=True`:
    - `POST /api/memory/profile/change`
    - `GET  /api/memory/profile`
    - `GET  /api/memory/profile/history?key=<path>&limit=<n>`
    - `POST /api/memory/episodic/upsert`
    - `GET  /api/memory/episodic/search?q=<text>&top_k=<n>`
13. **Frontend `MemoryHealthBanner.tsx`** in `AppLayout`, polls
    `/health` every 30 s, renders a yellow banner when degraded and a
    red banner when unhealthy.
14. **New config keys** in `core/config.py`:
    - `DEBUG_MEMORY: bool = False`
    - `POSTGRES_POOL_MIN: int = 1`, `POSTGRES_POOL_MAX: int = 5`
    - `QDRANT_COLLECTION: str = "shore_episodic"`
    - `MEMORY_EPISODIC_TOP_K: int = 5`,
      `MEMORY_EPISODIC_MIN_SCORE: float = 0.3`
    - `MEMORY_PROFILE_MAX_BYTES: int = 2048`
15. **Tests**: unit (mocked) — `test_embedding_service`, `test_profile`
    (asyncpg mock), `test_episodic` (qdrant mock), `test_pruning`,
    `test_facade` (extended), `test_health`, `test_memory_debug`.
    Opt-in real-DB integration — `test_profile_postgres`,
    `test_episodic_qdrant`, gated by `SHORE_INTEGRATION_TEST=1`
    (same flag Phase 1 uses).
16. **CLAUDE.md updated** for Phase 2 (architecture diagram, ENV table,
    backlog tick).

### 1.2 Definition of done

Phase 2 ships when all 16 deliverables pass and the runbook in §8.4
completes without rollback for ≥24 h.

### 1.3 Acceptance scenarios

- Seed `name=Luna` via debug API → next chat turn, system prompt
  contains `[Profile]\n{"name": "Luna"}`. Chat asking "what's my name"
  yields "Luna" (manual smoke).
- Seed an Episodic fact `"Luna drinks espresso"` with tag `coffee` →
  query "what do I drink?" returns it in `[Relevant memories]`.
- Restart backend → state persists (Postgres + Qdrant volume on LAN).
- `docker stop shore-postgres` → chat continues, banner reads "Memory
  degraded: postgres offline", `[Profile]` block omitted.
- `docker stop shore-qdrant` → analogous; `[Relevant memories]` block
  omitted.
- `assemble_context()` p95 < 100 ms on LAN local (informal log
  measurement).
- Audit log: `apply_change(name="Luna")` → `apply_change(name="Lina")`
  → `profile_history` has 2 rows with correct `old_value`/`new_value`;
  `profile.data.name = "Lina"`.

---

## 2. Package Layout

```
back-end/app/
├── services/
│   ├── embedding_service.py        # NEW
│   ├── tool_retriever.py           # MODIFIED — uses embedding_service
│   ├── llm_service.py              # MODIFIED — build_system_prompt(ctx)
│   ├── agent_service.py            # MODIFIED — pass ContextBundle through
│   └── memory/
│       ├── facade.py               # MODIFIED — real startup/shutdown
│       ├── short_term.py           # unchanged
│       ├── embedder.py             # REWRITTEN — wraps embedding_service
│       ├── profile.py              # REWRITTEN — asyncpg
│       ├── episodic.py             # REWRITTEN — qdrant async
│       ├── pruning.py              # NEW — profile dict pruning
│       └── types.py                # unchanged (ContextBundle, ScoredFact already there)
├── api/
│   ├── endpoints/
│   │   ├── health.py               # MODIFIED — postgres + qdrant probes
│   │   └── memory_debug.py         # NEW — gated by DEBUG_MEMORY
│   └── websockets/
│       └── chat_ws.py              # MODIFIED — assemble_context per turn
├── core/
│   └── config.py                   # MODIFIED — Phase 2 config keys
└── main.py                         # MODIFIED — include memory_debug router

deploy/memory/
├── docker-compose.yml              # MODIFIED — mount postgres/init.sql
├── postgres/
│   └── init.sql                    # NEW
└── README.md                       # MODIFIED — Phase 2 notes

front-end/src/
├── layouts/AppLayout/
│   └── MemoryHealthBanner.tsx      # NEW
└── services/health.service.ts      # NEW
```

**Why split `pruning.py` out:** logic depends on a freshness map from
`profile_history` and a size-loop. Pulling it into its own module
makes it testable as a pure function (input: dict + ts_map + max_bytes,
output: pruned dict).

**Why `memory_debug.py` is a separate router:** trivial to include or
exclude based on `settings.DEBUG_MEMORY`, no interference with
production routers.

---

## 3. Embedding Service + Embedder

### 3.1 `embedding_service.py`

```python
"""Shared SentenceTransformer singleton.
Used by tool_retriever (tool descriptions) and memory.embedder (facts/queries).
"""
import asyncio
from typing import Union

import numpy as np
from sentence_transformers import SentenceTransformer

from app.core.config import settings


class EmbeddingService:
    def __init__(self):
        self._model: SentenceTransformer | None = None

    def startup(self) -> None:
        if self._model is None:
            print(f"[Embedding] Loading {settings.TOOL_RETRIEVER_MODEL}")
            self._model = SentenceTransformer(
                settings.TOOL_RETRIEVER_MODEL, device="cpu"
            )

    def encode(self, text: Union[str, list[str]]) -> np.ndarray:
        if self._model is None:
            raise RuntimeError("EmbeddingService not started")
        is_single = isinstance(text, str)
        inputs = [text] if is_single else text
        vecs = self._model.encode(inputs, normalize_embeddings=True)
        return vecs[0] if is_single else vecs

    async def aencode(self, text: Union[str, list[str]]) -> np.ndarray:
        """Off-load to default executor so the event loop is not blocked."""
        return await asyncio.get_running_loop().run_in_executor(
            None, self.encode, text
        )


embedding_service = EmbeddingService()
```

### 3.2 `memory/embedder.py`

```python
"""Thin async wrapper over embedding_service for memory layers."""
import numpy as np

from app.services.embedding_service import embedding_service


class Embedder:
    DIM = 384  # all-MiniLM-L6-v2

    async def encode(self, text: str) -> list[float]:
        vec: np.ndarray = await embedding_service.aencode(text)
        return vec.tolist()


embedder = Embedder()
```

### 3.3 `tool_retriever.py` refactor

- Drop the `SentenceTransformer(...)` instantiation in `initialize()`.
- `from app.services.embedding_service import embedding_service`.
- `self._tool_embeddings = embedding_service.encode(self._tool_texts)`.
- Same substitution in `retrieve()` and `reindex()`.

### 3.4 Startup ordering in `main.py` lifespan

```python
embedding_service.startup()      # blocking ~3-5 s on cold start
await memory_facade.startup()    # uses embedder + Qdrant + Postgres
tool_retriever.initialize(...)   # uses embedding_service
```

### 3.5 Tests

- `tests/test_embedding_service.py`:
  - `startup()` idempotent (calling twice does not reload).
  - `encode("text")` returns `np.ndarray` shape `(384,)`.
  - `encode(["a", "b"])` returns `(2, 384)`.
  - `encode` before `startup` raises `RuntimeError`.
- `tests/memory/test_embedder.py` — mock
  `embedding_service.aencode` → wrapper returns `list[float]` of
  length 384.

---

## 4. Profile (Postgres)

### 4.1 Schema — `deploy/memory/postgres/init.sql`

```sql
CREATE TABLE IF NOT EXISTS profile (
    id          SMALLINT PRIMARY KEY DEFAULT 1
                CHECK (id = 1),
    data        JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS profile_history (
    id              BIGSERIAL PRIMARY KEY,
    key_path        TEXT NOT NULL,
    old_value       JSONB,
    new_value       JSONB,
    source_turn_ts  DOUBLE PRECISION,
    confidence      REAL,
    reason          TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_profile_history_key
    ON profile_history(key_path, created_at DESC);

INSERT INTO profile (id, data) VALUES (1, '{}'::jsonb)
    ON CONFLICT (id) DO NOTHING;
```

Postgres exec files in `/docker-entrypoint-initdb.d/` only on its
first init (empty data volume). Schema changes after that are out of
scope here; Phase 4 may add Alembic.

### 4.2 `profile.py`

```python
import asyncpg
from typing import Any, Optional

from app.core.config import settings
from app.services.memory.types import ProfileChange


def _key_path_to_pg_path(key_path: str) -> list[str]:
    return key_path.split(".")


class ProfileMemory:
    def __init__(self):
        self._pool: Optional[asyncpg.Pool] = None

    async def startup(self) -> None:
        self._pool = await asyncpg.create_pool(
            dsn=settings.POSTGRES_URL,
            min_size=settings.POSTGRES_POOL_MIN,
            max_size=settings.POSTGRES_POOL_MAX,
            command_timeout=2.0,
        )

    async def shutdown(self) -> None:
        if self._pool is not None:
            await self._pool.close()

    async def read(self) -> dict:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT data FROM profile WHERE id = 1"
            )
            return dict(row["data"]) if row else {}

    async def apply_change(self, change: ProfileChange) -> None:
        path = _key_path_to_pg_path(change.key_path)
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                old = await conn.fetchval(
                    "SELECT data #> $1 FROM profile WHERE id = 1",
                    path,
                )
                if change.new_value is None:
                    await conn.execute(
                        "UPDATE profile SET data = data #- $1, "
                        "updated_at = NOW() WHERE id = 1",
                        path,
                    )
                else:
                    await conn.execute(
                        "UPDATE profile SET data = jsonb_set("
                        "data, $1, $2::jsonb, true), "
                        "updated_at = NOW() WHERE id = 1",
                        path, change.new_value,
                    )
                await conn.execute(
                    """
                    INSERT INTO profile_history
                      (key_path, old_value, new_value, source_turn_ts,
                       confidence, reason)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    change.key_path,
                    old,
                    change.new_value,
                    change.source_turn_ts,
                    change.confidence,
                    change.reason,
                )

    async def history(
        self, key_path: str, limit: int = 20
    ) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, old_value, new_value, source_turn_ts,
                       confidence, reason, created_at
                FROM profile_history
                WHERE key_path = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                key_path, limit,
            )
            return [dict(r) for r in rows]

    async def key_updated_at_map(self) -> dict[str, float]:
        """Latest created_at per key_path — used by pruning."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT key_path, MAX(created_at) AS ts
                FROM profile_history
                GROUP BY key_path
                """
            )
            return {r["key_path"]: r["ts"].timestamp() for r in rows}

    async def health(self) -> bool:
        if self._pool is None:
            return False
        try:
            async with self._pool.acquire() as conn:
                await conn.execute("SELECT 1")
            return True
        except (asyncpg.PostgresError, OSError):
            return False
```

### 4.3 Tests

**Unit (`tests/memory/test_profile.py`)** — mock `asyncpg.Pool` and the
acquire context. Assert:

- `apply_change` runs SELECT → UPDATE → INSERT in a single transaction.
- `new_value=None` triggers `data #- path`; otherwise `jsonb_set`.
- INSERT history payload carries the correct `old_value` (fetched
  pre-update) and `new_value`.
- `history` orders by `created_at DESC`.
- `key_updated_at_map` groups by `key_path`.
- `health` False when pool is None; True after successful SELECT 1.

**Integration (`tests/integration/test_profile_postgres.py`,
gated `SHORE_INTEGRATION_TEST=1`):**

- Apply 3 changes for `like_tea` (true → true → false) → final value
  false; 3 history rows in order.
- Delete (new_value=None) → key removed from `data`; history row has
  `new_value=null`.
- Nested key `projects.shore.status=active` → readable back via
  `read()`.

---

## 5. Episodic (Qdrant)

### 5.1 `episodic.py`

```python
import hashlib
import time
import uuid
from typing import Optional

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qm
from qdrant_client.http.exceptions import UnexpectedResponse

from app.core.config import settings
from app.services.memory.embedder import embedder
from app.services.memory.types import EpisodicFact, ScoredFact, EmotionVector


_NAMESPACE_FACT = uuid.UUID("6f9619ff-8b86-d011-b42d-00cf4fc964ff")


def _fact_point_id(fact: EpisodicFact) -> str:
    fact_hash = hashlib.sha1(fact.fact.encode("utf-8")).hexdigest()[:16]
    name = f"{fact.source_turn_ts}:{fact.source_role}:{fact_hash}"
    return str(uuid.uuid5(_NAMESPACE_FACT, name))


class EpisodicMemory:
    def __init__(self):
        self._client: Optional[AsyncQdrantClient] = None

    async def startup(self) -> None:
        self._client = AsyncQdrantClient(url=settings.QDRANT_URL)
        await self._ensure_collection()

    async def shutdown(self) -> None:
        if self._client is not None:
            await self._client.close()

    async def _ensure_collection(self) -> None:
        coll = settings.QDRANT_COLLECTION
        existing = {
            c.name for c in (await self._client.get_collections()).collections
        }
        if coll in existing:
            return
        await self._client.create_collection(
            collection_name=coll,
            vectors_config=qm.VectorParams(
                size=embedder.DIM,
                distance=qm.Distance.COSINE,
                on_disk=True,
            ),
        )
        await self._client.create_payload_index(
            collection_name=coll,
            field_name="entity_tags",
            field_schema=qm.PayloadSchemaType.KEYWORD,
        )
        await self._client.create_payload_index(
            collection_name=coll,
            field_name="created_at",
            field_schema=qm.PayloadSchemaType.FLOAT,
        )
        await self._client.create_payload_index(
            collection_name=coll,
            field_name="valence",
            field_schema=qm.PayloadSchemaType.FLOAT,
        )
        print(f"[Memory] Created Qdrant collection '{coll}'")

    async def upsert(self, fact: EpisodicFact) -> str:
        vec = await embedder.encode(fact.fact)
        point_id = _fact_point_id(fact)
        payload = {
            "fact": fact.fact,
            "entity_tags": fact.entity_tags,
            "emotion": fact.emotion.model_dump(),
            "valence": fact.emotion.valence,
            "source_turn_ts": fact.source_turn_ts,
            "source_role": fact.source_role,
            "created_at": time.time(),
            "confidence": fact.confidence,
            "embedding_model_version": settings.TOOL_RETRIEVER_MODEL,
        }
        await self._client.upsert(
            collection_name=settings.QDRANT_COLLECTION,
            points=[qm.PointStruct(id=point_id, vector=vec, payload=payload)],
        )
        return point_id

    async def search(
        self,
        query: str,
        entity_filter: list[str] | None = None,
        top_k: int | None = None,
        min_score: float | None = None,
    ) -> list[ScoredFact]:
        top_k = top_k or settings.MEMORY_EPISODIC_TOP_K
        min_score = (
            min_score if min_score is not None
            else settings.MEMORY_EPISODIC_MIN_SCORE
        )
        vec = await embedder.encode(query)
        qf: qm.Filter | None = None
        if entity_filter:
            qf = qm.Filter(
                must=[qm.FieldCondition(
                    key="entity_tags",
                    match=qm.MatchAny(any=entity_filter),
                )]
            )
        hits = await self._client.search(
            collection_name=settings.QDRANT_COLLECTION,
            query_vector=vec,
            query_filter=qf,
            limit=top_k,
            score_threshold=min_score,
        )
        results: list[ScoredFact] = []
        for h in hits:
            p = h.payload
            fact = EpisodicFact(
                fact=p["fact"],
                entity_tags=p["entity_tags"],
                emotion=EmotionVector(**p["emotion"]),
                source_turn_ts=p["source_turn_ts"],
                source_role=p["source_role"],
                confidence=p["confidence"],
            )
            results.append(ScoredFact(fact=fact, score=h.score))
        return results

    async def count(self) -> int:
        if self._client is None:
            return 0
        info = await self._client.count(
            collection_name=settings.QDRANT_COLLECTION, exact=True,
        )
        return info.count

    async def health(self) -> bool:
        if self._client is None:
            return False
        try:
            await self._client.get_collections()
            return True
        except (UnexpectedResponse, OSError):
            return False
```

### 5.2 Notes

- `_fact_point_id` is deterministic — `uuid5(turn_ts:role:fact_hash)`.
  Phase 3's worker re-runs do not duplicate vectors.
- Payload always carries the full Plutchik 8 + `valence` shortcut, even
  though P2 prompt injection only consumes `fact` + `entity_tags`. This
  keeps schema stable for P3 / P4.
- `entity_filter` is wired for the debug API and future canonicalizer;
  the chat read path does **not** filter in P2.

### 5.3 Tests

**Unit (`tests/memory/test_episodic.py`)** — `AsyncMock` for
`AsyncQdrantClient`. Assert:

- `_ensure_collection` no-ops when collection exists; otherwise creates
  the collection plus three payload indexes.
- `upsert` builds the right payload, point_id stable for the same
  fact (call twice → same id).
- `search` builds a `Filter` only when `entity_filter` is non-empty.

**Integration (`tests/integration/test_episodic_qdrant.py`,
gated):**

- Upsert 5 facts with mixed tags → `count()==5`.
- Search semantically related query → expected top-K by cosine.
- Search with `entity_filter=["shore_assistant"]` → only matching
  facts.
- Re-upsert same fact → `count()` unchanged (deterministic id).

---

## 6. Facade + Read-Path Integration

### 6.1 `MemoryFacade.startup()` / `shutdown()`

```python
async def startup(self) -> None:
    # Redis (short-term)
    self._redis = Redis.from_url(
        settings.REDIS_URL, decode_responses=True,
        socket_timeout=_TIMEOUT, socket_connect_timeout=1.0,
        max_connections=10,
    )
    self.short_term = ShortTermMemory(self._redis)
    redis_ok = await self.short_term.health()

    # Profile (independent failure)
    try:
        await self.profile.startup()
        pg_ok = await self.profile.health()
    except Exception as e:
        print(f"[Memory] Postgres startup failed: {e}")
        pg_ok = False

    # Episodic (independent failure)
    try:
        await self.episodic.startup()
        qd_ok = await self.episodic.health()
    except Exception as e:
        print(f"[Memory] Qdrant startup failed: {e}")
        qd_ok = False

    print(f"[Memory] redis={redis_ok} postgres={pg_ok} qdrant={qd_ok}")


async def shutdown(self) -> None:
    if self._redis is not None:
        await self._redis.aclose()
    await self.profile.shutdown()
    await self.episodic.shutdown()
```

### 6.2 `assemble_context()`

```python
async def assemble_context(self, user_text: str) -> ContextBundle:
    short_term, profile_raw, episodic = await asyncio.gather(
        self._safe_load_short_term(),
        self._safe_read_profile(),
        self._safe_search_episodic(user_text),
    )
    profile = await self._safe_prune_profile(profile_raw)
    return ContextBundle(
        short_term=short_term, profile=profile, episodic_hits=episodic,
    )


async def _safe_prune_profile(self, raw: dict) -> dict:
    if not raw:
        return raw
    try:
        ts_map = await asyncio.wait_for(
            self.profile.key_updated_at_map(), timeout=_TIMEOUT,
        )
    except Exception as e:
        print(f"[Memory] key_updated_at_map degraded: {e}")
        ts_map = {}
    from app.services.memory.pruning import prune_profile
    return prune_profile(
        raw, ts_map, max_bytes=settings.MEMORY_PROFILE_MAX_BYTES,
    )
```

The existing `_safe_*` helpers (Phase 1) are unchanged in shape — each
returns an empty fragment on timeout or layer error so a single failure
doesn't break the bundle.

### 6.3 `pruning.py`

```python
"""Prune profile dict to max_bytes by dropping the least-recently-updated
top-level keys until the JSON fits."""
import json


def prune_profile(
    data: dict, ts_map: dict[str, float], max_bytes: int,
) -> dict:
    if not data:
        return data
    encoded = json.dumps(data, ensure_ascii=False).encode("utf-8")
    if len(encoded) <= max_bytes:
        return data

    def score(top_key: str) -> float:
        best = 0.0
        for k, ts in ts_map.items():
            if k == top_key or k.startswith(top_key + "."):
                best = max(best, ts)
        return best

    keys_sorted = sorted(data.keys(), key=score)  # oldest first
    pruned = dict(data)
    for k in keys_sorted:
        pruned.pop(k)
        encoded = json.dumps(pruned, ensure_ascii=False).encode("utf-8")
        if len(encoded) <= max_bytes:
            return pruned
    return pruned
```

### 6.4 `chat_ws.py` change

`chat_ws` maintains a **local** `conversation_history: list[dict]` across
the WS lifetime: it's seeded from `short_term.load()` on connect and
appended on every turn. That stays the source of truth for the LLM
`messages` list, because it always reflects the in-progress append.

For Phase 2 the only addition per turn is the Profile + Episodic
fragments. We still call `assemble_context(user_text)` (rather than a
specialized helper) because:

- `short_term.load()` inside `asyncio.gather` costs ~3 ms — negligible.
- One method to maintain instead of two (and Phase 3's worker will
  also reuse `assemble_context`).

Per turn, after STT (if audio) and before invoking the agent:

```python
bundle = await memory_facade.assemble_context(user_text)
# bundle.short_term is intentionally ignored — local conversation_history wins.
# bundle.profile + bundle.episodic_hits flow into agent_service.run(memory_bundle=bundle).
```

Initial WS connect keeps the existing `short_term.load()` call (there
is no `user_text` to query Episodic with yet, and the bundle would be
wasteful).

### 6.5 `agent_service.run()` signature

```python
async def run(
    self,
    user_text: str,
    conversation_history: list[dict],
    memory_bundle: ContextBundle | None = None,   # NEW
    thinking: bool = False,
    no_tools: bool = False,
    live_user_message: Optional[dict] = None,
) -> AsyncGenerator[dict, None]:
    ...
    system_prompt = build_system_prompt(
        relevant_tool_names,
        memory_bundle=memory_bundle if not no_tools else None,
    )
```

Notifications (`no_tools=True`) pass `None` for `memory_bundle` —
proactive nudges stay free of Profile/Episodic content.

### 6.6 `build_system_prompt` + memory block

```python
def build_system_prompt(
    retrieved_tool_names: list[str] | None = None,
    memory_bundle: "ContextBundle | None" = None,
) -> str:
    parts = [_PERSONA_TEXT]
    if retrieved_tool_names is not None:
        # ... existing tools_core + section files ...
    if _USER_TEXT:
        parts.append(_USER_TEXT)
    if memory_bundle is not None:
        mem_block = _format_memory_block(memory_bundle)
        if mem_block:
            parts.append(mem_block)
    return "\n\n".join(p for p in parts if p)


def _format_memory_block(bundle: "ContextBundle") -> str:
    import json
    lines: list[str] = []
    if bundle.profile:
        lines.append("[Profile]")
        lines.append(json.dumps(bundle.profile, ensure_ascii=False, indent=2))
    if bundle.episodic_hits:
        if lines:
            lines.append("")
        lines.append("[Relevant memories]")
        for sf in bundle.episodic_hits:
            tags = ", ".join(sf.fact.entity_tags) if sf.fact.entity_tags else "—"
            lines.append(f"- {sf.fact.fact} [tags: {tags}]")
    return "\n".join(lines)
```

**Empty cases:** Profile `{}` → no `[Profile]` block. Episodic 0 hits
→ no `[Relevant memories]` block. Both empty → nothing appended.

### 6.7 Tests

- `tests/memory/test_facade.py` (extend):
  - Mock 3 layers; time `asyncio.gather` → total < sum (parallel).
  - Each layer can fail independently — bundle returns empty fragment
    for that layer and the others stay intact.
  - Empty profile → `_safe_prune_profile` short-circuits and skips the
    history query entirely.
- `tests/memory/test_pruning.py`:
  - Profile under cap → returned unchanged.
  - Profile 5 KB, `ts_map` fresh on `k1`, stale on `k2`/`k3` → after
    prune `k1` survives, the others are dropped.
  - Nested key path `projects.shore.status` is scored under the
    `projects` top-level key.
  - Empty `ts_map` → all keys score 0; deterministic alphabetical
    eviction.

---

## 7. Debug REST API + Health Endpoint

### 7.1 `memory_debug.py`

```python
"""Debug endpoints for manual memory seeding (Phase 2).
Included in app router only when DEBUG_MEMORY=True."""
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.memory import memory_facade
from app.services.memory.types import EmotionVector, EpisodicFact, ProfileChange

router = APIRouter(prefix="/api/memory", tags=["memory-debug"])


# ── Profile ────────────────────────────────────────────────────────────

class ProfileChangeRequest(BaseModel):
    key_path: str
    new_value: Any | None = None
    source_turn_ts: float = 0.0
    confidence: float = Field(1.0, ge=0.0, le=1.0)
    reason: str = "manual debug seed"


@router.post("/profile/change")
async def profile_change(req: ProfileChangeRequest) -> dict:
    change = ProfileChange(**req.model_dump())
    try:
        await memory_facade.profile.apply_change(change)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"ok": True, "key_path": req.key_path}


@router.get("/profile")
async def profile_read() -> dict:
    import json
    try:
        data = await memory_facade.profile.read()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    size = len(json.dumps(data, ensure_ascii=False).encode("utf-8"))
    return {"data": data, "size_bytes": size}


@router.get("/profile/history")
async def profile_history(key: str, limit: int = 20) -> dict:
    try:
        rows = await memory_facade.profile.history(key, limit)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"key_path": key, "rows": rows}


# ── Episodic ───────────────────────────────────────────────────────────

class EpisodicUpsertRequest(BaseModel):
    fact: str
    entity_tags: list[str] = []
    emotion: Optional[EmotionVector] = None
    source_turn_ts: float = 0.0
    source_role: str = "user"
    confidence: float = Field(1.0, ge=0.0, le=1.0)


@router.post("/episodic/upsert")
async def episodic_upsert(req: EpisodicUpsertRequest) -> dict:
    fact = EpisodicFact(
        fact=req.fact,
        entity_tags=req.entity_tags,
        emotion=req.emotion or EmotionVector(),
        source_turn_ts=req.source_turn_ts,
        source_role=req.source_role,
        confidence=req.confidence,
    )
    try:
        point_id = await memory_facade.episodic.upsert(fact)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"ok": True, "point_id": point_id}


@router.get("/episodic/search")
async def episodic_search(q: str, top_k: int = 5) -> dict:
    try:
        results = await memory_facade.episodic.search(q, top_k=top_k)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {
        "query": q,
        "hits": [
            {
                "score": r.score,
                "fact": r.fact.fact,
                "entity_tags": r.fact.entity_tags,
                "confidence": r.fact.confidence,
            }
            for r in results
        ],
    }
```

### 7.2 Gating in `main.py`

```python
from app.core.config import settings

if settings.DEBUG_MEMORY:
    from app.api.endpoints import memory_debug
    app.include_router(memory_debug.router)
    print("[App] DEBUG_MEMORY=True — memory debug endpoints enabled")
```

### 7.3 `/health` endpoint

```python
@router.get("/health")
async def health() -> dict:
    redis_ok = (
        await memory_facade.short_term.health()
        if memory_facade.short_term is not None else False
    )
    pg_ok = await memory_facade.profile.health()
    qd_ok = await memory_facade.episodic.health()

    if redis_ok and pg_ok and qd_ok:
        status = "healthy"
    elif redis_ok:
        status = "degraded"     # short-term works → chat still works
    else:
        status = "unhealthy"

    return {
        "status": status,
        "memory": {
            "redis": "ok" if redis_ok else "down",
            "postgres": "ok" if pg_ok else "down",
            "qdrant": "ok" if qd_ok else "down",
        },
    }
```

### 7.4 Frontend `MemoryHealthBanner.tsx` (sketch)

```tsx
import { useEffect, useState } from "react";

type Health = {
  status: string;
  memory: { redis: string; postgres: string; qdrant: string };
};

export function MemoryHealthBanner() {
  const [h, setH] = useState<Health | null>(null);

  useEffect(() => {
    const poll = async () => {
      try {
        const r = await fetch("/health");
        setH(await r.json());
      } catch {
        setH({
          status: "unhealthy",
          memory: { redis: "down", postgres: "down", qdrant: "down" },
        });
      }
    };
    poll();
    const id = setInterval(poll, 30_000);
    return () => clearInterval(id);
  }, []);

  if (!h || h.status === "healthy") return null;

  const down = Object.entries(h.memory)
    .filter(([, v]) => v === "down")
    .map(([k]) => k);
  const tone =
    h.status === "unhealthy"
      ? "bg-red-200 text-red-900"
      : "bg-yellow-200 text-yellow-900";
  return (
    <div className={`${tone} px-3 py-1.5 text-sm`}>
      Memory degraded: {down.join(", ")} offline. Chat continues with
      reduced context.
    </div>
  );
}
```

Mount the banner at the top of `AppLayout` (above Header). The Vite
dev proxy already forwards `/health` (commit `ef5121d`).

### 7.5 Tests

- `tests/test_health.py` — patch facade methods, verify three status
  branches.
- `tests/test_memory_debug.py` — TestClient with `DEBUG_MEMORY=True`,
  mock facade methods, verify POST/GET shapes. Verify router is NOT
  included when `DEBUG_MEMORY=False`.

---

## 8. Rollout, Risks, Runbook

### 8.1 Branch & commit plan

Single feature branch `feature/hybrid-memory-phase-2` off `main`,
single PR at the end.

1. `chore(memory): add Phase 2 config keys + DEBUG_MEMORY flag`
2. `refactor(embeddings): extract shared EmbeddingService, wire tool_retriever`
3. `feat(memory): real embedder.py wrapping embedding_service`
4. `chore(deploy): postgres init.sql + compose mount`
5. `feat(memory): implement ProfileMemory (asyncpg) + tests`
6. `feat(memory): implement EpisodicMemory (qdrant async) + tests`
7. `feat(memory): pruning helper for profile cap`
8. `feat(memory): assemble_context returns real data; facade startup/shutdown wiring`
9. `feat(chat-ws): use assemble_context per turn; thread bundle to agent`
10. `feat(llm): build_system_prompt accepts ContextBundle, formats Profile + Episodic block`
11. `feat(api): debug memory endpoints gated by DEBUG_MEMORY`
12. `feat(health): postgres + qdrant probes in /health`
13. `feat(front-end): MemoryHealthBanner polls /health`
14. `test(memory): integration tests for profile + episodic (opt-in INTEGRATION_TESTS=1)`
15. `docs(memory): update CLAUDE.md for Phase 2`

### 8.2 Rollback levers

- `DEBUG_MEMORY=False` (default) — debug API disabled.
- Postgres / Qdrant down → circuit breaker → chat works on short-term
  only; banner shown.
- Hard rollback: `git revert <merge-sha>` returns to Phase 1; Postgres
  and Qdrant data are preserved on disk for the next ship.

### 8.3 Phase-2-specific risks

| # | Risk | Severity | Mitigation |
|---|------|----------|------------|
| P2-R1 | `init.sql` only runs on first Postgres init. Schema changes later need a manual migration. | Med | Phase 2 schema is final for profile-related tables; revisit Alembic in P4. README documents this. |
| P2-R2 | Qdrant collection is owned by backend startup. If someone deletes the collection, you must restart the backend to re-create. | Low | `_ensure_collection` is idempotent and logs the create. |
| P2-R3 | `embedding_service.startup()` blocks ~3-5 s, raising cold start. | Low | Single-user backend, acceptable. Documented in README. |
| P2-R4 | Prompt budget: Profile (~2 KB) + 5 Episodic facts (~500 tokens) adds ~1.2k tokens per turn. | Low | Caps are hardcoded; `prompt_chars` logged. |
| P2-R5 | Debug API has no auth — `DEBUG_MEMORY=True` on a LAN-exposed backend lets any LAN device seed Profile. | Med | Document: enable only during seeding, then disable. Phase 3+ can add a token header if needed. |
| P2-R6 | `assemble_context` calls 3 layers per turn — slow Postgres / Qdrant cold-start hurts latency. | Med | Circuit breaker (500 ms) per layer; warnings logged; banner shown. |

### 8.4 Operational runbook (post-deploy)

1. SSH the LAN DB server: `cd Shore-Assistant/deploy/memory && docker
   compose pull && docker compose up -d`.
2. Verify: `docker exec shore-postgres psql -U shore -d shore_memory
   -c "\dt"` shows `profile` + `profile_history`. `curl localhost:6333/
   collections` shows `shore_episodic` after the first backend start.
3. Backend `.env`: set `POSTGRES_URL`, `QDRANT_URL`, and temporarily
   `DEBUG_MEMORY=True`.
4. Restart backend → log shows `[Memory] redis=True postgres=True
   qdrant=True`. `/health` returns `healthy`.
5. Seed Profile:
   ```bash
   curl -X POST localhost:9000/api/memory/profile/change \
     -H 'Content-Type: application/json' \
     -d '{"key_path":"name","new_value":"Luna","reason":"first seed"}'
   curl localhost:9000/api/memory/profile
   ```
   Expect `{"data":{"name":"Luna"}, "size_bytes": ...}`.
6. Smoke chat: open UI, ask "what's my name?" → kuudere answers
   "Luna".
7. Seed an Episodic fact:
   ```bash
   curl -X POST localhost:9000/api/memory/episodic/upsert \
     -d '{"fact":"Luna drinks espresso with no sugar","entity_tags":["coffee"]}'
   ```
   Ask "what do I like to drink?" → answer mentions espresso.
8. Failure drill: `docker stop shore-postgres` → chat continues,
   banner reads "Memory degraded: postgres offline".
9. After ≥24 h stable, set `DEBUG_MEMORY=False`, restart backend.

### 8.5 Definition of Phase-2 done

- All 15 commits merged via the single PR.
- Unit tests pass; integration tests pass when
  `SHORE_INTEGRATION_TEST=1`.
- Smoke runbook steps 5-8 pass.
- ≥24 h of normal use without rollback.
- `CLAUDE.md` backlog: tick `[x] Memory backend Phase 2 — Profile +
  Episodic`.

---

## 9. Out of Scope (deferred to Phase 3+)

- LOCOMO worker (Gemini Flash) — automatic fact / emotion extraction
  on idle.
- Canonicalizer — entity-tag dedup job.
- Conflict-review UI / confidence calibration.
- PII redaction before any cloud call.
- Re-embedding job for model migration.
- Backup / restore tooling (separate ops spec).
