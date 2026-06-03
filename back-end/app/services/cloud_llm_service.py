"""
Cloud LLM sub-agent service.
Provides call_claude, call_gemini, call_openai methods.
History is passed via current_history_var ContextVar set by agent_service.
"""

from contextvars import ContextVar

from anthropic import AsyncAnthropic
from google import genai
from google.genai import types as genai_types
from openai import AsyncOpenAI

from app.core.config import settings

# Set by agent_service before each tool execution loop; read by cloud tools
current_history_var: ContextVar[list[dict]] = ContextVar("current_history", default=[])

ESCALATION_SYSTEM_PROMPT = (
    "You are a powerful AI sub-agent assisting Shore, a personal AI assistant. "
    "Shore's orchestrator has delegated a task to you because it requires deep reasoning or advanced capability. "
    "Be precise, thorough, and respond in plain text. Do not introduce yourself or explain that you are an AI."
)


class CloudLLMService:
    def __init__(self):
        self._anthropic_client = None
        self._gemini_client = None
        self._openai_client = None

    def _get_anthropic_client(self) -> "AsyncAnthropic":
        if self._anthropic_client is None:
            self._anthropic_client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        return self._anthropic_client

    def _get_gemini_client(self) -> "genai.Client":
        if self._gemini_client is None:
            self._gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)
        return self._gemini_client

    def _get_openai_client(self) -> "AsyncOpenAI":
        if self._openai_client is None:
            self._openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        return self._openai_client

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

            client = self._get_anthropic_client()
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

            client = self._get_gemini_client()
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
        """Call GPT-4o with conversation history as context."""
        if not settings.OPENAI_API_KEY:
            return "Error calling OpenAI: OPENAI_API_KEY is not set."
        try:
            trimmed = self._trim_history(history, settings.CLOUD_HISTORY_MAX_TURNS)

            messages = [{"role": "system", "content": ESCALATION_SYSTEM_PROMPT}]
            for m in trimmed:
                role = m.get("role", "user")
                if role not in ("user", "assistant"):
                    continue
                messages.append({"role": role, "content": m["content"]})
            messages.append({"role": "user", "content": question})

            client = self._get_openai_client()
            response = await client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                max_tokens=settings.CLOUD_MAX_TOKENS,
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"Error calling OpenAI: {e}"


cloud_llm_service = CloudLLMService()
