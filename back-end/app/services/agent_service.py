"""
LangGraph-based agent service.
Orchestrates intent classification, tool execution, and LLM response streaming.
"""

import re
import json
import time
import asyncio
import inspect
from typing import AsyncGenerator, Optional, TypedDict, Annotated

from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from app.services.llm_service import llm_service, SYSTEM_PROMPT
from app.tools import TOOL_MAP


# ==================== State ====================

class AgentState(TypedDict):
    messages: list[dict]           # Conversation history for Ollama
    current_input: str             # Latest user text
    intent: str                    # "direct" | "tool_call"
    tool_name: Optional[str]
    tool_args: Optional[dict]
    tool_result: Optional[str]
    llm_response: str              # Full accumulated response
    actions_log: list[dict]        # Events to stream to frontend


# ==================== Tool call parser ====================

TOOL_CALL_PATTERN = re.compile(
    r"```tool\s*\n?\s*(\{.*?\})\s*\n?\s*```",
    re.DOTALL,
)


def parse_tool_call(text: str) -> Optional[dict]:
    """Extract a tool call JSON from LLM response text."""
    match = TOOL_CALL_PATTERN.search(text)
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
        if "tool" in data:
            return data
    except json.JSONDecodeError:
        pass
    return None


# ==================== Tool execution ====================

async def execute_tool(tool_name: str, tool_args: dict) -> str:
    """Execute a registered tool by name."""
    tool = TOOL_MAP.get(tool_name)
    if tool is None:
        return f"Error: Unknown tool '{tool_name}'"
    try:
        # Use ainvoke for async tools, invoke for sync
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

    MAX_TOOL_ROUNDS = 5  # Prevent infinite tool loops

    async def run(
        self,
        user_text: str,
        conversation_history: list[dict],
    ) -> AsyncGenerator[dict, None]:
        """
        Process user input through the agent pipeline.

        Yields event dicts:
          {"type": "agent_action", "action": "thinking", "detail": "..."}
          {"type": "agent_action", "action": "tool_call", "tool": "...", "args": {...}}
          {"type": "agent_action", "action": "tool_result", "tool": "...", "result": "..."}
          {"type": "llm_token", "token": "...", "accumulated": "..."}
          {"type": "llm_sentence", "text": "..."}
          {"type": "llm_complete", "text": "..."}
        """
        # Build messages for Ollama
        messages = list(conversation_history)
        messages.append({"role": "user", "content": user_text})

        yield {
            "type": "agent_action",
            "action": "thinking",
            "detail": "Processing your message...",
            "timestamp": time.time(),
        }

        for round_num in range(self.MAX_TOOL_ROUNDS):
            # Stream LLM response
            full_response = ""
            sentence_buffer = ""

            async for event in llm_service.stream_chat_sentences(messages):
                if event["type"] == "token":
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
                elif event["type"] == "done":
                    full_response = event["full_text"]

            # Check if the response contains a tool call
            tool_call = parse_tool_call(full_response)

            if tool_call is None:
                # No tool call -- this is the final response
                yield {"type": "llm_complete", "text": full_response}
                return

            # Execute the tool
            tool_name = tool_call["tool"]
            tool_args = tool_call.get("args", {})

            yield {
                "type": "agent_action",
                "action": "tool_call",
                "detail": f"Calling {tool_name}...",
                "tool": tool_name,
                "args": tool_args,
                "timestamp": time.time(),
            }

            result = await execute_tool(tool_name, tool_args)

            yield {
                "type": "agent_action",
                "action": "tool_result",
                "detail": f"Got result from {tool_name}",
                "tool": tool_name,
                "result": result[:500],  # Truncate for frontend display
                "timestamp": time.time(),
            }

            # Add the assistant's tool-call response and the tool result to messages,
            # then loop to let the LLM synthesize the result
            messages.append({"role": "assistant", "content": full_response})
            messages.append({
                "role": "user",
                "content": f"Tool result for {tool_name}:\n{result}",
            })

        # If we exhausted tool rounds, yield whatever we have
        yield {
            "type": "llm_complete",
            "text": "I've reached the maximum number of tool calls. Here's what I found so far.",
        }


agent_service = AgentService()
