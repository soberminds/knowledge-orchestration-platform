"""API schema models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatHistoryItem(BaseModel):
    """A single history message."""

    role: Literal["system", "user", "assistant"] = "user"
    content: str = Field(min_length=1)


class ChatRequest(BaseModel):
    """Request payload for /api/chat and /api/chat/stream."""

    question: str = Field(min_length=1, max_length=4000)
    history: list[ChatHistoryItem] = Field(default_factory=list)
    top_k: int | None = Field(default=None, ge=1, le=20)
    model: str | None = Field(default=None, min_length=1, max_length=128)
    # Legacy flag kept for backward compatibility.
    web_search: bool = False
    # Prefer provider-native web search when model/provider supports it.
    native_web_search: bool = False
    # External web search via WEB_SEARCH_PROVIDER (tavily/serper).
    external_web_search: bool = False
    thinking_mode: Literal["quick", "deep"] = "quick"


class SourceHit(BaseModel):
    """A retrieval hit snippet."""

    source: str
    chunk_index: int
    page: int | None = None
    score: float | None = None
    preview: str


class CitationRef(BaseModel):
    """Citation reference used by [Sx] markers in answer text."""

    label: str
    source: str
    page: int | None = None
    chunk_indices: list[int] = Field(default_factory=list)
    score: float | None = None
    preview: str = ""


class ChatResponse(BaseModel):
    """Response payload for /api/chat."""

    answer: str
    rewritten_question: str
    sources: list[SourceHit]
    citations: list[CitationRef] = Field(default_factory=list)
    model: str | None = None
    usage: TokenUsage | None = None
    cost_estimate: CostEstimate | None = None


class ChatModelOption(BaseModel):
    """One chat model entry with availability metadata."""

    model: str
    provider: str
    supports_native_web_search: bool = False
    thinking_style: str | None = None
    deep_reasoning_effort: str | None = None
    deep_thinking_budget: int | None = None
    provider_configured: bool = True
    api_key_configured: bool = True
    base_url: str | None = None
    base_url_configured: bool = True
    available: bool = True
    unavailable_reason: str | None = None


class ChatOptionsResponse(BaseModel):
    """Dynamic options used by chat controls in frontend."""

    default_model: str
    models: list[str]
    model_options: list[ChatModelOption] = Field(default_factory=list)
    web_search_available: bool
    external_web_search_available: bool = False
    thinking_modes: list[Literal["quick", "deep"]] = Field(default_factory=lambda: ["quick", "deep"])


class TokenUsage(BaseModel):
    """Token usage for one model response."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class CostEstimate(BaseModel):
    """Estimated inference cost based on configured unit prices."""

    currency: str
    input_per_1m_tokens: float | None = None
    output_per_1m_tokens: float | None = None
    input_cost: float | None = None
    output_cost: float | None = None
    total_cost: float | None = None
    estimated: bool = True


class SearchRequest(BaseModel):
    """Request payload for /api/search."""

    query: str = Field(min_length=1, max_length=4000)
    top_k: int | None = Field(default=None, ge=1, le=20)


class SearchResponse(BaseModel):
    """Response payload for /api/search."""

    query: str
    hits: list[SourceHit]


class IngestResponse(BaseModel):
    """Response payload for ingest/upload/delete operations."""

    documents_loaded: int
    chunks_indexed: int
    source_files: list[str]


class DocumentInfo(BaseModel):
    """Document metadata for UI list."""

    path: str
    size_bytes: int
    modified_at: str
    extension: str


class FileEditTextResponse(BaseModel):
    """Text edit payload for editable source files."""

    path: str
    extension: str
    content: str
    encoding: str
    size_bytes: int
    editable: bool = True


class FileEditTextSaveRequest(BaseModel):
    """Save payload for text-edit operation."""

    path: str = Field(min_length=1)
    content: str = ""


class FileEditTextSaveResponse(BaseModel):
    """Result payload after saving editable text file."""

    path: str
    saved: bool = True
    extension: str
    encoding: str
    size_bytes: int
    modified_at: str


class OfficeEditorConfigResponse(BaseModel):
    """ONLYOFFICE editor bootstrapping payload."""

    path: str
    mode: Literal["edit", "view"] = "edit"
    document_server_url: str
    config: dict[str, Any]
    callback_token_ttl_sec: int
    auto_rebuild_index_on_save: bool = True


class OfficeHealthResponse(BaseModel):
    """ONLYOFFICE connectivity and runtime health snapshot."""

    checked_at: str
    configured: bool
    document_server_url: str | None = None
    document_server_internal_url: str | None = None
    public_backend_url: str
    index_update_mode: str
    auto_rebuild_index_on_save: bool
    jwt_enabled: bool
    jwt_secret_configured: bool
    callback_token_signing_ready: bool
    document_server_reachable: bool
    document_server_http_status: int | None = None
    command_service_ok: bool
    command_service_http_status: int | None = None
    document_server_version: str | None = None
    jwt_match: bool | None = None
    callback_reachable: bool
    callback_http_status: int | None = None
    notes: list[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    """Response payload for /api/health."""

    status: str
    collection_name: str
    indexed_chunks: int


ChatResponse.model_rebuild()
