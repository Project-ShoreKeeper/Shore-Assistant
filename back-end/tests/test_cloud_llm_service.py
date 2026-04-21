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
