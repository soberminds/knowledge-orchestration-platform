<script setup lang="ts">
defineProps<{
  modelValue: string;
  loading: boolean;
  starterPrompts: string[];
  showStarters: boolean;
}>();

defineEmits<{
  (event: "update:modelValue", value: string): void;
  (event: "send"): void;
  (event: "pick-starter", prompt: string): void;
}>();
</script>

<template>
  <footer class="composer-wrap">
    <div v-if="showStarters" class="starter-list">
      <button
        v-for="prompt in starterPrompts"
        :key="prompt"
        @click="$emit('pick-starter', prompt)"
      >
        {{ prompt }}
      </button>
    </div>

    <div class="composer-card">
      <el-input
        :model-value="modelValue"
        type="textarea"
        :rows="2"
        resize="none"
        placeholder="Ask your question (Enter to send, Shift+Enter for newline)"
        @update:model-value="$emit('update:modelValue', String($event))"
        @keydown.enter.exact.prevent="$emit('send')"
      />
      <div class="composer-actions">
        <span class="helper-text">Responses are generated from retrieval + citations.</span>
        <el-button type="primary" :loading="loading" @click="$emit('send')">
          Send
        </el-button>
      </div>
    </div>
  </footer>
</template>

<style scoped>
.composer-wrap {
  padding: 0 24px 16px;
  background: linear-gradient(180deg, rgba(247, 247, 248, 0) 0%, #f7f7f8 100%);
}

.starter-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}

.starter-list button {
  border: 1px solid #e5e7eb;
  background: #fff;
  border-radius: 999px;
  padding: 6px 12px;
  cursor: pointer;
  color: #374151;
}

.starter-list button:hover {
  background: #f9fafb;
}

.composer-card {
  border: 1px solid #e5e7eb;
  background: #fff;
  border-radius: 18px;
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.06);
  padding: 10px 10px 8px;
}

.composer-card :deep(.el-textarea__inner) {
  border: 0;
  box-shadow: none;
  resize: none;
  min-height: 56px !important;
  background: transparent;
}

.composer-actions {
  margin-top: 4px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.helper-text {
  color: #6b7280;
  font-size: 0.84rem;
}

@media (max-width: 720px) {
  .composer-wrap {
    padding-left: 12px;
    padding-right: 12px;
  }
}
</style>
