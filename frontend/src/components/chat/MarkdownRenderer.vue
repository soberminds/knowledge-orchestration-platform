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

const tooltipVisible = ref(false);
const tooltipText = ref("");
const tooltipStyle = ref<Record<string, string>>({});

function escapeAttr(raw: string): string {
  return raw
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

const markdown = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
  typographer: true,
});

const citationMap = computed(() => {
  const map = new Map<string, CitationRef>();
  for (const item of props.citations ?? []) {
    map.set(item.label, item);
  }
  return map;
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

const renderedHtml = computed(() => {
  let html = markdown.render(preparedContent.value);
  for (const [label, citation] of citationMap.value.entries()) {
    const preview = citation.preview || "";
    const escapedPreview = escapeAttr(preview);
    const anchorRegex = new RegExp(`<a href="#cite-${label}">\\[${label}\\]</a>`, "g");
    html = html.replace(
      anchorRegex,
      `<a href="#cite-${label}" class="citation-chip" data-citation-label="${label}" data-citation-preview="${escapedPreview}">[${label}]</a>`,
    );
  }
  return html;
});

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

function onContainerMouseMove(event: MouseEvent) {
  const target = event.target as HTMLElement | null;
  if (!target) {
    tooltipVisible.value = false;
    return;
  }
  const anchor = target.closest("a");
  if (!anchor) {
    tooltipVisible.value = false;
    return;
  }
  const href = anchor.getAttribute("href") ?? "";
  if (!href.startsWith("#cite-")) {
    tooltipVisible.value = false;
    return;
  }

  const preview = anchor.getAttribute("data-citation-preview") ?? "";
  if (!preview.trim()) {
    tooltipVisible.value = false;
    return;
  }

  tooltipText.value = preview;
  tooltipStyle.value = {
    left: `${event.clientX + 14}px`,
    top: `${event.clientY + 14}px`,
  };
  tooltipVisible.value = true;
}

function onContainerMouseLeave() {
  tooltipVisible.value = false;
}
</script>

<template>
  <pre v-if="useRawFallback" class="raw-fallback">{{ content }}</pre>
  <div
    v-else
    class="markdown-body"
    v-html="renderedHtml"
    @click="onContainerClick"
    @mousemove="onContainerMouseMove"
    @mouseleave="onContainerMouseLeave"
  ></div>

  <div v-if="tooltipVisible" class="citation-tooltip" :style="tooltipStyle">
    {{ tooltipText }}
  </div>
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

.markdown-body :deep(a.citation-chip) {
  display: inline-block;
  margin: 0 2px;
  padding: 0.03rem 0.45rem;
  border: 1px solid #9fd9d1;
  border-radius: 999px;
  background: #ecfdf8;
  color: #0f766e;
  text-decoration: none;
  font-weight: 700;
  line-height: 1.2;
}

.markdown-body :deep(a.citation-chip:hover) {
  background: #dff7f2;
}

.citation-tooltip {
  position: fixed;
  max-width: 360px;
  z-index: 2800;
  background: #fff;
  border: 1px solid #d9e8e2;
  box-shadow: 0 10px 32px rgba(2, 12, 27, 0.18);
  border-radius: 12px;
  padding: 10px 12px;
  color: #334155;
  font-size: 0.84rem;
  line-height: 1.62;
  pointer-events: none;
}
</style>
