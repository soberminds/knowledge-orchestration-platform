<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { listIndexFiles, type DocumentInfo, type HealthResponse, type IndexFileStatusCounts } from "../../api";
import { useI18n } from "../../composables/useI18n";

const props = defineProps<{
  health: HealthResponse | null;
  documents: DocumentInfo[];
  statusText: string;
  indexedChunks: number;
  ingesting: boolean;
  refreshing: boolean;
}>();

const emit = defineEmits<{
  (event: "rebuild"): void;
  (event: "refresh"): void;
}>();

const { locale, t } = useI18n();

const defaultStatusCounts = (): IndexFileStatusCounts => ({
  total: 0,
  pending: 0,
  queued: 0,
  running: 0,
  success: 0,
  failed: 0,
});

const indexFiles = ref<DocumentInfo[]>([]);
const indexTotal = ref(0);
const indexPage = ref(1);
const indexPageSize = ref(20);
const statusFilter = ref("all");
const keyword = ref("");
const submittedKeyword = ref("");
const indexLoading = ref(false);
const indexError = ref("");
const statusCounts = ref<IndexFileStatusCounts>(defaultStatusCounts());

let indexRequestId = 0;

const statusFilterOptions = computed(() => [
  { label: t("index.file_filter_all"), value: "all" },
  { label: t("index.file_filter_processing"), value: "processing" },
  { label: t("index.file_status_failed"), value: "failed" },
  { label: t("index.file_status_queued"), value: "queued" },
  { label: t("index.file_status_running"), value: "running" },
  { label: t("index.file_status_pending"), value: "pending" },
  { label: t("index.file_status_success"), value: "success" },
]);

const pageSizeOptions = computed(() =>
  [10, 20, 50, 100, 200].map((size) => ({
    label: t("index.file_page_size", { size }),
    value: size,
  })),
);

const fileRows = computed(() =>
  indexFiles.value
    .map((item) => {
      const status = normalizeStatus(item.index_status || item.parse_status);
      const stage = normalizeStage(item.index_stage || item.index_status || item.parse_status);
      const totalChunks = Number(item.index_total_chunks ?? 0);
      const indexedChunks = Number(item.index_indexed_chunks ?? 0);
      return {
        ...item,
        displayName: item.name || basenameOf(item.display_path || item.path),
        displayPath: item.display_path || item.path,
        folderPath: parentPathOf(item.display_path || item.path),
        status,
        stage,
        progress: indexProgress(status, item.index_progress),
        chunkText: chunkProgressText(indexedChunks, totalChunks),
        updatedAt: item.index_updated_at || item.index_finished_at || item.last_indexed_at || item.modified_at,
        errorText: item.index_error_message || item.parse_error || "",
      };
    })
    .sort((left, right) => {
      const rankDiff = statusRank(left.status) - statusRank(right.status);
      if (rankDiff !== 0) {
        return rankDiff;
      }
      return left.displayName.localeCompare(right.displayName, locale.value);
    }),
);

onMounted(() => {
  void fetchIndexFiles();
});

watch(
  () => props.ingesting,
  (nextValue, previousValue) => {
    if (previousValue && !nextValue) {
      void fetchIndexFiles();
    }
  },
);

async function fetchIndexFiles() {
  const requestId = ++indexRequestId;
  indexLoading.value = true;
  indexError.value = "";
  try {
    const payload = await listIndexFiles({
      page: indexPage.value,
      page_size: indexPageSize.value,
      status: statusFilter.value,
      keyword: submittedKeyword.value,
    });
    if (requestId !== indexRequestId) {
      return;
    }
    indexFiles.value = payload.items;
    indexTotal.value = payload.total;
    indexPage.value = payload.page;
    indexPageSize.value = payload.page_size;
    statusCounts.value = payload.status_counts || defaultStatusCounts();
  } catch (error) {
    if (requestId !== indexRequestId) {
      return;
    }
    indexError.value = error instanceof Error ? error.message : String(error);
  } finally {
    if (requestId === indexRequestId) {
      indexLoading.value = false;
    }
  }
}

function applyKeyword() {
  submittedKeyword.value = keyword.value.trim();
  indexPage.value = 1;
  void fetchIndexFiles();
}

function handleStatusFilterChange() {
  indexPage.value = 1;
  void fetchIndexFiles();
}

function handlePageSizeChange(size: number | string) {
  indexPageSize.value = Number(size) || 20;
  indexPage.value = 1;
  void fetchIndexFiles();
}

function handlePageChange(page: number) {
  indexPage.value = page;
  void fetchIndexFiles();
}

function handleRefresh() {
  void fetchIndexFiles();
  emit("refresh");
}

function handleRebuild() {
  emit("rebuild");
}

function normalizeStatus(status?: string | null) {
  const normalized = String(status || "pending").trim().toLowerCase();
  if (["queued", "running", "success", "failed", "pending"].includes(normalized)) {
    return normalized;
  }
  return "pending";
}

function normalizeStage(stage?: string | null) {
  const normalized = String(stage || "pending").trim().toLowerCase();
  if (["queued", "loading", "parsing", "splitting", "embedding", "writing", "success", "failed", "pending"].includes(normalized)) {
    return normalized;
  }
  return "pending";
}

function normalizePath(path?: string | null) {
  return String(path || "").replace(/\\/g, "/").replace(/^\/+|\/+$/g, "");
}

function basenameOf(path?: string | null) {
  const normalized = normalizePath(path);
  return normalized.split("/").filter(Boolean).pop() || normalized || "-";
}

function parentPathOf(path?: string | null) {
  const normalized = normalizePath(path);
  const index = normalized.lastIndexOf("/");
  if (index <= 0) {
    return t("index.file_root");
  }
  return normalized.slice(0, index);
}

function statusRank(status: string) {
  const ranks: Record<string, number> = {
    failed: 0,
    running: 1,
    queued: 2,
    pending: 3,
    success: 4,
  };
  return ranks[status] ?? 5;
}

function indexProgress(status?: string | null, progress?: number | null) {
  if (typeof progress === "number" && Number.isFinite(progress)) {
    return Math.max(0, Math.min(100, Math.round(progress)));
  }
  const normalized = normalizeStatus(status);
  if (normalized === "success") {
    return 100;
  }
  if (normalized === "failed") {
    return 100;
  }
  if (normalized === "running") {
    return 55;
  }
  if (normalized === "queued") {
    return 12;
  }
  return 0;
}

function chunkProgressText(indexedChunks: number, totalChunks: number) {
  if (!totalChunks && !indexedChunks) {
    return "";
  }
  return t("index.file_chunks", { indexed: Math.max(0, indexedChunks), total: Math.max(0, totalChunks) });
}

function statusLabel(status?: string | null) {
  const normalized = normalizeStatus(status);
  return t(`index.file_status_${normalized}`);
}

function stageLabel(stage?: string | null) {
  const normalized = normalizeStage(stage);
  return t(`index.file_stage_${normalized}`);
}

function statusTagType(status?: string | null) {
  const normalized = normalizeStatus(status);
  if (normalized === "success") {
    return "success";
  }
  if (normalized === "failed") {
    return "danger";
  }
  if (normalized === "running" || normalized === "queued") {
    return "warning";
  }
  return "info";
}

function progressToneClass(status?: string | null) {
  return `is-${normalizeStatus(status)}`;
}

function formatDateTime(value?: string | null) {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString(locale.value, { hour12: false });
}
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
        <el-button class="action-btn action-btn--confirm" :loading="ingesting" @click="handleRebuild">
          {{ t("index.rebuild") }}
        </el-button>
        <el-button class="action-btn action-btn--ghost" plain :loading="refreshing || indexLoading" @click="handleRefresh">
          {{ t("index.refresh") }}
        </el-button>
      </div>
    </section>

    <section class="index-monitor" v-loading="indexLoading">
      <div class="monitor-head">
        <div>
          <h2>{{ t("index.file_monitor") }}</h2>
          <p>{{ t("index.file_monitor_subtitle") }}</p>
        </div>
        <div class="monitor-stats">
          <span class="stat-pill">{{ t("index.file_total", { count: statusCounts.total }) }}</span>
          <span class="stat-pill is-working">{{ t("index.file_running", { count: statusCounts.running + statusCounts.queued }) }}</span>
          <span class="stat-pill is-success">{{ t("index.file_success", { count: statusCounts.success }) }}</span>
          <span class="stat-pill is-failed">{{ t("index.file_failed", { count: statusCounts.failed }) }}</span>
        </div>
      </div>

      <div class="monitor-tools">
        <el-select v-model="statusFilter" class="status-filter" @change="handleStatusFilterChange">
          <el-option
            v-for="option in statusFilterOptions"
            :key="option.value"
            :label="option.label"
            :value="option.value"
          />
        </el-select>
        <el-input
          v-model="keyword"
          class="keyword-input"
          clearable
          :placeholder="t('index.file_search_placeholder')"
          @clear="applyKeyword"
          @keyup.enter.exact="applyKeyword"
        />
        <el-button class="action-btn action-btn--ghost" plain @click="applyKeyword">
          {{ t("index.file_search") }}
        </el-button>
      </div>

      <el-alert v-if="indexError" class="index-error" :title="indexError" type="error" show-icon :closable="false" />

      <div v-if="fileRows.length" class="index-table-wrap">
        <div class="index-table">
        <div class="index-row index-row--head">
          <span>{{ t("index.file_name") }}</span>
          <span>{{ t("index.file_status") }}</span>
          <span>{{ t("index.file_progress") }}</span>
          <span>{{ t("index.file_updated_at") }}</span>
          <span>{{ t("index.file_error") }}</span>
        </div>

        <div v-for="row in fileRows" :key="row.id ?? row.path" class="index-row">
          <div class="file-name" :title="row.displayPath">
            <strong>{{ row.displayName }}</strong>
            <span>{{ row.folderPath }}</span>
          </div>
          <div class="status-cell">
            <el-tag size="small" effect="plain" round :type="statusTagType(row.status)">
              {{ statusLabel(row.status) }}
            </el-tag>
            <small>{{ stageLabel(row.stage) }}</small>
          </div>
          <div class="progress-cell">
            <div class="progress-line" :class="progressToneClass(row.status)">
              <span class="progress-fill" :style="{ width: `${row.progress}%` }" />
            </div>
            <span class="progress-text">{{ row.progress }}%</span>
            <span class="chunk-text">{{ row.chunkText || "-" }}</span>
          </div>
          <span class="muted">{{ formatDateTime(row.updatedAt) }}</span>
          <span class="error-cell" :title="row.errorText">
            {{ row.errorText || "-" }}
          </span>
        </div>
        </div>
      </div>

      <el-empty v-else :description="t('index.file_empty')" />

      <div v-if="indexTotal" class="pagination-row">
        <span class="pagination-total">{{ t("index.file_pagination_total", { total: indexTotal }) }}</span>
        <el-select v-model="indexPageSize" class="page-size-select" @change="handlePageSizeChange">
          <el-option
            v-for="option in pageSizeOptions"
            :key="option.value"
            :label="option.label"
            :value="option.value"
          />
        </el-select>
        <el-pagination
          :current-page="indexPage"
          :page-size="indexPageSize"
          :total="indexTotal"
          layout="prev, pager, next"
          @current-change="handlePageChange"
        />
      </div>
    </section>
  </section>
</template>

<style scoped>
.workspace-standard {
  box-sizing: border-box;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  padding: 18px 24px 28px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.tool-card,
.index-monitor {
  margin: 0;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.045);
  padding: 16px;
}

.tool-card {
  flex: 0 0 auto;
}

.index-monitor {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.index-monitor :deep(.el-empty) {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}

.status-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.status-grid article {
  border: 1px solid var(--border);
  border-radius: 8px;
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

.monitor-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  margin-bottom: 12px;
}

.monitor-head h2 {
  margin: 0;
  color: var(--text);
  font-size: 1.05rem;
  line-height: 1.35;
}

.monitor-head p {
  margin: 4px 0 0;
  color: var(--text-muted);
  font-size: 0.82rem;
}

.monitor-stats {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.monitor-tools {
  display: grid;
  grid-template-columns: 180px minmax(180px, 1fr) auto;
  gap: 10px;
  align-items: center;
  margin-bottom: 12px;
}

.status-filter,
.keyword-input {
  min-width: 0;
}

.index-error {
  margin-bottom: 12px;
  border-radius: 8px;
}

.stat-pill {
  display: inline-flex;
  align-items: center;
  min-height: 26px;
  padding: 0 10px;
  border: 1px solid rgba(100, 116, 139, 0.18);
  border-radius: 999px;
  background: #fff;
  color: #475569;
  font-size: 0.78rem;
  font-weight: 650;
  white-space: nowrap;
}

.stat-pill.is-working {
  border-color: rgba(245, 158, 11, 0.26);
  background: #fffbeb;
  color: #b45309;
}

.stat-pill.is-success {
  border-color: rgba(34, 197, 94, 0.24);
  background: #f0fdf4;
  color: #15803d;
}

.stat-pill.is-failed {
  border-color: rgba(239, 68, 68, 0.24);
  background: #fef2f2;
  color: #b91c1c;
}

.index-table-wrap {
  flex: 1 1 auto;
  min-height: 0;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #fff;
  overflow: auto;
}

.index-table {
  min-width: 980px;
}

.index-row {
  display: grid;
  grid-template-columns: minmax(280px, 1.8fr) 108px 190px 168px minmax(160px, 0.9fr);
  align-items: center;
  gap: 14px;
  min-height: 54px;
  padding: 9px 14px;
  border-top: 1px solid var(--border);
  background: #fff;
}

.index-row:first-child {
  border-top: 0;
}

.index-row--head {
  position: sticky;
  top: 0;
  z-index: 2;
  min-height: 36px;
  background: #f8fafc;
  color: var(--text-muted);
  font-size: 0.78rem;
  font-weight: 650;
}

.file-name {
  min-width: 0;
  display: grid;
  gap: 3px;
}

.file-name strong,
.file-name span,
.error-cell,
.muted {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-name strong {
  color: var(--text);
  font-size: 0.88rem;
}

.status-cell {
  min-width: 0;
  display: grid;
  justify-items: start;
  gap: 4px;
}

.status-cell small {
  max-width: 100%;
  overflow: hidden;
  color: var(--text-muted);
  font-size: 0.72rem;
  line-height: 1.2;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-name span,
.muted {
  color: var(--text-muted);
  font-size: 0.78rem;
}

.progress-cell {
  min-width: 0;
  display: grid;
  grid-template-columns: minmax(90px, 1fr) 44px;
  align-items: center;
  column-gap: 8px;
  row-gap: 4px;
}

.progress-line {
  position: relative;
  height: 7px;
  overflow: hidden;
  border-radius: 999px;
  background: #e2e8f0;
}

.progress-fill {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: #64748b;
  transition: width 0.25s ease;
}

.progress-line.is-success .progress-fill {
  background: #22c55e;
}

.progress-line.is-running .progress-fill,
.progress-line.is-queued .progress-fill {
  background: #0f766e;
}

.progress-line.is-failed .progress-fill {
  background: #ef4444;
}

.progress-text {
  color: var(--text-muted);
  font-size: 0.76rem;
  font-variant-numeric: tabular-nums;
  text-align: right;
}

.chunk-text {
  grid-column: 1 / 3;
  min-width: 0;
  overflow: hidden;
  color: var(--text-muted);
  font-size: 0.72rem;
  line-height: 1.2;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.error-cell {
  color: #b91c1c;
  font-size: 0.78rem;
}

.pagination-row {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  padding-top: 12px;
  overflow-x: auto;
}

.pagination-total {
  color: var(--text-muted);
  font-size: 0.82rem;
  white-space: nowrap;
}

.page-size-select {
  width: 108px;
  flex: 0 0 auto;
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

@media (max-width: 1080px) {
  .index-table-wrap {
    overflow-x: auto;
  }
}

@media (max-width: 720px) {
  .workspace-standard {
    padding: 12px;
  }

  .status-grid {
    grid-template-columns: 1fr;
  }

  .index-actions,
  .monitor-head {
    flex-direction: column;
    align-items: stretch;
  }

  .monitor-tools {
    display: grid;
    grid-template-columns: 1fr;
  }

  .monitor-stats {
    justify-content: flex-start;
  }

  .index-table {
    min-width: 860px;
  }
}
</style>
