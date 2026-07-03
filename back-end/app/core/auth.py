"""Redis-backed session store + user types for Google-OAuth sign-in.

The cookie or Bearer credential carries an opaque session id; the actual
session payload (user, csrf, timestamps) lives in Redis under
``{key_prefix}{sid}`` with a sliding TTL that's refreshed on every
read.

The OAuth-flow state token uses a separate, short-lived one-shot key
under ``{state_prefix}{state}`` — consumed on first read.
"""
import json
import secrets
import time
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Literal, Optional

from redis.asyncio import Redis


# ContextVar carrying the active user's id through the chat-turn lifecycle.
# chat_ws sets it on connection; tools / services read it. Defaults to the
# "legacy" id so legacy/AUTH_DISABLED paths keep working without changes.
current_user_id: ContextVar[str] = ContextVar("current_user_id", default="legacy")

# Role of the user owning the current request/WS turn. Default "admin"
# preserves legacy synthetic-admin behavior when AUTH_ENABLED=False.
current_user_role: ContextVar[str] = ContextVar(
    "current_user_role",
    default="admin",
)


Role = Literal["admin", "user"]


@dataclass(frozen=True)
class User:
    id: str        # Google `sub` claim (stable, opaque)
    email: str
    role: Role


@dataclass(frozen=True)
class Session:
    user: User
    csrf: str
    issued_at: float


class SessionStore:
    """Owns the lifecycle of session and OAuth-state keys in Redis."""

    def __init__(
        self,
        redis: Redis,
        ttl_seconds: int,
        key_prefix: str,
    ) -> None:
        self._redis = redis
        self._ttl = ttl_seconds
        self._prefix = key_prefix

    # ── Session ────────────────────────────────────────────────────

    async def create(self, user: User) -> tuple[str, str]:
        """Create a session for `user`. Returns (sid, csrf)."""
        sid = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        payload = {
            "user": {"id": user.id, "email": user.email, "role": user.role},
            "csrf": csrf,
            "iat": time.time(),
        }
        await self._redis.set(
            f"{self._prefix}{sid}",
            json.dumps(payload),
            ex=self._ttl,
        )
        return sid, csrf

    async def read(self, sid: str) -> Optional[Session]:
        """Read + refresh sliding TTL. Returns None if missing/expired."""
        key = f"{self._prefix}{sid}"
        raw = await self._redis.get(key)
        if raw is None:
            return None
        await self._redis.expire(key, self._ttl)
        data = json.loads(raw)
        u = data["user"]
        return Session(
            user=User(id=u["id"], email=u["email"], role=u["role"]),
            csrf=data["csrf"],
            issued_at=data["iat"],
        )

    async def delete(self, sid: str) -> None:
        await self._redis.delete(f"{self._prefix}{sid}")

    # ── OAuth state (one-shot) ─────────────────────────────────────

    async def create_oauth_state(
        self, ttl_seconds: int, prefix: str, client: str = "",
    ) -> str:
        """Create a one-shot OAuth state token.

        `client` optionally tags which flow initiated the login (e.g.
        "desktop" for the Tauri app's system-browser handoff) so
        `/callback` can branch on it after consuming the state. Empty
        string is the plain/legacy web flow and is stored as the same
        "1" sentinel used before the desktop flow existed.
        """
        state = secrets.token_urlsafe(32)
        value = client or "1"
        await self._redis.set(f"{prefix}{state}", value, ex=ttl_seconds)
        return state

    async def consume_oauth_state(
        self, state: str, prefix: str,
    ) -> Optional[str]:
        """Consume (delete) a one-shot OAuth state.

        Returns the tagged client string ("" for the plain/legacy "1"
        sentinel, e.g. "desktop" for desktop-originated flows), or
        None if the state didn't exist (invalid, expired, or already
        consumed).
        """
        key = f"{prefix}{state}"
        # GET then DELETE (two round-trips): GETDEL isn't on every
        # redis-py version we support, and we need the stored value
        # (not just existence) to recover the client tag.
        raw = await self._redis.get(key)
        if raw is None:
            return None
        await self._redis.delete(key)
        return "" if raw == "1" else raw

    # ── Exchange token (one-shot, desktop OAuth handoff) ────────────

    async def create_exchange_token(
        self, sid: str, ttl_seconds: int, prefix: str,
    ) -> str:
        """Mint a one-time token mapping to a session id.

        Used by the desktop OAuth flow: `/callback` mints this token and
        deep-links it back into the app; `/exchange` consumes it and
        returns the mapped session id as a Bearer access token.
        """
        token = secrets.token_urlsafe(32)
        await self._redis.set(f"{prefix}{token}", sid, ex=ttl_seconds)
        return token

    async def consume_exchange_token(
        self, token: str, prefix: str,
    ) -> Optional[str]:
        """Return the sid mapped to `token` and delete it (single-use).

        Returns None if the token is missing, expired, or already
        consumed.
        """
        key = f"{prefix}{token}"
        sid = await self._redis.get(key)
        if sid is None:
            return None
        await self._redis.delete(key)
        return sid
