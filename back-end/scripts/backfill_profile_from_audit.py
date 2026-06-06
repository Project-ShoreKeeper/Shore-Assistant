"""Rebuild profile.data by replaying profile_history in chronological order.

Background: before commit X, ``ProfileMemory.apply_change`` used
``jsonb_set(data, path, value, true)`` which silently no-ops when any
intermediate parent on the path is missing. Every nested-path write since
the LOCOMO worker landed was recorded in the audit log but never reached
``profile.data``. The audit log is the source of truth — replay it.

Usage (from back-end/):

    python -m scripts.backfill_profile_from_audit            # dry run
    python -m scripts.backfill_profile_from_audit --apply    # write

The script writes ``profile.data`` directly (one UPDATE) without
inserting new audit rows. Idempotent: re-running yields the same result.
"""
import argparse
import asyncio
import json
import sys

import asyncpg

from app.core.config import settings
from app.services.memory.profile import (
    _delete_at_path,
    _init_pg_conn,
    _key_path_to_pg_path,
    _set_at_path,
)


async def _rebuild() -> tuple[dict, dict, int]:
    """Return (current_data, rebuilt_data, replayed_row_count)."""
    conn = await asyncpg.connect(dsn=settings.POSTGRES_URL)
    await _init_pg_conn(conn)
    try:
        current_row = await conn.fetchrow(
            "SELECT data FROM profile WHERE id = 1"
        )
        current: dict = dict(current_row["data"]) if current_row else {}

        rows = await conn.fetch(
            "SELECT key_path, new_value FROM profile_history "
            "ORDER BY id ASC"
        )
    finally:
        await conn.close()

    rebuilt: dict = {}
    for r in rows:
        path = _key_path_to_pg_path(r["key_path"])
        if r["new_value"] is None:
            _delete_at_path(rebuilt, path)
        else:
            _set_at_path(rebuilt, path, r["new_value"])

    return current, rebuilt, len(rows)


async def _apply(rebuilt: dict) -> None:
    conn = await asyncpg.connect(dsn=settings.POSTGRES_URL)
    await _init_pg_conn(conn)
    try:
        async with conn.transaction():
            await conn.execute(
                "UPDATE profile SET data = $1, updated_at = NOW() "
                "WHERE id = 1",
                rebuilt,
            )
    finally:
        await conn.close()


def _pretty(d: dict) -> str:
    return json.dumps(d, indent=2, ensure_ascii=False, sort_keys=True)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--apply", action="store_true",
        help="Write the rebuilt profile. Without this flag, runs as a dry run.",
    )
    args = parser.parse_args()

    print(f"Connecting to {settings.POSTGRES_URL}\n")
    current, rebuilt, n_rows = await _rebuild()

    print(f"Replayed {n_rows} audit rows.\n")
    print("== Current profile.data ==")
    print(_pretty(current))
    print()
    print("== Rebuilt profile.data ==")
    print(_pretty(rebuilt))
    print()

    if current == rebuilt:
        print("No changes — profile already matches the audit replay.")
        return 0

    if not args.apply:
        print("Dry run. Re-run with --apply to write the rebuilt data.")
        return 0

    await _apply(rebuilt)
    print("Wrote rebuilt profile to Postgres.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
