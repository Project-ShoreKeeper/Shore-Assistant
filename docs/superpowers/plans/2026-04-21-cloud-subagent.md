# Cloud Sub-Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Claude, Gemini, and OpenAI as callable sub-agent tools that Gemma4:e4b can delegate hard tasks to, with full conversation history passed as context.

**Architecture:** Gemma4 acts as orchestrator and calls `ask_claude`, `ask_gemini`, or `ask_openai` tools when it decides a task is too complex. A shared `CloudLLMService` handles all API calls, receives the current conversation history via a Python `ContextVar` set in `agent_service.py` before the tool loop, and trims history to `CLOUD_HISTORY_MAX_TURNS` before sending.

**Tech Stack:** Python `anthropic` SDK (AsyncAnthropic + prompt caching), `google-genai` SDK, `openai` SDK (AsyncOpenAI), `langchain_core.tools @tool`, `contextvars.ContextVar`, `pytest` + `pytest-asyncio` + `unittest.mock`

---

## File Map

| Action | Path | Responsibility |
|--------|------|---------------|
| Create | `back-end/app/services/cloud_llm_service.py` | CloudLLMService: history packing, API calls to Claude/Gemini/OpenAI, ContextVar definition |
| Create | `back-end/app/tools/cloud_tools.py` | `ask_claude`, `ask_gemini`, `ask_openai` LangChain tools |
| Create | `back-end/tests/conftest.py` | pytest configuration (asyncio mode) |
| Create | `back-end/tests/test_cloud_llm_service.py` | Unit tests for CloudLLMService |
| Create | `back-end/tests/test_cloud_tools.py` | Unit tests for cloud tools |
| Modify | `back-end/requirements.txt` | Add anthropic, google-genai, openai, pytest, pytest-asyncio |
| Modify | `back-end/app/core/config.py` | Add ANTHROPIC_API_KEY, GEMINI_API_KEY, OPENAI_API_KEY, CLOUD_MAX_TOKENS, CLOUD_HISTORY_MAX_TURNS |
| Modify | `back-end/app/tools/__init__.py` | Register ask_claude, ask_gemini, ask_openai |
| Modify | `back-end/app/services/agent_service.py` | Set current_history_var before tool execution loop |
| Modify | `back-end/app/prompts/kuudere.txt` | Append escalation instruction |
| Modify | `back-end/app/prompts/base.txt` | Append escalation instruction |

---

## Task 1: Dependencies and Config

**Files:**
- Modify: `back-end/requirements.txt`
- Modify: `back-end/app/core/config.py`

- [ ] **Step 1: Add SDK dependencies to requirements.txt**

Open `back-end/requirements.txt` and append after the existing entries:

```
# Cloud AI sub-agents
anthropic>=0.40.0
google-genai>=1.0.0
openai>=1.0.0

# Testing
pytest>=8.0.0
pytest-asyncio>=0.24.0
```

- [ ] **Step 2: Install the new packages**

```bash
cd back-end
pip install anthropic>=0.40.0 "google-genai>=1.0.0" "openai>=1.0.0" pytest pytest-asyncio
```

Expected: all packages install without errors.

- [ ] **Step 3: Add config fields to `back-end/app/core/config.py`**

Add these fields inside the `Settings` class, after the `N8N_*` block:

```python
    # Cloud AI sub-agents
    ANTHROPIC_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    CLOUD_MAX_TOKENS: int = 4096
    CLOUD_HISTORY_MAX_TURNS: int = 10
```

- [ ] **Step 4: Add API keys to `.env` file**

In `back-end/.env` (create if it doesn't exist), add:

```
ANTHROPIC_API_KEY=your_anthropic_key_here
GEMINI_API_KEY=your_gemini_key_here
OPENAI_API_KEY=your_openai_key_here
```

- [ ] **Step 5: Commit**

```bash
git add back-end/requirements.txt back-end/app/core/config.py
git commit -m "feat: add cloud sub-agent config and dependencies"
```

---

## Task 2: Test Infrastructure

**Files:**
- Create: `back-end/tests/conftest.py`

- [ ] **Step 1: Create `back-end/tests/conftest.py`**

```python
import pytest

# Configure pytest-asyncio to auto mode so async test functions don't need @pytest.mark.asyncio
pytest_plugins = ["pytest_asyncio"]
```

- [ ] **Step 2: Create `back-end/pytest.ini`**

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
```

- [ ] **Step 3: Verify pytest runs**

```bash
cd back-end
pytest --collect-only
```

Expected output contains something like: `collected 0 items` (no tests yet, no errors).

- [ ] **Step 4: Commit**

```bash
git add back-end/tests/conftest.py back-end/pytest.ini
git commit -m "test: add pytest configuration"
```

---

## Task 3: CloudLLMService Skeleton

**Files:**
- Create: `back-end/app/services/cloud_llm_service.py`
- Create: `back-end/tests/test_cloud_llm_service.py`

- [ ] **Step 1: Write failing tests for history utilities**

Create `back-end/tests/test_cloud_llm_service.py`:

```python
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
    # Should return empty list when no value set
    token = current_history_var.set([])
    result = current_history_var.get([])
    assert result == []
    current_history_var.reset(token)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd back-end
pytest tests/test_cloud_llm_service.py -v
```

Expected: `ImportError` or `ModuleNotFoundError` — `cloud_llm_service` doesn't exist yet.

- [ ] **Step 3: Create `back-end/app/services/cloud_llm_service.py` with skeleton**

```python
"""
Cloud LLM sub-agent service.
Provides call_claude, call_gemini, call_openai methods.
History is passed via current_history_var ContextVar set by agent_service.
"""

from contextvars import ContextVar
from typing import Optional

from app.core.config import settings

# Set by agent_service before each tool execution loop; read by cloud tools
current_history_var: ContextVar[list[dict]] = ContextVar("current_history", default=[])

ESCALATION_SYSTEM_PROMPT = (
    "You are a powerful AI sub-agent assisting Shore, a personal AI assistant. "
    "Shore's orchestrator has delegated a task to you because it requires deep reasoning or advanced capability. "
    "Be precise, thorough, and respond in plain text. Do not introduce yourself or explain that you are an AI."
)


class CloudLLMService:
    def _trim_history(self, history: list[dict], max_turns: int) -> list[dict]:
        """Return the last max_turns turns (each turn = 1 user + 1 assistant message)."""
        if max_turns <= 0:
            return []
        max_messages = max_turns * 2
        return history[-max_messages:] if len(history) > max_messages else list(history)

    async def call_claude(self, question: str, history: list[dict]) -> str:
        raise NotImplementedError

    async def call_gemini(self, question: str, history: list[dict]) -> str:
        raise NotImplementedError

    async def call_openai(self, question: str, history: list[dict]) -> str:
        raise NotImplementedError


cloud_llm_service = CloudLLMService()
```

- [ ] **Step 4: Run tests to verify skeleton passes**

```bash
cd back-end
pytest tests/test_cloud_llm_service.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add back-end/app/services/cloud_llm_service.py back-end/tests/test_cloud_llm_service.py
git commit -m "feat: add CloudLLMService skeleton with history utilities"
```

---

## Task 4: Claude Integration

**Files:**
- Modify: `back-end/app/services/cloud_llm_service.py`
- Modify: `back-end/tests/test_cloud_llm_service.py`

- [ ] **Step 1: Add failing test for call_claude**

Append to `back-end/tests/test_cloud_llm_service.py`:

```python
async def test_call_claude_returns_text():
    service = CloudLLMService()

    mock_message = MagicMock()
    mock_message.content = [MagicMock(text="Claude answer")]

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=mock_message)

    with patch("app.services.cloud_llm_service.AsyncAnthropic", return_value=mock_client):
        result = await service.call_claude("explain recursion", SAMPLE_HISTORY)

    assert result == "Claude answer"


async def test_call_claude_returns_error_on_exception():
    service = CloudLLMService()

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(side_effect=Exception("rate limited"))

    with patch("app.services.cloud_llm_service.AsyncAnthropic", return_value=mock_client):
        result = await service.call_claude("explain recursion", [])

    assert result.startswith("Error calling Claude:")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd back-end
pytest tests/test_cloud_llm_service.py::test_call_claude_returns_text tests/test_cloud_llm_service.py::test_call_claude_returns_error_on_exception -v
```

Expected: FAIL — `AsyncAnthropic` not imported.

- [ ] **Step 3: Implement `call_claude` in `cloud_llm_service.py`**

Add the import at the top of the file:

```python
import anthropic
from anthropic import AsyncAnthropic
```

Replace the `call_claude` method:

```python
    async def call_claude(self, question: str, history: list[dict]) -> str:
        """Call Claude with conversation history as context. Uses prompt caching on system prompt."""
        if not settings.ANTHROPIC_API_KEY:
            return "Error calling Claude: ANTHROPIC_API_KEY is not set."
        try:
            trimmed = self._trim_history(history, settings.CLOUD_HISTORY_MAX_TURNS)

            # Convert Shore history to Anthropic format (user/assistant only)
            messages = []
            for m in trimmed:
                role = m.get("role", "user")
                if role not in ("user", "assistant"):
                    continue
                messages.append({"role": role, "content": m["content"]})

            # Append the current question as final user turn
            messages.append({"role": "user", "content": question})

            client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
            response = await client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=settings.CLOUD_MAX_TOKENS,
                system=[
                    {
                        "type": "text",
                        "text": ESCALATION_SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=messages,
            )
            return response.content[0].text
        except Exception as e:
            return f"Error calling Claude: {e}"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd back-end
pytest tests/test_cloud_llm_service.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add back-end/app/services/cloud_llm_service.py back-end/tests/test_cloud_llm_service.py
git commit -m "feat: implement call_claude with prompt caching and history context"
```

---

## Task 5: Gemini Integration

**Files:**
- Modify: `back-end/app/services/cloud_llm_service.py`
- Modify: `back-end/tests/test_cloud_llm_service.py`

- [ ] **Step 1: Add failing test for call_gemini**

Append to `back-end/tests/test_cloud_llm_service.py`:

```python
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

    with patch("app.services.cloud_llm_service.genai.Client", return_value=mock_client):
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd back-end
pytest tests/test_cloud_llm_service.py::test_call_gemini_returns_text tests/test_cloud_llm_service.py::test_call_gemini_returns_error_on_exception -v
```

Expected: FAIL — `genai` not imported.

- [ ] **Step 3: Implement `call_gemini` in `cloud_llm_service.py`**

Add import at the top:

```python
from google import genai
from google.genai import types as genai_types
```

Replace the `call_gemini` method:

```python
    async def call_gemini(self, question: str, history: list[dict]) -> str:
        """Call Gemini with conversation history as context."""
        if not settings.GEMINI_API_KEY:
            return "Error calling Gemini: GEMINI_API_KEY is not set."
        try:
            trimmed = self._trim_history(history, settings.CLOUD_HISTORY_MAX_TURNS)

            # Convert Shore history to Gemini contents format
            # Gemini uses "model" for assistant role
            contents = []
            for m in trimmed:
                role = m.get("role", "user")
                if role not in ("user", "assistant"):
                    continue
                gemini_role = "model" if role == "assistant" else "user"
                contents.append(
                    genai_types.Content(
                        role=gemini_role,
                        parts=[genai_types.Part(text=m["content"])],
                    )
                )

            # Append the current question
            contents.append(
                genai_types.Content(
                    role="user",
                    parts=[genai_types.Part(text=question)],
                )
            )

            client = genai.Client(api_key=settings.GEMINI_API_KEY)
            response = await client.aio.models.generate_content(
                model="gemini-2.0-flash",
                contents=contents,
                config=genai_types.GenerateContentConfig(
                    system_instruction=ESCALATION_SYSTEM_PROMPT,
                    max_output_tokens=settings.CLOUD_MAX_TOKENS,
                ),
            )
            return response.text
        except Exception as e:
            return f"Error calling Gemini: {e}"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd back-end
pytest tests/test_cloud_llm_service.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add back-end/app/services/cloud_llm_service.py back-end/tests/test_cloud_llm_service.py
git commit -m "feat: implement call_gemini with history context"
```

---

## Task 6: OpenAI Integration

**Files:**
- Modify: `back-end/app/services/cloud_llm_service.py`
- Modify: `back-end/tests/test_cloud_llm_service.py`

- [ ] **Step 1: Add failing test for call_openai**

Append to `back-end/tests/test_cloud_llm_service.py`:

```python
async def test_call_openai_returns_text():
    service = CloudLLMService()

    mock_choice = MagicMock()
    mock_choice.message.content = "OpenAI answer"

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    mock_completions = MagicMock()
    mock_completions.create = AsyncMock(return_value=mock_response)

    mock_chat = MagicMock()
    mock_chat.completions = mock_completions

    mock_client = MagicMock()
    mock_client.chat = mock_chat

    with patch("app.services.cloud_llm_service.AsyncOpenAI", return_value=mock_client):
        result = await service.call_openai("write a sorting algorithm", SAMPLE_HISTORY)

    assert result == "OpenAI answer"


async def test_call_openai_returns_error_on_exception():
    service = CloudLLMService()

    mock_completions = MagicMock()
    mock_completions.create = AsyncMock(side_effect=Exception("invalid key"))

    mock_chat = MagicMock()
    mock_chat.completions = mock_completions

    mock_client = MagicMock()
    mock_client.chat = mock_chat

    with patch("app.services.cloud_llm_service.AsyncOpenAI", return_value=mock_client):
        result = await service.call_openai("write a sorting algorithm", [])

    assert result.startswith("Error calling OpenAI:")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd back-end
pytest tests/test_cloud_llm_service.py::test_call_openai_returns_text tests/test_cloud_llm_service.py::test_call_openai_returns_error_on_exception -v
```

Expected: FAIL — `AsyncOpenAI` not imported.

- [ ] **Step 3: Implement `call_openai` in `cloud_llm_service.py`**

Add import at the top:

```python
from openai import AsyncOpenAI
```

Replace the `call_openai` method:

```python
    async def call_openai(self, question: str, history: list[dict]) -> str:
        """Call GPT-4o with conversation history as context."""
        if not settings.OPENAI_API_KEY:
            return "Error calling OpenAI: OPENAI_API_KEY is not set."
        try:
            trimmed = self._trim_history(history, settings.CLOUD_HISTORY_MAX_TURNS)

            messages = [{"role": "system", "content": ESCALATION_SYSTEM_PROMPT}]
            for m in trimmed:
                role = m.get("role", "user")
                if role not in ("user", "assistant"):
                    continue
                messages.append({"role": role, "content": m["content"]})
            messages.append({"role": "user", "content": question})

            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            response = await client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                max_tokens=settings.CLOUD_MAX_TOKENS,
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"Error calling OpenAI: {e}"
```

- [ ] **Step 4: Run all tests**

```bash
cd back-end
pytest tests/test_cloud_llm_service.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add back-end/app/services/cloud_llm_service.py back-end/tests/test_cloud_llm_service.py
git commit -m "feat: implement call_openai with history context"
```

---

## Task 7: Cloud Tools

**Files:**
- Create: `back-end/app/tools/cloud_tools.py`
- Create: `back-end/tests/test_cloud_tools.py`

- [ ] **Step 1: Write failing tests for cloud tools**

Create `back-end/tests/test_cloud_tools.py`:

```python
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
    # Ensure the tool works even with no history set
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd back-end
pytest tests/test_cloud_tools.py -v
```

Expected: FAIL — `app.tools.cloud_tools` doesn't exist yet.

- [ ] **Step 3: Create `back-end/app/tools/cloud_tools.py`**

```python
"""Cloud AI sub-agent tools for Gemma4 to delegate hard tasks."""

from langchain_core.tools import tool

from app.services.cloud_llm_service import cloud_llm_service, current_history_var


@tool
async def ask_claude(question: str) -> str:
    """Delegate a complex or difficult question to Claude (Anthropic).
    Use when the task requires deep reasoning, advanced coding, nuanced writing,
    detailed analysis, or when you are uncertain about your answer."""
    history = current_history_var.get([])
    return await cloud_llm_service.call_claude(question, history)


@tool
async def ask_gemini(question: str) -> str:
    """Delegate to Gemini (Google). Best for large document analysis,
    long-context summarization tasks, or when Claude is unavailable."""
    history = current_history_var.get([])
    return await cloud_llm_service.call_gemini(question, history)


@tool
async def ask_openai(question: str) -> str:
    """Delegate to GPT-4o (OpenAI). Use as a fallback when other cloud
    models are unavailable or rate-limited."""
    history = current_history_var.get([])
    return await cloud_llm_service.call_openai(question, history)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd back-end
pytest tests/test_cloud_tools.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add back-end/app/tools/cloud_tools.py back-end/tests/test_cloud_tools.py
git commit -m "feat: add ask_claude, ask_gemini, ask_openai tool wrappers"
```

---

## Task 8: Register Tools + Set ContextVar in Agent

**Files:**
- Modify: `back-end/app/tools/__init__.py`
- Modify: `back-end/app/services/agent_service.py`

- [ ] **Step 1: Register cloud tools in `back-end/app/tools/__init__.py`**

Add the import after the existing imports:

```python
from app.tools.cloud_tools import ask_claude, ask_gemini, ask_openai
```

Add the three tools to `ALL_TOOLS`:

```python
ALL_TOOLS = [
    get_system_time,
    read_file,
    list_directory,
    clear_memory,
    search_web,
    web_scrape,
    capture_screen,
    analyze_screen,
    set_reminder,
    set_scheduled_task,
    cancel_task,
    list_tasks,
    n8n_search_nodes,
    n8n_get_node_schema,
    n8n_search_workflow_templates,
    n8n_create_workflow,
    n8n_build_complex_workflow,
    n8n_manage_workflows,
    ask_claude,
    ask_gemini,
    ask_openai,
]
```

- [ ] **Step 2: Set `current_history_var` in `agent_service.py`**

At the top of `back-end/app/services/agent_service.py`, add the import:

```python
from app.services.cloud_llm_service import current_history_var
```

In the `run` method, add the ContextVar assignment immediately after the `messages` list is built (after line `messages = [m for m in conversation_history if m["content"].strip()]`):

```python
        messages = [m for m in conversation_history if m["content"].strip()]
        # Make conversation history available to cloud sub-agent tools
        current_history_var.set(conversation_history)
```

- [ ] **Step 3: Verify imports work by starting the server**

```bash
cd back-end
python -m uvicorn app.main:app --port 8000
```

Expected: server starts without `ImportError`. Ctrl+C to stop.

- [ ] **Step 4: Commit**

```bash
git add back-end/app/tools/__init__.py back-end/app/services/agent_service.py
git commit -m "feat: register cloud tools and wire ContextVar in agent loop"
```

---

## Task 9: Escalation Prompt

**Files:**
- Modify: `back-end/app/prompts/kuudere.txt`
- Modify: `back-end/app/prompts/base.txt`

- [ ] **Step 1: Append escalation instruction to `kuudere.txt`**

Add the following block at the end of `back-end/app/prompts/kuudere.txt`:

```
CLOUD SUB-AGENTS:
You have access to ask_claude, ask_gemini, and ask_openai tools.
Use ask_claude when:
- The task requires deep logical reasoning or complex multi-step thinking
- The user asks for advanced code (algorithms, architecture, debugging hard problems)
- You are not confident in your answer
- The task needs nuanced or detailed writing beyond a few sentences
Pass the user's full question to the tool unchanged. Present the returned answer naturally in your own voice. You do not need to mention that you delegated.
ask_gemini is best for large document analysis or long-context tasks.
ask_openai is a fallback if the others are unavailable.
```

- [ ] **Step 2: Append same instruction to `base.txt`**

Open `back-end/app/prompts/base.txt` and append the identical block from Step 1.

- [ ] **Step 3: Restart server and verify prompt loads**

```bash
cd back-end
python -m uvicorn app.main:app --port 8000
```

Expected: server starts, no errors. Check the log doesn't show any prompt loading errors. Ctrl+C to stop.

- [ ] **Step 4: Commit**

```bash
git add back-end/app/prompts/kuudere.txt back-end/app/prompts/base.txt
git commit -m "feat: add cloud sub-agent escalation instructions to persona prompts"
```

---

## Task 10: Run All Tests and Smoke Test

**Files:** None modified

- [ ] **Step 1: Run the full test suite**

```bash
cd back-end
pytest tests/test_cloud_llm_service.py tests/test_cloud_tools.py -v
```

Expected: all tests PASS, 0 failures.

- [ ] **Step 2: Start the server for live testing**

```bash
cd back-end
python -m uvicorn app.main:app --reload --port 8000
```

- [ ] **Step 3: Open the frontend and test escalation**

Open `http://localhost:5173` in a browser and navigate to the Chat page. Send a message that should trigger escalation:

> "Write me a recursive descent parser for arithmetic expressions in Python, with full error handling and an AST."

Expected behavior:
- In the UI's tool action cards, you should see a `ask_claude` tool call appear
- The tool card shows the question sent to Claude
- Shore presents Claude's answer in its own voice

- [ ] **Step 4: Test missing API key graceful failure**

In `.env`, temporarily blank out `ANTHROPIC_API_KEY=`. Restart server. Send a hard question.

Expected: Shore responds with something like "...Claude is unavailable right now." (Gemma4 presenting the error string from the tool result gracefully). Restore the key.

- [ ] **Step 5: Final commit**

```bash
git add .
git commit -m "feat: cloud AI sub-agents — Claude/Gemini/OpenAI callable by Gemma4"
```
