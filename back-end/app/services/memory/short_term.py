"""
Redis-backed short-term sliding window over recent chat messages.

The window key holds a Redis LIST per user
(``{REDIS_SHORT_TERM_KEY}:{user_id}:messages``) with at most
``MEMORY_MAX_TURNS * 2`` elements, each a JSON-encoded `Message`.
LPUSH puts the newest entry at index 0; LTRIM enforces the cap
atomically in the same pipeline.
"""

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import settings
from app.services.memory.types import Message


class ShortTermMemory:
    def __init__(self, redis: Redis):
        self._redis = redis

    def _key(self, user_id: str) -> str:
        return f"{settings.REDIS_SHORT_TERM_KEY}:{user_id}:messages"

    @property
    def _limit(self) -> int:
        return settings.MEMORY_MAX_TURNS * 2  # messages, not turns

    async def append(self, message: Message, user_id: str) -> None:
        payload = message.model_dump_json()
        key = self._key(user_id)
        pipe = self._redis.pipeline()
        pipe.lpush(key, payload)
        pipe.ltrim(key, 0, self._limit - 1)
        await pipe.execute()

    async def load(self, user_id: str) -> list[Message]:
        raw = await self._redis.lrange(self._key(user_id), 0, -1)
        return [Message.model_validate_json(item) for item in reversed(raw)]

    async def clear(self, user_id: str) -> bool:
        deleted = await self._redis.delete(self._key(user_id))
        return deleted > 0

    async def health(self) -> bool:
        try:
            await self._redis.ping()
            return True
        except RedisError:
            return False
