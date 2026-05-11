<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import type { UiMessage } from "../../types/chat";
import MessageItem from "./MessageItem.vue";

const props = defineProps<{
  messages: UiMessage[];
}>();

const emit = defineEmits<{
  (event: "viewport-ready", element: HTMLElement | null): void;
}>();

const viewportRef = ref<HTMLElement | null>(null);

onMounted(() => {
  emit("viewport-ready", viewportRef.value);
});

watch(viewportRef, (value) => {
  emit("viewport-ready", value);
});
</script>

<template>
  <section ref="viewportRef" class="messages-scroll">
    <MessageItem
      v-for="message in props.messages"
      :key="message.id"
      :message="message"
    />
  </section>
</template>

<style scoped>
.messages-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 10px 24px 22px;
  display: grid;
  align-content: start;
  gap: 18px;
  scrollbar-gutter: stable;
}

.messages-scroll::-webkit-scrollbar {
  width: 10px;
}

.messages-scroll::-webkit-scrollbar-thumb {
  background: #d1d5db;
  border-radius: 99px;
}

@media (max-width: 720px) {
  .messages-scroll {
    padding-left: 12px;
    padding-right: 12px;
  }
}
</style>
