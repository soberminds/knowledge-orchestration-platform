<script setup lang="ts">
import { computed } from "vue";
import type { DocumentInfo, HealthResponse } from "../../api";
import { useI18n } from "../../composables/useI18n";

const props = defineProps<{
  health: HealthResponse | null;
  documents: DocumentInfo[];
  statusText: string;
  indexedChunks: number;
  ingesting: boolean;
  refreshing: boolean;
}>();

defineEmits<{
  (event: "rebuild"): void;
  (event: "refresh"): void;
}>();

const { locale, t } = useI18n();

const fileRows = computed(() =>
  props.documents
    .filter((item) => !item.is_directory)
    .map((item) => ({
      ...item,
      displayName: item.name || basenameOf(item.display_path || item.path),
      displayPath: item.display_path || item.path,
      folderPath: parentPathOf(item.display_path || item.path),
      status: normalizeStatus(item.index_status || item.parse_status),
      progress: indexProgress(item.index_status || item.parse_status),
      updatedAt: item.last_indexed_at || item.modified_at,
      errorText: item.parse_error || "",
    }))
    .sort((left, right) => {
      const rankDiff = statusRank(left.status) - statusRank(right.status);
      if (rankDiff !== 0) {
        return rankDiff;
      }
      return left.displayName.localeCompare(right.displayName, locale.value);
    }),
);

const statusCounts = computed(() => {
  const counts = {
    total: fileRows.value.length,
    pending: 0,
    queued: 0,
    running: 0,
    success: 0,
    failed: 0,
  };

  for (const row of fileRows.value) {
    if (row.status === "queued") {
      counts.queued += 1;
    } else if (row.status === "running") {
      counts.running += 1;
    } else if (row.status === "success") {
      counts.success += 1;
    } else if (row.status === "failed") {
      counts.failed += 1;
    } else {
      counts.pending += 1;
    }
  }

  return counts;
});

function normalizeStatus(status?: string | null) {
  const normalized = String(status || "pending").trim().toLowerCase();
  if (["queued", "running", "success", "failed", "pending"].includes(normalized)) {
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

function indexProgress(status?: string | null) {
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

function statusLabel(status?: string | null) {
  const normalized = normalizeStatus(status);
  return t(`index.file_status_${normalized}`);
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
        <el-button class="action-btn action-btn--confirm" :loading="ingesting" @click="$emit('rebuild')">
          {{ t("index.rebuild") }}
        </el-button>
        <el-button class="action-btn action-btn--ghost" plain :loading="refreshing" @click="$emit('refresh')">
          {{ t("index.refresh") }}
        </el-button>
      </div>
    </section>

    <section class="index-monitor">
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
          </div>
          <div class="progress-cell">
            <div class="progress-line" :class="progressToneClass(row.status)">
              <span class="progress-fill" :style="{ width: `${row.progress}%` }" />
            </div>
            <span class="progress-text">{{ row.progress }}%</span>
          </div>
          <span class="muted">{{ formatDateTime(row.updatedAt) }}</span>
          <span class="error-cell" :title="row.errorText">
            {{ row.errorText || "-" }}
          </span>
        </div>
        </div>
      </div>

      <el-empty v-else :description="t('index.file_empty')" />
    </section>
  </section>
</template>

<style scoped>
.workspace-standard {
  height: 100%;
  min-height: 0;
  overflow: auto;
  padding: 18px 24px 28px;
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

.index-monitor {
  margin-top: 14px;
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
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #fff;
  overflow: hidden;
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

.file-name span,
.muted {
  color: var(--text-muted);
  font-size: 0.78rem;
}

.progress-cell {
  min-width: 0;
  display: grid;
  grid-template-columns: minmax(90px, 1fr) 38px;
  align-items: center;
  gap: 8px;
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

.error-cell {
  color: #b91c1c;
  font-size: 0.78rem;
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

  .monitor-stats {
    justify-content: flex-start;
  }

  .index-table {
    min-width: 860px;
  }
}
</style>
