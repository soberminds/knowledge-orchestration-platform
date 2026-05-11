<script setup lang="ts">
import MarkdownIt from "markdown-it";
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { buildFileUrl, getFilePageText } from "../../api";
import * as pdfjsLib from "pdfjs-dist/legacy/build/pdf";
import pdfWorkerUrl from "pdfjs-dist/legacy/build/pdf.worker.min.js?url";

pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorkerUrl;

const props = defineProps<{
  sourcePath: string;
  page?: number | null;
  snippet?: string;
  active?: boolean;
}>();

const emit = defineEmits<{
  (event: "error", message: string): void;
}>();

const containerRef = ref<HTMLElement | null>(null);
const canvasRef = ref<HTMLCanvasElement | null>(null);
const textLayerRef = ref<HTMLElement | null>(null);

const loading = ref(false);
const errorMessage = ref("");
const textHtml = ref("");
const pageCount = ref(1);
const currentPage = ref(1);
const zoomPercent = ref(110);

const fileUrl = computed(() => buildFileUrl(props.sourcePath));
const extension = computed(() => {
  const part = props.sourcePath.split("?")[0];
  const dot = part.lastIndexOf(".");
  if (dot < 0) {
    return "";
  }
  return part.slice(dot + 1).toLowerCase();
});
const isPdf = computed(() => extension.value === "pdf");
const isMarkdown = computed(() => extension.value === "md" || extension.value === "markdown");
const hasSnippet = computed(() => (props.snippet ?? "").trim().length > 0);

const markdown = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
  typographer: true,
});

let resizeObserver: ResizeObserver | null = null;
let resizeTimer: number | null = null;
let runToken = 0;
let pdfDoc: any = null;
let afterOpenTimer: number | null = null;

function escapeHtml(raw: string): string {
  return raw.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function normalizeForMatch(raw: string): string {
  return raw.replace(/[\s\u3000]/g, "").replace(/[^\u4e00-\u9fa5A-Za-z0-9]/g, "").toLowerCase();
}

function buildSnippetTokens(snippet: string): string[] {
  const normalized = normalizeForMatch(snippet);
  const tokens: string[] = [];
  if (!normalized) {
    return tokens;
  }

  if (normalized.length <= 14) {
    tokens.push(normalized);
    return tokens;
  }

  tokens.push(normalized.slice(0, 20));
  tokens.push(normalized.slice(Math.max(0, Math.floor(normalized.length / 2) - 8), Math.floor(normalized.length / 2) + 8));
  tokens.push(normalized.slice(Math.max(0, normalized.length - 20)));

  const deduped: string[] = [];
  const seen = new Set<string>();
  for (const token of tokens) {
    const cleaned = token.trim();
    if (!cleaned || seen.has(cleaned)) {
      continue;
    }
    seen.add(cleaned);
    deduped.push(cleaned);
  }
  return deduped;
}

function textMatchesSnippet(text: string, snippet: string): boolean {
  const left = normalizeForMatch(text);
  if (!left) {
    return false;
  }
  if (left.length < 3) {
    return false;
  }
  const tokens = buildSnippetTokens(snippet);
  if (!tokens.length) {
    return false;
  }
  if (left.length <= 4) {
    return tokens.some((token) => token.includes(left) && left.length >= 4);
  }
  return tokens.some((token) => left.includes(token) || token.includes(left));
}

function markSnippetInText(raw: string, snippet: string): string {
  const safe = escapeHtml(raw || "");
  if (!snippet.trim()) {
    return safe.replace(/\n/g, "<br/>");
  }

  const candidates = [
    snippet.trim(),
    snippet.trim().slice(0, 60),
    snippet.trim().slice(0, 30),
  ].filter((item) => item.length > 0);

  for (const candidate of candidates) {
    const escaped = candidate.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const regex = new RegExp(escaped, "g");
    const replaced = safe.replace(regex, (hit) => `<mark class="inline-hit">${hit}</mark>`);
    if (replaced !== safe) {
      return replaced.replace(/\n/g, "<br/>");
    }
  }

  return safe.replace(/\n/g, "<br/>");
}

function buildSnippetCandidates(snippet: string): string[] {
  const value = (snippet || "").trim();
  if (!value) {
    return [];
  }
  const candidates = [value];
  if (value.length > 80) {
    candidates.push(value.slice(0, 64));
  }
  if (value.length > 48) {
    candidates.push(value.slice(0, 40));
  }
  if (value.length > 24) {
    candidates.push(value.slice(0, 22));
  }
  const deduped: string[] = [];
  const seen = new Set<string>();
  for (const item of candidates) {
    const normalized = item.trim();
    if (!normalized || seen.has(normalized)) {
      continue;
    }
    seen.add(normalized);
    deduped.push(normalized);
  }
  return deduped;
}

function highlightMarkdownHtml(markdownHtml: string, snippet: string): string {
  const candidates = buildSnippetCandidates(snippet);
  if (!candidates.length || !markdownHtml.trim()) {
    return markdownHtml;
  }

  const parser = new DOMParser();
  const doc = parser.parseFromString(`<div id="root">${markdownHtml}</div>`, "text/html");
  const root = doc.getElementById("root");
  if (!root) {
    return markdownHtml;
  }

  for (const candidate of candidates) {
    const walker = doc.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let found = false;
    let current = walker.nextNode();
    while (current) {
      const textNode = current as Text;
      const raw = textNode.nodeValue ?? "";
      const parent = textNode.parentElement;
      const tag = parent?.tagName.toLowerCase();
      const shouldSkip = tag === "code" || tag === "pre" || tag === "script" || tag === "style";
      if (!shouldSkip && raw.includes(candidate)) {
        const parts = raw.split(candidate);
        const fragment = doc.createDocumentFragment();
        for (let i = 0; i < parts.length; i += 1) {
          if (parts[i]) {
            fragment.appendChild(doc.createTextNode(parts[i]));
          }
          if (i < parts.length - 1) {
            const mark = doc.createElement("mark");
            mark.className = "inline-hit";
            mark.textContent = candidate;
            fragment.appendChild(mark);
          }
        }
        parent?.replaceChild(fragment, textNode);
        found = true;
      }
      current = walker.nextNode();
    }
    if (found) {
      return root.innerHTML;
    }
  }

  return markdownHtml;
}

async function renderTextDocument(localToken: number) {
  const payload = await getFilePageText(props.sourcePath, props.page ?? 1);
  if (localToken !== runToken) {
    return;
  }

  pageCount.value = 1;
  currentPage.value = 1;

  const rawText = payload.text || "";
  if (isMarkdown.value) {
    const markdownHtml = markdown.render(rawText);
    textHtml.value = highlightMarkdownHtml(markdownHtml, props.snippet ?? "");
    return;
  }

  const marked = markSnippetInText(rawText, props.snippet ?? "");
  textHtml.value = marked;
}

async function renderPdfPage(localToken: number) {
  if (!pdfDoc || !canvasRef.value || !containerRef.value) {
    return;
  }

  const pageNumber = Math.min(Math.max(1, currentPage.value), pageCount.value);
  currentPage.value = pageNumber;
  const page = await pdfDoc.getPage(pageNumber);
  if (localToken !== runToken) {
    return;
  }

  const hostWidth = Math.max(320, containerRef.value.clientWidth - 36);
  const baseViewport = page.getViewport({ scale: 1 });
  const fitScale = hostWidth / baseViewport.width;
  const scale = fitScale * (zoomPercent.value / 100);
  const viewport = page.getViewport({ scale });

  const canvas = canvasRef.value;
  const context = canvas.getContext("2d");
  if (!context) {
    return;
  }

  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.floor(viewport.width * dpr);
  canvas.height = Math.floor(viewport.height * dpr);
  canvas.style.width = `${Math.floor(viewport.width)}px`;
  canvas.style.height = `${Math.floor(viewport.height)}px`;
  context.setTransform(dpr, 0, 0, dpr, 0, 0);
  context.clearRect(0, 0, viewport.width, viewport.height);

  await page.render({
    canvasContext: context,
    viewport,
  }).promise;
  if (localToken !== runToken) {
    return;
  }

  const textLayer = textLayerRef.value;
  if (!textLayer) {
    return;
  }

  textLayer.innerHTML = "";
  textLayer.style.width = `${Math.floor(viewport.width)}px`;
  textLayer.style.height = `${Math.floor(viewport.height)}px`;

  const textContent = await page.getTextContent();
  if (localToken !== runToken) {
    return;
  }

  const snippet = props.snippet ?? "";
  for (const item of textContent.items as any[]) {
    if (!item?.str) {
      continue;
    }
    const span = document.createElement("span");
    span.className = "pdf-text-item";
    if (textMatchesSnippet(item.str, snippet)) {
      span.classList.add("is-hit");
    }

    const tx = pdfjsLib.Util.transform(viewport.transform, item.transform);
    const angle = Math.atan2(tx[1], tx[0]);
    const fontHeight = Math.hypot(tx[2], tx[3]);
    const scaleX = fontHeight === 0 ? 1 : Math.hypot(tx[0], tx[1]) / fontHeight;

    span.style.left = `${tx[4]}px`;
    span.style.top = `${tx[5] - fontHeight}px`;
    span.style.fontSize = `${fontHeight}px`;
    span.style.transform = `rotate(${angle}rad) scaleX(${scaleX})`;
    span.style.transformOrigin = "0% 0%";
    span.textContent = item.str;
    textLayer.appendChild(span);
  }

  await nextTick();
  const firstHit = textLayer.querySelector(".pdf-text-item.is-hit");
  firstHit?.scrollIntoView({ block: "center", behavior: "smooth" });
}

function requestSettledPdfRender() {
  if (!isPdf.value) {
    return;
  }
  const token = runToken;
  void nextTick().then(() => {
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        void renderPdfPage(token);
      });
    });
  });
}

function schedulePdfRerender() {
  if (!isPdf.value || !pdfDoc) {
    return;
  }
  if (resizeTimer !== null) {
    window.clearTimeout(resizeTimer);
  }
  resizeTimer = window.setTimeout(() => {
    const localToken = runToken;
    void renderPdfPage(localToken);
  }, 120);
}

async function loadDocument() {
  const localToken = ++runToken;
  loading.value = true;
  errorMessage.value = "";
  textHtml.value = "";
  pageCount.value = 1;
  currentPage.value = Math.max(1, props.page ?? 1);
  pdfDoc = null;

  try {
    if (!isPdf.value) {
      await renderTextDocument(localToken);
      return;
    }

    const task = pdfjsLib.getDocument({
      url: fileUrl.value,
      useWorkerFetch: true,
    });
    pdfDoc = await task.promise;
    if (localToken !== runToken) {
      return;
    }
    pageCount.value = Math.max(1, pdfDoc.numPages || 1);
    currentPage.value = Math.min(Math.max(1, props.page ?? 1), pageCount.value);
    await nextTick();
    await renderPdfPage(localToken);
    if (afterOpenTimer !== null) {
      window.clearTimeout(afterOpenTimer);
    }
    // First render can happen before dialog layout settles; rerender once.
    afterOpenTimer = window.setTimeout(() => {
      if (localToken === runToken) {
        requestSettledPdfRender();
      }
    }, 90);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Failed to load file preview";
    errorMessage.value = message;
    emit("error", message);
  } finally {
    if (localToken === runToken) {
      loading.value = false;
    }
  }
}

function goPrevPage() {
  if (!isPdf.value || currentPage.value <= 1) {
    return;
  }
  currentPage.value -= 1;
  void renderPdfPage(runToken);
}

function goNextPage() {
  if (!isPdf.value || currentPage.value >= pageCount.value) {
    return;
  }
  currentPage.value += 1;
  void renderPdfPage(runToken);
}

function zoomIn() {
  zoomPercent.value = Math.min(220, zoomPercent.value + 10);
  if (isPdf.value) {
    void renderPdfPage(runToken);
  }
}

function zoomOut() {
  zoomPercent.value = Math.max(60, zoomPercent.value - 10);
  if (isPdf.value) {
    void renderPdfPage(runToken);
  }
}

watch(
  () => [props.sourcePath, props.page, props.snippet],
  () => {
    void loadDocument();
  },
  { immediate: true },
);

watch(
  () => props.active,
  (active) => {
    if (!active) {
      return;
    }
    requestSettledPdfRender();
  },
);

onMounted(() => {
  if (containerRef.value) {
    resizeObserver = new ResizeObserver(() => {
      schedulePdfRerender();
    });
    resizeObserver.observe(containerRef.value);
  }
});

onBeforeUnmount(() => {
  if (resizeObserver) {
    resizeObserver.disconnect();
    resizeObserver = null;
  }
  if (resizeTimer !== null) {
    window.clearTimeout(resizeTimer);
    resizeTimer = null;
  }
  if (afterOpenTimer !== null) {
    window.clearTimeout(afterOpenTimer);
    afterOpenTimer = null;
  }
});

defineExpose({
  refreshViewer: requestSettledPdfRender,
});
</script>

<template>
  <section class="unified-viewer">
    <header class="viewer-toolbar">
      <div class="file-name">{{ sourcePath }}</div>
      <div class="toolbar-actions">
        <template v-if="isPdf">
          <button type="button" class="tool-btn" @click="goPrevPage" :disabled="currentPage <= 1">-</button>
          <span class="tool-meta">{{ currentPage }} / {{ pageCount }}</span>
          <button type="button" class="tool-btn" @click="goNextPage" :disabled="currentPage >= pageCount">+</button>
          <span class="tool-sep"></span>
          <button type="button" class="tool-btn" @click="zoomOut">-</button>
          <span class="tool-meta">{{ zoomPercent }}%</span>
          <button type="button" class="tool-btn" @click="zoomIn">+</button>
        </template>
        <a :href="fileUrl" target="_blank" rel="noreferrer" class="open-link">打开原文件</a>
      </div>
    </header>

    <div ref="containerRef" class="viewer-stage">
      <el-skeleton v-if="loading" :rows="8" animated />
      <p v-else-if="errorMessage" class="viewer-error">{{ errorMessage }}</p>

      <template v-else-if="isPdf">
        <div class="pdf-page">
          <canvas ref="canvasRef" class="pdf-canvas"></canvas>
          <div ref="textLayerRef" class="pdf-text-layer"></div>
        </div>
      </template>

      <template v-else>
        <section v-if="hasSnippet" class="text-hit-callout">
          <small>引用定位片段</small>
          <p>{{ snippet }}</p>
        </section>
        <article class="text-page markdown-body" v-html="textHtml"></article>
      </template>
    </div>
  </section>
</template>

<style scoped>
.unified-viewer {
  border: 1px solid #dde3ea;
  border-radius: 14px;
  overflow: hidden;
  background: linear-gradient(180deg, #ffffff, #f8fafc);
}

.viewer-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border-bottom: 1px solid #e7ecf3;
  background: #f4f8fc;
}

.file-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 600;
  color: #0f172a;
}

.toolbar-actions {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.tool-btn {
  width: 26px;
  height: 26px;
  border-radius: 7px;
  border: 1px solid #cfd8e3;
  background: #fff;
  color: #334155;
  cursor: pointer;
}

.tool-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.tool-meta {
  font-size: 0.82rem;
  color: #475569;
  min-width: 56px;
  text-align: center;
}

.tool-sep {
  width: 1px;
  height: 16px;
  background: #d6dee8;
  margin: 0 2px;
}

.open-link {
  color: #0f766e;
  font-size: 0.82rem;
  text-decoration: none;
}

.open-link:hover {
  text-decoration: underline;
}

.viewer-stage {
  height: 74vh;
  overflow: auto;
  padding: 14px;
}

.viewer-error {
  margin: 0;
  color: #b42318;
}

.text-hit-callout {
  max-width: 860px;
  margin: 0 auto 10px;
  padding: 10px 12px;
  border: 1px solid #9fd9d1;
  border-radius: 10px;
  background: linear-gradient(135deg, rgba(52, 211, 153, 0.22), rgba(167, 243, 208, 0.34));
}

.text-hit-callout small {
  display: block;
  margin-bottom: 4px;
  color: #0f766e;
  font-weight: 700;
}

.text-hit-callout p {
  margin: 0;
  color: #134e4a;
  line-height: 1.65;
}

.pdf-page {
  position: relative;
  width: fit-content;
  margin: 0 auto;
  border: 1px solid #dbe3ef;
  border-radius: 12px;
  box-shadow: 0 10px 30px rgba(2, 12, 27, 0.08);
  overflow: hidden;
  background: #fff;
}

.pdf-canvas {
  display: block;
}

.pdf-text-layer {
  position: absolute;
  left: 0;
  top: 0;
  overflow: hidden;
  line-height: 1;
  opacity: 1;
  pointer-events: none;
}

.pdf-text-layer :deep(.pdf-text-item) {
  position: absolute;
  white-space: pre;
  color: transparent;
  transform-origin: 0 0;
}

.pdf-text-layer :deep(.pdf-text-item.is-hit) {
  background: rgba(52, 211, 153, 0.42);
  box-shadow: 0 0 0 1px rgba(16, 163, 127, 0.32);
  border-radius: 3px;
}

.text-page {
  max-width: 860px;
  margin: 0 auto;
  padding: 16px 20px;
  border: 1px solid #dde6f2;
  border-radius: 12px;
  background: #fff;
  line-height: 1.85;
  color: #111827;
}

.text-page :deep(mark.inline-hit) {
  background: rgba(52, 211, 153, 0.42);
  box-shadow: 0 0 0 1px rgba(16, 163, 127, 0.25);
  border-radius: 3px;
  padding: 0 2px;
}

.markdown-body :deep(p) {
  margin: 0.35rem 0;
}

.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(h4) {
  margin: 1rem 0 0.5rem;
  line-height: 1.35;
  color: #0f172a;
}

.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  margin: 0.45rem 0;
  padding-left: 1.4rem;
}

.markdown-body :deep(blockquote) {
  margin: 0.65rem 0;
  padding: 0.5rem 0.75rem;
  border-left: 3px solid #cbd5e1;
  background: #f8fafc;
  color: #334155;
}

.markdown-body :deep(pre) {
  margin: 0.65rem 0;
  padding: 0.75rem 0.8rem;
  border-radius: 10px;
  border: 1px solid #e5e7eb;
  background: #f3f4f6;
  overflow-x: auto;
}

.markdown-body :deep(code) {
  font-family: "JetBrains Mono", "Consolas", monospace;
  font-size: 0.86em;
}

.markdown-body :deep(:not(pre) > code) {
  padding: 0.08rem 0.35rem;
  border-radius: 7px;
  border: 1px solid #e5e7eb;
  background: #f3f4f6;
}

@media (max-width: 980px) {
  .viewer-stage {
    height: 66vh;
    padding: 10px;
  }
}
</style>
