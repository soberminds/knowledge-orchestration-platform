<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { ArrowRight, CircleCheck, Key, Lock, MagicStick, User, UserFilled } from "@element-plus/icons-vue";

type AuthMode = "login" | "register";

const props = defineProps<{
  mode: AuthMode;
  loading: boolean;
  errorMessage: string;
  guestUserLabel: string;
}>();

const emit = defineEmits<{
  (event: "update:mode", value: AuthMode): void;
  (event: "submit", payload: { username: string; password: string; nickname: string | null }): void;
  (event: "continue-guest"): void;
}>();

const username = ref("");
const password = ref("");
const nickname = ref("");

const modeOptions: Array<{ label: string; value: AuthMode }> = [
  { label: "登录", value: "login" },
  { label: "注册", value: "register" },
];

const capabilityCards = [
  {
    title: "可控知识范围",
    text: "会话可绑定工作区、知识库或文件夹，回答更聚焦。",
  },
  {
    title: "可确认 Agent",
    text: "发送邮件、重建索引等动作先确认，执行更安心。",
  },
  {
    title: "文档工作闭环",
    text: "上传、预览、在线编辑到后台索引一气贯通，解析、切片、向量写入和失败原因逐文件可见。",
  },
  {
    title: "多模型编排",
    text: "provider、流式事件和工具调用已经拆开，接新模型更顺。",
  },
  {
    title: "多模态输入",
    text: "文本、图片和文件引用可以统一进入一次对话。",
  },
  {
    title: "用户隔离",
    text: "文档、会话和工具记录都按用户隔离保存。",
  },
];

const metrics = [
  { value: "Scoped RAG", label: "范围可控" },
  { value: "Traceable Index", label: "索引可追踪" },
  { value: "Multi Model", label: "模型编排" },
];

const title = computed(() => (props.mode === "login" ? "欢迎回来" : "创建账号"));
const subtitle = computed(() =>
  props.mode === "login"
    ? "登录后继续使用你的会话、文档范围和个人知识库。"
    : "创建本地账号，隔离保存你的文档和会话。",
);
const submitLabel = computed(() => (props.mode === "login" ? "登录进入工作台" : "创建账号并进入"));
const switchLabel = computed(() => (props.mode === "login" ? "没有账号？立即注册" : "已有账号？返回登录"));
const submitIcon = computed(() => (props.mode === "login" ? Key : ArrowRight));

watch(
  () => props.mode,
  () => {
    password.value = "";
  },
);

function submit() {
  emit("submit", {
    username: username.value.trim(),
    password: password.value.trim(),
    nickname: props.mode === "register" ? nickname.value.trim() : null,
  });
}

function switchMode(nextMode: AuthMode) {
  emit("update:mode", nextMode);
}
</script>

<template>
  <section class="auth-screen">
    <div class="auth-shell">
      <section class="auth-hero">
        <div class="brand-row">
          <div class="brand-mark">K</div>
          <div class="brand-copy">
            <strong>知识编排平台</strong>
            <small>Knowledge Orchestration Platform</small>
          </div>
        </div>

        <div class="hero-main">
          <p class="hero-kicker">
            <MagicStick />
            Knowledge + Agent Workspace
          </p>
          <h1>从检索到执行，一次完成。</h1>
          <p class="hero-copy">
            把文档、范围、模型和工具放进同一个工作台，上传后后台建索引，回答时保留引用和可追踪状态。
          </p>
        </div>

        <div class="metric-row">
          <div v-for="item in metrics" :key="item.label" class="metric-card">
            <strong>{{ item.value }}</strong>
            <span>{{ item.label }}</span>
          </div>
        </div>

        <div class="capability-grid">
          <article v-for="item in capabilityCards" :key="item.title" class="capability-card">
            <CircleCheck />
            <div>
              <strong>{{ item.title }}</strong>
              <p>{{ item.text }}</p>
            </div>
          </article>
        </div>
      </section>

      <aside class="auth-card">
        <div class="auth-card-head">
          <div class="auth-head-topline">
            <p class="card-kicker">Account Access</p>
            <button class="guest-mini-button" type="button" :title="guestUserLabel" @click="$emit('continue-guest')">
              <Lock />
              <span>游客体验</span>
            </button>
          </div>
          <div>
            <h2>{{ title }}</h2>
            <p>{{ subtitle }}</p>
          </div>
        </div>

        <div class="mode-switch" role="tablist" aria-label="认证模式切换">
          <button
            v-for="option in modeOptions"
            :key="option.value"
            type="button"
            class="mode-switch-item"
            :class="{ active: mode === option.value }"
            :aria-pressed="mode === option.value"
            @click="switchMode(option.value)"
          >
            {{ option.label }}
          </button>
        </div>

        <div class="form-grid">
          <label class="field-row">
            <span>用户名</span>
            <el-input
              v-model="username"
              :prefix-icon="User"
              placeholder="请输入用户名"
              autocomplete="username"
              @keyup.enter.exact="submit"
            />
          </label>

          <label class="field-row">
            <span>密码</span>
            <el-input
              v-model="password"
              :prefix-icon="Lock"
              type="password"
              show-password
              placeholder="请输入密码"
              autocomplete="current-password"
              @keyup.enter.exact="submit"
            />
          </label>

          <div class="form-extra-slot">
            <label v-if="mode === 'register'" class="field-row">
              <span>昵称</span>
              <el-input
                v-model="nickname"
                placeholder="选填，作为界面显示名称"
                autocomplete="nickname"
                @keyup.enter.exact="submit"
              />
            </label>
            <div v-else class="login-note">
              <el-icon><UserFilled /></el-icon>
              <div>
                <strong>个人工作区</strong>
                <span>登录后自动恢复你的会话、文档范围和工具记录。</span>
              </div>
            </div>
          </div>
        </div>

        <el-alert v-if="errorMessage" class="auth-error" :title="errorMessage" type="error" show-icon :closable="false" />

        <div class="card-actions">
          <el-button class="submit-button" :loading="loading" @click="submit">
            <component :is="submitIcon" :size="17" />
            <span>{{ submitLabel }}</span>
          </el-button>

          <button class="switch-link" type="button" @click="switchMode(mode === 'login' ? 'register' : 'login')">
            {{ switchLabel }}
          </button>
        </div>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.auth-screen {
  min-height: 100vh;
  padding: clamp(72px, 14vh, 121px) 32px 32px;
  display: grid;
  place-items: start center;
  background:
    radial-gradient(at 40% 20%, rgba(20, 184, 166, 0.12) 0px, transparent 50%),
    radial-gradient(at 80% 0%, rgba(6, 182, 212, 0.08) 0px, transparent 50%),
    radial-gradient(at 0% 50%, rgba(20, 184, 166, 0.08) 0px, transparent 50%),
    var(--bg);
  position: relative;
  overflow: auto;
}

.auth-screen::before {
  content: "";
  position: fixed;
  inset: 0;
  background-image:
    linear-gradient(rgba(20, 184, 166, 0.08) 1px, transparent 1px),
    linear-gradient(90deg, rgba(20, 184, 166, 0.08) 1px, transparent 1px);
  background-size: 40px 40px;
  mask-image: linear-gradient(180deg, rgba(0, 0, 0, 0.42), transparent 82%);
  pointer-events: none;
}

.auth-shell {
  position: relative;
  z-index: 1;
  width: min(1080px, 100%);
  display: grid;
  grid-template-columns: minmax(0, 1fr) 420px;
  gap: clamp(28px, 5vw, 72px);
  align-items: end;
}

.auth-card {
  border: 1px solid var(--border);
  border-radius: 24px;
  background: rgba(255, 255, 255, 0.86);
  box-shadow: 0 24px 60px rgba(15, 23, 42, 0.1);
  backdrop-filter: blur(20px);
}

.auth-hero {
  min-width: 0;
  max-width: 620px;
  display: grid;
  gap: 24px;
}

.brand-row {
  display: inline-flex;
  align-items: center;
  gap: 12px;
}

.brand-mark {
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
  box-shadow: 0 14px 28px rgba(20, 184, 166, 0.2);
}

.brand-copy {
  display: grid;
}

.brand-copy strong {
  color: var(--text);
  font-size: 1.3rem;
  font-weight: 800;
  line-height: 1.18;
}

.brand-copy small {
  color: var(--text-muted);
  font-size: 0.82rem;
}

.hero-main {
  display: grid;
  gap: 16px;
}

.hero-kicker {
  width: fit-content;
  margin: 0;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: #0f766e;
  background: rgba(236, 253, 249, 0.9);
  border: 1px solid rgba(20, 184, 166, 0.18);
  border-radius: 999px;
  padding: 8px 12px;
  font-size: 0.82rem;
  font-weight: 700;
}

.hero-kicker svg {
  width: 16px;
  height: 16px;
}

.auth-hero h1 {
  margin: 0;
  max-width: 520px;
  color: var(--text);
  font-size: 2.16rem;
  line-height: 1.08;
  letter-spacing: 0;
  white-space: nowrap;
}

.hero-copy {
  margin: 0;
  max-width: 500px;
  color: var(--text-muted);
  line-height: 1.72;
  font-size: 0.96rem;
}

.metric-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.metric-card {
  min-height: 0;
  padding: 9px 12px;
  border: 1px solid rgba(20, 184, 166, 0.14);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.62);
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.metric-card strong {
  color: #0f766e;
  font-size: 0.85rem;
  font-weight: 800;
}

.metric-card span {
  color: var(--text-muted);
  font-size: 0.76rem;
}

.capability-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px 16px;
  max-width: 620px;
}

.capability-card {
  min-width: 0;
  min-height: 66px;
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr);
  gap: 10px;
  padding: 12px 14px;
  border: 1px solid rgba(20, 184, 166, 0.12);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.56);
  align-content: start;
}

body.is-dark-mode .capability-card {
  background: rgba(20, 32, 42, 0.7);
}

.capability-card svg {
  width: 18px;
  height: 18px;
  margin-top: 2px;
  color: #0f766e;
}

.capability-card strong {
  display: block;
  color: var(--text);
  font-size: 0.9rem;
  line-height: 1.25;
}

.capability-card p {
  margin: 5px 0 0;
  color: var(--text-muted);
  line-height: 1.5;
  font-size: 0.8rem;
}

.auth-card {
  width: 100%;
  max-width: 420px;
  justify-self: center;
  padding: 28px;
  display: grid;
  gap: 18px;
  align-content: start;
}

.auth-card-head {
  display: grid;
  gap: 0px;
}

.auth-card-head > div {
  min-width: 0;
}

.auth-head-topline {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.card-kicker {
  margin: 0;
  color: #0f766e;
  font-size: 0.72rem;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.auth-card h2 {
  margin: 0;
  color: var(--text);
  font-size: 1.55rem;
  line-height: 1.2;
}

.auth-card-head p:last-child {
  margin: 2px 0 0;
  color: var(--text-muted);
  line-height: 1.5;
  font-size: 0.9rem;
  min-height: 1.5em;
}

.guest-mini-button {
  min-height: 30px;
  padding: 0 9px;
  border: 1px solid rgba(20, 184, 166, 0.16);
  border-radius: 999px;
  background: rgba(236, 253, 249, 0.72);
  color: #0f766e;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  cursor: pointer;
  font-size: 0.76rem;
  font-weight: 700;
  white-space: nowrap;
}

.guest-mini-button svg {
  width: 14px;
  height: 14px;
}

.guest-mini-button:hover {
  border-color: rgba(20, 184, 166, 0.28);
  background: rgba(204, 251, 241, 0.76);
}

.mode-switch {
  width: 100%;
  padding: 4px;
  border-radius: 16px;
  border: 1px solid rgba(20, 184, 166, 0.14);
  background: rgba(15, 118, 110, 0.07);
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 4px;
}

.mode-switch-item {
  appearance: none;
  border: 0;
  border-radius: 12px;
  background: transparent;
  color: var(--text-muted);
  height: 40px;
  padding: 0 12px;
  font-size: 0.9rem;
  font-weight: 700;
  line-height: 1;
  cursor: pointer;
  transition: background 0.18s ease, color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
}

.mode-switch-item:hover {
  color: #0f766e;
  background: var(--surface-hover);
}

.mode-switch-item.active {
  color: #0f766e;
  background: var(--surface-solid);
  box-shadow: 0 8px 20px rgba(20, 184, 166, 0.14);
}

.mode-switch-item:active {
  transform: translateY(1px);
}

.form-grid {
  display: grid;
  gap: 13px;
}

.field-row {
  display: grid;
  gap: 7px;
  color: var(--text);
  font-size: 0.88rem;
  font-weight: 650;
}

.form-extra-slot {
  min-height: 74px;
  display: grid;
  align-items: stretch;
}

.login-note {
  min-height: 74px;
  padding: 12px 13px;
  border: 1px solid rgba(20, 184, 166, 0.12);
  border-radius: 13px;
  background: rgba(236, 253, 249, 0.48);
  color: var(--text);
  display: grid;
  grid-template-columns: 22px minmax(0, 1fr);
  gap: 9px;
  align-items: center;
}

.login-note .el-icon {
  color: #0f766e;
  font-size: 17px;
}

.login-note div {
  min-width: 0;
  display: grid;
  gap: 2px;
}

.login-note strong {
  color: var(--text);
  font-size: 0.84rem;
  line-height: 1.3;
}

.login-note span {
  color: var(--text-muted);
  font-size: 0.78rem;
  line-height: 1.45;
}

.field-row :deep(.el-input__wrapper) {
  min-height: 44px;
  border-radius: 12px;
  background: var(--surface-subtle);
  box-shadow: 0 0 0 1px var(--border) inset;
}

.field-row :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px rgba(20, 184, 166, 0.32) inset;
}

.auth-error {
  border-radius: 12px;
}

.card-actions {
  display: grid;
  gap: 10px;
}

.submit-button {
  --el-button-bg-color: #0f766e;
  --el-button-border-color: #0f766e;
  --el-button-hover-bg-color: #0d9488;
  --el-button-hover-border-color: #0d9488;
  --el-button-active-bg-color: #0b6f68;
  --el-button-active-border-color: #0b6f68;
  --el-button-text-color: #fff;
  --el-button-hover-text-color: #fff;
  --el-button-active-text-color: #fff;
  min-height: 46px;
  border-radius: 12px;
  width: 100%;
  justify-content: center;
  gap: 8px;
}

.switch-link {
  border: 0;
  background: transparent;
  color: #0f766e;
  font-size: 0.88rem;
  font-weight: 700;
  cursor: pointer;
  padding: 0;
  justify-self: center;
}

@media (max-width: 1020px) {
  .auth-shell {
    grid-template-columns: 1fr;
    gap: 22px;
    align-items: center;
  }

  .auth-hero,
  .auth-card {
    max-width: 680px;
    justify-self: center;
  }
}

@media (max-width: 720px) {
  .auth-screen {
    padding: 16px;
    place-items: start center;
  }

  .auth-card {
    border-radius: 18px;
    padding: 20px;
  }

  .auth-hero {
    gap: 18px;
  }

  .auth-hero h1 {
    max-width: 100%;
    font-size: 1.78rem;
    white-space: normal;
  }

  .hero-copy {
    font-size: 0.94rem;
  }

  .capability-grid {
    grid-template-columns: 1fr;
  }
}
</style>
