import type { CitationRef, CostEstimate, SourceHit, TokenUsage } from "../api";

export type WorkspaceTab = "chat" | "documents" | "index" | "search";

export interface NavTab {
  id: WorkspaceTab;
  label: string;
  subtitle: string;
}

export interface UiMessage {
  id: string;
  backendMessageId?: number;
  seqNo?: number;
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
  backendConversationId?: number | null;
  title: string;
  updatedAt: number;
  messages: UiMessage[];
  messagesLoaded?: boolean;
  messagesLoading?: boolean;
  olderMessagesLoading?: boolean;
  hasMoreMessages?: boolean;
  oldestSeqNo?: number | null;
}
