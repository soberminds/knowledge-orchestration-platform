"""Read-only tool registry for model tool calling."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable


ToolHandler = Callable[[dict[str, Any]], str]


@dataclass(frozen=True)
class ToolDefinition:
    """One OpenAI-compatible function tool definition."""

    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler

    def to_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """Registry for read-only tools exposed to model calls."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        if not definition.name:
            raise ValueError("Tool name is required.")
        self._tools[definition.name] = definition

    def openai_tools(self) -> list[dict[str, Any]]:
        return [tool.to_openai_tool() for tool in self._tools.values()]

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        definition = self._tools.get(name)
        if definition is None:
            return json.dumps(
                {"error": f"Unknown tool: {name}"},
                ensure_ascii=False,
            )
        try:
            return definition.handler(arguments)
        except Exception as exc:
            return json.dumps(
                {"error": str(exc)},
                ensure_ascii=False,
            )

    def is_empty(self) -> bool:
        return not self._tools


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False)


def build_readonly_tool_registry(
    *,
    search_knowledge_base: Callable[[str, int | None], list[Any]],
    search_web: Callable[[str, int], list[Any]],
    web_search_available: Callable[[], bool],
    include_web_search: bool = False,
) -> ToolRegistry:
    """Build read-only tools backed by existing service functions."""

    registry = ToolRegistry()

    registry.register(
        ToolDefinition(
            name="search_knowledge_base",
            description=(
                "Search the current user's knowledge base for relevant document chunks. "
                "Use this when the answer should be grounded in uploaded documents."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query in the user's language.",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Maximum number of chunks to return.",
                        "minimum": 1,
                        "maximum": 8,
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            handler=lambda args: _json_dumps(
                [
                    {
                        "source": hit.source,
                        "page": hit.page,
                        "chunk_index": hit.chunk_index,
                        "score": hit.score,
                        "preview": hit.preview,
                        "content": hit.content,
                        "file_id": hit.file_id,
                        "folder_id": hit.folder_id,
                        "display_name": hit.display_name,
                        "display_path": hit.display_path,
                        "folder_path": hit.folder_path,
                    }
                    for hit in search_knowledge_base(
                        str(args.get("query") or ""),
                        _coerce_top_k(args.get("top_k"), default=4, maximum=8),
                    )
                ]
            ),
        )
    )

    if include_web_search and web_search_available():
        registry.register(
            ToolDefinition(
                name="search_web",
                description=(
                    "Search the external web for recent or time-sensitive information. "
                    "Use only when web search is configured and current information is needed."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Web search query.",
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "Maximum number of web results to return.",
                            "minimum": 1,
                            "maximum": 5,
                        },
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
                handler=lambda args: _json_dumps(
                    [
                        {
                            "title": hit.title,
                            "url": hit.url,
                            "snippet": hit.snippet,
                        }
                        for hit in search_web(
                            str(args.get("query") or ""),
                            _coerce_top_k(args.get("top_k"), default=3, maximum=5) or 3,
                        )
                    ]
                ),
            )
        )

    return registry


def _coerce_top_k(value: Any, *, default: int, maximum: int) -> int:
    try:
        top_k = int(value)
    except Exception:
        top_k = default
    return max(1, min(maximum, top_k))
