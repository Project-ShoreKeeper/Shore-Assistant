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

from app.services.llm_service import llm_service, build_system_prompt
from app.services.tool_retriever import tool_retriever
from app.tools import TOOL_MAP, ALL_TOOLS


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
    r"```(?:tool|json)\s*\n?\s*(\{.*?\})\s*\n?\s*```",
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
        print(f"\n{'#'*60}")
        print(f"[Agent] ===== NEW REQUEST =====")
        print(f"[Agent] User text: {user_text[:200]}")
        print(f"[Agent] Conversation history length: {len(conversation_history)}")
        for i, m in enumerate(conversation_history):
            role = m["role"]
            preview = m["content"][:80].replace("\n", "\\n")
            print(f"[Agent]   history[{i}]: {role}: {preview}")

        # Retrieve relevant tools for this query
        relevant_tool_names = tool_retriever.retrieve(user_text)
        tool_descriptions = tool_retriever.get_tool_descriptions(
            relevant_tool_names, ALL_TOOLS
        )
        system_prompt = build_system_prompt(tool_descriptions)

        print(f"[Agent] Retrieved tools: {relevant_tool_names}")
        print(f"[Agent] System prompt length: {len(system_prompt)} chars")
        print(f"[Agent] Tool descriptions:\n{tool_descriptions}")

        # Build messages for Ollama
        # NOTE: conversation_history already includes the current user message
        # (appended by chat_ws.py before calling run()), so don't add it again.
        # Filter out empty assistant messages (from previous 0-token failures)
        messages = [m for m in conversation_history if m["content"].strip()]
        dropped = len(conversation_history) - len(messages)
        if dropped:
            print(f"[Agent] Dropped {dropped} empty messages from history")
        print(f"[Agent] Messages to send (count): {len(messages)}")
        # Verify last message is the current user input
        if messages:
            last = messages[-1]
            print(f"[Agent] Last message: role={last['role']}, content={last['content'][:100]}")
        print(f"{'#'*60}\n")

        yield {
            "type": "agent_action",
            "action": "thinking",
            "detail": "Processing your message...",
            "timestamp": time.time(),
        }

        for round_num in range(self.MAX_TOOL_ROUNDS):
            print(f"\n[Agent] --- Tool round {round_num + 1}/{self.MAX_TOOL_ROUNDS} ---")

            # Stream LLM response
            full_response = ""
            thinking_text = ""
            sentence_buffer = ""
            event_count = 0

            async for event in llm_service.stream_chat_sentences(
                messages, system_prompt=system_prompt
            ):
                event_count += 1
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
                elif event["type"] == "done":
                    full_response = event["full_text"]
                    thinking_text = event.get("thinking_text", "")

            print(f"[Agent] LLM streaming done. Events received: {event_count}")
            print(f"[Agent] Full response length: {len(full_response)} chars")
            print(f"[Agent] Thinking text length: {len(thinking_text)} chars")
            print(f"[Agent] Full response preview: {full_response[:300]}")

            # Check if the response contains a tool call
            tool_call = parse_tool_call(full_response)

            # Fallback: if content is empty but thinking contains a tool call,
            # the model put the tool call in its reasoning (common with thinking models)
            if tool_call is None and not full_response.strip() and thinking_text:
                print(f"[Agent] Content empty — checking thinking text for tool calls...")
                tool_call = parse_tool_call(thinking_text)
                if tool_call:
                    print(f"[Agent] Found tool call in thinking text: {tool_call}")

            print(f"[Agent] Tool call parsed: {tool_call}")

            if tool_call is None:
                # No tool call -- this is the final response
                print(f"[Agent] No tool call found — returning final response")
                yield {"type": "llm_complete", "text": full_response}
                return

            # Execute the tool
            tool_name = tool_call["tool"]
            tool_args = tool_call.get("args", {})
            print(f"[Agent] Executing tool: {tool_name} with args: {tool_args}")

            yield {
                "type": "agent_action",
                "action": "tool_call",
                "detail": f"Calling {tool_name}...",
                "tool": tool_name,
                "args": tool_args,
                "timestamp": time.time(),
            }

            result = await execute_tool(tool_name, tool_args)
            print(f"[Agent] Tool result: {result[:300]}")

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
            print(f"[Agent] Messages count after tool round: {len(messages)}")

        # If we exhausted tool rounds, yield whatever we have
        yield {
            "type": "llm_complete",
            "text": "I've reached the maximum number of tool calls. Here's what I found so far.",
        }


agent_service = AgentService()
