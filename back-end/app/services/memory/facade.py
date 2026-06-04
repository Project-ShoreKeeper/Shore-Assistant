"""
MemoryFacade — the single entry-point chat_ws and agent_service use.

Read-path methods fan out to short_term + profile + episodic in
parallel via asyncio.gather, each guarded by a 500 ms timeout and a
try/except so a failing layer never breaks chat.
"""

import asyncio
import time
from typing import Optional

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import settings
from app.services.memory.episodic import EpisodicMemory
from app.services.memory.profile import ProfileMemory
from app.services.memory.pruning import prune_profile
from app.services.memory.short_term import ShortTermMemory
from app.services.memory.types import ContextBundle, Message


_TIMEOUT = 0.5


class MemoryFacade:
    def __init__(self):
        self._redis: Optional[Redis] = None
        self.short_term: Optional[ShortTermMemory] = None
        self.profile = ProfileMemory()
        self.episodic = EpisodicMemory()

    async def startup(self) -> None:
        # Redis (short-term)
        self._redis = Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_timeout=_TIMEOUT,
            socket_connect_timeout=1.0,
            max_connections=10,
        )
        self.short_term = ShortTermMemory(self._redis)
        redis_ok = await self.short_term.health()

        # Profile (Postgres) — independent failure
        try:
            await self.profile.startup()
            pg_ok = await self.profile.health()
        except Exception as e:
            print(f"[Memory] Postgres startup failed: {e}")
            pg_ok = False

        # Episodic (Qdrant) — independent failure
        try:
            await self.episodic.startup()
            qd_ok = await self.episodic.health()
        except Exception as e:
            print(f"[Memory] Qdrant startup failed: {e}")
            qd_ok = False

        print(
            f"[Memory] redis={redis_ok} postgres={pg_ok} qdrant={qd_ok}"
        )

    async def shutdown(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
        await self.profile.shutdown()
        await self.episodic.shutdown()

    async def assemble_context(self, user_text: str) -> ContextBundle:
        short_term, profile_raw, episodic = await asyncio.gather(
            self._safe_load_short_term(),
            self._safe_read_profile(),
            self._safe_search_episodic(user_text),
        )
        profile = await self._safe_prune_profile(profile_raw)
        return ContextBundle(
            short_term=short_term,
            profile=profile,
            episodic_hits=episodic,
        )

    async def append_user(
        self, content: str, extras: Optional[dict] = None,
    ) -> None:
        await self._safe_append(Message(
            role="user", content=content, timestamp=time.time(), extras=extras,
        ))

    async def append_assistant(
        self, content: str, extras: Optional[dict] = None,
    ) -> None:
        await self._safe_append(Message(
            role="assistant", content=content, timestamp=time.time(),
            extras=extras,
        ))

    async def clear(self) -> bool:
        if self.short_term is None:
            return False
        try:
            return await self.short_term.clear()
        except RedisError as e:
            print(f"[Memory] clear failed: {e}")
            return False

    # ── private helpers ─────────────────────────────────────────────

    async def _safe_load_short_term(self):
        if self.short_term is None:
            return []
        try:
            return await asyncio.wait_for(
                self.short_term.load(), timeout=_TIMEOUT,
            )
        except (RedisError, asyncio.TimeoutError) as e:
            print(f"[Memory] short_term.load degraded: {e}")
            return []

    async def _safe_read_profile(self):
        try:
            return await asyncio.wait_for(
                self.profile.read(), timeout=_TIMEOUT,
            )
        except (Exception, asyncio.TimeoutError) as e:
            print(f"[Memory] profile.read degraded: {e}")
            return {}

    async def _safe_search_episodic(self, query: str):
        try:
            return await asyncio.wait_for(
                self.episodic.search(query), timeout=_TIMEOUT,
            )
        except (Exception, asyncio.TimeoutError) as e:
            print(f"[Memory] episodic.search degraded: {e}")
            return []

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
        return prune_profile(
            raw, ts_map, max_bytes=settings.MEMORY_PROFILE_MAX_BYTES,
        )

    async def _safe_append(self, message: Message) -> None:
        if self.short_term is None:
            print("[Memory] append skipped — facade not started")
            return
        try:
            await self.short_term.append(message)
        except RedisError as e:
            print(f"[Memory] short_term.append failed: {e}")


memory_facade = MemoryFacade()
