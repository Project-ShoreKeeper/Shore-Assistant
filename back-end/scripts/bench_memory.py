"""
Simple perf check for short-term memory.

Usage:
    python scripts/bench_memory.py

Reports p50/p95/p99 for short_term.load(), short_term.append(),
and facade.assemble_context().
"""

import asyncio
import statistics
import time

from app.services.memory import memory_facade
from app.services.memory.types import Message


N = 100


async def measure(name, coro_factory):
    samples = []
    for _ in range(N):
        t0 = time.perf_counter()
        await coro_factory()
        samples.append((time.perf_counter() - t0) * 1000.0)
    samples.sort()
    p50 = statistics.median(samples)
    p95 = samples[int(N * 0.95) - 1]
    p99 = samples[int(N * 0.99) - 1]
    print(f"{name:32s}  p50={p50:6.2f}ms  p95={p95:6.2f}ms  p99={p99:6.2f}ms")


async def main():
    await memory_facade.startup()

    msg = Message(role="user", content="bench", timestamp=time.time())
    await measure(
        "short_term.append()",
        lambda: memory_facade.short_term.append(msg),
    )
    await measure(
        "short_term.load()",
        lambda: memory_facade.short_term.load(),
    )
    await measure(
        "facade.assemble_context()",
        lambda: memory_facade.assemble_context("hello"),
    )

    await memory_facade.clear()
    await memory_facade.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
