<script setup lang="ts">
import { computed, nextTick, ref } from "vue";
import type { CitationRef } from "../../api";
import type { UiMessage } from "../../types/chat";
import MarkdownRenderer from "./MarkdownRenderer.vue";

const props = defineProps<{
  message: UiMessage;
}>();

const sourceDetailsRef = ref<HTMLDetailsElement | null>(null);

const citationItems = computed<CitationRef[]>(() => {
  if (props.message.citations.length) {
    return props.message.citations;
  }
  // Backward-compatible fallback for old messages without citation metadata.
  return props.message.sources.map((source, index) => ({
    label: `S${index + 1}`,
    source: source.source,
    page: source.page ?? null,
    chunk_indices: [source.chunk_index],
    score: source.score ?? null,
  }));
});

function citationElementId(label: string) {
  return `${props.message.id}-cite-${label}`;
}

async function focusCitation(label: string) {
  const details = sourceDetailsRef.value;
  if (!details) {
    return;
  }
  details.open = true;
  await nextTick();
  const target = document.getElementById(citationElementId(label));
  target?.scrollIntoView({
    block: "nearest",
    behavior: "smooth",
  });
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
            >
              <span class="citation-label">[{{ citation.label }}]</span>
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
</template>

<style scoped>
.message-row {
  max-width: 860px;
  display: grid;
  grid-template-columns: 40px minmax(0, 1fr);
  gap: 12px;
}

.message-row.is-user {
  margin-left: auto;
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

.citation-index li {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 0.82rem;
  color: #334155;
}

.citation-label {
  color: #0f766e;
  font-weight: 700;
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

@media (max-width: 720px) {
  .message-row {
    max-width: 100%;
  }
}
</style>
