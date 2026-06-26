<script setup lang="ts">
import { computed, ref, watch } from "vue";
import {
  CircleCheckFilled,
  CircleCloseFilled,
  Delete,
  Document as DocumentIcon,
  EditPen,
  Folder,
  FolderAdd,
  FolderOpened,
  Loading,
  MoreFilled,
  Open,
  Setting,
  Upload,
} from "@element-plus/icons-vue";
import {
  getFileEditableText,
  saveFileEditableText,
  type DocumentInfo,
  type OfficeHealthResponse,
} from "../../api";
import OnlyOfficeHealthPanel from "./OnlyOfficeHealthPanel.vue";
import { useI18n } from "../../composables/useI18n";
import { isEditableTextDocument, isOnlyOfficeDocument } from "../../utils/documentRouting";

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
  (event: "upload", folderPath?: string, parentId?: number | null): void;
  (event: "create-folder", parentPath: string, name: string, parentId?: number | null): void;
  (event: "open-document", path: string): void;
  (event: "open-office-editor", path: string): void;
  (event: "delete-document", path: string): void;
  (event: "delete-folder", path: string): void;
  (event: "document-saved", path: string): void;
  (event: "refresh-office-health"): void;
}>();

type BreadcrumbItem = {
  label: string;
  path: string;
};

type FolderItem = DocumentInfo & {
  name: string;
  parentPath: string;
  childFolderCount: number;
  childFileCount: number;
};

type FileItem = DocumentInfo & {
  name: string;
  parentPath: string;
};

type BrowserListItem = {
  kind: "folder" | "file";
  key: string;
  name: string;
  path: string;
  parentPath: string;
  modifiedAt: string;
  typeLabel: string;
  sizeLabel: string;
  folder?: FolderItem;
  doc?: FileItem;
};

type TreeFolderItem = FolderItem & {
  depth: number;
};

type NormalizedDocument = DocumentInfo & {
  visiblePath: string;
  visibleParentPath: string;
  is_directory: boolean;
};

const fileInputRef = ref<HTMLInputElement | null>(null);
const { locale, t } = useI18n();
const currentFolderPath = ref("");
const officeHealthDialogVisible = ref(false);
const createFolderDialogVisible = ref(false);
const createFolderName = ref("");
const editDialogVisible = ref(false);
const editLoading = ref(false);
const editSaving = ref(false);
const editError = ref("");
const editPath = ref("");
const editEncoding = ref("utf-8");
const editContent = ref("");
const editOriginalContent = ref("");
const editDialogFullscreen = ref(false);

const selectedFileNames = computed(() => props.selectedFiles.map((file) => file.name));
const canSaveEdit = computed(() => !editLoading.value && !editSaving.value);
const editDirty = computed(() => editContent.value !== editOriginalContent.value);
const deletingActive = computed(() => Boolean(props.deletingPath));

function normalizePath(path: string) {
  return path.replace(/\\/g, "/").replace(/^\/+|\/+$/g, "");
}

function parentPathOf(path: string) {
  const normalized = normalizePath(path);
  const index = normalized.lastIndexOf("/");
  return index >= 0 ? normalized.slice(0, index) : "";
}

function folderParentPath(path: string) {
  const normalized = normalizePath(path);
  return parentPathOf(normalized);
}

function basenameOf(path: string) {
  const normalized = normalizePath(path);
  return normalized.split("/").filter(Boolean).pop() || normalized;
}

function displayFolderName(path: string) {
  if (!path) {
    return "我的文档";
  }
  return basenameOf(path);
}

function formatVisiblePath(path: string) {
  const normalized = normalizePath(path);
  if (!normalized) {
    return "我的文档";
  }
  return normalized;
}

const normalizedDocuments = computed<NormalizedDocument[]>(() =>
  props.documents.map((item) => {
    const path = normalizePath(item.path);
    const visiblePath = normalizePath(item.display_path || item.path);
    return {
      ...item,
      path,
      visiblePath,
      visibleParentPath: folderParentPath(visiblePath),
      is_directory: Boolean(item.is_directory),
    };
  }),
);

const directoryItems = computed<FolderItem[]>(() => {
  const directories = new Map<string, NormalizedDocument>();

  for (const doc of normalizedDocuments.value) {
    if (doc.is_directory) {
      directories.set(doc.visiblePath, { ...doc });
      continue;
    }

    const segments = doc.visiblePath.split("/").filter(Boolean);
    for (let index = 1; index < segments.length; index += 1) {
      const folderPath = segments.slice(0, index).join("/");
      if (!directories.has(folderPath)) {
        directories.set(folderPath, {
          path: folderPath,
          visiblePath: folderPath,
          visibleParentPath: folderParentPath(folderPath),
          size_bytes: 0,
          modified_at: doc.modified_at,
          extension: "",
          is_directory: true,
        });
      }
    }
  }

  const folderPaths = Array.from(directories.keys());
  return Array.from(directories.values())
    .map((item) => {
      const path = normalizePath(item.visiblePath || item.path);
      const parentPath = folderParentPath(path);
      return {
        ...item,
        path,
        visiblePath: path,
        visibleParentPath: parentPath,
        name: displayFolderName(path),
        parentPath,
        childFolderCount: folderPaths.filter((candidate) => folderParentPath(candidate) === path).length,
        childFileCount: normalizedDocuments.value.filter(
          (doc) => !doc.is_directory && doc.visibleParentPath === path,
        ).length,
      };
    })
    .sort((left, right) => left.name.localeCompare(right.name, locale.value));
});

const treeFolderItems = computed<TreeFolderItem[]>(() => {
  const childrenByParent = new Map<string, FolderItem[]>();

  for (const folder of directoryItems.value) {
    const parentPath = normalizePath(folder.parentPath);
    const children = childrenByParent.get(parentPath) ?? [];
    children.push(folder);
    childrenByParent.set(parentPath, children);
  }

  for (const children of childrenByParent.values()) {
    children.sort((left, right) => left.name.localeCompare(right.name, locale.value));
  }

  const flattened: TreeFolderItem[] = [];
  const visited = new Set<string>();

  function appendChildren(parentPath: string, depth: number) {
    const children = childrenByParent.get(parentPath) ?? [];
    for (const child of children) {
      if (visited.has(child.path)) {
        continue;
      }
      visited.add(child.path);
      flattened.push({ ...child, depth });
      appendChildren(child.path, depth + 1);
    }
  }

  appendChildren("", 1);

  return flattened;
});

const currentFolder = computed(() => normalizePath(currentFolderPath.value));

const breadcrumbs = computed<BreadcrumbItem[]>(() => {
  const current = currentFolder.value;
  const items: BreadcrumbItem[] = [{ label: "我的文档", path: "" }];
  if (!current) {
    return items;
  }

  const segments = current.split("/").filter(Boolean);
  for (let index = 0; index < segments.length; index += 1) {
    const path = segments.slice(0, index + 1).join("/");
    items.push({
      label: segments[index],
      path,
    });
  }
  return items;
});

const visibleFolders = computed(() =>
  directoryItems.value.filter((item) => item.parentPath === currentFolder.value),
);

const visibleFiles = computed<FileItem[]>(() =>
  normalizedDocuments.value
    .filter((doc) => !doc.is_directory && doc.visibleParentPath === currentFolder.value)
    .map((doc) => ({
      ...doc,
      name: doc.name || basenameOf(doc.visiblePath),
      parentPath: doc.visibleParentPath,
    }))
    .sort((left, right) => left.name.localeCompare(right.name, locale.value)),
);

const browserListItems = computed<BrowserListItem[]>(() => [
  ...visibleFolders.value.map((folder) => ({
    kind: "folder" as const,
    key: `folder:${folder.path}`,
    name: folder.name,
    path: folder.path,
    parentPath: folder.parentPath,
    modifiedAt: folder.modified_at,
    typeLabel: "文件夹",
    sizeLabel: "-",
    folder,
  })),
  ...visibleFiles.value.map((doc) => ({
    kind: "file" as const,
    key: `file:${doc.path}`,
    name: doc.name,
    path: doc.path,
    parentPath: doc.parentPath,
    modifiedAt: doc.modified_at,
    typeLabel: doc.extension || "文件",
    sizeLabel: formatBytes(doc.size_bytes),
    doc,
  })),
]);

const currentUploadFolderPath = computed(() => {
  return currentFolder.value;
});

const currentFolderItem = computed(() =>
  directoryItems.value.find((item) => item.path === currentFolder.value) ?? null,
);
const currentUploadFolderId = computed(() => currentFolderItem.value?.folder_id ?? null);
const uploadTargetLabel = computed(() => formatVisiblePath(currentUploadFolderPath.value));
const hasCurrentItems = computed(() => browserListItems.value.length > 0);
const officeHealthOk = computed(
  () =>
    !props.officeHealthError &&
    Boolean(props.officeHealth?.configured) &&
    Boolean(props.officeHealth?.document_server_reachable) &&
    props.officeHealth?.jwt_match !== false &&
    props.officeHealth?.callback_reachable !== false,
);
const officeHealthProblem = computed(
  () =>
    Boolean(props.officeHealthError) ||
    Boolean(
      props.officeHealth &&
        (!props.officeHealth.configured ||
          !props.officeHealth.document_server_reachable ||
          props.officeHealth.jwt_match === false ||
          props.officeHealth.callback_reachable === false),
    ),
);
const officeHealthLabel = computed(() => {
  if (officeHealthOk.value) {
    return "ONLYOFFICE 正常";
  }
  if (officeHealthProblem.value) {
    return "ONLYOFFICE 需要检查";
  }
  return "ONLYOFFICE 健康检查";
});

watch(
  () => props.selectedFiles.length,
  (size) => {
    if (size === 0 && fileInputRef.value) {
      fileInputRef.value.value = "";
    }
  },
);

watch(
  () => props.documents,
  () => {
    if (!currentFolder.value) {
      return;
    }
    const exists = directoryItems.value.some((item) => item.path === currentFolder.value);
    if (!exists) {
      currentFolderPath.value = folderParentPath(currentFolder.value);
    }
  },
  { deep: true },
);

function onSelectFiles(event: Event) {
  const input = event.target as HTMLInputElement;
  const files = input.files ? Array.from(input.files) : [];
  emit("files-change", files);
}

function formatDateTime(value: string) {
  if (!value) {
    return "";
  }
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

function openBrowserItem(item: BrowserListItem) {
  if (item.folder) {
    openFolder(item.folder.path);
    return;
  }
  if (item.doc) {
    openDocument(item.doc.path);
  }
}

function browserItemCanUseOffice(item: BrowserListItem) {
  return Boolean(item.doc && isOfficeProEditableDocument(item.doc));
}

function browserItemCanEditText(item: BrowserListItem) {
  return Boolean(item.doc && isEditableDocument(item.doc));
}

function openBrowserItemInOffice(item: BrowserListItem) {
  if (item.doc) {
    openOfficeEditor(item.doc.path);
  }
}

function openBrowserItemTextEditor(item: BrowserListItem) {
  if (item.doc) {
    void openEditDialog(item.doc);
  }
}

function deleteBrowserItem(item: BrowserListItem) {
  if (item.doc) {
    deleteDocument(item.doc.path);
    return;
  }
  if (item.folder) {
    deleteFolder(item.folder.path);
  }
}

function handleBrowserFolderCommand(command: string, item: BrowserListItem) {
  if (item.folder) {
    handleFolderCommand(command, item.folder);
  }
}

function handleBrowserFileCommand(command: string, item: BrowserListItem) {
  if (item.doc) {
    handleFileCommand(command, item.doc);
  }
}

function deleteDocument(path: string) {
  emit("delete-document", path);
}

function deleteFolder(path: string) {
  emit("delete-folder", path);
}

function openFolder(path: string) {
  currentFolderPath.value = normalizePath(path);
}

function goToFolder(path: string) {
  currentFolderPath.value = normalizePath(path);
}

function uploadToCurrentFolder() {
  emit("upload", currentUploadFolderPath.value, currentUploadFolderId.value);
}

function uploadToFolder(folderPath: string) {
  const targetPath = normalizePath(folderPath);
  const folder = directoryItems.value.find((item) => item.path === targetPath) ?? null;
  emit("upload", targetPath, folder?.folder_id ?? null);
}

function openCreateFolderDialog() {
  createFolderName.value = "";
  createFolderDialogVisible.value = true;
}

function openCreateFolderDialogAt(folderPath: string) {
  currentFolderPath.value = normalizePath(folderPath);
  createFolderName.value = "";
  createFolderDialogVisible.value = true;
}

function submitCreateFolder() {
  const name = createFolderName.value.trim();
  if (!name) {
    return;
  }
  emit("create-folder", currentUploadFolderPath.value, name, currentUploadFolderId.value);
  createFolderDialogVisible.value = false;
}

function openOfficeHealthDialog() {
  officeHealthDialogVisible.value = true;
}

function closeOfficeHealthDialog() {
  officeHealthDialogVisible.value = false;
}

function isEditableDocument(doc: DocumentInfo): boolean {
  return isEditableTextDocument(doc.extension || doc.path);
}

function isOfficeProEditableDocument(doc: DocumentInfo): boolean {
  return isOnlyOfficeDocument(doc.extension || doc.path);
}

function openOfficeEditor(path: string) {
  emit("open-office-editor", path);
}

function handleFolderCommand(command: string, folder: FolderItem) {
  if (command === "open") {
    openFolder(folder.path);
    return;
  }
  if (command === "upload") {
    uploadToFolder(folder.path);
    return;
  }
  if (command === "create") {
    openCreateFolderDialogAt(folder.path);
    return;
  }
  if (command === "delete") {
    deleteFolder(folder.path);
  }
}

function handleFileCommand(command: string, doc: FileItem) {
  if (command === "open") {
    openDocument(doc.path);
    return;
  }
  if (command === "office") {
    openOfficeEditor(doc.path);
    return;
  }
  if (command === "edit") {
    void openEditDialog(doc);
    return;
  }
  if (command === "delete") {
    deleteDocument(doc.path);
  }
}

async function openEditDialog(doc: DocumentInfo) {
  if (!isEditableDocument(doc)) {
    return;
  }

  editDialogFullscreen.value = false;
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
  editDialogFullscreen.value = false;
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

function toggleEditDialogFullscreen() {
  editDialogFullscreen.value = !editDialogFullscreen.value;
}
</script>

<template>
  <section class="workspace-standard">
    <header class="file-manager-head">
      <div class="head-title">
        <div class="title-row">
          <h2>{{ t("documents.title") }}</h2>
          <span class="head-kicker">Documents</span>
        </div>
        <p>管理知识库文件，围绕当前目录完成上传、打开、编辑和删除。</p>
      </div>

      <div class="head-actions">
        <el-tooltip :content="officeHealthLabel" placement="bottom">
          <el-button
            class="health-icon-button"
            circle
            :loading="officeHealthLoading"
            @click="openOfficeHealthDialog"
          >
            <el-icon v-if="officeHealthOk"><CircleCheckFilled /></el-icon>
            <el-icon v-else-if="officeHealthProblem"><CircleCloseFilled /></el-icon>
            <el-icon v-else><Setting /></el-icon>
          </el-button>
        </el-tooltip>
      </div>
    </header>

    <section class="file-manager-shell">
      <div class="command-bar">
        <div class="command-group">
          <label class="command-button file-picker">
            <input
              ref="fileInputRef"
              type="file"
              multiple
              @change="onSelectFiles"
            />
            <el-icon><Upload /></el-icon>
            <span>{{ t("documents.select_files") }}</span>
          </label>

          <el-button
            type="primary"
            :icon="Upload"
            :loading="uploading"
            :disabled="!selectedFiles.length"
            @click="uploadToCurrentFolder"
          >
            {{ t("documents.upload_rebuild") }}
          </el-button>

          <el-button :icon="FolderAdd" @click="openCreateFolderDialog">
            新建文件夹
          </el-button>
        </div>

        <div class="command-meta">
          <span v-if="deletingActive" class="deleting-pill">
            <el-icon class="is-spinning"><Loading /></el-icon>
            删除中...
          </span>
          <span>{{ visibleFolders.length }} 个文件夹</span>
          <span>{{ visibleFiles.length }} 个文件</span>
        </div>
      </div>

      <div v-if="selectedFileNames.length" class="selected-file-strip">
        <span class="selected-label">待上传</span>
        <el-tag
          v-for="name in selectedFileNames"
          :key="name"
          type="info"
          effect="plain"
          round
        >
          {{ name }}
        </el-tag>
      </div>

      <div class="browser-layout">
        <aside class="folder-rail">
          <div class="rail-title">目录</div>
          <div class="tree-list">
            <button
              class="tree-node"
              :class="{ 'is-active': !currentFolder, 'is-root': true }"
              type="button"
              @click="goToFolder('')"
            >
              <el-icon><FolderOpened /></el-icon>
              <span>我的文档</span>
            </button>

            <button
              v-for="folder in treeFolderItems"
              :key="folder.path"
              class="tree-node"
              :class="{ 'is-active': currentFolder === folder.path }"
              type="button"
              :style="{ paddingLeft: `${14 + folder.depth * 18}px` }"
              @click="goToFolder(folder.path)"
            >
              <el-icon><Folder /></el-icon>
              <span>{{ folder.name }}</span>
            </button>
          </div>
        </aside>

        <main class="browser-main">
          <div class="browser-toolbar">
            <div class="breadcrumb-row">
              <button
                v-for="(item, index) in breadcrumbs"
                :key="item.path || 'root'"
                class="breadcrumb-button"
                type="button"
                @click="goToFolder(item.path)"
              >
                <span>{{ item.label }}</span>
                <span v-if="index < breadcrumbs.length - 1" class="breadcrumb-separator">/</span>
              </button>
            </div>
            <div class="toolbar-summary">
              {{ visibleFolders.length }} folders · {{ visibleFiles.length }} files
            </div>
          </div>

          <div v-if="browserListItems.length" class="explorer-list">
            <div class="explorer-list-head">
              <span>名称</span>
              <span>修改时间</span>
              <span>类型</span>
              <span>大小</span>
              <span>操作</span>
            </div>

            <article
              v-for="item in browserListItems"
              :key="item.key"
              class="explorer-row"
              :class="{ 'is-folder': item.kind === 'folder', 'is-deleting': deletingPath === item.path }"
              @dblclick="openBrowserItem(item)"
            >
              <div class="explorer-name-cell">
                <button class="explorer-name-button" type="button" @click="openBrowserItem(item)">
                  <el-icon class="explorer-item-icon">
                    <FolderOpened v-if="item.kind === 'folder'" />
                    <DocumentIcon v-else />
                  </el-icon>
                  <span>{{ item.name }}</span>
                </button>
                <span v-if="deletingPath === item.path" class="row-status">
                  <el-icon class="is-spinning"><Loading /></el-icon>
                  正在删除
                </span>
              </div>

              <span class="explorer-date-cell">
                {{ item.modifiedAt ? formatDateTime(item.modifiedAt) : "-" }}
              </span>
              <span class="explorer-type-cell">{{ item.typeLabel }}</span>
              <span class="explorer-size-cell">{{ item.sizeLabel }}</span>

              <div v-if="item.kind === 'folder'" class="item-actions">
                <el-tooltip content="打开文件夹" placement="top">
                  <button
                    class="icon-action"
                    type="button"
                    :disabled="deletingActive"
                    @click="openBrowserItem(item)"
                  >
                    <el-icon><Open /></el-icon>
                  </button>
                </el-tooltip>

                <el-popconfirm
                  title="删除文件夹会同时删除里面的文件和子文件夹，确认删除吗？"
                  confirm-button-text="删除"
                  cancel-button-text="取消"
                  width="260"
                  @confirm="deleteBrowserItem(item)"
                >
                  <template #reference>
                    <button
                      class="icon-action is-danger"
                      type="button"
                      :disabled="deletingActive"
                    >
                      <el-icon :class="{ 'is-spinning': deletingPath === item.path }">
                        <Loading v-if="deletingPath === item.path" />
                        <Delete v-else />
                      </el-icon>
                    </button>
                  </template>
                </el-popconfirm>

                <el-dropdown
                  trigger="click"
                  @command="handleBrowserFolderCommand(String($event), item)"
                >
                  <button class="icon-action" type="button" :disabled="deletingActive" @click.stop>
                    <el-icon><MoreFilled /></el-icon>
                  </button>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item command="open" :icon="Open">打开</el-dropdown-item>
                      <el-dropdown-item command="upload" :icon="Upload" :disabled="!selectedFiles.length">
                        上传到这里
                      </el-dropdown-item>
                      <el-dropdown-item command="create" :icon="FolderAdd">新建子文件夹</el-dropdown-item>
                      <el-dropdown-item command="delete" :icon="Delete">删除文件夹</el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
              </div>

              <div v-else class="item-actions">
                <el-tooltip :content="t('documents.open')" placement="top">
                  <button
                    class="icon-action"
                    type="button"
                    :disabled="deletingActive"
                    @click="openBrowserItem(item)"
                  >
                    <el-icon><Open /></el-icon>
                  </button>
                </el-tooltip>

                <el-tooltip
                  v-if="browserItemCanUseOffice(item)"
                  :content="t('documents.office_edit')"
                  placement="top"
                >
                  <button
                    class="icon-action is-warning"
                    type="button"
                    :disabled="deletingActive"
                    @click="openBrowserItemInOffice(item)"
                  >
                    <el-icon><EditPen /></el-icon>
                  </button>
                </el-tooltip>

                <el-tooltip
                  v-if="browserItemCanEditText(item)"
                  :content="t('documents.edit')"
                  placement="top"
                >
                  <button
                    class="icon-action is-success"
                    type="button"
                    :disabled="deletingActive"
                    @click="openBrowserItemTextEditor(item)"
                  >
                    <el-icon><EditPen /></el-icon>
                  </button>
                </el-tooltip>

                <el-popconfirm
                  :title="t('documents.delete_confirm_title')"
                  :confirm-button-text="t('documents.delete_confirm_button')"
                  :cancel-button-text="t('documents.delete_cancel_button')"
                  width="220"
                  @confirm="deleteBrowserItem(item)"
                >
                  <template #reference>
                    <button
                      class="icon-action is-danger"
                      type="button"
                      :disabled="deletingActive"
                    >
                      <el-icon :class="{ 'is-spinning': deletingPath === item.path }">
                        <Loading v-if="deletingPath === item.path" />
                        <Delete v-else />
                      </el-icon>
                    </button>
                  </template>
                </el-popconfirm>

                <el-dropdown
                  trigger="click"
                  @command="handleBrowserFileCommand(String($event), item)"
                >
                  <button class="icon-action" type="button" :disabled="deletingActive" @click.stop>
                    <el-icon><MoreFilled /></el-icon>
                  </button>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item command="open" :icon="Open">{{ t("documents.open") }}</el-dropdown-item>
                      <el-dropdown-item
                        v-if="browserItemCanUseOffice(item)"
                        command="office"
                        :icon="EditPen"
                      >
                        {{ t("documents.office_edit") }}
                      </el-dropdown-item>
                      <el-dropdown-item
                        v-if="browserItemCanEditText(item)"
                        command="edit"
                        :icon="EditPen"
                      >
                        {{ t("documents.edit") }}
                      </el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
              </div>
            </article>
          </div>

          <el-empty
            v-if="!hasCurrentItems"
            class="document-empty"
            :description="t('documents.empty')"
          />
        </main>
      </div>
    </section>

    <el-dialog
      v-model="officeHealthDialogVisible"
      title="ONLYOFFICE 健康检查"
      width="760px"
      append-to-body
      @closed="closeOfficeHealthDialog"
    >
      <OnlyOfficeHealthPanel
        compact
        :health="officeHealth"
        :loading="officeHealthLoading"
        :error="officeHealthError"
        @refresh="$emit('refresh-office-health')"
      />
    </el-dialog>

    <el-dialog
      v-model="createFolderDialogVisible"
      title="新建文件夹"
      width="420px"
      append-to-body
    >
      <div class="create-folder-body">
        <p>创建位置：{{ uploadTargetLabel }}</p>
        <el-input
          v-model="createFolderName"
          placeholder="文件夹名称"
          maxlength="128"
          show-word-limit
          @keyup.enter="submitCreateFolder"
        />
      </div>
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="createFolderDialogVisible = false">{{ t("documents.cancel") }}</el-button>
          <el-button
            type="primary"
            :disabled="!createFolderName.trim()"
            @click="submitCreateFolder"
          >
            创建
          </el-button>
        </span>
      </template>
    </el-dialog>

    <el-dialog
      v-model="editDialogVisible"
      :fullscreen="editDialogFullscreen"
      :width="editDialogFullscreen ? '100%' : '80%'"
      :top="editDialogFullscreen ? '0' : '5vh'"
      append-to-body
      class="edit-dialog"
      @closed="closeEditDialog"
    >
      <template #header>
        <div class="dialog-head">
          <span class="dialog-title">{{ t("documents.edit_dialog_title") }}</span>
          <button
            type="button"
            class="dialog-tool-btn dialog-tool-icon-btn"
            :title="editDialogFullscreen ? t('viewer.exit_fullscreen') : t('viewer.fullscreen')"
            @click="toggleEditDialogFullscreen"
          >
            <svg
              v-if="!editDialogFullscreen"
              class="dialog-tool-icon"
              viewBox="0 0 20 20"
              aria-hidden="true"
            >
              <path d="M4 8V4h4M12 4h4v4M16 12v4h-4M8 16H4v-4"></path>
            </svg>
            <svg
              v-else
              class="dialog-tool-icon"
              viewBox="0 0 20 20"
              aria-hidden="true"
            >
              <path d="M8 4H4v4M12 4h4v4M4 12v4h4M16 12v4h-4"></path>
              <path d="M8 8L4 4M12 8l4-4M8 12l-4 4M12 12l4 4"></path>
            </svg>
          </button>
        </div>
      </template>

      <section class="edit-dialog-body" :class="{ 'is-fullscreen': editDialogFullscreen }">
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
          :autosize="!editDialogFullscreen ? { minRows: 20, maxRows: 28 } : false"
          :rows="editDialogFullscreen ? 1 : 20"
          class="edit-textarea"
          :class="{ 'is-fullscreen': editDialogFullscreen }"
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
  --surface: #ffffff;
  --surface-subtle: #fbfbfc;
  --surface-hover: #f4f4f5;
  --border: #dedee3;
  --border-subtle: #eeeef1;
  --text: #111827;
  --text-muted: #6b7280;
  --text-soft: #9ca3af;
  --accent: #2563eb;
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  background: #f7f7f8;
}

.file-manager-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 30px 10px;
  flex-shrink: 0;
}

.head-title {
  min-width: 0;
}

.title-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.head-kicker {
  display: inline-flex;
  align-items: center;
  min-height: 20px;
  padding: 0 8px;
  border: 1px solid #dedee3;
  border-radius: 999px;
  background: #fff;
  color: #6b7280;
  font-size: 0.7rem;
  font-weight: 650;
  line-height: 1;
}

.file-manager-head h2 {
  margin: 0;
  color: #111827;
  font-size: 1.2rem;
  font-weight: 720;
  letter-spacing: 0;
}

.file-manager-head p {
  margin: 4px 0 0;
  color: #6b7280;
  font-size: 0.84rem;
}

.head-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.health-icon-button :deep(.el-icon) {
  font-size: 1rem;
}

.health-icon-button {
  width: 34px;
  height: 34px;
  border-color: #d9d9de;
  background: #fff;
  color: #6b7280;
  box-shadow: 0 1px 2px rgba(17, 24, 39, 0.04);
}

.health-icon-button:hover {
  border-color: #b9bbc3;
  background: #f9fafb;
  color: #111827;
}

.health-icon-button :deep(.el-icon svg) {
  display: block;
}

.file-manager-shell {
  display: flex;
  flex-direction: column;
  margin: 0 30px 18px;
  background: #fff;
  border: 1px solid #dedee3;
  border-radius: 8px;
  box-shadow: 0 18px 40px rgba(17, 24, 39, 0.045);
  min-height: 0;
  flex: 1;
  overflow: hidden;
}

.command-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  border-bottom: 1px solid #e8e8ed;
  background: #fff;
  flex-shrink: 0;
}

.command-group,
.command-meta,
.selected-file-strip {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
}

.command-group {
  gap: 8px;
}

.command-meta {
  justify-content: flex-end;
  gap: 10px;
  color: #6b7280;
  font-size: 0.81rem;
}

.command-meta > span {
  color: #8a8f98;
}

.deleting-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: 1px solid #fed7aa;
  border-radius: 999px;
  padding: 4px 9px;
  background: #fff7ed;
  color: #c2410c !important;
  font-weight: 620;
}

.command-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 34px;
  padding: 0 12px;
  border-radius: 8px;
  border: 1px solid #d9d9de;
  background: #fff;
  color: #1f2937;
  font-size: 0.86rem;
  font-weight: 520;
  cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease, color 0.15s ease;
}

.command-button:hover {
  border-color: #b9bbc3;
  background: #f9fafb;
  color: #111827;
}

.command-group :deep(.el-button--primary) {
  --el-button-bg-color: #111827;
  --el-button-border-color: #111827;
  --el-button-hover-bg-color: #1f2937;
  --el-button-hover-border-color: #1f2937;
  --el-button-active-bg-color: #000;
  --el-button-active-border-color: #000;
}

.file-picker input {
  display: none;
}

.selected-file-strip {
  gap: 8px;
  padding: 9px 14px;
  border-bottom: 1px solid #e8e8ed;
  background: #fafafa;
  flex-shrink: 0;
}

.selected-label {
  color: #4b5563;
  font-size: 0.8rem;
  font-weight: 650;
}

.browser-layout {
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
  flex: 1;
  min-height: 0;
}

.folder-rail {
  min-width: 0;
  min-height: 0;
  border-right: 1px solid #e8e8ed;
  background: #fbfbfc;
  overflow: auto;
}

.rail-title {
  padding: 15px 16px 9px;
  color: #6b7280;
  font-size: 0.75rem;
  font-weight: 650;
}

.tree-list {
  display: grid;
  gap: 2px;
  padding: 0 10px 14px;
}

.tree-node {
  width: 100%;
  min-height: 32px;
  display: flex;
  align-items: center;
  gap: 7px;
  border: 0;
  border-radius: 8px;
  padding: 0 10px;
  background: transparent;
  color: #374151;
  text-align: left;
  cursor: pointer;
  transition: background 0.14s ease, color 0.14s ease;
}

.tree-node span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tree-node:hover {
  background: #f1f1f3;
}

.tree-node.is-active {
  background: #ececef;
  color: #111827;
  font-weight: 650;
}

.browser-main {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  background: #fff;
  overflow: auto;
}

.browser-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  min-height: 44px;
  padding: 0 18px;
  border-bottom: 1px solid #eeeef1;
  background: #fff;
  flex-shrink: 0;
}

.breadcrumb-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
}

.breadcrumb-button {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: 0;
  padding: 4px 1px;
  background: transparent;
  color: #374151;
  font-size: 0.85rem;
  font-weight: 520;
  cursor: pointer;
}

.breadcrumb-button:hover {
  color: #111827;
}

.breadcrumb-separator {
  color: #9ca3af;
}

.toolbar-summary {
  color: #6b7280;
  font-size: 0.8rem;
  white-space: nowrap;
}

.explorer-list {
  display: grid;
  padding: 0 20px 20px;
  flex-shrink: 0;
}

.explorer-list-head,
.explorer-row {
  display: grid;
  grid-template-columns: minmax(220px, 2fr) minmax(132px, 0.85fr) minmax(90px, 0.55fr) minmax(70px, 0.45fr) minmax(116px, 0.55fr);
  align-items: center;
  gap: 14px;
  padding: 0 10px;
}

.explorer-list-head {
  min-height: 34px;
  border-top: 1px solid #eeeef1;
  border-bottom: 1px solid #eeeef1;
  background: #fbfbfc;
  color: #6b7280;
  font-size: 0.75rem;
  font-weight: 650;
}

.explorer-row {
  min-height: 48px;
  border-bottom: 1px solid #f0f0f2;
  color: #374151;
  font-size: 0.86rem;
  transition: background 0.14s ease, box-shadow 0.14s ease;
}

.explorer-row:hover {
  background: #f8fafc;
  box-shadow: inset 3px 0 0 #dbeafe;
}

.explorer-row.is-deleting {
  background: #fff7ed;
  box-shadow: inset 3px 0 0 #fb923c;
  color: #9a3412;
}

.explorer-row.is-deleting .explorer-name-button,
.explorer-row.is-deleting .explorer-type-cell,
.explorer-row.is-deleting .explorer-size-cell,
.explorer-row.is-deleting .explorer-date-cell {
  color: #9a3412;
}

.explorer-row.is-folder .explorer-item-icon {
  color: #2563eb;
}

.explorer-name-cell {
  min-width: 0;
  display: grid;
  gap: 3px;
}

.explorer-name-button {
  min-width: 0;
  border: 0;
  padding: 0;
  background: transparent;
  color: #111827;
  font-size: 0.9rem;
  font-weight: 590;
  text-align: left;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 9px;
}

.explorer-name-button span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.explorer-name-button:hover {
  color: #111827;
}

.row-status {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: #c2410c;
  font-size: 0.74rem;
  font-weight: 620;
}

.explorer-item-icon {
  color: #6b7280;
  font-size: 1.04rem;
  flex-shrink: 0;
}

.explorer-type-cell,
.explorer-size-cell,
.explorer-date-cell {
  min-width: 0;
  color: #6b7280;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.item-actions {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 4px;
}

.icon-action {
  width: 27px;
  height: 27px;
  border: 1px solid transparent;
  border-radius: 7px;
  background: transparent;
  color: #6b7280;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: background 0.14s ease, border-color 0.14s ease, color 0.14s ease;
}

.icon-action:hover {
  border-color: #d9d9de;
  background: #f4f4f5;
  color: #111827;
}

.icon-action.is-success:hover {
  border-color: #bbf7d0;
  background: #f0fdf4;
  color: #15803d;
}

.icon-action.is-warning:hover {
  border-color: #fde68a;
  background: #fffbeb;
  color: #b45309;
}

.icon-action.is-danger:hover {
  border-color: #fecaca;
  background: #fff1f2;
  color: #dc2626;
}

.icon-action:disabled {
  cursor: progress;
  opacity: 0.55;
}

.is-spinning {
  animation: spin 0.9s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.document-empty {
  margin: 24px 20px 30px;
  border: 1px dashed #d9d9de;
  border-radius: 8px;
  background: #fbfbfc;
  flex-shrink: 0;
}

.document-empty :deep(.el-empty__description p) {
  color: #6b7280;
  font-size: 0.88rem;
}

.create-folder-body {
  display: grid;
  gap: 10px;
}

.create-folder-body p {
  margin: 0;
  color: #6b7280;
  font-size: 0.88rem;
}

.edit-dialog-body {
  display: grid;
  gap: 10px;
  min-height: 0;
}

.dialog-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.dialog-title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 1rem;
  font-weight: 600;
  color: #111827;
}

.dialog-tool-btn {
  min-width: 32px;
  height: 28px;
  padding: 0 6px;
  border-radius: 7px;
  border: 1px solid #cfd8e3;
  background: #fff;
  color: #374151;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  white-space: nowrap;
  line-height: 1;
  font-size: 0.78rem;
}

.dialog-tool-icon-btn {
  min-width: 34px;
  padding: 0;
}

.dialog-tool-icon {
  width: 14px;
  height: 14px;
  stroke: currentColor;
  stroke-width: 1.7;
  fill: none;
  vector-effect: non-scaling-stroke;
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
  color: #374151;
  word-break: break-all;
}

.edit-textarea :deep(.el-textarea__inner) {
  font-family: "JetBrains Mono", "Consolas", "Courier New", monospace;
  line-height: 1.45;
}

.edit-dialog-body.is-fullscreen {
  grid-template-rows: auto auto auto minmax(0, 1fr);
  height: 100%;
}

.edit-textarea.is-fullscreen {
  height: 100%;
}

.edit-textarea.is-fullscreen :deep(.el-textarea) {
  height: 100%;
}

.edit-textarea.is-fullscreen :deep(.el-textarea__inner) {
  height: 100%;
  resize: none;
}

:deep(.el-dialog.edit-dialog) {
  display: flex;
  flex-direction: column;
  max-height: calc(100vh - 10vh);
}

:deep(.el-dialog.edit-dialog.is-fullscreen) {
  height: 100vh;
  max-height: 100vh;
}

:deep(.edit-dialog .el-dialog__header) {
  margin-right: 0;
  padding: 10px 14px;
  border-bottom: 1px solid #e7ecf3;
  background: #f4f8fc;
}

:deep(.edit-dialog .el-dialog__body) {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

@media (max-width: 860px) {
  .file-manager-head {
    padding-left: 12px;
    padding-right: 12px;
    flex-direction: column;
    align-items: stretch;
  }

  .head-actions {
    justify-content: flex-end;
  }

  .file-manager-shell {
    margin-left: 12px;
    margin-right: 12px;
  }

  .command-bar {
    align-items: stretch;
    flex-direction: column;
  }

  .command-group {
    align-items: stretch;
  }

  .command-group :deep(.el-button),
  .command-button {
    flex: 1;
  }

  .command-meta {
    justify-content: flex-start;
  }

  .browser-layout {
    grid-template-columns: 1fr;
  }

  .folder-rail {
    border-right: 0;
    border-bottom: 1px solid #eef2f7;
    max-height: 190px;
  }

  .explorer-list {
    padding-left: 12px;
    padding-right: 12px;
  }

  .explorer-list-head {
    display: none;
  }

  .explorer-row {
    grid-template-columns: 1fr;
    gap: 6px;
    min-height: auto;
    padding: 10px 4px;
  }

  .explorer-type-cell,
  .explorer-size-cell,
  .explorer-date-cell {
    font-size: 0.78rem;
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
