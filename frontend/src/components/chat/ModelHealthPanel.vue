<script setup lang="ts">
import { computed } from "vue";
import type { ChatModelOption } from "../../api";
import { useI18n } from "../../composables/useI18n";
import { formatChinaDateTime } from "../../utils/dateTime";

const props = defineProps<{
  modelOptions: ChatModelOption[];
  selectedModel: string;
  loading: boolean;
  lastCheckedAt: number | null;
  showTitle?: boolean;
  dialogMode?: boolean;
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
  return formatChinaDateTime(props.lastCheckedAt, locale.value);
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
  <section class="model-health-panel" :class="{ 'is-dialog-mode': dialogMode }">
    <header class="panel-head">
      <div>
        <h3 v-if="showTitle !== false">{{ t("model_health.title") }}</h3>
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
          <span class="check-pill neutral">
            {{ t("model_health.tool_calling", { value: option.supports_tool_calling ? t("model_health.yes") : t("model_health.no") }) }}
          </span>
          <span class="check-pill neutral">
            {{ t("model_health.multimodal_input", { value: option.supports_multimodal_input ? t("model_health.yes") : t("model_health.no") }) }}
          </span>
          <span class="check-pill neutral">
            {{ t("model_health.responses_api", { value: option.supports_responses_api ? t("model_health.yes") : t("model_health.no") }) }}
          </span>
          <span class="check-pill neutral">
            {{ t("model_health.responses_streaming", { value: option.supports_responses_streaming ? t("model_health.yes") : t("model_health.no") }) }}
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
  border: 1px solid var(--border);
  border-radius: 14px;
  background: var(--surface);
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
  color: var(--text);
  font-size: 0.98rem;
  line-height: 1.3;
}

.panel-head p {
  margin: 2px 0 0;
  color: var(--text-muted);
  font-size: 0.8rem;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.summary-card {
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 8px 10px;
  display: grid;
  gap: 4px;
  background: var(--surface-subtle);
}

.model-health-panel.is-dialog-mode {
  margin: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  padding: 0;
  box-shadow: none;
}

.summary-card span {
  color: var(--text-muted);
  font-size: 0.76rem;
}

.summary-card strong {
  color: var(--text);
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

.model-health-panel.is-dialog-mode .health-list {
  max-height: min(58vh, 560px);
}

.model-item {
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--surface-solid);
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
  background: var(--surface-danger);
}

.model-item-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.model-name {
  color: var(--text);
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
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 2px 8px;
  font-size: 0.76rem;
  color: var(--text-muted);
  background: var(--surface-muted);
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
  color: var(--text-muted);
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: baseline;
}

.base-url code {
  word-break: break-all;
  font-family: "JetBrains Mono", "Consolas", monospace;
  background: var(--surface-muted);
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

  .model-health-panel.is-dialog-mode {
    margin: 0;
  }
}
</style>
