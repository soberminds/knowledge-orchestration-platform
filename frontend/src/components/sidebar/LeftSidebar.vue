<script setup lang="ts">
import type { NavTab, WorkspaceTab, ChatSession } from "../../types/chat";

defineProps<{
  navTabs: NavTab[];
  activeTab: WorkspaceTab;
  recentSessions: ChatSession[];
  activeSessionId: string;
  statusText: string;
  documentCount: number;
  indexedChunks: number;
}>();

defineEmits<{
  (event: "new-chat"): void;
  (event: "select-tab", tab: WorkspaceTab): void;
  (event: "select-session", sessionId: string): void;
}>();
</script>

<template>
  <aside class="left-sidebar">
    <div class="sidebar-head">
      <div class="logo-mark">R</div>
      <div class="head-text">
        <strong>RAG Studio</strong>
        <small>Knowledge Copilot</small>
      </div>
    </div>

    <button class="new-chat-btn" @click="$emit('new-chat')">+ New Chat</button>

    <section class="nav-section">
      <h3>Workspaces</h3>
      <button
        v-for="tab in navTabs"
        :key="tab.id"
        :class="['nav-item', activeTab === tab.id ? 'is-active' : '']"
        @click="$emit('select-tab', tab.id)"
      >
        <div class="nav-item-main">{{ tab.label }}</div>
        <small>{{ tab.subtitle }}</small>
      </button>
    </section>

    <section class="nav-section recent-section">
      <h3>Recent</h3>
      <button
        v-for="session in recentSessions"
        :key="session.id"
        :class="['recent-item', activeSessionId === session.id ? 'is-active' : '']"
        @click="$emit('select-session', session.id)"
      >
        {{ session.title }}
      </button>
    </section>

    <section class="sidebar-foot">
      <article>
        <span>Index</span>
        <strong>{{ statusText }}</strong>
      </article>
      <article>
        <span>Documents</span>
        <strong>{{ documentCount }}</strong>
      </article>
      <article>
        <span>Chunks</span>
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
  padding: 14px 12px 10px;
  overflow: hidden;
}

.sidebar-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 6px 12px;
}

.logo-mark {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  background: #111827;
  color: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
}

.head-text {
  display: grid;
}

.head-text strong {
  font-size: 0.96rem;
}

.head-text small {
  font-size: 0.8rem;
  color: var(--ink-soft);
}

.new-chat-btn {
  border: 1px solid var(--line);
  background: #fff;
  border-radius: 12px;
  min-height: 40px;
  text-align: left;
  padding: 0 12px;
  cursor: pointer;
  transition: background 0.2s ease;
}

.new-chat-btn:hover {
  background: #f9fafb;
}

.nav-section {
  margin-top: 14px;
  display: grid;
  gap: 8px;
}

.nav-section h3 {
  margin: 0;
  font-size: 0.82rem;
  color: var(--ink-soft);
  font-weight: 600;
  padding: 0 4px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.nav-item {
  border: 1px solid transparent;
  background: transparent;
  border-radius: 10px;
  text-align: left;
  padding: 9px 10px;
  cursor: pointer;
  display: grid;
  gap: 3px;
  transition: background 0.2s ease, border-color 0.2s ease;
}

.nav-item .nav-item-main {
  font-weight: 600;
  font-size: 0.93rem;
}

.nav-item small {
  color: var(--ink-soft);
  font-size: 0.8rem;
}

.nav-item:hover {
  background: #fff;
  border-color: var(--line);
}

.nav-item.is-active {
  background: #fff;
  border-color: #d1d5db;
}

.recent-section {
  min-height: 0;
  flex: 1;
}

.recent-item {
  border: 1px solid transparent;
  background: transparent;
  border-radius: 10px;
  text-align: left;
  padding: 8px 10px;
  cursor: pointer;
  font-size: 0.9rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  transition: background 0.2s ease;
}

.recent-item:hover {
  background: #fff;
}

.recent-item.is-active {
  background: #e5e7eb;
}

.sidebar-foot {
  border-top: 1px solid var(--line);
  padding-top: 10px;
  margin-top: 10px;
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
  color: var(--ink);
  font-weight: 600;
}
</style>
