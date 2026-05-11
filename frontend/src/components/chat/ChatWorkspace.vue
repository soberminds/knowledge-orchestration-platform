<script setup lang="ts">
import { computed } from "vue";
import type { UiMessage } from "../../types/chat";
import ChatComposer from "./ChatComposer.vue";
import MessageList from "./MessageList.vue";

const props = defineProps<{
  title: string;
  messages: UiMessage[];
  loading: boolean;
  composer: string;
  topK: number;
  starterPrompts: string[];
}>();

const emit = defineEmits<{
  (event: "update:composer", value: string): void;
  (event: "update:topK", value: number): void;
  (event: "send"): void;
  (event: "pick-starter", prompt: string): void;
  (event: "viewport-ready", element: HTMLElement | null): void;
}>();

const showStarters = computed(() => props.messages.length <= 1);
</script>

<template>
  <section class="chat-workspace">
    <header class="workspace-head">
      <div>
        <h2>{{ title }}</h2>
        <p>Chat workspace with retrieval-augmented streaming responses.</p>
      </div>
      <div class="head-actions">
        <el-tag effect="plain" type="success">top_k: {{ topK }}</el-tag>
        <el-input-number
          :model-value="topK"
          :min="1"
          :max="10"
          size="small"
          controls-position="right"
          @update:model-value="emit('update:topK', Number($event))"
        />
      </div>
    </header>

    <MessageList :messages="messages" @viewport-ready="emit('viewport-ready', $event)" />

    <ChatComposer
      :model-value="composer"
      :loading="loading"
      :starter-prompts="starterPrompts"
      :show-starters="showStarters"
      @update:model-value="emit('update:composer', $event)"
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
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
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

.head-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

@media (max-width: 720px) {
  .workspace-head {
    padding-left: 12px;
    padding-right: 12px;
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
