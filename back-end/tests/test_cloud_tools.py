import pytest
from unittest.mock import AsyncMock, patch

from app.services.cloud_llm_service import current_history_var


SAMPLE_HISTORY = [
    {"role": "user", "content": "Hello"},
    {"role": "assistant", "content": "...what."},
]


async def test_ask_claude_passes_history_and_question():
    token = current_history_var.set(SAMPLE_HISTORY)
    try:
        with patch(
            "app.tools.cloud_tools.cloud_llm_service.call_claude",
            new=AsyncMock(return_value="Claude says: yes"),
        ) as mock_call:
            from app.tools.cloud_tools import ask_claude
            result = await ask_claude.ainvoke({"question": "is recursion hard?"})

        mock_call.assert_called_once_with("is recursion hard?", SAMPLE_HISTORY)
        assert result == "Claude says: yes"
    finally:
        current_history_var.reset(token)


async def test_ask_gemini_passes_history_and_question():
    token = current_history_var.set(SAMPLE_HISTORY)
    try:
        with patch(
            "app.tools.cloud_tools.cloud_llm_service.call_gemini",
            new=AsyncMock(return_value="Gemini says: sure"),
        ) as mock_call:
            from app.tools.cloud_tools import ask_gemini
            result = await ask_gemini.ainvoke({"question": "summarize this"})

        mock_call.assert_called_once_with("summarize this", SAMPLE_HISTORY)
        assert result == "Gemini says: sure"
    finally:
        current_history_var.reset(token)


async def test_ask_openai_passes_history_and_question():
    token = current_history_var.set(SAMPLE_HISTORY)
    try:
        with patch(
            "app.tools.cloud_tools.cloud_llm_service.call_openai",
            new=AsyncMock(return_value="GPT says: here"),
        ) as mock_call:
            from app.tools.cloud_tools import ask_openai
            result = await ask_openai.ainvoke({"question": "write quicksort"})

        mock_call.assert_called_once_with("write quicksort", SAMPLE_HISTORY)
        assert result == "GPT says: here"
    finally:
        current_history_var.reset(token)


async def test_ask_claude_uses_empty_history_when_var_not_set():
    token = current_history_var.set([])
    try:
        with patch(
            "app.tools.cloud_tools.cloud_llm_service.call_claude",
            new=AsyncMock(return_value="ok"),
        ) as mock_call:
            from app.tools.cloud_tools import ask_claude
            await ask_claude.ainvoke({"question": "hello"})

        mock_call.assert_called_once_with("hello", [])
    finally:
        current_history_var.reset(token)
