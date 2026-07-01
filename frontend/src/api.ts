export interface HistoryItem {
  role: "system" | "user" | "assistant";
  content: string;
}

export type ChatMessagePartType = "text" | "image_url" | "file_ref";

export interface ChatMessagePart {
  type: ChatMessagePartType;
  text?: string | null;
  image_url?: string | null;
  file_id?: number | null;
  file_name?: string | null;
  mime_type?: string | null;
}

export interface UserProfile {
  id: number;
  username: string;
  nickname?: string | null;
  avatar_url?: string | null;
  user_type: string;
  is_default: boolean;
  status: number;
  last_login_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  authenticated: boolean;
  is_guest: boolean;
}

export interface AuthRequestPayload {
  username: string;
  password: string;
  nickname?: string | null;
}

export interface AuthResponse {
  user: UserProfile;
  session_token: string;
}

export interface SourceHit {
  source: string;
  chunk_index: number;
  page?: number | null;
  score?: number | null;
  preview: string;
  file_id?: number | null;
  folder_id?: number | null;
  display_name?: string | null;
  display_path?: string | null;
  folder_path?: string | null;
}

export interface CitationRef {
  label: string;
  source: string;
  page?: number | null;
  chunk_indices: number[];
  score?: number | null;
  preview: string;
  file_id?: number | null;
  folder_id?: number | null;
  display_name?: string | null;
  display_path?: string | null;
  folder_path?: string | null;
}

export interface ChatResponse {
  answer: string;
  conversation_id?: number | null;
  rewritten_question: string;
  sources: SourceHit[];
  citations: CitationRef[];
  model?: string | null;
  usage?: TokenUsage | null;
  cost_estimate?: CostEstimate | null;
  model_diagnostics?: ModelDiagnostics | null;
}

export interface TokenUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

export interface CostEstimate {
  currency: string;
  input_per_1m_tokens?: number | null;
  output_per_1m_tokens?: number | null;
  input_cost?: number | null;
  output_cost?: number | null;
  total_cost?: number | null;
  estimated?: boolean;
}

export interface ToolCallDiagnostic {
  id?: string | null;
  name?: string | null;
  display_name?: string | null;
  arguments?: Record<string, unknown> | string | null;
  status?: "success" | "error" | "pending_confirmation" | string | null;
  summary?: string | null;
  duration_ms?: number | null;
  risk_level?: "read" | "write" | "dangerous" | string | null;
  requires_confirmation?: boolean | null;
  default_enabled?: boolean | null;
  error?: string | null;
  confirmation_id?: string | null;
  confirmation_message?: string | null;
  confirmation_status?: string | null;
  result?: Record<string, unknown> | null;
}

export interface AgentToolConfirmationResponse {
  confirmation_id: string;
  user_id?: number | null;
  tool_name: string;
  display_name: string;
  arguments: Record<string, unknown>;
  message: string;
  status: string;
  created_at: string;
  expires_at: string;
  result?: Record<string, unknown> | null;
  error?: string | null;
  assistant_followup?: string | null;
  confirmed_at?: string | null;
  cancelled_at?: string | null;
}

export interface ModelDiagnostics {
  requested_model?: string | null;
  provider?: string | null;
  resolved_model?: string | null;
  native_web_search_used: boolean;
  external_web_search_used: boolean;
  thinking_mode?: string | null;
  run_mode?: string | null;
  provider_api?: string | null;
  option_fallback_used: boolean;
  warnings: string[];
  tool_calls?: ToolCallDiagnostic[];
  capabilities?: {
    supports_native_web_search?: boolean;
    supports_tool_calling?: boolean;
    supports_multimodal_input?: boolean;
    supports_responses_api?: boolean;
    supports_responses_streaming?: boolean;
    thinking_style?: string | null;
  } | null;
}

export type ThinkingMode = "quick" | "deep";
export type RunMode = "chat" | "rag" | "agent";

export interface ChatModelOption {
  model: string;
  provider: string;
  supports_native_web_search?: boolean;
  supports_tool_calling?: boolean;
  supports_multimodal_input?: boolean;
  supports_responses_api?: boolean;
  supports_responses_streaming?: boolean;
  thinking_style?: string | null;
  deep_reasoning_effort?: string | null;
  deep_thinking_budget?: number | null;
  provider_configured?: boolean;
  api_key_configured?: boolean;
  base_url?: string | null;
  base_url_configured?: boolean;
  available: boolean;
  unavailable_reason?: string | null;
}

export interface ChatOptionsResponse {
  default_model: string;
  models: string[];
  model_options: ChatModelOption[];
  knowledge_bases: KnowledgeBaseScopeOption[];
  workspaces: WorkspaceScopeOption[];
  web_search_available: boolean;
  external_web_search_available: boolean;
  thinking_modes: ThinkingMode[];
}

export interface KnowledgeBaseScopeOption {
  id: number;
  label: string;
  workspace_id?: number | null;
  workspace_key?: string | null;
  workspace_name?: string | null;
  folder_id?: number | null;
}

export interface WorkspaceScopeOption {
  id: number;
  key: string;
  label: string;
  workspace_name?: string | null;
}

export interface ChatConversationSummary {
  id: number;
  title: string;
  model?: string | null;
  workspace_key?: string | null;
  scope_type?: "all" | "folder" | "kb" | "workspace";
  scope_id?: number;
  scope_name?: string | null;
  message_count: number;
  preview: string;
  last_message_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ChatConversationListResponse {
  items: ChatConversationSummary[];
  page: number;
  page_size: number;
  has_more: boolean;
}

export interface ChatMessageRecord {
  id: number;
  conversation_id: number;
  sender_user_id?: number | null;
  role: "system" | "user" | "assistant" | "tool";
  content: string;
  message_parts?: ChatMessagePart[];
  seq_no: number;
  created_at: string;
  model?: string | null;
  citations: CitationRef[];
  sources: SourceHit[];
  usage?: TokenUsage | null;
  model_diagnostics?: ModelDiagnostics | null;
  reasoning_parts?: string[];
}

export interface ChatMessagePageResponse {
  items: ChatMessageRecord[];
  conversation_id: number;
  limit: number;
  has_more: boolean;
  oldest_seq_no?: number | null;
  newest_seq_no?: number | null;
}

export interface ChatRequestPayload {
  question: string;
  message_parts?: ChatMessagePart[];
  conversation_id?: number | null;
  history: HistoryItem[];
  top_k?: number;
  model?: string;
  scope_type?: "all" | "folder" | "kb" | "workspace";
  scope_id?: number | null;
  workspace_key?: string | null;
  web_search?: boolean;
  native_web_search?: boolean;
  external_web_search?: boolean;
  thinking_mode?: ThinkingMode;
  run_mode?: RunMode;
}

export interface SearchResponse {
  query: string;
  hits: SourceHit[];
}

export interface IngestResponse {
  documents_loaded: number;
  chunks_indexed: number;
  source_files: string[];
}

export interface DocumentInfo {
  id?: number | null;
  path: string;
  display_path?: string | null;
  size_bytes: number;
  modified_at: string;
  extension: string;
  is_directory?: boolean;
  parent_id?: number | null;
  folder_id?: number | null;
  name?: string | null;
  source_type?: string;
}

export interface CreateDocumentFolderResponse {
  path: string;
  id?: number | null;
  parent_id?: number | null;
  created: boolean;
}

export interface DocumentMutationResponse {
  previous_path: string;
  path: string;
  id?: number | null;
  file_id?: number | null;
  folder_id?: number | null;
  documents_loaded: number;
  chunks_indexed: number;
  source_files: string[];
}

export interface HealthResponse {
  status: string;
  collection_name: string;
  indexed_chunks: number;
}

export interface FilePageTextResponse {
  path: string;
  page: number;
  page_count?: number;
  page_label?: string;
  format?: "plain" | "markdown" | "table";
  text: string;
  table_headers?: string[];
  table_rows?: string[][];
  table_data_start_row?: number;
  table_header_row_number?: number;
  table_total_rows?: number;
  table_total_columns?: number;
  table_truncated?: boolean;
}

export interface FileEditableTextResponse {
  path: string;
  extension: string;
  content: string;
  encoding: string;
  size_bytes: number;
  editable: boolean;
}

export interface FileEditableTextSaveResponse {
  path: string;
  saved: boolean;
  extension: string;
  encoding: string;
  size_bytes: number;
  modified_at: string;
}

export interface OfficeEditorConfigResponse {
  path: string;
  mode: "edit" | "view";
  document_server_url: string;
  config: Record<string, unknown>;
  callback_token_ttl_sec: number;
  auto_rebuild_index_on_save: boolean;
}

export interface OfficeHealthResponse {
  checked_at: string;
  configured: boolean;
  document_server_url?: string | null;
  document_server_internal_url?: string | null;
  public_backend_url: string;
  public_backend_internal_url?: string | null;
  index_update_mode: string;
  auto_rebuild_index_on_save: boolean;
  jwt_enabled: boolean;
  jwt_secret_configured: boolean;
  callback_token_signing_ready: boolean;
  document_server_reachable: boolean;
  document_server_http_status?: number | null;
  command_service_ok: boolean;
  command_service_http_status?: number | null;
  document_server_version?: string | null;
  jwt_match?: boolean | null;
  callback_reachable: boolean;
  callback_http_status?: number | null;
  notes: string[];
}

export interface OfficeCallbackStatusResponse {
  path: string;
  has_event: boolean;
  status: "unknown" | "success" | "failed";
  success?: boolean | null;
  message: string;
  callback_status?: number | null;
  updated_at?: string | null;
  index_status: "idle" | "queued" | "running" | "success" | "failed";
  index_message: string;
  index_updated_at?: string | null;
}

interface ChatStreamDeltaEvent {
  type: "delta";
  delta: string;
}

export interface ChatStreamDoneEvent {
  type: "done";
  answer: string;
  conversation_id?: number | null;
  rewritten_question: string;
  sources: SourceHit[];
  citations: CitationRef[];
  model?: string | null;
  usage?: TokenUsage | null;
  cost_estimate?: CostEstimate | null;
  model_diagnostics?: ModelDiagnostics | null;
  reasoning_parts?: string[];
}

interface ChatStreamErrorEvent {
  type: "error";
  error: string;
}

export interface ChatStreamReasoningDeltaEvent {
  type: "reasoning_delta";
  delta: string;
}

export interface ChatStreamToolCallDeltaEvent {
  type: "tool_call_delta";
  tool_call_delta: Record<string, unknown>;
}

export interface ChatStreamUsageEvent {
  type: "usage";
  usage?: TokenUsage | null;
}

export interface ChatStreamDiagnosticsEvent {
  type: "diagnostics";
  model_diagnostics?: ModelDiagnostics | null;
}

type ChatStreamEvent =
  | ChatStreamDeltaEvent
  | ChatStreamDoneEvent
  | ChatStreamErrorEvent
  | ChatStreamReasoningDeltaEvent
  | ChatStreamToolCallDeltaEvent
  | ChatStreamUsageEvent
  | ChatStreamDiagnosticsEvent;

export interface ChatStreamHandlers {
  onDelta?: (delta: string) => void | Promise<void>;
  onReasoningDelta?: (delta: string) => void | Promise<void>;
  onToolCallDelta?: (payload: Record<string, unknown>) => void | Promise<void>;
  onUsage?: (usage?: TokenUsage | null) => void | Promise<void>;
  onDiagnostics?: (diagnostics?: ModelDiagnostics | null) => void | Promise<void>;
  onDone?: (payload: ChatStreamDoneEvent) => void | Promise<void>;
  onError?: (message: string) => void | Promise<void>;
}

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
  });

  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;

  if (!response.ok) {
    const message = payload?.detail ?? payload?.message ?? response.statusText;
    throw new Error(message || "Request failed");
  }

  return payload as T;
}

function parseSseChunks(rawEvent: string): ChatStreamEvent[] {
  const lines = rawEvent.split(/\r?\n/);
  const dataLines = lines
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trimStart());

  if (!dataLines.length) {
    return [];
  }

  const payload = dataLines.join("\n").trim();
  if (!payload) {
    return [];
  }

  try {
    const parsed = JSON.parse(payload) as ChatStreamEvent;
    return [parsed];
  } catch {
    return [];
  }
}

function findSseBoundary(buffer: string): { index: number; length: number } | null {
  const crlfBoundary = buffer.indexOf("\r\n\r\n");
  const lfBoundary = buffer.indexOf("\n\n");

  if (crlfBoundary === -1 && lfBoundary === -1) {
    return null;
  }
  if (crlfBoundary !== -1 && (lfBoundary === -1 || crlfBoundary < lfBoundary)) {
    return { index: crlfBoundary, length: 4 };
  }
  return { index: lfBoundary, length: 2 };
}

function appendFileIdentity(params: URLSearchParams, path: string, fileId?: number | null) {
  if (fileId !== undefined && fileId !== null) {
    params.set("file_id", String(fileId));
    return;
  }
  if (path) {
    params.set("path", path);
  }
}

export async function getHealth(): Promise<HealthResponse> {
  return requestJson<HealthResponse>("/api/health");
}

export async function listDocuments(): Promise<DocumentInfo[]> {
  return requestJson<DocumentInfo[]>("/api/documents");
}

export async function deleteDocument(path: string): Promise<IngestResponse> {
  return requestJson<IngestResponse>(`/api/documents?path=${encodeURIComponent(path)}`, {
    method: "DELETE",
  });
}

export async function deleteDocumentById(fileId: number): Promise<IngestResponse> {
  return requestJson<IngestResponse>(`/api/documents?file_id=${encodeURIComponent(String(fileId))}`, {
    method: "DELETE",
  });
}

export async function deleteDocumentFolder(path: string): Promise<IngestResponse> {
  return requestJson<IngestResponse>(`/api/document-folders?path=${encodeURIComponent(path)}`, {
    method: "DELETE",
  });
}

export async function createDocumentFolder(
  parentPath: string,
  name: string,
  parentId?: number | null,
): Promise<CreateDocumentFolderResponse> {
  return requestJson<CreateDocumentFolderResponse>("/api/document-folders", {
    method: "POST",
    body: JSON.stringify({
      parent_path: parentPath,
      parent_id: parentId ?? null,
      name,
    }),
  });
}

export async function renameDocument(path: string, newName: string): Promise<DocumentMutationResponse> {
  return requestJson<DocumentMutationResponse>("/api/documents/rename", {
    method: "PUT",
    body: JSON.stringify({ path, new_name: newName }),
  });
}

export async function renameDocumentById(
  fileId: number,
  newName: string,
): Promise<DocumentMutationResponse> {
  return requestJson<DocumentMutationResponse>("/api/documents/rename", {
    method: "PUT",
    body: JSON.stringify({ file_id: fileId, new_name: newName }),
  });
}

export async function moveDocument(
  path: string,
  parentPath: string,
  parentId?: number | null,
): Promise<DocumentMutationResponse> {
  return requestJson<DocumentMutationResponse>("/api/documents/move", {
    method: "PUT",
    body: JSON.stringify({
      path,
      parent_path: parentPath,
      parent_id: parentId ?? null,
    }),
  });
}

export async function moveDocumentById(
  fileId: number,
  parentPath: string,
  parentId?: number | null,
): Promise<DocumentMutationResponse> {
  return requestJson<DocumentMutationResponse>("/api/documents/move", {
    method: "PUT",
    body: JSON.stringify({
      file_id: fileId,
      parent_path: parentPath,
      parent_id: parentId ?? null,
    }),
  });
}

export async function renameDocumentFolder(path: string, newName: string): Promise<DocumentMutationResponse> {
  return requestJson<DocumentMutationResponse>("/api/document-folders/rename", {
    method: "PUT",
    body: JSON.stringify({ path, new_name: newName }),
  });
}

export async function moveDocumentFolder(
  path: string,
  parentPath: string,
  parentId?: number | null,
): Promise<DocumentMutationResponse> {
  return requestJson<DocumentMutationResponse>("/api/document-folders/move", {
    method: "PUT",
    body: JSON.stringify({
      path,
      parent_path: parentPath,
      parent_id: parentId ?? null,
    }),
  });
}

export async function rebuildIndex(): Promise<IngestResponse> {
  return requestJson<IngestResponse>("/api/ingest", {
    method: "POST",
  });
}

export async function chat(payload: ChatRequestPayload): Promise<ChatResponse> {
  return requestJson<ChatResponse>("/api/chat", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function chatStream(
  payload: ChatRequestPayload,
  handlers: ChatStreamHandlers = {},
): Promise<void> {
  const response = await fetch(`${API_BASE}/api/chat/stream`, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const text = await response.text();
    let message = response.statusText;
    if (text) {
      try {
        const payloadObj = JSON.parse(text);
        message = payloadObj?.detail ?? payloadObj?.message ?? message;
      } catch {
        message = text;
      }
    }
    throw new Error(message || "Stream request failed");
  }

  if (!response.body) {
    throw new Error("Streaming is not supported by the current browser.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let receivedDone = false;

  async function handleEvents(events: ChatStreamEvent[]) {
    for (const event of events) {
      if (event.type === "delta") {
        await handlers.onDelta?.(event.delta);
        continue;
      }
      if (event.type === "done") {
        receivedDone = true;
        await handlers.onDone?.(event);
        continue;
      }
      if (event.type === "reasoning_delta") {
        await handlers.onReasoningDelta?.(event.delta);
        continue;
      }
      if (event.type === "tool_call_delta") {
        await handlers.onToolCallDelta?.(event.tool_call_delta);
        continue;
      }
      if (event.type === "usage") {
        await handlers.onUsage?.(event.usage);
        continue;
      }
      if (event.type === "diagnostics") {
        await handlers.onDiagnostics?.(event.model_diagnostics);
        continue;
      }
      await handlers.onError?.(event.error);
      throw new Error(event.error);
    }
  }

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });

    let boundary = findSseBoundary(buffer);
    while (boundary) {
      const rawEvent = buffer.slice(0, boundary.index);
      buffer = buffer.slice(boundary.index + boundary.length);

      const events = parseSseChunks(rawEvent);
      await handleEvents(events);
      boundary = findSseBoundary(buffer);
    }
  }

  // Parse any trailing complete payload without separator (defensive).
  const trailingEvents = parseSseChunks(buffer);
  if (trailingEvents.length) {
    await handleEvents(trailingEvents);
  }

  if (!receivedDone) {
    throw new Error("Stream ended unexpectedly without done event.");
  }
}

export async function getChatOptions(): Promise<ChatOptionsResponse> {
  return requestJson<ChatOptionsResponse>("/api/chat/options");
}

export async function listChatConversations(
  params: { page?: number; page_size?: number } = {},
): Promise<ChatConversationListResponse> {
  const query = new URLSearchParams();
  if (params.page !== undefined) {
    query.set("page", String(params.page));
  }
  if (params.page_size !== undefined) {
    query.set("page_size", String(params.page_size));
  }
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return requestJson<ChatConversationListResponse>(`/api/chat/conversations${suffix}`);
}

export async function listChatMessages(
  conversationId: number,
  params: { limit?: number; before_seq_no?: number | null } = {},
): Promise<ChatMessagePageResponse> {
  const query = new URLSearchParams();
  if (params.limit !== undefined) {
    query.set("limit", String(params.limit));
  }
  if (params.before_seq_no !== undefined && params.before_seq_no !== null) {
    query.set("before_seq_no", String(params.before_seq_no));
  }
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return requestJson<ChatMessagePageResponse>(
    `/api/chat/conversations/${conversationId}/messages${suffix}`,
  );
}

export async function search(payload: { query: string; top_k?: number }): Promise<SearchResponse> {
  return requestJson<SearchResponse>("/api/search", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function uploadDocuments(
  files: FileList | File[],
  folderPath = "",
  parentId?: number | null,
): Promise<IngestResponse> {
  const form = new FormData();
  Array.from(files).forEach((file) => form.append("files", file));
  if (folderPath) {
    form.append("folder_path", folderPath);
  }
  if (parentId !== undefined && parentId !== null) {
    form.append("parent_id", String(parentId));
  }

  const response = await fetch(`${API_BASE}/api/upload`, {
    method: "POST",
    credentials: "include",
    body: form,
  });

  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;

  if (!response.ok) {
    const message = payload?.detail ?? payload?.message ?? response.statusText;
    throw new Error(message || "Upload failed");
  }

  return payload as IngestResponse;
}

export function buildFileUrl(path: string, fileId?: number | null): string {
  const params = new URLSearchParams();
  appendFileIdentity(params, path, fileId);
  return `${API_BASE}/api/file?${params.toString()}`;
}

export function buildPreviewPdfUrl(path: string, fileId?: number | null): string {
  const params = new URLSearchParams();
  appendFileIdentity(params, path, fileId);
  return `${API_BASE}/api/file/preview-pdf?${params.toString()}`;
}

export async function getFilePageText(
  path: string,
  page?: number,
  fileId?: number | null,
): Promise<FilePageTextResponse> {
  const params = new URLSearchParams();
  appendFileIdentity(params, path, fileId);
  if (page !== undefined && page !== null) {
    params.set("page", String(page));
  }
  return requestJson<FilePageTextResponse>(`/api/file/page-text?${params.toString()}`);
}

export async function getFileEditableText(path: string, fileId?: number | null): Promise<FileEditableTextResponse> {
  const params = new URLSearchParams();
  appendFileIdentity(params, path, fileId);
  return requestJson<FileEditableTextResponse>(`/api/file/edit-text?${params.toString()}`);
}

export async function saveFileEditableText(
  path: string,
  content: string,
  fileId?: number | null,
): Promise<FileEditableTextSaveResponse> {
  const payload = fileId !== undefined && fileId !== null ? { file_id: fileId, content } : { path, content };
  return requestJson<FileEditableTextSaveResponse>("/api/file/edit-text", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function getOfficeEditorConfig(
  path: string,
  options: { mode?: "edit" | "view"; lang?: string; fileId?: number | null } = {},
): Promise<OfficeEditorConfigResponse> {
  const params = new URLSearchParams();
  appendFileIdentity(params, path, options.fileId ?? null);
  if (options.mode) {
    params.set("mode", options.mode);
  }
  if (options.lang) {
    params.set("lang", options.lang);
  }
  return requestJson<OfficeEditorConfigResponse>(`/api/office/editor-config?${params.toString()}`);
}

export async function getOfficeHealth(): Promise<OfficeHealthResponse> {
  return requestJson<OfficeHealthResponse>("/api/office/health");
}

export async function getOfficeCallbackStatus(path: string, fileId?: number | null): Promise<OfficeCallbackStatusResponse> {
  const params = new URLSearchParams();
  appendFileIdentity(params, path, fileId);
  return requestJson<OfficeCallbackStatusResponse>(`/api/office/callback-status?${params.toString()}`);
}

export async function confirmAgentToolConfirmation(
  confirmationId: string,
  payload: { conversation_id?: number | null } = {},
): Promise<AgentToolConfirmationResponse> {
  return requestJson<AgentToolConfirmationResponse>(
    `/api/agent/tool-confirmations/${encodeURIComponent(confirmationId)}/confirm`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export async function cancelAgentToolConfirmation(
  confirmationId: string,
  payload: { conversation_id?: number | null } = {},
): Promise<AgentToolConfirmationResponse> {
  return requestJson<AgentToolConfirmationResponse>(
    `/api/agent/tool-confirmations/${encodeURIComponent(confirmationId)}/cancel`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export async function getCurrentUser(): Promise<UserProfile> {
  return requestJson<UserProfile>("/api/auth/me");
}

export async function login(payload: AuthRequestPayload): Promise<AuthResponse> {
  return requestJson<AuthResponse>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function register(payload: AuthRequestPayload): Promise<AuthResponse> {
  return requestJson<AuthResponse>("/api/auth/register", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function logout(): Promise<{ ok: boolean }> {
  return requestJson<{ ok: boolean }>("/api/auth/logout", {
    method: "POST",
  });
}
