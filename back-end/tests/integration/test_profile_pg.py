"""Integration tests for ProfileMemory against a real Postgres.

Opt-in: set `RUN_PG_INTEGRATION=1` to run.

Each test gets a fresh, isolated schema (`shore_test_<uuid8>`) created on the
DSN from `POSTGRES_TEST_URL` (fallback: `POSTGRES_URL`, fallback: the default
docker-compose DSN). The schema is dropped on teardown.

We pin every pooled connection's `search_path` to the test schema so the
unqualified `profile` / `profile_history` references inside `ProfileMemory`
resolve there instead of `public`.
"""

import os
import uuid
from typing import AsyncIterator

import asyncpg
import pytest
import pytest_asyncio

from app.services.memory.profile import ProfileMemory, _init_pg_conn
from app.services.memory.types import ProfileChange


PG_URL = (
    os.getenv("POSTGRES_TEST_URL")
    or os.getenv("POSTGRES_URL")
    or "postgresql://shore:changeme@localhost:5432/shore_memory"
)


pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_PG_INTEGRATION"),
    reason="Set RUN_PG_INTEGRATION=1 to run real-Postgres integration tests",
)


_SCHEMA_DDL_TEMPLATE = """
CREATE TABLE {schema}.profile (
    id          SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    data        JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE {schema}.profile_history (
    id              BIGSERIAL PRIMARY KEY,
    key_path        TEXT NOT NULL,
    old_value       JSONB,
    new_value       JSONB,
    source_turn_ts  DOUBLE PRECISION,
    confidence      REAL,
    reason          TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
INSERT INTO {schema}.profile (id, data) VALUES (1, '{{}}'::jsonb);
"""


@pytest_asyncio.fixture
async def pg_profile() -> AsyncIterator[ProfileMemory]:
    schema = f"shore_test_{uuid.uuid4().hex[:8]}"

    admin = await asyncpg.connect(PG_URL)
    try:
        await admin.execute(f'CREATE SCHEMA "{schema}"')
        await admin.execute(_SCHEMA_DDL_TEMPLATE.format(schema=f'"{schema}"'))
    finally:
        await admin.close()

    async def setup(conn: asyncpg.Connection) -> None:
        # Per-acquire hook: asyncpg resets session state on release,
        # so search_path must be set on every acquire, not just at
        # physical connection creation.
        await conn.execute(f'SET search_path TO "{schema}", public')

    pm = ProfileMemory()
    pm._pool = await asyncpg.create_pool(
        dsn=PG_URL, min_size=1, max_size=2, command_timeout=5.0,
        init=_init_pg_conn, setup=setup,
    )
    try:
        yield pm
    finally:
        await pm._pool.close()
        admin = await asyncpg.connect(PG_URL)
        try:
            await admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
        finally:
            await admin.close()


def _change(key_path: str, new_value, reason: str = "test") -> ProfileChange:
    return ProfileChange(
        key_path=key_path,
        new_value=new_value,
        source_turn_ts=0.0,
        confidence=1.0,
        reason=reason,
    )


async def test_root_key_write(pg_profile: ProfileMemory):
    await pg_profile.apply_change(_change("name", "Luna"))
    assert await pg_profile.read() == {"name": "Luna"}


async def test_nested_path_creates_intermediates(pg_profile: ProfileMemory):
    """Regression: jsonb_set silently no-ops when parents don't exist."""
    await pg_profile.apply_change(
        _change("preferences.beverage.coffee", "mint latte"),
    )
    assert await pg_profile.read() == {
        "preferences": {"beverage": {"coffee": "mint latte"}},
    }


async def test_nested_path_under_existing_object(pg_profile: ProfileMemory):
    await pg_profile.apply_change(_change("role", {"title": "dev"}))
    await pg_profile.apply_change(
        _change("role.achievements.memory_system", {"built_by": "Luna"}),
    )
    data = await pg_profile.read()
    assert data["role"]["title"] == "dev"
    assert data["role"]["achievements"]["memory_system"] == {"built_by": "Luna"}


async def test_delete_removes_nested_leaf(pg_profile: ProfileMemory):
    await pg_profile.apply_change(_change("a.b.c", "x"))
    await pg_profile.apply_change(_change("a.b.c", None))
    assert await pg_profile.read() == {"a": {"b": {}}}


async def test_delete_on_missing_path_is_noop(pg_profile: ProfileMemory):
    await pg_profile.apply_change(_change("does.not.exist", None))
    assert await pg_profile.read() == {}


async def test_intermediate_scalar_is_clobbered(pg_profile: ProfileMemory):
    """Writing a child path of a scalar replaces the scalar with an object.

    Matches jsonb_set's behavior for leaf overwrites; preferable to the
    silent-failure trap the bug created.
    """
    await pg_profile.apply_change(_change("name", "Luna"))
    await pg_profile.apply_change(_change("name.first", "Luna"))
    assert await pg_profile.read() == {"name": {"first": "Luna"}}


async def test_audit_captures_old_value_for_nested_path(
    pg_profile: ProfileMemory,
):
    await pg_profile.apply_change(
        _change("preferences.beverage.coffee", "espresso", reason="initial"),
    )
    await pg_profile.apply_change(
        _change("preferences.beverage.coffee", "mint latte", reason="changed"),
    )
    rows = await pg_profile.history("preferences.beverage.coffee", limit=5)
    assert len(rows) == 2
    assert rows[0]["new_value"] == "mint latte"
    assert rows[0]["old_value"] == "espresso"
    assert rows[1]["new_value"] == "espresso"
    assert rows[1]["old_value"] is None
