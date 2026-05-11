import type { Ref } from "vue";
import { computed, nextTick, reactive, ref } from "vue";
import { chatStream, type HistoryItem, type SourceHit } from "../api";
import type { ChatSession, UiMessage } from "../types/chat";

const STARTER_PROMPTS = [
  "请总结我的知识库中关于项目架构的关键点。",
  "这个项目从文档到问答的完整 RAG 流程是什么？",
  "请列出当前知识库里最值得先读的 5 条结论。",
];

function createId() {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

function buildSessionTitle(text: string) {
  const normalized = text.trim().replace(/\s+/g, " ");
  if (!normalized) {
    return "New Chat";
  }
  return normalized.length > 24 ? `${normalized.slice(0, 24)}...` : normalized;
}

function createWelcomeMessage(): UiMessage {
  return {
    id: createId(),
    role: "assistant",
    createdAt: Date.now(),
    content: "Hi, ask any question from your knowledge base and I will answer with citations.",
    sources: [],
  };
}

function createSession(seedTitle = "New Chat"): ChatSession {
  return {
    id: createId(),
    title: seedTitle,
    updatedAt: Date.now(),
    messages: [createWelcomeMessage()],
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
  const sessions = ref<ChatSession[]>([]);
  const activeSessionId = ref("");
  const loading = ref(false);
  const composer = ref("");
  const errorMessage = ref("");
  const messageViewport = ref<HTMLElement | null>(null);

  const activeSession = computed(
    () => sessions.value.find((session) => session.id === activeSessionId.value) ?? null,
  );
  const messages = computed(() => activeSession.value?.messages ?? []);
  const recentSessions = computed(() => [...sessions.value].sort((a, b) => b.updatedAt - a.updatedAt).slice(0, 12));
  const starterPrompts = STARTER_PROMPTS;

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
    const session = createSession();
    sessions.value.unshift(session);
    activeSessionId.value = session.id;
    composer.value = "";
    clearError();
    void scrollToBottom();
  }

  function switchSession(sessionId: string) {
    activeSessionId.value = sessionId;
    clearError();
    void scrollToBottom();
  }

  async function appendDeltaSmoothly(target: UiMessage, delta: string) {
    let index = 0;
    for (const char of delta) {
      index += 1;
      target.content += char;

      if (index % 10 === 0) {
        await scrollToBottom();
      }

      if (/[\n。！？.!?;；]/.test(char)) {
        await delay(20);
      } else {
        await delay(6);
      }
    }
  }

  function applyDonePayload(target: UiMessage, payload: { answer: string; sources: SourceHit[] }) {
    if (!target.content.trim() && payload.answer) {
      target.content = payload.answer;
    }
    target.sources = payload.sources ?? [];
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

    clearError();
    composer.value = "";

    const userMessage = reactive<UiMessage>({
      id: createId(),
      role: "user",
      content: question,
      createdAt: Date.now(),
      sources: [],
    });
    session.messages.push(userMessage);
    session.updatedAt = Date.now();

    if (session.title === "New Chat" || session.messages.length <= 3) {
      session.title = buildSessionTitle(question);
    }

    const assistantMessage = reactive<UiMessage>({
      id: createId(),
      role: "assistant",
      content: "",
      createdAt: Date.now(),
      sources: [],
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
          history,
          top_k: topK.value,
        },
        {
          onDelta: async (delta) => {
            await appendDeltaSmoothly(assistantMessage, delta);
          },
          onDone: async (donePayload) => {
            applyDonePayload(assistantMessage, donePayload);
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
      assistantMessage.content = error instanceof Error ? error.message : "Chat request failed";
      errorMessage.value = "Chat failed. Please check backend logs.";
    } finally {
      loading.value = false;
      session.updatedAt = Date.now();
    }
  }

  function initialize() {
    if (!sessions.value.length) {
      newChat();
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
    useStarterPrompt,
    sendChat,
    initialize,
    clearError,
    setViewport,
    scrollToBottom,
  };
}
