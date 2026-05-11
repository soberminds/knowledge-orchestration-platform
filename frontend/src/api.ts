export interface HistoryItem {
  role: "system" | "user" | "assistant";
  content: string;
}

export interface SourceHit {
  source: string;
  chunk_index: number;
  page?: number | null;
  score?: number | null;
  preview: string;
}

export interface CitationRef {
  label: string;
  source: string;
  page?: number | null;
  chunk_indices: number[];
  score?: number | null;
  preview: string;
}

export interface ChatResponse {
  answer: string;
  rewritten_question: string;
  sources: SourceHit[];
  citations: CitationRef[];
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
  path: string;
  size_bytes: number;
  modified_at: string;
  extension: string;
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

interface ChatStreamDeltaEvent {
  type: "delta";
  delta: string;
}

interface ChatStreamDoneEvent {
  type: "done";
  answer: string;
  rewritten_question: string;
  sources: SourceHit[];
  citations: CitationRef[];
}

interface ChatStreamErrorEvent {
  type: "error";
  error: string;
}

type ChatStreamEvent = ChatStreamDeltaEvent | ChatStreamDoneEvent | ChatStreamErrorEvent;

export interface ChatStreamHandlers {
  onDelta?: (delta: string) => void | Promise<void>;
  onDone?: (payload: ChatStreamDoneEvent) => void | Promise<void>;
  onError?: (message: string) => void | Promise<void>;
}

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
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

export async function getHealth(): Promise<HealthResponse> {
  return requestJson<HealthResponse>("/api/health");
}

export async function listDocuments(): Promise<DocumentInfo[]> {
  return requestJson<DocumentInfo[]>("/api/documents");
}

export async function rebuildIndex(): Promise<IngestResponse> {
  return requestJson<IngestResponse>("/api/ingest", {
    method: "POST",
  });
}

export async function chat(payload: { question: string; history: HistoryItem[]; top_k?: number }): Promise<ChatResponse> {
  return requestJson<ChatResponse>("/api/chat", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function chatStream(
  payload: { question: string; history: HistoryItem[]; top_k?: number },
  handlers: ChatStreamHandlers = {},
): Promise<void> {
  const response = await fetch(`${API_BASE}/api/chat/stream`, {
    method: "POST",
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

export async function search(payload: { query: string; top_k?: number }): Promise<SearchResponse> {
  return requestJson<SearchResponse>("/api/search", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function uploadDocuments(files: FileList | File[]): Promise<IngestResponse> {
  const form = new FormData();
  Array.from(files).forEach((file) => form.append("files", file));

  const response = await fetch(`${API_BASE}/api/upload`, {
    method: "POST",
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

export function buildFileUrl(path: string): string {
  return `${API_BASE}/api/file?path=${encodeURIComponent(path)}`;
}

export function buildPreviewPdfUrl(path: string): string {
  return `${API_BASE}/api/file/preview-pdf?path=${encodeURIComponent(path)}`;
}

export async function getFilePageText(path: string, page?: number): Promise<FilePageTextResponse> {
  const params = new URLSearchParams();
  params.set("path", path);
  if (page !== undefined && page !== null) {
    params.set("page", String(page));
  }
  return requestJson<FilePageTextResponse>(`/api/file/page-text?${params.toString()}`);
}
