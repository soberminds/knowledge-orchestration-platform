<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
import { getOfficeCallbackStatus, getOfficeEditorConfig, type OfficeCallbackStatusResponse } from "../../api";
import { useI18n } from "../../composables/useI18n";

type OfficeEditorMode = "edit" | "view";

const props = defineProps<{
  visible: boolean;
  sourcePath: string;
  mode?: OfficeEditorMode;
}>();

const emit = defineEmits<{
  (event: "error", message: string): void;
  (event: "ready"): void;
}>();

const { locale, t } = useI18n();
const loading = ref(false);
const loadError = ref("");
const editorHostRef = ref<HTMLElement | null>(null);
const activeScriptSrc = ref("");
const editorInstance = ref<any>(null);
const callbackStatus = ref<OfficeCallbackStatusResponse | null>(null);
const callbackStatusTimer = ref<number | null>(null);

const callbackStatusTagType = computed(() => {
  const payload = callbackStatus.value;
  if (!payload || !payload.has_event || payload.status === "unknown") {
    return "info";
  }
  return payload.status === "success" ? "success" : "danger";
});

const callbackStatusLabel = computed(() => {
  const payload = callbackStatus.value;
  if (!payload || !payload.has_event || payload.status === "unknown") {
    return t("documents.office_callback_status_unknown");
  }
  if (payload.status === "success") {
    return t("documents.office_callback_status_success");
  }
  return t("documents.office_callback_status_failed");
});

const callbackStatusTimeText = computed(() => {
  const payload = callbackStatus.value;
  if (!payload?.has_event || !payload.updated_at) {
    return t("documents.office_callback_not_saved");
  }
  const parsed = new Date(payload.updated_at);
  if (Number.isNaN(parsed.getTime())) {
    return payload.updated_at;
  }
  return parsed.toLocaleString();
});

const callbackStatusMessage = computed(() => {
  const payload = callbackStatus.value;
  if (!payload?.has_event || !payload.message) {
    return "";
  }
  return payload.message;
});

function setError(message: string) {
  loadError.value = message;
  emit("error", message);
}

function clearError() {
  loadError.value = "";
}

function clearCallbackStatus() {
  callbackStatus.value = null;
}

function stopCallbackStatusPolling() {
  if (callbackStatusTimer.value !== null) {
    window.clearInterval(callbackStatusTimer.value);
    callbackStatusTimer.value = null;
  }
}

async function refreshCallbackStatus() {
  const sourcePath = props.sourcePath?.trim();
  if (!sourcePath) {
    clearCallbackStatus();
    return;
  }

  try {
    callbackStatus.value = await getOfficeCallbackStatus(sourcePath);
  } catch {
    // Callback status is a best-effort UX hint.
  }
}

function startCallbackStatusPolling() {
  stopCallbackStatusPolling();
  if (!props.visible || !props.sourcePath?.trim()) {
    clearCallbackStatus();
    return;
  }

  void refreshCallbackStatus();
  callbackStatusTimer.value = window.setInterval(() => {
    void refreshCallbackStatus();
  }, 2500);
}

function destroyEditor() {
  try {
    if (editorInstance.value && typeof editorInstance.value.destroyEditor === "function") {
      editorInstance.value.destroyEditor();
    }
  } catch {
    // Ignore destroy errors from third-party SDK.
  } finally {
    editorInstance.value = null;
  }

  if (editorHostRef.value) {
    editorHostRef.value.innerHTML = "";
  }
}

function resolveDocsApiScript(windowObj: Window): any {
  return (windowObj as any).DocsAPI;
}

function loadDocsApiScript(documentServerUrl: string): Promise<void> {
  const normalized = documentServerUrl.replace(/\/+$/, "");
  const scriptSrc = `${normalized}/web-apps/apps/api/documents/api.js`;
  const globalWindow = window as Window;
  const existingApi = resolveDocsApiScript(globalWindow);

  if (existingApi) {
    if (activeScriptSrc.value && activeScriptSrc.value !== scriptSrc) {
      return Promise.reject(new Error("ONLYOFFICE API already loaded from a different origin. Please refresh the page."));
    }
    activeScriptSrc.value = scriptSrc;
    return Promise.resolve();
  }

  const existingScript = document.querySelector<HTMLScriptElement>("script[data-onlyoffice-api='1']");
  if (existingScript) {
    if (existingScript.src === scriptSrc) {
      return new Promise((resolve, reject) => {
        existingScript.addEventListener("load", () => resolve(), { once: true });
        existingScript.addEventListener("error", () => reject(new Error("Failed to load ONLYOFFICE API script.")), { once: true });
      });
    }
    existingScript.remove();
  }

  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = scriptSrc;
    script.async = true;
    script.defer = true;
    script.setAttribute("data-onlyoffice-api", "1");
    script.onload = () => {
      activeScriptSrc.value = scriptSrc;
      resolve();
    };
    script.onerror = () => reject(new Error("Failed to load ONLYOFFICE API script."));
    document.head.appendChild(script);
  });
}

async function openOnlyOfficeEditor() {
  const sourcePath = props.sourcePath?.trim();
  if (!props.visible || !sourcePath) {
    return;
  }

  loading.value = true;
  clearError();
  destroyEditor();

  try {
    const mode: OfficeEditorMode = props.mode === "view" ? "view" : "edit";
    const payload = await getOfficeEditorConfig(sourcePath, {
      mode,
      lang: locale.value,
    });

    await loadDocsApiScript(payload.document_server_url);
    await nextTick();

    if (!editorHostRef.value) {
      throw new Error("Editor mount point is missing.");
    }

    const docsApi = resolveDocsApiScript(window as Window);
    if (!docsApi || typeof docsApi.DocEditor !== "function") {
      throw new Error("ONLYOFFICE DocsAPI is unavailable.");
    }

    const editorId = `onlyoffice-editor-${Date.now()}`;
    editorHostRef.value.id = editorId;
    editorInstance.value = new docsApi.DocEditor(editorId, payload.config);
    emit("ready");
  } catch (error) {
    const message = error instanceof Error ? error.message : t("documents.office_open_failed");
    setError(message);
  } finally {
    loading.value = false;
  }
}

watch(
  () => [props.visible, props.sourcePath, props.mode, locale.value] as const,
  async () => {
    if (!props.visible) {
      stopCallbackStatusPolling();
      clearCallbackStatus();
      destroyEditor();
      clearError();
      return;
    }
    startCallbackStatusPolling();
    await openOnlyOfficeEditor();
  },
  { immediate: true },
);

onBeforeUnmount(() => {
  stopCallbackStatusPolling();
  destroyEditor();
});
</script>

<template>
  <section class="onlyoffice-root">
    <el-alert
      v-if="loadError"
      :title="loadError"
      type="error"
      show-icon
      :closable="false"
      class="onlyoffice-alert"
    />
    <section class="onlyoffice-callback-status">
      <span class="onlyoffice-callback-label">{{ t("documents.office_callback_last_save") }}</span>
      <el-tag size="small" :type="callbackStatusTagType">
        {{ callbackStatusLabel }}
      </el-tag>
      <span class="onlyoffice-callback-time">{{ callbackStatusTimeText }}</span>
      <span v-if="callbackStatusMessage" class="onlyoffice-callback-message">{{ callbackStatusMessage }}</span>
    </section>

    <section v-loading="loading" class="onlyoffice-stage">
      <div ref="editorHostRef" class="onlyoffice-host" />
    </section>
  </section>
</template>

<style scoped>
.onlyoffice-root {
  height: 100%;
  min-height: 0;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  gap: 8px;
}

.onlyoffice-alert {
  margin-bottom: 2px;
}

.onlyoffice-callback-status {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  background: #f8fafc;
  color: #334155;
  font-size: 12px;
}

.onlyoffice-callback-label {
  font-weight: 600;
  color: #0f172a;
}

.onlyoffice-callback-time {
  color: #475569;
}

.onlyoffice-callback-message {
  color: #64748b;
}

.onlyoffice-stage {
  min-height: 70vh;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  overflow: hidden;
  background: #fff;
}

.onlyoffice-host {
  width: 100%;
  height: 100%;
  min-height: 70vh;
}
</style>
