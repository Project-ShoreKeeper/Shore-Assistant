"""FastAPI dependencies for authentication and authorization.

When ``settings.AUTH_ENABLED`` is False, all dependencies short-circuit
and return a synthetic admin user — preserves the pre-auth behavior so
existing tests and dev workflows keep working unmodified.
"""
from typing import Optional

from fastapi import Cookie, Depends, Header, HTTPException, Request, status

from app.core.auth import Session, SessionStore, User
from app.core.config import settings


_LEGACY_USER = User(id="legacy", email="legacy@local", role="admin")
_session_store: Optional[SessionStore] = None


def set_session_store(store: SessionStore) -> None:
    """Wire the singleton store at app startup."""
    global _session_store
    _session_store = store


def get_session_store() -> SessionStore:
    if _session_store is None:
        raise RuntimeError(
            "SessionStore not initialized — call set_session_store() at startup",
        )
    return _session_store


def _unauthenticated() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error": "unauthenticated"},
    )


def _session_expired() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error": "session_expired"},
    )


def _csrf_mismatch() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"error": "csrf_mismatch"},
    )


def _forbidden() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"error": "forbidden"},
    )


async def _resolve_session(request: Request) -> Optional[Session]:
    """Look up the current session by cookie. Returns None if absent.

    Stashes the resolved Session on request.state so multiple deps in
    one request only do one Redis round-trip.
    """
    cached = getattr(request.state, "_auth_session", None)
    if cached is not None:
        return cached
    sid = request.cookies.get(settings.AUTH_COOKIE_NAME)
    if not sid:
        request.state._auth_session = None
        return None
    session = await get_session_store().read(sid)
    request.state._auth_session = session
    return session


async def current_user(request: Request) -> User:
    """Resolve the signed-in user. Raises 401 if absent or expired."""
    if not settings.AUTH_ENABLED:
        return _LEGACY_USER
    sid = request.cookies.get(settings.AUTH_COOKIE_NAME)
    if not sid:
        raise _unauthenticated()
    session = await _resolve_session(request)
    if session is None:
        raise _session_expired()
    return session.user


async def csrf_check(
    request: Request,
    x_csrf_token: Optional[str] = Header(default=None, alias="X-CSRF-Token"),
) -> None:
    """Verify the CSRF token header matches the session's csrf value.

    Only meaningful for state-changing requests (POST/PUT/PATCH/DELETE).
    Must be combined with ``current_user`` — order doesn't matter, both
    share request.state cache.
    """
    if not settings.AUTH_ENABLED:
        return
    session = await _resolve_session(request)
    if session is None:
        raise _session_expired()
    if not x_csrf_token or x_csrf_token != session.csrf:
        raise _csrf_mismatch()


async def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise _forbidden()
    return user
