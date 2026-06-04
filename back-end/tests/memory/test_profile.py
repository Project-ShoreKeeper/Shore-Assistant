"""Unit tests for ProfileMemory — asyncpg mocked."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.memory.profile import ProfileMemory, _key_path_to_pg_path
from app.services.memory.types import ProfileChange


def _make_pool_with_conn(conn: AsyncMock) -> AsyncMock:
    """Wrap an AsyncMock connection so `async with pool.acquire() as conn:` works."""
    acquire_ctx = AsyncMock()
    acquire_ctx.__aenter__.return_value = conn
    acquire_ctx.__aexit__.return_value = None
    pool = AsyncMock()
    pool.acquire = MagicMock(return_value=acquire_ctx)
    return pool


def _make_tx(conn: AsyncMock) -> None:
    """Attach a working async-context-manager transaction() to the conn mock."""
    tx_ctx = AsyncMock()
    tx_ctx.__aenter__.return_value = None
    tx_ctx.__aexit__.return_value = None
    conn.transaction = MagicMock(return_value=tx_ctx)


def test_key_path_to_pg_path_splits_on_dot():
    assert _key_path_to_pg_path("a.b.c") == ["a", "b", "c"]
    assert _key_path_to_pg_path("name") == ["name"]


async def test_read_returns_empty_dict_when_no_row():
    conn = AsyncMock()
    conn.fetchrow.return_value = None
    pool = _make_pool_with_conn(conn)

    pm = ProfileMemory()
    pm._pool = pool
    assert await pm.read() == {}


async def test_read_returns_data_dict():
    conn = AsyncMock()
    conn.fetchrow.return_value = {"data": {"name": "Luna"}}
    pool = _make_pool_with_conn(conn)

    pm = ProfileMemory()
    pm._pool = pool
    assert await pm.read() == {"name": "Luna"}


async def test_apply_change_uses_jsonb_set_for_value():
    conn = AsyncMock()
    conn.fetchval.return_value = None
    _make_tx(conn)
    pool = _make_pool_with_conn(conn)

    pm = ProfileMemory()
    pm._pool = pool

    await pm.apply_change(ProfileChange(
        key_path="name", new_value="Luna",
        source_turn_ts=1.0, confidence=0.9, reason="test",
    ))

    # First execute = UPDATE jsonb_set, second = INSERT history.
    update_sql = conn.execute.await_args_list[0].args[0]
    insert_sql = conn.execute.await_args_list[1].args[0]
    assert "jsonb_set" in update_sql
    assert "INSERT INTO profile_history" in insert_sql


async def test_apply_change_uses_minus_operator_for_delete():
    conn = AsyncMock()
    conn.fetchval.return_value = "Luna"
    _make_tx(conn)
    pool = _make_pool_with_conn(conn)

    pm = ProfileMemory()
    pm._pool = pool

    await pm.apply_change(ProfileChange(
        key_path="name", new_value=None,
        source_turn_ts=1.0, confidence=1.0, reason="forget",
    ))

    update_sql = conn.execute.await_args_list[0].args[0]
    assert "data #- $1" in update_sql


async def test_apply_change_carries_old_value_into_history():
    conn = AsyncMock()
    conn.fetchval.return_value = "espresso"
    _make_tx(conn)
    pool = _make_pool_with_conn(conn)

    pm = ProfileMemory()
    pm._pool = pool

    await pm.apply_change(ProfileChange(
        key_path="favorite_coffee", new_value="latte",
        source_turn_ts=2.0, confidence=0.7, reason="changed mind",
    ))

    insert_call = conn.execute.await_args_list[1]
    # Args are: sql, key_path, old, new, source_turn_ts, confidence, reason
    assert insert_call.args[1] == "favorite_coffee"
    assert insert_call.args[2] == "espresso"
    assert insert_call.args[3] == "latte"
    assert insert_call.args[6] == "changed mind"


async def test_history_orders_descending_with_limit():
    conn = AsyncMock()
    conn.fetch.return_value = []
    pool = _make_pool_with_conn(conn)

    pm = ProfileMemory()
    pm._pool = pool
    await pm.history("name", limit=5)

    sql = conn.fetch.await_args.args[0]
    assert "ORDER BY created_at DESC" in sql
    assert conn.fetch.await_args.args[1] == "name"
    assert conn.fetch.await_args.args[2] == 5


async def test_key_updated_at_map_returns_timestamps():
    ts = datetime(2026, 6, 4, tzinfo=timezone.utc)
    conn = AsyncMock()
    conn.fetch.return_value = [
        {"key_path": "name", "ts": ts},
        {"key_path": "favorite_coffee", "ts": ts},
    ]
    pool = _make_pool_with_conn(conn)

    pm = ProfileMemory()
    pm._pool = pool
    result = await pm.key_updated_at_map()
    assert set(result.keys()) == {"name", "favorite_coffee"}
    assert all(isinstance(v, float) for v in result.values())


async def test_health_false_when_pool_none():
    pm = ProfileMemory()
    assert await pm.health() is False


async def test_health_true_after_successful_select():
    conn = AsyncMock()
    conn.execute.return_value = "SELECT 1"
    pool = _make_pool_with_conn(conn)
    pm = ProfileMemory()
    pm._pool = pool
    assert await pm.health() is True
