"""Profile memory — Postgres JSONB single-row snapshot + audit log."""
import asyncpg
import json
from typing import Any, Optional

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


def _read_at_path(data: dict, path: list[str]) -> Any:
    cur: Any = data
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


def _set_at_path(data: dict, path: list[str], value: Any) -> None:
    """Set value at path; create or clobber any non-object intermediate."""
    cur = data
    for key in path[:-1]:
        existing = cur.get(key)
        if not isinstance(existing, dict):
            cur[key] = {}
        cur = cur[key]
    cur[path[-1]] = value


def _delete_at_path(data: dict, path: list[str]) -> None:
    """Pop the leaf at path. No-op if any ancestor is missing or non-object."""
    cur = data
    for key in path[:-1]:
        existing = cur.get(key)
        if not isinstance(existing, dict):
            return
        cur = existing
    cur.pop(path[-1], None)


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
        # Postgres jsonb_set does NOT create missing intermediate path
        # components — `jsonb_set(data, '{a,b,c}', v, true)` silently
        # returns `data` unchanged when `a` or `a.b` don't exist. We
        # read-modify-write the whole dict to handle nested paths
        # correctly. `SELECT FOR UPDATE` keeps the change atomic.
        path = _key_path_to_pg_path(change.key_path)
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT data FROM profile WHERE id = 1 FOR UPDATE"
                )
                data: dict = dict(row["data"]) if row else {}

                old = _read_at_path(data, path)
                if change.new_value is None:
                    _delete_at_path(data, path)
                else:
                    _set_at_path(data, path, change.new_value)

                await conn.execute(
                    "UPDATE profile SET data = $1, "
                    "updated_at = NOW() WHERE id = 1",
                    data,
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

    async def audit_recent(self, limit: int = 50) -> list[dict]:
        """Global audit log across all keys, newest first."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, key_path, old_value, new_value, source_turn_ts,
                       confidence, reason, created_at
                FROM profile_history
                ORDER BY created_at DESC
                LIMIT $1
                """,
                limit,
            )
            return [dict(r) for r in rows]

    async def restore(self, audit_id: int, reason: Optional[str] = None) -> dict:
        """Apply the old_value of a past audit row as a new ProfileChange.

        Returns the freshly inserted audit row. Raises ValueError if the
        audit_id does not exist.
        """
        async with self._pool.acquire() as conn:
            target = await conn.fetchrow(
                "SELECT key_path, old_value FROM profile_history WHERE id = $1",
                audit_id,
            )
            if target is None:
                raise ValueError(f"audit id {audit_id} not found")
        change = ProfileChange(
            key_path=target["key_path"],
            new_value=target["old_value"],
            source_turn_ts=0.0,
            confidence=1.0,
            reason=reason or f"restored from audit #{audit_id}",
        )
        await self.apply_change(change)
        async with self._pool.acquire() as conn:
            new_row = await conn.fetchrow(
                """
                SELECT id, key_path, old_value, new_value, source_turn_ts,
                       confidence, reason, created_at
                FROM profile_history
                WHERE key_path = $1
                ORDER BY id DESC
                LIMIT 1
                """,
                target["key_path"],
            )
            return dict(new_row)

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
