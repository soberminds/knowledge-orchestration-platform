<script setup lang="ts">
import { computed } from "vue";
import type { OfficeHealthResponse } from "../../api";
import { useI18n } from "../../composables/useI18n";

const props = defineProps<{
  health: OfficeHealthResponse | null;
  loading: boolean;
  error?: string;
}>();

const emit = defineEmits<{
  (event: "refresh"): void;
}>();

const { locale, t } = useI18n();

const checkedAtText = computed(() => {
  const raw = props.health?.checked_at;
  if (!raw) {
    return t("documents.office_health_not_checked");
  }
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) {
    return raw;
  }
  return date.toLocaleString(locale.value, { hour12: false });
});

function boolLabel(value: boolean | null | undefined) {
  if (value === true) return t("documents.office_health_yes");
  if (value === false) return t("documents.office_health_no");
  return t("documents.office_health_unknown");
}
</script>

<template>
  <section class="office-health-panel">
    <header class="panel-head">
      <div>
        <h3>{{ t("documents.office_health_title") }}</h3>
        <p>{{ t("documents.office_health_checked_at", { time: checkedAtText }) }}</p>
      </div>
      <el-button size="small" :loading="loading" @click="emit('refresh')">
        {{ t("documents.office_health_refresh") }}
      </el-button>
    </header>

    <p class="panel-subtitle">{{ t("documents.office_health_subtitle") }}</p>

    <el-alert
      v-if="error"
      :title="error"
      type="error"
      show-icon
      :closable="false"
      class="panel-alert"
    />

    <section class="summary-grid">
      <article class="summary-card">
        <span>{{ t("documents.office_health_configured") }}</span>
        <strong :class="{ bad: !health?.configured, ok: !!health?.configured }">
          {{ boolLabel(health?.configured ?? false) }}
        </strong>
      </article>
      <article class="summary-card">
        <span>{{ t("documents.office_health_ds_reachable") }}</span>
        <strong :class="{ bad: !health?.document_server_reachable, ok: !!health?.document_server_reachable }">
          {{ boolLabel(health?.document_server_reachable) }}
        </strong>
      </article>
      <article class="summary-card">
        <span>{{ t("documents.office_health_jwt_match") }}</span>
        <strong :class="{ bad: health?.jwt_match === false, ok: health?.jwt_match === true }">
          {{ boolLabel(health?.jwt_match) }}
        </strong>
      </article>
      <article class="summary-card">
        <span>{{ t("documents.office_health_callback_reachable") }}</span>
        <strong :class="{ bad: !health?.callback_reachable, ok: !!health?.callback_reachable }">
          {{ boolLabel(health?.callback_reachable) }}
        </strong>
      </article>
    </section>

    <section v-if="health" class="meta-lines">
      <p>
        <span>{{ t("documents.office_health_url") }}:</span>
        <code>{{ health.document_server_url || "-" }}</code>
      </p>
      <p v-if="health.document_server_internal_url">
        <span>{{ t("documents.office_health_internal_url") }}:</span>
        <code>{{ health.document_server_internal_url }}</code>
      </p>
      <p>
        <span>{{ t("documents.office_health_backend_url") }}:</span>
        <code>{{ health.public_backend_url }}</code>
      </p>
      <p>
        <span>{{ t("documents.office_health_ds_version") }}:</span>
        <code>{{ health.document_server_version || "-" }}</code>
      </p>
      <p>
        <span>{{ t("documents.office_health_index_mode", { mode: health.index_update_mode }) }}</span>
      </p>
      <p>
        <span>{{ t("documents.office_health_auto_rebuild", { value: boolLabel(health.auto_rebuild_index_on_save) }) }}</span>
      </p>
      <p>
        <span>{{ t("documents.office_health_ds_status", { status: health.document_server_http_status ?? "-" }) }}</span>
      </p>
      <p>
        <span>{{ t("documents.office_health_command_status", { status: health.command_service_http_status ?? "-" }) }}</span>
      </p>
      <p>
        <span>{{ t("documents.office_health_callback_status", { status: health.callback_http_status ?? "-" }) }}</span>
      </p>
    </section>

    <section v-if="health?.notes?.length" class="notes">
      <h4>{{ t("documents.office_health_notes") }}</h4>
      <ul>
        <li v-for="note in health.notes" :key="note">{{ note }}</li>
      </ul>
    </section>
  </section>
</template>

<style scoped>
.office-health-panel {
  margin: 0 24px 14px;
  padding: 12px;
  border-radius: 14px;
  border: 1px solid #d7dee8;
  background: linear-gradient(180deg, #f7fbff 0%, #ffffff 58%);
  display: grid;
  gap: 9px;
}

.panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}

.panel-head h3 {
  margin: 0;
  font-size: 0.98rem;
}

.panel-head p {
  margin: 2px 0 0;
  color: #5f6b7a;
  font-size: 0.8rem;
}

.panel-subtitle {
  margin: 0;
  color: #5f6b7a;
  font-size: 0.82rem;
}

.panel-alert {
  margin-top: 2px;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.summary-card {
  border: 1px solid #d7dee8;
  background: #fff;
  border-radius: 10px;
  padding: 8px 10px;
  display: grid;
  gap: 4px;
}

.summary-card span {
  color: #6b7280;
  font-size: 0.76rem;
}

.summary-card strong {
  font-size: 0.96rem;
  line-height: 1.3;
}

.summary-card strong.ok {
  color: #0f8a5f;
}

.summary-card strong.bad {
  color: #b63a3a;
}

.meta-lines {
  display: grid;
  gap: 4px;
}

.meta-lines p {
  margin: 0;
  font-size: 0.82rem;
  color: #455468;
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.meta-lines code {
  font-family: "JetBrains Mono", "Consolas", monospace;
  background: #f3f6fa;
  border-radius: 6px;
  padding: 1px 6px;
  word-break: break-all;
}

.notes h4 {
  margin: 0 0 6px;
  font-size: 0.86rem;
  color: #374151;
}

.notes ul {
  margin: 0;
  padding-left: 18px;
  color: #b14242;
  font-size: 0.8rem;
  display: grid;
  gap: 4px;
}

@media (max-width: 900px) {
  .summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .office-health-panel {
    margin-left: 12px;
    margin-right: 12px;
  }
}
</style>
