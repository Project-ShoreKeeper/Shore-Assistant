"""Parse AUTH_ALLOWED_EMAILS into an ordered list and resolve roles.

The first email in the list is granted the "admin" role. All others
are "user". Lookups are case-insensitive and tolerant of whitespace.
"""
from typing import Optional

from app.core.auth import Role


def parse_allowlist(raw: str) -> list[str]:
    """Parse 'a@x.com, b@y.com ,, c@z.com' → ['a@x.com','b@y.com','c@z.com'].

    Order preserved (first entry becomes admin). Lowercased.
    Empty entries dropped.
    """
    out: list[str] = []
    for part in raw.split(","):
        e = part.strip().lower()
        if e:
            out.append(e)
    return out


def resolve_role(email: str, allowlist: list[str]) -> Optional[Role]:
    """Return 'admin' if email is the first entry, 'user' if it's later,
    None if not allowlisted."""
    e = email.strip().lower()
    if not allowlist or e not in allowlist:
        return None
    return "admin" if allowlist[0] == e else "user"
