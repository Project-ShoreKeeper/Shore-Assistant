"""Profile memory stub — implemented in Phase 2 against Postgres."""

from typing import Any


class ProfileMemory:
    async def read(self) -> dict:
        return {}

    async def apply_change(self, change: Any) -> None:
        raise NotImplementedError("Profile writes wired in Phase 2")

    async def health(self) -> bool:
        return False
