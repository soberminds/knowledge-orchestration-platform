<script setup lang="ts">
import type { SourceHit } from "../../api";
import { useI18n } from "../../composables/useI18n";

defineProps<{
  query: string;
  hits: SourceHit[];
  searching: boolean;
  topK: number;
}>();

defineEmits<{
  (event: "update:query", value: string): void;
  (event: "update:topK", value: number): void;
  (event: "run-search"): void;
}>();

const { t } = useI18n();
</script>

<template>
  <section class="workspace-standard">
    <header class="workspace-head">
      <div>
        <h2>{{ t("search.title") }}</h2>
        <p>{{ t("search.subtitle") }}</p>
      </div>
      <div class="head-actions">
        <el-tag effect="plain" type="success">top_k: {{ topK }}</el-tag>
        <el-input-number
          :model-value="topK"
          :min="1"
          :max="10"
          size="small"
          controls-position="right"
          @update:model-value="$emit('update:topK', Number($event))"
        />
      </div>
    </header>

    <section class="tool-card">
      <div class="search-line">
        <el-input
          :model-value="query"
          :placeholder="t('search.placeholder')"
          @update:model-value="$emit('update:query', String($event))"
          @keyup.enter="$emit('run-search')"
        />
        <el-button
          type="primary"
          :loading="searching"
          @click="$emit('run-search')"
        >
          {{ t("search.button") }}
        </el-button>
      </div>
    </section>

    <section class="list-card">
      <article
        v-for="(hit, index) in hits"
        :key="`${hit.source}-${index}`"
        class="list-item"
      >
        <div class="item-head">
          <strong>[{{ index + 1 }}] {{ hit.source }}</strong>
          <span>chunk {{ hit.chunk_index }}</span>
          <span v-if="hit.page !== null && hit.page !== undefined">p{{ hit.page }}</span>
          <span v-if="hit.score !== null && hit.score !== undefined">score {{ hit.score }}</span>
        </div>
        <p>{{ hit.preview }}</p>
      </article>

      <el-empty
        v-if="!hits.length"
        :description="t('search.empty')"
      />
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
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
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

.head-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.tool-card,
.list-card {
  margin: 0 24px 18px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 16px;
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.06);
}

.tool-card {
  padding: 16px;
}

.search-line {
  display: flex;
  align-items: center;
  gap: 10px;
}

.list-card {
  padding: 12px;
  min-height: 280px;
}

.list-item {
  border: 1px solid #eef0f3;
  border-radius: 12px;
  padding: 10px 11px;
  margin-bottom: 8px;
}

.item-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.item-head span {
  color: #6b7280;
  font-size: 0.83rem;
}

.list-item p {
  margin: 8px 0 0;
  color: #374151;
  line-height: 1.66;
}

@media (max-width: 720px) {
  .workspace-head {
    padding-left: 12px;
    padding-right: 12px;
    flex-direction: column;
    align-items: flex-start;
  }

  .tool-card,
  .list-card {
    margin-left: 12px;
    margin-right: 12px;
  }

  .search-line {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
