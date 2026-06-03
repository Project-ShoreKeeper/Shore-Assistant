import json
import pytest

from app.services.llm_service import _parse_sse_line, _ToolCallAccumulator


def test_parse_sse_line_returns_done_sentinel():
    assert _parse_sse_line("data: [DONE]") == "[DONE]"


def test_parse_sse_line_parses_json_payload():
    payload = {"choices": [{"delta": {"content": "hi"}}]}
    result = _parse_sse_line(f"data: {json.dumps(payload)}")
    assert result == payload


def test_parse_sse_line_returns_none_for_blank():
    assert _parse_sse_line("") is None
    assert _parse_sse_line("   ") is None


def test_parse_sse_line_returns_none_for_non_data_lines():
    # llama-server may send :keep-alive or event: lines we don't care about
    assert _parse_sse_line(": keep-alive") is None
    assert _parse_sse_line("event: ping") is None


def test_parse_sse_line_returns_none_on_malformed_json():
    assert _parse_sse_line("data: {not valid json") is None


def test_accumulator_single_call_assembled_across_chunks():
    acc = _ToolCallAccumulator()
    acc.absorb([{"index": 0, "id": "call_1", "type": "function",
                 "function": {"name": "get_time", "arguments": ""}}])
    acc.absorb([{"index": 0, "function": {"arguments": '{"tz"'}}])
    acc.absorb([{"index": 0, "function": {"arguments": ': "UTC"}'}}])
    result = acc.finalize()
    assert result == [
        {"id": "call_1", "type": "function",
         "function": {"name": "get_time", "arguments": {"tz": "UTC"}}}
    ]


def test_accumulator_multiple_calls_by_index():
    acc = _ToolCallAccumulator()
    acc.absorb([
        {"index": 0, "id": "a", "type": "function",
         "function": {"name": "x", "arguments": "{}"}},
        {"index": 1, "id": "b", "type": "function",
         "function": {"name": "y", "arguments": "{}"}},
    ])
    result = acc.finalize()
    assert [tc["id"] for tc in result] == ["a", "b"]
    assert all(tc["function"]["arguments"] == {} for tc in result)


def test_accumulator_empty_returns_empty_list():
    acc = _ToolCallAccumulator()
    assert acc.finalize() == []


def test_accumulator_malformed_json_passes_through_as_string():
    acc = _ToolCallAccumulator()
    acc.absorb([{"index": 0, "id": "c", "type": "function",
                 "function": {"name": "z", "arguments": "{broken"}}])
    result = acc.finalize()
    assert result[0]["function"]["arguments"] == "{broken"


from app.services.llm_service import _normalize_outgoing_messages


def test_normalize_serializes_dict_arguments():
    messages = [
        {"role": "user", "content": "what time is it"},
        {"role": "assistant", "content": "",
         "tool_calls": [{"id": "c1", "type": "function",
                         "function": {"name": "get_time",
                                      "arguments": {"tz": "UTC"}}}]},
        {"role": "tool", "content": "12:00", "tool_call_id": "c1"},
    ]
    normalized = _normalize_outgoing_messages(messages)
    assert normalized[1]["tool_calls"][0]["function"]["arguments"] == '{"tz": "UTC"}'


def test_normalize_leaves_string_arguments_untouched():
    messages = [
        {"role": "assistant", "content": "",
         "tool_calls": [{"id": "c1", "type": "function",
                         "function": {"name": "n", "arguments": '{"x":1}'}}]}
    ]
    assert _normalize_outgoing_messages(messages)[0]["tool_calls"][0]["function"]["arguments"] == '{"x":1}'


def test_normalize_does_not_mutate_input():
    messages = [
        {"role": "assistant", "content": "",
         "tool_calls": [{"id": "c1", "type": "function",
                         "function": {"name": "n", "arguments": {"a": 1}}}]}
    ]
    _ = _normalize_outgoing_messages(messages)
    assert messages[0]["tool_calls"][0]["function"]["arguments"] == {"a": 1}


def test_normalize_passes_through_non_tool_messages():
    messages = [{"role": "user", "content": "hi"}]
    assert _normalize_outgoing_messages(messages) == messages


from unittest.mock import AsyncMock, MagicMock, patch


class _FakeStreamResponse:
    """Minimal async-context-manager response mimicking httpx.AsyncClient.stream()."""
    def __init__(self, lines: list[str]):
        self._lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def raise_for_status(self):
        return None

    async def aiter_lines(self):
        for line in self._lines:
            yield line


def _build_sse_lines(events: list[dict]) -> list[str]:
    return [f"data: {json.dumps(e)}" for e in events] + ["data: [DONE]"]


async def test_stream_chat_yields_content_thinking_and_tool_calls():
    from app.services.llm_service import LLMService

    events = [
        {"choices": [{"delta": {"reasoning_content": "thinking..."}}]},
        {"choices": [{"delta": {"content": "Hello"}}]},
        {"choices": [{"delta": {"content": " world"}}]},
        {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "call_1", "type": "function",
             "function": {"name": "get_time", "arguments": ""}}
        ]}}]},
        {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": '{"tz":"UTC"}'}}
        ]}, "finish_reason": "tool_calls"}]},
    ]
    fake_lines = _build_sse_lines(events)

    fake_client = MagicMock()
    fake_client.is_closed = False
    fake_client.stream = MagicMock(return_value=_FakeStreamResponse(fake_lines))

    service = LLMService()
    service._client = fake_client

    yielded = []
    async for ev in service.stream_chat([{"role": "user", "content": "hi"}], thinking=True):
        yielded.append(ev)

    types = [e["type"] for e in yielded]
    assert types == ["thinking", "content", "content", "tool_calls"]
    assert yielded[0]["token"] == "thinking..."
    assert yielded[1]["token"] == "Hello"
    assert yielded[2]["token"] == " world"
    assert yielded[3]["tool_calls"][0]["id"] == "call_1"
    assert yielded[3]["tool_calls"][0]["function"]["name"] == "get_time"
    assert yielded[3]["tool_calls"][0]["function"]["arguments"] == {"tz": "UTC"}


async def test_stream_chat_posts_to_v1_chat_completions_with_normalized_args():
    from app.services.llm_service import LLMService

    captured = {}

    def stream_capture(method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        return _FakeStreamResponse(["data: [DONE]"])

    fake_client = MagicMock()
    fake_client.is_closed = False
    fake_client.stream = MagicMock(side_effect=stream_capture)

    service = LLMService()
    service._client = fake_client

    history = [
        {"role": "assistant", "content": "",
         "tool_calls": [{"id": "c1", "type": "function",
                         "function": {"name": "n", "arguments": {"a": 1}}}]}
    ]
    async for _ in service.stream_chat(history, thinking=False):
        pass

    assert captured["method"] == "POST"
    assert captured["url"] == "/v1/chat/completions"
    payload = captured["json"]
    assert payload["stream"] is True
    assert "reasoning_effort" not in payload
    sent_assistant = next(m for m in payload["messages"] if m["role"] == "assistant")
    assert sent_assistant["tool_calls"][0]["function"]["arguments"] == '{"a": 1}'


async def test_stream_chat_sets_reasoning_effort_when_thinking():
    from app.services.llm_service import LLMService

    captured = {}

    def stream_capture(method, url, **kwargs):
        captured["json"] = kwargs.get("json")
        return _FakeStreamResponse(["data: [DONE]"])

    fake_client = MagicMock()
    fake_client.is_closed = False
    fake_client.stream = MagicMock(side_effect=stream_capture)

    service = LLMService()
    service._client = fake_client

    async for _ in service.stream_chat([{"role": "user", "content": "x"}], thinking=True):
        pass

    assert captured["json"]["reasoning_effort"] == "medium"


async def test_generate_once_returns_message_content():
    from app.services.llm_service import LLMService

    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json = MagicMock(return_value={
        "choices": [{"message": {"content": "non-stream answer"}}]
    })

    fake_client = MagicMock()
    fake_client.is_closed = False
    fake_client.post = AsyncMock(return_value=fake_response)

    service = LLMService()
    service._client = fake_client

    result = await service.generate_once([{"role": "user", "content": "x"}])

    assert result == "non-stream answer"
    assert fake_client.post.call_args.args[0] == "/v1/chat/completions"
    payload = fake_client.post.call_args.kwargs["json"]
    assert payload["stream"] is False


async def test_generate_with_image_sends_data_uri_image_url():
    from app.services.llm_service import LLMService

    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json = MagicMock(return_value={
        "choices": [{"message": {"content": "I see a cat."}}]
    })

    fake_client = MagicMock()
    fake_client.is_closed = False
    fake_client.post = AsyncMock(return_value=fake_response)

    service = LLMService()
    service._client = fake_client

    result = await service.generate_with_image("what is this", "AAAA")

    assert result == "I see a cat."
    payload = fake_client.post.call_args.kwargs["json"]
    user_msg = payload["messages"][-1]
    assert user_msg["role"] == "user"
    assert isinstance(user_msg["content"], list)
    assert user_msg["content"][0] == {"type": "text", "text": "what is this"}
    assert user_msg["content"][1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/jpeg;base64,AAAA"},
    }


def test_ollama_only_methods_are_gone():
    from app.services.llm_service import LLMService
    assert not hasattr(LLMService, "unload_model")
    assert not hasattr(LLMService, "preload_model")
    assert not hasattr(LLMService, "list_running_models")


def test_normalize_preserves_list_shaped_content():
    """Multimodal user messages have content as a list of parts. The filter
    that strips empty messages must not call .strip() on a list."""
    messages = [
        {"role": "user", "content": [
            {"type": "text", "text": "describe this"},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,xxx"}},
        ]},
    ]
    out = _normalize_outgoing_messages(messages)
    assert out == messages
