<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { DocumentInfo } from "../../api";

const props = defineProps<{
  documents: DocumentInfo[];
  selectedFiles: File[];
  uploading: boolean;
  deletingPath?: string;
}>();

const emit = defineEmits<{
  (event: "files-change", files: File[]): void;
  (event: "upload"): void;
  (event: "open-document", path: string): void;
  (event: "delete-document", path: string): void;
}>();

const fileInputRef = ref<HTMLInputElement | null>(null);

const selectedFileNames = computed(() => props.selectedFiles.map((file) => file.name));

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
  return date.toLocaleString("zh-CN", { hour12: false });
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
</script>

<template>
  <section class="workspace-standard">
    <header class="workspace-head">
      <div>
        <h2>Document Management</h2>
        <p>Upload source files and inspect currently indexed documents.</p>
      </div>
    </header>

    <section class="tool-card">
      <div class="upload-line">
        <label class="file-picker">
          <input
            ref="fileInputRef"
            type="file"
            multiple
            @change="onSelectFiles"
          />
          <span>Select Files</span>
        </label>

        <el-button
          type="primary"
          :loading="uploading"
          :disabled="!selectedFiles.length"
          @click="$emit('upload')"
        >
          Upload and Rebuild
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
            <el-button size="small" text type="primary" @click="openDocument(doc.path)">Open</el-button>
            <el-popconfirm
              title="Delete this file?"
              confirm-button-text="Delete"
              cancel-button-text="Cancel"
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
                  Delete
                </el-button>
              </template>
            </el-popconfirm>
          </div>
        </div>
      </article>

      <el-empty
        v-if="!documents.length"
        description="No documents found yet."
      />
    </section>
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
}
</style>
