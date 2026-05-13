<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import ChatWorkspace from "./components/chat/ChatWorkspace.vue";
import LeftSidebar from "./components/sidebar/LeftSidebar.vue";
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

async function deleteDocumentFromWorkspace(path: string) {
  try {
    await dashboard.deleteDocument(path);
    if (documentViewerVisible.value && documentViewerPath.value === path) {
      documentViewerVisible.value = false;
      documentViewerPath.value = "";
      documentViewerError.value = "";
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
        :selected-files="dashboard.selectedFiles.value"
        :uploading="dashboard.uploading.value"
        :deleting-path="dashboard.deletingPath.value"
        @files-change="dashboard.setSelectedFiles"
        @upload="dashboard.uploadAndBuild"
        @open-document="openDocumentFromWorkspace"
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
    </section>
  </main>
</template>

<style scoped>
.viewer-host {
  display: grid;
  gap: 10px;
}

.viewer-error-banner {
  margin-bottom: 2px;
}
</style>
