"""API schema models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatHistoryItem(BaseModel):
    """A single history message."""

    role: Literal["system", "user", "assistant"] = "user"
    content: str = Field(min_length=1)


class ChatMessagePart(BaseModel):
    """One multimodal message part used by chat requests."""

    type: Literal["text", "image_url", "file_ref"] = "text"
    text: str | None = Field(default=None, max_length=4000)
    image_url: str | None = Field(default=None, max_length=3_000_000)
    file_id: int | None = Field(default=None, ge=1)
    file_name: str | None = Field(default=None, max_length=255)
    mime_type: str | None = Field(default=None, max_length=128)


RunMode = Literal["chat", "rag", "agent"]
ThinkingMode = Literal["quick", "deep"]


class ChatRequest(BaseModel):
    """Request payload for /api/chat and /api/chat/stream."""

    question: str = Field(min_length=1, max_length=4000)
    message_parts: list[ChatMessagePart] = Field(default_factory=list, max_length=20)
    conversation_id: int | None = Field(default=None, ge=1)
    history: list[ChatHistoryItem] = Field(default_factory=list)
    top_k: int | None = Field(default=None, ge=1, le=20)
    model: str | None = Field(default=None, min_length=1, max_length=128)
    scope_type: Literal["all", "folder", "kb", "workspace"] = "all"
    scope_id: int | None = Field(default=None, ge=0)
    workspace_key: str | None = Field(default=None, max_length=128)
    # Legacy flag kept for backward compatibility.
    web_search: bool = False
    # Prefer provider-native web search when model/provider supports it.
    native_web_search: bool = False
    # External web search via WEB_SEARCH_PROVIDER (tavily/serper).
    external_web_search: bool = False
    thinking_mode: ThinkingMode = "quick"
    run_mode: RunMode = "rag"


class AuthRequest(BaseModel):
    """Login/register request payload."""

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)
    nickname: str | None = Field(default=None, max_length=128)


class UserProfile(BaseModel):
    """Authenticated or guest user profile."""

    id: int
    username: str
    nickname: str | None = None
    avatar_url: str | None = None
    user_type: str
    is_default: bool = False
    status: int = 1
    last_login_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    authenticated: bool = False
    is_guest: bool = False


class AuthResponse(BaseModel):
    """Authentication response."""

    user: UserProfile
    session_token: str


class SourceHit(BaseModel):
    """A retrieval hit snippet."""

    source: str
    chunk_index: int
    page: int | None = None
    score: float | None = None
    preview: str
    file_id: int | None = None
    folder_id: int | None = None
    display_name: str | None = None
    display_path: str | None = None
    folder_path: str | None = None


class CitationRef(BaseModel):
    """Citation reference used by [Sx] markers in answer text."""

    label: str
    source: str
    page: int | None = None
    chunk_indices: list[int] = Field(default_factory=list)
    score: float | None = None
    preview: str = ""
    file_id: int | None = None
    folder_id: int | None = None
    display_name: str | None = None
    display_path: str | None = None
    folder_path: str | None = None


class ModelDiagnostics(BaseModel):
    """Runtime model-call diagnostics returned with each assistant answer."""

    requested_model: str | None = None
    provider: str | None = None
    resolved_model: str | None = None
    native_web_search_used: bool = False
    external_web_search_used: bool = False
    thinking_mode: str | None = None
    run_mode: str | None = None
    provider_api: str | None = None
    option_fallback_used: bool = False
    warnings: list[str] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    capabilities: dict[str, Any] | None = None


class AgentToolConfirmationActionRequest(BaseModel):
    """Action payload for an Agent tool confirmation."""

    conversation_id: int | None = Field(default=None, ge=1)


class AgentToolConfirmationResponse(BaseModel):
    """Response payload for pending/confirmed Agent tool actions."""

    confirmation_id: str
    user_id: int | None = None
    tool_name: str
    display_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    message: str
    status: str
    created_at: str
    expires_at: str
    result: dict[str, Any] | None = None
    error: str | None = None
    assistant_followup: str | None = None
    confirmed_at: str | None = None
    cancelled_at: str | None = None


class ChatResponse(BaseModel):
    """Response payload for /api/chat."""

    answer: str
    conversation_id: int | None = None
    rewritten_question: str
    sources: list[SourceHit]
    citations: list[CitationRef] = Field(default_factory=list)
    model: str | None = None
    usage: TokenUsage | None = None
    cost_estimate: CostEstimate | None = None
    model_diagnostics: ModelDiagnostics | None = None


class ChatModelOption(BaseModel):
    """One chat model entry with availability metadata."""

    model: str
    provider: str
    supports_native_web_search: bool = False
    supports_tool_calling: bool = True
    supports_multimodal_input: bool = False
    supports_responses_api: bool = False
    supports_responses_streaming: bool = False
    thinking_style: str | None = None
    deep_reasoning_effort: str | None = None
    deep_thinking_budget: int | None = None
    provider_configured: bool = True
    api_key_configured: bool = True
    base_url: str | None = None
    base_url_configured: bool = True
    available: bool = True
    unavailable_reason: str | None = None


class KnowledgeBaseScopeOption(BaseModel):
    """One selectable knowledge base scope entry."""

    id: int
    label: str
    workspace_id: int | None = None
    workspace_key: str | None = None
    workspace_name: str | None = None
    folder_id: int | None = None


class WorkspaceScopeOption(BaseModel):
    """One selectable workspace scope entry."""

    id: int
    key: str
    label: str
    workspace_name: str | None = None


class ChatOptionsResponse(BaseModel):
    """Dynamic options used by chat controls in frontend."""

    default_model: str
    models: list[str]
    model_options: list[ChatModelOption] = Field(default_factory=list)
    knowledge_bases: list[KnowledgeBaseScopeOption] = Field(default_factory=list)
    workspaces: list[WorkspaceScopeOption] = Field(default_factory=list)
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


class ChatConversationSummary(BaseModel):
    """One persisted conversation shown in the recent-session list."""

    id: int
    title: str
    model: str | None = None
    workspace_key: str | None = None
    scope_type: Literal["all", "folder", "kb", "workspace"] = "all"
    scope_id: int = 0
    scope_name: str | None = None
    message_count: int = 0
    preview: str = ""
    last_message_at: str | None = None
    created_at: str
    updated_at: str


class ChatConversationListResponse(BaseModel):
    """Paged conversation list for the current local user."""

    items: list[ChatConversationSummary]
    page: int
    page_size: int
    has_more: bool = False


class ChatMessageRecord(BaseModel):
    """One persisted chat message record."""

    id: int
    conversation_id: int
    sender_user_id: int | None = None
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    message_parts: list[ChatMessagePart] = Field(default_factory=list)
    seq_no: int
    created_at: str
    model: str | None = None
    citations: list[CitationRef] = Field(default_factory=list)
    sources: list[SourceHit] = Field(default_factory=list)
    usage: TokenUsage | None = None
    model_diagnostics: ModelDiagnostics | None = None
    reasoning_parts: list[str] = Field(default_factory=list)


class ChatMessagePageResponse(BaseModel):
    """Paged messages for one conversation."""

    items: list[ChatMessageRecord]
    conversation_id: int
    limit: int
    has_more: bool = False
    oldest_seq_no: int | None = None
    newest_seq_no: int | None = None


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
    status: str = "success"
    message: str = ""


class DocumentInfo(BaseModel):
    """Document metadata for UI list."""

    id: int | None = None
    path: str
    display_path: str | None = None
    size_bytes: int
    modified_at: str
    extension: str
    is_directory: bool = False
    parent_id: int | None = None
    folder_id: int | None = None
    name: str | None = None
    source_type: str = "db"
    parse_status: str | None = None
    index_status: str | None = None
    parse_error: str | None = None
    last_indexed_at: str | None = None
    index_job_id: int | None = None
    index_job_file_id: int | None = None
    index_job_type: str | None = None
    index_stage: str | None = None
    index_progress: int | None = None
    index_total_chunks: int | None = None
    index_indexed_chunks: int | None = None
    index_error_message: str | None = None
    index_updated_at: str | None = None
    index_started_at: str | None = None
    index_finished_at: str | None = None


class IndexFileStatusCounts(BaseModel):
    """Status counters for the paged index monitor."""

    total: int = 0
    pending: int = 0
    queued: int = 0
    running: int = 0
    success: int = 0
    failed: int = 0


class IndexFileListResponse(BaseModel):
    """Paged file index monitor response."""

    items: list[DocumentInfo]
    total: int
    page: int
    page_size: int
    status_counts: IndexFileStatusCounts


class CreateDocumentFolderRequest(BaseModel):
    """Request payload for creating a document folder."""

    parent_path: str = ""
    parent_id: int | None = None
    name: str = Field(min_length=1, max_length=128)


class CreateDocumentFolderResponse(BaseModel):
    """Created document folder metadata."""

    path: str
    id: int | None = None
    parent_id: int | None = None
    created: bool = True


class DocumentMutationRequest(BaseModel):
    """Request payload for document rename or move operations."""

    path: str = ""
    file_id: int | None = Field(default=None, ge=1)
    parent_path: str = ""
    parent_id: int | None = None
    new_name: str | None = Field(default=None, max_length=255)


class DocumentMutationResponse(BaseModel):
    """Result payload for document rename or move operations."""

    previous_path: str
    path: str
    id: int | None = None
    file_id: int | None = None
    folder_id: int | None = None
    documents_loaded: int = 0
    chunks_indexed: int = 0
    source_files: list[str] = Field(default_factory=list)


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

    path: str = ""
    file_id: int | None = Field(default=None, ge=1)
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
    public_backend_internal_url: str | None = None
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


class OfficeCallbackStatusResponse(BaseModel):
    """Latest ONLYOFFICE callback-save status for one file."""

    path: str
    has_event: bool = False
    status: Literal["unknown", "success", "failed"] = "unknown"
    success: bool | None = None
    message: str = ""
    callback_status: int | None = None
    updated_at: str | None = None
    index_status: Literal["idle", "queued", "running", "success", "failed"] = "idle"
    index_message: str = ""
    index_updated_at: str | None = None


class HealthResponse(BaseModel):
    """Response payload for /api/health."""

    status: str
    collection_name: str
    indexed_chunks: int


ChatResponse.model_rebuild()
