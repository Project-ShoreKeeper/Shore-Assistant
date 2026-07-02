"""Unit tests for ImageAttachmentStore — asyncpg + disk both faked."""
import base64
import uuid
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image

from app.services.image_store import ImageAttachmentStore

def _png_data_url(size: tuple[int, int] = (1, 1)) -> str:
    buf = BytesIO()
    Image.new("RGB", size, color=(10, 20, 30)).save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _make_pool_with_conn(conn: AsyncMock) -> AsyncMock:
    acquire_ctx = AsyncMock()
    acquire_ctx.__aenter__.return_value = conn
    acquire_ctx.__aexit__.return_value = None
    pool = AsyncMock()
    pool.acquire = MagicMock(return_value=acquire_ctx)
    return pool


@pytest.fixture(autouse=True)
def _tmp_storage_dir(tmp_path, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "IMAGE_STORAGE_DIR", str(tmp_path))
    return tmp_path


async def test_save_attachments_returns_empty_when_not_started():
    store = ImageAttachmentStore()
    result = await store.save_attachments(
        [{"data_url": _png_data_url(), "width": 1, "height": 1}],
        user_id="u1", role="user",
    )
    assert result == []


async def test_save_attachments_writes_file_and_inserts_row(_tmp_storage_dir):
    conn = AsyncMock()
    pool = _make_pool_with_conn(conn)
    store = ImageAttachmentStore()
    store.startup(pool)

    result = await store.save_attachments(
        [{"data_url": _png_data_url(), "width": 1, "height": 1}],
        user_id="u1", role="user",
    )

    assert len(result) == 1
    saved = result[0]
    assert saved["url"] == f"/api/images/{saved['id']}"
    assert saved["width"] == 1 and saved["height"] == 1
    assert saved["size_kb"] > 0

    # File actually landed on disk under the user's subdirectory, re-encoded
    # as JPEG regardless of the original format.
    on_disk = list((_tmp_storage_dir / "u1").glob("*.jpg"))
    assert len(on_disk) == 1

    # DB insert happened with the matching id + the compressed mime type.
    insert_call = conn.execute.await_args
    assert insert_call.args[1] == uuid.UUID(saved["id"])
    assert insert_call.args[2] == "u1"
    assert insert_call.args[5] == "image/jpeg"


async def test_save_attachments_downscales_oversized_image(_tmp_storage_dir, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "IMAGE_ATTACHMENT_MAX_DIMENSION", 500)

    big = Image.new("RGB", (2000, 100), color=(200, 50, 50))
    buf = BytesIO()
    big.save(buf, format="PNG")
    data_url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

    conn = AsyncMock()
    pool = _make_pool_with_conn(conn)
    store = ImageAttachmentStore()
    store.startup(pool)

    result = await store.save_attachments(
        [{"data_url": data_url, "width": 2000, "height": 100}],
        user_id="u1", role="user",
    )

    assert len(result) == 1
    assert result[0]["width"] == 500  # downscaled from 2000, aspect preserved
    assert result[0]["height"] == 25


async def test_save_attachments_skips_malformed_image_without_raising(_tmp_storage_dir):
    conn = AsyncMock()
    pool = _make_pool_with_conn(conn)
    store = ImageAttachmentStore()
    store.startup(pool)

    result = await store.save_attachments(
        [{"data_url": "not-a-valid-data-url", "width": 1, "height": 1}],
        user_id="u1", role="user",
    )
    assert result == []
    conn.execute.assert_not_awaited()


async def test_get_returns_none_for_malformed_id():
    store = ImageAttachmentStore()
    store.startup(_make_pool_with_conn(AsyncMock()))
    assert await store.get("not-a-uuid") is None


async def test_get_returns_none_when_row_missing():
    conn = AsyncMock()
    conn.fetchrow.return_value = None
    store = ImageAttachmentStore()
    store.startup(_make_pool_with_conn(conn))
    assert await store.get(str(uuid.uuid4())) is None


async def test_get_returns_none_when_file_missing_on_disk(_tmp_storage_dir):
    conn = AsyncMock()
    conn.fetchrow.return_value = {"rel_path": "u1/missing.png", "mime_type": "image/png"}
    store = ImageAttachmentStore()
    store.startup(_make_pool_with_conn(conn))
    assert await store.get(str(uuid.uuid4())) is None


async def test_get_returns_path_and_mime_when_file_present(_tmp_storage_dir):
    (_tmp_storage_dir / "u1").mkdir()
    (_tmp_storage_dir / "u1" / "real.png").write_bytes(b"fake-png-bytes")

    conn = AsyncMock()
    conn.fetchrow.return_value = {"rel_path": "u1/real.png", "mime_type": "image/png"}
    store = ImageAttachmentStore()
    store.startup(_make_pool_with_conn(conn))

    record = await store.get(str(uuid.uuid4()))
    assert record is not None
    assert record["mime_type"] == "image/png"
    assert record["path"].name == "real.png"
