"""Integration tests — require a real Postgres at POSTGRES_URL with the Phase 2 schema.

Gated by SHORE_INTEGRATION_TEST=1. Tests reset the profile and history tables
at the start so they are repeatable.
"""

import os

import pytest
import pytest_asyncio

from app.services.memory.profile import ProfileMemory
from app.services.memory.types import ProfileChange


pytestmark = pytest.mark.skipif(
    os.getenv("SHORE_INTEGRATION_TEST") != "1",
    reason="Integration tests opt-in via SHORE_INTEGRATION_TEST=1",
)


@pytest_asyncio.fixture
async def profile():
    pm = ProfileMemory()
    await pm.startup()
    # Reset state for repeatability
    async with pm._pool.acquire() as conn:
        await conn.execute("UPDATE profile SET data = '{}'::jsonb WHERE id = 1")
        await conn.execute("DELETE FROM profile_history")
    yield pm
    await pm.shutdown()


async def test_three_consecutive_changes_yield_three_history_rows(profile):
    for v in [True, True, False]:
        await profile.apply_change(ProfileChange(
            key_path="like_tea", new_value=v,
            source_turn_ts=1.0, confidence=0.9, reason="test",
        ))
    assert (await profile.read())["like_tea"] is False
    hist = await profile.history("like_tea", limit=10)
    assert len(hist) == 3


async def test_delete_removes_key_and_logs_null_new_value(profile):
    await profile.apply_change(ProfileChange(
        key_path="name", new_value="Luna",
        source_turn_ts=1.0, confidence=1.0, reason="seed",
    ))
    await profile.apply_change(ProfileChange(
        key_path="name", new_value=None,
        source_turn_ts=2.0, confidence=1.0, reason="forget",
    ))
    assert "name" not in await profile.read()
    hist = await profile.history("name", limit=10)
    assert hist[0]["new_value"] is None


async def test_nested_key_path_round_trips(profile):
    await profile.apply_change(ProfileChange(
        key_path="projects.shore.status", new_value="active",
        source_turn_ts=1.0, confidence=0.9, reason="seed",
    ))
    data = await profile.read()
    assert data["projects"]["shore"]["status"] == "active"


async def test_key_updated_at_map_returns_floats(profile):
    await profile.apply_change(ProfileChange(
        key_path="a", new_value=1, source_turn_ts=1.0,
        confidence=1.0, reason="x",
    ))
    ts_map = await profile.key_updated_at_map()
    assert "a" in ts_map
    assert isinstance(ts_map["a"], float)
