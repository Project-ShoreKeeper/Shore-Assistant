"""
Cloud LLM sub-agent service.
Provides call_claude, call_gemini, call_openai methods.
History is passed via current_history_var ContextVar set by agent_service.
"""

from contextvars import ContextVar

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
        raise NotImplementedError

    async def call_gemini(self, question: str, history: list[dict]) -> str:
        raise NotImplementedError

    async def call_openai(self, question: str, history: list[dict]) -> str:
        raise NotImplementedError


cloud_llm_service = CloudLLMService()
