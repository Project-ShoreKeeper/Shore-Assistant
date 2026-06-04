import pytest  # noqa: F401
import pytest_asyncio
from fakeredis import aioredis as fakeredis_aio

# Configure pytest-asyncio to auto mode so async test functions don't need @pytest.mark.asyncio
pytest_plugins = ["pytest_asyncio"]


@pytest_asyncio.fixture
async def fake_redis():
    """Async fakeredis instance with the same interface as redis.asyncio.Redis."""
    fake = fakeredis_aio.FakeRedis(decode_responses=True)
    yield fake
    await fake.flushdb()
    await fake.aclose()
