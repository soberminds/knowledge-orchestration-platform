import { computed, ref } from "vue";
import { useI18n } from "./useI18n";
import {
  deleteDocument as deleteDocumentApi,
  getHealth,
  getOfficeHealth,
  listDocuments,
  rebuildIndex,
  uploadDocuments,
  type DocumentInfo,
  type HealthResponse,
  type OfficeHealthResponse,
} from "../api";

const RETRY_DELAYS_MS = [0, 600, 1200];

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
  const errorMessage = ref("");
  const officeHealthError = ref("");

  const statusText = computed(() => health.value?.status ?? t("status.loading"));
  const indexedChunks = computed(() => health.value?.indexed_chunks ?? 0);

  function setSelectedFiles(files: File[]) {
    selectedFiles.value = files;
  }

  function clearError() {
    errorMessage.value = "";
  }

  async function refreshDashboard(options?: { retries?: number }) {
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

  async function uploadAndBuild() {
    if (!selectedFiles.value.length) {
      errorMessage.value = t("error.select_files_first");
      return;
    }

    uploading.value = true;
    clearError();
    try {
      await uploadDocuments(selectedFiles.value);
      selectedFiles.value = [];
      await refreshDashboard();
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : t("error.upload_failed");
      throw error;
    } finally {
      uploading.value = false;
    }
  }

  async function deleteDocument(path: string) {
    deletingPath.value = path;
    clearError();
    try {
      await deleteDocumentApi(path);
      await refreshDashboard();
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : t("error.delete_document_failed");
      throw error;
    } finally {
      deletingPath.value = "";
    }
  }

  async function runIngest() {
    ingesting.value = true;
    clearError();
    try {
      await rebuildIndex();
      await refreshDashboard();
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : t("error.rebuild_index_failed");
      throw error;
    } finally {
      ingesting.value = false;
    }
  }

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
    errorMessage,
    officeHealthError,
    statusText,
    indexedChunks,
    setSelectedFiles,
    refreshDashboard,
    refreshOfficeHealth,
    uploadAndBuild,
    deleteDocument,
    runIngest,
    clearError,
  };
}
