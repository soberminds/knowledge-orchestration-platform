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
    <header class="workspace-head">
      <div>
        <h2>{{ t("index.title") }}</h2>
        <p>{{ t("index.subtitle") }}</p>
      </div>
    </header>

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
        <el-button type="primary" :loading="ingesting" @click="$emit('rebuild')">
          {{ t("index.rebuild") }}
        </el-button>
        <el-button plain :loading="refreshing" @click="$emit('refresh')">
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
}

.workspace-head {
  padding: 18px 24px 12px;
}

.workspace-head h2 {
  margin: 0;
  font-size: 1.18rem;
}

.workspace-head p {
  margin: 4px 0 0;
  color: #6b7280;
  font-size: 0.9rem;
}

.tool-card {
  margin: 0 24px 18px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 16px;
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.06);
  padding: 16px;
}

.status-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.status-grid article {
  border: 1px solid #eef0f3;
  border-radius: 12px;
  padding: 10px;
}

.status-grid span {
  display: block;
  color: #6b7280;
  font-size: 0.82rem;
}

.status-grid strong {
  display: block;
  margin-top: 6px;
  font-size: 1rem;
}

.index-actions {
  margin-top: 14px;
  display: flex;
  align-items: center;
  gap: 10px;
}

@media (max-width: 720px) {
  .workspace-head {
    padding-left: 12px;
    padding-right: 12px;
  }

  .tool-card {
    margin-left: 12px;
    margin-right: 12px;
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
