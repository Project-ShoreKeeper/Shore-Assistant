"""LOCOMO worker — debounced extraction of facts from short-term turns."""
import asyncio
from typing import Optional

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import settings
from app.services.memory.extractor import LocomoExtractor, ExtractorDisabled
from app.services.memory.types import Message


class WorkerService:
    def __init__(self):
        self._redis: Optional[Redis] = None
        self._extractor: Optional[LocomoExtractor] = None
        self._facade = None  # injected during startup to avoid circular import
        self._lock = asyncio.Lock()
        self._pending_task: Optional[asyncio.Task] = None

    async def get_last_extracted_ts(self) -> float:
        if self._redis is None:
            return 0.0
        try:
            raw = await self._redis.get(settings.WORKER_LAST_TS_KEY)
        except RedisError:
            return 0.0
        return float(raw) if raw else 0.0

    async def set_last_extracted_ts(self, ts: float) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.set(settings.WORKER_LAST_TS_KEY, str(ts))
        except RedisError as e:
            print(f"[Worker] set_last_extracted_ts failed: {e}")

    async def extract(self) -> None:
        """Read new short-term turns, extract via Gemini, apply to Profile + Episodic."""
        if self._facade is None or self._extractor is None:
            print("[Worker] extract skipped — not started")
            return
        if self._lock.locked():
            print("[Worker] extract skipped — asyncio lock held")
            return

        async with self._lock:
            if not await self._acquire_redis_lock():
                print("[Worker] extract skipped — redis lock held by another process")
                return
            try:
                await self._extract_inner()
            finally:
                await self._release_redis_lock()

    async def _acquire_redis_lock(self) -> bool:
        if self._redis is None:
            return True
        try:
            ok = await self._redis.set(
                settings.WORKER_LOCK_KEY, "1",
                nx=True, ex=settings.WORKER_LOCK_TTL_SECONDS,
            )
            return bool(ok)
        except RedisError as e:
            print(f"[Worker] redis SETNX failed: {e}")
            return False

    async def _release_redis_lock(self) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.delete(settings.WORKER_LOCK_KEY)
        except RedisError as e:
            print(f"[Worker] redis lock release failed: {e}")

    async def _extract_inner(self) -> None:
        last_ts = await self.get_last_extracted_ts()
        all_turns = await self._facade.short_term.load()
        unprocessed: list[Message] = [
            m for m in all_turns if m.timestamp > last_ts
        ]
        if not unprocessed:
            return

        profile_snapshot = await self._facade.profile.read()

        try:
            output = await self._extractor.extract(
                turns=unprocessed, profile_snapshot=profile_snapshot,
            )
        except ExtractorDisabled as e:
            print(f"[Worker] extractor disabled: {e}")
            return
        except Exception as e:
            print(f"[Worker] extract failed (no state changed): {e!r}")
            return

        for change in output.profile_changes:
            try:
                await self._facade.profile.apply_change(change)
            except Exception as e:
                print(f"[Worker] profile.apply_change failed: {e!r}")

        for fact in output.episodic_facts:
            try:
                await self._facade.episodic.upsert(fact)
            except Exception as e:
                print(f"[Worker] episodic.upsert failed: {e!r}")

        newest_ts = max(m.timestamp for m in unprocessed)
        await self.set_last_extracted_ts(newest_ts)
        print(
            f"[Worker] extracted "
            f"{len(output.profile_changes)} profile change(s) + "
            f"{len(output.episodic_facts)} episodic fact(s); "
            f"last_ts → {newest_ts}"
        )


    async def on_turn_completed(self) -> None:
        """Hook called by chat_ws after each assistant turn is persisted."""
        if not settings.WORKER_ENABLED:
            return

        if await self._safety_valve_should_fire():
            await self._cancel_pending()
            self._pending_task = asyncio.create_task(self.extract())
            return

        await self._cancel_pending()
        self._pending_task = asyncio.create_task(self._delayed_extract())

    async def startup(self, redis: Redis, facade) -> None:
        """Wire dependencies. Idempotent."""
        if not settings.WORKER_ENABLED:
            print("[Worker] disabled — startup skipped")
            return
        self._redis = redis
        self._facade = facade
        self._extractor = LocomoExtractor()
        print(
            f"[Worker] ready — model={settings.WORKER_GEMINI_MODEL} "
            f"idle_delay={settings.WORKER_IDLE_DELAY_SECONDS}s "
            f"safety_valve={settings.WORKER_MAX_UNPROCESSED_MESSAGES}"
        )

    async def shutdown(self) -> None:
        await self._cancel_pending()

    async def _safety_valve_should_fire(self) -> bool:
        if self._facade is None:
            return False
        try:
            last_ts = await self.get_last_extracted_ts()
            turns = await self._facade.short_term.load()
            unprocessed = sum(1 for m in turns if m.timestamp > last_ts)
            return unprocessed >= settings.WORKER_MAX_UNPROCESSED_MESSAGES
        except Exception as e:
            print(f"[Worker] safety_valve check failed: {e!r}")
            return False

    async def _delayed_extract(self) -> None:
        try:
            await asyncio.sleep(settings.WORKER_IDLE_DELAY_SECONDS)
        except asyncio.CancelledError:
            return
        await self.extract()

    async def _cancel_pending(self) -> None:
        task = self._pending_task
        if task and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._pending_task = None


worker_service = WorkerService()
