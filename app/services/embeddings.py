"""Embedding adapter with local-cache-first and endpoint fallback loading."""

from __future__ import annotations

import os
from functools import lru_cache

from langchain_core.embeddings import Embeddings

from app.core.settings import settings


class LocalSentenceTransformerEmbeddings(Embeddings):
    """Adapter that exposes sentence-transformers through LangChain Embeddings."""

    def __init__(self, model_name: str, device: str = "cpu") -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - dependency missing at runtime
            raise RuntimeError("Missing dependency: sentence-transformers") from exc

        load_errors: list[str] = []
        previous_hf_endpoint = os.environ.get("HF_ENDPOINT")
        cache_folder = str(settings.sentence_transformers_home)

        settings.hf_home.mkdir(parents=True, exist_ok=True)
        settings.sentence_transformers_home.mkdir(parents=True, exist_ok=True)

        try:
            # Prefer local cache so later reindex operations do not depend on network.
            try:
                self._model = SentenceTransformer(
                    model_name,
                    device=device,
                    cache_folder=cache_folder,
                    local_files_only=True,
                )
                return
            except Exception as exc:
                load_errors.append(f"local cache unavailable: {exc}")

            endpoints: list[str] = []
            for endpoint in (settings.hf_endpoint, settings.hf_fallback_endpoint):
                normalized = (endpoint or "").strip().rstrip("/")
                if normalized and normalized not in endpoints:
                    endpoints.append(normalized)

            for endpoint in endpoints:
                try:
                    os.environ["HF_ENDPOINT"] = endpoint
                    self._model = SentenceTransformer(
                        model_name,
                        device=device,
                        cache_folder=cache_folder,
                    )
                    return
                except Exception as exc:
                    load_errors.append(f"{endpoint}: {exc}")

            joined = " | ".join(load_errors) if load_errors else "unknown error"
            raise RuntimeError(
                "Failed to load embedding model. Tried local cache first, then remote endpoints. "
                f"Details: {joined}"
            )
        finally:
            if previous_hf_endpoint is None:
                os.environ.pop("HF_ENDPOINT", None)
            else:
                os.environ["HF_ENDPOINT"] = previous_hf_endpoint

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return vectors.tolist()

    def embed_query(self, text: str) -> list[float]:
        vector = self._model.encode(
            [text],
            normalize_embeddings=True,
            show_progress_bar=False,
        )[0]
        return vector.tolist()


@lru_cache(maxsize=1)
def get_embedding_model(model_name: str, device: str) -> LocalSentenceTransformerEmbeddings:
    """Process-level cache to avoid reloading the embedding model repeatedly."""
    return LocalSentenceTransformerEmbeddings(model_name=model_name, device=device)
