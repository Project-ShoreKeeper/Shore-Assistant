"""Local disk + Postgres store for raw chat image attachments.

Distinct from the semantic memory layers (short-term/profile/episodic):
this exists purely so a user can view an image they sent again later.
The agent and LOCOMO worker never read this store — they only ever see
the text placeholder built by `_build_memory_message` in chat_ws.py.
"""
import asyncio
import base64
import time
import uuid
from pathlib import Path
from typing import Optional

import asyncpg

from app.core.config import settings

_MIME_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}


class ImageAttachmentStore:
    def __init__(self):
        self._pool: Optional[asyncpg.Pool] = None

    def startup(self, pool: Optional[asyncpg.Pool]) -> None:
        self._pool = pool

    def _base_dir(self, user_id: str) -> Path:
        return Path(settings.IMAGE_STORAGE_DIR) / user_id

    async def save_attachments(
        self, images: list[dict], user_id: str, role: str,
    ) -> list[dict]:
        """Decode + persist each image; skip (log) any that fail rather
        than breaking the chat turn. Returns only the ones that saved,
        as wire-ready dicts: {id, url, width, height, size_kb}."""
        if self._pool is None or not images:
            return []
        base_dir = self._base_dir(user_id)
        await asyncio.to_thread(base_dir.mkdir, parents=True, exist_ok=True)
        now = time.time()
        saved: list[dict] = []
        for img in images:
            try:
                saved.append(await self._save_one(img, user_id, role, base_dir, now))
            except Exception as e:
                print(f"[ImageStore] save_attachments skipped one image: {e!r}")
        return saved

    async def _save_one(
        self, img: dict, user_id: str, role: str, base_dir: Path, now: float,
    ) -> dict:
        header, b64data = img["data_url"].split(",", 1)
        mime = header.split(";")[0].split(":", 1)[1]
        ext = _MIME_EXT.get(mime, "bin")
        raw = base64.b64decode(b64data)
        image_id = uuid.uuid4()
        path = base_dir / f"{image_id}.{ext}"
        await asyncio.to_thread(path.write_bytes, raw)
        rel_path = f"{base_dir.name}/{image_id}.{ext}"

        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO image_attachments
                    (id, user_id, role, rel_path, mime_type, width, height,
                     byte_size, source_turn_ts)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                image_id, user_id, role, rel_path, mime,
                img.get("width"), img.get("height"), len(raw), now,
            )

        return {
            "id": str(image_id),
            "url": f"/api/images/{image_id}",
            "width": img.get("width"),
            "height": img.get("height"),
            "size_kb": round(len(raw) / 1024, 1),
        }

    async def get(self, image_id: str) -> Optional[dict]:
        """Metadata + absolute path for serving. None if missing/bad id/
        file no longer on disk."""
        if self._pool is None:
            return None
        try:
            point_id = uuid.UUID(image_id)
        except ValueError:
            return None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT rel_path, mime_type FROM image_attachments WHERE id = $1",
                point_id,
            )
        if row is None:
            return None
        path = Path(settings.IMAGE_STORAGE_DIR) / row["rel_path"]
        if not path.is_file():
            return None
        return {"path": path, "mime_type": row["mime_type"]}


image_store = ImageAttachmentStore()
