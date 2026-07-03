<script setup lang="ts">
import { computed, ref } from "vue";
import { Close, Link, Paperclip, Picture } from "@element-plus/icons-vue";
import type { ChatMessagePart, ChatModelOption, DocumentInfo, KnowledgeBaseScopeOption, RunMode, WorkspaceScopeOption } from "../../api";
import { useI18n } from "../../composables/useI18n";
import type { FolderScopeNode } from "../../utils/documentTree";

type ChatScopeType = "all" | "folder" | "kb" | "workspace";
const MAX_PASTED_IMAGE_BYTES = 2 * 1024 * 1024;

interface ModelGroup {
  provider: string;
  models: ChatModelOption[];
}

const props = defineProps<{
  modelValue: string;
  messageParts: ChatMessagePart[];
  loading: boolean;
  starterPrompts: string[];
  showStarters: boolean;
  topK: number;
  selectedModel: string;
  thinkingMode: "quick" | "deep";
  runMode: RunMode;
  scopeType: ChatScopeType;
  scopeId: number | null;
  scopeName: string | null;
  workspaceKey: string | null;
  folderScopeTree: FolderScopeNode[];
  knowledgeBaseOptions: KnowledgeBaseScopeOption[];
  workspaceOptions: WorkspaceScopeOption[];
  documents: DocumentInfo[];
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
  (event: "update:message-parts", value: ChatMessagePart[]): void;
  (event: "update:top-k", value: number): void;
  (event: "update:selected-model", value: string): void;
  (event: "update:thinking-mode", value: "quick" | "deep"): void;
  (event: "update:run-mode", value: RunMode): void;
  (event: "update:scope-type", value: ChatScopeType): void;
  (event: "update:scope-id", value: number | null): void;
  (event: "update:scope-name", value: string | null): void;
  (event: "update:workspace-key", value: string | null): void;
  (event: "update:native-web-search-enabled", value: boolean): void;
  (event: "update:external-web-search-enabled", value: boolean): void;
  (event: "refresh-model-options"): void;
  (event: "toggle-model-health"): void;
  (event: "send"): void;
  (event: "pick-starter", prompt: string): void;
}>();

const { t } = useI18n();
const imageUrlDraft = ref("");
const pastedImageError = ref("");
const previewImageUrl = ref("");
const imagePreviewVisible = computed({
  get: () => Boolean(previewImageUrl.value),
  set: (value: boolean) => {
    if (!value) {
      previewImageUrl.value = "";
    }
  },
});

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

const scopeOptions = computed(() => [
  { label: t("chat.scope_all"), value: "all" },
  { label: t("chat.scope_folder"), value: "folder" },
  { label: t("chat.scope_kb"), value: "kb" },
  { label: t("chat.scope_workspace"), value: "workspace" },
]);

const thinkingSummary = computed(() => (props.thinkingMode === "deep" ? t("chat.mode_deep") : t("chat.mode_quick")));
const usesRetrievalControls = computed(() => props.runMode !== "chat");
const runModeSummary = computed(() => {
  if (props.runMode === "chat") {
    return t("chat.run_mode_chat");
  }
  if (props.runMode === "agent") {
    return t("chat.run_mode_agent");
  }
  return t("chat.run_mode_rag");
});

const runModeOptions = computed(() => [
  { label: t("chat.run_mode_chat"), value: "chat" },
  { label: t("chat.run_mode_rag"), value: "rag" },
  { label: t("chat.run_mode_agent"), value: "agent" },
]);

function findFolderLabel(nodes: FolderScopeNode[], id: number | null): string | null {
  if (id == null) {
    return null;
  }
  for (const node of nodes) {
    if (node.id === id) {
      return node.label;
    }
    const nested = findFolderLabel(node.children ?? [], id);
    if (nested) {
      return nested;
    }
  }
  return null;
}

function findKnowledgeBaseLabel(id: number | null): string | null {
  if (id == null) {
    return null;
  }
  return props.knowledgeBaseOptions.find((item) => item.id === id)?.label ?? null;
}

function findWorkspaceLabel(key: string | null): string | null {
  const normalizedKey = key?.trim();
  if (!normalizedKey) {
    return null;
  }
  return (
    props.workspaceOptions.find((item) => item.key === normalizedKey || item.id === Number(normalizedKey))?.label ??
    normalizedKey
  );
}

const webSummary = computed(() => {
  if (!props.nativeWebSearchSupported && !props.externalWebSearchAvailable) {
    return t("chat.web_off");
  }
  const enabled = props.nativeWebSearchEnabled || props.externalWebSearchEnabled;
  return enabled ? t("chat.web_on") : t("chat.web_off");
});

const fileOptions = computed(() =>
  props.documents
    .filter((item) => !item.is_directory)
    .map((item) => ({
      ...item,
      label: item.display_path || item.path || item.name || `#${item.id ?? ""}`,
    })),
);

const selectedFileIds = computed(() =>
  props.messageParts
    .filter((part) => part.type === "file_ref" && part.file_id != null)
    .map((part) => Number(part.file_id)),
);

const attachmentSummary = computed(() => {
  const count = props.messageParts.filter((part) => part.type !== "text").length;
  return count > 0 ? t("chat.attachments_count", { count }) : t("chat.attachments");
});

const attachmentChips = computed(() =>
  props.messageParts
    .filter((part) => part.type !== "text")
    .map((part, index) => ({
      key: buildAttachmentKey(part, index),
      label:
        part.type === "file_ref"
          ? part.file_name || `#${part.file_id ?? ""}`
          : formatImagePartLabel(part.image_url || ""),
      type: part.type,
      imageUrl: part.type === "image_url" ? part.image_url || "" : "",
      index,
    })),
);

function buildAttachmentKey(part: ChatMessagePart, index: number): string {
  if (part.type === "file_ref") {
    return `${part.type}-${part.file_id ?? part.file_name ?? index}`;
  }
  if (part.type === "image_url" && part.image_url?.startsWith("data:image/")) {
    return `${part.type}-pasted-${index}-${part.image_url.length}`;
  }
  return `${part.type}-${part.image_url ?? index}`;
}

function formatImagePartLabel(imageUrl: string): string {
  if (!imageUrl) {
    return t("chat.attachment_image");
  }
  if (imageUrl.startsWith("data:image/")) {
    return t("chat.attachment_pasted_image");
  }
  return imageUrl;
}

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

const scopeSummary = computed(() => {
  const scopeName = props.scopeName?.trim() || "";
  const shorten = (value: string, max = 24) => (value.length > max ? `${value.slice(0, max)}...` : value);

  if (props.scopeType === "folder") {
    const label = scopeName || findFolderLabel(props.folderScopeTree, props.scopeId) || "";
    if (label) {
      return `${t("chat.scope_folder")}: ${shorten(label)}`;
    }
    return props.scopeId == null ? `${t("chat.scope_folder")}: ${t("chat.scope_unset")}` : `${t("chat.scope_folder")} #${props.scopeId}`;
  }
  if (props.scopeType === "kb") {
    const label = scopeName || findKnowledgeBaseLabel(props.scopeId) || "";
    if (label) {
      return `${t("chat.scope_kb")}: ${shorten(label)}`;
    }
    return props.scopeId == null ? `${t("chat.scope_kb")}: ${t("chat.scope_unset")}` : `${t("chat.scope_kb")} #${props.scopeId}`;
  }
  if (props.scopeType === "workspace") {
    const label = scopeName || findWorkspaceLabel(props.workspaceKey) || "";
    if (label) {
      return `${t("chat.scope_workspace")}: ${shorten(label)}`;
    }
    const key = props.workspaceKey?.trim();
    if (!key) {
      return `${t("chat.scope_workspace")}: ${t("chat.scope_unset")}`;
    }
    return `${t("chat.scope_workspace")}: ${shorten(key)}`;
  }
  return t("chat.scope_all");
});

function pickModel(model: ChatModelOption) {
  if (!model.available) {
    return;
  }
  emit("update:selected-model", model.model);
}

function normalizeScopeId(value: unknown): number | null {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return null;
  }
  return Math.max(1, Math.round(parsed));
}

function normalizeWorkspaceKey(value: unknown): string | null {
  const text = String(value ?? "").trim();
  return text ? text : null;
}

function normalizeSelectedLabel(value: unknown): string | null {
  const text = String(value ?? "").trim();
  return text ? text : null;
}

function handleFolderScopeChange(value: unknown) {
  const id = normalizeScopeId(value);
  emit("update:scope-id", id);
  emit("update:scope-name", id == null ? null : normalizeSelectedLabel(findFolderLabel(props.folderScopeTree, id)));
}

function handleKnowledgeBaseScopeChange(value: unknown) {
  const id = normalizeScopeId(value);
  emit("update:scope-id", id);
  emit("update:scope-name", id == null ? null : normalizeSelectedLabel(findKnowledgeBaseLabel(id)));
}

function handleWorkspaceScopeChange(value: unknown) {
  const key = normalizeWorkspaceKey(value);
  emit("update:workspace-key", key);
  emit("update:scope-name", key ? normalizeSelectedLabel(findWorkspaceLabel(key)) : null);
}

function normalizeTopK(value: unknown): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return props.topK;
  }
  return Math.max(1, Math.min(10, Math.round(parsed)));
}

function emitParts(parts: ChatMessagePart[]) {
  emit("update:message-parts", parts);
}

function handleFileRefsChange(value: unknown) {
  const ids = Array.isArray(value)
    ? value.map((item) => Number(item)).filter((item) => Number.isFinite(item) && item > 0)
    : [];
  const nonFileParts = props.messageParts.filter((part) => part.type !== "file_ref");
  const fileParts = ids
    .map((id) => fileOptions.value.find((item) => item.id === id))
    .filter((item): item is DocumentInfo & { label: string } => Boolean(item))
    .map((item) => ({
      type: "file_ref" as const,
      file_id: item.id ?? null,
      file_name: item.display_path || item.path || item.name || null,
      mime_type: item.extension || null,
    }));
  emitParts([...nonFileParts, ...fileParts]);
}

function addImageUrl() {
  const imageUrl = imageUrlDraft.value.trim();
  if (!imageUrl) {
    return;
  }
  emitParts([...props.messageParts, { type: "image_url", image_url: imageUrl }]);
  imageUrlDraft.value = "";
  pastedImageError.value = "";
}

function addPastedImage(file: File) {
  pastedImageError.value = "";
  if (!file.type.startsWith("image/")) {
    return;
  }
  if (file.size > MAX_PASTED_IMAGE_BYTES) {
    pastedImageError.value = t("chat.attachment_paste_too_large", { size: "2MB" });
    return;
  }

  const reader = new FileReader();
  reader.onload = () => {
    const dataUrl = typeof reader.result === "string" ? reader.result : "";
    if (!dataUrl) {
      pastedImageError.value = t("chat.attachment_paste_failed");
      return;
    }
    emitParts([...props.messageParts, { type: "image_url", image_url: dataUrl }]);
  };
  reader.onerror = () => {
    pastedImageError.value = t("chat.attachment_paste_failed");
  };
  reader.readAsDataURL(file);
}

function handlePaste(event: ClipboardEvent) {
  const files = Array.from(event.clipboardData?.files ?? []);
  const imageFile = files.find((file) => file.type.startsWith("image/"));
  if (!imageFile) {
    return;
  }
  event.preventDefault();
  addPastedImage(imageFile);
}

function removeAttachment(indexInFiltered: number) {
  const attachments = attachmentChips.value;
  const target = attachments[indexInFiltered];
  if (!target) {
    return;
  }
  let currentAttachmentIndex = -1;
  emitParts(
    props.messageParts.filter((part) => {
      if (part.type === "text") {
        return true;
      }
      currentAttachmentIndex += 1;
      return currentAttachmentIndex !== indexInFiltered;
    }),
  );
}

function openAttachmentPreview(chip: { type: string; imageUrl?: string }) {
  const imageUrl = String(chip.imageUrl || "");
  if (chip.type !== "image_url" || !imageUrl) {
    return;
  }
  previewImageUrl.value = imageUrl;
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
        @paste="handlePaste"
      />
      <div v-if="attachmentChips.length" class="attachment-strip">
        <span
          v-for="(chip, index) in attachmentChips"
          :key="chip.key"
          class="attachment-chip"
          :class="{ 'is-previewable': chip.type === 'image_url' && chip.imageUrl }"
          :title="chip.label"
          role="button"
          tabindex="0"
          @click="openAttachmentPreview(chip)"
          @keydown.enter.prevent="openAttachmentPreview(chip)"
          @keydown.space.prevent="openAttachmentPreview(chip)"
        >
          <el-icon v-if="chip.type === 'file_ref'"><Paperclip /></el-icon>
          <el-icon v-else><Picture /></el-icon>
          <span>{{ chip.label }}</span>
          <button type="button" :aria-label="t('chat.remove_attachment')" @click.stop="removeAttachment(index)">
            <el-icon><Close /></el-icon>
          </button>
        </span>
      </div>
      <div class="composer-actions">
        <div class="composer-left-actions">
          <el-popover placement="top-start" :width="380" trigger="click" popper-class="chat-settings-popper">
            <template #reference>
              <button class="composer-tool-button" type="button">
                <el-icon><Paperclip /></el-icon>
                <span>{{ attachmentSummary }}</span>
              </button>
            </template>
            <section class="settings-panel attachment-panel">
              <header class="settings-head">
                <strong>{{ t("chat.attachments") }}</strong>
              </header>

              <div class="attachment-field">
                <label>{{ t("chat.attachment_files") }}</label>
                <el-select
                  :model-value="selectedFileIds"
                  multiple
                  filterable
                  clearable
                  collapse-tags
                  collapse-tags-tooltip
                  size="small"
                  class="scope-select"
                  :placeholder="t('chat.attachment_files_placeholder')"
                  @update:model-value="handleFileRefsChange"
                >
                  <el-option
                    v-for="item in fileOptions"
                    :key="item.id ?? item.path"
                    :label="item.label"
                    :value="item.id"
                    :disabled="item.id == null"
                  />
                </el-select>
                <p class="hint-line">{{ t("chat.attachment_files_hint") }}</p>
              </div>

              <div class="attachment-field">
                <label>{{ t("chat.attachment_image_url") }}</label>
                <div class="attachment-image-row">
                  <el-input
                    v-model="imageUrlDraft"
                    size="small"
                    clearable
                    :placeholder="t('chat.attachment_image_placeholder')"
                    @keydown.enter.prevent="addImageUrl"
                  />
                  <el-button size="small" class="link-btn" @click="addImageUrl">
                    <el-icon><Link /></el-icon>
                    {{ t("chat.attachment_add") }}
                  </el-button>
                </div>
                <p class="hint-line">{{ t("chat.attachment_image_hint") }}</p>
                <p v-if="pastedImageError" class="hint-line error-line">{{ pastedImageError }}</p>
              </div>
            </section>
          </el-popover>
          <span class="helper-text">{{ t("chat.helper_text") }}</span>
        </div>
        <el-button class="send-btn" :loading="loading" @click="$emit('send')">
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
          <el-button link class="link-btn" :loading="optionsLoading" @click="$emit('refresh-model-options')">
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

      <el-popover placement="top-start" :width="340" trigger="click" popper-class="chat-settings-popper">
        <template #reference>
          <button class="option-pill" :class="{ 'option-pill--active': runMode === 'agent' }" type="button">
            <span class="option-dot option-dot--mode" />
            {{ t("chat.run_mode_prefix") }}: {{ runModeSummary }}
          </button>
        </template>
        <section class="settings-panel">
          <header class="settings-head">
            <strong>{{ t("chat.settings_run_mode") }}</strong>
          </header>
          <el-segmented
            :model-value="runMode"
            :options="runModeOptions"
            @change="$emit('update:run-mode', String($event) as RunMode)"
          />
          <p class="hint-line">{{ t("chat.settings_run_mode_hint") }}</p>
        </section>
      </el-popover>

      <el-popover v-if="usesRetrievalControls" placement="top-start" :width="360" trigger="click" popper-class="chat-settings-popper">
        <template #reference>
          <button class="option-pill" :class="{ 'option-pill--active': scopeType !== 'all' }" type="button">
            <span class="option-dot option-dot--scope" />
            {{ t("chat.scope_prefix") }}: {{ scopeSummary }}
          </button>
        </template>

        <section class="settings-panel">
          <header class="settings-head">
            <strong>{{ t("chat.settings_scope") }}</strong>
          </header>

          <el-segmented
            :model-value="scopeType"
            :options="scopeOptions"
            @change="$emit('update:scope-type', String($event) as ChatScopeType)"
          />

          <p class="hint-line">{{ t("chat.settings_scope_hint") }}</p>

          <div v-if="scopeType === 'folder' || scopeType === 'kb'" class="scope-field">
            <label>{{ scopeType === 'folder' ? t("chat.scope_folder") : t("chat.scope_kb") }}</label>
            <el-tree-select
              v-if="scopeType === 'folder'"
              :model-value="scopeId ?? undefined"
              :data="folderScopeTree"
              node-key="id"
              :props="{ value: 'id', label: 'label', children: 'children' }"
              filterable
              clearable
              check-strictly
              :render-after-expand="false"
              size="small"
              class="scope-tree-select"
              placeholder="请选择文件夹"
              @update:model-value="handleFolderScopeChange"
            />
            <el-select
              v-else
              :model-value="scopeId ?? undefined"
              filterable
              clearable
              size="small"
              class="scope-select"
              placeholder="请选择知识库"
              @update:model-value="handleKnowledgeBaseScopeChange"
            >
              <el-option
                v-for="item in knowledgeBaseOptions"
                :key="item.id"
                :label="item.label"
                :value="item.id"
              >
                <div class="scope-option">
                  <span class="scope-option-label">{{ item.label }}</span>
                  <small v-if="item.workspace_name">{{ item.workspace_name }}</small>
                </div>
              </el-option>
            </el-select>
            <p class="hint-line">
              {{ t("chat.settings_scope_hint") }}
            </p>
          </div>

          <div v-else-if="scopeType === 'workspace'" class="scope-field">
            <label>{{ t("chat.scope_workspace") }}</label>
            <el-select
              :model-value="workspaceKey ?? ''"
              filterable
              clearable
              size="small"
              class="scope-select"
              placeholder="请选择工作区"
              @update:model-value="handleWorkspaceScopeChange"
            >
              <el-option
                v-for="item in workspaceOptions"
                :key="item.key"
                :label="item.label"
                :value="item.key"
              >
                <div class="scope-option">
                  <span class="scope-option-label">{{ item.label }}</span>
                  <small v-if="item.workspace_name">{{ item.workspace_name }}</small>
                </div>
              </el-option>
            </el-select>
            <p class="hint-line">{{ t("chat.settings_scope_hint") }}</p>
          </div>

          <p v-else class="hint-line">{{ t("chat.settings_scope_all_hint") }}</p>
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

      <el-popover v-if="usesRetrievalControls" placement="top-start" :width="280" trigger="click">
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

  <el-dialog
    v-model="imagePreviewVisible"
    append-to-body
    class="attachment-preview-dialog"
    width="min(760px, 92vw)"
    :title="t('chat.attachment_image_preview')"
  >
    <img v-if="previewImageUrl" class="attachment-preview-image" :src="previewImageUrl" :alt="t('chat.attachment_image_preview')" />
  </el-dialog>
</template>

<style scoped>
.composer-wrap {
  padding: 0 24px 16px;
  background: linear-gradient(180deg, transparent 0%, var(--bg) 100%);
}

.starter-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}

.starter-list button {
  border: 1px solid var(--border);
  background: var(--surface);
  border-radius: 999px;
  padding: 6px 12px;
  cursor: pointer;
  color: var(--text);
}

.starter-list button:hover {
  background: var(--accent-soft);
  border-color: var(--accent-border);
}

.composer-card {
  border: 1px solid var(--border);
  background: var(--surface);
  border-radius: 20px;
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.06);
  padding: 10px 10px 8px;
}

.composer-card :deep(.el-textarea__inner) {
  border: 0;
  box-shadow: none;
  resize: none;
  min-height: 56px !important;
  background: transparent;
  color: var(--text);
}

.composer-actions {
  margin-top: 4px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.composer-left-actions {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 10px;
}

.helper-text {
  color: var(--text-muted);
  font-size: 0.84rem;
}

.composer-tool-button {
  border: 1px solid var(--border);
  background: var(--surface-solid);
  color: var(--text);
  border-radius: 999px;
  padding: 6px 10px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  font-size: 0.82rem;
  white-space: nowrap;
}

.composer-tool-button:hover {
  border-color: var(--accent-border);
  background: var(--surface-hover);
  color: var(--accent-strong);
}

.attachment-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 6px 2px 2px;
}

.attachment-chip {
  max-width: min(320px, 100%);
  border: 1px solid var(--accent-border);
  background: var(--accent-soft);
  color: var(--accent-strong);
  border-radius: 999px;
  padding: 4px 6px 4px 8px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 0.78rem;
}

.attachment-chip.is-previewable {
  cursor: zoom-in;
}

.attachment-chip.is-previewable:hover {
  border-color: var(--accent-strong);
  background: rgba(204, 251, 241, 0.72);
}

.attachment-chip span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.attachment-chip button {
  width: 18px;
  height: 18px;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: inherit;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}

.attachment-chip button:hover {
  background: rgba(15, 118, 110, 0.14);
}

.attachment-preview-image {
  display: block;
  width: 100%;
  max-height: 72vh;
  object-fit: contain;
  border-radius: 8px;
  background: #f8fafc;
}

.send-btn {
  --el-button-bg-color: #0f766e;
  --el-button-border-color: #0f766e;
  --el-button-hover-bg-color: #0d9488;
  --el-button-hover-border-color: #0d9488;
  --el-button-active-bg-color: #0b6f68;
  --el-button-active-border-color: #0b6f68;
  --el-button-text-color: #fff;
  --el-button-hover-text-color: #fff;
  --el-button-active-text-color: #fff;
  border-radius: 12px;
}

.bubble-row {
  margin-top: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.option-pill {
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text);
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
  border-color: var(--accent-border);
  background: var(--accent-soft);
  color: var(--accent-strong);
}

.option-pill--ghost {
  margin-left: auto;
}

.option-pill--active {
  border-color: var(--accent-border);
  background: var(--surface-active);
  color: var(--accent-strong);
}

.option-pill:hover {
  border-color: var(--accent-border);
  background: var(--surface-hover);
}

.option-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #14b8a6;
}

.option-dot--scope {
  background: #1f9d7a;
}

.option-dot--mode {
  background: #0f766e;
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

.link-btn {
  color: #0f766e;
}

.settings-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.settings-row label {
  font-size: 0.9rem;
  color: var(--text);
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
  color: var(--text);
  font-size: 0.9rem;
}

.scope-field {
  display: grid;
  gap: 8px;
}

.scope-field label {
  font-size: 0.9rem;
  color: var(--text);
}

.scope-number {
  width: 100%;
}

.scope-select,
.scope-tree-select {
  width: 100%;
}

.scope-option {
  display: grid;
  gap: 2px;
}

.scope-option-label {
  display: block;
  line-height: 1.2;
}

.attachment-panel {
  gap: 14px;
}

.attachment-field {
  display: grid;
  gap: 8px;
}

.attachment-field label {
  color: var(--text);
  font-size: 0.88rem;
}

.attachment-image-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
}

.settings-models {
  border-top: 1px solid var(--border);
  padding-top: 10px;
  display: grid;
  gap: 10px;
  max-height: 280px;
  overflow: auto;
}

.settings-block-title {
  margin: 0;
  font-size: 0.9rem;
  color: var(--text-muted);
}

.model-group {
  display: grid;
  gap: 6px;
}

.group-title {
  margin: 0;
  font-size: 0.8rem;
  color: var(--text-muted);
}

.model-item {
  width: 100%;
  border: 1px solid var(--border);
  background: var(--surface-solid);
  border-radius: 10px;
  padding: 8px 10px;
  display: grid;
  gap: 3px;
  text-align: left;
  position: relative;
  cursor: pointer;
}

.model-item:hover {
  border-color: var(--accent-border);
  background: var(--surface-hover);
}

.model-item.selected {
  border-color: var(--accent-border);
  background: var(--surface-active);
}

.model-item.disabled {
  opacity: 0.6;
  cursor: not-allowed;
  background: var(--surface-muted);
}

.model-main {
  color: var(--text);
  font-size: 0.92rem;
  font-weight: 500;
  word-break: break-all;
}

.model-sub {
  color: var(--text-muted);
  font-size: 0.78rem;
  word-break: break-all;
}

.model-check {
  position: absolute;
  right: 10px;
  top: 8px;
  color: #0f766e;
  font-weight: 700;
  font-size: 0.75rem;
}

.hint-line {
  margin: 0;
  color: var(--text-muted);
  font-size: 0.8rem;
}

.error-line {
  color: #b14242;
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
