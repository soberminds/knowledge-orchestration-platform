<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "../../composables/useI18n";
import type { LocaleCode } from "../../i18n/messages";
import type { NavTab, WorkspaceTab, ChatSession } from "../../types/chat";

const props = defineProps<{
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

const { locale, localeOptions, setLocale, t } = useI18n();
const localeValue = computed<LocaleCode>({
  get: () => locale.value,
  set: (value) => setLocale(value),
});
</script>

<template>
  <aside class="left-sidebar">
    <div class="sidebar-head">
      <div class="logo-mark">R</div>
      <div class="head-text">
        <strong>{{ t("sidebar.brand_name") }}</strong>
        <small>{{ t("sidebar.brand_subtitle") }}</small>
      </div>
    </div>

    <div class="sidebar-language">
      <span>{{ t("sidebar.language") }}</span>
      <el-select v-model="localeValue" size="small" class="language-select">
        <el-option
          v-for="option in localeOptions"
          :key="option.code"
          :label="t(option.nameKey)"
          :value="option.code"
        />
      </el-select>
    </div>

    <button class="new-chat-btn" @click="$emit('new-chat')">{{ t("sidebar.new_chat") }}</button>

    <section class="nav-section">
      <h3>{{ t("sidebar.workspaces") }}</h3>
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
      <div class="recent-head">
        <h3>{{ t("sidebar.recent") }}</h3>
        <span class="recent-count">{{ recentSessions.length }}</span>
      </div>

      <div class="recent-list">
        <button
          v-for="session in recentSessions"
          :key="session.id"
          :class="['recent-item', activeSessionId === session.id ? 'is-active' : '']"
          @click="$emit('select-session', session.id)"
        >
          <span class="recent-title">{{ session.title }}</span>
        </button>

        <p v-if="!recentSessions.length" class="recent-empty">
          {{ t("sidebar.recent_empty") }}
        </p>
      </div>
    </section>

    <section class="sidebar-foot">
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

.sidebar-language {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin: 0 2px 8px;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: #fff;
  color: var(--ink-soft);
  font-size: 0.8rem;
}

.language-select {
  width: 104px;
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
  border: 1px solid #d7deea;
  background: #fff;
  color: #64748b;
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
  border: 1px solid #e3e8f1;
  border-radius: 12px;
  background: linear-gradient(180deg, #f8fafd 0%, #f4f6f9 100%);
}

.recent-list::-webkit-scrollbar {
  width: 8px;
}

.recent-list::-webkit-scrollbar-thumb {
  background: #cfd6e2;
  border-radius: 999px;
}

.recent-item {
  border: 1px solid #dfe5ef;
  background: #fff;
  border-radius: 10px;
  text-align: left;
  padding: 10px 11px;
  cursor: pointer;
  transition: background 0.2s ease, border-color 0.2s ease, transform 0.12s ease;
}

.recent-item:hover {
  background: #f9fbff;
  border-color: #c8d4e5;
  transform: translateY(-1px);
}

.recent-item.is-active {
  background: linear-gradient(135deg, #e8f1ff 0%, #f0f6ff 100%);
  border-color: #b8c9e6;
}

.recent-title {
  display: block;
  font-size: 0.88rem;
  color: #1f2937;
  line-height: 1.4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.recent-empty {
  margin: 4px 0;
  padding: 10px;
  border: 1px dashed #d8dee8;
  border-radius: 10px;
  color: #7b8794;
  font-size: 0.82rem;
  text-align: center;
  background: #fff;
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
