import type { Ref } from "vue";
import { ref } from "vue";
import { search, type SourceHit } from "../api";

export function useSearchWorkspace(topK: Ref<number>) {
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
      errorMessage.value = "Please enter a query.";
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
      errorMessage.value = error instanceof Error ? error.message : "Search failed";
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
