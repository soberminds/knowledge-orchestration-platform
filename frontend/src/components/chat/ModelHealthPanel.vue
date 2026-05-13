<script setup lang="ts">
import { computed } from "vue";
import type { ChatModelOption } from "../../api";
import { useI18n } from "../../composables/useI18n";

const props = defineProps<{
  modelOptions: ChatModelOption[];
  selectedModel: string;
  loading: boolean;
  lastCheckedAt: number | null;
}>();

const emit = defineEmits<{
  (event: "refresh"): void;
}>();

const { locale, t } = useI18n();

const totalCount = computed(() => props.modelOptions.length);
const availableCount = computed(() => props.modelOptions.filter((item) => item.available).length);
const unavailableCount = computed(() => Math.max(0, totalCount.value - availableCount.value));

const formattedCheckedAt = computed(() => {
  if (!props.lastCheckedAt) {
    return t("model_health.not_checked");
  }
  return new Date(props.lastCheckedAt).toLocaleString(locale.value, { hour12: false });
});

function providerLabel(provider: string) {
  const token = provider.trim().toLowerCase();
  if (token === "deepseek") return "DeepSeek";
  if (token === "qwen") return "Qwen";
  if (token === "zai") return "Z.AI";
  if (token === "kimi") return "Moonshot";
  if (token === "hunyuan") return "Hunyuan";
  if (token === "qianfan") return "Qianfan";
  if (token === "siliconflow") return "SiliconFlow";
  if (token === "openai") return "OpenAI";
  return provider || "Other";
}

function checkLabel(enabled: boolean) {
  return enabled ? t("model_health.configured") : t("model_health.missing");
}

function thinkingStyleLabel(style?: string | null) {
  const token = String(style || "none").trim().toLowerCase();
  if (token === "deepseek") return t("model_health.style.deepseek");
  if (token === "qwen") return t("model_health.style.qwen");
  return t("model_health.style.generic");
}
</script>

<template>
  <section class="model-health-panel">
    <header class="panel-head">
      <div>
        <h3>{{ t("model_health.title") }}</h3>
        <p>{{ t("model_health.last_check", { time: formattedCheckedAt }) }}</p>
      </div>
      <el-button size="small" :loading="loading" @click="emit('refresh')">{{ t("chat.settings_refresh") }}</el-button>
    </header>

    <section class="summary-grid">
      <article class="summary-card">
        <span>{{ t("model_health.total") }}</span>
        <strong>{{ totalCount }}</strong>
      </article>
      <article class="summary-card ok">
        <span>{{ t("model_health.available") }}</span>
        <strong>{{ availableCount }}</strong>
      </article>
      <article class="summary-card bad">
        <span>{{ t("model_health.unavailable") }}</span>
        <strong>{{ unavailableCount }}</strong>
      </article>
    </section>

    <el-scrollbar class="health-list">
      <article
        v-for="option in modelOptions"
        :key="option.model"
        class="model-item"
        :class="{
          'is-selected': option.model === selectedModel,
          'is-unavailable': !option.available,
        }"
      >
        <div class="model-item-head">
          <div class="model-name">{{ option.model }}</div>
          <div class="head-tags">
            <el-tag size="small" :type="option.available ? 'success' : 'danger'">
              {{ option.available ? t("model_health.tag_available") : t("model_health.tag_unavailable") }}
            </el-tag>
            <el-tag size="small" effect="plain">{{ providerLabel(option.provider) }}</el-tag>
            <el-tag
              v-if="option.model === selectedModel"
              size="small"
              effect="dark"
              type="info"
            >
              {{ t("model_health.tag_selected") }}
            </el-tag>
          </div>
        </div>

        <div class="check-row">
          <span class="check-pill neutral">
            {{ t("model_health.thinking_style", { style: thinkingStyleLabel(option.thinking_style) }) }}
          </span>
          <span
            class="check-pill"
            :class="{ ok: Boolean(option.api_key_configured), bad: !Boolean(option.api_key_configured) }"
          >
            {{ t("model_health.api_key", { status: checkLabel(Boolean(option.api_key_configured)) }) }}
          </span>
          <span
            class="check-pill"
            :class="{ ok: Boolean(option.base_url_configured), bad: !Boolean(option.base_url_configured) }"
          >
            {{ t("model_health.base_url", { status: checkLabel(Boolean(option.base_url_configured)) }) }}
          </span>
          <span class="check-pill neutral">
            {{ t("model_health.native_search", { value: option.supports_native_web_search ? t("model_health.yes") : t("model_health.no") }) }}
          </span>
        </div>

        <p class="base-url">
          <span>{{ t("model_health.base_url_label") }}</span>
          <code>{{ option.base_url || t("model_health.base_url_not_set") }}</code>
        </p>
        <p v-if="option.thinking_style === 'deepseek'" class="mapping-detail">
          {{ t("model_health.deepseek_mapping", { effort: option.deep_reasoning_effort || "high" }) }}
        </p>
        <p v-if="option.thinking_style === 'qwen'" class="mapping-detail">
          {{ t("model_health.qwen_mapping", { budget: option.deep_thinking_budget ?? "(default)" }) }}
        </p>
        <p v-if="!option.available" class="reason">
          {{ option.unavailable_reason || t("model_health.default_unavailable_reason") }}
        </p>
      </article>
    </el-scrollbar>
  </section>
</template>

<style scoped>
.model-health-panel {
  margin: 0 24px 12px;
  border: 1px solid #d7dee8;
  border-radius: 14px;
  background: linear-gradient(180deg, #f7fbff 0%, #ffffff 56%);
  padding: 12px;
  display: grid;
  gap: 10px;
}

.panel-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 8px;
}

.panel-head h3 {
  margin: 0;
  font-size: 0.98rem;
  line-height: 1.3;
}

.panel-head p {
  margin: 2px 0 0;
  color: #5f6b7a;
  font-size: 0.8rem;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.summary-card {
  border: 1px solid #d7dee8;
  border-radius: 10px;
  padding: 8px 10px;
  display: grid;
  gap: 4px;
  background: #fff;
}

.summary-card span {
  color: #6b7280;
  font-size: 0.76rem;
}

.summary-card strong {
  font-size: 1.04rem;
  line-height: 1.2;
}

.summary-card.ok strong {
  color: #0f8a5f;
}

.summary-card.bad strong {
  color: #c0392b;
}

.health-list {
  max-height: 260px;
  padding-right: 4px;
}

.model-item {
  border: 1px solid #dce4ee;
  border-radius: 12px;
  background: #fff;
  padding: 9px 10px;
  display: grid;
  gap: 7px;
}

.model-item + .model-item {
  margin-top: 8px;
}

.model-item.is-selected {
  border-color: #6aa9ff;
  box-shadow: 0 0 0 1px rgba(106, 169, 255, 0.2);
}

.model-item.is-unavailable {
  background: #fff8f8;
}

.model-item-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.model-name {
  font-size: 0.95rem;
  font-weight: 600;
  line-height: 1.2;
  word-break: break-all;
}

.head-tags {
  display: flex;
  align-items: center;
  gap: 6px;
}

.check-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.check-pill {
  border: 1px solid #d6deea;
  border-radius: 999px;
  padding: 2px 8px;
  font-size: 0.76rem;
  color: #4f5b6a;
  background: #f8fbff;
}

.check-pill.ok {
  border-color: #93d8bf;
  color: #11744f;
  background: #edf9f3;
}

.check-pill.bad {
  border-color: #eab8b8;
  color: #ad3232;
  background: #fff0f0;
}

.check-pill.neutral {
  border-color: #d2d9e4;
}

.base-url {
  margin: 0;
  font-size: 0.78rem;
  color: #586779;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: baseline;
}

.base-url code {
  word-break: break-all;
  font-family: "JetBrains Mono", "Consolas", monospace;
  background: #f3f6fa;
  border-radius: 6px;
  padding: 2px 6px;
}

.reason {
  margin: 0;
  font-size: 0.78rem;
  color: #b14242;
}

.mapping-detail {
  margin: 0;
  font-size: 0.78rem;
  color: #546375;
}

@media (max-width: 720px) {
  .model-health-panel {
    margin-left: 12px;
    margin-right: 12px;
  }
}
</style>
