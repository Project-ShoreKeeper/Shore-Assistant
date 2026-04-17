"""
LangGraph-based agent service.
Orchestrates tool execution and LLM response streaming using Ollama's native tool calling.
"""

import time
from datetime import datetime
from typing import AsyncGenerator, Optional, TypedDict

from app.services.llm_service import llm_service, build_system_prompt
from app.services.tool_retriever import tool_retriever
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
        return str(result)
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
        thinking: bool = False,
        no_tools: bool = False,
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
        # Retrieve relevant tools for this query (skip for notifications)
        if no_tools:
            tool_schemas = None
        else:
            relevant_tool_names = tool_retriever.retrieve(user_text)
            tool_schemas = tool_retriever.get_tool_schemas(relevant_tool_names, ALL_TOOLS)

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S (%A)")
        system_prompt = f"[Current time: {current_time}]\n\n" + build_system_prompt()

        # Build messages for Ollama
        messages = [m for m in conversation_history if m["content"].strip()]

        max_rounds = 1 if no_tools else self.MAX_TOOL_ROUNDS
        for round_num in range(max_rounds):
            # Stream LLM response
            full_response = ""
            pending_tool_calls = []

            async for event in llm_service.stream_chat_sentences(
                messages, system_prompt=system_prompt, thinking=thinking,
                tools=tool_schemas,
            ):
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

            # If the model returned text alongside tool calls, emit llm_complete for that text
            # as a separate assistant message before the tool_call events, so the UI can render
            # the pre-tool-call narration as its own bubble. (Per spec: "let the text come after
            # as another message, dont fully delete it" — text appears before tool cards in UI.)
            # NOTE: Token streaming already sent the text; llm_complete finalizes it.
            if full_response.strip():
                yield {"type": "llm_complete", "text": full_response}

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

                # Add tool result in Ollama's expected format
                messages.append({
                    "role": "tool",
                    "content": result,
                    "tool_name": tool_name,
                })

        # Exhausted tool rounds
        yield {
            "type": "llm_complete",
            "text": "I've reached the maximum number of tool calls. Here's what I found so far.",
        }


agent_service = AgentService()
