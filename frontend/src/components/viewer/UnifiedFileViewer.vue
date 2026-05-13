<script setup lang="ts">
import MarkdownIt from "markdown-it";
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { buildFileUrl, buildPreviewPdfUrl, getFilePageText } from "../../api";
import { useI18n } from "../../composables/useI18n";
import * as pdfjsLib from "pdfjs-dist/legacy/build/pdf";
import pdfWorkerUrl from "pdfjs-dist/legacy/build/pdf.worker.min.js?url";
import DocxPageViewer from "./DocxPageViewer.vue";
import SpreadsheetGridViewer from "./SpreadsheetGridViewer.vue";

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

const viewerRootRef = ref<HTMLElement | null>(null);
const containerRef = ref<HTMLElement | null>(null);
const pdfStackRef = ref<HTMLElement | null>(null);
const docxViewerRef = ref<InstanceType<typeof DocxPageViewer> | null>(null);
const { t } = useI18n();

const loading = ref(false);
const errorMessage = ref("");
const textHtml = ref("");
const pageCount = ref(1);
const currentPage = ref(1);
const pageLabel = ref<"preview" | "page">("preview");
const zoomPercent = ref(90);
const contentFormat = ref<"plain" | "markdown" | "table">("plain");
const tableHeaders = ref<string[]>([]);
const tableRows = ref<string[][]>([]);
const tableDataStartRow = ref(1);
const tableTruncated = ref(false);
const tableTotalRows = ref(0);
const tableTotalColumns = ref(0);
const officePdfMode = ref(false);
const officePdfError = ref("");

const renderedPdfPages = ref<number[]>([]);
const autoPagingBusy = ref(false);
const autoPagingText = ref("");
const isFullscreen = ref(false);
const fileVersionToken = ref(Date.now());

const fileUrl = computed(() => `${buildFileUrl(props.sourcePath)}&v=${fileVersionToken.value}`);
const previewPdfUrl = computed(() => `${buildPreviewPdfUrl(props.sourcePath)}&v=${fileVersionToken.value}`);
const extension = computed(() => {
  const part = props.sourcePath.split("?")[0];
  const dot = part.lastIndexOf(".");
  if (dot < 0) {
    return "";
  }
  return part.slice(dot + 1).toLowerCase();
});
const isPdf = computed(() => extension.value === "pdf");
const isDocx = computed(() => extension.value === "docx");
const isLegacyDoc = computed(() => extension.value === "doc");
const isOfficeDoc = computed(() => isDocx.value || isLegacyDoc.value);
const isMarkdownByExtension = computed(() => extension.value === "md" || extension.value === "markdown");
const shouldRenderMarkdown = computed(() => contentFormat.value === "markdown" || isMarkdownByExtension.value);
const isTableFormat = computed(() => contentFormat.value === "table");
const isPdfLike = computed(() => isPdf.value || officePdfMode.value);
const showSidePager = computed(() => isPdfLike.value || (isDocx.value && !officePdfMode.value));
const hasSnippet = computed(() => (props.snippet ?? "").trim().length > 0);
const hasPagination = computed(() => pageCount.value > 1);
const pageLabelText = computed(() => (pageLabel.value === "page" ? t("viewer.page") : t("viewer.preview")));
const canFullscreen = computed(() => {
  if (typeof document === "undefined") {
    return false;
  }
  const doc = document as Document & {
    webkitFullscreenEnabled?: boolean;
    msFullscreenEnabled?: boolean;
    mozFullScreenEnabled?: boolean;
  };
  return Boolean(doc.fullscreenEnabled || doc.webkitFullscreenEnabled || doc.msFullscreenEnabled || doc.mozFullScreenEnabled);
});

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
let scrollTicking = false;

const pdfCanvasMap = new Map<number, HTMLCanvasElement>();
const pdfTextLayerMap = new Map<number, HTMLElement>();
const pdfFrameMap = new Map<number, HTMLElement>();
const pdfRenderTasks = new Map<number, any>();

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function getLoadedFirstPage(): number {
  return renderedPdfPages.value.length ? renderedPdfPages.value[0] : 0;
}

function getLoadedLastPage(): number {
  return renderedPdfPages.value.length ? renderedPdfPages.value[renderedPdfPages.value.length - 1] : 0;
}

function clearPdfElementMaps() {
  pdfCanvasMap.clear();
  pdfTextLayerMap.clear();
  pdfFrameMap.clear();
}

function resetPdfStack() {
  renderedPdfPages.value = [];
  clearPdfElementMaps();
  autoPagingBusy.value = false;
}

function setPdfCanvasRef(pageNumber: number, node: unknown) {
  const rawNode = (node as { $el?: unknown } | null)?.$el ?? node;
  if (!rawNode) {
    pdfCanvasMap.delete(pageNumber);
    return;
  }
  if (rawNode instanceof HTMLCanvasElement) {
    pdfCanvasMap.set(pageNumber, rawNode);
  }
}

function setPdfTextLayerRef(pageNumber: number, node: unknown) {
  const rawNode = (node as { $el?: unknown } | null)?.$el ?? node;
  if (!rawNode) {
    pdfTextLayerMap.delete(pageNumber);
    return;
  }
  if (rawNode instanceof HTMLElement) {
    pdfTextLayerMap.set(pageNumber, rawNode);
  }
}

function setPdfFrameRef(pageNumber: number, node: unknown) {
  const rawNode = (node as { $el?: unknown } | null)?.$el ?? node;
  if (!rawNode) {
    pdfFrameMap.delete(pageNumber);
    return;
  }
  if (rawNode instanceof HTMLElement) {
    pdfFrameMap.set(pageNumber, rawNode);
  }
}

function getFullscreenElement(): Element | null {
  const doc = document as Document & {
    webkitFullscreenElement?: Element | null;
    msFullscreenElement?: Element | null;
    mozFullScreenElement?: Element | null;
  };
  return doc.fullscreenElement || doc.webkitFullscreenElement || doc.msFullscreenElement || doc.mozFullScreenElement || null;
}

function syncFullscreenState() {
  const host = viewerRootRef.value;
  if (!host) {
    isFullscreen.value = false;
    return;
  }
  isFullscreen.value = getFullscreenElement() === host;
}

async function enterFullscreen() {
  const host = viewerRootRef.value as (HTMLElement & {
    webkitRequestFullscreen?: () => Promise<void> | void;
    msRequestFullscreen?: () => Promise<void> | void;
    mozRequestFullScreen?: () => Promise<void> | void;
  }) | null;
  if (!host) {
    return;
  }

  if (host.requestFullscreen) {
    await host.requestFullscreen();
    return;
  }
  if (host.webkitRequestFullscreen) {
    await host.webkitRequestFullscreen();
    return;
  }
  if (host.msRequestFullscreen) {
    await host.msRequestFullscreen();
    return;
  }
  if (host.mozRequestFullScreen) {
    await host.mozRequestFullScreen();
  }
}

async function exitFullscreen() {
  const doc = document as Document & {
    webkitExitFullscreen?: () => Promise<void> | void;
    msExitFullscreen?: () => Promise<void> | void;
    mozCancelFullScreen?: () => Promise<void> | void;
  };
  if (doc.exitFullscreen) {
    await doc.exitFullscreen();
    return;
  }
  if (doc.webkitExitFullscreen) {
    await doc.webkitExitFullscreen();
    return;
  }
  if (doc.msExitFullscreen) {
    await doc.msExitFullscreen();
    return;
  }
  if (doc.mozCancelFullScreen) {
    await doc.mozCancelFullScreen();
  }
}

async function toggleFullscreen() {
  if (isFullscreen.value) {
    await exitFullscreen();
    return;
  }
  await enterFullscreen();
}

async function cancelOneRenderTask(task: any) {
  if (!task) {
    return;
  }
  try {
    task.cancel();
  } catch {
    // Ignore cancel errors.
  }
  try {
    await task.promise;
  } catch {
    // Expected when render is cancelled.
  }
}

async function cancelAllPdfRenderTasks() {
  const tasks = Array.from(pdfRenderTasks.values());
  pdfRenderTasks.clear();
  await Promise.all(tasks.map((task) => cancelOneRenderTask(task)));
}

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
  if (!left || left.length < 3) {
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

  const candidates = [snippet.trim(), snippet.trim().slice(0, 70), snippet.trim().slice(0, 36)].filter((item) => item.length > 0);
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
  if (value.length > 100) {
    candidates.push(value.slice(0, 72));
  }
  if (value.length > 56) {
    candidates.push(value.slice(0, 42));
  }
  if (value.length > 28) {
    candidates.push(value.slice(0, 24));
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

function resetTablePayload() {
  tableHeaders.value = [];
  tableRows.value = [];
  tableDataStartRow.value = 1;
  tableTruncated.value = false;
  tableTotalRows.value = 0;
  tableTotalColumns.value = 0;
}

async function renderTextDocument(localToken: number) {
  const payload = await getFilePageText(props.sourcePath, currentPage.value);
  if (localToken !== runToken) {
    return;
  }

  pageCount.value = Math.max(1, payload.page_count ?? 1);
  currentPage.value = Math.min(Math.max(1, payload.page ?? currentPage.value), pageCount.value);
  pageLabel.value = pageCount.value > 1 ? "page" : "preview";
  if (payload.format === "table") {
    contentFormat.value = "table";
  } else if (payload.format === "markdown") {
    contentFormat.value = "markdown";
  } else {
    contentFormat.value = "plain";
  }

  if (contentFormat.value === "table") {
    tableHeaders.value = payload.table_headers ?? [];
    tableRows.value = payload.table_rows ?? [];
    tableDataStartRow.value = Math.max(1, payload.table_data_start_row ?? 1);
    tableTruncated.value = Boolean(payload.table_truncated);
    tableTotalRows.value = Math.max(0, payload.table_total_rows ?? tableRows.value.length);
    tableTotalColumns.value = Math.max(0, payload.table_total_columns ?? tableHeaders.value.length);
    textHtml.value = "";
    return;
  }

  resetTablePayload();

  const rawText = payload.text || "";
  if (shouldRenderMarkdown.value) {
    const markdownHtml = markdown.render(rawText);
    textHtml.value = highlightMarkdownHtml(markdownHtml, props.snippet ?? "");
    return;
  }

  textHtml.value = markSnippetInText(rawText, props.snippet ?? "");
}

async function renderPdfPageIntoFrame(localToken: number, pageNumber: number, focusHit = false) {
  if (!pdfDoc || localToken !== runToken) {
    return;
  }

  const canvas = pdfCanvasMap.get(pageNumber);
  const textLayer = pdfTextLayerMap.get(pageNumber);
  const host = containerRef.value;
  if (!canvas || !textLayer || !host) {
    return;
  }

  const existingTask = pdfRenderTasks.get(pageNumber);
  if (existingTask) {
    await cancelOneRenderTask(existingTask);
    if (pdfRenderTasks.get(pageNumber) === existingTask) {
      pdfRenderTasks.delete(pageNumber);
    }
  }

  const page = await pdfDoc.getPage(pageNumber);
  if (localToken !== runToken) {
    return;
  }

  const hostWidth = Math.max(320, host.clientWidth - 56);
  const baseViewport = page.getViewport({ scale: 1 });
  const fitScale = hostWidth / baseViewport.width;
  const scale = fitScale * (zoomPercent.value / 100);
  const viewport = page.getViewport({ scale });

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

  textLayer.innerHTML = "";
  textLayer.style.width = `${Math.floor(viewport.width)}px`;
  textLayer.style.height = `${Math.floor(viewport.height)}px`;

  const renderTask = page.render({
    canvasContext: context,
    viewport,
  });
  pdfRenderTasks.set(pageNumber, renderTask);
  try {
    await renderTask.promise;
  } catch (error: any) {
    if (error?.name === "RenderingCancelledException") {
      return;
    }
    throw error;
  } finally {
    if (pdfRenderTasks.get(pageNumber) === renderTask) {
      pdfRenderTasks.delete(pageNumber);
    }
  }
  if (localToken !== runToken) {
    return;
  }

  const textContent = await page.getTextContent();
  if (localToken !== runToken) {
    return;
  }

  const snippet = props.snippet ?? "";
  let hasHit = false;

  for (const item of textContent.items as any[]) {
    if (!item?.str) {
      continue;
    }
    const span = document.createElement("span");
    span.className = "pdf-text-item";
    if (textMatchesSnippet(item.str, snippet)) {
      span.classList.add("is-hit");
      hasHit = true;
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

  if (!focusHit || !hasHit) {
    return;
  }

  await nextTick();
  const firstHit = textLayer.querySelector(".pdf-text-item.is-hit") as HTMLElement | null;
  firstHit?.scrollIntoView({ block: "center", behavior: "smooth" });
}

async function ensurePdfPageRange(localToken: number, targetPage: number) {
  if (!pdfDoc || localToken !== runToken) {
    return;
  }

  const safePage = clamp(targetPage, 1, pageCount.value);

  if (!renderedPdfPages.value.length) {
    renderedPdfPages.value = [safePage];
    await nextTick();
    await renderPdfPageIntoFrame(localToken, safePage, hasSnippet.value);
    return;
  }

  const first = getLoadedFirstPage();
  const last = getLoadedLastPage();

  if (safePage < first) {
    const prependPages: number[] = [];
    for (let page = safePage; page < first; page += 1) {
      prependPages.push(page);
    }
    renderedPdfPages.value = [...prependPages, ...renderedPdfPages.value];
    await nextTick();
    for (const page of prependPages) {
      await renderPdfPageIntoFrame(localToken, page, false);
    }
    return;
  }

  if (safePage > last) {
    const appendPages: number[] = [];
    for (let page = last + 1; page <= safePage; page += 1) {
      appendPages.push(page);
    }
    renderedPdfPages.value = [...renderedPdfPages.value, ...appendPages];
    await nextTick();
    for (const page of appendPages) {
      await renderPdfPageIntoFrame(localToken, page, false);
    }
  }
}

async function appendNextPdfPage(localToken: number): Promise<boolean> {
  if (!pdfDoc || localToken !== runToken) {
    return false;
  }
  const last = getLoadedLastPage();
  if (last <= 0 || last >= pageCount.value) {
    return false;
  }
  const nextPage = last + 1;
  await ensurePdfPageRange(localToken, nextPage);
  return true;
}

async function prependPrevPdfPage(localToken: number): Promise<boolean> {
  if (!pdfDoc || localToken !== runToken) {
    return false;
  }
  const first = getLoadedFirstPage();
  if (first <= 1) {
    return false;
  }

  const host = containerRef.value;
  const beforeTop = host?.scrollTop ?? 0;
  const beforeHeight = host?.scrollHeight ?? 0;

  await ensurePdfPageRange(localToken, first - 1);
  if (localToken !== runToken || !host) {
    return true;
  }
  await nextTick();

  const heightDelta = host.scrollHeight - beforeHeight;
  if (heightDelta > 0) {
    host.scrollTop = beforeTop + heightDelta;
  }
  return true;
}

function scrollToPdfPage(pageNumber: number, behavior: ScrollBehavior = "smooth") {
  const host = containerRef.value;
  const target = pdfFrameMap.get(pageNumber);
  if (!host || !target) {
    return;
  }
  host.scrollTo({
    top: Math.max(0, target.offsetTop - 14),
    behavior,
  });
}

function updateCurrentPageByScroll() {
  const host = containerRef.value;
  if (!host || !renderedPdfPages.value.length) {
    return;
  }

  const probe = host.scrollTop + host.clientHeight * 0.35;
  let bestPage = renderedPdfPages.value[0];
  let bestDistance = Number.POSITIVE_INFINITY;

  for (const page of renderedPdfPages.value) {
    const frame = pdfFrameMap.get(page);
    if (!frame) {
      continue;
    }
    const distance = Math.abs(frame.offsetTop - probe);
    if (distance < bestDistance) {
      bestDistance = distance;
      bestPage = page;
    }
  }

  currentPage.value = clamp(bestPage, 1, pageCount.value);
}

async function rerenderLoadedPdfPages(localToken: number) {
  if (!pdfDoc || localToken !== runToken || !renderedPdfPages.value.length) {
    return;
  }

  await cancelAllPdfRenderTasks();
  for (const page of renderedPdfPages.value) {
    if (localToken !== runToken) {
      return;
    }
    await renderPdfPageIntoFrame(localToken, page, false);
  }
  updateCurrentPageByScroll();
}

function requestSettledPdfRender() {
  if (!isPdfLike.value || !pdfDoc) {
    return;
  }
  const token = runToken;
  void nextTick().then(() => {
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        void rerenderLoadedPdfPages(token);
      });
    });
  });
}

function schedulePdfRerender() {
  if (!isPdfLike.value || !pdfDoc) {
    return;
  }
  if (resizeTimer !== null) {
    window.clearTimeout(resizeTimer);
  }
  resizeTimer = window.setTimeout(() => {
    const localToken = runToken;
    void rerenderLoadedPdfPages(localToken);
  }, 120);
}

async function maybeAutoPageByScroll() {
  const host = containerRef.value;
  if (!host || !isPdfLike.value || loading.value || errorMessage.value || autoPagingBusy.value) {
    return;
  }
  if (!pdfDoc || !renderedPdfPages.value.length) {
    return;
  }

  const loadedFirstPage = getLoadedFirstPage();
  const loadedLastPage = getLoadedLastPage();

  const nearTop = host.scrollTop <= 120;
  if (nearTop && loadedFirstPage > 1) {
    autoPagingBusy.value = true;
    autoPagingText.value = t("viewer.loading_previous_page");
    try {
      await prependPrevPdfPage(runToken);
    } finally {
      window.setTimeout(() => {
        autoPagingBusy.value = false;
      }, 80);
    }
    return;
  }

  const nearBottom = host.scrollTop + host.clientHeight >= host.scrollHeight - 160;
  if (nearBottom && loadedLastPage < pageCount.value) {
    autoPagingBusy.value = true;
    autoPagingText.value = t("viewer.loading_next_page");
    try {
      await appendNextPdfPage(runToken);
    } finally {
      window.setTimeout(() => {
        autoPagingBusy.value = false;
      }, 80);
    }
  }
}

function handleViewerStageScroll() {
  if (!isPdfLike.value) {
    return;
  }
  if (scrollTicking) {
    return;
  }

  scrollTicking = true;
  window.requestAnimationFrame(() => {
    scrollTicking = false;
    updateCurrentPageByScroll();
    void maybeAutoPageByScroll();
  });
}

async function loadPdfDocument(localToken: number, url: string) {
  const task = pdfjsLib.getDocument({
    url,
    useWorkerFetch: true,
  });
  pdfDoc = await task.promise;
  if (localToken !== runToken) {
    return;
  }

  pageCount.value = Math.max(1, pdfDoc.numPages || 1);
  currentPage.value = clamp(currentPage.value, 1, pageCount.value);
  pageLabel.value = "page";
  resetPdfStack();

  await ensurePdfPageRange(localToken, currentPage.value);
  await nextTick();
  scrollToPdfPage(currentPage.value, "auto");

  if (afterOpenTimer !== null) {
    window.clearTimeout(afterOpenTimer);
  }
  // First render can happen before dialog layout settles; rerender once.
  afterOpenTimer = window.setTimeout(() => {
    if (localToken === runToken) {
      requestSettledPdfRender();
    }
  }, 100);
}

async function loadDocument() {
  fileVersionToken.value = Date.now();
  const localToken = ++runToken;
  loading.value = true;
  errorMessage.value = "";
  textHtml.value = "";
  pageCount.value = 1;
  pageLabel.value = "preview";
  contentFormat.value = "plain";
  resetTablePayload();
  officePdfMode.value = false;
  officePdfError.value = "";
  zoomPercent.value = isPdf.value || isOfficeDoc.value ? 50 : 90;
  resetPdfStack();
  await cancelAllPdfRenderTasks();
  pdfDoc = null;

  if (currentPage.value <= 0) {
    currentPage.value = 1;
  }

  try {
    if (isOfficeDoc.value) {
      try {
        await loadPdfDocument(localToken, previewPdfUrl.value);
        officePdfMode.value = true;
        return;
      } catch (previewError) {
        officePdfMode.value = false;
        officePdfError.value = previewError instanceof Error ? previewError.message : t("viewer.office_pdf_preview_unavailable");
        if (isDocx.value) {
          // Fallback to docx HTML viewer.
          return;
        }
        // Legacy .doc fallback to extracted text preview.
        await renderTextDocument(localToken);
        return;
      }
    }

    if (!isPdf.value) {
      await renderTextDocument(localToken);
      return;
    }

    await loadPdfDocument(localToken, fileUrl.value);
  } catch (error) {
    const message = error instanceof Error ? error.message : t("viewer.file_preview_load_failed");
    errorMessage.value = message;
    emit("error", message);
  } finally {
    if (localToken === runToken) {
      loading.value = false;
    }
  }
}

function onDocxPageState(payload: { currentPage: number; pageCount: number }) {
  if (!isDocx.value || officePdfMode.value) {
    return;
  }
  pageCount.value = Math.max(1, payload.pageCount);
  currentPage.value = clamp(payload.currentPage, 1, pageCount.value);
  pageLabel.value = "page";
}

async function jumpToPdfPage(targetPage: number) {
  const localToken = runToken;
  const safePage = clamp(targetPage, 1, pageCount.value);
  await ensurePdfPageRange(localToken, safePage);
  if (localToken !== runToken) {
    return;
  }
  currentPage.value = safePage;
  scrollToPdfPage(safePage);
}

function goPrevPage() {
  if (isDocx.value && !officePdfMode.value) {
    docxViewerRef.value?.goPrevPage?.();
    return;
  }
  if (currentPage.value <= 1) {
    return;
  }
  const targetPage = currentPage.value - 1;
  if (isPdfLike.value) {
    void jumpToPdfPage(targetPage);
    return;
  }
  currentPage.value = targetPage;
  void loadDocument();
}

function goNextPage() {
  if (isDocx.value && !officePdfMode.value) {
    docxViewerRef.value?.goNextPage?.();
    return;
  }
  if (currentPage.value >= pageCount.value) {
    return;
  }
  const targetPage = currentPage.value + 1;
  if (isPdfLike.value) {
    void jumpToPdfPage(targetPage);
    return;
  }
  currentPage.value = targetPage;
  void loadDocument();
}

function zoomIn() {
  zoomPercent.value = Math.min(240, zoomPercent.value + 10);
  if (isPdfLike.value) {
    void rerenderLoadedPdfPages(runToken);
  }
}

function zoomOut() {
  zoomPercent.value = Math.max(50, zoomPercent.value - 10);
  if (isPdfLike.value) {
    void rerenderLoadedPdfPages(runToken);
  }
}

watch(
  () => [props.sourcePath, props.page, props.snippet],
  () => {
    if (props.page && props.page > 0) {
      currentPage.value = Math.floor(props.page);
    }
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
    void loadDocument();
  },
);

onMounted(() => {
  document.addEventListener("fullscreenchange", syncFullscreenState);
  document.addEventListener("webkitfullscreenchange", syncFullscreenState as EventListener);
  document.addEventListener("msfullscreenchange", syncFullscreenState as EventListener);
  document.addEventListener("MSFullscreenChange", syncFullscreenState as EventListener);
  document.addEventListener("mozfullscreenchange", syncFullscreenState as EventListener);
  syncFullscreenState();
  if (containerRef.value) {
    resizeObserver = new ResizeObserver(() => {
      schedulePdfRerender();
    });
    resizeObserver.observe(containerRef.value);
  }
});

onBeforeUnmount(() => {
  void cancelAllPdfRenderTasks();
  document.removeEventListener("fullscreenchange", syncFullscreenState);
  document.removeEventListener("webkitfullscreenchange", syncFullscreenState as EventListener);
  document.removeEventListener("msfullscreenchange", syncFullscreenState as EventListener);
  document.removeEventListener("MSFullscreenChange", syncFullscreenState as EventListener);
  document.removeEventListener("mozfullscreenchange", syncFullscreenState as EventListener);
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
  autoPagingBusy.value = false;
  scrollTicking = false;
});

defineExpose({
  refreshViewer: () => {
    if (isDocx.value && !officePdfMode.value) {
      docxViewerRef.value?.refreshViewer?.();
      return;
    }
    requestSettledPdfRender();
  },
});
</script>

<template>
  <section ref="viewerRootRef" class="unified-viewer" :class="{ 'is-fullscreen': isFullscreen }">
    <header class="viewer-toolbar">
      <div class="file-name">{{ sourcePath }}</div>
      <div class="toolbar-actions">
        <template v-if="hasPagination">
          <button type="button" class="tool-btn" @click="goPrevPage" :disabled="currentPage <= 1">-1</button>
          <span class="tool-meta">{{ pageLabelText }} {{ currentPage }} / {{ pageCount }}</span>
          <button type="button" class="tool-btn" @click="goNextPage" :disabled="currentPage >= pageCount">+1</button>
          <span class="tool-sep"></span>
        </template>
        <template v-if="isPdfLike">
          <button type="button" class="tool-btn" @click="zoomOut">-</button>
          <span class="tool-meta">{{ zoomPercent }}%</span>
          <button type="button" class="tool-btn" @click="zoomIn">+</button>
        </template>
        <button
          v-if="canFullscreen"
          type="button"
          class="tool-btn tool-icon-btn"
          :title="isFullscreen ? t('viewer.exit_fullscreen') : t('viewer.fullscreen')"
          @click="toggleFullscreen"
        >
          <span aria-hidden="true">⛶</span>
        </button>
        <a :href="fileUrl" target="_blank" rel="noreferrer" class="open-link">{{ t("viewer.open_source_file") }}</a>
      </div>
    </header>

    <div ref="containerRef" class="viewer-stage" @scroll="handleViewerStageScroll">
      <el-skeleton v-if="loading" :rows="8" animated />
      <p v-else-if="errorMessage" class="viewer-error">{{ errorMessage }}</p>
      <template v-else>
        <template v-if="isPdfLike">
          <div ref="pdfStackRef" class="pdf-stack">
            <article
              v-for="pageNumber in renderedPdfPages"
              :key="`pdf-page-${pageNumber}`"
              class="pdf-page"
              :class="{ 'is-current': pageNumber === currentPage }"
              :ref="(node) => setPdfFrameRef(pageNumber, node)"
            >
              <canvas class="pdf-canvas" :ref="(node) => setPdfCanvasRef(pageNumber, node)"></canvas>
              <div class="pdf-text-layer" :ref="(node) => setPdfTextLayerRef(pageNumber, node)"></div>
            </article>
          </div>
          <p v-if="autoPagingBusy" class="pdf-load-more">{{ autoPagingText }}</p>
        </template>

        <template v-else>
          <section v-if="hasSnippet" class="text-hit-callout">
            <small>{{ t("viewer.citation_snippet") }}</small>
            <p>{{ snippet }}</p>
          </section>
          <template v-if="isDocx && !officePdfMode">
            <el-alert
              v-if="officePdfError"
              class="legacy-doc-note"
              type="warning"
              show-icon
              :closable="false"
              :title="t('viewer.office_pdf_unavailable', { error: officePdfError })"
            />
            <DocxPageViewer
              ref="docxViewerRef"
              :source-path="sourcePath"
              :page="currentPage"
              :snippet="snippet"
              :active="active"
              @page-state="onDocxPageState"
              @error="emit('error', $event)"
            />
          </template>
          <template v-else-if="isLegacyDoc && !officePdfMode">
            <el-alert
              class="legacy-doc-note"
              type="warning"
              show-icon
              :closable="false"
              :title="t('viewer.legacy_doc_fallback')"
            />
            <el-alert
              v-if="officePdfError"
              class="legacy-doc-note"
              type="error"
              show-icon
              :closable="false"
              :title="officePdfError"
            />
            <article class="text-page markdown-body" v-html="textHtml"></article>
          </template>
          <SpreadsheetGridViewer
            v-else-if="isTableFormat"
            :headers="tableHeaders"
            :rows="tableRows"
            :data-start-row="tableDataStartRow"
            :snippet="snippet"
            :truncated="tableTruncated"
            :total-rows="tableTotalRows"
            :total-columns="tableTotalColumns"
          />
          <article v-else class="text-page markdown-body" v-html="textHtml"></article>
        </template>
      </template>
    </div>
    <div v-if="showSidePager && hasPagination && !loading && !errorMessage" class="stage-pager-layer">
      <button type="button" class="stage-page-btn is-left" @click="goPrevPage" :disabled="currentPage <= 1">-1</button>
      <button type="button" class="stage-page-btn is-right" @click="goNextPage" :disabled="currentPage >= pageCount">+1</button>
    </div>
  </section>
</template>

<style scoped>
.unified-viewer {
  position: relative;
  border: 1px solid #dde3ea;
  border-radius: 14px;
  overflow: hidden;
  background: linear-gradient(180deg, #ffffff, #f8fafc);
}

.unified-viewer.is-fullscreen {
  border-radius: 0;
  border: none;
  width: 100vw;
  height: 100vh;
  background: #eef2f7;
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
  flex-wrap: nowrap;
}

.tool-btn {
  min-width: 32px;
  height: 28px;
  padding: 0 6px;
  border-radius: 7px;
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

.tool-icon-btn {
  min-width: 34px;
  font-size: 0.95rem;
  font-weight: 700;
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
  position: relative;
  height: 74vh;
  overflow: auto;
  padding: 14px;
}

.unified-viewer.is-fullscreen .viewer-stage {
  height: calc(100vh - 56px);
}

.stage-pager-layer {
  position: absolute;
  inset: 58px 0 0;
  pointer-events: none;
  z-index: 12;
}

.stage-page-btn {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  z-index: 9;
  width: 38px;
  height: 38px;
  border-radius: 999px;
  border: 1px solid #b6c5d7;
  background: rgba(255, 255, 255, 0.92);
  box-shadow: 0 8px 16px rgba(15, 23, 42, 0.12);
  color: #0f172a;
  font-size: 0.78rem;
  font-weight: 700;
  cursor: pointer;
  white-space: nowrap;
  line-height: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  pointer-events: auto;
}

.stage-page-btn:disabled {
  opacity: 0.42;
  cursor: not-allowed;
}

.stage-page-btn.is-left {
  left: 8px;
}

.stage-page-btn.is-right {
  right: 8px;
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

.legacy-doc-note {
  margin: 0 auto 10px;
  max-width: 960px;
}

.pdf-stack {
  display: flex;
  flex-direction: column;
  gap: 16px;
  align-items: center;
  padding: 2px 34px 8px;
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

.pdf-page.is-current {
  box-shadow: 0 0 0 2px rgba(16, 163, 127, 0.32), 0 12px 30px rgba(2, 12, 27, 0.1);
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
  background: rgba(52, 211, 153, 0.46);
  box-shadow: 0 0 0 1px rgba(16, 163, 127, 0.34);
  border-radius: 3px;
}

.pdf-load-more {
  margin: 6px 0 2px;
  text-align: center;
  color: #0f766e;
  font-size: 0.82rem;
}

.text-page {
  max-width: 960px;
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

.markdown-body :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 0.8rem 0;
  table-layout: auto;
}

.markdown-body :deep(th),
.markdown-body :deep(td) {
  border: 1px solid #dbe3ef;
  padding: 0.42rem 0.5rem;
  text-align: left;
  vertical-align: top;
}

.markdown-body :deep(th) {
  background: #f8fafc;
  font-weight: 700;
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

  .pdf-stack {
    padding: 0 20px 6px;
  }
}
</style>

