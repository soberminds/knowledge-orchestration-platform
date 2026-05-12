import type { CitationRef, CostEstimate, SourceHit, TokenUsage } from "../api";

export type WorkspaceTab = "chat" | "documents" | "index" | "search";

export interface NavTab {
  id: WorkspaceTab;
  label: string;
  subtitle: string;
}

export interface UiMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: number;
  sources: SourceHit[];
  citations: CitationRef[];
  model?: string;
  usage?: TokenUsage;
  costEstimate?: CostEstimate;
  streaming?: boolean;
  failed?: boolean;
}

export interface ChatSession {
  id: string;
  title: string;
  updatedAt: number;
  messages: UiMessage[];
}
