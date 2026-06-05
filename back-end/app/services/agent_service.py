"""
LangGraph-based agent service.
Orchestrates tool execution and LLM response streaming using llama-server's OpenAI-compatible tool calling.
"""

import json
import time
from typing import AsyncGenerator, Optional, TypedDict

from app.services.llm_service import llm_service, build_system_prompt
from app.services.memory.types import ContextBundle
from app.services.tool_retriever import tool_retriever
from app.services.cloud_llm_service import current_history_var
from app.tools import TOOL_MAP, ALL_TOOLS


# ==================== State ====================

class AgentState(TypedDict):
    messages: list[dict]
    current_input: str
    intent: str
    tool_name: Optional[str]
    tool_args: Optional[dict]
    tool_result: Optional[str]
    llm_response: str
    actions_log: list[dict]


# ==================== Tool execution ====================

def _unwrap_tool_envelope(result_str: str) -> str:
    """Flatten a file_tool ToolEnvelope into LLM-friendly text.

    file_tool wraps every response in:
        {"tool", "status", "duration_ms", "risk_level", "reversible",
         "result", "suggested_next_actions", "warnings"}

    Plain-string results from legacy tools are returned untouched. The agent
    loop's error detection relies on the "Error" prefix, so envelope errors
    are surfaced that way.
    """
    try:
        envelope = json.loads(result_str)
    except (json.JSONDecodeError, TypeError):
        return result_str  # legacy tool — plain string

    if not (isinstance(envelope, dict) and "status" in envelope and "result" in envelope):
        return result_str  # some other JSON the tool happened to return

    if envelope.get("status") == "error":
        return f"Error: {envelope.get('message', 'unknown file_tool error')}"

    parts: list[str] = []

    # High-risk + irreversible actions get a leading flag so the LLM stays cautious.
    if envelope.get("risk_level") == "high" and not envelope.get("reversible", True):
        parts.append("[WARNING: high-risk, irreversible action]")

    parts.append(json.dumps(envelope["result"], ensure_ascii=False))

    if envelope.get("warnings"):
        parts.append("Warnings: " + "; ".join(str(w) for w in envelope["warnings"]))

    if envelope.get("suggested_next_actions"):
        hints = "\n".join(f"- {h}" for h in envelope["suggested_next_actions"])
        parts.append(f"Suggested next steps:\n{hints}")

    return "\n".join(parts)


async def execute_tool(tool_name: str, tool_args: dict) -> str:
    """Execute a registered tool by name."""
    tool = TOOL_MAP.get(tool_name)
    if tool is None:
        return f"Error: Unknown tool '{tool_name}'"

    try:
        if tool.coroutine:
            result = await tool.ainvoke(tool_args)
        else:
            result = tool.invoke(tool_args)
        return _unwrap_tool_envelope(str(result))
    except Exception as e:
        return f"Error executing tool '{tool_name}': {e}"


# ==================== Agent runner ====================

class AgentService:
    """
    Runs the agent loop: user input -> LLM -> (optional tool call) -> final response.
    Yields events as an async generator for real-time WebSocket streaming.
    """

    MAX_TOOL_ROUNDS = 50

    async def run(
        self,
        user_text: str,
        conversation_history: list[dict],
        memory_bundle: ContextBundle | None = None,
        thinking: bool = False,
        no_tools: bool = False,
        live_user_message: Optional[dict] = None,
    ) -> AsyncGenerator[dict, None]:
        """
        Process user input through the agent pipeline.

        Yields event dicts:
          {"type": "agent_action", "action": "tool_call", "tool": "...", "args": {...}}
          {"type": "agent_action", "action": "tool_result", "tool": "...", "result": "...", "status": "completed"|"error"}
          {"type": "llm_token", "token": "...", "accumulated": "..."}
          {"type": "llm_sentence", "text": "..."}
          {"type": "llm_complete", "text": "..."}
        """
        t0 = time.perf_counter()

        # Retrieve relevant tools for this query (skip for notifications)
        if no_tools:
            tool_schemas = None
            relevant_tool_names = None
        else:
            relevant_tool_names = tool_retriever.retrieve(user_text)
            tool_schemas = tool_retriever.get_tool_schemas(relevant_tool_names, ALL_TOOLS)

        t1 = time.perf_counter()

        # Pass retrieved names so the system prompt only includes rules for
        # tool groups actually in scope this turn.
        system_prompt = build_system_prompt(
            relevant_tool_names,
            memory_bundle=memory_bundle if not no_tools else None,
        )

        # Build messages for llama-server
        messages = [
            m for m in conversation_history
            if (m["content"] if isinstance(m["content"], list)
                else m["content"].strip())
        ]
        if live_user_message is not None and messages:
            # Swap the text-only user turn (already in history) with the
            # multimodal version for this LLM call only. conversation_history
            # itself stays text-only so future turns don't re-ship image bytes.
            messages[-1] = live_user_message
        current_history_var.set(conversation_history)

        prompt_chars = len(system_prompt) + sum(len(m.get("content") or "") for m in messages)
        tool_count = len(tool_schemas) if tool_schemas else 0
        print(
            f"[Latency] tool_retrieval={(t1 - t0) * 1000:.1f}ms "
            f"tools={tool_count} prompt_chars={prompt_chars} history_msgs={len(messages)}"
        )

        max_rounds = 1 if no_tools else self.MAX_TOOL_ROUNDS
        for round_num in range(max_rounds):
            # Stream LLM response
            full_response = ""
            pending_tool_calls = []
            first_token_logged = False
            t_llm_start = time.perf_counter()

            async for event in llm_service.stream_chat_sentences(
                messages, system_prompt=system_prompt, thinking=thinking,
                tools=tool_schemas,
            ):
                if not first_token_logged and event["type"] in ("thinking_token", "token"):
                    t_first = time.perf_counter()
                    kind = "thinking" if event["type"] == "thinking_token" else "content"
                    print(
                        f"[Latency] round={round_num} llama_ttft={(t_first - t_llm_start) * 1000:.1f}ms "
                        f"({kind}) total_since_user={(t_first - t0) * 1000:.1f}ms"
                    )
                    first_token_logged = True
                if event["type"] == "thinking_token":
                    yield {
                        "type": "llm_thinking_token",
                        "token": event["token"],
                        "accumulated": event["accumulated"],
                    }
                elif event["type"] == "thinking_done":
                    yield {
                        "type": "llm_thinking_done",
                        "text": event["text"],
                    }
                elif event["type"] == "token":
                    full_response = event["accumulated"]
                    yield {
                        "type": "llm_token",
                        "token": event["token"],
                        "accumulated": event["accumulated"],
                    }
                elif event["type"] == "sentence":
                    yield {
                        "type": "llm_sentence",
                        "text": event["text"],
                    }
                elif event["type"] == "tool_calls":
                    pending_tool_calls = event["tool_calls"]
                elif event["type"] == "done":
                    full_response = event["full_text"]

            # No tool calls — stream is complete
            if not pending_tool_calls:
                yield {"type": "llm_complete", "text": full_response}
                return

            # Add the assistant message (with tool_calls) to history
            assistant_msg = {"role": "assistant", "content": full_response}
            if pending_tool_calls:
                assistant_msg["tool_calls"] = pending_tool_calls
            messages.append(assistant_msg)

            for tc in pending_tool_calls:
                func = tc.get("function", {})
                tool_name = func.get("name", "unknown")
                tool_args = func.get("arguments", {})

                yield {
                    "type": "agent_action",
                    "action": "tool_call",
                    "detail": f"Calling {tool_name}...",
                    "tool": tool_name,
                    "args": tool_args,
                    "timestamp": time.time(),
                }

                result = await execute_tool(tool_name, tool_args)
                is_error = result.startswith("Error")

                yield {
                    "type": "agent_action",
                    "action": "tool_result",
                    "detail": f"Got result from {tool_name}",
                    "tool": tool_name,
                    "result": result,
                    "status": "error" if is_error else "completed",
                    "timestamp": time.time(),
                }

                # Add tool result in OpenAI-compatible format
                messages.append({
                    "role": "tool",
                    "content": result,
                    "tool_call_id": tc.get("id"),
                })

        # Exhausted tool rounds
        yield {
            "type": "llm_complete",
            "text": "I've reached the maximum number of tool calls. Here's what I found so far.",
        }


agent_service = AgentService()
