<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { ArrowRight, Key, Lock, User } from "@element-plus/icons-vue";

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

const title = computed(() => (props.mode === "login" ? "欢迎回来" : "创建本地账号"));
const subtitle = computed(() =>
  props.mode === "login"
    ? "使用已有账号继续，或者直接进入游客模式。"
    : "注册后可保存个人会话、文档范围和偏好设置。",
);
const submitLabel = computed(() => (props.mode === "login" ? "登录" : "注册"));
const switchLabel = computed(() => (props.mode === "login" ? "没有账号，去注册" : "已有账号，去登录"));
const submitIcon = computed(() => (props.mode === "login" ? Key : ArrowRight));
const guestHint = computed(() => props.guestUserLabel || "默认本地用户 local-user");

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
      <div class="auth-hero">
        <div class="brand-row">
          <div class="brand-mark">R</div>
          <div class="brand-copy">
            <strong>RAG Knowledge Platform</strong>
            <small>{{ guestHint }}</small>
          </div>
        </div>

        <h1>{{ title }}</h1>
        <p class="hero-copy">
          {{ subtitle }}
        </p>

        <ul class="feature-list">
          <li>本地游客可直接进入，不会挡住试用流程。</li>
          <li>登录后可绑定自己的会话、文件夹和知识范围。</li>
          <li>注册账号后，文档、聊天和检索都能按用户隔离。</li>
        </ul>
      </div>

      <div class="auth-card">
        <div class="auth-card-head">
          <div>
            <p class="card-kicker">Account Access</p>
            <h2>{{ title }}</h2>
          </div>
          <el-button class="guest-button" plain @click="$emit('continue-guest')">
            游客进入
          </el-button>
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

          <label v-if="mode === 'register'" class="field-row">
            <span>昵称</span>
            <el-input
              v-model="nickname"
              placeholder="选填，展示名称"
              autocomplete="nickname"
              @keyup.enter.exact="submit"
            />
          </label>
        </div>

        <el-alert v-if="errorMessage" class="auth-error" :title="errorMessage" type="error" show-icon :closable="false" />

        <div class="card-actions">
          <el-button class="submit-button" :loading="loading" @click="submit">
            <el-icon><component :is="submitIcon" /></el-icon>
            <span>{{ submitLabel }}</span>
          </el-button>
          <button class="switch-link" type="button" @click="switchMode(mode === 'login' ? 'register' : 'login')">
            {{ switchLabel }}
          </button>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.auth-screen {
  min-height: 100vh;
  padding: 28px;
  display: grid;
  place-items: center;
  background:
    radial-gradient(circle at 18% 18%, rgba(20, 184, 166, 0.14), transparent 36%),
    radial-gradient(circle at 82% 8%, rgba(6, 182, 212, 0.08), transparent 28%),
    linear-gradient(180deg, var(--surface-subtle) 0%, var(--bg) 100%);
  position: relative;
  overflow: hidden;
}

.auth-screen::before {
  content: "";
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(148, 163, 184, 0.08) 1px, transparent 1px),
    linear-gradient(90deg, rgba(148, 163, 184, 0.08) 1px, transparent 1px);
  background-size: 36px 36px;
  mask-image: linear-gradient(180deg, rgba(0, 0, 0, 0.72), transparent 92%);
  pointer-events: none;
}

.auth-shell {
  position: relative;
  z-index: 1;
  width: min(1120px, 100%);
  display: grid;
  grid-template-columns: minmax(0, 1.02fr) minmax(340px, 0.98fr);
  gap: 20px;
  align-items: stretch;
}

.auth-hero,
.auth-card {
  border: 1px solid var(--border);
  border-radius: 24px;
  background: var(--surface);
  box-shadow: 0 24px 48px rgba(15, 23, 42, 0.08);
  backdrop-filter: blur(14px);
}

.auth-hero {
  padding: 32px 34px;
  display: grid;
  align-content: center;
  gap: 18px;
}

.brand-row {
  display: inline-flex;
  align-items: center;
  gap: 12px;
}

.brand-mark {
  width: 44px;
  height: 44px;
  border-radius: 14px;
  background: linear-gradient(135deg, #0f766e 0%, #14b8a6 100%);
  color: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-weight: 800;
  box-shadow: 0 12px 22px rgba(20, 184, 166, 0.18);
}

.brand-copy {
  display: grid;
}

.brand-copy strong {
  color: var(--text);
  font-size: 0.96rem;
}

.brand-copy small {
  color: var(--text-muted);
  font-size: 0.8rem;
}

.auth-hero h1 {
  margin: 0;
  color: var(--text);
  font-size: clamp(2rem, 2vw + 1rem, 3rem);
  line-height: 1.08;
  letter-spacing: 0;
}

.hero-copy {
  margin: 0;
  max-width: 36rem;
  color: var(--text-muted);
  line-height: 1.75;
  font-size: 0.96rem;
}

.feature-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 10px;
}

.feature-list li {
  padding: 11px 12px;
  border-radius: 14px;
  border: 1px solid var(--border);
  background: var(--surface-subtle);
  color: var(--text);
  line-height: 1.55;
}

.auth-card {
  padding: 22px 22px 20px;
  display: grid;
  gap: 14px;
  align-content: center;
}

.auth-card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.card-kicker {
  margin: 0 0 4px;
  color: #0f766e;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.auth-card h2 {
  margin: 0;
  color: var(--text);
  font-size: 1.2rem;
}

.mode-switch {
  width: 100%;
  padding: 4px;
  border-radius: 18px;
  border: 1px solid rgba(20, 184, 166, 0.12);
  background: rgba(15, 118, 110, 0.07);
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 4px;
}

.mode-switch-item {
  appearance: none;
  border: 0;
  border-radius: 14px;
  background: transparent;
  color: var(--text-muted);
  height: 38px;
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
  gap: 12px;
}

.field-row {
  display: grid;
  gap: 7px;
  color: var(--text);
  font-size: 0.88rem;
  font-weight: 600;
}

.field-row :deep(.el-input__wrapper) {
  border-radius: 14px;
  background: var(--surface-subtle);
  box-shadow: 0 0 0 1px var(--border) inset;
}

.field-row :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px rgba(20, 184, 166, 0.28) inset;
}

.auth-error {
  border-radius: 14px;
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
  min-height: 44px;
  border-radius: 14px;
  width: 100%;
  justify-content: center;
}

.guest-button {
  height: 34px;
  padding: 0 12px;
  border-radius: 999px;
  border-color: var(--border);
  color: var(--text);
  background: var(--surface-solid);
  box-shadow: 0 4px 10px rgba(15, 23, 42, 0.04);
}

.switch-link {
  border: 0;
  background: transparent;
  color: #0f766e;
  font-size: 0.88rem;
  font-weight: 600;
  cursor: pointer;
  padding: 0;
  justify-self: center;
}

@media (max-width: 980px) {
  .auth-shell {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .auth-screen {
    padding: 12px;
  }

  .auth-hero,
  .auth-card {
    border-radius: 20px;
    padding: 20px;
  }

  .auth-card-head {
    align-items: flex-start;
    flex-direction: column;
  }

  .mode-switch {
    grid-template-columns: 1fr 1fr;
  }
}
</style>
