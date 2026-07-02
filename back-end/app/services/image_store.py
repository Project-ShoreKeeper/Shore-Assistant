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
from io import BytesIO
from pathlib import Path
from typing import Optional

import asyncpg
from PIL import Image

from app.core.config import settings


def _compress_to_jpeg(raw: bytes) -> tuple[bytes, int, int]:
    """Re-encode any input format as JPEG, downscaled to at most
    IMAGE_ATTACHMENT_MAX_DIMENSION on the longest edge. Runs on a worker
    thread (Pillow is sync/CPU-bound). Flattens transparency onto white
    since JPEG has no alpha channel."""
    img = Image.open(BytesIO(raw))
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        img = img.convert("RGBA")
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[-1])
        img = background
    else:
        img = img.convert("RGB")

    max_dim = settings.IMAGE_ATTACHMENT_MAX_DIMENSION
    if max(img.size) > max_dim:
        img.thumbnail((max_dim, max_dim), Image.LANCZOS)

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=settings.IMAGE_ATTACHMENT_JPEG_QUALITY, optimize=True)
    return buf.getvalue(), img.width, img.height


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
        _header, b64data = img["data_url"].split(",", 1)
        raw = base64.b64decode(b64data)
        compressed, width, height = await asyncio.to_thread(_compress_to_jpeg, raw)

        image_id = uuid.uuid4()
        path = base_dir / f"{image_id}.jpg"
        await asyncio.to_thread(path.write_bytes, compressed)
        rel_path = f"{base_dir.name}/{image_id}.jpg"

        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO image_attachments
                    (id, user_id, role, rel_path, mime_type, width, height,
                     byte_size, source_turn_ts)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                image_id, user_id, role, rel_path, "image/jpeg",
                width, height, len(compressed), now,
            )

        return {
            "id": str(image_id),
            "url": f"/api/images/{image_id}",
            "width": width,
            "height": height,
            "size_kb": round(len(compressed) / 1024, 1),
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
