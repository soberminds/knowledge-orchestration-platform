<script setup lang="ts">
import type { HealthResponse } from "../../api";
import { useI18n } from "../../composables/useI18n";

defineProps<{
  health: HealthResponse | null;
  statusText: string;
  indexedChunks: number;
  ingesting: boolean;
  refreshing: boolean;
}>();

defineEmits<{
  (event: "rebuild"): void;
  (event: "refresh"): void;
}>();

const { t } = useI18n();
</script>

<template>
  <section class="workspace-standard">
    <section class="tool-card">
      <div class="status-grid">
        <article>
          <span>{{ t("index.service_status") }}</span>
          <strong>{{ statusText }}</strong>
        </article>
        <article>
          <span>{{ t("index.collection_name") }}</span>
          <strong>{{ health?.collection_name ?? "-" }}</strong>
        </article>
        <article>
          <span>{{ t("index.chunk_count") }}</span>
          <strong>{{ indexedChunks }}</strong>
        </article>
      </div>

      <div class="index-actions">
        <el-button class="action-btn action-btn--confirm" :loading="ingesting" @click="$emit('rebuild')">
          {{ t("index.rebuild") }}
        </el-button>
        <el-button class="action-btn action-btn--ghost" plain :loading="refreshing" @click="$emit('refresh')">
          {{ t("index.refresh") }}
        </el-button>
      </div>
    </section>
  </section>
</template>

<style scoped>
.workspace-standard {
  height: 100%;
  min-height: 0;
  overflow: auto;
  padding: 18px 24px;
}

.tool-card {
  margin: 0;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 16px;
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.05);
  padding: 16px;
}

.status-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.status-grid article {
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 10px;
  background: var(--surface-subtle);
}

.status-grid span {
  display: block;
  color: var(--text-muted);
  font-size: 0.82rem;
}

.status-grid strong {
  display: block;
  margin-top: 6px;
  color: var(--text);
  font-size: 1rem;
}

.index-actions {
  margin-top: 14px;
  display: flex;
  align-items: center;
  gap: 10px;
}

.action-btn--confirm {
  --el-button-bg-color: #0f766e;
  --el-button-border-color: #0f766e;
  --el-button-hover-bg-color: #0d9488;
  --el-button-hover-border-color: #0d9488;
  --el-button-active-bg-color: #0b6f68;
  --el-button-active-border-color: #0b6f68;
  --el-button-text-color: #fff;
  --el-button-hover-text-color: #fff;
  --el-button-active-text-color: #fff;
}

.action-btn--ghost {
  --el-button-text-color: #0f766e;
  --el-button-hover-text-color: #0f766e;
  --el-button-active-text-color: #0f766e;
  --el-button-bg-color: rgba(236, 253, 249, 0.94);
  --el-button-border-color: rgba(20, 184, 166, 0.18);
  --el-button-hover-bg-color: rgba(220, 252, 242, 0.96);
  --el-button-hover-border-color: rgba(20, 184, 166, 0.28);
  --el-button-active-bg-color: rgba(220, 252, 242, 0.98);
  --el-button-active-border-color: rgba(20, 184, 166, 0.32);
}

@media (max-width: 720px) {
  .workspace-standard {
    padding: 12px;
  }

  .status-grid {
    grid-template-columns: 1fr;
  }

  .index-actions {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
