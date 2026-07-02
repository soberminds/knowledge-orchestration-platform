import type { Ref } from "vue";
import { computed, nextTick, reactive, ref } from "vue";
import { useI18n } from "./useI18n";
import {
  chatStream,
  cancelAgentToolConfirmation,
  confirmAgentToolConfirmation,
  getChatOptions,
  listChatConversations,
  listChatMessages,
  type AgentToolConfirmationResponse,
  type ChatOptionsResponse,
  type ChatConversationSummary,
  type ChatMessageRecord,
  type ChatMessagePart,
  type ChatModelOption,
  type KnowledgeBaseScopeOption,
  type ModelDiagnostics,
  type ToolCallDiagnostic,
  type ChatStreamDoneEvent,
  type HistoryItem,
  type WorkspaceScopeOption,
  type ThinkingMode,
  type RunMode,
} from "../api";
import type { ChatSession, UiMessage } from "../types/chat";

const CONVERSATION_PAGE_SIZE = 20;
const MESSAGE_PAGE_SIZE = 30;
type ChatScopeType = "all" | "folder" | "kb" | "workspace";
type UiToolCall = NonNullable<UiMessage["toolCalls"]>[number];
type ToolConfirmationUiPayload = { messageId: string; confirmationId: string };

function createId() {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

function buildSessionTitle(text: string, fallbackTitle: string) {
  const normalized = text.trim().replace(/\s+/g, " ");
  if (!normalized) {
    return fallbackTitle;
  }
  return normalized.length > 24 ? `${normalized.slice(0, 24)}...` : normalized;
}

function createWelcomeMessage(welcomeText: string): UiMessage {
  return {
    id: createId(),
    role: "assistant",
    createdAt: Date.now(),
    content: welcomeText,
    sources: [],
    citations: [],
  };
}

function createSession(
  seedTitle: string,
  welcomeText: string,
  scope: { scopeType?: ChatScopeType; scopeId?: number | null; workspaceKey?: string | null; scopeName?: string | null } = {},
): ChatSession {
  return {
    id: createId(),
    backendConversationId: null,
    title: seedTitle,
    scopeType: scope.scopeType ?? "all",
    scopeId: scope.scopeId ?? null,
    workspaceKey: scope.workspaceKey ?? null,
    scopeName: scope.scopeName ?? null,
    updatedAt: Date.now(),
    messages: [createWelcomeMessage(welcomeText)],
    messagesLoaded: true,
    messagesLoading: false,
    olderMessagesLoading: false,
    hasMoreMessages: false,
    oldestSeqNo: null,
  };
}

function parseTimestamp(value?: string | null) {
  const timestamp = value ? Date.parse(value) : NaN;
  return Number.isFinite(timestamp) ? timestamp : Date.now();
}

function parseToolArguments(value: unknown): Record<string, unknown> | undefined {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  if (typeof value !== "string" || !value.trim()) {
    return undefined;
  }
  try {
    const parsed = JSON.parse(value) as unknown;
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>;
    }
  } catch {
    return undefined;
  }
  return undefined;
}

function normalizeToolCall(payload: Record<string, unknown> | ToolCallDiagnostic): UiToolCall | null {
  const payloadRecord = payload as Record<string, unknown>;
  const functionPayload =
    payloadRecord.function && typeof payloadRecord.function === "object" && !Array.isArray(payloadRecord.function)
      ? (payloadRecord.function as Record<string, unknown>)
      : {};
  const id = String(payloadRecord.id ?? "").trim();
  const name = String(payloadRecord.name ?? functionPayload.name ?? "").trim();
  const args = parseToolArguments(payloadRecord.arguments ?? functionPayload.arguments);
  const displayName = String(payloadRecord.display_name ?? "").trim();
  const status = String(payloadRecord.status ?? "").trim();
  const summary = String(payloadRecord.summary ?? "").trim();
  const riskLevel = String(payloadRecord.risk_level ?? "").trim();
  const error = String(payloadRecord.error ?? "").trim();
  const confirmationId = String(payloadRecord.confirmation_id ?? "").trim();
  const confirmationMessage = String(payloadRecord.confirmation_message ?? "").trim();
  const confirmationStatus = String(payloadRecord.confirmation_status ?? "").trim();
  const assistantFollowup = String(payloadRecord.assistant_followup ?? "").trim();
  const confirmedAt = String(payloadRecord.confirmed_at ?? "").trim();
  const cancelledAt = String(payloadRecord.cancelled_at ?? "").trim();
  const result =
    payloadRecord.result && typeof payloadRecord.result === "object" && !Array.isArray(payloadRecord.result)
      ? (payloadRecord.result as Record<string, unknown>)
      : null;
  const durationMs =
    typeof payloadRecord.duration_ms === "number" && Number.isFinite(payloadRecord.duration_ms)
      ? payloadRecord.duration_ms
      : null;

  if (!id && !name) {
    return null;
  }
  return {
    ...(id ? { id } : {}),
    ...(name ? { name } : {}),
    ...(displayName ? { display_name: displayName } : {}),
    ...(args ? { arguments: args } : {}),
    ...(status ? { status } : {}),
    ...(summary ? { summary } : {}),
    ...(durationMs !== null ? { duration_ms: durationMs } : {}),
    ...(riskLevel ? { risk_level: riskLevel } : {}),
    ...(typeof payloadRecord.requires_confirmation === "boolean" ? { requires_confirmation: payloadRecord.requires_confirmation } : {}),
    ...(typeof payloadRecord.default_enabled === "boolean" ? { default_enabled: payloadRecord.default_enabled } : {}),
    ...(error ? { error } : {}),
    ...(confirmationId ? { confirmation_id: confirmationId } : {}),
    ...(confirmationMessage ? { confirmation_message: confirmationMessage } : {}),
    ...(confirmationStatus ? { confirmation_status: confirmationStatus } : {}),
    ...(assistantFollowup ? { assistant_followup: assistantFollowup } : {}),
    ...(confirmedAt ? { confirmed_at: confirmedAt } : {}),
    ...(cancelledAt ? { cancelled_at: cancelledAt } : {}),
    ...(result ? { result } : {}),
  };
}

function toolCallsFromDiagnostics(diagnostics?: ModelDiagnostics | null): UiToolCall[] {
  return (diagnostics?.tool_calls ?? [])
    .map((item) => normalizeToolCall(item))
    .filter((item): item is UiToolCall => item !== null);
}

function toolCallKey(toolCall: UiToolCall) {
  return String(toolCall.confirmation_id || toolCall.id || `${toolCall.name || ""}:${JSON.stringify(toolCall.arguments ?? {})}`);
}

function isTerminalConfirmationStatus(status?: string | null) {
  return ["running", "confirmed", "cancelled", "failed"].includes(String(status || ""));
}

function mergeToolCallWithLocalState(incoming: UiToolCall, existing?: UiToolCall): UiToolCall {
  if (!existing) {
    return incoming;
  }
  const existingConfirmationStatus = String(existing.confirmation_status || "");
  if (!isTerminalConfirmationStatus(existingConfirmationStatus)) {
    return {
      ...existing,
      ...incoming,
      result: incoming.result ?? existing.result,
      error: incoming.error ?? existing.error,
      confirmation_status: incoming.confirmation_status ?? existing.confirmation_status,
    };
  }
  return {
    ...existing,
    ...incoming,
    status: existing.status ?? incoming.status,
    confirmation_status: existing.confirmation_status,
    summary: existing.summary || incoming.summary,
    error: existing.error ?? incoming.error,
    result: existing.result ?? incoming.result,
    assistant_followup: existing.assistant_followup ?? incoming.assistant_followup,
    confirmed_at: existing.confirmed_at ?? incoming.confirmed_at,
    cancelled_at: existing.cancelled_at ?? incoming.cancelled_at,
  };
}

function mergeToolCallsWithLocalState(existingCalls: UiToolCall[] | undefined, incomingCalls: UiToolCall[]) {
  if (!existingCalls?.length) {
    return incomingCalls;
  }
  const existingByKey = new Map(existingCalls.map((toolCall) => [toolCallKey(toolCall), toolCall]));
  const merged = incomingCalls.map((toolCall) => mergeToolCallWithLocalState(toolCall, existingByKey.get(toolCallKey(toolCall))));
  const incomingKeys = new Set(incomingCalls.map((toolCall) => toolCallKey(toolCall)));
  const localOnly = existingCalls.filter(
    (toolCall) => !incomingKeys.has(toolCallKey(toolCall)) && isTerminalConfirmationStatus(toolCall.confirmation_status),
  );
  return [...merged, ...localOnly];
}

function confirmationSuccessSummary(toolCall: UiToolCall, result?: Record<string, unknown> | null) {
  const toolName = String(toolCall.name || "");
  if (toolName === "rebuild_file_index" && result) {
    const displayPath = String(result.display_path || result.path || result.file_id || "文件");
    const chunksIndexed = Number(result.chunks_indexed);
    const chunkLabel = Number.isFinite(chunksIndexed) ? `，写入 ${chunksIndexed} 个切片` : "";
    return `已重新索引 ${displayPath}${chunkLabel}。`;
  }
  if (toolName === "send_email" && result) {
    const subject = String(result.subject || "邮件");
    return `邮件已发送：${subject}。`;
  }
  return "已确认并执行。";
}

function formatFollowupRecipients(value: unknown) {
  if (Array.isArray(value)) {
    return value.map((item) => String(item || "").trim()).filter(Boolean).join("、");
  }
  return String(value || "").trim();
}

function buildToolConfirmationFollowup(toolCall: UiToolCall, response: AgentToolConfirmationResponse) {
  const explicit = String(response.assistant_followup || "").trim();
  if (explicit) {
    return explicit;
  }
  const status = String(response.status || "");
  const toolName = String(response.tool_name || toolCall.name || "");
  const result = response.result ?? toolCall.result ?? null;
  const args = parseToolArguments(response.arguments) ?? parseToolArguments(toolCall.arguments) ?? {};

  if (status === "confirmed") {
    if (toolName === "send_email") {
      const recipients = formatFollowupRecipients(result?.to ?? args.to);
      const subject = String(result?.subject ?? args.subject ?? "邮件").trim();
      const sentAt = String(result?.sent_at ?? "").trim();
      const sentAtText = sentAt ? `发送时间：${sentAt}。` : "";
      return `邮件已发送成功。收件人：${recipients || "未记录"}；主题：${subject || "邮件"}。${sentAtText}`.trim();
    }
    if (toolName === "rebuild_file_index") {
      const displayPath = String(result?.display_path || result?.path || result?.file_id || args.display_path || args.file_id || "文件");
      const chunksIndexed = Number(result?.chunks_indexed);
      const chunkLabel = Number.isFinite(chunksIndexed) ? `，写入 ${chunksIndexed} 个切片` : "";
      return `文件索引已重建完成：${displayPath}${chunkLabel}。`;
    }
    return "操作已确认并执行完成。";
  }
  if (status === "cancelled") {
    return "已取消该待确认操作，未执行工具。";
  }
  if (status === "failed" || response.error) {
    return `待确认操作执行失败：${response.error || "请查看工具结果详情。"}`;
  }
  return "";
}

function applyDiagnosticsToMessage(target: UiMessage, diagnostics?: ModelDiagnostics | null) {
  if (!diagnostics) {
    return;
  }
  target.modelDiagnostics = diagnostics;
  target.providerApi = diagnostics.provider_api ?? target.providerApi ?? null;
  const toolCalls = toolCallsFromDiagnostics(diagnostics);
  if (toolCalls.length) {
    target.toolCalls = mergeToolCallsWithLocalState(target.toolCalls, toolCalls);
  }
}

function applyToolConfirmationResponse(toolCall: UiToolCall, response: AgentToolConfirmationResponse): UiToolCall {
  const status = String(response.status || "");
  const isConfirmed = status === "confirmed";
  const isCancelled = status === "cancelled";
  const isFailed = status === "failed" || Boolean(response.error);
  const result = response.result ?? toolCall.result ?? null;
  const summary = isConfirmed
    ? confirmationSuccessSummary(toolCall, result)
    : isCancelled
      ? "已取消执行。"
      : isFailed
        ? "确认执行失败。"
        : toolCall.summary;

  const assistantFollowup = buildToolConfirmationFollowup(toolCall, response) || toolCall.assistant_followup || null;

  return {
    ...toolCall,
    status: isConfirmed ? "success" : isFailed ? "error" : isCancelled ? "cancelled" : toolCall.status,
    confirmation_status: status || toolCall.confirmation_status || null,
    summary,
    error: response.error ?? null,
    result,
    assistant_followup: assistantFollowup,
    confirmed_at: response.confirmed_at ?? toolCall.confirmed_at ?? null,
    cancelled_at: response.cancelled_at ?? toolCall.cancelled_at ?? null,
  };
}

function appendAssistantFollowup(content: string, followup?: string | null) {
  const text = String(followup || "").trim();
  if (!text) {
    return content;
  }
  if (content.includes(text)) {
    return content;
  }
  const separator = content.trim() ? "\n\n" : "";
  return `${content.trimEnd()}${separator}${text}`;
}

function collectToolConfirmationFollowups(message: UiMessage) {
  return (message.toolCalls ?? [])
    .map((toolCall) => String(toolCall.assistant_followup || "").trim())
    .filter((text, index, list) => Boolean(text) && list.indexOf(text) === index);
}

function appendAssistantFollowups(content: string, followups: string[]) {
  return followups.reduce((nextContent, followup) => appendAssistantFollowup(nextContent, followup), content);
}

function markToolConfirmationRunning(toolCall: UiToolCall): UiToolCall {
  return {
    ...toolCall,
    confirmation_status: "running",
    summary: toolCall.summary || "等待确认的工具操作正在执行。",
    error: null,
  };
}

function markToolConfirmationFailed(toolCall: UiToolCall, message: string): UiToolCall {
  return {
    ...toolCall,
    status: "error",
    confirmation_status: "failed",
    summary: "确认操作失败。",
    error: message,
  };
}

function conversationToSession(item: ChatConversationSummary): ChatSession {
  return {
    id: `db-${item.id}`,
    backendConversationId: item.id,
    title: item.title || item.preview || "Chat",
    scopeType: item.scope_type ?? "all",
    scopeId: item.scope_id ?? null,
    workspaceKey: item.workspace_key ?? null,
    scopeName: item.scope_name ?? null,
    updatedAt: parseTimestamp(item.last_message_at ?? item.updated_at ?? item.created_at),
    messages: [],
    messagesLoaded: false,
    messagesLoading: false,
    olderMessagesLoading: false,
    hasMoreMessages: item.message_count > 0,
    oldestSeqNo: null,
  };
}

function messageRecordToUiMessage(record: ChatMessageRecord): UiMessage | null {
  if (record.role !== "user" && record.role !== "assistant") {
    return null;
  }
  return {
    id: `db-msg-${record.id}`,
    backendMessageId: record.id,
    seqNo: record.seq_no,
    role: record.role,
    content: record.content,
    createdAt: parseTimestamp(record.created_at),
    sources: record.sources ?? [],
    citations: record.citations ?? [],
    messageParts: record.message_parts ?? [],
    model: record.model ?? undefined,
    usage: record.usage ?? undefined,
    modelDiagnostics: record.model_diagnostics ?? undefined,
    providerApi: record.model_diagnostics?.provider_api ?? null,
    toolCalls: toolCallsFromDiagnostics(record.model_diagnostics),
    reasoningParts: record.reasoning_parts ?? [],
  };
}

function toHistoryPayload(messages: UiMessage[]): HistoryItem[] {
  return messages
    .filter((item) => item.content.trim() && !item.streaming)
    .map((item) => ({
      role: item.role,
      content: item.content,
    }))
    .slice(-12);
}

function delay(ms: number) {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

export function useChatWorkspace(topK: Ref<number>) {
  const { t } = useI18n();
  const sessions = ref<ChatSession[]>([]);
  const activeSessionId = ref("");
  const loading = ref(false);
  const composer = ref("");
  const messageParts = ref<ChatMessagePart[]>([]);
  const errorMessage = ref("");
  const messageViewport = ref<HTMLElement | null>(null);
  const availableModels = ref<string[]>([]);
  const modelOptions = ref<ChatModelOption[]>([]);
  const knowledgeBaseOptions = ref<KnowledgeBaseScopeOption[]>([]);
  const workspaceOptions = ref<WorkspaceScopeOption[]>([]);
  const selectedModel = ref("");
  const thinkingMode = ref<ThinkingMode>("quick");
  const runMode = ref<RunMode>("rag");
  const scopeType = ref<"all" | "folder" | "kb" | "workspace">("all");
  const scopeId = ref<number | null>(null);
  const workspaceKey = ref<string | null>(null);
  const scopeName = ref<string | null>(null);
  const nativeWebSearchEnabled = ref(false);
  const externalWebSearchEnabled = ref(false);
  const externalWebSearchAvailable = ref(false);
  const optionsLoading = ref(false);
  const optionsLastCheckedAt = ref<number | null>(null);
  const conversationsLoading = ref(false);
  const conversationsPage = ref(1);
  const conversationsHasMore = ref(false);

  const activeSession = computed(
    () => sessions.value.find((session) => session.id === activeSessionId.value) ?? null,
  );
  const messages = computed(() => activeSession.value?.messages ?? []);
  const recentSessions = computed(() => [...sessions.value].sort((a, b) => b.updatedAt - a.updatedAt));
  const selectedModelOption = computed(
    () => modelOptions.value.find((item) => item.model === selectedModel.value) ?? null,
  );
  const selectedModelSupportsNativeSearch = computed(() => Boolean(selectedModelOption.value?.supports_native_web_search));
  const selectedKnowledgeBaseLabel = computed(() => {
    if (scopeType.value !== "kb" || scopeId.value == null) {
      return null;
    }
    const found = knowledgeBaseOptions.value.find((item) => item.id === scopeId.value);
    return found?.label ?? scopeName.value ?? null;
  });
  const selectedWorkspaceLabel = computed(() => {
    if (scopeType.value !== "workspace") {
      return null;
    }
    const key = workspaceKey.value?.trim();
    if (!key) {
      return null;
    }
    const found = workspaceOptions.value.find((item) => item.key === key || item.id === Number(key));
    return found?.label ?? scopeName.value ?? key;
  });
  const starterPrompts = computed(() => [
    t("chat.starter.summary"),
    t("chat.starter.rag_flow"),
    t("chat.starter.top_findings"),
  ]);

  async function scrollToBottom(smooth = false) {
    await nextTick();
    const viewport = messageViewport.value;
    if (!viewport) {
      return;
    }
    viewport.scrollTo({
      top: viewport.scrollHeight,
      behavior: smooth ? "smooth" : "auto",
    });
  }

  function setViewport(el: HTMLElement | null) {
    messageViewport.value = el;
  }

  function useStarterPrompt(prompt: string) {
    composer.value = prompt;
  }

  function applySessionScope(session: ChatSession) {
    scopeType.value = session.scopeType ?? "all";
    scopeId.value = session.scopeId ?? null;
    workspaceKey.value = session.workspaceKey ?? null;
    if (session.scopeType === "kb" && session.scopeId != null) {
      const found = knowledgeBaseOptions.value.find((item) => item.id === session.scopeId);
      scopeName.value = session.scopeName ?? found?.label ?? null;
      return;
    }
    if (session.scopeType === "workspace" && session.workspaceKey) {
      const found = workspaceOptions.value.find((item) => item.key === session.workspaceKey || item.id === Number(session.workspaceKey));
      scopeName.value = session.scopeName ?? found?.label ?? session.workspaceKey;
      return;
    }
    scopeName.value = session.scopeName ?? null;
  }

  function syncActiveSessionScope() {
    const session = activeSession.value;
    if (!session) {
      return;
    }
    session.scopeType = scopeType.value;
    session.scopeId = scopeId.value;
    session.workspaceKey = workspaceKey.value;
    session.scopeName = scopeName.value;
  }

  function resetForUserChange() {
    sessions.value = [];
    activeSessionId.value = "";
    composer.value = "";
    messageParts.value = [];
    errorMessage.value = "";
    runMode.value = "rag";
    scopeType.value = "all";
    scopeId.value = null;
    workspaceKey.value = null;
    scopeName.value = null;
    knowledgeBaseOptions.value = [];
    workspaceOptions.value = [];
    conversationsPage.value = 1;
    conversationsHasMore.value = false;
  }

  function clearError() {
    errorMessage.value = "";
  }

  function newChat() {
    const session = createSession(t("chat.new_chat"), t("chat.welcome_message"), {
      scopeType: scopeType.value,
      scopeId: scopeId.value,
      workspaceKey: workspaceKey.value,
      scopeName: scopeName.value,
    });
    applySessionScope(session);
    sessions.value.unshift(session);
    activeSessionId.value = session.id;
    composer.value = "";
    messageParts.value = [];
    clearError();
    void scrollToBottom();
  }

  function setSessionMessagesFromPage(session: ChatSession, records: ChatMessageRecord[], hasMore: boolean) {
    const loadedMessages = records
      .map((record) => messageRecordToUiMessage(record))
      .filter((message): message is UiMessage => message !== null);
    session.messages = loadedMessages.length ? loadedMessages : [createWelcomeMessage(t("chat.welcome_message"))];
    session.messagesLoaded = true;
    session.messagesLoading = false;
    session.hasMoreMessages = hasMore;
    session.oldestSeqNo = loadedMessages[0]?.seqNo ?? null;
  }

  async function loadSessionMessages(session: ChatSession, options: { force?: boolean } = {}) {
    if (!session.backendConversationId) {
      session.messagesLoaded = true;
      return;
    }
    if (session.messagesLoading || (session.messagesLoaded && !options.force)) {
      return;
    }

    session.messagesLoading = true;
    try {
      const page = await listChatMessages(session.backendConversationId, { limit: MESSAGE_PAGE_SIZE });
      setSessionMessagesFromPage(session, page.items, page.has_more);
      session.oldestSeqNo = page.oldest_seq_no ?? session.oldestSeqNo ?? null;
      await scrollToBottom();
    } catch (error) {
      session.messagesLoading = false;
      const message = error instanceof Error ? error.message : t("error.chat_request_failed");
      errorMessage.value = message;
      if (!session.messages.length) {
        session.messages = [createWelcomeMessage(t("chat.welcome_message"))];
      }
    }
  }

  async function switchSession(sessionId: string) {
    activeSessionId.value = sessionId;
    clearError();
    const session = activeSession.value;
    if (session) {
      applySessionScope(session);
      await loadSessionMessages(session);
    }
    await scrollToBottom();
  }

  function setScopeType(value: ChatScopeType) {
    scopeType.value = value;
    scopeId.value = null;
    workspaceKey.value = null;
    scopeName.value = null;
    syncActiveSessionScope();
  }

  function setScopeId(value: number | null) {
    scopeId.value = value;
    workspaceKey.value = null;
    if (value === null) {
      scopeName.value = null;
    } else if (scopeType.value === "kb") {
      scopeName.value = knowledgeBaseOptions.value.find((item) => item.id === value)?.label ?? null;
    } else if (scopeType.value === "folder") {
      scopeName.value = scopeName.value ?? null;
    }
    syncActiveSessionScope();
  }

  function setWorkspaceKey(value: string | null) {
    workspaceKey.value = value;
    scopeId.value = null;
    const found = value ? workspaceOptions.value.find((item) => item.key === value || item.id === Number(value)) : null;
    scopeName.value = found?.label ?? value ?? null;
    syncActiveSessionScope();
  }

  function setScopeName(value: string | null) {
    scopeName.value = value?.trim() ? value.trim() : null;
    syncActiveSessionScope();
  }

  async function loadOlderMessages() {
    const session = activeSession.value;
    if (
      !session ||
      !session.backendConversationId ||
      !session.hasMoreMessages ||
      !session.oldestSeqNo ||
      session.olderMessagesLoading ||
      session.messagesLoading
    ) {
      return;
    }

    const viewport = messageViewport.value;
    const previousHeight = viewport?.scrollHeight ?? 0;
    const previousTop = viewport?.scrollTop ?? 0;
    session.olderMessagesLoading = true;
    try {
      const page = await listChatMessages(session.backendConversationId, {
        limit: MESSAGE_PAGE_SIZE,
        before_seq_no: session.oldestSeqNo,
      });
      const olderMessages = page.items
        .map((record) => messageRecordToUiMessage(record))
        .filter((message): message is UiMessage => message !== null);

      if (olderMessages.length) {
        const existingIds = new Set(session.messages.map((message) => message.backendMessageId));
        const deduped = olderMessages.filter(
          (message) => message.backendMessageId === undefined || !existingIds.has(message.backendMessageId),
        );
        session.messages = [...deduped, ...session.messages];
        session.oldestSeqNo = page.oldest_seq_no ?? deduped[0]?.seqNo ?? session.oldestSeqNo;
      }
      session.hasMoreMessages = page.has_more;
      await nextTick();
      if (viewport) {
        viewport.scrollTop = viewport.scrollHeight - previousHeight + previousTop;
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : t("error.chat_request_failed");
      errorMessage.value = message;
    } finally {
      session.olderMessagesLoading = false;
    }
  }

  function setSelectedModel(model: string) {
    selectedModel.value = model;
    const nextOption = modelOptions.value.find((item) => item.model === model);
    if (nextOption?.supports_native_web_search) {
      nativeWebSearchEnabled.value = true;
    } else {
      nativeWebSearchEnabled.value = false;
    }
  }

  async function appendDeltaSmoothly(target: UiMessage, delta: string) {
    let index = 0;
    for (const char of delta) {
      index += 1;
      target.content += char;

      if (index % 10 === 0) {
        await scrollToBottom();
      }

      if (/[\n.!?;:\u3002\uFF01\uFF1F\uFF1B]/.test(char)) {
        await delay(20);
      } else {
        await delay(6);
      }
    }
  }

  function applyDonePayload(target: UiMessage, payload: ChatStreamDoneEvent) {
    // Always use the final done payload. It may contain a polished/expanded answer.
    const localFollowups = collectToolConfirmationFollowups(target);
    target.content = appendAssistantFollowups(payload.answer ?? target.content, localFollowups);
    target.sources = payload.sources ?? [];
    target.citations = payload.citations ?? [];
    target.model = payload.model ?? undefined;
    target.usage = payload.usage ?? undefined;
    target.costEstimate = payload.cost_estimate ?? undefined;
    target.reasoningParts = payload.reasoning_parts ?? target.reasoningParts ?? [];
    applyDiagnosticsToMessage(target, payload.model_diagnostics);
    target.content = appendAssistantFollowups(target.content, collectToolConfirmationFollowups(target));
    target.streaming = false;
  }

  function setMessageParts(parts: ChatMessagePart[]) {
    messageParts.value = parts;
  }

  function buildRequestMessageParts(question: string): ChatMessagePart[] {
    const parts = messageParts.value
      .map((part) => ({ ...part }))
      .filter((part) => {
        if (part.type === "image_url") {
          return Boolean(part.image_url?.trim());
        }
        if (part.type === "file_ref") {
          return Boolean(part.file_id || part.file_name?.trim());
        }
        return Boolean(part.text?.trim());
      });
    return [{ type: "text", text: question }, ...parts];
  }

  async function sendChat() {
    if (loading.value) {
      return;
    }

    let session = activeSession.value;
    if (!session) {
      newChat();
      session = activeSession.value;
    }
    if (!session) {
      return;
    }

    const question = composer.value.trim();
    if (!question) {
      return;
    }

    const selected = selectedModel.value.trim();
    const selectedOption = modelOptions.value.find((item) => item.model === selected);
    if (selectedOption && !selectedOption.available) {
      errorMessage.value =
        selectedOption.unavailable_reason ||
        t("error.model_temporarily_unavailable", { model: selected });
      return;
    }

    clearError();
    const requestMessageParts = buildRequestMessageParts(question);
    composer.value = "";
    messageParts.value = [];

    const userMessage = reactive<UiMessage>({
      id: createId(),
      role: "user",
      content: question,
      messageParts: requestMessageParts,
      createdAt: Date.now(),
      sources: [],
      citations: [],
    });
    session.messages.push(userMessage);
    session.updatedAt = Date.now();
    session.scopeType = scopeType.value;
    session.scopeId = scopeId.value;
    session.workspaceKey = workspaceKey.value;
    session.scopeName = scopeName.value;

    if (session.messages.length <= 3) {
      session.title = buildSessionTitle(question, t("chat.new_chat"));
    }

    const assistantMessage = reactive<UiMessage>({
      id: createId(),
      role: "assistant",
      content: "",
      createdAt: Date.now(),
      sources: [],
      citations: [],
      reasoningParts: [],
      toolCalls: [],
      providerApi: null,
      streaming: true,
    });
    session.messages.push(assistantMessage);

    loading.value = true;
    await scrollToBottom(true);

    try {
      const history = toHistoryPayload(session.messages.slice(0, -1));
      await chatStream(
        {
          question,
          message_parts: requestMessageParts,
          conversation_id: session.backendConversationId ?? undefined,
          history,
          top_k: topK.value,
          model: selectedModel.value || undefined,
          scope_type: scopeType.value,
          scope_id: scopeId.value ?? undefined,
          workspace_key: workspaceKey.value ?? undefined,
          web_search: false,
          native_web_search: selectedModelSupportsNativeSearch.value ? nativeWebSearchEnabled.value : false,
          external_web_search: externalWebSearchAvailable.value ? externalWebSearchEnabled.value : false,
          thinking_mode: thinkingMode.value,
          run_mode: runMode.value,
        },
        {
          onDelta: async (delta) => {
            await appendDeltaSmoothly(assistantMessage, delta);
          },
          onReasoningDelta: (delta) => {
            const normalized = delta.trim();
            if (!normalized) {
              return;
            }
            assistantMessage.reasoningParts = [...(assistantMessage.reasoningParts ?? []), delta];
          },
          onToolCallDelta: (payload) => {
            const toolCall = normalizeToolCall(payload);
            if (!toolCall) {
              return;
            }
            assistantMessage.toolCalls = [...(assistantMessage.toolCalls ?? []), toolCall];
          },
          onUsage: (usage) => {
            assistantMessage.usage = usage ?? undefined;
          },
          onDiagnostics: (diagnostics) => {
            applyDiagnosticsToMessage(assistantMessage, diagnostics);
          },
          onDone: async (donePayload) => {
            if (donePayload.conversation_id) {
              session.backendConversationId = donePayload.conversation_id;
              if (!session.id.startsWith("db-")) {
                session.id = `db-${donePayload.conversation_id}`;
                activeSessionId.value = session.id;
              }
            }
            session.scopeType = scopeType.value;
            session.scopeId = scopeId.value;
            session.workspaceKey = workspaceKey.value;
            session.scopeName = scopeName.value;
            applyDonePayload(assistantMessage, donePayload);
            if (session.backendConversationId) {
              await syncToolConfirmationStatesForMessage(assistantMessage, session.backendConversationId);
            }
            session.messagesLoaded = true;
            session.hasMoreMessages = Boolean(session.hasMoreMessages);
            await scrollToBottom();
          },
          onError: (message) => {
            errorMessage.value = message;
          },
        },
      );
    } catch (error) {
      assistantMessage.streaming = false;
      assistantMessage.failed = true;
      const message = error instanceof Error ? error.message : t("error.chat_request_failed");
      assistantMessage.content = message;
      errorMessage.value = message;
    } finally {
      loading.value = false;
      session.updatedAt = Date.now();
    }
  }

  function updateToolCall(
    payload: ToolConfirmationUiPayload,
    updater: (toolCall: UiToolCall) => UiToolCall,
  ): boolean {
    for (const session of sessions.value) {
      const message = session.messages.find((item) => item.id === payload.messageId);
      if (!message?.toolCalls?.length) {
        continue;
      }
      let updated = false;
      message.toolCalls = message.toolCalls.map((toolCall) => {
        if (toolCall.confirmation_id !== payload.confirmationId) {
          return toolCall;
        }
        updated = true;
        return updater(toolCall);
      });
      if (updated) {
        session.updatedAt = Date.now();
        return true;
      }
    }
    return false;
  }

  function findToolCallByConfirmationId(payload: ToolConfirmationUiPayload): UiToolCall | null {
    for (const session of sessions.value) {
      const message = session.messages.find((item) => item.id === payload.messageId);
      const toolCall = message?.toolCalls?.find((item) => item.confirmation_id === payload.confirmationId);
      if (toolCall) {
        return toolCall;
      }
    }
    return null;
  }

  function appendToolConfirmationFollowup(payload: ToolConfirmationUiPayload, followup?: string | null): boolean {
    const text = String(followup || "").trim();
    if (!text) {
      return false;
    }
    for (const session of sessions.value) {
      const message = session.messages.find((item) => item.id === payload.messageId);
      if (!message) {
        continue;
      }
      const nextContent = appendAssistantFollowup(message.content, text);
      if (nextContent === message.content) {
        return false;
      }
      message.content = nextContent;
      session.updatedAt = Date.now();
      return true;
    }
    return false;
  }

  function findConversationIdByMessageId(messageId: string): number | null {
    for (const session of sessions.value) {
      if (session.messages.some((message) => message.id === messageId)) {
        return session.backendConversationId ?? null;
      }
    }
    return activeSession.value?.backendConversationId ?? null;
  }

  async function syncToolConfirmationStatesForMessage(message: UiMessage, conversationId: number) {
    const toolCalls = message.toolCalls ?? [];
    for (const toolCall of toolCalls) {
      const confirmationId = String(toolCall.confirmation_id || "").trim();
      const status = String(toolCall.confirmation_status || "");
      if (!confirmationId || (status !== "confirmed" && status !== "cancelled")) {
        continue;
      }
      try {
        const response =
          status === "confirmed"
            ? await confirmAgentToolConfirmation(confirmationId, { conversation_id: conversationId })
            : await cancelAgentToolConfirmation(confirmationId, { conversation_id: conversationId });
        const payload = { messageId: message.id, confirmationId };
        updateToolCall(payload, (currentToolCall) => applyToolConfirmationResponse(currentToolCall, response));
        appendToolConfirmationFollowup(payload, buildToolConfirmationFollowup(toolCall, response));
      } catch {
        // The user already sees the local tool result. This late sync only keeps history persistence in step.
      }
    }
  }

  async function confirmToolCall(payload: ToolConfirmationUiPayload) {
    const confirmationId = payload.confirmationId.trim();
    if (!confirmationId) {
      return;
    }
    const currentToolCall = findToolCallByConfirmationId(payload);
    if (isTerminalConfirmationStatus(currentToolCall?.confirmation_status)) {
      return;
    }
    clearError();
    updateToolCall(payload, markToolConfirmationRunning);
    try {
      const response = await confirmAgentToolConfirmation(confirmationId, {
        conversation_id: findConversationIdByMessageId(payload.messageId),
      });
      const followup = buildToolConfirmationFollowup(currentToolCall ?? ({ confirmation_id: confirmationId } as UiToolCall), response);
      updateToolCall(payload, (toolCall) => applyToolConfirmationResponse(toolCall, response));
      appendToolConfirmationFollowup(payload, followup);
    } catch (error) {
      const message = error instanceof Error ? error.message : t("error.chat_request_failed");
      errorMessage.value = message;
      updateToolCall(payload, (toolCall) => markToolConfirmationFailed(toolCall, message));
    }
  }

  async function cancelToolCall(payload: ToolConfirmationUiPayload) {
    const confirmationId = payload.confirmationId.trim();
    if (!confirmationId) {
      return;
    }
    clearError();
    try {
      const currentToolCall = findToolCallByConfirmationId(payload);
      const response = await cancelAgentToolConfirmation(confirmationId, {
        conversation_id: findConversationIdByMessageId(payload.messageId),
      });
      const followup = buildToolConfirmationFollowup(currentToolCall ?? ({ confirmation_id: confirmationId } as UiToolCall), response);
      updateToolCall(payload, (toolCall) => applyToolConfirmationResponse(toolCall, response));
      appendToolConfirmationFollowup(payload, followup);
    } catch (error) {
      const message = error instanceof Error ? error.message : t("error.chat_request_failed");
      errorMessage.value = message;
      updateToolCall(payload, (toolCall) => markToolConfirmationFailed(toolCall, message));
    }
  }

  async function initialize() {
    await Promise.all([loadConversations(), loadChatOptions()]);
  }

  async function loadConversations(options: { reset?: boolean } = {}) {
    if (conversationsLoading.value) {
      return;
    }

    conversationsLoading.value = true;
    const reset = options.reset ?? true;
    const nextPage = reset ? 1 : conversationsPage.value + 1;
    try {
      const page = await listChatConversations({
        page: nextPage,
        page_size: CONVERSATION_PAGE_SIZE,
      });
      const loadedSessions = page.items.map((item) => conversationToSession(item));

      if (reset) {
        sessions.value = loadedSessions;
      } else {
        const existingIds = new Set(sessions.value.map((session) => session.backendConversationId));
        sessions.value.push(
          ...loadedSessions.filter(
            (session) => session.backendConversationId == null || !existingIds.has(session.backendConversationId),
          ),
        );
      }

      conversationsPage.value = page.page;
      conversationsHasMore.value = page.has_more;

      if (!sessions.value.length) {
        newChat();
        return;
      }

      if (!activeSessionId.value || !sessions.value.some((session) => session.id === activeSessionId.value)) {
        activeSessionId.value = sessions.value[0].id;
      }
      const session = activeSession.value;
      if (session) {
        applySessionScope(session);
        await loadSessionMessages(session);
      }
      if (knowledgeBaseOptions.value.length || workspaceOptions.value.length) {
        for (const sessionItem of sessions.value) {
          if (sessionItem.scopeType === "kb" && sessionItem.scopeId != null && !sessionItem.scopeName) {
            sessionItem.scopeName = knowledgeBaseOptions.value.find((item) => item.id === sessionItem.scopeId)?.label ?? null;
          }
          if (sessionItem.scopeType === "workspace" && sessionItem.workspaceKey && !sessionItem.scopeName) {
            sessionItem.scopeName =
              workspaceOptions.value.find(
                (item) => item.key === sessionItem.workspaceKey || item.id === Number(sessionItem.workspaceKey),
              )?.label ?? sessionItem.workspaceKey;
          }
        }
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : t("error.chat_request_failed");
      errorMessage.value = message;
      if (!sessions.value.length) {
        newChat();
      }
    } finally {
      conversationsLoading.value = false;
    }
  }

  async function loadMoreConversations() {
    if (!conversationsHasMore.value || conversationsLoading.value) {
      return;
    }
    await loadConversations({ reset: false });
  }

  async function loadChatOptions() {
    if (optionsLoading.value) {
      return;
    }
    optionsLoading.value = true;
    try {
      const options = await getChatOptions();
      const typedOptions = options as ChatOptionsResponse;
      availableModels.value = options.models?.length ? options.models : [options.default_model];
      modelOptions.value = options.model_options ?? [];
      knowledgeBaseOptions.value = typedOptions.knowledge_bases ?? [];
      workspaceOptions.value = typedOptions.workspaces ?? [];
      const firstAvailableModel =
        modelOptions.value.find((item) => item.available)?.model || options.default_model || availableModels.value[0];
      selectedModel.value = availableModels.value.includes(firstAvailableModel)
        ? firstAvailableModel
        : availableModels.value[0];
      externalWebSearchAvailable.value = Boolean(
        options.external_web_search_available ?? options.web_search_available,
      );
      if (!externalWebSearchAvailable.value) {
        externalWebSearchEnabled.value = false;
      }

      const currentOption = modelOptions.value.find((item) => item.model === selectedModel.value);
      if (currentOption?.supports_native_web_search) {
        nativeWebSearchEnabled.value = true;
      } else {
        nativeWebSearchEnabled.value = false;
      }
      if (sessions.value.length) {
        for (const session of sessions.value) {
          if (session.scopeType === "kb" && session.scopeId != null && !session.scopeName) {
            session.scopeName = knowledgeBaseOptions.value.find((item) => item.id === session.scopeId)?.label ?? null;
          }
          if (session.scopeType === "workspace" && session.workspaceKey && !session.scopeName) {
            session.scopeName =
              workspaceOptions.value.find((item) => item.key === session.workspaceKey || item.id === Number(session.workspaceKey))?.label ??
              session.workspaceKey;
          }
        }
        const session = activeSession.value;
        if (session) {
          applySessionScope(session);
        }
      }
    } catch {
      // Keep safe defaults without interrupting chat usage.
      availableModels.value = availableModels.value.length ? availableModels.value : ["deepseek-v4-flash"];
      modelOptions.value = availableModels.value.map((model) => ({
        model,
        provider: "deepseek",
        supports_native_web_search: false,
        available: true,
      }));
      if (!selectedModel.value) {
        selectedModel.value = availableModels.value[0];
      }
      knowledgeBaseOptions.value = [];
      workspaceOptions.value = [];
      externalWebSearchAvailable.value = false;
      externalWebSearchEnabled.value = false;
      nativeWebSearchEnabled.value = false;
    } finally {
      optionsLastCheckedAt.value = Date.now();
      optionsLoading.value = false;
    }
  }

  return {
    sessions,
    activeSessionId,
    activeSession,
    recentSessions,
    messages,
    loading,
    composer,
    messageParts,
    errorMessage,
    starterPrompts,
    newChat,
    switchSession,
    loadOlderMessages,
    loadMoreConversations,
    setSelectedModel,
    useStarterPrompt,
    sendChat,
    confirmToolCall,
    cancelToolCall,
    initialize,
    clearError,
    setMessageParts,
    setViewport,
    scrollToBottom,
    availableModels,
    modelOptions,
    knowledgeBaseOptions,
    workspaceOptions,
    selectedModel,
    thinkingMode,
    runMode,
    scopeType,
    scopeId,
    workspaceKey,
    scopeName,
    nativeWebSearchEnabled,
    selectedModelSupportsNativeSearch,
    selectedKnowledgeBaseLabel,
    selectedWorkspaceLabel,
    externalWebSearchEnabled,
    externalWebSearchAvailable,
    optionsLoading,
    optionsLastCheckedAt,
    conversationsLoading,
    conversationsHasMore,
    loadChatOptions,
    setScopeType,
    setScopeId,
    setWorkspaceKey,
    setScopeName,
    resetForUserChange,
  };
}
