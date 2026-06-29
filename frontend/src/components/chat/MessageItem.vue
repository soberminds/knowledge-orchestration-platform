<script setup lang="ts">
import { computed, nextTick, ref } from "vue";
import type { CitationRef } from "../../api";
import { useI18n } from "../../composables/useI18n";
import type { UiMessage } from "../../types/chat";
import { isOnlyOfficeDocument } from "../../utils/documentRouting";
import OnlyOfficeEditor from "../viewer/OnlyOfficeEditor.vue";
import UnifiedFileViewer from "../viewer/UnifiedFileViewer.vue";
import MarkdownRenderer from "./MarkdownRenderer.vue";

const props = defineProps<{
  message: UiMessage;
}>();

const sourceDetailsRef = ref<HTMLDetailsElement | null>(null);
const activeCitationLabel = ref("");

const viewerVisible = ref(false);
const viewerSourcePath = ref("");
const viewerPage = ref(1);
const viewerSnippet = ref("");
const viewerError = ref("");
const viewerRef = ref<InstanceType<typeof UnifiedFileViewer> | null>(null);

const officeViewerVisible = ref(false);
const officeViewerSourcePath = ref("");
const officeViewerError = ref("");
const officeViewerRef = ref<InstanceType<typeof OnlyOfficeEditor> | null>(null);

const { t } = useI18n();

const citationItems = computed<CitationRef[]>(() => {
  if (props.message.citations.length) {
    return props.message.citations;
  }

  return props.message.sources.map((source, index) => ({
    label: `S${index + 1}`,
    source: source.source,
    page: source.page ?? null,
    chunk_indices: [source.chunk_index],
    score: source.score ?? null,
    preview: source.preview,
    file_id: source.file_id ?? null,
    folder_id: source.folder_id ?? null,
    display_name: source.display_name ?? null,
    display_path: source.display_path ?? null,
    folder_path: source.folder_path ?? null,
  }));
});

const citationMap = computed(() => {
  const map = new Map<string, CitationRef>();
  for (const citation of citationItems.value) {
    map.set(citation.label, citation);
  }
  return map;
});

const usageSummary = computed(() => {
  if (props.message.role !== "assistant" || !props.message.usage) {
    return "";
  }
  const usage = props.message.usage;
  return t("message.tokens_summary", {
    prompt: usage.prompt_tokens,
    completion: usage.completion_tokens,
    total: usage.total_tokens,
  });
});

const modelSummary = computed(() => {
  if (props.message.role !== "assistant" || !props.message.model) {
    return "";
  }
  return t("message.model_used", { model: props.message.model });
});

const costSummary = computed(() => {
  if (
    props.message.role !== "assistant" ||
    props.message.costEstimate == null ||
    props.message.costEstimate.total_cost == null
  ) {
    return "";
  }
  const cost = props.message.costEstimate;
  const currency = cost.currency || "CNY";
  const total = Number(cost.total_cost || 0).toFixed(6);
  const model = props.message.model ? `${props.message.model} ` : "";
  return t("message.estimated_cost", { model, currency, total });
});

const costHintSummary = computed(() => {
  if (
    props.message.role !== "assistant" ||
    !props.message.usage ||
    props.message.costEstimate?.total_cost != null
  ) {
    return "";
  }
  if (!props.message.model) {
    return t("message.cost_not_configured");
  }
  return t("message.cost_not_configured_with_model", { model: props.message.model });
});

const diagnosticsSummary = computed(() => {
  if (props.message.role !== "assistant" || !props.message.modelDiagnostics) {
    return "";
  }
  const diagnostics = props.message.modelDiagnostics;
  const parts = [
    `provider=${diagnostics.provider || "-"}`,
    `requested=${diagnostics.requested_model || "-"}`,
    `resolved=${diagnostics.resolved_model || props.message.model || "-"}`,
    `nativeWeb=${diagnostics.native_web_search_used ? "on" : "off"}`,
    `externalWeb=${diagnostics.external_web_search_used ? "on" : "off"}`,
    `thinking=${diagnostics.thinking_mode || "-"}`,
  ];
  if (diagnostics.option_fallback_used) {
    parts.push("fallback=on");
  }
  return parts.join(", ");
});

const diagnosticsWarnings = computed(() => {
  if (props.message.role !== "assistant" || !props.message.modelDiagnostics?.warnings?.length) {
    return [];
  }
  return props.message.modelDiagnostics.warnings;
});

function citationElementId(label: string) {
  return `${props.message.id}-cite-${label}`;
}

function citationDisplayPath(citation: CitationRef) {
  return citation.display_path || citation.source;
}

function sourceDisplayPath(source: { display_path?: string | null; source: string }) {
  return source.display_path || source.source;
}

function resetTextViewerState() {
  viewerSourcePath.value = "";
  viewerPage.value = 1;
  viewerSnippet.value = "";
  viewerError.value = "";
}

function resetOfficeViewerState() {
  officeViewerSourcePath.value = "";
  officeViewerError.value = "";
}

function openCitationViewer(citation: CitationRef) {
  if (/^https?:\/\//i.test(citation.source)) {
    window.open(citation.source, "_blank", "noopener,noreferrer");
    return;
  }

  activeCitationLabel.value = citation.label;

  if (isOnlyOfficeDocument(citation.source)) {
    viewerVisible.value = false;
    resetTextViewerState();
    officeViewerError.value = "";
    officeViewerSourcePath.value = citation.source;
    officeViewerVisible.value = true;
    return;
  }

  if (officeViewerVisible.value) {
    officeViewerVisible.value = false;
  }
  resetOfficeViewerState();
  viewerError.value = "";
  viewerSourcePath.value = citation.source;
  viewerPage.value = Math.max(1, citation.page ?? 1);
  viewerSnippet.value = citation.preview || "";
  viewerVisible.value = true;
}

function onViewerDialogOpened() {
  viewerRef.value?.refreshViewer?.();
}

function onOfficeViewerDialogOpened() {
  officeViewerRef.value?.resizeEditor?.();
}

function onOfficeViewerDialogClosed() {
  resetOfficeViewerState();
}

async function focusCitation(label: string) {
  activeCitationLabel.value = label;
  const details = sourceDetailsRef.value;
  if (details) {
    details.open = true;
    await nextTick();
    const target = document.getElementById(citationElementId(label));
    target?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  const citation = citationMap.value.get(label);
  if (citation) {
    openCitationViewer(citation);
  }
}
</script>

<template>
  <article :class="['message-row', message.role === 'user' ? 'is-user' : 'is-assistant']">
    <div class="avatar">
      {{ message.role === "user" ? t("message.you") : t("message.ai") }}
    </div>

    <div class="message-body">
      <div class="message-content">
        <template v-if="message.role === 'assistant'">
          <MarkdownRenderer :content="message.content" :citations="citationItems" @citation-click="focusCitation" />
        </template>
        <template v-else>
          <p class="user-text">{{ message.content }}</p>
        </template>
        <span v-if="message.streaming" class="stream-cursor">|</span>
      </div>

      <p v-if="message.failed" class="failed-note">{{ t("message.request_failed_retry") }}</p>
      <p v-if="modelSummary || usageSummary || costSummary || costHintSummary || diagnosticsSummary" class="usage-note">
        <span v-if="modelSummary">{{ modelSummary }}</span>
        <span v-if="modelSummary && (usageSummary || costSummary || costHintSummary || diagnosticsSummary)">{{ t("message.separator") }}</span>
        <span v-if="usageSummary">{{ usageSummary }}</span>
        <span v-if="usageSummary && (costSummary || costHintSummary || diagnosticsSummary)">{{ t("message.separator") }}</span>
        <span v-if="costSummary">{{ costSummary }}</span>
        <span v-else-if="costHintSummary">{{ costHintSummary }}</span>
        <span v-if="(costSummary || costHintSummary) && diagnosticsSummary">{{ t("message.separator") }}</span>
        <span v-if="diagnosticsSummary">{{ diagnosticsSummary }}</span>
      </p>
      <ul v-if="diagnosticsWarnings.length" class="diagnostics-warnings">
        <li v-for="warning in diagnosticsWarnings" :key="warning">{{ warning }}</li>
      </ul>

      <details v-if="message.sources.length" ref="sourceDetailsRef" class="source-details">
        <summary>{{ t("message.sources_count", { count: message.sources.length }) }}</summary>

        <div v-if="citationItems.length" class="citation-index">
          <h4>{{ t("message.evidence_tags") }}</h4>
          <ul>
            <li
              v-for="citation in citationItems"
              :id="citationElementId(citation.label)"
              :key="`${message.id}-citation-${citation.label}`"
              :class="['citation-row', activeCitationLabel === citation.label ? 'is-active' : '']"
            >
              <button class="citation-link" @click.prevent="openCitationViewer(citation)">
                [{{ citation.label }}]
              </button>
              <span class="citation-source">{{ citationDisplayPath(citation) }}</span>
              <span v-if="citation.page !== null && citation.page !== undefined">{{ t("message.page_prefix") }}{{ citation.page }}</span>
              <span v-if="citation.score !== null && citation.score !== undefined">{{ t("message.score_prefix") }} {{ citation.score }}</span>
              <span v-if="citation.chunk_indices.length">{{ t("message.chunks_prefix") }} {{ citation.chunk_indices.join(", ") }}</span>
            </li>
          </ul>
        </div>

        <ul>
          <li v-for="(source, index) in message.sources" :key="`${message.id}-${index}`">
            <div class="source-head">
              <strong>[{{ index + 1 }}] {{ sourceDisplayPath(source) }}</strong>
              <span>{{ t("message.chunk") }} {{ source.chunk_index }}</span>
              <span v-if="source.page !== null && source.page !== undefined">{{ t("message.page_prefix") }}{{ source.page }}</span>
              <span v-if="source.score !== null && source.score !== undefined">{{ t("message.score_prefix") }} {{ source.score }}</span>
            </div>
            <p>{{ source.preview }}</p>
          </li>
        </ul>
      </details>
    </div>
  </article>

  <el-dialog
    v-model="viewerVisible"
    width="92%"
    top="3vh"
    append-to-body
    class="citation-dialog"
    :title="viewerSourcePath || t('message.citation_viewer_title')"
    @opened="onViewerDialogOpened"
  >
    <section class="viewer-host">
      <el-alert
        v-if="viewerError"
        :title="viewerError"
        type="error"
        show-icon
        :closable="false"
        class="viewer-error-banner"
      />
      <UnifiedFileViewer
        ref="viewerRef"
        :source-path="viewerSourcePath"
        :page="viewerPage"
        :snippet="viewerSnippet"
        :active="viewerVisible"
        @error="viewerError = $event"
      />
    </section>
  </el-dialog>

  <el-dialog
    v-model="officeViewerVisible"
    width="96%"
    top="2vh"
    append-to-body
    destroy-on-close
    class="citation-office-dialog"
    :title="officeViewerSourcePath || t('documents.open')"
    @opened="onOfficeViewerDialogOpened"
    @closed="onOfficeViewerDialogClosed"
  >
    <section class="viewer-host office-viewer-host">
      <el-alert
        v-if="officeViewerError"
        :title="officeViewerError"
        type="error"
        show-icon
        :closable="false"
        class="viewer-error-banner"
      />
      <OnlyOfficeEditor
        ref="officeViewerRef"
        :visible="officeViewerVisible"
        :source-path="officeViewerSourcePath"
        mode="view"
        @error="officeViewerError = $event"
      />
    </section>
  </el-dialog>
</template>

<style scoped>
.message-row {
  width: 100%;
  max-width: 100%;
  display: grid;
  grid-template-columns: 38px minmax(0, 1fr);
  gap: 10px;
}

.message-row.is-user {
  justify-self: end;
  width: min(76%, 860px);
  grid-template-columns: minmax(0, 1fr) 38px;
}

.message-row.is-user .avatar {
  order: 2;
  background: #0f766e;
  color: #fff;
}

.message-row.is-user .message-body {
  order: 1;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 10px 13px;
  box-shadow: 0 8px 20px rgba(15, 23, 42, 0.04);
}

.avatar {
  width: 34px;
  height: 34px;
  border-radius: 11px;
  background: linear-gradient(135deg, #0f766e 0%, #14b8a6 100%);
  color: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 0.8rem;
  font-weight: 700;
}

.message-body {
  padding: 2px 0;
}

.message-content {
  position: relative;
}

.user-text {
  margin: 0;
  line-height: 1.7;
  white-space: pre-wrap;
}

.stream-cursor {
  display: inline-block;
  margin-left: 2px;
  animation: blink 1s steps(2, start) infinite;
}

.failed-note {
  margin: 0.35rem 0 0;
  color: #b42318;
  font-size: 0.84rem;
}

.usage-note {
  margin: 0.38rem 0 0;
  color: var(--text-muted);
  font-size: 0.8rem;
}

.diagnostics-warnings {
  margin: 0.35rem 0 0;
  padding-left: 1rem;
  color: #b45309;
  font-size: 0.8rem;
}

.source-details {
  margin-top: 10px;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--surface-subtle);
}

.source-details summary {
  cursor: pointer;
  color: var(--text-muted);
  font-size: 0.88rem;
}

.citation-index {
  margin-top: 10px;
  padding: 8px;
  border: 1px solid rgba(20, 184, 166, 0.12);
  border-radius: 10px;
  background: rgba(236, 253, 249, 0.72);
}

.citation-index h4 {
  margin: 0 0 6px;
  font-size: 0.82rem;
  color: #0f766e;
}

.citation-index ul {
  margin: 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 5px;
}

.citation-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  font-size: 0.82rem;
  color: var(--text);
  border-radius: 8px;
  padding: 5px 6px;
}

.citation-row.is-active {
  background: linear-gradient(90deg, rgba(20, 184, 166, 0.14), rgba(20, 184, 166, 0.04));
}

.citation-link {
  border: 1px solid rgba(20, 184, 166, 0.24);
  background: rgba(236, 253, 249, 0.92);
  border-radius: 999px;
  color: #0f766e;
  font-weight: 700;
  padding: 2px 8px;
  cursor: pointer;
}

.citation-source {
  color: var(--text);
}

.source-details ul {
  margin: 8px 0 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 8px;
}

.source-details li {
  border-top: 1px dashed var(--border);
  padding-top: 8px;
  font-size: 0.86rem;
  color: var(--text);
}

.source-details li:first-child {
  border-top: 0;
  padding-top: 0;
}

.source-head {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  color: var(--text-muted);
}

.source-head strong {
  color: var(--text);
}

.source-details li p {
  margin: 6px 0 0;
  line-height: 1.65;
}

.viewer-host {
  display: grid;
  gap: 10px;
}

.viewer-error-banner {
  margin-bottom: 2px;
}

.office-viewer-host {
  min-height: 0;
  height: 82vh;
  display: flex;
  flex-direction: column;
}

.office-viewer-host :deep(.onlyoffice-root) {
  flex: 1;
  min-height: 0;
}

:deep(.el-dialog.citation-office-dialog) {
  display: flex;
  flex-direction: column;
  max-height: calc(100vh - 4vh);
}

:deep(.citation-office-dialog .el-dialog__body) {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 10px 12px 12px;
}

@keyframes blink {
  0%,
  49% {
    opacity: 1;
  }
  50%,
  100% {
    opacity: 0;
  }
}
</style>
