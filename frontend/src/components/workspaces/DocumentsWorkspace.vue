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
  mutatingPath?: string;
}>();

const emit = defineEmits<{
  (event: "files-change", files: File[]): void;
  (event: "upload", folderPath?: string, parentId?: number | null): void;
  (event: "create-folder", parentPath: string, name: string, parentId?: number | null): void;
  (event: "use-current-folder-in-chat", folderPath: string, folderId: number | null): void;
  (event: "open-document", path: string, fileId?: number | null): void;
  (event: "open-office-editor", path: string, fileId?: number | null): void;
  (event: "delete-document", path: string, fileId?: number | null): void;
  (event: "delete-folder", path: string): void;
  (event: "rename-document", path: string, newName: string, fileId?: number | null): void;
  (event: "move-document", path: string, parentPath: string, parentId?: number | null, fileId?: number | null): void;
  (event: "rename-folder", path: string, newName: string): void;
  (event: "move-folder", path: string, parentPath: string, parentId?: number | null): void;
  (event: "document-saved", path: string, fileId?: number | null): void;
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
  id: number | null;
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
const renameDialogVisible = ref(false);
const renameTarget = ref<BrowserListItem | null>(null);
const renameName = ref("");
const moveDialogVisible = ref(false);
const moveTarget = ref<BrowserListItem | null>(null);
const moveTargetFolderPath = ref("");
const editDialogVisible = ref(false);
const editLoading = ref(false);
const editSaving = ref(false);
const editError = ref("");
const editPath = ref("");
const editFileId = ref<number | null>(null);
const editEncoding = ref("utf-8");
const editContent = ref("");
const editOriginalContent = ref("");
const editDialogFullscreen = ref(false);

const selectedFileNames = computed(() => props.selectedFiles.map((file) => file.name));
const canSaveEdit = computed(() => !editLoading.value && !editSaving.value);
const editDirty = computed(() => editContent.value !== editOriginalContent.value);
const deletingActive = computed(() => Boolean(props.deletingPath));
const mutatingActive = computed(() => Boolean(props.mutatingPath));
const busyActive = computed(() => deletingActive.value || mutatingActive.value);
const mutatingPath = computed(() => props.mutatingPath || "");

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
    id: folder.folder_id ?? folder.id ?? null,
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
    id: doc.id ?? null,
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
const chatScopeActionHint = computed(() => {
  if (!currentFolder.value) {
    return "将全部文档设为当前聊天的检索范围";
  }
  return `将“${formatVisiblePath(currentFolder.value)}”设为当前聊天的检索范围`;
});
const uploadTargetLabel = computed(() => formatVisiblePath(currentUploadFolderPath.value));
const hasCurrentItems = computed(() => browserListItems.value.length > 0);
const moveTargetLabel = computed(() => moveTarget.value?.name || "");
const moveDestinationOptions = computed(() => {
  const target = moveTarget.value;
  return [
    {
      label: "我的文档",
      path: "",
      folderId: null as number | null,
      disabled: false,
    },
    ...directoryItems.value.map((folder) => {
      const folderPath = normalizePath(folder.path);
      const isSelf = Boolean(target?.kind === "folder" && folderPath === target.path);
      const isDescendant = Boolean(target?.kind === "folder" && folderPath.startsWith(`${target.path}/`));
      return {
        label: folderPath,
        path: folderPath,
        folderId: folder.folder_id ?? null,
        disabled: isSelf || isDescendant,
      };
    }),
  ];
});
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

function shouldShowIndexStatus(status?: string | null) {
  const normalized = String(status || "").trim().toLowerCase();
  return Boolean(normalized && normalized !== "success");
}

function indexStatusLabel(status?: string | null) {
  const normalized = String(status || "").trim().toLowerCase();
  if (normalized === "queued") {
    return "排队中";
  }
  if (normalized === "running") {
    return "索引中";
  }
  if (normalized === "failed") {
    return "索引失败";
  }
  if (normalized === "pending") {
    return "待索引";
  }
  return normalized || "待索引";
}

function indexStatusTagType(status?: string | null) {
  const normalized = String(status || "").trim().toLowerCase();
  if (normalized === "failed") {
    return "danger";
  }
  if (normalized === "running" || normalized === "queued") {
    return "warning";
  }
  return "info";
}

function openDocument(path: string, fileId?: number | null) {
  emit("open-document", path, fileId ?? null);
}

function openDocumentByItem(item: BrowserListItem) {
  if (item.doc) {
    emit("open-document", item.doc.path, item.doc.id ?? null);
  }
}

function openBrowserItem(item: BrowserListItem) {
  if (item.folder) {
    openFolder(item.folder.path);
    return;
  }
  if (item.doc) {
    openDocumentByItem(item);
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
    openOfficeEditor(item.doc.path, item.doc.id ?? null);
  }
}

function openBrowserItemTextEditor(item: BrowserListItem) {
  if (item.doc) {
    void openEditDialog(item.doc);
  }
}

function deleteBrowserItem(item: BrowserListItem) {
  if (item.doc) {
    deleteDocument(item.doc.path, item.doc.id ?? null);
    return;
  }
  if (item.folder) {
    deleteFolder(item.folder.path);
  }
}

function openRenameDialog(item: BrowserListItem) {
  renameTarget.value = item;
  renameName.value = item.name;
  renameDialogVisible.value = true;
}

function submitRename() {
  const target = renameTarget.value;
  const name = renameName.value.trim();
  if (!target || !name || name === target.name) {
    renameDialogVisible.value = false;
    return;
  }
  if (target.kind === "folder") {
    emit("rename-folder", target.path, name);
  } else {
    emit("rename-document", target.path, name, target.id);
  }
  renameDialogVisible.value = false;
}

function openMoveDialog(item: BrowserListItem) {
  moveTarget.value = item;
  moveTargetFolderPath.value = item.parentPath;
  moveDialogVisible.value = true;
}

function submitMove() {
  const target = moveTarget.value;
  if (!target) {
    return;
  }
  const destinationPath = normalizePath(moveTargetFolderPath.value);
  if (destinationPath === normalizePath(target.parentPath)) {
    moveDialogVisible.value = false;
    return;
  }
  const folder = directoryItems.value.find((item) => item.path === destinationPath) ?? null;
  const parentId = destinationPath ? folder?.folder_id ?? null : null;
  if (target.kind === "folder") {
    emit("move-folder", target.path, destinationPath, parentId);
  } else {
    emit("move-document", target.path, destinationPath, parentId, target.id);
  }
  moveDialogVisible.value = false;
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

function deleteDocument(path: string, fileId?: number | null) {
  emit("delete-document", path, fileId ?? null);
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

function useCurrentFolderInChat() {
  emit("use-current-folder-in-chat", currentFolder.value, currentUploadFolderId.value);
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

function openOfficeEditor(path: string, fileId?: number | null) {
  emit("open-office-editor", path, fileId ?? null);
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
  if (command === "rename") {
    openRenameDialog({
      kind: "folder",
      id: folder.folder_id ?? folder.id ?? null,
      key: `folder:${folder.path}`,
      name: folder.name,
      path: folder.path,
      parentPath: folder.parentPath,
      modifiedAt: folder.modified_at,
      typeLabel: "文件夹",
      sizeLabel: "-",
      folder,
    });
    return;
  }
  if (command === "move") {
    openMoveDialog({
      kind: "folder",
      id: folder.folder_id ?? folder.id ?? null,
      key: `folder:${folder.path}`,
      name: folder.name,
      path: folder.path,
      parentPath: folder.parentPath,
      modifiedAt: folder.modified_at,
      typeLabel: "文件夹",
      sizeLabel: "-",
      folder,
    });
    return;
  }
  if (command === "delete") {
    deleteFolder(folder.path);
  }
}

function handleFileCommand(command: string, doc: FileItem) {
  if (command === "open") {
    openDocument(doc.path, doc.id ?? null);
    return;
  }
  if (command === "office") {
    openOfficeEditor(doc.path, doc.id ?? null);
    return;
  }
  if (command === "edit") {
    void openEditDialog(doc);
    return;
  }
  if (command === "rename") {
    openRenameDialog({
      kind: "file",
      id: doc.id ?? null,
      key: `file:${doc.path}`,
      name: doc.name,
      path: doc.path,
      parentPath: doc.parentPath,
      modifiedAt: doc.modified_at,
      typeLabel: doc.extension || "文件",
      sizeLabel: formatBytes(doc.size_bytes),
      doc,
    });
    return;
  }
  if (command === "move") {
    openMoveDialog({
      kind: "file",
      id: doc.id ?? null,
      key: `file:${doc.path}`,
      name: doc.name,
      path: doc.path,
      parentPath: doc.parentPath,
      modifiedAt: doc.modified_at,
      typeLabel: doc.extension || "文件",
      sizeLabel: formatBytes(doc.size_bytes),
      doc,
    });
    return;
  }
  if (command === "delete") {
    deleteDocument(doc.path, doc.id ?? null);
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
  editFileId.value = doc.id ?? null;
  editContent.value = "";
  editOriginalContent.value = "";
  editEncoding.value = "utf-8";

  try {
    const payload = await getFileEditableText(doc.path, doc.id ?? null);
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
  editFileId.value = null;
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
    await saveFileEditableText(editPath.value, editContent.value, editFileId.value);
    editOriginalContent.value = editContent.value;
    emit("document-saved", editPath.value, editFileId.value);
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
    <header v-if="false" class="file-manager-head">
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
            class="action-btn action-btn--confirm"
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
          <span v-else-if="mutatingActive" class="deleting-pill">
            <el-icon class="is-spinning"><Loading /></el-icon>
            更新中...
          </span>
          <span>{{ visibleFolders.length }} 个文件夹</span>
          <span>{{ visibleFiles.length }} 个文件</span>
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
            <div class="toolbar-side">
              <div class="toolbar-summary">
                {{ visibleFolders.length }} folders · {{ visibleFiles.length }} files
              </div>
              <el-tooltip :content="chatScopeActionHint" placement="top">
                <el-button
                  size="small"
                  class="action-btn action-btn--ghost"
                  plain
                  :icon="FolderOpened"
                  :disabled="busyActive"
                  @click="useCurrentFolderInChat"
                >
                  在聊天中使用
                </el-button>
              </el-tooltip>
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
              :class="{ 'is-folder': item.kind === 'folder', 'is-deleting': deletingPath === item.path || mutatingPath === item.path }"
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
                <span v-else-if="mutatingPath === item.path" class="row-status">
                  <el-icon class="is-spinning"><Loading /></el-icon>
                  正在更新
                </span>
                <el-tag
                  v-if="item.doc && shouldShowIndexStatus(item.doc.index_status)"
                  size="small"
                  effect="plain"
                  :type="indexStatusTagType(item.doc.index_status)"
                  class="index-status-tag"
                >
                  {{ indexStatusLabel(item.doc.index_status) }}
                </el-tag>
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
                    :disabled="busyActive"
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
                      :disabled="busyActive"
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
                  <button class="icon-action" type="button" :disabled="busyActive" @click.stop>
                    <el-icon><MoreFilled /></el-icon>
                  </button>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item command="open" :icon="Open">打开</el-dropdown-item>
                      <el-dropdown-item command="upload" :icon="Upload" :disabled="!selectedFiles.length">
                        上传到这里
                      </el-dropdown-item>
                      <el-dropdown-item command="create" :icon="FolderAdd">新建子文件夹</el-dropdown-item>
                      <el-dropdown-item command="rename" :icon="EditPen">重命名</el-dropdown-item>
                      <el-dropdown-item command="move" :icon="Folder">移动到...</el-dropdown-item>
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
                    :disabled="busyActive"
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
                    :disabled="busyActive"
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
                    :disabled="busyActive"
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
                      :disabled="busyActive"
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
                  <button class="icon-action" type="button" :disabled="busyActive" @click.stop>
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
                      <el-dropdown-item command="rename" :icon="EditPen">重命名</el-dropdown-item>
                      <el-dropdown-item command="move" :icon="Folder">移动到...</el-dropdown-item>
                      <el-dropdown-item command="delete" :icon="Delete">删除</el-dropdown-item>
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
            class="action-btn action-btn--confirm"
            :disabled="!createFolderName.trim()"
            @click="submitCreateFolder"
          >
            创建
          </el-button>
        </span>
      </template>
    </el-dialog>

    <el-dialog
      v-model="renameDialogVisible"
      title="重命名"
      width="420px"
      append-to-body
    >
      <div class="create-folder-body">
        <p>当前名称：{{ renameTarget?.name || "-" }}</p>
        <el-input
          v-model="renameName"
          placeholder="输入新名称"
          maxlength="255"
          show-word-limit
          @keyup.enter="submitRename"
        />
      </div>
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="renameDialogVisible = false">{{ t("documents.cancel") }}</el-button>
          <el-button
            class="action-btn action-btn--confirm"
            :loading="mutatingActive"
            :disabled="!renameName.trim() || renameName.trim() === renameTarget?.name"
            @click="submitRename"
          >
            保存
          </el-button>
        </span>
      </template>
    </el-dialog>

    <el-dialog
      v-model="moveDialogVisible"
      title="移动到"
      width="480px"
      append-to-body
    >
      <div class="move-dialog-body">
        <p>移动对象：{{ moveTargetLabel || "-" }}</p>
        <el-radio-group v-model="moveTargetFolderPath" class="move-target-list">
          <el-radio
            v-for="option in moveDestinationOptions"
            :key="option.path || 'root'"
            :label="option.path"
            :disabled="option.disabled"
            border
          >
            {{ option.label }}
          </el-radio>
        </el-radio-group>
      </div>
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="moveDialogVisible = false">{{ t("documents.cancel") }}</el-button>
          <el-button
            class="action-btn action-btn--confirm"
            :loading="mutatingActive"
            :disabled="moveTargetFolderPath === moveTarget?.parentPath"
            @click="submitMove"
          >
            移动
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
            class="action-btn action-btn--confirm"
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
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  background: transparent;
  padding: 18px 24px;
}

.health-icon-button :deep(.el-icon) {
  font-size: 1rem;
}

.health-icon-button {
  width: 34px;
  height: 34px;
  border-color: var(--border);
  background: var(--surface-solid);
  color: var(--text-muted);
  box-shadow: 0 1px 2px rgba(17, 24, 39, 0.04);
}

.health-icon-button:hover {
  border-color: var(--border-strong);
  background: var(--surface-hover);
  color: var(--text);
}

.health-icon-button :deep(.el-icon svg) {
  display: block;
}

.file-manager-shell {
  display: flex;
  flex-direction: column;
  margin: 0;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  box-shadow: 0 20px 44px rgba(17, 24, 39, 0.055);
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
  border-bottom: 1px solid var(--border);
  background: var(--surface);
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
  color: var(--text-muted);
  font-size: 0.81rem;
}

.command-meta > span {
  color: var(--text-soft);
}

.deleting-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: 1px solid color-mix(in srgb, #fb923c 46%, transparent);
  border-radius: 999px;
  padding: 4px 9px;
  background: var(--surface-warn);
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
  border: 1px solid var(--border);
  background: var(--surface-solid);
  color: var(--text);
  font-size: 0.86rem;
  font-weight: 520;
  cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease, color 0.15s ease;
}

.command-button:hover {
  border-color: var(--border-strong);
  background: var(--surface-hover);
  color: var(--text);
}

.action-btn--confirm {
  --el-button-bg-color: #0f766e;
  --el-button-border-color: #0f766e;
  --el-button-hover-bg-color: #0d9488;
  --el-button-hover-border-color: #0d9488;
  --el-button-active-bg-color: #0b6f68;
  --el-button-active-border-color: #0b6f68;
  --el-button-text-color: #fff;
  --el-button-hover-text-color: #fff;
  --el-button-active-text-color: #fff;
}

.action-btn--ghost {
  --el-button-bg-color: rgba(236, 253, 249, 0.94);
  --el-button-border-color: rgba(20, 184, 166, 0.18);
  --el-button-hover-bg-color: rgba(220, 252, 242, 0.98);
  --el-button-hover-border-color: rgba(20, 184, 166, 0.28);
  --el-button-active-bg-color: rgba(220, 252, 242, 0.98);
  --el-button-active-border-color: rgba(20, 184, 166, 0.32);
  --el-button-text-color: #0f766e;
  --el-button-hover-text-color: #0f766e;
  --el-button-active-text-color: #0f766e;
}

.file-picker input {
  display: none;
}

.selected-file-strip {
  gap: 8px;
  padding: 9px 14px;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
  flex-shrink: 0;
}

.selected-label {
  color: var(--text-muted);
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
  border-right: 1px solid var(--border);
  background: var(--surface);
  overflow: auto;
}

.rail-title {
  padding: 15px 16px 9px;
  color: var(--text-muted);
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
  color: var(--text);
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
  background: var(--surface-hover);
}

.tree-node.is-active {
  background: var(--surface-active);
  color: var(--text);
  font-weight: 650;
}

.browser-main {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  background: var(--surface);
  overflow: auto;
}

.browser-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  min-height: 44px;
  padding: 0 18px;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
  flex-shrink: 0;
}

.toolbar-side {
  display: inline-flex;
  align-items: center;
  gap: 10px;
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
  color: var(--text);
  font-size: 0.85rem;
  font-weight: 520;
  cursor: pointer;
}

.breadcrumb-button:hover {
  color: var(--accent-strong);
}

.breadcrumb-separator {
  color: var(--text-soft);
}

.toolbar-summary {
  color: var(--text-muted);
  font-size: 0.8rem;
  white-space: nowrap;
}

.toolbar-side :deep(.el-button) {
  height: 30px;
  padding: 0 10px;
  border-radius: 8px;
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
  border-top: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
  background: var(--surface);
  color: var(--text-muted);
  font-size: 0.75rem;
  font-weight: 650;
}

.explorer-row {
  min-height: 48px;
  border-bottom: 1px solid var(--border);
  color: var(--text);
  font-size: 0.86rem;
  transition: background 0.14s ease, box-shadow 0.14s ease;
}

.explorer-row:hover {
  background: rgba(20, 184, 166, 0.045);
  box-shadow: inset 3px 0 0 #14b8a6;
}

.explorer-row.is-deleting {
  background: rgba(251, 146, 60, 0.08);
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
  color: #0f766e;
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
  color: var(--text);
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
  color: var(--accent-strong);
}

.row-status {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: #c2410c;
  font-size: 0.74rem;
  font-weight: 620;
}

.index-status-tag {
  width: fit-content;
  max-width: 100%;
}

.explorer-item-icon {
  color: var(--text-muted);
  font-size: 1.04rem;
  flex-shrink: 0;
}

.explorer-type-cell,
.explorer-size-cell,
.explorer-date-cell {
  min-width: 0;
  color: var(--text-muted);
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
  color: var(--text-muted);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: background 0.14s ease, border-color 0.14s ease, color 0.14s ease;
}

.icon-action:hover {
  border-color: var(--border-strong);
  background: var(--surface-hover);
  color: var(--text);
}

.icon-action.is-success:hover {
  border-color: color-mix(in srgb, #22c55e 42%, transparent);
  background: color-mix(in srgb, #22c55e 12%, var(--surface-solid));
  color: color-mix(in srgb, #22c55e 78%, var(--text));
}

.icon-action.is-warning:hover {
  border-color: color-mix(in srgb, #fbbf24 44%, transparent);
  background: var(--surface-warn);
  color: var(--warning);
}

.icon-action.is-danger:hover {
  border-color: color-mix(in srgb, #fb7185 46%, transparent);
  background: var(--surface-danger);
  color: var(--danger);
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
  border: 1px dashed rgba(148, 163, 184, 0.28);
  border-radius: 8px;
  background: var(--surface);
  flex-shrink: 0;
}

.document-empty :deep(.el-empty__description p) {
  color: var(--text-muted);
  font-size: 0.88rem;
}

.create-folder-body {
  display: grid;
  gap: 10px;
}

.create-folder-body p {
  margin: 0;
  color: var(--text-muted);
  font-size: 0.88rem;
}

.move-dialog-body {
  display: grid;
  gap: 12px;
}

.move-dialog-body p {
  margin: 0;
  color: var(--text-muted);
  font-size: 0.88rem;
}

.move-target-list {
  display: grid;
  gap: 8px;
  max-height: 320px;
  overflow: auto;
  padding-right: 4px;
}

.move-target-list :deep(.el-radio) {
  width: 100%;
  margin-right: 0;
}

.move-target-list :deep(.el-radio__label) {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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
  color: var(--text);
}

.dialog-tool-btn {
  min-width: 32px;
  height: 28px;
  padding: 0 6px;
  border-radius: 7px;
  border: 1px solid var(--border);
  background: var(--surface-solid);
  color: var(--text);
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
  color: var(--text-muted);
}

.edit-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.edit-path {
  font-size: 0.86rem;
  color: var(--text);
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
  .workspace-standard {
    padding: 12px;
  }

  .file-manager-shell {
    margin: 0;
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
