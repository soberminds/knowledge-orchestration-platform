"""Tool registry for model tool calling."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Literal


ToolHandler = Callable[[dict[str, Any]], str]
ToolRiskLevel = Literal["read", "write", "dangerous"]
ToolExecutionStatus = Literal["success", "error", "pending_confirmation"]
ToolResultSummarizer = Callable[[str], str]
ToolConfirmationRequester = Callable[["ToolSpec", dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class ToolSpec:
    """One tool exposed to the model and to the Agent diagnostics UI."""

    name: str
    display_name: str
    description: str
    parameters: dict[str, Any]
    risk_level: ToolRiskLevel
    requires_confirmation: bool
    default_enabled: bool
    handler: ToolHandler
    summarize_result: ToolResultSummarizer | None = None
    confirmation_requester: ToolConfirmationRequester | None = None

    def to_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass(frozen=True)
class ToolExecutionResult:
    """Structured result for one tool call."""

    name: str
    display_name: str
    arguments: dict[str, Any]
    status: ToolExecutionStatus
    content: str
    summary: str
    duration_ms: int
    risk_level: ToolRiskLevel
    requires_confirmation: bool
    default_enabled: bool
    error: str | None = None
    confirmation_id: str | None = None
    confirmation_message: str | None = None

    def to_diagnostic(self, *, tool_call_id: str = "") -> dict[str, Any]:
        return {
            "id": tool_call_id or None,
            "name": self.name,
            "display_name": self.display_name,
            "arguments": self.arguments,
            "status": self.status,
            "summary": self.summary,
            "duration_ms": self.duration_ms,
            "risk_level": self.risk_level,
            "requires_confirmation": self.requires_confirmation,
            "default_enabled": self.default_enabled,
            "error": self.error,
            "confirmation_id": self.confirmation_id,
            "confirmation_message": self.confirmation_message,
        }


class ToolRegistry:
    """Registry for tools exposed to model calls."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, definition: ToolSpec) -> None:
        if not definition.name:
            raise ValueError("Tool name is required.")
        self._tools[definition.name] = definition

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def openai_tools(self) -> list[dict[str, Any]]:
        return [tool.to_openai_tool() for tool in self._tools.values() if tool.default_enabled]

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolExecutionResult:
        started_at = time.perf_counter()
        normalized_arguments = dict(arguments or {})
        definition = self._tools.get(name)
        if definition is None:
            content = _json_dumps({"error": f"Unknown tool: {name}"})
            return ToolExecutionResult(
                name=name,
                display_name=name or "Unknown tool",
                arguments=normalized_arguments,
                status="error",
                content=content,
                summary=f"未知工具：{name}",
                duration_ms=_elapsed_ms(started_at),
                risk_level="read",
                requires_confirmation=False,
                default_enabled=False,
                error=f"Unknown tool: {name}",
            )

        if definition.requires_confirmation:
            confirmation_payload = (
                definition.confirmation_requester(definition, normalized_arguments)
                if definition.confirmation_requester is not None
                else {}
            )
            confirmation_id = str(confirmation_payload.get("confirmation_id") or "") or None
            confirmation_message = str(confirmation_payload.get("message") or "") or None
            content = _json_dumps(
                {
                    "status": "pending_confirmation",
                    "tool": definition.name,
                    "confirmation_id": confirmation_id,
                    "message": confirmation_message,
                    "arguments": normalized_arguments,
                }
            )
            return ToolExecutionResult(
                name=definition.name,
                display_name=definition.display_name,
                arguments=normalized_arguments,
                status="pending_confirmation",
                content=content,
                summary=confirmation_message or f"{definition.display_name} 需要用户确认后执行。",
                duration_ms=_elapsed_ms(started_at),
                risk_level=definition.risk_level,
                requires_confirmation=definition.requires_confirmation,
                default_enabled=definition.default_enabled,
                confirmation_id=confirmation_id,
                confirmation_message=confirmation_message,
            )

        try:
            content = definition.handler(normalized_arguments)
            summary = (
                definition.summarize_result(content)
                if definition.summarize_result is not None
                else f"{definition.display_name} 执行完成。"
            )
            return ToolExecutionResult(
                name=definition.name,
                display_name=definition.display_name,
                arguments=normalized_arguments,
                status="success",
                content=content,
                summary=summary,
                duration_ms=_elapsed_ms(started_at),
                risk_level=definition.risk_level,
                requires_confirmation=definition.requires_confirmation,
                default_enabled=definition.default_enabled,
            )
        except Exception as exc:
            content = _json_dumps({"error": str(exc)})
            return ToolExecutionResult(
                name=definition.name,
                display_name=definition.display_name,
                arguments=normalized_arguments,
                status="error",
                content=content,
                summary=f"{definition.display_name} 执行失败：{exc}",
                duration_ms=_elapsed_ms(started_at),
                risk_level=definition.risk_level,
                requires_confirmation=definition.requires_confirmation,
                default_enabled=definition.default_enabled,
                error=str(exc),
            )

    def is_empty(self) -> bool:
        return not self.openai_tools()


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _elapsed_ms(started_at: float) -> int:
    return max(0, int((time.perf_counter() - started_at) * 1000))


def _load_json_payload(raw: str) -> Any:
    try:
        return json.loads(raw)
    except Exception:
        return None


def _summarize_json_list(raw: str, *, item_label: str) -> str:
    payload = _load_json_payload(raw)
    if isinstance(payload, list):
        return f"返回 {len(payload)} 条{item_label}。"
    if isinstance(payload, dict) and payload.get("error"):
        return str(payload.get("error"))
    return "工具执行完成。"


def build_readonly_tool_registry(
    *,
    search_knowledge_base: Callable[[str, int | None], list[Any]],
    list_documents: Callable[[int | None, str | None, int], dict[str, Any]],
    get_document_metadata: Callable[[int], dict[str, Any]],
    read_document_summary: Callable[[int, int], dict[str, Any]],
    request_tool_confirmation: ToolConfirmationRequester | None = None,
    search_web: Callable[[str, int], list[Any]],
    web_search_available: Callable[[], bool],
    email_tool_available: Callable[[], bool] | None = None,
    include_web_search: bool = False,
) -> ToolRegistry:
    """Build Agent tools backed by existing service functions."""

    registry = ToolRegistry()

    registry.register(
        ToolSpec(
            name="search_knowledge_base",
            display_name="搜索知识库",
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
            risk_level="read",
            requires_confirmation=False,
            default_enabled=True,
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
            summarize_result=lambda raw: _summarize_json_list(raw, item_label="知识库片段"),
        )
    )

    registry.register(
        ToolSpec(
            name="list_documents",
            display_name="查询文档列表",
            description=(
                "List folders and files in the current user's document library. "
                "Use this to answer questions about what documents exist, what is inside a folder, "
                "or to find candidate file IDs before reading metadata or summaries."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "folder_id": {
                        "type": "integer",
                        "description": "Optional folder ID. If set, list this folder and its descendants.",
                        "minimum": 1,
                    },
                    "keyword": {
                        "type": "string",
                        "description": "Optional keyword used to filter names and display paths.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum folders and files to return.",
                        "minimum": 1,
                        "maximum": 50,
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
            risk_level="read",
            requires_confirmation=False,
            default_enabled=True,
            handler=lambda args: _json_dumps(
                list_documents(
                    _coerce_optional_int(args.get("folder_id")),
                    str(args.get("keyword") or "").strip() or None,
                    _coerce_top_k(args.get("limit"), default=20, maximum=50),
                )
            ),
            summarize_result=_summarize_document_listing,
        )
    )

    registry.register(
        ToolSpec(
            name="get_document_metadata",
            display_name="查询文档元数据",
            description=(
                "Get metadata for one document by file_id, including path, folder, size, "
                "parse status, index status and last indexed time."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "file_id": {
                        "type": "integer",
                        "description": "Document file ID.",
                        "minimum": 1,
                    },
                },
                "required": ["file_id"],
                "additionalProperties": False,
            },
            risk_level="read",
            requires_confirmation=False,
            default_enabled=True,
            handler=lambda args: _json_dumps(get_document_metadata(_require_positive_int(args.get("file_id"), "file_id"))),
            summarize_result=_summarize_document_metadata,
        )
    )

    registry.register(
        ToolSpec(
            name="read_document_summary",
            display_name="读取文档摘要",
            description=(
                "Read a safe preview from one document by file_id. "
                "Use this when the user asks what a specific document is about."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "file_id": {
                        "type": "integer",
                        "description": "Document file ID.",
                        "minimum": 1,
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "Maximum characters to return in the preview.",
                        "minimum": 200,
                        "maximum": 8000,
                    },
                },
                "required": ["file_id"],
                "additionalProperties": False,
            },
            risk_level="read",
            requires_confirmation=False,
            default_enabled=True,
            handler=lambda args: _json_dumps(
                read_document_summary(
                    _require_positive_int(args.get("file_id"), "file_id"),
                    _coerce_top_k(args.get("max_chars"), default=2000, maximum=8000),
                )
            ),
            summarize_result=_summarize_document_summary,
        )
    )

    registry.register(
        ToolSpec(
            name="rebuild_file_index",
            display_name="重新索引文件",
            description=(
                "Request a user-confirmed rebuild of vector index chunks for one document by file_id. "
                "Use this when the user asks to rebuild, recreate, refresh, or reindex a document index and the target file_id is known. "
                "If the user says the first document/file, call list_documents first, then call this tool with that file_id. "
                "This tool creates the frontend confirmation card; do not ask for a separate plain-text confirmation when file_id is known. "
                "This changes index state and must not run until the user confirms it."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "file_id": {
                        "type": "integer",
                        "description": "Document file ID that needs index rebuild.",
                        "minimum": 1,
                    },
                    "reason": {
                        "type": "string",
                        "description": "Short reason shown to the user before confirmation.",
                    },
                },
                "required": ["file_id"],
                "additionalProperties": False,
            },
            risk_level="write",
            requires_confirmation=True,
            default_enabled=True,
            handler=lambda args: _json_dumps({"status": "not_executed", "reason": "requires_confirmation"}),
            summarize_result=_summarize_rebuild_file_index,
            confirmation_requester=request_tool_confirmation,
        )
    )

    if email_tool_available is not None and email_tool_available():
        registry.register(
            ToolSpec(
                name="send_email",
                display_name="发送邮件",
                description=(
                    "Request user confirmation to send a plain-text email through the configured SMTP account. "
                    "Use this when the user clearly asks to send an email and provides a recipient address plus a content goal. "
                    "Draft a concise subject and body from the conversation when the user did not provide exact wording. "
                    "Do not ask for a separate natural-language confirmation; this tool itself creates the user confirmation card. "
                    "Ask the user a follow-up question only when the recipient address or content goal is missing or ambiguous."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "to": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Recipient email addresses.",
                        },
                        "cc": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional CC recipient email addresses.",
                        },
                        "subject": {
                            "type": "string",
                            "description": "Email subject.",
                        },
                        "body": {
                            "type": "string",
                            "description": "Plain text email body.",
                        },
                    },
                    "required": ["to", "subject", "body"],
                    "additionalProperties": False,
                },
                risk_level="write",
                requires_confirmation=True,
                default_enabled=True,
                handler=lambda args: _json_dumps({"status": "not_executed", "reason": "requires_confirmation"}),
                summarize_result=_summarize_send_email,
                confirmation_requester=request_tool_confirmation,
            )
        )

    if include_web_search and web_search_available():
        registry.register(
            ToolSpec(
                name="search_web",
                display_name="搜索网页",
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
                risk_level="read",
                requires_confirmation=False,
                default_enabled=True,
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
                summarize_result=lambda raw: _summarize_json_list(raw, item_label="网页结果"),
            )
        )

    return registry


def _coerce_top_k(value: Any, *, default: int, maximum: int) -> int:
    try:
        top_k = int(value)
    except Exception:
        top_k = default
    return max(1, min(maximum, top_k))


def _coerce_optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        number = int(value)
    except Exception:
        return None
    return number if number > 0 else None


def _require_positive_int(value: Any, name: str) -> int:
    try:
        number = int(value)
    except Exception as exc:
        raise ValueError(f"{name} must be a positive integer.") from exc
    if number <= 0:
        raise ValueError(f"{name} must be a positive integer.")
    return number


def _summarize_document_listing(raw: str) -> str:
    payload = _load_json_payload(raw)
    if not isinstance(payload, dict):
        return "文档列表查询完成。"
    folder_count = int(payload.get("folder_count") or 0)
    file_count = int(payload.get("file_count") or 0)
    truncated = bool(payload.get("truncated"))
    suffix = "，结果已截断。" if truncated else "。"
    return f"找到 {folder_count} 个文件夹、{file_count} 个文件{suffix}"


def _summarize_document_metadata(raw: str) -> str:
    payload = _load_json_payload(raw)
    if not isinstance(payload, dict):
        return "文档元数据查询完成。"
    name = str(payload.get("name") or payload.get("display_path") or payload.get("file_id") or "文档")
    index_status = str(payload.get("index_status") or "unknown")
    parse_status = str(payload.get("parse_status") or "unknown")
    return f"{name}：解析状态 {parse_status}，索引状态 {index_status}。"


def _summarize_document_summary(raw: str) -> str:
    payload = _load_json_payload(raw)
    if not isinstance(payload, dict):
        return "文档摘要读取完成。"
    name = str(payload.get("name") or payload.get("display_path") or payload.get("file_id") or "文档")
    char_count = int(payload.get("char_count") or 0)
    truncated = bool(payload.get("truncated"))
    suffix = "，内容已截断。" if truncated else "。"
    return f"已读取 {name} 的预览内容，共 {char_count} 字符{suffix}"


def _summarize_rebuild_file_index(raw: str) -> str:
    payload = _load_json_payload(raw)
    if not isinstance(payload, dict):
        return "重新索引请求已创建，等待用户确认。"
    confirmation_id = str(payload.get("confirmation_id") or "")
    if confirmation_id:
        return f"重新索引请求已创建，等待用户确认：{confirmation_id}。"
    return "重新索引请求已创建，等待用户确认。"


def _summarize_send_email(raw: str) -> str:
    payload = _load_json_payload(raw)
    if not isinstance(payload, dict):
        return "邮件发送请求已创建，等待用户确认。"
    confirmation_id = str(payload.get("confirmation_id") or "")
    if confirmation_id:
        return f"邮件发送请求已创建，等待用户确认：{confirmation_id}。"
    return "邮件发送请求已创建，等待用户确认。"
