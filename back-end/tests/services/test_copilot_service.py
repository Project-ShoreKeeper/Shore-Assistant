"""Unit tests for CopilotService output summarization, prompt, and tick gating."""
from app.services.copilot_service import summarize_copilot_run


def _events(final_text, actions=()):
    """Build a fake agent_service.run event stream."""
    evs = []
    for a in actions:
        evs.append({"type": "agent_action", "action": "tool_call",
                    "tool": a["tool"], "args": a["args"], "timestamp": 1.0})
        evs.append({"type": "agent_action", "action": "tool_result",
                    "tool": a["tool"], "result": a["result"],
                    "status": a.get("status", "completed"), "timestamp": 2.0})
    evs.append({"type": "llm_complete", "text": final_text})
    return evs


def test_summarize_noop_no_actions_returns_none():
    assert summarize_copilot_run(_events("__NOOP__")) is None


def test_summarize_empty_no_actions_returns_none():
    assert summarize_copilot_run(_events("   ")) is None


def test_summarize_real_text_returns_message():
    out = summarize_copilot_run(_events("I ran the tests, 2 failed."))
    assert out is not None
    assert out["text"] == "I ran the tests, 2 failed."
    assert out["agent_actions"] == []


def test_summarize_collects_actions_with_results():
    out = summarize_copilot_run(_events(
        "Tests are green.",
        actions=[{"tool": "run_command",
                  "args": {"command": "pytest"},
                  "result": "2 passed"}],
    ))
    assert out is not None
    assert len(out["agent_actions"]) == 1
    act = out["agent_actions"][0]
    assert act["tool"] == "run_command"
    assert act["args"] == {"command": "pytest"}
    assert act["result"] == "2 passed"
    assert act["status"] == "completed"


def test_summarize_noop_text_but_actions_keeps_actions():
    out = summarize_copilot_run(_events(
        "__NOOP__",
        actions=[{"tool": "run_command", "args": {"command": "git status"},
                  "result": "clean"}],
    ))
    assert out is not None
    assert out["text"] == ""
    assert len(out["agent_actions"]) == 1
