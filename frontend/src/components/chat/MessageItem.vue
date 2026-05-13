<script setup lang="ts">
import { computed, nextTick, ref } from "vue";
import type { CitationRef } from "../../api";
import { useI18n } from "../../composables/useI18n";
import type { UiMessage } from "../../types/chat";
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

function citationElementId(label: string) {
  return `${props.message.id}-cite-${label}`;
}

function openCitationViewer(citation: CitationRef) {
  if (/^https?:\/\//i.test(citation.source)) {
    window.open(citation.source, "_blank", "noopener,noreferrer");
    return;
  }

  activeCitationLabel.value = citation.label;
  viewerError.value = "";
  viewerSourcePath.value = citation.source;
  viewerPage.value = Math.max(1, citation.page ?? 1);
  viewerSnippet.value = citation.preview || "";
  viewerVisible.value = true;
}

function onViewerDialogOpened() {
  viewerRef.value?.refreshViewer?.();
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
      <p v-if="usageSummary || costSummary" class="usage-note">
        <span v-if="usageSummary">{{ usageSummary }}</span>
        <span v-if="usageSummary && costSummary">{{ t("message.separator") }}</span>
        <span v-if="costSummary">{{ costSummary }}</span>
      </p>

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
              <span class="citation-source">{{ citation.source }}</span>
              <span v-if="citation.page !== null && citation.page !== undefined">{{ t("message.page_prefix") }}{{ citation.page }}</span>
              <span v-if="citation.score !== null && citation.score !== undefined">{{ t("message.score_prefix") }} {{ citation.score }}</span>
              <span v-if="citation.chunk_indices.length">{{ t("message.chunks_prefix") }} {{ citation.chunk_indices.join(", ") }}</span>
            </li>
          </ul>
        </div>

        <ul>
          <li v-for="(source, index) in message.sources" :key="`${message.id}-${index}`">
            <div class="source-head">
              <strong>[{{ index + 1 }}] {{ source.source }}</strong>
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
</template>

<style scoped>
.message-row {
  width: 100%;
  max-width: 100%;
  display: grid;
  grid-template-columns: 40px minmax(0, 1fr);
  gap: 12px;
}

.message-row.is-user {
  justify-self: end;
  width: min(78%, 900px);
  grid-template-columns: minmax(0, 1fr) 40px;
}

.message-row.is-user .avatar {
  order: 2;
  background: #111827;
  color: #fff;
}

.message-row.is-user .message-body {
  order: 1;
  background: #eef2ff;
  border: 1px solid #dbe2ff;
  border-radius: 12px;
  padding: 10px 14px;
}

.avatar {
  width: 36px;
  height: 36px;
  border-radius: 11px;
  background: #10a37f;
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
  color: #64748b;
  font-size: 0.8rem;
}

.source-details {
  margin-top: 10px;
  padding: 8px 10px;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  background: #fafafa;
}

.source-details summary {
  cursor: pointer;
  color: #6b7280;
  font-size: 0.88rem;
}

.citation-index {
  margin-top: 10px;
  padding: 8px;
  border: 1px solid #d7ebea;
  border-radius: 8px;
  background: #f0fbf9;
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
  color: #334155;
  border-radius: 8px;
  padding: 5px 6px;
}

.citation-row.is-active {
  background: linear-gradient(90deg, rgba(16, 163, 127, 0.16), rgba(16, 163, 127, 0.05));
}

.citation-link {
  border: 1px solid #9fd9d1;
  background: #ecfdf8;
  border-radius: 999px;
  color: #0f766e;
  font-weight: 700;
  padding: 2px 8px;
  cursor: pointer;
}

.citation-source {
  color: #0f172a;
}

.source-details ul {
  margin: 8px 0 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 8px;
}

.source-details li {
  border-top: 1px dashed #e5e7eb;
  padding-top: 8px;
  font-size: 0.86rem;
  color: #374151;
}

.source-details li:first-child {
  border-top: 0;
  padding-top: 0;
}

.source-head {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  color: #6b7280;
}

.source-head strong {
  color: #0f172a;
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
