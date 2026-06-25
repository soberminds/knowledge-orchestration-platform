import type { Ref } from "vue";
import { computed, nextTick, reactive, ref } from "vue";
import { useI18n } from "./useI18n";
import {
  chatStream,
  getChatOptions,
  listChatConversations,
  listChatMessages,
  type ChatConversationSummary,
  type ChatMessageRecord,
  type ChatModelOption,
  type ChatStreamDoneEvent,
  type HistoryItem,
  type ThinkingMode,
} from "../api";
import type { ChatSession, UiMessage } from "../types/chat";

const CONVERSATION_PAGE_SIZE = 20;
const MESSAGE_PAGE_SIZE = 30;

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

function createSession(seedTitle: string, welcomeText: string): ChatSession {
  return {
    id: createId(),
    backendConversationId: null,
    title: seedTitle,
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

function conversationToSession(item: ChatConversationSummary): ChatSession {
  return {
    id: `db-${item.id}`,
    backendConversationId: item.id,
    title: item.title || item.preview || "Chat",
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
    model: record.model ?? undefined,
    usage: record.usage ?? undefined,
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
  const errorMessage = ref("");
  const messageViewport = ref<HTMLElement | null>(null);
  const availableModels = ref<string[]>([]);
  const modelOptions = ref<ChatModelOption[]>([]);
  const selectedModel = ref("");
  const thinkingMode = ref<ThinkingMode>("quick");
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

  function clearError() {
    errorMessage.value = "";
  }

  function newChat() {
    const session = createSession(t("chat.new_chat"), t("chat.welcome_message"));
    sessions.value.unshift(session);
    activeSessionId.value = session.id;
    composer.value = "";
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
      await loadSessionMessages(session);
    }
    await scrollToBottom();
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
    if (!nextOption?.supports_native_web_search) {
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
    target.content = payload.answer ?? target.content;
    target.sources = payload.sources ?? [];
    target.citations = payload.citations ?? [];
    target.model = payload.model ?? undefined;
    target.usage = payload.usage ?? undefined;
    target.costEstimate = payload.cost_estimate ?? undefined;
    target.streaming = false;
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
    composer.value = "";

    const userMessage = reactive<UiMessage>({
      id: createId(),
      role: "user",
      content: question,
      createdAt: Date.now(),
      sources: [],
      citations: [],
    });
    session.messages.push(userMessage);
    session.updatedAt = Date.now();

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
          conversation_id: session.backendConversationId ?? undefined,
          history,
          top_k: topK.value,
          model: selectedModel.value || undefined,
          web_search: false,
          native_web_search: selectedModelSupportsNativeSearch.value ? nativeWebSearchEnabled.value : false,
          external_web_search: externalWebSearchAvailable.value ? externalWebSearchEnabled.value : false,
          thinking_mode: thinkingMode.value,
        },
        {
          onDelta: async (delta) => {
            await appendDeltaSmoothly(assistantMessage, delta);
          },
          onDone: async (donePayload) => {
            if (donePayload.conversation_id) {
              session.backendConversationId = donePayload.conversation_id;
              if (!session.id.startsWith("db-")) {
                session.id = `db-${donePayload.conversation_id}`;
                activeSessionId.value = session.id;
              }
            }
            applyDonePayload(assistantMessage, donePayload);
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

  function initialize() {
    void loadConversations();
    void loadChatOptions();
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
        await loadSessionMessages(session);
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
      availableModels.value = options.models?.length ? options.models : [options.default_model];
      modelOptions.value = options.model_options ?? [];
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
      if (!currentOption?.supports_native_web_search) {
        nativeWebSearchEnabled.value = false;
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
    errorMessage,
    starterPrompts,
    newChat,
    switchSession,
    loadOlderMessages,
    loadMoreConversations,
    setSelectedModel,
    useStarterPrompt,
    sendChat,
    initialize,
    clearError,
    setViewport,
    scrollToBottom,
    availableModels,
    modelOptions,
    selectedModel,
    thinkingMode,
    nativeWebSearchEnabled,
    selectedModelSupportsNativeSearch,
    externalWebSearchEnabled,
    externalWebSearchAvailable,
    optionsLoading,
    optionsLastCheckedAt,
    conversationsLoading,
    conversationsHasMore,
    loadChatOptions,
  };
}
