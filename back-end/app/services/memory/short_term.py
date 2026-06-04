"""
Redis-backed short-term sliding window over recent chat messages.

The window key holds a Redis LIST with at most ``MEMORY_MAX_TURNS * 2``
elements, each a JSON-encoded `Message`. LPUSH puts the newest entry at
index 0; LTRIM enforces the cap atomically in the same pipeline.
"""

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import settings
from app.services.memory.types import Message


class ShortTermMemory:
    def __init__(self, redis: Redis):
        self._redis = redis

    @property
    def _key(self) -> str:
        return settings.REDIS_SHORT_TERM_KEY

    @property
    def _limit(self) -> int:
        return settings.MEMORY_MAX_TURNS * 2  # messages, not turns

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
