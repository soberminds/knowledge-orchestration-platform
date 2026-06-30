<script setup lang="ts">
import {
  ChatDotRound,
  Connection,
  DataAnalysis,
  FolderOpened,
  Fold,
  Plus,
  Search,
} from "@element-plus/icons-vue";
import { useI18n } from "../../composables/useI18n";
import type { ChatSession, NavTab, WorkspaceTab } from "../../types/chat";

const props = defineProps<{
  navTabs: NavTab[];
  activeTab: WorkspaceTab;
  recentSessions: ChatSession[];
  activeSessionId: string;
  statusText: string;
  documentCount: number;
  indexedChunks: number;
  collapsed: boolean;
}>();

const emit = defineEmits<{
  (event: "new-chat"): void;
  (event: "select-tab", tab: WorkspaceTab): void;
  (event: "select-session", sessionId: string): void;
  (event: "load-more-sessions"): void;
  (event: "toggle-sidebar"): void;
}>();

const { t } = useI18n();

const navIcons = {
  chat: ChatDotRound,
  documents: FolderOpened,
  index: DataAnalysis,
  search: Search,
} as const;

function navIcon(tab: WorkspaceTab) {
  return navIcons[tab] ?? Connection;
}

function scopeLabel(session: ChatSession) {
  const folderLabel = t("chat.scope_folder");
  const kbLabel = t("chat.scope_kb");
  const workspaceLabel = t("chat.scope_workspace");
  const allLabel = t("chat.scope_all");
  const unsetLabel = t("chat.scope_unset");

  if (session.scopeType === "folder") {
    const name = session.scopeName?.trim();
    if (name) {
      return `${folderLabel} / ${name}`;
    }
    if (session.scopeId == null) {
      return `${folderLabel} / ${unsetLabel}`;
    }
    return `${folderLabel} #${session.scopeId}`;
  }

  if (session.scopeType === "kb") {
    const name = session.scopeName?.trim();
    if (name) {
      return `${kbLabel} / ${name}`;
    }
    if (session.scopeId == null) {
      return `${kbLabel} / ${unsetLabel}`;
    }
    return `${kbLabel} #${session.scopeId}`;
  }

  if (session.scopeType === "workspace") {
    const name = session.scopeName?.trim();
    if (name) {
      return `${workspaceLabel} / ${name}`;
    }
    if (!session.workspaceKey) {
      return `${workspaceLabel} / ${unsetLabel}`;
    }
    const key = session.workspaceKey.length > 18 ? `${session.workspaceKey.slice(0, 18)}...` : session.workspaceKey;
    return `${workspaceLabel} / ${key}`;
  }

  return allLabel;
}

function scopeBadgeClass(session: ChatSession) {
  return `scope-badge scope-badge--${session.scopeType}`;
}

function onRecentScroll(event: Event) {
  const target = event.currentTarget as HTMLElement | null;
  if (!target) {
    return;
  }
  const distanceToBottom = target.scrollHeight - target.scrollTop - target.clientHeight;
  if (distanceToBottom <= 24) {
    emit("load-more-sessions");
  }
}
</script>

<template>
  <aside class="left-sidebar" :class="{ 'is-collapsed': collapsed }">
    <div class="sidebar-head">
      <template v-if="collapsed">
        <el-tooltip :content="t('sidebar.expand_sidebar')" placement="right">
          <button class="logo-mark logo-mark-button" type="button" @click="$emit('toggle-sidebar')">
            R
          </button>
        </el-tooltip>
      </template>
      <template v-else>
        <div class="sidebar-head-main">
          <div class="logo-mark">K</div>
          <div class="head-text">
            <strong>{{ t("sidebar.brand_name") }}</strong>
            <small>{{ t("sidebar.brand_subtitle") }}</small>
          </div>
        </div>
        <el-tooltip :content="t('sidebar.collapse_sidebar')" placement="right">
          <button class="sidebar-toggle-btn" type="button" @click="$emit('toggle-sidebar')">
            <el-icon><Fold /></el-icon>
          </button>
        </el-tooltip>
      </template>
    </div>

    <el-tooltip :content="t('sidebar.new_chat')" placement="right" :disabled="!collapsed">
      <button class="new-chat-btn" @click="$emit('new-chat')">
        <el-icon><Plus /></el-icon>
        <span v-if="!collapsed">{{ t("sidebar.new_chat") }}</span>
      </button>
    </el-tooltip>

    <section class="nav-section">
      <h3 v-if="!collapsed">{{ t("sidebar.workspaces") }}</h3>
      <el-tooltip
        v-for="tab in navTabs"
        :key="tab.id"
        :content="tab.label"
        placement="right"
        :disabled="!collapsed"
      >
        <button
          :class="['nav-item', activeTab === tab.id ? 'is-active' : '']"
          @click="$emit('select-tab', tab.id)"
        >
          <el-icon class="nav-icon">
            <component :is="navIcon(tab.id)" />
          </el-icon>
          <div v-if="!collapsed" class="nav-copy">
            <div class="nav-item-main">{{ tab.label }}</div>
            <small>{{ tab.subtitle }}</small>
          </div>
        </button>
      </el-tooltip>
    </section>

    <section v-if="!collapsed" class="nav-section recent-section">
      <div class="recent-head">
        <h3>{{ t("sidebar.recent") }}</h3>
        <span class="recent-count">{{ recentSessions.length }}</span>
      </div>

      <div class="recent-list" @scroll="onRecentScroll">
        <button
          v-for="session in recentSessions"
          :key="session.id"
          :class="['recent-item', activeSessionId === session.id ? 'is-active' : '']"
          @click="$emit('select-session', session.id)"
        >
          <span class="recent-title">{{ session.title }}</span>
          <span class="scope-badge-row">
            <span :class="scopeBadgeClass(session)">{{ scopeLabel(session) }}</span>
          </span>
        </button>

        <p v-if="!recentSessions.length" class="recent-empty">
          {{ t("sidebar.recent_empty") }}
        </p>
      </div>
    </section>

    <section v-if="!collapsed" class="sidebar-foot">
      <article>
        <span>{{ t("sidebar.index") }}</span>
        <strong>{{ statusText }}</strong>
      </article>
      <article>
        <span>{{ t("sidebar.documents") }}</span>
        <strong>{{ documentCount }}</strong>
      </article>
      <article>
        <span>{{ t("sidebar.chunks") }}</span>
        <strong>{{ indexedChunks }}</strong>
      </article>
    </section>
  </aside>
</template>

<style scoped>
.left-sidebar {
  background: var(--sidebar-bg);
  border-right: 1px solid var(--line);
  display: flex;
  flex-direction: column;
  padding: 16px 14px 12px;
  overflow: hidden;
}

.left-sidebar.is-collapsed {
  align-items: center;
  padding: 14px 8px 10px;
}

.sidebar-head {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 4px 6px 14px;
}

.left-sidebar.is-collapsed .sidebar-head {
  justify-content: center;
  padding-inline: 0;
}

.sidebar-head-main {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 10px;
}

.logo-mark {
  width: 34px;
  height: 34px;
  border-radius: 11px;
  background: linear-gradient(135deg, #0f766e 0%, #14b8a6 100%);
  color: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  flex: 0 0 auto;
  box-shadow: 0 8px 16px rgba(15, 118, 110, 0.18);
}

.logo-mark-button {
  border: 0;
  cursor: pointer;
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}

.left-sidebar.is-collapsed .logo-mark-button {
  width: 40px;
  min-width: 40px;
  position: relative;
}

.logo-mark-button:hover {
  transform: translateY(-1px);
  box-shadow: 0 10px 20px rgba(15, 118, 110, 0.22);
}

.sidebar-toggle-btn {
  width: 34px;
  height: 34px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface-solid);
  color: var(--ink-soft);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background 0.16s ease, border-color 0.16s ease, color 0.16s ease;
}

.sidebar-toggle-btn:hover {
  background: var(--accent-soft);
  border-color: var(--accent-border);
  color: var(--accent-strong);
}

.left-sidebar.is-collapsed .sidebar-toggle-btn {
  display: none;
}

.head-text {
  display: grid;
  min-width: 0;
}

.head-text strong {
  font-size: 0.96rem;
  color: var(--ink);
  white-space: nowrap;
}

.head-text small {
  font-size: 0.8rem;
  color: var(--ink-soft);
  white-space: nowrap;
}

.new-chat-btn {
  width: 100%;
  border: 1px solid var(--line);
  background: var(--surface-solid);
  color: var(--ink);
  border-radius: 12px;
  min-height: 42px;
  text-align: left;
  padding: 0 14px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 10px;
  font-weight: 650;
  transition: background 0.18s ease, border-color 0.18s ease, color 0.18s ease;
}

.left-sidebar.is-collapsed .new-chat-btn {
  width: 40px;
  justify-content: center;
  padding: 0;
}

.new-chat-btn:hover {
  background: var(--accent-soft);
  border-color: var(--accent-border);
  color: var(--accent-strong);
}

.nav-section {
  width: 100%;
  margin-top: 16px;
  display: grid;
  gap: 6px;
}

.left-sidebar.is-collapsed .nav-section {
  justify-items: center;
}

.nav-section h3 {
  margin: 0;
  font-size: 0.82rem;
  color: var(--ink-soft);
  font-weight: 600;
  padding: 0 6px 4px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.nav-item {
  width: 100%;
  border: 1px solid transparent;
  background: transparent;
  color: var(--ink);
  border-radius: 12px;
  text-align: left;
  padding: 10px 12px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 52px;
  transition: background 0.16s ease, border-color 0.16s ease, color 0.16s ease;
}

.left-sidebar.is-collapsed .nav-item {
  width: 40px;
  height: 40px;
  min-height: 40px;
  justify-content: center;
  padding: 0;
}

.nav-icon {
  width: 26px;
  height: 26px;
  border-radius: 9px;
  color: var(--ink-soft);
  font-size: 17px;
  flex: 0 0 auto;
}

.nav-copy {
  min-width: 0;
  display: grid;
  gap: 3px;
}

.nav-item-main {
  font-weight: 600;
  font-size: 0.93rem;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.nav-item small {
  color: var(--ink-soft);
  font-size: 0.8rem;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.nav-item:hover {
  background: var(--accent-softer);
  border-color: var(--accent-border);
  color: var(--accent-strong);
}

.nav-item.is-active {
  background: var(--surface-active);
  border-color: var(--accent-border);
  color: var(--accent-strong);
}

.nav-item.is-active .nav-icon {
  color: var(--accent-strong);
}

.recent-section {
  min-height: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.recent-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 4px;
}

.recent-head h3 {
  margin: 0;
}

.recent-count {
  min-width: 22px;
  height: 22px;
  padding: 0 6px;
  border-radius: 999px;
  border: 1px solid var(--accent-border);
  background: var(--accent-soft);
  color: var(--accent-strong);
  font-size: 0.75rem;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.recent-list {
  min-height: 0;
  flex: 1;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 8px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--surface-subtle);
}

.recent-item {
  border: 1px solid var(--border);
  background: var(--surface-solid);
  border-radius: 12px;
  text-align: left;
  padding: 10px 11px;
  cursor: pointer;
}

.recent-item:hover {
  background: var(--accent-softer);
  border-color: var(--accent-border);
}

.recent-item.is-active {
  background: var(--surface-active);
  border-color: var(--accent-border);
}

.recent-title {
  display: block;
  font-size: 0.88rem;
  color: var(--text);
  line-height: 1.4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.scope-badge-row {
  display: flex;
  margin-top: 6px;
}

.scope-badge {
  display: inline-flex;
  align-items: center;
  max-width: 100%;
  min-height: 20px;
  padding: 0 8px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: var(--surface-muted);
  color: var(--text-muted);
  font-size: 0.72rem;
  line-height: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.scope-badge--folder {
  border-color: color-mix(in srgb, #818cf8 48%, transparent);
  background: color-mix(in srgb, #6366f1 13%, var(--surface-solid));
  color: color-mix(in srgb, #818cf8 82%, var(--text));
}

.scope-badge--kb {
  border-color: color-mix(in srgb, #fbbf24 44%, transparent);
  background: color-mix(in srgb, #f59e0b 14%, var(--surface-solid));
  color: color-mix(in srgb, #f59e0b 84%, var(--text));
}

.scope-badge--workspace {
  border-color: color-mix(in srgb, #22c55e 40%, transparent);
  background: color-mix(in srgb, #22c55e 12%, var(--surface-solid));
  color: color-mix(in srgb, #22c55e 76%, var(--text));
}

.scope-badge--all {
  border-color: var(--accent-border);
  background: var(--accent-soft);
  color: var(--accent-strong);
}

.recent-empty {
  margin: 4px 0;
  padding: 10px;
  border: 1px dashed var(--border-strong);
  border-radius: 10px;
  color: var(--text-muted);
  font-size: 0.82rem;
  text-align: center;
  background: var(--surface-solid);
}

.sidebar-foot {
  border-top: 1px solid var(--line);
  padding-top: 12px;
  margin-top: 12px;
  display: grid;
  gap: 8px;
}

.sidebar-foot article {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 0.84rem;
  color: var(--ink-soft);
}

.sidebar-foot strong {
  color: var(--accent-strong);
  font-weight: 600;
}

.left-sidebar.is-collapsed .logo-mark-button {
  box-shadow: 0 8px 16px rgba(15, 118, 110, 0.18);
}

.left-sidebar.is-collapsed .logo-mark-button:hover {
  box-shadow: 0 10px 20px rgba(15, 118, 110, 0.22);
}
</style>
