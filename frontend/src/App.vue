<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import {
  ArrowDown,
  Key,
  Moon,
  Operation,
  Service,
  Sunny,
  Switch,
  User,
} from "@element-plus/icons-vue";
import ChatWorkspace from "./components/chat/ChatWorkspace.vue";
import AuthScreen from "./components/AuthScreen.vue";
import LeftSidebar from "./components/sidebar/LeftSidebar.vue";
import OnlyOfficeEditor from "./components/viewer/OnlyOfficeEditor.vue";
import UnifiedFileViewer from "./components/viewer/UnifiedFileViewer.vue";
import DocumentsWorkspace from "./components/workspaces/DocumentsWorkspace.vue";
import IndexWorkspace from "./components/workspaces/IndexWorkspace.vue";
import SearchWorkspace from "./components/workspaces/SearchWorkspace.vue";
import { useAuth } from "./composables/useAuth";
import { useI18n } from "./composables/useI18n";
import { useChatWorkspace } from "./composables/useChatWorkspace";
import { useDashboard } from "./composables/useDashboard";
import { useSearchWorkspace } from "./composables/useSearchWorkspace";
import type { LocaleCode } from "./i18n/messages";
import type { NavTab, WorkspaceTab } from "./types/chat";
import { isOnlyOfficeDocument } from "./utils/documentRouting";

const THEME_STORAGE_KEY = "kop.theme";

function readInitialDarkMode() {
  if (typeof window === "undefined") {
    return false;
  }
  const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
  if (stored === "dark") {
    return true;
  }
  if (stored === "light") {
    return false;
  }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
}

const { locale, localeOptions, setLocale, t } = useI18n();
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
const documentViewerFileId = ref<number | null>(null);
const documentViewerError = ref("");
const documentViewerRef = ref<InstanceType<typeof UnifiedFileViewer> | null>(null);
const officeEditorVisible = ref(false);
const officeEditorPath = ref("");
const officeEditorFileId = ref<number | null>(null);
const officeEditorError = ref("");
const officeEditorFullscreen = ref(false);
const officeEditorMode = ref<"edit" | "view">("edit");
const officeEditorRef = ref<InstanceType<typeof OnlyOfficeEditor> | null>(null);
const authScreenMode = ref<"login" | "register">("login");
const authEntryMode = ref<"auth" | "app">("auth");
const authBootstrapped = ref(false);
const sidebarCollapsed = ref(false);
const isDarkMode = ref(readInitialDarkMode());

const dashboard = useDashboard();
const chatWorkspace = useChatWorkspace(topK);
const searchWorkspace = useSearchWorkspace(topK);
const auth = useAuth();

const activeTabMeta = computed(() => navTabs.value.find((tab) => tab.id === activeTab.value));
const activeTabTitle = computed(() => activeTabMeta.value?.label ?? t("sidebar.workspaces"));
const activeTabSubtitle = computed(() => activeTabMeta.value?.subtitle ?? "");
const isAuthenticated = computed(() => Boolean(auth.currentUser.value?.authenticated && !auth.currentUser.value?.is_guest));

const userDisplayName = computed(() => {
  const currentUser = auth.currentUser.value;
  if (!currentUser || currentUser.is_guest) {
    return "游客";
  }
  return currentUser.nickname || currentUser.username || t("sidebar.guest_user_name");
});

const userStatusLabel = computed(() => (isAuthenticated.value ? t("sidebar.auth_status_authenticated") : t("sidebar.auth_status_guest")));

const userMetaLabel = computed(() => {
  const currentUser = auth.currentUser.value;
  if (!currentUser) {
    return "";
  }
  if (currentUser.is_guest) {
    return `默认本地用户 ${currentUser.username || "local-user"}`;
  }
  return currentUser.username || "";
});

const userInitial = computed(() => {
  const text = userDisplayName.value.trim();
  return text ? text.slice(0, 1).toUpperCase() : "U";
});

function localeDisplayName(code: LocaleCode) {
  return code === "zh-CN" ? "中文" : "English";
}

const currentLocaleName = computed(() => localeDisplayName(locale.value));
const userMenuPopperClass = computed(() =>
  ["user-dropdown-popper", isDarkMode.value ? "is-dark-mode" : ""].filter(Boolean).join(" "),
);
const showAuthScreen = computed(() => authBootstrapped.value && !isAuthenticated.value && authEntryMode.value === "auth");

const activeErrorMessage = computed(() => {
  if (auth.errorMessage.value) {
    return auth.errorMessage.value;
  }
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

function pathMatchesOrIsChild(targetPath: string, parentPath: string) {
  if (!parentPath) {
    return true;
  }
  return targetPath === parentPath || targetPath.startsWith(`${parentPath}/`);
}

const officeDialogTitle = computed(() => {
  if (officeEditorPath.value) {
    return officeEditorPath.value;
  }
  return officeEditorMode.value === "view" ? t("documents.open") : t("documents.office_edit");
});

function switchTab(tab: WorkspaceTab) {
  activeTab.value = tab;
}

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value;
}

function toggleDarkMode() {
  isDarkMode.value = !isDarkMode.value;
}

function handleLocaleCommand(command: string | number | object) {
  if (typeof command !== "string") {
    return;
  }
  if (localeOptions.some((option) => option.code === command)) {
    setLocale(command as LocaleCode);
  }
}

function handleUserMenuCommand(command: string | number | object) {
  if (command === "login") {
    openAuthScreen("login");
    return;
  }
  if (command === "register") {
    openAuthScreen("register");
    return;
  }
  if (command === "logout") {
    void handleLogout();
    return;
  }
  if (command === "profile") {
    ElMessage.info("个人资料功能暂未开放");
    return;
  }
  if (command === "api-key") {
    ElMessage.info("API 密钥功能暂未开放");
    return;
  }
  if (command === "contact") {
    ElMessage.info("联系客服：微信 Starry-Stream");
  }
}

function setEntryMode(value: "auth" | "app") {
  authEntryMode.value = value;
}

function openAuthScreen(mode: "login" | "register") {
  authScreenMode.value = mode;
  setEntryMode("auth");
  auth.clearError();
}

async function continueAsGuest() {
  setEntryMode("app");
  auth.clearError();
  await refreshDataAfterAuthChange();
}

function resetWorkspaceForUserChange() {
  chatWorkspace.resetForUserChange();
  searchWorkspace.resetForUserChange();
  dashboard.resetForUserChange();
  closeDocumentViewerState();
  resetOfficeEditorState();
  activeTab.value = "chat";
}

async function refreshDataAfterAuthChange() {
  resetWorkspaceForUserChange();
  await chatWorkspace.initialize();
  await dashboard.refreshDashboard({ retries: 2 });
}

async function syncCurrentUser() {
  try {
    await auth.loadCurrentUser();
  } catch {
    auth.clearError();
    // keep guest fallback
  }
}

async function submitAuthDialog(payload: { username: string; password: string; nickname: string | null }) {
  const username = payload.username.trim();
  const password = payload.password.trim();
  const nickname = payload.nickname?.trim() ?? "";
  if (!username || !password) {
    ElMessage.warning(t("sidebar.auth_form_required"));
    return;
  }

  try {
    if (authScreenMode.value === "register") {
      await auth.register({
        username,
        password,
        nickname: nickname || null,
      });
      ElMessage.success(t("sidebar.register_success"));
    } else {
      await auth.login({
        username,
        password,
      });
      ElMessage.success(t("sidebar.login_success"));
    }
    setEntryMode("app");
    await refreshDataAfterAuthChange();
  } catch {
    // auth.errorMessage is already shown in sidebar and dialog.
  }
}

async function handleLogout() {
  try {
    await auth.logout();
    ElMessage.success(t("sidebar.logout_success"));
    authScreenMode.value = "login";
    setEntryMode("auth");
    resetWorkspaceForUserChange();
    await syncCurrentUser();
  } catch {
    // auth.errorMessage is already shown in sidebar and dialog.
  }
}

function openSession(sessionId: string) {
  void chatWorkspace.switchSession(sessionId);
  activeTab.value = "chat";
}

function createNewChat() {
  chatWorkspace.newChat();
  activeTab.value = "chat";
}

function useCurrentFolderInChat(folderPath: string, folderId: number | null) {
  if (!folderPath || folderId == null) {
    chatWorkspace.setScopeType("all");
    chatWorkspace.setScopeId(null);
    chatWorkspace.setWorkspaceKey(null);
    chatWorkspace.setScopeName(null);
    activeTab.value = "chat";
    return;
  }

  chatWorkspace.setScopeType("folder");
  chatWorkspace.setScopeId(folderId);
  chatWorkspace.setWorkspaceKey(null);
  chatWorkspace.setScopeName(folderPath);
  activeTab.value = "chat";
}

function setTopK(value: number) {
  if (!Number.isFinite(value)) {
    return;
  }
  topK.value = Math.max(1, Math.min(10, Math.round(value)));
}

function closeDocumentViewerState() {
  documentViewerVisible.value = false;
  documentViewerPath.value = "";
  documentViewerFileId.value = null;
  documentViewerError.value = "";
}

function resetOfficeEditorState() {
  officeEditorPath.value = "";
  officeEditorFileId.value = null;
  officeEditorError.value = "";
  officeEditorFullscreen.value = false;
  officeEditorMode.value = "edit";
}

function openDocumentFromWorkspace(path: string, fileId?: number | null) {
  if (isOnlyOfficeDocument(path)) {
    closeDocumentViewerState();
    officeEditorPath.value = path;
    officeEditorFileId.value = fileId ?? null;
    officeEditorError.value = "";
    officeEditorFullscreen.value = false;
    officeEditorMode.value = "view";
    officeEditorVisible.value = true;
    return;
  }

  if (officeEditorVisible.value) {
    officeEditorVisible.value = false;
  }
  resetOfficeEditorState();
  documentViewerPath.value = path;
  documentViewerFileId.value = fileId ?? null;
  documentViewerError.value = "";
  documentViewerVisible.value = true;
}

function openOfficeEditorFromWorkspace(path: string, fileId?: number | null) {
  closeDocumentViewerState();
  officeEditorPath.value = path;
  officeEditorFileId.value = fileId ?? null;
  officeEditorError.value = "";
  officeEditorFullscreen.value = false;
  officeEditorMode.value = "edit";
  officeEditorVisible.value = true;
}

async function deleteDocumentFromWorkspace(path: string, fileId?: number | null) {
  try {
    await dashboard.deleteDocument(path, fileId ?? null);
    const viewerMatches = (fileId != null && documentViewerFileId.value === fileId) || documentViewerPath.value === path;
    const editorMatches = (fileId != null && officeEditorFileId.value === fileId) || officeEditorPath.value === path;
    if (documentViewerVisible.value && viewerMatches) {
      closeDocumentViewerState();
    }
    if (officeEditorVisible.value && editorMatches) {
      officeEditorVisible.value = false;
      resetOfficeEditorState();
    }
  } catch {
    // The composable already stores the error message for display.
  }
}

async function deleteFolderFromWorkspace(path: string) {
  try {
    await dashboard.deleteDocumentFolder(path);
    if (documentViewerVisible.value && pathMatchesOrIsChild(documentViewerPath.value, path)) {
      closeDocumentViewerState();
    }
    if (officeEditorVisible.value && pathMatchesOrIsChild(officeEditorPath.value, path)) {
      officeEditorVisible.value = false;
      resetOfficeEditorState();
    }
  } catch {
    // The composable already stores the error message for display.
  }
}

async function renameDocumentFromWorkspace(path: string, newName: string, fileId?: number | null) {
  try {
    const result = await dashboard.renameDocument(path, newName, fileId ?? null);
    const nextPath = result?.path || path;
    const viewerMatches = (fileId != null && documentViewerFileId.value === fileId) || documentViewerPath.value === path;
    const editorMatches = (fileId != null && officeEditorFileId.value === fileId) || officeEditorPath.value === path;
    if (documentViewerVisible.value && viewerMatches) {
      documentViewerPath.value = nextPath;
    }
    if (officeEditorVisible.value && editorMatches) {
      officeEditorPath.value = nextPath;
    }
  } catch {
    // The composable already stores the error message for display.
  }
}

async function moveDocumentFromWorkspace(path: string, parentPath: string, parentId?: number | null, fileId?: number | null) {
  try {
    const result = await dashboard.moveDocument(path, parentPath, parentId, fileId ?? null);
    const nextPath = result?.path || path;
    const viewerMatches = (fileId != null && documentViewerFileId.value === fileId) || documentViewerPath.value === path;
    const editorMatches = (fileId != null && officeEditorFileId.value === fileId) || officeEditorPath.value === path;
    if (documentViewerVisible.value && viewerMatches) {
      documentViewerPath.value = nextPath;
    }
    if (officeEditorVisible.value && editorMatches) {
      officeEditorPath.value = nextPath;
    }
  } catch {
    // The composable already stores the error message for display.
  }
}

async function renameFolderFromWorkspace(path: string, newName: string) {
  try {
    await dashboard.renameDocumentFolder(path, newName);
    if (documentViewerVisible.value && pathMatchesOrIsChild(documentViewerPath.value, path)) {
      closeDocumentViewerState();
    }
    if (officeEditorVisible.value && pathMatchesOrIsChild(officeEditorPath.value, path)) {
      officeEditorVisible.value = false;
      resetOfficeEditorState();
    }
  } catch {
    // The composable already stores the error message for display.
  }
}

async function moveFolderFromWorkspace(path: string, parentPath: string, parentId?: number | null) {
  try {
    await dashboard.moveDocumentFolder(path, parentPath, parentId);
    if (documentViewerVisible.value && pathMatchesOrIsChild(documentViewerPath.value, path)) {
      closeDocumentViewerState();
    }
    if (officeEditorVisible.value && pathMatchesOrIsChild(officeEditorPath.value, path)) {
      officeEditorVisible.value = false;
      resetOfficeEditorState();
    }
  } catch {
    // The composable already stores the error message for display.
  }
}

async function onDocumentSaved(path: string, fileId?: number | null) {
  try {
    if (documentViewerVisible.value && ((fileId != null && documentViewerFileId.value === fileId) || documentViewerPath.value === path)) {
      documentViewerPath.value = path;
      documentViewerFileId.value = fileId ?? documentViewerFileId.value;
    }
    if (officeEditorVisible.value && ((fileId != null && officeEditorFileId.value === fileId) || officeEditorPath.value === path)) {
      officeEditorPath.value = path;
      officeEditorFileId.value = fileId ?? officeEditorFileId.value;
    }
    await dashboard.refreshDashboard();
  } catch {
    // Error is already tracked by useDashboard state.
  }
}

function onDocumentViewerOpened() {
  documentViewerRef.value?.refreshViewer?.();
}

async function onOfficeEditorClosed() {
  resetOfficeEditorState();
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

watch(isDarkMode, (value) => {
  if (typeof window !== "undefined") {
    window.localStorage.setItem(THEME_STORAGE_KEY, value ? "dark" : "light");
    document.body.classList.toggle("is-dark-mode", value);
  }
}, { immediate: true });

watch(
  () => isAuthenticated.value,
  (authenticated) => {
    if (authenticated) {
      setEntryMode("app");
    }
  },
);

onMounted(async () => {
  await syncCurrentUser();
  authBootstrapped.value = true;
  if (isAuthenticated.value || authEntryMode.value === "app") {
    setEntryMode("app");
    await chatWorkspace.initialize();
    try {
      await dashboard.refreshDashboard({ retries: 2 });
    } catch {
      // Error text is already captured in composable state.
    }
  }
});
</script>

<template>
  <AuthScreen
    v-if="showAuthScreen"
    :mode="authScreenMode"
    :loading="auth.loading.value"
    :error-message="auth.errorMessage.value"
    :guest-user-label="userMetaLabel || t('sidebar.guest_user')"
    @update:mode="authScreenMode = $event"
    @submit="submitAuthDialog"
    @continue-guest="continueAsGuest"
  />

  <section v-else-if="!authBootstrapped" class="app-boot-screen">
    <div class="app-boot-card">
      <span class="app-boot-mark">K</span>
      <strong>知识编排平台</strong>
      <small>正在确认登录状态...</small>
    </div>
  </section>

  <main v-else class="app-shell" :class="{ 'is-sidebar-collapsed': sidebarCollapsed, 'is-dark-mode': isDarkMode }">
    <LeftSidebar
      :nav-tabs="navTabs"
      :active-tab="activeTab"
      :recent-sessions="chatWorkspace.recentSessions.value"
      :active-session-id="chatWorkspace.activeSessionId.value"
      :status-text="dashboard.statusText.value"
      :document-count="dashboard.documentCount.value"
      :indexed-chunks="dashboard.indexedChunks.value"
      :collapsed="sidebarCollapsed"
      @new-chat="createNewChat"
      @select-tab="switchTab"
      @select-session="openSession"
      @load-more-sessions="chatWorkspace.loadMoreConversations"
      @toggle-sidebar="toggleSidebar"
    />

    <section class="main-workspace">
      <header class="workspace-topbar">
        <div class="workspace-heading">
          <strong>{{ activeTabTitle }}</strong>
          <span v-if="activeTabSubtitle">{{ activeTabSubtitle }}</span>
        </div>

        <div class="topbar-actions">
          <el-tooltip :content="isDarkMode ? '切换浅色模式' : '切换深色模式'" placement="bottom">
            <button class="topbar-icon-btn topbar-icon-btn--theme" type="button" @click="toggleDarkMode">
              <el-icon>
                <Sunny v-if="isDarkMode" />
                <Moon v-else />
              </el-icon>
            </button>
          </el-tooltip>

          <el-dropdown trigger="click" @command="handleLocaleCommand">
            <button class="topbar-chip-btn topbar-chip-btn--locale" type="button">
              <el-icon><Operation /></el-icon>
              <span>{{ currentLocaleName }}</span>
              <el-icon class="chip-caret"><ArrowDown /></el-icon>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item
                  v-for="option in localeOptions"
                  :key="option.code"
                  :command="option.code"
                  :class="{ 'is-current-locale': locale === option.code }"
                >
                  {{ localeDisplayName(option.code) }}
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>

          <el-dropdown trigger="click" :popper-class="userMenuPopperClass" @command="handleUserMenuCommand">
            <button class="user-menu-trigger" type="button">
              <span class="user-avatar-mini" :class="{ 'is-authenticated': isAuthenticated }">
                {{ userInitial }}
              </span>
              <span class="user-trigger-text">
                <strong>{{ userDisplayName }}</strong>
                <small>{{ userStatusLabel }}</small>
              </span>
              <el-icon class="chip-caret"><ArrowDown /></el-icon>
            </button>
            <template #dropdown>
              <el-dropdown-menu class="user-dropdown-menu">
                <div class="user-dropdown-head">
                  <span class="user-avatar-large" :class="{ 'is-authenticated': isAuthenticated }">{{ userInitial }}</span>
                  <div>
                    <strong>{{ userDisplayName }}</strong>
                    <small>{{ userStatusLabel }}</small>
                    <small v-if="userMetaLabel">{{ userMetaLabel }}</small>
                  </div>
                </div>
                <el-dropdown-item v-if="!isAuthenticated" command="login">
                  {{ t("sidebar.login") }}
                </el-dropdown-item>
                <el-dropdown-item v-if="!isAuthenticated" command="register">
                  {{ t("sidebar.register") }}
                </el-dropdown-item>
                <template v-else>
                  <el-dropdown-item command="profile">
                    <el-icon><User /></el-icon>
                    个人资料
                  </el-dropdown-item>
                  <el-dropdown-item command="api-key">
                    <el-icon><Key /></el-icon>
                    API 密钥
                  </el-dropdown-item>
                  <el-dropdown-item command="contact" disabled>
                    <el-icon><Service /></el-icon>
                    联系客服：微信 Starry-Stream
                  </el-dropdown-item>
                  <el-dropdown-item command="logout" :disabled="auth.loading.value" divided class="is-logout">
                    <el-icon><Switch /></el-icon>
                    {{ t("sidebar.logout") }}
                  </el-dropdown-item>
                </template>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>

      <section v-if="activeErrorMessage" class="notice-row">
        <el-alert :title="activeErrorMessage" type="error" show-icon :closable="false" />
      </section>

      <ChatWorkspace
        v-if="activeTab === 'chat'"
        :title="chatWorkspace.activeSession.value?.title ?? t('app.chat_default_title')"
        :messages="chatWorkspace.messages.value"
        :loading="chatWorkspace.loading.value"
        :composer="chatWorkspace.composer.value"
        :message-parts="chatWorkspace.messageParts.value"
        :top-k="topK"
        :starter-prompts="chatWorkspace.starterPrompts.value"
        :available-models="chatWorkspace.availableModels.value"
        :model-options="chatWorkspace.modelOptions.value"
        :selected-model="chatWorkspace.selectedModel.value"
        :thinking-mode="chatWorkspace.thinkingMode.value"
        :run-mode="chatWorkspace.runMode.value"
        :scope-type="chatWorkspace.activeSession.value?.scopeType ?? chatWorkspace.scopeType.value"
        :scope-id="chatWorkspace.activeSession.value?.scopeId ?? chatWorkspace.scopeId.value"
        :scope-name="chatWorkspace.activeSession.value?.scopeName ?? chatWorkspace.scopeName.value"
        :workspace-key="chatWorkspace.activeSession.value?.workspaceKey ?? chatWorkspace.workspaceKey.value"
        :folder-scope-tree="dashboard.folderScopeTree.value"
        :knowledge-base-options="chatWorkspace.knowledgeBaseOptions.value"
        :workspace-options="chatWorkspace.workspaceOptions.value"
        :documents="dashboard.documents.value"
        :native-web-search-enabled="chatWorkspace.nativeWebSearchEnabled.value"
        :native-web-search-supported="chatWorkspace.selectedModelSupportsNativeSearch.value"
        :external-web-search-enabled="chatWorkspace.externalWebSearchEnabled.value"
        :external-web-search-available="chatWorkspace.externalWebSearchAvailable.value"
        :options-loading="chatWorkspace.optionsLoading.value"
        :options-last-checked-at="chatWorkspace.optionsLastCheckedAt.value"
        @update:composer="chatWorkspace.composer.value = $event"
        @update:message-parts="chatWorkspace.setMessageParts($event)"
        @update:top-k="setTopK"
        @update:selected-model="chatWorkspace.setSelectedModel($event)"
        @update:thinking-mode="chatWorkspace.thinkingMode.value = $event"
        @update:run-mode="chatWorkspace.runMode.value = $event"
        @update:scope-type="chatWorkspace.setScopeType($event)"
        @update:scope-id="chatWorkspace.setScopeId($event)"
        @update:scope-name="chatWorkspace.setScopeName($event)"
        @update:workspace-key="chatWorkspace.setWorkspaceKey($event)"
        @update:native-web-search-enabled="chatWorkspace.nativeWebSearchEnabled.value = $event"
        @update:external-web-search-enabled="chatWorkspace.externalWebSearchEnabled.value = $event"
        @refresh-model-options="chatWorkspace.loadChatOptions"
        @send="chatWorkspace.sendChat"
        @pick-starter="chatWorkspace.useStarterPrompt"
        @viewport-ready="chatWorkspace.setViewport"
        @load-older="chatWorkspace.loadOlderMessages"
        @confirm-tool="chatWorkspace.confirmToolCall"
        @cancel-tool="chatWorkspace.cancelToolCall"
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
        :mutating-path="dashboard.mutatingPath.value"
        @files-change="dashboard.setSelectedFiles"
        @upload="dashboard.uploadAndBuild"
        @create-folder="dashboard.createDocumentFolder"
        @refresh-office-health="dashboard.refreshOfficeHealth"
        @open-document="openDocumentFromWorkspace"
        @open-office-editor="openOfficeEditorFromWorkspace"
        @delete-document="deleteDocumentFromWorkspace"
        @delete-folder="deleteFolderFromWorkspace"
        @rename-document="renameDocumentFromWorkspace"
        @move-document="moveDocumentFromWorkspace"
        @rename-folder="renameFolderFromWorkspace"
        @move-folder="moveFolderFromWorkspace"
        @document-saved="onDocumentSaved"
        @use-current-folder-in-chat="useCurrentFolderInChat"
      />

      <IndexWorkspace
        v-else-if="activeTab === 'index'"
        :health="dashboard.health.value"
        :documents="dashboard.documents.value"
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
            :source-file-id="documentViewerFileId"
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
            <span class="dialog-title">{{ officeDialogTitle }}</span>
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
            :source-file-id="officeEditorFileId"
            :mode="officeEditorMode"
            @error="officeEditorError = $event"
          />
        </section>
      </el-dialog>

    </section>
  </main>
</template>

<style scoped>
.app-boot-screen {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 24px;
  background:
    radial-gradient(at 40% 20%, rgba(20, 184, 166, 0.12) 0px, transparent 50%),
    radial-gradient(at 80% 0%, rgba(6, 182, 212, 0.08) 0px, transparent 50%),
    radial-gradient(at 0% 50%, rgba(20, 184, 166, 0.08) 0px, transparent 50%),
    var(--bg);
}

.app-boot-card {
  min-width: 220px;
  padding: 22px 24px;
  border: 1px solid var(--border);
  border-radius: 18px;
  background: var(--surface);
  box-shadow: var(--shadow-soft);
  display: grid;
  justify-items: center;
  gap: 8px;
  color: var(--text);
}

.app-boot-mark {
  width: 44px;
  height: 44px;
  border-radius: 13px;
  background: #0f766e;
  color: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-weight: 800;
  font-size: 1.16rem;
  box-shadow: 0 12px 22px rgba(20, 184, 166, 0.18);
}

.app-boot-card strong {
  font-size: 1rem;
}

.app-boot-card small {
  color: var(--text-muted);
  font-size: 0.82rem;
}

.workspace-topbar {
  min-height: 72px;
  padding: 14px 28px;
  border-bottom: 0;
  background: #fffc;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex: 0 0 auto;
  box-shadow: none;
  backdrop-filter: none;
}

.workspace-heading {
  min-width: 0;
  display: grid;
  gap: 2px;
}

.workspace-heading strong {
  min-width: 0;
  color: var(--ink);
  font-size: 1.08rem;
  font-weight: 700;
  line-height: 1.25;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workspace-heading span {
  color: var(--ink-soft);
  font-size: 0.82rem;
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.topbar-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  flex: 0 0 auto;
}

.topbar-icon-btn,
.topbar-chip-btn,
.user-menu-trigger {
  height: 36px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--muted-icon);
  border-radius: 999px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: background 0.18s ease, border-color 0.18s ease, color 0.18s ease;
}

.topbar-icon-btn:hover,
.topbar-chip-btn:hover,
.user-menu-trigger:hover {
  border-color: var(--accent-border);
  background: var(--accent-soft);
  color: var(--accent-strong);
}

.topbar-icon-btn {
  width: 36px;
  padding: 0;
  font-size: 16px;
}

.topbar-icon-btn--menu {
  color: var(--muted-icon);
  background: transparent;
  border-color: transparent;
}

.topbar-icon-btn--menu:hover {
  color: var(--accent-strong);
  background: var(--accent-soft);
  border-color: var(--accent-border);
}

.topbar-icon-btn--theme {
  color: var(--muted-icon);
  background: transparent;
  border-color: transparent;
}

.topbar-icon-btn--theme:hover {
  color: var(--accent-strong);
  background: var(--accent-soft);
  border-color: var(--accent-border);
}

.topbar-chip-btn {
  gap: 7px;
  padding: 0 11px;
  font-size: 0.84rem;
  font-weight: 600;
}

.topbar-chip-btn--locale {
  color: var(--ink);
  background: transparent;
  border-color: transparent;
}

.topbar-chip-btn--locale:hover {
  color: var(--accent-strong);
  background: var(--accent-soft);
  border-color: var(--accent-border);
}

.chip-caret {
  font-size: 12px;
  color: currentColor;
  opacity: 0.72;
}

.user-menu-trigger {
  gap: 6px;
  min-width: 112px;
  padding: 0 8px 0 5px;
  height: 34px;
  border-color: transparent;
  background: var(--surface-subtle);
  box-shadow: none;
}

.user-menu-trigger:hover {
  border-color: transparent;
  background: var(--surface);
  box-shadow: none;
}

.user-avatar-mini,
.user-avatar-large {
  background: linear-gradient(135deg, #0f766e 0%, #14b8a6 100%);
  color: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  flex: 0 0 auto;
}

.user-avatar-mini {
  width: 30px;
  height: 30px;
  border-radius: 999px;
  font-size: 0.8rem;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.45);
}

.user-avatar-large {
  width: 32px;
  height: 32px;
  border-radius: 10px;
  font-size: 0.78rem;
  box-shadow: 0 8px 14px rgba(20, 184, 166, 0.12);
}

.user-avatar-mini.is-authenticated,
.user-avatar-large.is-authenticated {
  background: var(--accent);
}

.user-trigger-text {
  min-width: 0;
  display: grid;
  text-align: left;
  line-height: 1.1;
}

.user-trigger-text strong,
.user-trigger-text small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.user-trigger-text strong {
  max-width: 76px;
  color: var(--ink);
  font-size: 0.84rem;
  font-weight: 650;
}

.user-trigger-text small {
  color: var(--ink-soft);
  font-size: 0.68rem;
}

.user-dropdown-head {
  min-width: 198px;
  padding: 9px 10px 8px;
  border-bottom: 1px solid var(--border);
  background: var(--surface-subtle);
  display: grid;
  grid-template-columns: 32px minmax(0, 1fr);
  align-items: center;
  gap: 8px;
}

.user-dropdown-head div {
  min-width: 0;
  display: grid;
  gap: 1px;
}

.user-dropdown-head strong,
.user-dropdown-head small {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.user-dropdown-head strong {
  color: var(--ink);
  font-size: 0.86rem;
  font-weight: 700;
}

.user-dropdown-head small {
  color: var(--ink-soft);
  font-size: 0.69rem;
  line-height: 1.2;
}

.user-dropdown-head small + small {
  opacity: 0.82;
}

:deep(.user-dropdown-menu) {
  min-width: 198px;
  padding: 0;
  border: 1px solid var(--border-strong);
  border-radius: 12px;
  background: var(--surface);
  backdrop-filter: blur(12px);
  box-shadow: 0 16px 32px rgba(15, 23, 42, 0.11);
  overflow: hidden;
}

:deep(.user-dropdown-menu .el-dropdown-menu__item) {
  padding: 8px 10px;
  gap: 7px;
  font-size: 0.84rem;
}

:deep(.user-dropdown-menu .el-dropdown-menu__item:hover) {
  background: rgba(20, 184, 166, 0.08);
  color: var(--accent-strong);
}

:deep(.user-dropdown-menu .el-dropdown-menu__item [class^="el-icon"]) {
  font-size: 14px;
}

:deep(.user-dropdown-menu .el-dropdown-menu__item.is-logout) {
  color: #ef4444;
}

.user-dropdown-note {
  color: var(--ink-soft);
}

.app-shell.is-dark-mode :deep(.user-dropdown-menu) {
  border-color: var(--border-strong);
  background: var(--surface);
  box-shadow: 0 20px 42px rgba(0, 0, 0, 0.42);
}

.app-shell.is-dark-mode .user-dropdown-head {
  background: var(--surface-subtle);
  border-bottom-color: var(--border);
}

.app-shell.is-dark-mode :deep(.user-dropdown-menu .el-dropdown-menu__item) {
  color: var(--text);
}

.app-shell.is-dark-mode :deep(.user-dropdown-menu .el-dropdown-menu__item:hover) {
  background: var(--accent-soft);
  color: var(--accent-strong);
}

.app-shell.is-dark-mode :deep(.user-dropdown-menu .el-dropdown-menu__item.is-logout) {
  color: #fb7185;
}

:deep(.is-current-locale) {
  color: var(--accent-strong);
  font-weight: 700;
}

.app-shell.is-dark-mode .workspace-topbar {
  background: rgba(16, 24, 33, 0.8);
}

.app-shell.is-dark-mode .topbar-icon-btn,
.app-shell.is-dark-mode .topbar-chip-btn,
.app-shell.is-dark-mode .user-menu-trigger {
  border-color: transparent;
  color: var(--ink);
}

.app-shell.is-dark-mode .topbar-icon-btn--menu {
  color: var(--ink-soft);
  background: rgba(255, 255, 255, 0.03);
  border-color: var(--line);
}

.app-shell.is-dark-mode .topbar-icon-btn--theme {
  color: var(--ink-soft);
  background: rgba(255, 255, 255, 0.03);
  border-color: var(--line);
}

.app-shell.is-dark-mode .topbar-chip-btn--locale {
  color: var(--ink);
  background: rgba(255, 255, 255, 0.03);
  border-color: var(--line);
}

.app-shell.is-dark-mode .user-menu-trigger {
  background: rgba(255, 255, 255, 0.03);
  border-color: var(--line);
}

.app-shell.is-dark-mode .topbar-icon-btn:hover,
.app-shell.is-dark-mode .topbar-chip-btn:hover,
.app-shell.is-dark-mode .user-menu-trigger:hover {
  background: var(--accent-soft);
  border-color: var(--accent-border);
}

.app-shell.is-dark-mode .topbar-icon-btn--menu:hover {
  color: var(--accent-strong);
  background: var(--accent-soft);
  border-color: var(--accent-border);
}

.app-shell.is-dark-mode .topbar-icon-btn--theme:hover {
  color: var(--accent-strong);
  background: var(--accent-soft);
  border-color: var(--accent-border);
}

.app-shell.is-dark-mode .topbar-chip-btn--locale:hover {
  color: var(--accent-strong);
  background: var(--accent-soft);
  border-color: var(--accent-border);
}

.app-shell.is-dark-mode .user-menu-trigger:hover {
  background: var(--accent-soft);
  border-color: var(--accent-border);
}

.app-shell.is-dark-mode .user-trigger-text strong {
  color: var(--ink);
}

.app-shell.is-dark-mode .user-trigger-text small,
.app-shell.is-dark-mode .chip-caret {
  color: var(--ink-soft);
}

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
  color: var(--text);
}

.dialog-tool-btn {
  min-width: 32px;
  height: 28px;
  padding: 0 6px;
  border-radius: 7px;
  border: 1px solid var(--border);
  background: var(--surface-solid);
  color: var(--text);
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

:deep(.action-btn--confirm.el-button) {
  --el-button-bg-color: #0f766e;
  --el-button-border-color: #0f766e;
  --el-button-hover-bg-color: #0d9488;
  --el-button-hover-border-color: #0d9488;
  --el-button-active-bg-color: #0b6f68;
  --el-button-active-border-color: #0b6f68;
}

:deep(.action-btn--confirm.el-button.is-disabled) {
  --el-button-disabled-bg-color: #c5e7e2;
  --el-button-disabled-border-color: #c5e7e2;
  --el-button-disabled-text-color: #fff;
}

:deep(.el-dialog.office-editor-dialog.is-fullscreen) {
  height: 100vh;
  max-height: 100vh;
}

:deep(.office-editor-dialog .el-dialog__header) {
  margin-right: 0;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
  background: var(--surface-subtle);
}

:deep(.office-editor-dialog .el-dialog__body) {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 10px 12px 12px;
}

@media (max-width: 760px) {
  .workspace-topbar {
    align-items: flex-start;
    flex-direction: column;
    padding: 10px 12px;
  }

  .topbar-actions {
    width: 100%;
    justify-content: flex-start;
    overflow-x: auto;
    padding-bottom: 2px;
  }

  .user-menu-trigger {
    min-width: 118px;
  }
}
</style>
