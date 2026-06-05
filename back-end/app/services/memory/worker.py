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


worker_service = WorkerService()
