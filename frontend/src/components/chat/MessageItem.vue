<script setup lang="ts">
import { computed, nextTick, ref } from "vue";
import { buildFileUrl, getFilePageText, type CitationRef } from "../../api";
import type { UiMessage } from "../../types/chat";
import MarkdownRenderer from "./MarkdownRenderer.vue";

const props = defineProps<{
  message: UiMessage;
}>();

const sourceDetailsRef = ref<HTMLDetailsElement | null>(null);
const activeCitationLabel = ref<string>("");

const viewerVisible = ref(false);
const viewerLoading = ref(false);
const viewerError = ref("");
const viewerTextHtml = ref("");
const viewerRawText = ref("");
const viewerSourcePath = ref("");
const viewerPage = ref<number | null>(null);
const viewerFileUrl = ref("");
const viewerSnippet = ref("");

function escapeHtml(raw: string): string {
  return raw
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function normalizeSnippet(text: string): string {
  return text
    .replace(/\s+/g, " ")
    .replace(/^\.{3,}/, "")
    .replace(/\.{3,}$/, "")
    .replace(/^…+/, "")
    .replace(/…+$/, "")
    .trim();
}

function highlightText(content: string, snippet: string): string {
  const safeContent = escapeHtml(content);
  const keyword = normalizeSnippet(snippet);
  if (!keyword) {
    return safeContent.replace(/\n/g, "<br/>");
  }

  const candidateKeywords = [keyword];
  if (keyword.length > 60) {
    candidateKeywords.push(keyword.slice(0, 48));
  }
  if (keyword.length > 30) {
    candidateKeywords.push(keyword.slice(0, 24));
  }

  let highlighted = safeContent;
  for (const candidate of candidateKeywords) {
    const escapedKeyword = candidate.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const regex = new RegExp(escapedKeyword, "g");
    const replaced = safeContent.replace(regex, (match) => `<mark class="citation-highlight">${match}</mark>`);
    if (replaced !== safeContent) {
      highlighted = replaced;
      break;
    }
  }

  return highlighted.replace(/\n/g, "<br/>");
}

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

function citationElementId(label: string) {
  return `${props.message.id}-cite-${label}`;
}

async function openCitationViewer(citation: CitationRef) {
  activeCitationLabel.value = citation.label;
  viewerSourcePath.value = citation.source;
  viewerPage.value = citation.page ?? 1;
  viewerSnippet.value = citation.preview || "";
  viewerFileUrl.value = buildFileUrl(citation.source) + (citation.page ? `#page=${citation.page}` : "");
  viewerVisible.value = true;
  viewerLoading.value = true;
  viewerError.value = "";
  viewerRawText.value = "";
  viewerTextHtml.value = "";

  try {
    const payload = await getFilePageText(citation.source, citation.page ?? 1);
    viewerRawText.value = payload.text || "";
    viewerTextHtml.value = highlightText(payload.text || "", citation.preview || "");
  } catch (error) {
    viewerError.value = error instanceof Error ? error.message : "Failed to load citation text.";
  } finally {
    viewerLoading.value = false;
  }
}

async function focusCitation(label: string) {
  activeCitationLabel.value = label;
  const details = sourceDetailsRef.value;
  if (details) {
    details.open = true;
    await nextTick();
    const target = document.getElementById(citationElementId(label));
    target?.scrollIntoView({
      block: "nearest",
      behavior: "smooth",
    });
  }

  const citation = citationMap.value.get(label);
  if (citation) {
    await openCitationViewer(citation);
  }
}
</script>

<template>
  <article :class="['message-row', message.role === 'user' ? 'is-user' : 'is-assistant']">
    <div class="avatar">
      {{ message.role === "user" ? "You" : "AI" }}
    </div>

    <div class="message-body">
      <div class="message-content">
        <template v-if="message.role === 'assistant'">
          <MarkdownRenderer
            :content="message.content"
            :citations="citationItems"
            @citation-click="focusCitation"
          />
        </template>
        <template v-else>
          <p class="user-text">{{ message.content }}</p>
        </template>
        <span v-if="message.streaming" class="stream-cursor">|</span>
      </div>

      <p v-if="message.failed" class="failed-note">Request failed. Please retry.</p>

      <details v-if="message.sources.length" ref="sourceDetailsRef" class="source-details">
        <summary>Sources ({{ message.sources.length }})</summary>

        <div v-if="citationItems.length" class="citation-index">
          <h4>Evidence Tags</h4>
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
              <span v-if="citation.page !== null && citation.page !== undefined">p{{ citation.page }}</span>
              <span v-if="citation.score !== null && citation.score !== undefined">score {{ citation.score }}</span>
              <span v-if="citation.chunk_indices.length">chunks {{ citation.chunk_indices.join(", ") }}</span>
            </li>
          </ul>
        </div>

        <ul>
          <li v-for="(source, index) in message.sources" :key="`${message.id}-${index}`">
            <div class="source-head">
              <strong>[{{ index + 1 }}] {{ source.source }}</strong>
              <span>chunk {{ source.chunk_index }}</span>
              <span v-if="source.page !== null && source.page !== undefined">p{{ source.page }}</span>
              <span v-if="source.score !== null && source.score !== undefined">score {{ source.score }}</span>
            </div>
            <p>{{ source.preview }}</p>
          </li>
        </ul>
      </details>
    </div>
  </article>

  <el-dialog
    v-model="viewerVisible"
    width="88%"
    top="4vh"
    append-to-body
    :title="viewerSourcePath || 'Citation Viewer'"
    class="citation-dialog"
  >
    <section class="viewer-shell">
      <aside class="viewer-pane text-pane">
        <header>
          <strong>引用定位</strong>
          <small v-if="viewerPage !== null">page {{ viewerPage }}</small>
        </header>
        <p v-if="viewerSnippet" class="snippet-pill">{{ viewerSnippet }}</p>
        <el-skeleton v-if="viewerLoading" :rows="8" animated />
        <p v-else-if="viewerError" class="viewer-error">{{ viewerError }}</p>
        <div v-else class="citation-text" v-html="viewerTextHtml"></div>
      </aside>

      <aside class="viewer-pane file-pane">
        <header>
          <strong>原文件</strong>
          <a :href="viewerFileUrl" target="_blank" rel="noreferrer">新窗口打开</a>
        </header>
        <iframe
          v-if="viewerFileUrl"
          class="file-frame"
          :src="viewerFileUrl"
          title="source file viewer"
        ></iframe>
      </aside>
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
  padding: 4px 6px;
}

.citation-row.is-active {
  background: #d8f3ea;
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

.viewer-shell {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  height: 74vh;
}

.viewer-pane {
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  background: #fff;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.viewer-pane > header {
  padding: 10px 12px;
  border-bottom: 1px solid #eef0f3;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}

.viewer-pane > header small {
  color: #64748b;
}

.text-pane {
  padding-bottom: 10px;
}

.snippet-pill {
  margin: 10px 12px 0;
  padding: 8px 10px;
  border-radius: 8px;
  background: #e4f7ef;
  border: 1px solid #9fd9d1;
  color: #115e59;
  font-size: 0.86rem;
}

.viewer-error {
  margin: 12px;
  color: #b42318;
}

.citation-text {
  margin: 10px 12px;
  overflow: auto;
  line-height: 1.76;
  color: #1f2937;
  white-space: normal;
}

.citation-text :deep(mark.citation-highlight) {
  background: #bff3dd;
  color: #114b5f;
  border-radius: 3px;
  padding: 0 2px;
}

.file-frame {
  width: 100%;
  height: 100%;
  border: 0;
  border-radius: 0 0 12px 12px;
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

@media (max-width: 980px) {
  .viewer-shell {
    grid-template-columns: 1fr;
    height: auto;
    min-height: 72vh;
  }

  .file-pane {
    min-height: 340px;
  }
}
</style>
