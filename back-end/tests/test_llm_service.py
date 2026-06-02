import json
import pytest

from app.services.llm_service import _parse_sse_line


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
