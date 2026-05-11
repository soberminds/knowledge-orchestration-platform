import type { SourceHit } from "../api";

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
  streaming?: boolean;
  failed?: boolean;
}

export interface ChatSession {
  id: string;
  title: string;
  updatedAt: number;
  messages: UiMessage[];
}
