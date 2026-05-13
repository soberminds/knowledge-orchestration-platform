<script setup lang="ts">
import { computed } from "vue";
import type { ChatModelOption } from "../../api";
import { useI18n } from "../../composables/useI18n";

interface ModelGroup {
  provider: string;
  models: ChatModelOption[];
}

const props = defineProps<{
  modelValue: string;
  loading: boolean;
  starterPrompts: string[];
  showStarters: boolean;
  topK: number;
  selectedModel: string;
  thinkingMode: "quick" | "deep";
  nativeWebSearchEnabled: boolean;
  nativeWebSearchSupported: boolean;
  externalWebSearchEnabled: boolean;
  externalWebSearchAvailable: boolean;
  modelGroups: ModelGroup[];
  optionsLoading: boolean;
  modelHealthVisible: boolean;
}>();

const emit = defineEmits<{
  (event: "update:modelValue", value: string): void;
  (event: "update:top-k", value: number): void;
  (event: "update:selected-model", value: string): void;
  (event: "update:thinking-mode", value: "quick" | "deep"): void;
  (event: "update:native-web-search-enabled", value: boolean): void;
  (event: "update:external-web-search-enabled", value: boolean): void;
  (event: "refresh-model-options"): void;
  (event: "toggle-model-health"): void;
  (event: "send"): void;
  (event: "pick-starter", prompt: string): void;
}>();

const { t } = useI18n();

const totalModelCount = computed(() => props.modelGroups.reduce((sum, group) => sum + group.models.length, 0));
const availableModelCount = computed(() =>
  props.modelGroups.reduce((sum, group) => sum + group.models.filter((item) => item.available).length, 0),
);

const selectedModelOption = computed(() => {
  for (const group of props.modelGroups) {
    const found = group.models.find((item) => item.model === props.selectedModel);
    if (found) {
      return found;
    }
  }
  return null;
});

const modelSummary = computed(() => {
  const raw = selectedModelOption.value?.model || props.selectedModel || t("chat.model_prefix");
  return raw.length > 26 ? `${raw.slice(0, 26)}...` : raw;
});

const thinkingSummary = computed(() => (props.thinkingMode === "deep" ? t("chat.mode_deep") : t("chat.mode_quick")));

const webSummary = computed(() => {
  if (!props.nativeWebSearchSupported && !props.externalWebSearchAvailable) {
    return t("chat.web_off");
  }
  const enabled = props.nativeWebSearchEnabled || props.externalWebSearchEnabled;
  return enabled ? t("chat.web_on") : t("chat.web_off");
});

function modelDescription(model: ChatModelOption): string {
  if (!model.available) {
    return model.unavailable_reason || t("chat.model_not_configured");
  }
  if (model.thinking_style === "qwen") {
    const budget = model.deep_thinking_budget ?? 2048;
    return t("chat.model_qwen_budget", { budget });
  }
  if (model.thinking_style === "deepseek") {
    return t("chat.model_deepseek_effort", { effort: model.deep_reasoning_effort || "high" });
  }
  return t("chat.model_general");
}

function pickModel(model: ChatModelOption) {
  if (!model.available) {
    return;
  }
  emit("update:selected-model", model.model);
}

function normalizeTopK(value: unknown): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return props.topK;
  }
  return Math.max(1, Math.min(10, Math.round(parsed)));
}
</script>

<template>
  <footer class="composer-wrap">
    <div v-if="showStarters" class="starter-list">
      <button
        v-for="prompt in starterPrompts"
        :key="prompt"
        @click="$emit('pick-starter', prompt)"
      >
        {{ prompt }}
      </button>
    </div>

    <div class="composer-card">
      <el-input
        :model-value="modelValue"
        type="textarea"
        :rows="2"
        resize="none"
        :placeholder="t('chat.input_placeholder')"
        @update:model-value="$emit('update:modelValue', String($event))"
        @keydown.enter.exact.prevent="$emit('send')"
      />
    <div class="composer-actions">
      <span class="helper-text">{{ t("chat.helper_text") }}</span>
      <el-button type="primary" :loading="loading" @click="$emit('send')">
        {{ t("chat.send") }}
        </el-button>
    </div>
    </div>

    <div class="bubble-row">
      <el-popover placement="top-start" :width="420" trigger="click" popper-class="chat-settings-popper">
        <template #reference>
          <button class="option-pill option-pill--primary" type="button">
            <span class="option-dot" />
            {{ t("chat.model_prefix") }}: {{ modelSummary }}
          </button>
        </template>

        <section class="settings-panel">
          <header class="settings-head">
            <strong>{{ t("chat.settings_model_selection") }}</strong>
            <el-button link type="primary" :loading="optionsLoading" @click="$emit('refresh-model-options')">
              {{ t("chat.settings_refresh") }}
            </el-button>
          </header>

          <div class="settings-models">
            <section v-for="group in modelGroups" :key="group.provider" class="model-group">
              <p class="group-title">{{ group.provider }}</p>
              <button
                v-for="model in group.models"
                :key="model.model"
                type="button"
                class="model-item"
                :class="{
                  selected: model.model === selectedModel,
                  disabled: !model.available,
                }"
                :disabled="!model.available"
                @click="pickModel(model)"
              >
                <span class="model-main">{{ model.model }}</span>
                <span class="model-sub">{{ modelDescription(model) }}</span>
                <span v-if="model.model === selectedModel" class="model-check">{{ t("chat.settings_selected") }}</span>
              </button>
            </section>
          </div>
        </section>
      </el-popover>

      <el-popover
        v-if="nativeWebSearchSupported || externalWebSearchAvailable"
        placement="top-start"
        :width="320"
        trigger="click"
      >
        <template #reference>
          <button class="option-pill" type="button">{{ t("chat.web_prefix") }}: {{ webSummary }}</button>
        </template>
        <section class="settings-panel">
          <header class="settings-head">
            <strong>{{ t("chat.settings_web_search") }}</strong>
          </header>
          <div class="settings-row switch-stack">
            <div v-if="nativeWebSearchSupported" class="switch-line">
              <span>{{ t("chat.settings_native_web") }}</span>
              <el-switch
                :model-value="nativeWebSearchEnabled"
                @update:model-value="$emit('update:native-web-search-enabled', Boolean($event))"
              />
            </div>
            <div v-if="externalWebSearchAvailable" class="switch-line">
              <span>{{ t("chat.settings_external_web") }}</span>
              <el-switch
                :model-value="externalWebSearchEnabled"
                @update:model-value="$emit('update:external-web-search-enabled', Boolean($event))"
              />
            </div>
          </div>
        </section>
      </el-popover>

      <el-popover placement="top-start" :width="300" trigger="click">
        <template #reference>
          <button class="option-pill" type="button">{{ t("chat.thinking_prefix") }}: {{ thinkingSummary }}</button>
        </template>
        <section class="settings-panel">
          <header class="settings-head">
            <strong>{{ t("chat.settings_thinking_mode") }}</strong>
          </header>
          <el-segmented
            :model-value="thinkingMode"
            :options="[
              { label: t('chat.mode_quick'), value: 'quick' },
              { label: t('chat.mode_deep'), value: 'deep' },
            ]"
            @change="$emit('update:thinking-mode', String($event) as 'quick' | 'deep')"
          />
          <p class="hint-line">
            {{ t("chat.settings_thinking_hint") }}
          </p>
        </section>
      </el-popover>

      <el-popover placement="top-start" :width="280" trigger="click">
        <template #reference>
          <button class="option-pill" type="button">{{ t("chat.topk_prefix") }}: {{ topK }}</button>
        </template>
        <section class="settings-panel">
          <header class="settings-head">
            <strong>{{ t("chat.settings_retrieval_range") }}</strong>
          </header>
          <div class="settings-row">
            <label>{{ t("chat.settings_top_k") }}</label>
            <el-input-number
              :model-value="topK"
              :min="1"
              :max="10"
              size="small"
              controls-position="right"
              @update:model-value="$emit('update:top-k', normalizeTopK($event))"
            />
          </div>
          <p class="hint-line">{{ t("chat.settings_top_k_hint") }}</p>
        </section>
      </el-popover>

      <button
        class="option-pill option-pill--ghost"
        :class="{ 'option-pill--active': modelHealthVisible }"
        type="button"
        @click="$emit('toggle-model-health')"
      >
        {{ t("chat.model_health") }} {{ availableModelCount }}/{{ totalModelCount }}
      </button>
    </div>
  </footer>
</template>

<style scoped>
.composer-wrap {
  padding: 0 24px 16px;
  background: linear-gradient(180deg, rgba(247, 247, 248, 0) 0%, #f7f7f8 100%);
}

.starter-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}

.starter-list button {
  border: 1px solid #e5e7eb;
  background: #fff;
  border-radius: 999px;
  padding: 6px 12px;
  cursor: pointer;
  color: #374151;
}

.starter-list button:hover {
  background: #f9fafb;
}

.composer-card {
  border: 1px solid #d6dbe3;
  background: #fff;
  border-radius: 22px;
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.08);
  padding: 10px 10px 8px;
}

.composer-card :deep(.el-textarea__inner) {
  border: 0;
  box-shadow: none;
  resize: none;
  min-height: 56px !important;
  background: transparent;
}

.composer-actions {
  margin-top: 4px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.helper-text {
  color: #6b7280;
  font-size: 0.84rem;
}

.bubble-row {
  margin-top: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.option-pill {
  border: 1px solid #d4dae4;
  background: #fff;
  color: #344255;
  border-radius: 999px;
  padding: 6px 12px;
  font-size: 0.84rem;
  line-height: 1;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.option-pill--primary {
  border-color: #b8c8e6;
  background: #eef4ff;
  color: #1f4f98;
}

.option-pill--ghost {
  margin-left: auto;
}

.option-pill--active {
  border-color: #7bb28d;
  background: #eaf6ee;
  color: #1d7f49;
}

.option-pill:hover {
  border-color: #a8b6ce;
  background: #f8fafc;
}

.option-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #2f6fdb;
}

.settings-panel {
  display: grid;
  gap: 12px;
}

.settings-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.settings-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.settings-row label {
  font-size: 0.9rem;
  color: #2f3d51;
}

.switch-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.switch-stack {
  display: grid;
  gap: 8px;
}

.switch-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  color: #334155;
  font-size: 0.9rem;
}

.settings-models {
  border-top: 1px solid #e5e9f0;
  padding-top: 10px;
  display: grid;
  gap: 10px;
  max-height: 280px;
  overflow: auto;
}

.settings-block-title {
  margin: 0;
  font-size: 0.9rem;
  color: #475569;
}

.model-group {
  display: grid;
  gap: 6px;
}

.group-title {
  margin: 0;
  font-size: 0.8rem;
  color: #6b7280;
}

.model-item {
  width: 100%;
  border: 1px solid #d9e1eb;
  background: #fff;
  border-radius: 10px;
  padding: 8px 10px;
  display: grid;
  gap: 3px;
  text-align: left;
  position: relative;
  cursor: pointer;
}

.model-item:hover {
  border-color: #b9c9de;
  background: #f9fbfe;
}

.model-item.selected {
  border-color: #7bb28d;
  background: #eaf6ee;
}

.model-item.disabled {
  opacity: 0.6;
  cursor: not-allowed;
  background: #f8fafc;
}

.model-main {
  color: #1f2937;
  font-size: 0.92rem;
  font-weight: 500;
  word-break: break-all;
}

.model-sub {
  color: #64748b;
  font-size: 0.78rem;
  word-break: break-all;
}

.model-check {
  position: absolute;
  right: 10px;
  top: 8px;
  color: #1d7f49;
  font-weight: 700;
  font-size: 0.75rem;
}

.hint-line {
  margin: 0;
  color: #64748b;
  font-size: 0.8rem;
}

@media (max-width: 720px) {
  .composer-wrap {
    padding-left: 12px;
    padding-right: 12px;
  }

  .option-pill--ghost {
    margin-left: 0;
  }
}
</style>
