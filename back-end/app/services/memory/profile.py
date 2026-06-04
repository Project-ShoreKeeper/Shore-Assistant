"""Profile memory — Postgres JSONB single-row snapshot + audit log."""
import asyncpg
import json
from typing import Optional

from app.core.config import settings
from app.services.memory.types import ProfileChange


async def _init_pg_conn(conn: asyncpg.Connection) -> None:
    """Register a JSONB / JSON codec on every connection acquired from the pool.
    Without this, asyncpg cannot serialize Python dicts/values into JSONB
    columns or deserialize JSONB rows back into Python dicts.
    """
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )
    await conn.set_type_codec(
        "json",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )


def _key_path_to_pg_path(key_path: str) -> list[str]:
    """Convert 'projects.shore.status' -> ['projects','shore','status']."""
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
            init=_init_pg_conn,
        )

    async def shutdown(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

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
                        "data, $1, $2, true), "
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
        self, key_path: str, limit: int = 20,
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
