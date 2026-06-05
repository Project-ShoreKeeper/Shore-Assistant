"""LOCOMO worker — debounced extraction of facts from short-term turns."""
import asyncio
from typing import Optional

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import settings


class WorkerService:
    def __init__(self):
        self._redis: Optional[Redis] = None

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


worker_service = WorkerService()
