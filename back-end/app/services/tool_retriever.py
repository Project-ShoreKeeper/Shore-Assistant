"""Embedding-based tool retriever via shore-ai-service."""

import numpy as np

from app.core.config import settings
from app.services.ai_client.embed import EmbedUnavailable, embed_client


# Tools that are always injected regardless of retrieval score
ALWAYS_AVAILABLE = {
    "get_system_time",
    "clear_memory",
    "set_reminder",
    "set_scheduled_task",
    "list_tasks",
    "cancel_task",
    "ask_claude",
    "ask_gemini",
    "ask_openai",
    "run_command",
    "computer_use",
}


class ToolRetriever:
    """Retrieve relevant tools for a user query using cosine similarity."""

    def __init__(self):
        self._tool_texts: list[str] = []
        self._tool_names: list[str] = []
        self._tool_embeddings: np.ndarray | None = None

    async def initialize(self, tools: list) -> None:
        """Embed all tool descriptions at startup using shore-ai-service."""
        self._tool_names = [t.name for t in tools]
        self._tool_texts = [f"{t.name}: {t.description}" for t in tools]
        try:
            vectors = await embed_client.encode(self._tool_texts)
        except EmbedUnavailable:
            self._tool_embeddings = None
            print("[ToolRetriever] embed service unavailable; degraded mode")
            return
        self._tool_embeddings = np.asarray(vectors, dtype=np.float32)
        print(f"[ToolRetriever] Indexed {len(tools)} tools")

    async def retrieve(self, query: str, top_k: int | None = None) -> list[str]:
        """
        Return the names of the top-K most relevant tools for the query.
        Falls back to all tools if scores are below threshold.
        """
        if self._tool_embeddings is None:
            return [n for n in self._tool_names if n in ALWAYS_AVAILABLE]

        k = top_k or settings.TOOL_RETRIEVER_TOP_K
        threshold = settings.TOOL_RETRIEVER_THRESHOLD

        try:
            query_vectors = await embed_client.encode([query])
        except EmbedUnavailable:
            return [n for n in self._tool_names if n in ALWAYS_AVAILABLE]
        query_embedding = np.asarray(query_vectors, dtype=np.float32)
        # Cosine similarity (embeddings are already normalized)
        scores = (self._tool_embeddings @ query_embedding.T).flatten()

        # If no tool passes threshold, return all
        if scores.max() < threshold:
            return list(self._tool_names)

        # Get top-K indices sorted by score descending
        top_indices = np.argsort(scores)[::-1][:k]
        retrieved = [self._tool_names[i] for i in top_indices if scores[i] >= threshold]

        # Merge always-available tools
        for name in ALWAYS_AVAILABLE:
            if name not in retrieved:
                retrieved.append(name)

        # Add companion tools (e.g. web_search always brings web_scrape).
        # Terminal tools are bidirectional companions: retrieving any one of
        # them brings the rest, since "list sessions" almost always implies
        # "send to a session" as a follow-up call.
        TERMINAL_GROUP = [
            "open_terminal", "send_to_terminal", "read_terminal",
            "list_terminals", "close_terminal",
        ]
        COMPANION_TOOLS = {
            "web_search": ["web_scrape"],
            "open_terminal": TERMINAL_GROUP,
            "send_to_terminal": TERMINAL_GROUP,
            "read_terminal": TERMINAL_GROUP,
            "list_terminals": TERMINAL_GROUP,
            "close_terminal": TERMINAL_GROUP,
            "computer_use": ["stop_computer_use"],
            "stop_computer_use": ["computer_use"],
        }
        for tool, companions in COMPANION_TOOLS.items():
            if tool in retrieved:
                for companion in companions:
                    if companion != tool and companion not in retrieved:
                        retrieved.append(companion)

        return retrieved

    async def reindex(self, tools: list) -> None:
        """Re-embed all tools after dynamic tools are added/removed."""
        if self._tool_embeddings is None and not tools:
            return
        await self.initialize(tools)

    def get_tool_descriptions(self, tool_names: list[str], all_tools: list) -> str:
        """Format tool descriptions for the selected tools, ready for the system prompt."""
        tool_map = {t.name: t for t in all_tools}
        lines = []
        for name in tool_names:
            tool = tool_map.get(name)
            if tool:
                # Build a concise description with args info from the docstring
                lines.append(f"- {tool.name}: {tool.description}")
        return "\n".join(lines)

    def get_tool_schemas(self, tool_names: list[str], all_tools: list) -> list[dict]:
        """Convert selected tools to OpenAI-compatible JSON schema for llama-server's native tool calling.

        Args:
            tool_names: list of tool names to include in the output.
            all_tools: list of LangChain BaseTool objects to look up from.

        Returns:
            List of schemas in `{"type": "function", "function": {...}}` shape.
        """
        tool_map = {t.name: t for t in all_tools}
        schemas = []
        for name in tool_names:
            tool = tool_map.get(name)
            if not tool:
                continue

            properties, required = self._extract_properties(tool)

            schemas.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                },
            })
        return schemas

    @staticmethod
    def _resolve_type(prop_def: dict) -> str:
        """Resolve the JSON schema type, handling Pydantic v2's anyOf shape for optional fields."""
        if "type" in prop_def:
            return prop_def["type"]
        for candidate in prop_def.get("anyOf", []):
            t = candidate.get("type")
            if t and t != "null":
                return t
        return "string"

    @staticmethod
    def _extract_properties(tool) -> tuple[dict, list[str]]:
        """Extract JSON schema properties and required list from a LangChain tool's args_schema."""
        if not hasattr(tool, "args_schema") or tool.args_schema is None:
            return {}, []
        try:
            # Pydantic v2 uses model_json_schema; fall back to .schema() for v1 compatibility
            if hasattr(tool.args_schema, "model_json_schema"):
                schema = tool.args_schema.model_json_schema()
            else:
                schema = tool.args_schema.schema()
        except Exception:
            return {}, []

        properties = {}
        for prop_name, prop_def in schema.get("properties", {}).items():
            prop_entry = {"type": ToolRetriever._resolve_type(prop_def)}
            if "description" in prop_def:
                prop_entry["description"] = prop_def["description"]
            if "default" in prop_def:
                prop_entry["default"] = prop_def["default"]
            if "enum" in prop_def:
                prop_entry["enum"] = prop_def["enum"]
            properties[prop_name] = prop_entry

        # Drop required fields that didn't survive property extraction
        required = [r for r in schema.get("required", []) if r in properties]
        return properties, required


tool_retriever = ToolRetriever()
