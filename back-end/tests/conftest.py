import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "asyncio: mark test as async")


# Enable pytest-asyncio auto mode so async def test_* functions run without decorators
import pytest_asyncio  # noqa: F401

# pytest-asyncio >= 0.21 uses asyncio_mode ini option; set it programmatically
def pytest_collection_modifyitems(items):
    for item in items:
        if item.get_closest_marker("asyncio") is None:
            import inspect
            if inspect.iscoroutinefunction(item.function):
                item.add_marker(pytest.mark.asyncio)
