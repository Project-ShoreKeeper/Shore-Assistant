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
