"""
Embedding-based tool retriever.
Embeds tool descriptions at startup, retrieves the most relevant tools per query
instead of injecting all tools into every LLM prompt.
"""

import numpy as np
from sentence_transformers import SentenceTransformer

from app.core.config import settings


# Tools that are always injected regardless of retrieval score
ALWAYS_AVAILABLE = {
    "get_system_time",
    "clear_memory",
    "set_reminder",
    "set_scheduled_task",
    "list_tasks",
    "cancel_task",
}


class ToolRetriever:
    """Retrieve relevant tools for a user query using cosine similarity."""

    def __init__(self):
        self._model: SentenceTransformer | None = None
        self._tool_texts: list[str] = []
        self._tool_names: list[str] = []
        self._tool_embeddings: np.ndarray | None = None

    def initialize(self, tools: list) -> None:
        """
        Embed all tool descriptions at startup.
        Args:
            tools: list of langchain tool objects with .name and .description
        """
        print(f"[ToolRetriever] Loading embedding model: {settings.TOOL_RETRIEVER_MODEL}")
        self._model = SentenceTransformer(
            settings.TOOL_RETRIEVER_MODEL,
            device="cpu",
        )

        self._tool_names = [t.name for t in tools]
        self._tool_texts = [f"{t.name}: {t.description}" for t in tools]
        self._tool_embeddings = self._model.encode(
            self._tool_texts, normalize_embeddings=True
        )
        print(f"[ToolRetriever] Indexed {len(tools)} tools")

    def retrieve(self, query: str, top_k: int | None = None) -> list[str]:
        """
        Return the names of the top-K most relevant tools for the query.
        Falls back to all tools if scores are below threshold.
        """
        if self._model is None or self._tool_embeddings is None:
            return list(self._tool_names)

        k = top_k or settings.TOOL_RETRIEVER_TOP_K
        threshold = settings.TOOL_RETRIEVER_THRESHOLD

        query_embedding = self._model.encode(
            [query], normalize_embeddings=True
        )
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

        # Add companion tools (e.g. web_search always brings web_scrape)
        COMPANION_TOOLS = {
            "web_search": "web_scrape",
        }
        for tool, companion in COMPANION_TOOLS.items():
            if tool in retrieved and companion not in retrieved:
                retrieved.append(companion)

        return retrieved

    def reindex(self, tools: list) -> None:
        """Re-embed all tools after dynamic tools are added/removed."""
        if self._model is None:
            return
        self._tool_names = [t.name for t in tools]
        self._tool_texts = [f"{t.name}: {t.description}" for t in tools]
        self._tool_embeddings = self._model.encode(
            self._tool_texts, normalize_embeddings=True
        )
        print(f"[ToolRetriever] Re-indexed {len(tools)} tools")

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
        """Convert selected tools to OpenAI-compatible JSON schema for Ollama's native tool calling."""
        tool_map = {t.name: t for t in all_tools}
        schemas = []
        for name in tool_names:
            tool = tool_map.get(name)
            if not tool:
                continue
            # Extract parameters from LangChain's args_schema
            try:
                schema = tool.args_schema.schema()
                properties = {}
                required = schema.get("required", [])
                for prop_name, prop_def in schema.get("properties", {}).items():
                    prop_entry = {"type": prop_def.get("type", "string")}
                    if "description" in prop_def:
                        prop_entry["description"] = prop_def["description"]
                    if "default" in prop_def:
                        prop_entry["default"] = prop_def["default"]
                    if "enum" in prop_def:
                        prop_entry["enum"] = prop_def["enum"]
                    properties[prop_name] = prop_entry
            except Exception:
                properties = {}
                required = []

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


tool_retriever = ToolRetriever()
