<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import ChatWorkspace from "./components/chat/ChatWorkspace.vue";
import LeftSidebar from "./components/sidebar/LeftSidebar.vue";
import DocumentsWorkspace from "./components/workspaces/DocumentsWorkspace.vue";
import IndexWorkspace from "./components/workspaces/IndexWorkspace.vue";
import SearchWorkspace from "./components/workspaces/SearchWorkspace.vue";
import { useChatWorkspace } from "./composables/useChatWorkspace";
import { useDashboard } from "./composables/useDashboard";
import { useSearchWorkspace } from "./composables/useSearchWorkspace";
import type { NavTab, WorkspaceTab } from "./types/chat";

const navTabs: NavTab[] = [
  { id: "chat", label: "Chat", subtitle: "streaming Q&A" },
  { id: "documents", label: "Documents", subtitle: "upload and inspect" },
  { id: "index", label: "Index", subtitle: "rebuild and health" },
  { id: "search", label: "Search", subtitle: "retrieval playground" },
];

const activeTab = ref<WorkspaceTab>("chat");
const topK = ref(4);

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

onMounted(async () => {
  chatWorkspace.initialize();
  try {
    await dashboard.refreshDashboard();
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
        :title="chatWorkspace.activeSession.value?.title ?? 'Chat'"
        :messages="chatWorkspace.messages.value"
        :loading="chatWorkspace.loading.value"
        :composer="chatWorkspace.composer.value"
        :top-k="topK"
        :starter-prompts="chatWorkspace.starterPrompts"
        @update:composer="chatWorkspace.composer.value = $event"
        @update:top-k="setTopK"
        @send="chatWorkspace.sendChat"
        @pick-starter="chatWorkspace.useStarterPrompt"
        @viewport-ready="chatWorkspace.setViewport"
      />

      <DocumentsWorkspace
        v-else-if="activeTab === 'documents'"
        :documents="dashboard.documents.value"
        :selected-files="dashboard.selectedFiles.value"
        :uploading="dashboard.uploading.value"
        @files-change="dashboard.setSelectedFiles"
        @upload="dashboard.uploadAndBuild"
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
    </section>
  </main>
</template>
