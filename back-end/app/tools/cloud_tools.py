"""Cloud AI sub-agent tools for Gemma4 to delegate hard tasks."""

from langchain_core.tools import tool

from app.services.cloud_llm_service import cloud_llm_service, current_history_var


@tool
async def ask_claude(question: str) -> str:
    """Delegate a complex or difficult question to Claude (Anthropic).
    Use when the task requires deep reasoning, advanced coding, nuanced writing,
    detailed analysis, or when you are uncertain about your answer."""
    history = current_history_var.get([])
    return await cloud_llm_service.call_claude(question, history)


@tool
async def ask_gemini(question: str) -> str:
    """Delegate to Gemini (Google). Best for large document analysis,
    long-context summarization tasks, or when Claude is unavailable."""
    history = current_history_var.get([])
    return await cloud_llm_service.call_gemini(question, history)


@tool
async def ask_openai(question: str) -> str:
    """Delegate to GPT-4o (OpenAI). Use as a fallback when other cloud
    models are unavailable or rate-limited."""
    history = current_history_var.get([])
    return await cloud_llm_service.call_openai(question, history)
