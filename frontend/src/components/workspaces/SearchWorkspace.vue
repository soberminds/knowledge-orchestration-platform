<script setup lang="ts">
import { Search } from "@element-plus/icons-vue";
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

function hitDisplayPath(hit: SourceHit) {
  return hit.display_path || hit.source;
}
</script>

<template>
  <section class="workspace-standard">
    <section class="search-toolbar">
      <div class="toolbar-copy">
        <p class="toolbar-kicker">检索实验场</p>
        <div class="toolbar-main">
          <h2>{{ t("search.title") }}</h2>
          <span>top_k {{ topK }}</span>
        </div>
      </div>

      <div class="toolbar-tools">
        <el-input-number
          class="topk-input"
          :model-value="topK"
          :min="1"
          :max="10"
          size="small"
          controls-position="right"
          @update:model-value="$emit('update:topK', Number($event))"
        />
      </div>
    </section>

    <section class="search-card">
      <div class="search-line">
        <el-input
          class="search-input"
          :model-value="query"
          :placeholder="t('search.placeholder')"
          :prefix-icon="Search"
          @update:model-value="$emit('update:query', String($event))"
          @keyup.enter="$emit('run-search')"
        />
        <el-button
          class="action-btn action-btn--confirm search-button"
          :loading="searching"
          @click="$emit('run-search')"
        >
          {{ t("search.button") }}
        </el-button>
      </div>

      <div class="search-meta">
        <span v-if="hits.length">{{ hits.length }} 条结果</span>
        <span v-else>等待输入检索内容</span>
      </div>
    </section>

    <section class="result-panel">
      <div class="result-panel-head">
        <strong>结果</strong>
        <span v-if="hits.length">共 {{ hits.length }} 条</span>
        <span v-else>暂无命中</span>
      </div>

      <article
        v-for="(hit, index) in hits"
        :key="`${hit.source}-${index}`"
        class="result-item"
      >
        <div class="result-head">
          <div class="result-rank">{{ index + 1 }}</div>
          <div class="result-copy">
            <strong>{{ hitDisplayPath(hit) }}</strong>
            <div class="result-tags">
              <span>chunk {{ hit.chunk_index }}</span>
              <span v-if="hit.page !== null && hit.page !== undefined">p{{ hit.page }}</span>
              <span v-if="hit.score !== null && hit.score !== undefined">score {{ hit.score }}</span>
              <span v-if="hit.file_id !== null && hit.file_id !== undefined">file_id {{ hit.file_id }}</span>
              <span v-if="hit.folder_id !== null && hit.folder_id !== undefined">folder_id {{ hit.folder_id }}</span>
            </div>
          </div>
        </div>
        <p>{{ hit.preview }}</p>
      </article>

      <el-empty v-if="!hits.length" :description="t('search.empty')" />
    </section>
  </section>
</template>

<style scoped>
.workspace-standard {
  height: 100%;
  min-height: 0;
  overflow: auto;
  padding: 16px 20px 20px;
}

.search-toolbar,
.search-card,
.result-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 18px;
  box-shadow: 0 12px 26px rgba(15, 23, 42, 0.05);
}

.search-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  margin-bottom: 12px;
}

.toolbar-copy {
  min-width: 0;
  display: grid;
  gap: 4px;
}

.toolbar-kicker {
  margin: 0;
  color: #0f766e;
  font-size: 0.72rem;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.toolbar-main {
  display: flex;
  align-items: baseline;
  gap: 10px;
}

.toolbar-main h2 {
  margin: 0;
  color: var(--text);
  font-size: 1rem;
  line-height: 1.25;
}

.toolbar-main span {
  color: var(--text-muted);
  font-size: 0.8rem;
}

.toolbar-tools {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 0 0 auto;
}

.topk-input {
  width: 104px;
}

.topk-input :deep(.el-input__wrapper) {
  border-radius: 12px;
  background: var(--surface-subtle);
  box-shadow: 0 0 0 1px var(--border) inset;
}

.search-card {
  padding: 14px;
  margin-bottom: 12px;
}

.search-line {
  display: flex;
  align-items: center;
  gap: 10px;
}

.search-input {
  flex: 1 1 auto;
}

.search-input :deep(.el-input__wrapper) {
  min-height: 46px;
  border-radius: 16px;
  background: var(--surface-subtle);
  box-shadow: 0 0 0 1px var(--border) inset;
}

.search-input :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px rgba(20, 184, 166, 0.28) inset;
}

.search-input :deep(.el-input__prefix) {
  color: #0f766e;
}

.search-button {
  min-width: 106px;
  height: 46px;
  border-radius: 16px;
}

.search-meta {
  margin-top: 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  color: var(--text-muted);
  font-size: 0.8rem;
}

.search-meta span {
  padding: 5px 9px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: var(--surface-muted);
}

.result-panel {
  padding: 14px;
  min-height: 280px;
}

.result-panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border);
}

.result-panel-head strong {
  color: var(--text);
  font-size: 0.95rem;
  font-weight: 800;
}

.result-panel-head span {
  color: var(--text-muted);
  font-size: 0.8rem;
}

.result-item {
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 12px;
  margin-bottom: 10px;
  background: var(--surface-subtle);
}

.result-head {
  display: flex;
  align-items: center;
  gap: 10px;
}

.result-rank {
  width: 30px;
  height: 30px;
  border-radius: 10px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  background: rgba(20, 184, 166, 0.12);
  color: #0f766e;
  font-size: 0.84rem;
  font-weight: 800;
}

.result-copy {
  min-width: 0;
  display: grid;
  gap: 6px;
}

.result-copy strong {
  color: var(--text);
  font-size: 0.92rem;
  line-height: 1.35;
}

.result-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.result-tags span {
  color: var(--text-muted);
  font-size: 0.76rem;
  padding: 4px 8px;
  border-radius: 999px;
  background: var(--surface-muted);
  border: 1px solid var(--border);
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

.result-item p {
  margin: 8px 0 0;
  color: var(--text);
  line-height: 1.66;
}

@media (max-width: 720px) {
  .workspace-standard {
    padding: 12px;
  }

  .search-toolbar,
  .search-line {
    flex-direction: column;
    align-items: stretch;
  }

  .toolbar-main {
    flex-direction: column;
    align-items: flex-start;
    gap: 2px;
  }

  .toolbar-tools {
    width: 100%;
  }

  .topk-input,
  .search-button {
    width: 100%;
  }
}
</style>
