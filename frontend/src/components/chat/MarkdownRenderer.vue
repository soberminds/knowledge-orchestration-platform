<script setup lang="ts">
import MarkdownIt from "markdown-it";
import { computed, ref } from "vue";
import type { CitationRef } from "../../api";

const props = defineProps<{
  content: string;
  citations?: CitationRef[];
}>();

const emit = defineEmits<{
  (event: "citation-click", label: string): void;
}>();

const containerRef = ref<HTMLElement | null>(null);

const markdown = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
  typographer: true,
});

const knownLabels = computed(() => {
  const set = new Set<string>();
  for (const item of props.citations ?? []) {
    set.add(item.label);
  }
  return set;
});

const preparedContent = computed(() => {
  const text = props.content || "";
  return text.replace(/\[(S\d+)\]/g, (match, label: string) => {
    if (!knownLabels.value.has(label)) {
      return match;
    }
    return `[${label}](#cite-${label})`;
  });
});

const renderedHtml = computed(() => markdown.render(preparedContent.value));
const useRawFallback = computed(() => {
  if (!props.content) {
    return false;
  }
  const plainText = renderedHtml.value
    .replace(/<[^>]*>/g, "")
    .replace(/&nbsp;/g, " ")
    .trim();
  return plainText.length === 0;
});

function onContainerClick(event: MouseEvent) {
  const target = event.target as HTMLElement | null;
  if (!target) {
    return;
  }
  const anchor = target.closest("a");
  if (!anchor) {
    return;
  }
  const href = anchor.getAttribute("href") ?? "";
  if (!href.startsWith("#cite-")) {
    return;
  }
  event.preventDefault();
  const label = href.slice("#cite-".length);
  if (!label) {
    return;
  }
  emit("citation-click", label);
}
</script>

<template>
  <pre v-if="useRawFallback" class="raw-fallback">{{ content }}</pre>
  <div
    v-else
    ref="containerRef"
    class="markdown-body"
    v-html="renderedHtml"
    @click="onContainerClick"
  ></div>
</template>

<style scoped>
.raw-fallback {
  margin: 0;
  white-space: pre-wrap;
  line-height: 1.76;
  color: #111827;
}

.markdown-body {
  color: #111827;
  line-height: 1.76;
  word-break: break-word;
}

.markdown-body :deep(p) {
  margin: 0.32rem 0;
}

.markdown-body :deep(pre) {
  margin: 0.6rem 0;
  padding: 0.75rem 0.85rem;
  border-radius: 10px;
  background: #f3f4f6;
  border: 1px solid #e5e7eb;
  overflow-x: auto;
}

.markdown-body :deep(code) {
  font-family: "JetBrains Mono", "Consolas", monospace;
  font-size: 0.85em;
}

.markdown-body :deep(:not(pre) > code) {
  padding: 0.12rem 0.35rem;
  border-radius: 8px;
  background: #f3f4f6;
  border: 1px solid #e5e7eb;
}

.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  margin: 0.45rem 0;
  padding-left: 1.35rem;
}

.markdown-body :deep(blockquote) {
  margin: 0.55rem 0;
  padding: 0.5rem 0.8rem;
  border-left: 3px solid #d1d5db;
  background: #f8fafc;
  color: #334155;
}

.markdown-body :deep(a) {
  color: #0f766e;
}

.markdown-body :deep(a[href^="#cite-"]) {
  display: inline-block;
  margin: 0 2px;
  padding: 0.04rem 0.4rem;
  border: 1px solid #9fd9d1;
  border-radius: 999px;
  background: #ecfdf8;
  color: #0f766e;
  text-decoration: none;
  font-weight: 600;
}

.markdown-body :deep(a[href^="#cite-"]:hover) {
  background: #dff7f2;
}
</style>
