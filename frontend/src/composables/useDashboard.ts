import { computed, ref } from "vue";
import {
  getHealth,
  listDocuments,
  rebuildIndex,
  uploadDocuments,
  type DocumentInfo,
  type HealthResponse,
} from "../api";

const RETRY_DELAYS_MS = [0, 600, 1200];

function wait(ms: number) {
  return new Promise<void>((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

export function useDashboard() {
  const health = ref<HealthResponse | null>(null);
  const documents = ref<DocumentInfo[]>([]);
  const selectedFiles = ref<File[]>([]);

  const refreshing = ref(false);
  const uploading = ref(false);
  const ingesting = ref(false);
  const errorMessage = ref("");

  const statusText = computed(() => health.value?.status ?? "loading");
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
          const [healthData, docs] = await Promise.all([getHealth(), listDocuments()]);
          health.value = healthData;
          documents.value = docs;
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
      errorMessage.value = error instanceof Error ? error.message : "Failed to refresh dashboard";
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
      errorMessage.value = "Please select files first.";
      return;
    }

    uploading.value = true;
    clearError();
    try {
      await uploadDocuments(selectedFiles.value);
      selectedFiles.value = [];
      await refreshDashboard();
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : "Upload failed";
      throw error;
    } finally {
      uploading.value = false;
    }
  }

  async function runIngest() {
    ingesting.value = true;
    clearError();
    try {
      await rebuildIndex();
      await refreshDashboard();
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : "Failed to rebuild index";
      throw error;
    } finally {
      ingesting.value = false;
    }
  }

  return {
    health,
    documents,
    selectedFiles,
    refreshing,
    uploading,
    ingesting,
    errorMessage,
    statusText,
    indexedChunks,
    setSelectedFiles,
    refreshDashboard,
    uploadAndBuild,
    runIngest,
    clearError,
  };
}
