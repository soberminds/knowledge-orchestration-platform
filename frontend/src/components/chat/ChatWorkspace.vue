<script setup lang="ts">
import { computed, ref } from "vue";
import type { ChatModelOption } from "../../api";
import type { UiMessage } from "../../types/chat";
import ChatComposer from "./ChatComposer.vue";
import MessageList from "./MessageList.vue";
import ModelHealthPanel from "./ModelHealthPanel.vue";

const props = defineProps<{
  title: string;
  messages: UiMessage[];
  loading: boolean;
  composer: string;
  topK: number;
  starterPrompts: string[];
  availableModels: string[];
  modelOptions: ChatModelOption[];
  selectedModel: string;
  thinkingMode: "quick" | "deep";
  nativeWebSearchEnabled: boolean;
  nativeWebSearchSupported: boolean;
  externalWebSearchEnabled: boolean;
  externalWebSearchAvailable: boolean;
  optionsLoading: boolean;
  optionsLastCheckedAt: number | null;
}>();

const emit = defineEmits<{
  (event: "update:composer", value: string): void;
  (event: "update:topK", value: number): void;
  (event: "update:selectedModel", value: string): void;
  (event: "update:thinkingMode", value: "quick" | "deep"): void;
  (event: "update:nativeWebSearchEnabled", value: boolean): void;
  (event: "update:externalWebSearchEnabled", value: boolean): void;
  (event: "refresh-model-options"): void;
  (event: "send"): void;
  (event: "pick-starter", prompt: string): void;
  (event: "viewport-ready", element: HTMLElement | null): void;
}>();

const showStarters = computed(() => props.messages.length <= 1);
const modelHealthVisible = ref(false);

interface ModelGroup {
  provider: string;
  models: ChatModelOption[];
}

function inferProviderByModelName(modelName: string): string {
  const normalized = modelName.trim().toLowerCase();
  if (!normalized) return "other";
  if (normalized.startsWith("deepseek")) return "deepseek";
  if (normalized.startsWith("qwen") || normalized.startsWith("qwq")) return "qwen";
  if (normalized.startsWith("glm") || normalized.startsWith("chatglm") || normalized.includes("zhipu")) return "zai";
  if (normalized.startsWith("kimi") || normalized.startsWith("moonshot")) return "kimi";
  if (normalized.startsWith("hunyuan")) return "hunyuan";
  if (normalized.startsWith("doubao") || normalized.startsWith("seed")) return "volcengine";
  if (normalized.startsWith("ernie") || normalized.startsWith("wenxin")) return "qianfan";
  if (normalized.startsWith("gpt") || normalized.startsWith("o1") || normalized.startsWith("o3")) return "openai";
  if (normalized.startsWith("claude")) return "anthropic";
  if (normalized.startsWith("gemini")) return "google";
  return "other";
}

function providerLabel(provider: string): string {
  const token = provider.trim().toLowerCase();
  if (token === "deepseek") return "DeepSeek";
  if (token === "qwen") return "Qwen (Alibaba)";
  if (token === "zai") return "Z.AI";
  if (token === "kimi") return "Moonshot";
  if (token === "hunyuan") return "Tencent Hunyuan";
  if (token === "volcengine") return "Volcengine";
  if (token === "qianfan") return "Baidu Qianfan";
  if (token === "siliconflow") return "SiliconFlow";
  if (token === "openai") return "OpenAI";
  if (token === "anthropic") return "Anthropic";
  if (token === "google") return "Google";
  return "Other";
}

const modelGroups = computed<ModelGroup[]>(() => {
  const normalizedOptions: ChatModelOption[] =
    props.modelOptions.length > 0
      ? props.modelOptions
      : props.availableModels.map((model) => ({
          model,
          provider: inferProviderByModelName(model),
          available: true,
        }));

  const providerOrder = [
    "DeepSeek",
    "Qwen (Alibaba)",
    "Z.AI",
    "Moonshot",
    "Tencent Hunyuan",
    "Volcengine",
    "Baidu Qianfan",
    "OpenAI",
    "Anthropic",
    "Google",
    "Other",
  ];

  const groups = new Map<string, ChatModelOption[]>();
  for (const modelOption of normalizedOptions) {
    const provider = providerLabel(modelOption.provider || inferProviderByModelName(modelOption.model));
    if (!groups.has(provider)) {
      groups.set(provider, []);
    }
    groups.get(provider)!.push(modelOption);
  }

  return Array.from(groups.entries())
    .map(([provider, models]) => ({ provider, models }))
    .sort((a, b) => {
      const ai = providerOrder.indexOf(a.provider);
      const bi = providerOrder.indexOf(b.provider);
      const aRank = ai === -1 ? Number.MAX_SAFE_INTEGER : ai;
      const bRank = bi === -1 ? Number.MAX_SAFE_INTEGER : bi;
      if (aRank !== bRank) return aRank - bRank;
      return a.provider.localeCompare(b.provider);
    });
});
</script>

<template>
  <section class="chat-workspace">
    <header class="workspace-head">
      <h2>{{ title }}</h2>
      <p>Chat workspace with retrieval-augmented streaming responses.</p>
    </header>

    <ModelHealthPanel
      v-if="modelHealthVisible"
      :model-options="modelOptions"
      :selected-model="selectedModel"
      :loading="optionsLoading"
      :last-checked-at="optionsLastCheckedAt"
      @refresh="emit('refresh-model-options')"
    />

    <MessageList :messages="messages" @viewport-ready="emit('viewport-ready', $event)" />

    <ChatComposer
      :model-value="composer"
      :loading="loading"
      :starter-prompts="starterPrompts"
      :show-starters="showStarters"
      :top-k="topK"
      :selected-model="selectedModel"
      :thinking-mode="thinkingMode"
      :native-web-search-enabled="nativeWebSearchEnabled"
      :native-web-search-supported="nativeWebSearchSupported"
      :external-web-search-enabled="externalWebSearchEnabled"
      :external-web-search-available="externalWebSearchAvailable"
      :model-groups="modelGroups"
      :options-loading="optionsLoading"
      :model-health-visible="modelHealthVisible"
      @update:model-value="emit('update:composer', $event)"
      @update:top-k="emit('update:topK', $event)"
      @update:selected-model="emit('update:selectedModel', $event)"
      @update:thinking-mode="emit('update:thinkingMode', $event)"
      @update:native-web-search-enabled="emit('update:nativeWebSearchEnabled', $event)"
      @update:external-web-search-enabled="emit('update:externalWebSearchEnabled', $event)"
      @refresh-model-options="emit('refresh-model-options')"
      @toggle-model-health="modelHealthVisible = !modelHealthVisible"
      @send="emit('send')"
      @pick-starter="emit('pick-starter', $event)"
    />
  </section>
</template>

<style scoped>
.chat-workspace {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.workspace-head {
  padding: 18px 24px 12px;
}

.workspace-head h2 {
  margin: 0;
  font-size: 1.18rem;
  font-weight: 600;
}

.workspace-head p {
  margin: 4px 0 0;
  color: #6b7280;
  font-size: 0.9rem;
}

@media (max-width: 720px) {
  .workspace-head {
    padding-left: 12px;
    padding-right: 12px;
  }
}
</style>
