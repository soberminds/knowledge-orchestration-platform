<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { renderAsync } from "docx-preview";
import { buildFileUrl } from "../../api";
import { useI18n } from "../../composables/useI18n";

const props = defineProps<{
  sourcePath: string;
  page?: number | null;
  snippet?: string;
  active?: boolean;
}>();

const emit = defineEmits<{
  (event: "error", message: string): void;
  (event: "page-state", payload: { currentPage: number; pageCount: number }): void;
}>();

const loading = ref(false);
const errorMessage = ref("");
const containerRef = ref<HTMLElement | null>(null);
const runToken = ref(0);
const zoomPercent = ref(50);
const pageCount = ref(1);
const currentPage = ref(1);
const pageElements = ref<HTMLElement[]>([]);
let scrollTicking = false;
const { t } = useI18n();

const fileUrl = computed(() => buildFileUrl(props.sourcePath));
const canPrevPage = computed(() => currentPage.value > 1);
const canNextPage = computed(() => currentPage.value < pageCount.value);

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function getDocxWrapper(): HTMLElement | null {
  return containerRef.value?.querySelector(".docx-wrapper") as HTMLElement | null;
}

function collectPages() {
  const container = containerRef.value;
  if (!container) {
    pageElements.value = [];
    pageCount.value = 1;
    currentPage.value = 1;
    return;
  }

  const pages = Array.from(container.querySelectorAll("section.docx")) as HTMLElement[];
  pageElements.value = pages;
  pageCount.value = Math.max(1, pages.length);
  currentPage.value = clamp(currentPage.value, 1, pageCount.value);
}

function emitPageState() {
  emit("page-state", {
    currentPage: currentPage.value,
    pageCount: pageCount.value,
  });
}

function applyZoom() {
  const wrapper = getDocxWrapper();
  if (!wrapper) {
    return;
  }
  wrapper.style.setProperty("--docx-zoom", String(zoomPercent.value / 100));
}

function applyTableColumnFixes(root: HTMLElement) {
  const tables = Array.from(root.querySelectorAll("section.docx table")) as HTMLElement[];
  for (const table of tables) {
    table.classList.remove("docx-table-first-col-tight");
    const firstCell = table.querySelector("tr > th:first-child, tr > td:first-child") as HTMLElement | null;
    if (!firstCell) {
      continue;
    }
    const tableWidth = table.getBoundingClientRect().width;
    const firstWidth = firstCell.getBoundingClientRect().width;
    if (!tableWidth || !firstWidth) {
      continue;
    }
    const ratio = firstWidth / tableWidth;
    if (ratio < 0.1) {
      table.classList.add("docx-table-first-col-tight");
    }
  }
}

function updateCurrentPageFromScroll() {
  const container = containerRef.value;
  if (!container || !pageElements.value.length) {
    currentPage.value = 1;
    return;
  }

  const probe = container.scrollTop + container.clientHeight * 0.35;
  let bestIndex = 0;
  let bestDistance = Number.POSITIVE_INFINITY;
  for (let index = 0; index < pageElements.value.length; index += 1) {
    const pageTop = pageElements.value[index].offsetTop;
    const distance = Math.abs(pageTop - probe);
    if (distance < bestDistance) {
      bestDistance = distance;
      bestIndex = index;
    }
  }
  currentPage.value = bestIndex + 1;
}

function scrollToPage(targetPage: number, behavior: ScrollBehavior = "smooth") {
  const container = containerRef.value;
  const target = pageElements.value[targetPage - 1];
  if (!container || !target) {
    return;
  }
  container.scrollTo({
    top: Math.max(0, target.offsetTop - 14),
    behavior,
  });
}

function goPrevPage() {
  if (!canPrevPage.value) {
    return;
  }
  const targetPage = currentPage.value - 1;
  currentPage.value = targetPage;
  scrollToPage(targetPage);
}

function goNextPage() {
  if (!canNextPage.value) {
    return;
  }
  const targetPage = currentPage.value + 1;
  currentPage.value = targetPage;
  scrollToPage(targetPage);
}

function zoomIn() {
  zoomPercent.value = clamp(zoomPercent.value + 10, 50, 220);
  applyZoom();
}

function zoomOut() {
  zoomPercent.value = clamp(zoomPercent.value - 10, 50, 220);
  applyZoom();
}

function resetZoom() {
  zoomPercent.value = 50;
  applyZoom();
}

function handleCanvasScroll() {
  if (scrollTicking) {
    return;
  }
  scrollTicking = true;
  window.requestAnimationFrame(() => {
    scrollTicking = false;
    updateCurrentPageFromScroll();
  });
}

function normalizeForMatch(raw: string): string {
  return raw.replace(/[\s\u3000]/g, "").replace(/[^\u4e00-\u9fa5A-Za-z0-9]/g, "").toLowerCase();
}

function buildSnippetCandidates(snippet: string): string[] {
  const value = (snippet || "").trim();
  if (!value) {
    return [];
  }

  const normalized = normalizeForMatch(value);
  const candidates = [value];
  if (value.length > 80) {
    candidates.push(value.slice(0, 60));
  }
  if (value.length > 48) {
    candidates.push(value.slice(0, 34));
  }
  if (value.length > 22) {
    candidates.push(value.slice(0, 20));
  }
  if (normalized.length > 24) {
    candidates.push(normalized.slice(0, 20));
  }

  const deduped: string[] = [];
  const seen = new Set<string>();
  for (const item of candidates) {
    const text = item.trim();
    if (!text || seen.has(text)) {
      continue;
    }
    seen.add(text);
    deduped.push(text);
  }
  return deduped;
}

function textMatchesSnippet(text: string, snippet: string): boolean {
  const left = normalizeForMatch(text);
  if (!left || left.length < 3) {
    return false;
  }

  const normalizedSnippet = normalizeForMatch(snippet);
  if (!normalizedSnippet) {
    return false;
  }
  if (left.length <= 4) {
    return normalizedSnippet.includes(left) && left.length >= 4;
  }
  return left.includes(normalizedSnippet) || normalizedSnippet.includes(left);
}

function shouldSkipNode(parent: HTMLElement | null): boolean {
  if (!parent) {
    return true;
  }
  const tag = parent.tagName.toLowerCase();
  if (tag === "script" || tag === "style" || tag === "svg" || tag === "path") {
    return true;
  }
  if (parent.closest(".docx-hit")) {
    return true;
  }
  return false;
}

function clearExistingHighlights(root: HTMLElement) {
  const marks = Array.from(root.querySelectorAll("mark.docx-hit"));
  for (const mark of marks) {
    const text = mark.textContent ?? "";
    mark.replaceWith(document.createTextNode(text));
  }
}

function highlightDocxByExactMatch(root: HTMLElement, snippet: string): boolean {
  const candidates = buildSnippetCandidates(snippet);
  for (const candidate of candidates) {
    const normalizedCandidate = normalizeForMatch(candidate);
    const directMode = candidate.length > 6;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let matched = false;
    let current = walker.nextNode();

    while (current) {
      const textNode = current as Text;
      const parent = textNode.parentElement;
      const raw = textNode.nodeValue ?? "";
      if (!shouldSkipNode(parent) && raw.trim()) {
        const canUseDirect = directMode && raw.includes(candidate);
        const canUseNormalized = !directMode && textMatchesSnippet(raw, normalizedCandidate);
        if (canUseDirect || canUseNormalized) {
          const fragment = document.createDocumentFragment();
          if (canUseDirect) {
            const parts = raw.split(candidate);
            for (let i = 0; i < parts.length; i += 1) {
              if (parts[i]) {
                fragment.appendChild(document.createTextNode(parts[i]));
              }
              if (i < parts.length - 1) {
                const mark = document.createElement("mark");
                mark.className = "docx-hit";
                mark.textContent = candidate;
                fragment.appendChild(mark);
              }
            }
          } else {
            const mark = document.createElement("mark");
            mark.className = "docx-hit";
            mark.textContent = raw;
            fragment.appendChild(mark);
          }
          parent?.replaceChild(fragment, textNode);
          matched = true;
        }
      }
      current = walker.nextNode();
    }
    if (matched) {
      return true;
    }
  }

  return false;
}

function highlightSnippetInDocx(root: HTMLElement, snippet: string): void {
  clearExistingHighlights(root);
  const cleanSnippet = snippet.trim();
  if (!cleanSnippet) {
    return;
  }
  const matched = highlightDocxByExactMatch(root, cleanSnippet);
  if (!matched) {
    return;
  }
  const first = root.querySelector("mark.docx-hit");
  first?.scrollIntoView({ block: "center", behavior: "auto" });
  updateCurrentPageFromScroll();
}

async function renderDocxDocument() {
  const localToken = ++runToken.value;
  loading.value = true;
  errorMessage.value = "";

  try {
    if (!containerRef.value) {
      await nextTick();
    }
    const response = await fetch(fileUrl.value);
    if (!response.ok) {
      throw new Error(`Failed to fetch docx file: ${response.status}`);
    }
    const blob = await response.blob();

    if (localToken !== runToken.value) {
      return;
    }

    const container = containerRef.value;
    if (!container) {
      return;
    }
    container.innerHTML = "";

    await renderAsync(blob, container, undefined, {
      className: "docx",
      inWrapper: true,
      breakPages: true,
      ignoreLastRenderedPageBreak: false,
      experimental: true,
      ignoreWidth: false,
      ignoreHeight: false,
      ignoreFonts: false,
      useBase64URL: true,
      renderHeaders: true,
      renderFooters: true,
      renderFootnotes: true,
      renderEndnotes: true,
    });

    if (localToken !== runToken.value) {
      return;
    }

    await nextTick();
    collectPages();
    applyZoom();
    applyTableColumnFixes(container);
    const requestedPage = clamp(Math.floor(props.page ?? 1), 1, pageCount.value);
    currentPage.value = requestedPage;
    if (!String(props.snippet ?? "").trim() && requestedPage > 1) {
      scrollToPage(requestedPage, "auto");
    }
    updateCurrentPageFromScroll();
    highlightSnippetInDocx(container, props.snippet ?? "");
  } catch (error) {
    const message = error instanceof Error ? error.message : t("viewer.docx_preview_failed");
    errorMessage.value = message;
    if (containerRef.value) {
      containerRef.value.innerHTML = "";
    }
    emit("error", message);
  } finally {
    if (localToken === runToken.value) {
      loading.value = false;
    }
  }
}

function refreshHighlightOnly() {
  const container = containerRef.value;
  if (!container) {
    return;
  }
  highlightSnippetInDocx(container, props.snippet ?? "");
}

function refreshViewer() {
  if (!containerRef.value || !containerRef.value.children.length) {
    void renderDocxDocument();
    return;
  }
  refreshHighlightOnly();
}

watch(
  () => props.page,
  (page) => {
    if (!Number.isFinite(page ?? NaN) || !pageElements.value.length) {
      return;
    }
    const targetPage = clamp(Math.floor(page ?? 1), 1, pageCount.value);
    currentPage.value = targetPage;
    scrollToPage(targetPage);
  },
);

watch(
  () => props.sourcePath,
  () => {
    void renderDocxDocument();
  },
);

watch(
  () => props.snippet,
  () => {
    refreshHighlightOnly();
  },
);

watch(
  () => props.active,
  (active) => {
    if (!active) {
      return;
    }
    void nextTick().then(() => refreshViewer());
  },
);

watch(
  () => zoomPercent.value,
  () => {
    applyZoom();
  },
);

watch(
  () => [currentPage.value, pageCount.value],
  () => {
    emitPageState();
  },
  { immediate: true },
);

onMounted(() => {
  void renderDocxDocument();
});

defineExpose({
  refreshViewer,
  goPrevPage,
  goNextPage,
});
</script>

<template>
  <section class="docx-viewer">
    <header class="docx-toolbar">
      <div class="toolbar-left">
        <button type="button" class="tool-btn" :disabled="!canPrevPage" @click="goPrevPage">-1</button>
        <span class="tool-meta">{{ currentPage }} / {{ pageCount }}</span>
        <button type="button" class="tool-btn" :disabled="!canNextPage" @click="goNextPage">+1</button>
      </div>

      <div class="toolbar-middle">
        <button type="button" class="tool-btn" @click="zoomOut">-</button>
        <span class="tool-meta">{{ zoomPercent }}%</span>
        <button type="button" class="tool-btn" @click="zoomIn">+</button>
        <button type="button" class="tool-btn reset-btn" @click="resetZoom">50%</button>
      </div>

      <div class="toolbar-right">
        <a :href="fileUrl" target="_blank" rel="noreferrer" class="download-link">{{ t("viewer.download") }}</a>
      </div>
    </header>

    <p v-if="errorMessage" class="viewer-error">{{ errorMessage }}</p>
    <div ref="containerRef" class="docx-canvas" @scroll="handleCanvasScroll"></div>
    <div v-if="loading" class="docx-loading-mask">
      <el-skeleton :rows="10" animated />
    </div>
  </section>
</template>

<style scoped>
.docx-viewer {
  position: relative;
  min-height: 420px;
}

.docx-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 10px;
  border: 1px solid #d9e2ef;
  border-radius: 12px;
  background: #f8fafc;
  margin-bottom: 10px;
}

.toolbar-left,
.toolbar-middle,
.toolbar-right {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.tool-btn {
  min-width: 32px;
  height: 28px;
  padding: 0 6px;
  border-radius: 8px;
  border: 1px solid #cfd8e3;
  background: #fff;
  color: #334155;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  white-space: nowrap;
  line-height: 1;
  font-size: 0.78rem;
}

.tool-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.reset-btn {
  min-width: 48px;
  font-size: 0.75rem;
}

.tool-meta {
  color: #334155;
  font-size: 0.82rem;
  min-width: 62px;
  text-align: center;
}

.download-link {
  color: #0f766e;
  font-size: 0.82rem;
  text-decoration: none;
  border: 1px solid #9fd9d1;
  background: #ecfdf8;
  border-radius: 8px;
  min-height: 28px;
  padding: 0 10px;
  display: inline-flex;
  align-items: center;
}

.download-link:hover {
  text-decoration: underline;
}

.viewer-error {
  margin: 0;
  color: #b42318;
}

.docx-canvas {
  min-height: 360px;
  border: 1px solid #d9e2ef;
  border-radius: 14px;
  background: linear-gradient(180deg, #f1f3f5, #eceff3);
  overflow: auto;
}

.docx-loading-mask {
  position: absolute;
  left: 0;
  right: 0;
  top: 0;
  bottom: 0;
  padding: 14px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.82);
  pointer-events: none;
}

.docx-canvas :deep(.docx-wrapper) {
  padding: 24px 0 52px;
  zoom: var(--docx-zoom, 1);
  min-height: 100%;
}

.docx-canvas :deep(.docx-wrapper > section.docx) {
  margin: 0 auto 26px;
  box-shadow: 0 14px 28px rgba(15, 23, 42, 0.16);
  border: 1px solid #dbe3ef;
  background: #fff;
}

.docx-canvas :deep(section.docx p),
.docx-canvas :deep(section.docx span),
.docx-canvas :deep(section.docx a),
.docx-canvas :deep(section.docx td),
.docx-canvas :deep(section.docx th) {
  word-break: normal !important;
  overflow-wrap: normal !important;
  white-space: normal;
  writing-mode: horizontal-tb !important;
  text-orientation: mixed !important;
}

.docx-canvas :deep(section.docx a) {
  display: inline !important;
  white-space: nowrap;
}

.docx-canvas :deep(section.docx table) {
  border-collapse: collapse;
  width: 100%;
}

.docx-canvas :deep(section.docx table.docx-table-first-col-tight tr > th:first-child),
.docx-canvas :deep(section.docx table.docx-table-first-col-tight tr > td:first-child) {
  width: 92px !important;
  min-width: 92px !important;
  max-width: 92px !important;
}

.docx-canvas :deep(section.docx table.docx-table-first-col-tight tr > td:first-child p),
.docx-canvas :deep(section.docx table.docx-table-first-col-tight tr > th:first-child p) {
  white-space: normal !important;
}

.docx-canvas :deep(mark.docx-hit) {
  background: rgba(52, 211, 153, 0.38);
  box-shadow: 0 0 0 1px rgba(16, 163, 127, 0.2);
  border-radius: 3px;
  padding: 0 1px;
}

@media (max-width: 860px) {
  .docx-toolbar {
    flex-wrap: wrap;
  }

  .toolbar-right {
    width: 100%;
    justify-content: flex-end;
  }
}
</style>

