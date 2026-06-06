"""Chronicles endpoint — serves hand-written changelog markdown files.

Markdown files live in `<repo-root>/docs/chronicles/` with YAML frontmatter:

    ---
    version: 0.1.0
    title: Initial Publish
    date: 2026-06-05
    summary: One-line description shown in the sidebar.
    ---

    ## Frontend
    - ...

The slug for each entry is the filename without `.md` (e.g. `v0.1.0.md`
becomes slug `v0.1.0`). Versions are sorted by `date` desc (newest first);
ties broken by `version` desc using packaging.version when available, else
lexical.
"""
from __future__ import annotations

import re
from datetime import date as date_cls
from pathlib import Path
from typing import Optional

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/chronicles", tags=["chronicles"])

# Repo root = back-end/../  (this file is back-end/app/api/endpoints/chronicles.py)
_REPO_ROOT = Path(__file__).resolve().parents[4]
_CHRONICLES_DIR = _REPO_ROOT / "docs" / "chronicles"

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


class ChronicleMeta(BaseModel):
    slug: str
    version: Optional[str] = None
    title: str
    date: Optional[str] = None
    summary: Optional[str] = None


class ChronicleEntry(ChronicleMeta):
    content: str


def _parse_file(path: Path) -> Optional[ChronicleEntry]:
    """Read one chronicle file. Returns None if it cannot be parsed."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None

    meta: dict = {}
    body = raw
    m = _FRONTMATTER_RE.match(raw)
    if m:
        try:
            parsed = yaml.safe_load(m.group(1)) or {}
            if isinstance(parsed, dict):
                meta = parsed
            body = m.group(2)
        except yaml.YAMLError:
            # Treat unparsable frontmatter as a regular body with no metadata.
            body = raw

    slug = path.stem
    title = str(meta.get("title") or slug)
    version = meta.get("version")
    if version is not None:
        version = str(version)
    raw_date = meta.get("date")
    if isinstance(raw_date, date_cls):
        date_str = raw_date.isoformat()
    elif raw_date is None:
        date_str = None
    else:
        date_str = str(raw_date)
    summary = meta.get("summary")
    if summary is not None:
        summary = str(summary)

    return ChronicleEntry(
        slug=slug,
        version=version,
        title=title,
        date=date_str,
        summary=summary,
        content=body,
    )


def _list_entries() -> list[ChronicleEntry]:
    if not _CHRONICLES_DIR.is_dir():
        return []
    entries: list[ChronicleEntry] = []
    for p in sorted(_CHRONICLES_DIR.glob("*.md")):
        entry = _parse_file(p)
        if entry is not None:
            entries.append(entry)
    # Sort newest first by date desc, then version desc (lexical).
    entries.sort(
        key=lambda e: (e.date or "", e.version or ""),
        reverse=True,
    )
    return entries


@router.get("")
async def list_chronicles() -> dict:
    """Sidebar payload — metadata only, no body."""
    entries = _list_entries()
    return {
        "entries": [ChronicleMeta(**e.model_dump(exclude={"content"})).model_dump() for e in entries],
    }


@router.get("/{slug}")
async def get_chronicle(slug: str) -> dict:
    # Defensive: reject anything with a path separator.
    if "/" in slug or "\\" in slug or ".." in slug:
        raise HTTPException(status_code=400, detail="invalid slug")

    path = _CHRONICLES_DIR / f"{slug}.md"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="chronicle not found")
    entry = _parse_file(path)
    if entry is None:
        raise HTTPException(status_code=500, detail="failed to parse chronicle")

    # Compute prev/next navigation in the sorted order (newest first).
    entries = _list_entries()
    slugs = [e.slug for e in entries]
    try:
        idx = slugs.index(slug)
    except ValueError:
        idx = -1
    prev_slug = slugs[idx + 1] if 0 <= idx < len(slugs) - 1 else None  # older
    next_slug = slugs[idx - 1] if idx > 0 else None  # newer

    return {
        **entry.model_dump(),
        "prev_slug": prev_slug,  # older
        "next_slug": next_slug,  # newer
    }
