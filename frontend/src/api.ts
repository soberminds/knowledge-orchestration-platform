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

export interface ChatResponse {
  answer: string;
  rewritten_question: string;
  sources: SourceHit[];
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

