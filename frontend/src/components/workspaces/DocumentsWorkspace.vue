<script setup lang="ts">
import { computed, ref, watch } from "vue";
import {
  getFileEditableText,
  saveFileEditableText,
  type DocumentInfo,
  type OfficeHealthResponse,
} from "../../api";
import OnlyOfficeHealthPanel from "./OnlyOfficeHealthPanel.vue";
import { useI18n } from "../../composables/useI18n";

const props = defineProps<{
  documents: DocumentInfo[];
  officeHealth: OfficeHealthResponse | null;
  officeHealthLoading: boolean;
  officeHealthError?: string;
  selectedFiles: File[];
  uploading: boolean;
  deletingPath?: string;
}>();

const emit = defineEmits<{
  (event: "files-change", files: File[]): void;
  (event: "upload"): void;
  (event: "open-document", path: string): void;
  (event: "open-office-editor", path: string): void;
  (event: "delete-document", path: string): void;
  (event: "document-saved", path: string): void;
  (event: "refresh-office-health"): void;
}>();

const fileInputRef = ref<HTMLInputElement | null>(null);
const { locale, t } = useI18n();
const editDialogVisible = ref(false);
const editLoading = ref(false);
const editSaving = ref(false);
const editError = ref("");
const editPath = ref("");
const editEncoding = ref("utf-8");
const editContent = ref("");
const editOriginalContent = ref("");

const EDITABLE_TEXT_EXTENSIONS = new Set([
  ".txt",
  ".md",
  ".markdown",
  ".csv",
  ".tsv",
  ".json",
  ".jsonl",
  ".yaml",
  ".yml",
  ".xml",
  ".ini",
  ".cfg",
  ".conf",
  ".toml",
  ".log",
  ".rst",
  ".rtf",
  ".sql",
  ".py",
  ".js",
  ".ts",
  ".jsx",
  ".tsx",
  ".java",
  ".c",
  ".cpp",
  ".h",
  ".hpp",
  ".go",
  ".rs",
  ".sh",
  ".bat",
  ".ps1",
]);
const OFFICE_PRO_EDITOR_EXTENSIONS = new Set([
  ".doc",
  ".docx",
  ".xls",
  ".xlsx",
  ".xlsm",
]);

const selectedFileNames = computed(() => props.selectedFiles.map((file) => file.name));
const canSaveEdit = computed(() => !editLoading.value && !editSaving.value);
const editDirty = computed(() => editContent.value !== editOriginalContent.value);

watch(
  () => props.selectedFiles.length,
  (size) => {
    if (size === 0 && fileInputRef.value) {
      fileInputRef.value.value = "";
    }
  },
);

function onSelectFiles(event: Event) {
  const input = event.target as HTMLInputElement;
  const files = input.files ? Array.from(input.files) : [];
  emit("files-change", files);
}

function formatDateTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString(locale.value, { hour12: false });
}

function formatBytes(bytes: number) {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function openDocument(path: string) {
  emit("open-document", path);
}

function deleteDocument(path: string) {
  emit("delete-document", path);
}

function isEditableDocument(doc: DocumentInfo): boolean {
  return EDITABLE_TEXT_EXTENSIONS.has((doc.extension || "").toLowerCase());
}

function isOfficeProEditableDocument(doc: DocumentInfo): boolean {
  return OFFICE_PRO_EDITOR_EXTENSIONS.has((doc.extension || "").toLowerCase());
}

function openOfficeEditor(path: string) {
  emit("open-office-editor", path);
}

async function openEditDialog(doc: DocumentInfo) {
  if (!isEditableDocument(doc)) {
    return;
  }

  editDialogVisible.value = true;
  editLoading.value = true;
  editSaving.value = false;
  editError.value = "";
  editPath.value = doc.path;
  editContent.value = "";
  editOriginalContent.value = "";
  editEncoding.value = "utf-8";

  try {
    const payload = await getFileEditableText(doc.path);
    editPath.value = payload.path;
    editEncoding.value = payload.encoding || "utf-8";
    editContent.value = payload.content || "";
    editOriginalContent.value = payload.content || "";
  } catch (error) {
    editError.value = error instanceof Error ? error.message : t("documents.edit_load_failed");
  } finally {
    editLoading.value = false;
  }
}

function closeEditDialog() {
  editDialogVisible.value = false;
  editLoading.value = false;
  editSaving.value = false;
  editError.value = "";
  editPath.value = "";
  editContent.value = "";
  editOriginalContent.value = "";
  editEncoding.value = "utf-8";
}

async function saveEditedDocument() {
  if (!editPath.value) {
    return;
  }
  editSaving.value = true;
  editError.value = "";
  try {
    await saveFileEditableText(editPath.value, editContent.value);
    editOriginalContent.value = editContent.value;
    emit("document-saved", editPath.value);
  } catch (error) {
    editError.value = error instanceof Error ? error.message : t("documents.edit_save_failed");
  } finally {
    editSaving.value = false;
  }
}
</script>

<template>
  <section class="workspace-standard">
    <header class="workspace-head">
      <div>
        <h2>{{ t("documents.title") }}</h2>
        <p>{{ t("documents.subtitle") }}</p>
      </div>
    </header>

    <OnlyOfficeHealthPanel
      :health="officeHealth"
      :loading="officeHealthLoading"
      :error="officeHealthError"
      @refresh="$emit('refresh-office-health')"
    />

    <section class="tool-card">
      <div class="upload-line">
        <label class="file-picker">
          <input
            ref="fileInputRef"
            type="file"
            multiple
            @change="onSelectFiles"
          />
          <span>{{ t("documents.select_files") }}</span>
        </label>

        <el-button
          type="primary"
          :loading="uploading"
          :disabled="!selectedFiles.length"
          @click="$emit('upload')"
        >
          {{ t("documents.upload_rebuild") }}
        </el-button>
      </div>

      <div v-if="selectedFileNames.length" class="file-tags">
        <el-tag
          v-for="name in selectedFileNames"
          :key="name"
          type="info"
          effect="plain"
        >
          {{ name }}
        </el-tag>
      </div>
    </section>

    <section class="list-card">
      <article v-for="doc in documents" :key="doc.path" class="list-item">
        <div class="item-main">
          <div class="doc-meta-block">
            <button class="doc-link" type="button" @click="openDocument(doc.path)">{{ doc.path }}</button>
            <div class="doc-submeta">
              <el-tag size="small" type="info">{{ doc.extension }}</el-tag>
              <small>{{ formatBytes(doc.size_bytes) }}</small>
              <small>{{ formatDateTime(doc.modified_at) }}</small>
            </div>
          </div>

          <div class="item-actions">
            <el-button size="small" text type="primary" @click="openDocument(doc.path)">{{ t("documents.open") }}</el-button>
            <el-button
              v-if="isOfficeProEditableDocument(doc)"
              size="small"
              text
              type="warning"
              @click="openOfficeEditor(doc.path)"
            >
              {{ t("documents.office_edit") }}
            </el-button>
            <el-button
              v-if="isEditableDocument(doc)"
              size="small"
              text
              type="success"
              @click="openEditDialog(doc)"
            >
              {{ t("documents.edit") }}
            </el-button>
            <el-popconfirm
              :title="t('documents.delete_confirm_title')"
              :confirm-button-text="t('documents.delete_confirm_button')"
              :cancel-button-text="t('documents.delete_cancel_button')"
              width="220"
              @confirm="deleteDocument(doc.path)"
            >
              <template #reference>
                <el-button
                  size="small"
                  text
                  type="danger"
                  :loading="deletingPath === doc.path"
                >
                  {{ t("documents.delete") }}
                </el-button>
              </template>
            </el-popconfirm>
          </div>
        </div>
      </article>

      <el-empty
        v-if="!documents.length"
        :description="t('documents.empty')"
      />
    </section>

    <el-dialog
      v-model="editDialogVisible"
      width="80%"
      top="5vh"
      append-to-body
      :title="t('documents.edit_dialog_title')"
      @closed="closeEditDialog"
    >
      <section class="edit-dialog-body">
        <p class="edit-tip">{{ t("documents.edit_tip") }}</p>
        <div class="edit-meta">
          <span class="edit-path">{{ editPath }}</span>
          <el-tag size="small" type="info">{{ t("documents.edit_encoding", { encoding: editEncoding }) }}</el-tag>
          <el-tag size="small" :type="editDirty ? 'warning' : 'success'">
            {{ editDirty ? t("documents.edit_unsaved") : t("documents.edit_saved") }}
          </el-tag>
        </div>

        <el-alert
          v-if="editError"
          :title="editError"
          type="error"
          show-icon
          :closable="false"
        />

        <el-skeleton v-if="editLoading" :rows="8" animated />

        <el-input
          v-else
          v-model="editContent"
          type="textarea"
          :autosize="{ minRows: 20, maxRows: 28 }"
          class="edit-textarea"
        />
      </section>

      <template #footer>
        <span class="dialog-footer">
          <el-button @click="editDialogVisible = false">{{ t("documents.cancel") }}</el-button>
          <el-button
            type="primary"
            :loading="editSaving"
            :disabled="!canSaveEdit || !editDirty"
            @click="saveEditedDocument"
          >
            {{ t("documents.save") }}
          </el-button>
        </span>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.workspace-standard {
  height: 100%;
  min-height: 0;
  overflow: auto;
}

.workspace-head {
  padding: 18px 24px 12px;
}

.workspace-head h2 {
  margin: 0;
  font-size: 1.18rem;
}

.workspace-head p {
  margin: 4px 0 0;
  color: #6b7280;
  font-size: 0.9rem;
}

.tool-card,
.list-card {
  margin: 0 24px 18px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 16px;
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.06);
}

.tool-card {
  padding: 16px;
}

.upload-line {
  display: flex;
  align-items: center;
  gap: 10px;
}

.file-picker {
  display: inline-flex;
  align-items: center;
  min-height: 38px;
  padding: 0 12px;
  border-radius: 10px;
  border: 1px solid #e5e7eb;
  background: #fff;
  cursor: pointer;
}

.file-picker input {
  display: none;
}

.file-tags {
  margin-top: 12px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.list-card {
  padding: 12px;
  min-height: 280px;
}

.list-item {
  border: 1px solid #eef0f3;
  border-radius: 12px;
  padding: 10px 11px;
  margin-bottom: 8px;
}

.item-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.doc-meta-block {
  min-width: 0;
  display: grid;
  gap: 6px;
}

.doc-submeta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.item-actions {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.doc-link {
  border: 0;
  padding: 0;
  background: transparent;
  color: #0f172a;
  font-size: 0.95rem;
  font-weight: 650;
  text-align: left;
  cursor: pointer;
}

.doc-link:hover {
  color: #0f766e;
}

.doc-submeta small {
  color: #6b7280;
  font-size: 0.83rem;
}

.edit-dialog-body {
  display: grid;
  gap: 10px;
}

.edit-tip {
  margin: 0;
  font-size: 0.9rem;
  color: #475569;
}

.edit-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.edit-path {
  font-size: 0.86rem;
  color: #334155;
  word-break: break-all;
}

.edit-textarea :deep(.el-textarea__inner) {
  font-family: "JetBrains Mono", "Consolas", "Courier New", monospace;
  line-height: 1.45;
}

@media (max-width: 720px) {
  .workspace-head {
    padding-left: 12px;
    padding-right: 12px;
  }

  .tool-card,
  .list-card {
    margin-left: 12px;
    margin-right: 12px;
  }

  .upload-line {
    flex-direction: column;
    align-items: stretch;
  }

  .item-main {
    flex-direction: column;
    align-items: flex-start;
  }

  .item-actions {
    width: 100%;
    justify-content: flex-end;
  }

  .edit-meta {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
