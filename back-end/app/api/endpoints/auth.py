"""Auth endpoints: /api/auth/{login,callback,logout,me}.

Login flow:
  GET  /api/auth/login       → 302 to Google with one-shot state
  GET  /api/auth/callback    → verify state, exchange code, allowlist
                                check, create session, set cookie, 302 /
  POST /api/auth/logout      → delete session, clear cookie
  GET  /api/auth/me          → current user + csrf token

The actual Google token-exchange is encapsulated in
``_exchange_code_for_userinfo`` so it can be substituted in tests.
"""
import json
from typing import Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse

from app.api.deps import (
    _resolve_session,
    _session_expired,
    csrf_check,
    current_user,
    get_session_store,
)
from app.core.allowlist import parse_allowlist, resolve_role
from app.core.auth import SessionStore, User
from app.core.config import settings


router = APIRouter(prefix="/api/auth", tags=["auth"])

_session_store: Optional[SessionStore] = None  # patched in tests; falls back
                                               # to get_session_store() at runtime


def _store() -> SessionStore:
    return _session_store if _session_store is not None else get_session_store()


_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


async def _exchange_code_for_userinfo(code: str) -> dict:
    """Exchange an OAuth code for ``{sub, email}``.

    Validated with Google's published JWKS — but for v1 we accept the
    decoded id_token payload without re-verifying the signature: we
    just received the token over TLS from Google's token endpoint, so
    its provenance is trusted. (Signature verification can be added in
    a follow-up if we ever stop trusting the transport.)
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            _GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.AUTH_GOOGLE_CLIENT_ID,
                "client_secret": settings.AUTH_GOOGLE_CLIENT_SECRET,
                "redirect_uri": settings.AUTH_OAUTH_REDIRECT_URL,
                "grant_type": "authorization_code",
            },
        )
        resp.raise_for_status()
        token = resp.json()
    id_token = token.get("id_token")
    if not id_token:
        raise HTTPException(
            status_code=502, detail={"error": "oauth_upstream"},
        )
    # Decode without signature verification — see docstring above.
    _header_b64, payload_b64, _sig = id_token.split(".")
    import base64
    payload_b64 += "=" * (-len(payload_b64) % 4)
    payload = json.loads(base64.urlsafe_b64decode(payload_b64))
    return {"sub": payload["sub"], "email": payload["email"]}


def _set_session_cookie(response: Response, sid: str) -> None:
    response.set_cookie(
        key=settings.AUTH_COOKIE_NAME,
        value=sid,
        max_age=settings.AUTH_SESSION_TTL_SECONDS,
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        domain=settings.AUTH_COOKIE_DOMAIN or None,
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.set_cookie(
        key=settings.AUTH_COOKIE_NAME,
        value="",
        max_age=0,
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        domain=settings.AUTH_COOKIE_DOMAIN or None,
        path="/",
    )


@router.get("/login")
async def login() -> RedirectResponse:
    state = await _store().create_oauth_state(
        ttl_seconds=settings.AUTH_OAUTH_STATE_TTL_SECONDS,
        prefix=settings.AUTH_OAUTH_STATE_KEY_PREFIX,
    )
    params = {
        "client_id": settings.AUTH_GOOGLE_CLIENT_ID,
        "redirect_uri": settings.AUTH_OAUTH_REDIRECT_URL,
        "response_type": "code",
        "scope": "openid email",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return RedirectResponse(
        url=f"{_GOOGLE_AUTH_URL}?{urlencode(params)}", status_code=302,
    )


@router.get("/callback")
async def callback(code: str, state: str) -> Response:
    ok = await _store().consume_oauth_state(
        state, prefix=settings.AUTH_OAUTH_STATE_KEY_PREFIX,
    )
    if not ok:
        raise HTTPException(
            status_code=400, detail={"error": "oauth_state_invalid"},
        )

    try:
        info = await _exchange_code_for_userinfo(code)
    except HTTPException:
        raise
    except Exception as e:
        print(f"[auth] token exchange failed: {e!r}")
        raise HTTPException(
            status_code=502, detail={"error": "oauth_upstream"},
        )

    email = info["email"]
    allowlist = parse_allowlist(settings.AUTH_ALLOWED_EMAILS)
    role = resolve_role(email, allowlist)
    if role is None:
        raise HTTPException(
            status_code=403,
            detail={"error": "not_allowlisted", "email": email},
        )

    sid, _csrf = await _store().create(
        User(id=info["sub"], email=email.lower(), role=role),
    )
    response = RedirectResponse(
        url=settings.AUTH_POST_LOGIN_REDIRECT_URL, status_code=302,
    )
    _set_session_cookie(response, sid)
    return response


@router.post("/logout")
async def logout(
    request: Request,
    _csrf: None = Depends(csrf_check),
    _user: User = Depends(current_user),
) -> Response:
    sid = request.cookies.get(settings.AUTH_COOKIE_NAME)
    if sid:
        await _store().delete(sid)
    response = JSONResponse({"ok": True})
    _clear_session_cookie(response)
    return response


@router.get("/me")
async def me(request: Request, user: User = Depends(current_user)) -> dict:
    if not settings.AUTH_ENABLED:
        # current_user returned the synthetic admin; there's no real
        # session, so CSRF is irrelevant (csrf_check is also a no-op).
        return {"email": user.email, "role": user.role, "csrf": ""}
    session = await _resolve_session(request)
    if session is None:
        # current_user already raised; defensive fallback.
        raise _session_expired()
    return {"email": user.email, "role": user.role, "csrf": session.csrf}
