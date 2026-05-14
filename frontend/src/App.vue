<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import ChatWorkspace from "./components/chat/ChatWorkspace.vue";
import LeftSidebar from "./components/sidebar/LeftSidebar.vue";
import OnlyOfficeEditor from "./components/viewer/OnlyOfficeEditor.vue";
import UnifiedFileViewer from "./components/viewer/UnifiedFileViewer.vue";
import DocumentsWorkspace from "./components/workspaces/DocumentsWorkspace.vue";
import IndexWorkspace from "./components/workspaces/IndexWorkspace.vue";
import SearchWorkspace from "./components/workspaces/SearchWorkspace.vue";
import { useI18n } from "./composables/useI18n";
import { useChatWorkspace } from "./composables/useChatWorkspace";
import { useDashboard } from "./composables/useDashboard";
import { useSearchWorkspace } from "./composables/useSearchWorkspace";
import type { NavTab, WorkspaceTab } from "./types/chat";

const { t } = useI18n();
const navTabs = computed<NavTab[]>(() => [
  { id: "chat", label: t("nav.chat.label"), subtitle: t("nav.chat.subtitle") },
  { id: "documents", label: t("nav.documents.label"), subtitle: t("nav.documents.subtitle") },
  { id: "index", label: t("nav.index.label"), subtitle: t("nav.index.subtitle") },
  { id: "search", label: t("nav.search.label"), subtitle: t("nav.search.subtitle") },
]);

const activeTab = ref<WorkspaceTab>("chat");
const topK = ref(4);
const documentViewerVisible = ref(false);
const documentViewerPath = ref("");
const documentViewerError = ref("");
const documentViewerRef = ref<InstanceType<typeof UnifiedFileViewer> | null>(null);
const officeEditorVisible = ref(false);
const officeEditorPath = ref("");
const officeEditorError = ref("");
const officeEditorFullscreen = ref(false);
const officeEditorRef = ref<InstanceType<typeof OnlyOfficeEditor> | null>(null);

const dashboard = useDashboard();
const chatWorkspace = useChatWorkspace(topK);
const searchWorkspace = useSearchWorkspace(topK);

const activeErrorMessage = computed(() => {
  if (activeTab.value === "chat") {
    return chatWorkspace.errorMessage.value;
  }
  if (activeTab.value === "search") {
    return searchWorkspace.errorMessage.value;
  }
  return dashboard.errorMessage.value;
});

const officeEditorHostStyle = computed(() => ({
  height: officeEditorFullscreen.value ? "calc(100vh - 74px)" : "82vh",
}));

function switchTab(tab: WorkspaceTab) {
  activeTab.value = tab;
}

function openSession(sessionId: string) {
  chatWorkspace.switchSession(sessionId);
  activeTab.value = "chat";
}

function createNewChat() {
  chatWorkspace.newChat();
  activeTab.value = "chat";
}

function setTopK(value: number) {
  if (!Number.isFinite(value)) {
    return;
  }
  topK.value = Math.max(1, Math.min(10, Math.round(value)));
}

function openDocumentFromWorkspace(path: string) {
  documentViewerPath.value = path;
  documentViewerError.value = "";
  documentViewerVisible.value = true;
}

function openOfficeEditorFromWorkspace(path: string) {
  officeEditorPath.value = path;
  officeEditorError.value = "";
  officeEditorFullscreen.value = false;
  officeEditorVisible.value = true;
}

async function deleteDocumentFromWorkspace(path: string) {
  try {
    await dashboard.deleteDocument(path);
    if (documentViewerVisible.value && documentViewerPath.value === path) {
      documentViewerVisible.value = false;
      documentViewerPath.value = "";
      documentViewerError.value = "";
    }
    if (officeEditorVisible.value && officeEditorPath.value === path) {
      officeEditorVisible.value = false;
      officeEditorPath.value = "";
      officeEditorError.value = "";
    }
  } catch {
    // The composable already stores the error message for display.
  }
}

async function onDocumentSaved() {
  try {
    await dashboard.refreshDashboard();
  } catch {
    // Error is already tracked by useDashboard state.
  }
}

function onDocumentViewerOpened() {
  documentViewerRef.value?.refreshViewer?.();
}

async function onOfficeEditorClosed() {
  officeEditorFullscreen.value = false;
  officeEditorPath.value = "";
  officeEditorError.value = "";
  try {
    await dashboard.refreshDashboard();
  } catch {
    // Error is already tracked by useDashboard state.
  }
}

function toggleOfficeEditorFullscreen() {
  officeEditorFullscreen.value = !officeEditorFullscreen.value;
}

function notifyOfficeEditorResize() {
  officeEditorRef.value?.resizeEditor?.();
  window.setTimeout(() => {
    window.dispatchEvent(new Event("resize"));
    officeEditorRef.value?.resizeEditor?.();
  }, 80);
}

watch(
  () => officeEditorFullscreen.value,
  async () => {
    if (!officeEditorVisible.value) {
      return;
    }
    await nextTick();
    notifyOfficeEditorResize();
  },
);

onMounted(async () => {
  chatWorkspace.initialize();
  try {
    await dashboard.refreshDashboard({ retries: 2 });
  } catch {
    // Error text is already captured in composable state.
  }
});
</script>

<template>
  <main class="app-shell">
    <LeftSidebar
      :nav-tabs="navTabs"
      :active-tab="activeTab"
      :recent-sessions="chatWorkspace.recentSessions.value"
      :active-session-id="chatWorkspace.activeSessionId.value"
      :status-text="dashboard.statusText.value"
      :document-count="dashboard.documents.value.length"
      :indexed-chunks="dashboard.indexedChunks.value"
      @new-chat="createNewChat"
      @select-tab="switchTab"
      @select-session="openSession"
    />

    <section class="main-workspace">
      <section v-if="activeErrorMessage" class="notice-row">
        <el-alert :title="activeErrorMessage" type="error" show-icon :closable="false" />
      </section>

      <ChatWorkspace
        v-if="activeTab === 'chat'"
        :title="chatWorkspace.activeSession.value?.title ?? t('app.chat_default_title')"
        :messages="chatWorkspace.messages.value"
        :loading="chatWorkspace.loading.value"
        :composer="chatWorkspace.composer.value"
        :top-k="topK"
        :starter-prompts="chatWorkspace.starterPrompts.value"
        :available-models="chatWorkspace.availableModels.value"
        :model-options="chatWorkspace.modelOptions.value"
        :selected-model="chatWorkspace.selectedModel.value"
        :thinking-mode="chatWorkspace.thinkingMode.value"
        :native-web-search-enabled="chatWorkspace.nativeWebSearchEnabled.value"
        :native-web-search-supported="chatWorkspace.selectedModelSupportsNativeSearch.value"
        :external-web-search-enabled="chatWorkspace.externalWebSearchEnabled.value"
        :external-web-search-available="chatWorkspace.externalWebSearchAvailable.value"
        :options-loading="chatWorkspace.optionsLoading.value"
        :options-last-checked-at="chatWorkspace.optionsLastCheckedAt.value"
        @update:composer="chatWorkspace.composer.value = $event"
        @update:top-k="setTopK"
        @update:selected-model="chatWorkspace.setSelectedModel($event)"
        @update:thinking-mode="chatWorkspace.thinkingMode.value = $event"
        @update:native-web-search-enabled="chatWorkspace.nativeWebSearchEnabled.value = $event"
        @update:external-web-search-enabled="chatWorkspace.externalWebSearchEnabled.value = $event"
        @refresh-model-options="chatWorkspace.loadChatOptions"
        @send="chatWorkspace.sendChat"
        @pick-starter="chatWorkspace.useStarterPrompt"
        @viewport-ready="chatWorkspace.setViewport"
      />

      <DocumentsWorkspace
        v-else-if="activeTab === 'documents'"
        :documents="dashboard.documents.value"
        :office-health="dashboard.officeHealth.value"
        :office-health-loading="dashboard.officeHealthLoading.value"
        :office-health-error="dashboard.officeHealthError.value"
        :selected-files="dashboard.selectedFiles.value"
        :uploading="dashboard.uploading.value"
        :deleting-path="dashboard.deletingPath.value"
        @files-change="dashboard.setSelectedFiles"
        @upload="dashboard.uploadAndBuild"
        @refresh-office-health="dashboard.refreshOfficeHealth"
        @open-document="openDocumentFromWorkspace"
        @open-office-editor="openOfficeEditorFromWorkspace"
        @delete-document="deleteDocumentFromWorkspace"
        @document-saved="onDocumentSaved"
      />

      <IndexWorkspace
        v-else-if="activeTab === 'index'"
        :health="dashboard.health.value"
        :status-text="dashboard.statusText.value"
        :indexed-chunks="dashboard.indexedChunks.value"
        :ingesting="dashboard.ingesting.value"
        :refreshing="dashboard.refreshing.value"
        @rebuild="dashboard.runIngest"
        @refresh="dashboard.refreshDashboard"
      />

      <SearchWorkspace
        v-else
        :query="searchWorkspace.query.value"
        :hits="searchWorkspace.hits.value"
        :searching="searchWorkspace.searching.value"
        :top-k="topK"
        @update:query="searchWorkspace.query.value = $event"
        @update:top-k="setTopK"
        @run-search="searchWorkspace.runSearch"
      />

      <el-dialog
        v-model="documentViewerVisible"
        width="92%"
        top="3vh"
        append-to-body
        :title="documentViewerPath || t('app.document_viewer_title')"
        @opened="onDocumentViewerOpened"
      >
        <section class="viewer-host">
          <el-alert
            v-if="documentViewerError"
            :title="documentViewerError"
            type="error"
            show-icon
            :closable="false"
            class="viewer-error-banner"
          />
          <UnifiedFileViewer
            ref="documentViewerRef"
            :source-path="documentViewerPath"
            :page="1"
            :snippet="''"
            :active="documentViewerVisible"
            @error="documentViewerError = $event"
          />
        </section>
      </el-dialog>

      <el-dialog
        v-model="officeEditorVisible"
        :fullscreen="officeEditorFullscreen"
        :width="officeEditorFullscreen ? '100%' : '96%'"
        :top="officeEditorFullscreen ? '0' : '2vh'"
        append-to-body
        destroy-on-close
        class="office-editor-dialog"
        @opened="notifyOfficeEditorResize"
        @closed="onOfficeEditorClosed"
      >
        <template #header>
          <div class="dialog-head">
            <span class="dialog-title">{{ officeEditorPath || t("documents.office_edit") }}</span>
            <button
              type="button"
              class="dialog-tool-btn dialog-tool-icon-btn"
              :title="officeEditorFullscreen ? t('viewer.exit_fullscreen') : t('viewer.fullscreen')"
              @click="toggleOfficeEditorFullscreen"
            >
              <svg
                v-if="!officeEditorFullscreen"
                class="dialog-tool-icon"
                viewBox="0 0 20 20"
                aria-hidden="true"
              >
                <path d="M4 8V4h4M12 4h4v4M16 12v4h-4M8 16H4v-4"></path>
              </svg>
              <svg
                v-else
                class="dialog-tool-icon"
                viewBox="0 0 20 20"
                aria-hidden="true"
              >
                <path d="M8 4H4v4M12 4h4v4M4 12v4h4M16 12v4h-4"></path>
                <path d="M8 8L4 4M12 8l4-4M8 12l-4 4M12 12l4 4"></path>
              </svg>
            </button>
          </div>
        </template>

        <section class="viewer-host office-viewer-host" :style="officeEditorHostStyle">
          <el-alert
            v-if="officeEditorError"
            :title="officeEditorError"
            type="error"
            show-icon
            :closable="false"
            class="viewer-error-banner"
          />
          <OnlyOfficeEditor
            ref="officeEditorRef"
            :visible="officeEditorVisible"
            :source-path="officeEditorPath"
            mode="edit"
            @error="officeEditorError = $event"
          />
        </section>
      </el-dialog>
    </section>
  </main>
</template>

<style scoped>
.viewer-host {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.viewer-error-banner {
  margin-bottom: 2px;
}

.dialog-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.dialog-title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 1rem;
  font-weight: 600;
  color: #0f172a;
}

.dialog-tool-btn {
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

.dialog-tool-icon-btn {
  min-width: 34px;
  padding: 0;
}

.dialog-tool-icon {
  width: 14px;
  height: 14px;
  stroke: currentColor;
  stroke-width: 1.7;
  fill: none;
  vector-effect: non-scaling-stroke;
}

.office-viewer-host {
  flex: 1;
  min-height: 0;
}

.office-viewer-host :deep(.onlyoffice-root) {
  flex: 1;
  min-height: 0;
}

:deep(.el-dialog.office-editor-dialog) {
  display: flex;
  flex-direction: column;
  max-height: calc(100vh - 4vh);
}

:deep(.el-dialog.office-editor-dialog.is-fullscreen) {
  height: 100vh;
  max-height: 100vh;
}

:deep(.office-editor-dialog .el-dialog__header) {
  margin-right: 0;
  padding: 10px 14px;
  border-bottom: 1px solid #e7ecf3;
  background: #f4f8fc;
}

:deep(.office-editor-dialog .el-dialog__body) {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 10px 12px 12px;
}
</style>
