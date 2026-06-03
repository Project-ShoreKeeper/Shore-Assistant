"""Unit tests for agent_service.AgentService changes around multimodal input."""
import sys
import types
from unittest.mock import MagicMock
import pytest


@pytest.fixture()
def agent_service_module():
    """
    Import agent_service with all heavy dependencies stubbed out.
    Cleans up injected stubs after the test so the real modules are never
    displaced from sys.modules when the tests run alongside test_llm_service.py.
    """
    stub_keys = [
        "app.services.llm_service",
        "app.services.tool_retriever",
        "app.services.cloud_llm_service",
        "app.tools",
    ]

    # Save anything that was already there (real or previous stub)
    saved = {k: sys.modules.get(k) for k in stub_keys}
    # Also save agent_service itself so we re-import fresh each test
    saved["app.services.agent_service"] = sys.modules.get("app.services.agent_service")

    # Install stubs
    llm_mod = types.ModuleType("app.services.llm_service")
    llm_mod.llm_service = MagicMock()
    llm_mod.build_system_prompt = lambda: "SYS"
    sys.modules["app.services.llm_service"] = llm_mod

    tr_mod = types.ModuleType("app.services.tool_retriever")
    tr_mod.tool_retriever = MagicMock()
    tr_mod.tool_retriever.retrieve = MagicMock(return_value=[])
    tr_mod.tool_retriever.get_tool_schemas = MagicMock(return_value=None)
    sys.modules["app.services.tool_retriever"] = tr_mod

    cloud_mod = types.ModuleType("app.services.cloud_llm_service")
    cloud_mod.current_history_var = MagicMock()
    sys.modules["app.services.cloud_llm_service"] = cloud_mod

    tools_mod = types.ModuleType("app.tools")
    tools_mod.TOOL_MAP = {}
    tools_mod.ALL_TOOLS = []
    sys.modules["app.tools"] = tools_mod

    # Force a fresh import of agent_service against the stubs
    sys.modules.pop("app.services.agent_service", None)
    import app.services.agent_service as mod
    sys.modules["app.services.agent_service"] = mod

    yield mod

    # Restore everything we touched
    for k, v in saved.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v


@pytest.mark.asyncio
async def test_live_user_message_replaces_last_history_entry(agent_service_module):
    """When live_user_message is provided, agent's LLM call must see it as the
    final user message instead of the text-only entry in conversation_history."""
    captured = {}

    async def fake_stream(messages, **kwargs):
        captured["messages"] = list(messages)
        yield {"type": "done", "full_text": ""}
        yield {"type": "token", "token": "", "accumulated": ""}

    agent_service_module.llm_service.stream_chat_sentences = fake_stream

    from app.services.agent_service import AgentService
    svc = AgentService()
    history = [{"role": "user", "content": "old"},
               {"role": "user", "content": "describe this [Attached 1 image: 1024x768]"}]
    live = {"role": "user", "content": [
        {"type": "text", "text": "describe this"},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,xxx"}},
    ]}

    gen = svc.run("describe this", history, live_user_message=live)
    async for _ in gen:
        if "messages" in captured:
            break

    assert captured["messages"][-1] == live
    assert captured["messages"][-1]["content"] != "describe this [Attached 1 image: 1024x768]"
    # History itself is unchanged — image bytes never enter conversation_history
    assert history[-1]["content"] == "describe this [Attached 1 image: 1024x768]"
