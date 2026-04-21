"""
Cloud LLM sub-agent service.
Provides call_claude, call_gemini, call_openai methods.
History is passed via current_history_var ContextVar set by agent_service.
"""

from contextvars import ContextVar

from anthropic import AsyncAnthropic
from google import genai
from google.genai import types as genai_types

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
        """Call Claude with conversation history as context. Uses prompt caching on system prompt."""
        if not settings.ANTHROPIC_API_KEY:
            return "Error calling Claude: ANTHROPIC_API_KEY is not set."
        try:
            trimmed = self._trim_history(history, settings.CLOUD_HISTORY_MAX_TURNS)

            messages = []
            for m in trimmed:
                role = m.get("role", "user")
                if role not in ("user", "assistant"):
                    continue
                messages.append({"role": role, "content": m["content"]})
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

    async def call_gemini(self, question: str, history: list[dict]) -> str:
        """Call Gemini with conversation history as context."""
        if not settings.GEMINI_API_KEY:
            return "Error calling Gemini: GEMINI_API_KEY is not set."
        try:
            trimmed = self._trim_history(history, settings.CLOUD_HISTORY_MAX_TURNS)

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

    async def call_openai(self, question: str, history: list[dict]) -> str:
        raise NotImplementedError


cloud_llm_service = CloudLLMService()
