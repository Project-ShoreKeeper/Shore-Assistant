import pytest

# Configure pytest-asyncio to auto mode so async test functions don't need @pytest.mark.asyncio
pytest_plugins = ["pytest_asyncio"]
