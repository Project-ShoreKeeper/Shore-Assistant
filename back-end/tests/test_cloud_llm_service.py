import pytest
from contextvars import ContextVar
from unittest.mock import AsyncMock, patch, MagicMock

from app.services.cloud_llm_service import CloudLLMService, current_history_var


SAMPLE_HISTORY = [
    {"role": "user", "content": "Hello"},
    {"role": "assistant", "content": "...what do you want."},
    {"role": "user", "content": "Can you write code?"},
    {"role": "assistant", "content": "...yes."},
]


def test_trim_history_under_limit():
    service = CloudLLMService()
    result = service._trim_history(SAMPLE_HISTORY, max_turns=10)
    assert result == SAMPLE_HISTORY


def test_trim_history_over_limit():
    service = CloudLLMService()
    result = service._trim_history(SAMPLE_HISTORY, max_turns=1)
    # 1 turn = 2 messages (user + assistant)
    assert len(result) == 2
    assert result[0]["role"] == "user"
    assert result[0]["content"] == "Can you write code?"


def test_trim_history_zero():
    service = CloudLLMService()
    result = service._trim_history(SAMPLE_HISTORY, max_turns=0)
    assert result == []


def test_context_var_default():
    token = current_history_var.set([])
    result = current_history_var.get([])
    assert result == []
    current_history_var.reset(token)


async def test_call_claude_returns_text():
    service = CloudLLMService()

    mock_message = MagicMock()
    mock_message.content = [MagicMock(text="Claude answer")]

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=mock_message)

    with patch("app.services.cloud_llm_service.AsyncAnthropic", return_value=mock_client), \
         patch("app.services.cloud_llm_service.settings") as mock_settings:
        mock_settings.ANTHROPIC_API_KEY = "test-key"
        mock_settings.CLOUD_HISTORY_MAX_TURNS = 10
        mock_settings.CLOUD_MAX_TOKENS = 4096
        result = await service.call_claude("explain recursion", SAMPLE_HISTORY)

    assert result == "Claude answer"


async def test_call_claude_returns_error_on_exception():
    service = CloudLLMService()

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(side_effect=Exception("rate limited"))

    with patch("app.services.cloud_llm_service.AsyncAnthropic", return_value=mock_client):
        result = await service.call_claude("explain recursion", [])

    assert result.startswith("Error calling Claude:")


async def test_call_gemini_returns_text():
    service = CloudLLMService()

    mock_response = MagicMock()
    mock_response.text = "Gemini answer"

    mock_models = MagicMock()
    mock_models.generate_content = AsyncMock(return_value=mock_response)

    mock_aio = MagicMock()
    mock_aio.models = mock_models

    mock_client = MagicMock()
    mock_client.aio = mock_aio

    with patch("app.services.cloud_llm_service.genai.Client", return_value=mock_client), \
         patch("app.services.cloud_llm_service.settings") as mock_settings:
        mock_settings.GEMINI_API_KEY = "test-gemini-key"
        mock_settings.CLOUD_HISTORY_MAX_TURNS = 10
        mock_settings.CLOUD_MAX_TOKENS = 4096
        result = await service.call_gemini("summarize this doc", SAMPLE_HISTORY)

    assert result == "Gemini answer"


async def test_call_gemini_returns_error_on_exception():
    service = CloudLLMService()

    mock_models = MagicMock()
    mock_models.generate_content = AsyncMock(side_effect=Exception("quota exceeded"))

    mock_aio = MagicMock()
    mock_aio.models = mock_models

    mock_client = MagicMock()
    mock_client.aio = mock_aio

    with patch("app.services.cloud_llm_service.genai.Client", return_value=mock_client):
        result = await service.call_gemini("summarize this doc", [])

    assert result.startswith("Error calling Gemini:")
