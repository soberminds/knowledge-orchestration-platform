import { computed, onBeforeUnmount, ref } from "vue";
import { useI18n } from "./useI18n";
import {
  createDocumentFolder as createDocumentFolderApi,
  deleteDocument as deleteDocumentApi,
  deleteDocumentById as deleteDocumentByIdApi,
  deleteDocumentFolder as deleteDocumentFolderApi,
  getHealth,
  getOfficeHealth,
  listDocuments,
  moveDocument as moveDocumentApi,
  moveDocumentById as moveDocumentByIdApi,
  moveDocumentFolder as moveDocumentFolderApi,
  rebuildIndex,
  renameDocument as renameDocumentApi,
  renameDocumentById as renameDocumentByIdApi,
  renameDocumentFolder as renameDocumentFolderApi,
  uploadDocuments,
  type DocumentInfo,
  type HealthResponse,
  type OfficeHealthResponse,
} from "../api";
import { buildFolderScopeTree, type FolderScopeNode } from "../utils/documentTree";

const RETRY_DELAYS_MS = [0, 600, 1200];
const ACTIVE_INDEX_STATUSES = new Set(["queued", "running"]);

function wait(ms: number) {
  return new Promise<void>((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

export function useDashboard() {
  const { t } = useI18n();
  const health = ref<HealthResponse | null>(null);
  const officeHealth = ref<OfficeHealthResponse | null>(null);
  const documents = ref<DocumentInfo[]>([]);
  const selectedFiles = ref<File[]>([]);

  const refreshing = ref(false);
  const officeHealthLoading = ref(false);
  const uploading = ref(false);
  const ingesting = ref(false);
  const deletingPath = ref("");
  const mutatingPath = ref("");
  const errorMessage = ref("");
  const officeHealthError = ref("");

  const statusText = computed(() => health.value?.status ?? t("status.loading"));
  const indexedChunks = computed(() => health.value?.indexed_chunks ?? 0);
  const documentCount = computed(() => documents.value.filter((item) => !item.is_directory).length);
  const folderScopeTree = computed<FolderScopeNode[]>(() => buildFolderScopeTree(documents.value));
  let indexPollingTimer: number | undefined;

  function setSelectedFiles(files: File[]) {
    selectedFiles.value = files;
  }

  function clearError() {
    errorMessage.value = "";
  }

  function clearIndexPolling() {
    if (indexPollingTimer !== undefined) {
      window.clearTimeout(indexPollingTimer);
      indexPollingTimer = undefined;
    }
  }

  function hasProcessingIndexDocuments(items = documents.value) {
    return items.some((item) => {
      if (item.is_directory) {
        return false;
      }
      const status = String(item.index_status || item.parse_status || "").trim().toLowerCase();
      return ACTIVE_INDEX_STATUSES.has(status);
    });
  }

  function scheduleIndexPolling(attempts = 240, delayMs = 3000) {
    clearIndexPolling();
    let remaining = attempts;

    const tick = async () => {
      indexPollingTimer = undefined;
      if (remaining <= 0) {
        return;
      }
      remaining -= 1;
      try {
        await refreshDashboard({ skipIndexPolling: true });
      } catch {
        // Keep polling best-effort; explicit errors still surface on direct actions.
      }
      if (remaining > 0 && hasProcessingIndexDocuments()) {
        indexPollingTimer = window.setTimeout(tick, delayMs);
      }
    };

    indexPollingTimer = window.setTimeout(tick, delayMs);
  }

  function resetForUserChange() {
    clearIndexPolling();
    health.value = null;
    officeHealth.value = null;
    documents.value = [];
    selectedFiles.value = [];
    refreshing.value = false;
    officeHealthLoading.value = false;
    uploading.value = false;
    ingesting.value = false;
    deletingPath.value = "";
    mutatingPath.value = "";
    errorMessage.value = "";
    officeHealthError.value = "";
  }

  async function refreshDashboard(options?: { retries?: number; skipIndexPolling?: boolean }) {
    refreshing.value = true;
    clearError();
    const retries = Math.max(0, options?.retries ?? 0);
    let lastError: unknown = null;

    try {
      for (let attempt = 0; attempt <= retries; attempt += 1) {
        const delayMs = RETRY_DELAYS_MS[Math.min(attempt, RETRY_DELAYS_MS.length - 1)];
        if (delayMs > 0) {
          await wait(delayMs);
        }

        try {
          const [healthData, docs, officeData] = await Promise.all([
            getHealth(),
            listDocuments(),
            getOfficeHealth().catch(() => null),
          ]);
          health.value = healthData;
          documents.value = docs;
          if (!options?.skipIndexPolling && hasProcessingIndexDocuments(docs)) {
            scheduleIndexPolling();
          }
          if (officeData) {
            officeHealth.value = officeData;
            officeHealthError.value = "";
          }
          clearError();
          return;
        } catch (error) {
          lastError = error;
          if (attempt >= retries) {
            throw error;
          }
        }
      }
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : t("error.refresh_dashboard_failed");
      throw error;
    } finally {
      refreshing.value = false;
    }

    if (lastError) {
      throw lastError;
    }
  }

  async function uploadAndBuild(folderPath = "", parentId?: number | null) {
    if (!selectedFiles.value.length) {
      errorMessage.value = t("error.select_files_first");
      return;
    }

    uploading.value = true;
    clearError();
    try {
      await uploadDocuments(selectedFiles.value, folderPath, parentId);
      selectedFiles.value = [];
      await refreshDashboard({ retries: 1 });
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : t("error.upload_failed");
      throw error;
    } finally {
      uploading.value = false;
    }
  }

  async function createDocumentFolder(parentPath: string, name: string, parentId?: number | null) {
    clearError();
    try {
      await createDocumentFolderApi(parentPath, name, parentId);
      await refreshDashboard();
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : t("error.create_folder_failed");
      throw error;
    }
  }

  async function deleteDocument(path: string, fileId?: number | null) {
    deletingPath.value = path;
    clearError();
    try {
      if (fileId != null) {
        await deleteDocumentByIdApi(fileId);
      } else {
        await deleteDocumentApi(path);
      }
      await refreshDashboard();
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : t("error.delete_document_failed");
      throw error;
    } finally {
      deletingPath.value = "";
    }
  }

  async function deleteDocumentFolder(path: string) {
    deletingPath.value = path;
    clearError();
    try {
      await deleteDocumentFolderApi(path);
      await refreshDashboard();
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : t("error.delete_document_failed");
      throw error;
    } finally {
      deletingPath.value = "";
    }
  }

  async function renameDocument(path: string, newName: string, fileId?: number | null) {
    mutatingPath.value = path;
    clearError();
    try {
      const result = fileId != null
        ? await renameDocumentByIdApi(fileId, newName)
        : await renameDocumentApi(path, newName);
      await refreshDashboard();
      return result;
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : t("error.refresh_dashboard_failed");
      throw error;
    } finally {
      mutatingPath.value = "";
    }
  }

  async function moveDocument(path: string, parentPath: string, parentId?: number | null, fileId?: number | null) {
    mutatingPath.value = path;
    clearError();
    try {
      const result = fileId != null
        ? await moveDocumentByIdApi(fileId, parentPath, parentId)
        : await moveDocumentApi(path, parentPath, parentId);
      await refreshDashboard();
      return result;
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : t("error.refresh_dashboard_failed");
      throw error;
    } finally {
      mutatingPath.value = "";
    }
  }

  async function renameDocumentFolder(path: string, newName: string) {
    mutatingPath.value = path;
    clearError();
    try {
      const result = await renameDocumentFolderApi(path, newName);
      await refreshDashboard();
      return result;
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : t("error.refresh_dashboard_failed");
      throw error;
    } finally {
      mutatingPath.value = "";
    }
  }

  async function moveDocumentFolder(path: string, parentPath: string, parentId?: number | null) {
    mutatingPath.value = path;
    clearError();
    try {
      const result = await moveDocumentFolderApi(path, parentPath, parentId);
      await refreshDashboard();
      return result;
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : t("error.refresh_dashboard_failed");
      throw error;
    } finally {
      mutatingPath.value = "";
    }
  }

  async function runIngest() {
    ingesting.value = true;
    clearError();
    try {
      await rebuildIndex();
      await refreshDashboard({ retries: 1 });
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : t("error.rebuild_index_failed");
      throw error;
    } finally {
      ingesting.value = false;
    }
  }

  onBeforeUnmount(() => {
    clearIndexPolling();
  });

  async function refreshOfficeHealth() {
    officeHealthLoading.value = true;
    officeHealthError.value = "";
    try {
      officeHealth.value = await getOfficeHealth();
    } catch (error) {
      officeHealthError.value = error instanceof Error ? error.message : "Failed to fetch ONLYOFFICE health.";
      throw error;
    } finally {
      officeHealthLoading.value = false;
    }
  }

  return {
    health,
    officeHealth,
    documents,
    selectedFiles,
    refreshing,
    officeHealthLoading,
    uploading,
    ingesting,
    deletingPath,
    mutatingPath,
    errorMessage,
    officeHealthError,
    statusText,
    indexedChunks,
    documentCount,
    folderScopeTree,
    setSelectedFiles,
    refreshDashboard,
    refreshOfficeHealth,
    uploadAndBuild,
    createDocumentFolder,
    deleteDocument,
    deleteDocumentFolder,
    renameDocument,
    moveDocument,
    renameDocumentFolder,
    moveDocumentFolder,
    runIngest,
    clearError,
    resetForUserChange,
  };
}
