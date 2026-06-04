# Hybrid Memory — Phase 1: Infra + Redis Short-term

**Date:** 2026-06-04
**Status:** Design (approved, awaiting user spec review)
**Parent spec:** `2026-06-04-hybrid-memory-master-design.md`
**Depends on:** Chat History Rehydration (spec 2026-06-03) shipped first.

This sub-spec elaborates **Phase 1** of the Hybrid Memory roadmap. The
goal is to replace the JSON-file `memory_service.py` with a Redis-backed
short-term sliding window running on the LAN DB server, while bringing
up the full Postgres + Redis + Qdrant Docker stack so Phase 2 needs no
infra work. Chat behavior is identical to today; only the storage
backend changes.

Phases 2 (Profile + Episodic) and 3 (Worker) are out of scope here.

---

## 1. Deliverables and Acceptance

### 1.1 Deliverables

1. `deploy/memory/docker-compose.yml` running three containers on the LAN
   server: Postgres 16, Redis 7 (AOF on), Qdrant — all `healthy` after
   `docker compose up -d`.
2. New `back-end/app/services/memory/` package with `types.py`,
   `short_term.py`, `embedder.py` (stub), `profile.py` (stub),
   `episodic.py` (stub), and `facade.py` (real Short-term, stub the
   rest).
3. `chat_ws.py` no longer imports `memory_service`. It uses
   `memory_facade` for all reads, appends, and clears.
4. `system_tools.py:clear_memory` deletes the Redis key via the facade.
5. `health.py` reports `memory.redis` connection status; degraded when
   Redis is down (not unhealthy).
6. `app/services/memory_service.py` deleted.
7. `back-end/data/memory/` deleted from the repo and added to
   `.gitignore`.
8. Config: `REDIS_URL`, `REDIS_SHORT_TERM_KEY`, `MEMORY_MAX_TURNS` added;
   `POSTGRES_URL`, `QDRANT_URL` added but unused. `MEMORY_DIR` removed.
9. Tests: new `tests/memory/test_short_term.py`, `test_facade.py`,
   `test_types.py`; new `tests/integration/test_short_term_redis.py`.
   `test_memory_service.py` deleted. `test_chat_ws_history.py` and
   `test_chat_ws_concurrent.py` updated for the new facade interface.
10. Manual smoke: restart back-end → history restored from Redis. Kill
    Redis mid-session → next turn still streams; warning logged;
    frontend does not crash.

### 1.2 Definition of done

Phase 1 ships when all ten deliverables pass and the production cutover
runbook in §6.2 completes without rollback for at least 24 hours.

---

## 2. Docker Stack

### 2.1 Repo file layout

```
deploy/
└── memory/
    ├── docker-compose.yml
    ├── .env.example       # template (committed)
    └── README.md          # server-side setup runbook
```

The real `.env` lives on the server only; never committed.

### 2.2 `docker-compose.yml`

```yaml
name: shore-memory

services:
  redis:
    image: redis:7.4-alpine
    container_name: shore-redis
    restart: unless-stopped
    command:
      - redis-server
      - --appendonly
      - "yes"
      - --appendfsync
      - everysec
      - --save
      - "300 100"           # RDB snapshot every 5 min if >=100 keys changed
      - --maxmemory-policy
      - noeviction          # source of truth -- never evict
    ports:
      - "127.0.0.1:6379:6379"
      - "${LAN_BIND_IP}:6379:6379"
    volumes:
      - /var/lib/shore/redis:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 5

  postgres:
    image: postgres:16-alpine
    container_name: shore-postgres
    restart: unless-stopped
    environment:
      POSTGRES_DB: shore_memory
      POSTGRES_USER: shore
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    ports:
      - "${LAN_BIND_IP}:5432:5432"
    volumes:
      - /var/lib/shore/postgres:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U shore -d shore_memory"]
      interval: 10s
      timeout: 3s
      retries: 5

  qdrant:
    image: qdrant/qdrant:v1.12.4
    container_name: shore-qdrant
    restart: unless-stopped
    ports:
      - "${LAN_BIND_IP}:6333:6333"   # REST
      - "${LAN_BIND_IP}:6334:6334"   # gRPC
    volumes:
      - /var/lib/shore/qdrant:/qdrant/storage
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- http://localhost:6333/healthz || exit 1"]
      interval: 10s
      timeout: 3s
      retries: 5
```

### 2.3 `.env.example`

```bash
# LAN-facing IP of the server (set on the box, e.g. 192.168.1.50)
LAN_BIND_IP=192.168.1.X

# Postgres password (Postgres image requires it set even though P1 does not use it)
POSTGRES_PASSWORD=changeme
```

### 2.4 Design notes

- **Redis bind on two interfaces** (loopback + LAN) so admin work on the
  server uses `localhost` while the AI machine connects via the LAN IP.
  Never `0.0.0.0`.
- **Postgres password is required** for the image to start, even though
  no code uses Postgres yet in P1. Set a placeholder; P2 will enforce a
  real value.
- **No Qdrant API key** under the LAN trust model. P4 may add one.
- **Images pinned to `major.minor`** to avoid surprise breaking changes
  on `pull`. Upgrades are intentional via PR.
- **`maxmemory-policy noeviction`** is critical: Redis is the source of
  truth for short-term, so silent eviction is unacceptable. If RAM ever
  fills, writes fail loudly and the facade logs.

### 2.5 `README.md` content (server runbook)

```markdown
# Shore Memory Stack — Server Setup

## Prerequisites
- Linux server with Docker + compose plugin (compose v2+).
- Static LAN IP (e.g. 192.168.1.50).
- Folders /var/lib/shore/{redis,postgres,qdrant} created with the right
  UIDs.

## First-time setup
1. SSH to the server.
2. `git clone <repo>` and `cd Shore-Assistant/deploy/memory`.
3. `cp .env.example .env` and fill in LAN_BIND_IP, POSTGRES_PASSWORD.
4. `sudo mkdir -p /var/lib/shore/{redis,postgres,qdrant}`
   `sudo chown 999:999 /var/lib/shore/redis`        # redis UID
   `sudo chown 70:70 /var/lib/shore/postgres`        # postgres-alpine UID
   `sudo chown 1000:1000 /var/lib/shore/qdrant`      # qdrant UID
5. `docker compose up -d`.
6. Verify with `docker compose ps`; all three should be `healthy` in
   ~30s.

## Updates
`git pull && docker compose pull && docker compose up -d`.

## Backup (manual)
- Redis: `redis-cli BGSAVE`, then rsync `/var/lib/shore/redis/dump.rdb`.
- Postgres + Qdrant: stop containers, rsync data dirs, restart.

## Reset (destroys all memory)
`docker compose down -v && sudo rm -rf /var/lib/shore/{redis,postgres,qdrant}/*`
```

### 2.6 Deferred for later phases

- Backup automation (P4 / ops spec).
- Metric exporters (P4).
- TLS / encryption (deferred indefinitely on LAN).
- Multi-node Redis (Sentinel / Cluster) — single-user, never needed.
- Container resource limits — server dedicated, not needed in P1.

---

## 3. Backend Code Structure

### 3.1 Package layout

```
back-end/app/services/memory/
├── __init__.py         # exposes `memory_facade` singleton
├── types.py            # Pydantic models from Master Spec §3.4
├── short_term.py       # Redis-backed sliding window (REAL)
├── embedder.py         # STUB - NotImplementedError, P2 fills in
├── profile.py          # STUB - read/health return empty
├── episodic.py         # STUB - search returns []
└── facade.py           # MemoryFacade
```

P1 ships full module skeletons. Read-path stubs return safe empty
values; write-path stubs raise `NotImplementedError` (no P1 caller
invokes them).

### 3.2 `types.py`

Exactly the Pydantic models defined in Master Spec §3.4, plus a P1-only
`ContextBundle`:

```python
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


class Message(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str
    timestamp: float
    extras: Optional[dict] = None


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
    new_value: Any | None
    source_turn_ts: float
    confidence: float
    reason: str


class WorkerOutput(BaseModel):
    profile_changes: list[ProfileChange]
    episodic_facts: list[EpisodicFact]


class ScoredFact(BaseModel):
    fact: EpisodicFact
    score: float


class ContextBundle(BaseModel):
    short_term: list[Message]
    profile: dict
    episodic_hits: list[ScoredFact]
```

### 3.3 `short_term.py` (real implementation)

```python
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import settings
from app.services.memory.types import Message


class ShortTermMemory:
    """
    Redis-backed sliding window over recent messages.

    All operations raise RedisError on failure; the facade catches and
    degrades.
    """

    def __init__(self, redis: Redis):
        self._redis = redis
        self._key = settings.REDIS_SHORT_TERM_KEY
        self._limit = settings.MEMORY_MAX_TURNS * 2  # messages, not turns

    async def append(self, message: Message) -> None:
        payload = message.model_dump_json()
        pipe = self._redis.pipeline()
        pipe.lpush(self._key, payload)
        pipe.ltrim(self._key, 0, self._limit - 1)
        await pipe.execute()

    async def load(self) -> list[Message]:
        raw = await self._redis.lrange(self._key, 0, -1)
        return [Message.model_validate_json(item) for item in reversed(raw)]

    async def clear(self) -> bool:
        deleted = await self._redis.delete(self._key)
        return deleted > 0

    async def health(self) -> bool:
        try:
            await self._redis.ping()
            return True
        except RedisError:
            return False
```

Key choices:

- `model_dump_json()` ensures nested `extras` (including base64
  attachments) survive round-trip without manual JSON coercion.
- `LPUSH + LTRIM` in a pipeline so the window cannot exceed limit
  between commands.
- `load()` reverses to chronological order; both the frontend and the
  agent expect oldest-first.
- `health()` swallows exceptions so the facade can use it for routing.

### 3.4 Stubs for P2

```python
# embedder.py
class Embedder:
    async def encode(self, text: str) -> list[float]:
        raise NotImplementedError("Embedder is wired in Phase 2")


# profile.py
class ProfileMemory:
    async def read(self) -> dict:
        return {}

    async def apply_change(self, change) -> None:
        raise NotImplementedError("Profile writes wired in Phase 2")

    async def health(self) -> bool:
        return False


# episodic.py
class EpisodicMemory:
    async def search(self, query, entity_filter=None, top_k=5, min_score=0.3):
        return []

    async def upsert(self, fact) -> None:
        raise NotImplementedError("Episodic writes wired in Phase 2")

    async def health(self) -> bool:
        return False
```

### 3.5 `facade.py`

```python
import asyncio
import time
from typing import Optional

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import settings
from app.services.memory.episodic import EpisodicMemory
from app.services.memory.profile import ProfileMemory
from app.services.memory.short_term import ShortTermMemory
from app.services.memory.types import ContextBundle, Message


class MemoryFacade:
    def __init__(self):
        self._redis: Optional[Redis] = None
        self.short_term: Optional[ShortTermMemory] = None
        self.profile = ProfileMemory()
        self.episodic = EpisodicMemory()

    async def startup(self) -> None:
        self._redis = Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_timeout=0.5,
            socket_connect_timeout=1.0,
            max_connections=10,
        )
        self.short_term = ShortTermMemory(self._redis)
        if not await self.short_term.health():
            print("[Memory] WARNING: Redis unreachable at startup")

    async def shutdown(self) -> None:
        if self._redis:
            await self._redis.close()

    async def assemble_context(self, user_text: str) -> ContextBundle:
        short_term, profile, episodic = await asyncio.gather(
            self._safe_load_short_term(),
            self._safe_read_profile(),
            self._safe_search_episodic(user_text),
        )
        return ContextBundle(
            short_term=short_term,
            profile=profile,
            episodic_hits=episodic,
        )

    async def append_user(self, content, extras=None):
        await self._safe_append(Message(
            role="user", content=content, timestamp=time.time(), extras=extras
        ))

    async def append_assistant(self, content, extras=None):
        await self._safe_append(Message(
            role="assistant", content=content, timestamp=time.time(), extras=extras
        ))

    async def clear(self) -> bool:
        if not self.short_term:
            return False
        try:
            return await self.short_term.clear()
        except RedisError as e:
            print(f"[Memory] clear failed: {e}")
            return False

    async def _safe_load_short_term(self):
        if not self.short_term:
            return []
        try:
            return await asyncio.wait_for(self.short_term.load(), timeout=0.5)
        except (RedisError, asyncio.TimeoutError) as e:
            print(f"[Memory] short_term.load degraded: {e}")
            return []

    async def _safe_read_profile(self):
        try:
            return await asyncio.wait_for(self.profile.read(), timeout=0.5)
        except (Exception, asyncio.TimeoutError) as e:
            print(f"[Memory] profile.read degraded: {e}")
            return {}

    async def _safe_search_episodic(self, query):
        try:
            return await asyncio.wait_for(
                self.episodic.search(query), timeout=0.5
            )
        except (Exception, asyncio.TimeoutError) as e:
            print(f"[Memory] episodic.search degraded: {e}")
            return []

    async def _safe_append(self, message: Message) -> None:
        if not self.short_term:
            print("[Memory] append skipped — facade not started")
            return
        try:
            await self.short_term.append(message)
        except RedisError as e:
            print(f"[Memory] short_term.append failed: {e}")


memory_facade = MemoryFacade()
```

### 3.6 `__init__.py`

```python
from app.services.memory.facade import memory_facade

__all__ = ["memory_facade"]
```

### 3.7 Lifecycle wiring (`main.py`)

`main.py` already uses an `@asynccontextmanager`-based `lifespan`
function. Extend it rather than introducing the deprecated `on_event`
decorators:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load models once at startup, clean up on shutdown."""
    if settings.STT_ENABLED:
        # ... existing init ...

    await memory_facade.startup()       # NEW

    yield

    await memory_facade.shutdown()      # NEW
    # ... existing cleanup ...
```

Place `memory_facade.startup()` after model loads so an early Redis-down
warning does not block heavier init work.

---

## 4. Refactor Points

### 4.1 `chat_ws.py`

| Line | Before | After |
|------|--------|-------|
| 15 | `from app.services.memory_service import memory_service` | `from app.services.memory import memory_facade` |
| 49 | comment "...goes on conversation_history / memory_service" | comment "...goes on conversation_history / short-term memory" |
| 139 | `persisted = memory_service.load(session_id="default")` | `persisted_msgs = await memory_facade.short_term.load()`<br>`persisted = [m.model_dump() for m in persisted_msgs]` |
| 243-249 | `memory_service.append(session_id="default", role="user", content=..., extras=...)` | `await memory_facade.append_user(content=..., extras=...)` |
| 334-340 | `memory_service.append(session_id="default", role="assistant", content=..., extras=...)` | `await memory_facade.append_assistant(content=..., extras=...)` |
| 429 | `memory_service.clear("default")` | `await memory_facade.clear()` |

`_build_memory_message` keeps its dict shape — that dict becomes the
`extras` payload of a `Message`, which already accepts any dict.

The wire-protocol shape (the `history` message sent on connect, defined
by the Chat History Rehydration spec) is preserved: `Message.model_dump()`
produces an identical dict.

### 4.2 `system_tools.py:clear_memory`

```python
@tool
async def clear_memory() -> str:
    """Clear the conversation memory. Use when the user asks to forget..."""
    cleared = await memory_facade.clear()
    return "Cleared" if cleared else "Already empty"
```

`agent_service.execute_tool` already routes async tools via
`tool.coroutine`, so no other wiring changes.

### 4.3 `health.py`

```python
@router.post("/clear-memory")
async def clear_memory():
    cleared = await memory_facade.clear()
    return {"cleared": cleared}


@router.get("/health")
async def health():
    return {
        "status": "ok",
        "memory": {
            "redis": (
                await memory_facade.short_term.health()
                if memory_facade.short_term else False
            ),
        },
    }
```

### 4.4 Tool registry (`app/tools/__init__.py`)

No change. `clear_memory` becomes a coroutine; the registry already
treats both sync and async tools uniformly.

### 4.5 Tests

| File | Action |
|------|--------|
| `tests/test_memory_service.py` (untracked) | DELETE — class gone. |
| `tests/test_chat_ws_history.py` (untracked) | UPDATE — monkeypatch `memory_facade.short_term.load`/`append` as `AsyncMock`. |
| `tests/test_chat_ws_concurrent.py` | UPDATE — same monkeypatch shape. |
| `tests/memory/test_types.py` | NEW — see §7. |
| `tests/memory/test_short_term.py` | NEW — see §7. |
| `tests/memory/test_facade.py` | NEW — see §7. |
| `tests/integration/test_short_term_redis.py` | NEW — see §7. |

### 4.6 Test fixture pattern

```python
@pytest.fixture
async def fake_redis(monkeypatch):
    from fakeredis import aioredis as fakeredis_aio
    fake = fakeredis_aio.FakeRedis(decode_responses=True)
    monkeypatch.setattr(memory_facade, "_redis", fake)
    monkeypatch.setattr(memory_facade, "short_term", ShortTermMemory(fake))
    yield fake
    await fake.flushdb()
    await fake.close()
```

### 4.7 Legacy cleanup

At the end of the P1 PR:

```bash
git rm -r back-end/data/memory/
```

Add `back-end/data/memory/` to `.gitignore` so future code cannot resurrect
the folder silently.

### 4.8 Suggested commit sequence

Split the PR into ~5 commits so review stays grokkable:

1. `feat(memory): add memory package skeleton (types, stubs)` — no
   caller touched.
2. `feat(memory): implement Redis ShortTermMemory + facade circuit breakers`
   — module complete, not yet wired.
3. `refactor(chat_ws): switch to memory_facade, drop memory_service`
   — primary caller swap.
4. `refactor(tools,health): clear_memory async via facade` — minor
   touchpoints.
5. `chore(memory): remove legacy memory_service.py and data/memory/`
   — cleanup.

---

## 5. Configuration

### 5.1 `back-end/.env.example`

`back-end/.env.example` will be created as part of P1 (currently
untracked):

```bash
# ═══════════════════════════════════════════════════════════════════
# Shore Assistant Back-end — Environment Configuration
# Copy to .env and fill in. .env is gitignored.
# ═══════════════════════════════════════════════════════════════════

# ─── LLM (llama-server) ──────────────────────────────────────────────
LLAMA_BASE_URL=http://localhost:8080
LLAMA_MODEL=
LLAMA_TIMEOUT=120

# ─── Persona ─────────────────────────────────────────────────────────
PERSONA=kuudere

# ─── Short-term memory (Redis on LAN server) ────────────────────────
REDIS_URL=redis://192.168.1.50:6379/0
REDIS_SHORT_TERM_KEY=shore:short_term:messages
MEMORY_MAX_TURNS=15

# ─── Profile + Episodic (Phase 2, declared early) ───────────────────
POSTGRES_URL=postgresql://shore:CHANGEME@192.168.1.50:5432/shore_memory
QDRANT_URL=http://192.168.1.50:6333

# ─── Scheduler ───────────────────────────────────────────────────────
SCHEDULER_TASKS_FILE=data/scheduled_tasks.json
SCHEDULER_PENDING_FILE=data/pending_notifications.json

# ─── Tool retriever ──────────────────────────────────────────────────
TOOL_RETRIEVER_MODEL=all-MiniLM-L6-v2
TOOL_RETRIEVER_TOP_K=3
TOOL_RETRIEVER_THRESHOLD=0.3

# ─── n8n integration ─────────────────────────────────────────────────
N8N_ENABLED=False
N8N_BASE_URL=http://localhost:5678
N8N_API_KEY=
N8N_WEBHOOK_SECRET=
N8N_REFRESH_INTERVAL_MINUTES=0

# ─── Node PTY service ────────────────────────────────────────────────
NODE_PTY_WS_URL=wss://terminal.shore-keeper.com
NODE_PTY_AUTH_TOKEN=
NODE_PTY_RECONNECT_BASE_MS=1000
NODE_PTY_RECONNECT_MAX_MS=30000
NODE_PTY_PING_INTERVAL_SECONDS=30
NODE_PTY_PING_TIMEOUT_SECONDS=5
```

### 5.2 `app/core/config.py`

```python
class Settings(BaseSettings):
    # ... existing fields ...

    # ── Short-term memory ──
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_SHORT_TERM_KEY: str = "shore:short_term:messages"
    MEMORY_MAX_TURNS: int = 15      # was 20

    # ── Reserved for Phase 2 (declared, unused in P1) ──
    POSTGRES_URL: str = "postgresql://shore:changeme@localhost:5432/shore_memory"
    QDRANT_URL: str = "http://localhost:6333"

    # ── REMOVED in P1 ──
    # MEMORY_DIR: str = "data/memory"
```

### 5.3 Default-value rationale

| Var | Default | Why |
|-----|---------|-----|
| `MEMORY_MAX_TURNS` | 15 | Master Spec §3.5 — design brief said 10–15. |
| `REDIS_SHORT_TERM_KEY` | `shore:short_term:messages` | `shore:*` namespace avoids collisions if Redis is shared later. |
| `REDIS_URL` default `localhost` | localhost | Dev tests with `fakeredis` or a local container; production env overrides to LAN IP. |
| `max_connections=10` (in code) | 10 | Single-user, single chat session — gather of 3 layers plus pings fits in <10. |
| `socket_timeout=0.5s` (in code) | 0.5 | Matches the Master Spec §3.5 circuit-breaker budget. |

### 5.4 `requirements.txt` additions

```
redis>=5.0.0,<6.0.0          # async-native via redis.asyncio
```

Add `back-end/requirements-dev.txt` (new file):

```
fakeredis[lua]>=2.20.0
pytest-asyncio>=0.23.0       # if not already present
```

Update README to direct developers to install both files; production
installs only `requirements.txt`.

### 5.5 `.gitignore` additions

```
# Memory backend
back-end/data/memory/        # legacy folder — must not be re-created
```

### 5.6 `CLAUDE.md` updates

- **Project Structure** — replace `memory_service.py` with the `memory/`
  package and list its modules.
- **Key Technical Constraints** — change "Conversation memory: per-session
  JSON files" to "Conversation memory: Redis sliding window on LAN DB
  server, AOF persistence".
- **Configuration** — table: add `REDIS_URL`, `REDIS_SHORT_TERM_KEY`,
  `POSTGRES_URL`, `QDRANT_URL`; change `MEMORY_MAX_TURNS` default to 15;
  remove `MEMORY_DIR`.
- **Commands** — add a step "Start memory stack:
  `ssh server && cd Shore-Assistant/deploy/memory && docker compose up -d`".
- **Backlog** — mark `[x] Memory backend Phase 1 (Redis short-term)`.

---

## 6. Deployment Runbook

### 6.1 Pre-flight

On the dev machine:

- [ ] Unit tests pass (`pytest tests/memory/`).
- [ ] Integration tests pass with local Docker Redis
  (`docker run --rm -p 6379:6379 redis:7.4-alpine` then
  `SHORE_INTEGRATION_TEST=1 pytest tests/integration/test_short_term_redis.py`).
- [ ] Manual smoke: backend starts → chat 3 turns → restart backend →
  reload UI → history restored from Redis.
- [ ] Negative smoke: `docker stop` Redis mid-session → next turn still
  streams; logs show `[Memory] short_term.load degraded`.
- [ ] `back-end/.env` includes `REDIS_URL=redis://localhost:6379/0` for
  local testing.

On the LAN server:

- [ ] `docker compose version` returns v2+.
- [ ] Static IP confirmed; note it as `<SERVER_LAN_IP>`.
- [ ] Data dirs exist with the right owners:
  ```bash
  sudo mkdir -p /var/lib/shore/{redis,postgres,qdrant}
  sudo chown 999:999  /var/lib/shore/redis
  sudo chown 70:70    /var/lib/shore/postgres
  sudo chown 1000:1000 /var/lib/shore/qdrant
  ```
- [ ] Firewall allows ports 6379, 5432, 6333, 6334 from the AI-machine
  subnet only.

### 6.2 Cutover

**Step 1 — Bring up the DB stack on the server.**

```bash
ssh server
cd ~/Shore-Assistant
git pull
cd deploy/memory
cp .env.example .env
$EDITOR .env       # set LAN_BIND_IP and POSTGRES_PASSWORD
docker compose up -d
docker compose ps  # all three: healthy
```

Verify locally on the server:

```bash
redis-cli ping                          # PONG
docker exec shore-postgres pg_isready -U shore -d shore_memory
curl -s http://localhost:6333/healthz
```

Verify reachability from the AI machine:

```bash
redis-cli -h <SERVER_LAN_IP> ping
curl http://<SERVER_LAN_IP>:6333/healthz
```

**Step 2 — Update back-end env.**

`back-end/.env` on the AI machine:

```bash
REDIS_URL=redis://<SERVER_LAN_IP>:6379/0
REDIS_SHORT_TERM_KEY=shore:short_term:messages
MEMORY_MAX_TURNS=15
POSTGRES_URL=postgresql://shore:<password>@<SERVER_LAN_IP>:5432/shore_memory
QDRANT_URL=http://<SERVER_LAN_IP>:6333
# Remove or comment out MEMORY_DIR
```

**Step 3 — Deploy back-end code.**

```bash
cd back-end
git checkout main && git pull
pip install -r requirements.txt
python -m uvicorn app.main:app --port 9000
```

Expected startup log:

```
[Memory] Redis connected at redis://192.168.1.50:6379/0
[Memory] Profile/Episodic stubs registered (Phase 2 pending)
INFO:     Application startup complete.
```

If `[Memory] WARNING: Redis unreachable at startup` appears, return to
Step 1 and verify network / firewall.

**Step 4 — Production smoke test.**

- Open the chat UI → send a message → Shore replies.
- On the server:
  `redis-cli LRANGE shore:short_term:messages 0 -1` → two entries
  (user + assistant), `Message`-shaped JSON.
- Restart the back-end (Ctrl-C then re-run).
- Reload the chat UI → history restored.

**Step 5 — Cleanup.**

```bash
git rm -r back-end/data/memory/   # if not already removed in the PR
```

### 6.3 Rollback

**Quick rollback** (keep the DB stack up, revert back-end):

```bash
cd back-end
git revert <P1_merge_commit_sha>
pip install -r requirements.txt
# restore MEMORY_DIR=data/memory in .env
# restore the backup of default.json:
cp ~/backups/default.json.pre-p1 back-end/data/memory/default.json
python -m uvicorn app.main:app --port 9000
```

Before merging P1, take this backup:

```bash
cp back-end/data/memory/default.json ~/backups/default.json.pre-p1
```

Keep it for at least one week post-ship.

**Full rollback** (remove the DB stack entirely):

```bash
cd ~/Shore-Assistant/deploy/memory
docker compose down              # preserve volumes
# or destructive:
docker compose down -v
sudo rm -rf /var/lib/shore/{redis,postgres,qdrant}/*
```

### 6.4 Day-2 operations

**Restarting Redis** is safe at any time; AOF replay restores state with
≤1 s of loss. `docker compose restart redis` blocks until healthcheck
passes; the chat sees a 5-15 s degraded window. Schedule during idle
periods.

**Manual clear:**
`redis-cli -h <SERVER_LAN_IP> DEL shore:short_term:messages`
or `POST /clear-memory` to the back-end.

**Memory monitoring:**
`redis-cli INFO memory | grep used_memory_human`.
The sliding window caps at 30 messages × <2 KB ≈ 60 KB; running out of
RAM in P1 is not realistic unless large image attachments are involved.
`maxmemory-policy noeviction` ensures any saturation causes a loud write
failure rather than silent eviction.

**Manual backup** (until P4 automation):

```bash
# Server cron @daily
docker exec shore-redis redis-cli BGSAVE
sleep 5
cp /var/lib/shore/redis/dump.rdb ~/backups/redis-$(date +%F).rdb
```

### 6.5 Observability

P1 ships with no metrics framework. System state is observed via:

1. Back-end logs (stdout) — search for the `[Memory]` prefix.
2. `redis-cli INFO` / `LRANGE` / `MONITOR` (debug only).
3. `/health` endpoint — now reports `memory.redis: true|false`.
4. `docker compose ps` on the server.

Prometheus exporters are deferred to Phase 4.

### 6.6 "Shipped successfully" definition

After 24 hours post-cutover, all three are true:

- No `[Memory] *` warnings in back-end logs (excluding startup).
- Redis still up on the server (`docker compose ps`).
- Chat works normally across at least one back-end restart.

When all three hold, P1 is declared shipped; Phase 2 brainstorming may
begin.

---

## 7. Testing Plan

### 7.1 Test inventory

| File | Type | Status |
|------|------|--------|
| `tests/memory/test_types.py` | Unit | NEW |
| `tests/memory/test_short_term.py` | Unit (fakeredis) | NEW |
| `tests/memory/test_facade.py` | Unit (mocked layers) | NEW |
| `tests/integration/test_short_term_redis.py` | Integration | NEW |
| `tests/test_chat_ws_history.py` | Integration | UPDATE |
| `tests/test_chat_ws_concurrent.py` | Integration | UPDATE |
| `tests/test_memory_service.py` | — | DELETE |

### 7.2 `test_types.py`

- `Message.model_dump_json()` round-trips: parse → serialize → parse
  identical.
- `Message.extras` accepts arbitrary nested dicts (thinking,
  agent_actions, attachments).
- `EmotionVector.valence`:
  - all zeros → 0.0
  - `joy=1.0` only → ~0.25
  - max positive Plutchik vector → clamps to +1.0
  - max negative Plutchik vector → clamps to -1.0
- `ProfileChange(new_value=None)` valid (delete semantic).
- `ScoredFact.score` accepts 0.0 and 1.0 at the boundary.

### 7.3 `test_short_term.py` (mocked Redis via fakeredis)

```python
@pytest.mark.asyncio
async def test_append_orders_messages_chronologically(fake_redis):
    st = ShortTermMemory(fake_redis)
    await st.append(Message(role="user", content="hi", timestamp=1.0))
    await st.append(Message(role="assistant", content="hello", timestamp=2.0))
    loaded = await st.load()
    assert [m.timestamp for m in loaded] == [1.0, 2.0]


@pytest.mark.asyncio
async def test_sliding_window_trims_at_limit(fake_redis):
    st = ShortTermMemory(fake_redis)
    for i in range(35):
        await st.append(Message(role="user", content=str(i), timestamp=float(i)))
    loaded = await st.load()
    assert len(loaded) == 30
    assert loaded[0].content == "5"     # oldest kept
    assert loaded[-1].content == "34"   # newest


@pytest.mark.asyncio
async def test_extras_round_trip(fake_redis):
    st = ShortTermMemory(fake_redis)
    extras = {
        "thinking_text": "Let me think...",
        "agent_actions": [{"tool": "x", "status": "completed"}],
        "attachments": [{"type": "image", "mime": "image/png", "data_b64": "iVBOR..."}],
    }
    await st.append(Message(
        role="assistant", content="Done.", timestamp=1.0, extras=extras
    ))
    loaded = await st.load()
    assert loaded[0].extras == extras


@pytest.mark.asyncio
async def test_clear_deletes_key(fake_redis):
    st = ShortTermMemory(fake_redis)
    await st.append(Message(role="user", content="x", timestamp=1.0))
    assert await st.clear() is True
    assert await st.load() == []
    assert await st.clear() is False    # idempotent


@pytest.mark.asyncio
async def test_health_ok_when_reachable(fake_redis):
    assert await ShortTermMemory(fake_redis).health() is True


@pytest.mark.asyncio
async def test_health_false_when_redis_disconnected(fake_redis):
    await fake_redis.connection_pool.disconnect()
    assert await ShortTermMemory(fake_redis).health() is False
```

### 7.4 `test_facade.py`

```python
@pytest.mark.asyncio
async def test_assemble_context_returns_empty_when_redis_down(monkeypatch):
    async def boom():
        raise RedisError("connection refused")
    monkeypatch.setattr(memory_facade.short_term, "load", boom)
    bundle = await memory_facade.assemble_context("hello")
    assert bundle.short_term == []
    assert bundle.profile == {}
    assert bundle.episodic_hits == []


@pytest.mark.asyncio
async def test_assemble_context_timeout_degrades(monkeypatch):
    async def slow():
        await asyncio.sleep(2.0)
        return []
    monkeypatch.setattr(memory_facade.short_term, "load", slow)
    t0 = time.monotonic()
    bundle = await memory_facade.assemble_context("hello")
    assert time.monotonic() - t0 < 0.7
    assert bundle.short_term == []


@pytest.mark.asyncio
async def test_assemble_context_runs_parallel(fake_redis, monkeypatch):
    """asyncio.gather: 3 × 100ms calls should take ~100ms, not ~300ms."""
    async def slow_load():
        await asyncio.sleep(0.1)
        return []
    monkeypatch.setattr(memory_facade.short_term, "load", slow_load)
    # similar slow stubs on profile.read / episodic.search
    t0 = time.monotonic()
    await memory_facade.assemble_context("x")
    assert time.monotonic() - t0 < 0.2


@pytest.mark.asyncio
async def test_append_user_no_op_when_facade_not_started():
    facade = MemoryFacade()
    await facade.append_user("hi")    # must not raise
```

### 7.5 `test_short_term_redis.py` (integration)

Gated by `SHORE_INTEGRATION_TEST=1`. Uses Redis DB 15 to isolate.

```python
@pytest.fixture(scope="module")
async def real_redis():
    redis = Redis.from_url("redis://localhost:6379/15", decode_responses=True)
    yield redis
    await redis.flushdb()
    await redis.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_aof_survives_restart(real_redis):
    """Append messages, simulate restart, confirm persistence."""
    # ... append 5 messages, close, reconnect, LRANGE assertions


@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_appends_safe():
    """asyncio.gather 100 appends; LLEN equals min(30, 100)."""
```

### 7.6 Refactor of existing tests

`test_chat_ws_history.py`:

```python
# Before
monkeypatch.setattr(
    memory_module.memory_service, "load", lambda session_id: fake_history
)

# After
async def fake_load():
    return [Message(**m) for m in fake_history]
monkeypatch.setattr(memory_facade.short_term, "load", fake_load)
```

`test_chat_ws_concurrent.py` follows the same transform and additionally
asserts that `memory_facade.append_user` (not the old service) is called.

### 7.7 Performance gate

The PR description must include a perf block measured on LAN:

```
short_term.load()              p95 = ___ ms  (budget < 10 ms)
short_term.append()            p95 = ___ ms  (budget < 10 ms)
facade.assemble_context()      p95 = ___ ms  (budget < 80 ms)
```

A simple driver lives at `back-end/scripts/bench_memory.py` and runs 100
iterations, reporting p50 / p95 / p99.

### 7.8 Explicit non-goals for P1 tests

- Postgres / Qdrant integration (P2).
- Worker behavior (P3).
- Browser end-to-end automation — manual smoke is enough; e2e is
  deferred.
- AOF persistence under power loss — not feasible in CI; covered by
  manual smoke instead.

### 7.9 CI gates

If a CI pipeline exists:

- Default job: unit tests only (`pytest tests/memory/`).
- Optional job: integration tests with a `redis:7.4-alpine` service
  container.

If no CI pipeline exists, the discipline is local-only; this is recorded
in `CLAUDE.md` under "Commands".

---

## 8. Open Items

- **Chat History Rehydration** must ship first (spec 2026-06-03). P1
  assumes the `extras` field is already populated in the legacy JSON
  before the JSON path is removed.
- **AI-machine static IP for Redis URL** — recorded in `back-end/.env`
  on the AI machine, not in the repo.
- Anything not listed in §1.1 is out of scope and belongs to a later
  phase or sub-spec.
