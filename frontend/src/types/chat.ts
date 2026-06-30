import type { ChatMessagePart, CitationRef, CostEstimate, ModelDiagnostics, SourceHit, TokenUsage } from "../api";
import type { ToolCallDiagnostic } from "../api";

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
  messageParts?: ChatMessagePart[];
  reasoningParts?: string[];
  toolCalls?: ToolCallDiagnostic[];
  providerApi?: string | null;
  createdAt: number;
  sources: SourceHit[];
  citations: CitationRef[];
  model?: string;
  usage?: TokenUsage;
  costEstimate?: CostEstimate;
  modelDiagnostics?: ModelDiagnostics;
  streaming?: boolean;
  failed?: boolean;
}

export interface ChatSession {
  id: string;
  backendConversationId?: number | null;
  title: string;
  scopeType: "all" | "folder" | "kb" | "workspace";
  scopeId: number | null;
  workspaceKey: string | null;
  scopeName?: string | null;
  updatedAt: number;
  messages: UiMessage[];
  messagesLoaded?: boolean;
  messagesLoading?: boolean;
  olderMessagesLoading?: boolean;
  hasMoreMessages?: boolean;
  oldestSeqNo?: number | null;
}
