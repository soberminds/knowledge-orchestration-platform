<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { renderAsync } from "docx-preview";
import { buildFileUrl } from "../../api";

const props = defineProps<{
  sourcePath: string;
  snippet?: string;
  active?: boolean;
}>();

const emit = defineEmits<{
  (event: "error", message: string): void;
}>();

const loading = ref(false);
const errorMessage = ref("");
const containerRef = ref<HTMLElement | null>(null);
const runToken = ref(0);

const fileUrl = computed(() => buildFileUrl(props.sourcePath));

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
  first?.scrollIntoView({ block: "center", behavior: "smooth" });
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
    highlightSnippetInDocx(container, props.snippet ?? "");
  } catch (error) {
    const message = error instanceof Error ? error.message : "Failed to render DOCX preview";
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

onMounted(() => {
  void renderDocxDocument();
});

defineExpose({
  refreshViewer,
});
</script>

<template>
  <section class="docx-viewer">
    <p v-if="errorMessage" class="viewer-error">{{ errorMessage }}</p>
    <div ref="containerRef" class="docx-canvas"></div>
    <div v-if="loading" class="docx-loading-mask">
      <el-skeleton :rows="10" animated />
    </div>
  </section>
</template>

<style scoped>
.docx-viewer {
  position: relative;
  min-height: 360px;
}

.viewer-error {
  margin: 0;
  color: #b42318;
}

.docx-canvas {
  min-height: 360px;
  border: 1px solid #d9e2ef;
  border-radius: 14px;
  background: #e7eaef;
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
  padding: 24px 0;
}

.docx-canvas :deep(.docx-wrapper > section.docx) {
  margin: 0 auto 24px;
  box-shadow: 0 14px 28px rgba(15, 23, 42, 0.16);
  border: 1px solid #dbe3ef;
  background: #fff;
}

.docx-canvas :deep(mark.docx-hit) {
  background: rgba(52, 211, 153, 0.38);
  box-shadow: 0 0 0 1px rgba(16, 163, 127, 0.2);
  border-radius: 3px;
  padding: 0 1px;
}
</style>
