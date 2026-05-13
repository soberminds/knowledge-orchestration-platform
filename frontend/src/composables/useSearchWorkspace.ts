import type { Ref } from "vue";
import { ref } from "vue";
import { search, type SourceHit } from "../api";
import { useI18n } from "./useI18n";

export function useSearchWorkspace(topK: Ref<number>) {
  const { t } = useI18n();
  const query = ref("");
  const hits = ref<SourceHit[]>([]);
  const searching = ref(false);
  const errorMessage = ref("");

  function clearError() {
    errorMessage.value = "";
  }

  async function runSearch() {
    const trimmed = query.value.trim();
    if (!trimmed) {
      errorMessage.value = t("error.search_query_required");
      return;
    }

    searching.value = true;
    clearError();
    try {
      const result = await search({
        query: trimmed,
        top_k: topK.value,
      });
      hits.value = result.hits;
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : t("error.search_failed");
      throw error;
    } finally {
      searching.value = false;
    }
  }

  return {
    query,
    hits,
    searching,
    errorMessage,
    runSearch,
    clearError,
  };
}
