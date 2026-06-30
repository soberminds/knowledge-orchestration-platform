"""Core RAG service: ingest, retrieve, and answer (sync + streaming)."""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Literal
from urllib import error as urllib_error
from urllib import request as urllib_request

from app.core.settings import settings
from app.core.request_context import get_current_user_id
from chromadb import PersistentClient
from chromadb.config import Settings as ChromaSettings
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.schemas import ChatHistoryItem, ChatMessagePart
from app.services.embeddings import get_embedding_model
from app.services.document_library import DocumentLibraryService
from app.services.files import iter_source_files, load_documents_from_file
from app.services.llm_provider_adapter import (
    LLMProviderAdapter,
    LLMProviderAdapterFactory,
    ModelUnavailableError,
    ProviderRuntimeConfig,
)
from app.services.llm_provider_mapping import (
    CapabilityRegistry,
    ModelCapability,
)
from app.services.llm_streaming import StreamingEvent, content_delta, done_event, reasoning_delta, tool_call_delta
from app.services.preview_pdf import get_preview_pdf_cache_path
from app.services.tools import ToolRegistry, build_readonly_tool_registry

QuestionMode = Literal["overview", "technical", "comparison", "list", "general"]
ThinkingMode = Literal["quick", "deep"]
logger = logging.getLogger(__name__)


def _patch_posthog_capture_signature() -> None:
    """Compat patch for posthog>=7 used with chromadb 0.5.x telemetry."""
    try:
        import posthog
    except Exception:
        return

    capture_fn = getattr(posthog, "capture", None)
    if capture_fn is None or getattr(capture_fn, "__chroma_compat_patch__", False):
        return

    try:
        params = list(inspect.signature(capture_fn).parameters.values())
    except Exception:
        return

    # posthog>=7 switched to capture(event=..., **kwargs); chromadb still calls
    # capture(distinct_id, event, properties). Adapt without changing behavior.
    if params and params[0].name == "event":
        original_capture = capture_fn

        def _capture_compat(
            distinct_id: str,
            event: str,
            properties: dict[str, Any] | None = None,
            **kwargs: Any,
        ):
            payload = dict(kwargs)
            if properties is not None:
                payload.setdefault("properties", properties)
            payload.setdefault("distinct_id", distinct_id)
            try:
                return original_capture(event, **payload)
            except Exception:
                return None

        setattr(_capture_compat, "__chroma_compat_patch__", True)
        posthog.capture = _capture_compat


@dataclass(frozen=True)
class SearchHit:
    """Internal retrieval result."""

    source: str
    chunk_index: int
    page: int | None
    score: float | None
    preview: str
    content: str
    file_id: int | None = None
    folder_id: int | None = None
    display_name: str | None = None
    display_path: str | None = None
    folder_path: str | None = None


@dataclass(frozen=True)
class IngestStats:
    """Index build stats."""

    documents_loaded: int
    chunks_indexed: int
    source_files: list[str]


@dataclass(frozen=True)
class WebSearchHit:
    """External web search result snippet."""

    title: str
    url: str
    snippet: str


class KnowledgeBaseService:
    """Main knowledge-base service used by API routes."""

    def __init__(self) -> None:
        _patch_posthog_capture_signature()
        self.settings = settings
        self._lock = threading.RLock()
        self._embedder = None
        self._vector_store: Chroma | None = None
        self._document_library: DocumentLibraryService | None = None
        self._llm_adapter_factory = LLMProviderAdapterFactory(
            qwen_responses_api_enabled=self.settings.qwen_responses_api_enabled,
        )
        self._model_provider_overrides_cache: dict[str, str] | None = None
        self._extra_provider_configs_cache: dict[str, ProviderRuntimeConfig] | None = None
        self._model_pricing_cache: dict[str, dict[str, float]] | None = None
        self._capability_registry = CapabilityRegistry(
            capability_overrides_json=self.settings.model_capabilities_json,
            qwen_deep_thinking_budget=self.settings.qwen_deep_thinking_budget,
            deepseek_deep_reasoning_effort=self.settings.deepseek_deep_reasoning_effort,
        )

    @property
    def document_library(self) -> DocumentLibraryService:
        if self._document_library is None:
            self._document_library = DocumentLibraryService()
        return self._document_library

    @property
    def embedder(self):
        if self._embedder is None:
            self._embedder = get_embedding_model(
                model_name=self.settings.embedding_model,
                device=self.settings.embedding_device,
            )
        return self._embedder

    def _load_model_provider_overrides(self) -> dict[str, str]:
        if self._model_provider_overrides_cache is not None:
            return self._model_provider_overrides_cache

        raw = self.settings.model_provider_overrides_json.strip()
        if not raw:
            self._model_provider_overrides_cache = {}
            return self._model_provider_overrides_cache

        try:
            parsed = json.loads(raw)
        except Exception:
            self._model_provider_overrides_cache = {}
            return self._model_provider_overrides_cache

        if not isinstance(parsed, dict):
            self._model_provider_overrides_cache = {}
            return self._model_provider_overrides_cache

        normalized: dict[str, str] = {}
        for model_key, provider_name in parsed.items():
            if not isinstance(model_key, str) or not isinstance(provider_name, str):
                continue
            model_token = model_key.strip().lower()
            provider_token = provider_name.strip().lower()
            if not model_token or not provider_token:
                continue
            normalized[model_token] = provider_token

        self._model_provider_overrides_cache = normalized
        return self._model_provider_overrides_cache

    def _load_extra_provider_configs(self) -> dict[str, ProviderRuntimeConfig]:
        if self._extra_provider_configs_cache is not None:
            return self._extra_provider_configs_cache

        raw = self.settings.extra_provider_configs_json.strip()
        if not raw:
            self._extra_provider_configs_cache = {}
            return self._extra_provider_configs_cache

        try:
            parsed = json.loads(raw)
        except Exception:
            self._extra_provider_configs_cache = {}
            return self._extra_provider_configs_cache

        if not isinstance(parsed, dict):
            self._extra_provider_configs_cache = {}
            return self._extra_provider_configs_cache

        normalized: dict[str, ProviderRuntimeConfig] = {}
        for provider_name, value in parsed.items():
            if not isinstance(provider_name, str) or not isinstance(value, dict):
                continue

            token = provider_name.strip().lower()
            base_url = str(value.get("base_url", "")).strip()
            if not token or not base_url:
                continue

            explicit_api_key = str(value.get("api_key", "")).strip()
            api_key_env = str(value.get("api_key_env", "")).strip()
            api_key = explicit_api_key
            if not api_key and api_key_env:
                api_key = os.getenv(api_key_env, "").strip()

            normalized[token] = ProviderRuntimeConfig(
                provider=token,
                base_url=base_url,
                api_key=api_key,
            )

        self._extra_provider_configs_cache = normalized
        return self._extra_provider_configs_cache

    def _default_provider_configs(self) -> dict[str, ProviderRuntimeConfig]:
        return {
            "deepseek": ProviderRuntimeConfig(
                provider="deepseek",
                base_url=self.settings.deepseek_base_url,
                api_key=self.settings.deepseek_api_key,
            ),
            "qwen": ProviderRuntimeConfig(
                provider="qwen",
                base_url=self.settings.qwen_base_url,
                api_key=self.settings.qwen_api_key,
            ),
            "zai": ProviderRuntimeConfig(
                provider="zai",
                base_url=self.settings.zai_base_url,
                api_key=self.settings.zai_api_key,
            ),
            "kimi": ProviderRuntimeConfig(
                provider="kimi",
                base_url=self.settings.kimi_base_url,
                api_key=self.settings.kimi_api_key,
            ),
            "hunyuan": ProviderRuntimeConfig(
                provider="hunyuan",
                base_url=self.settings.hunyuan_base_url,
                api_key=self.settings.hunyuan_api_key,
            ),
            "siliconflow": ProviderRuntimeConfig(
                provider="siliconflow",
                base_url=self.settings.siliconflow_base_url,
                api_key=self.settings.siliconflow_api_key,
            ),
            "qianfan": ProviderRuntimeConfig(
                provider="qianfan",
                base_url=self.settings.qianfan_base_url,
                api_key=self.settings.qianfan_api_key,
            ),
            "openai": ProviderRuntimeConfig(
                provider="openai",
                base_url=self.settings.openai_base_url,
                api_key=self.settings.openai_api_key,
            ),
        }

    def _resolve_provider_name(self, model_name: str) -> str:
        normalized = model_name.strip().lower()
        if not normalized:
            return "deepseek"

        overrides = self._load_model_provider_overrides()
        exact = overrides.get(normalized)
        if exact:
            return exact
        sorted_keys = sorted(overrides.keys(), key=len, reverse=True)
        for key in sorted_keys:
            if normalized.startswith(key):
                return overrides[key]

        if normalized.startswith("deepseek"):
            return "deepseek"
        if normalized.startswith("qwen") or normalized.startswith("qwq"):
            return "qwen"
        if normalized.startswith("glm") or normalized.startswith("chatglm") or "zhipu" in normalized:
            return "zai"
        if normalized.startswith("kimi") or normalized.startswith("moonshot"):
            return "kimi"
        if normalized.startswith("hunyuan"):
            return "hunyuan"
        if normalized.startswith("ernie") or normalized.startswith("wenxin"):
            return "qianfan"
        if normalized.startswith("gpt") or normalized.startswith("o1") or normalized.startswith("o3") or normalized.startswith("o4"):
            return "openai"
        if normalized.startswith("pro/") or "/" in normalized:
            # Many SiliconFlow model IDs use "org/model" style.
            return "siliconflow"

        return "deepseek"

    def _resolve_provider_config(self, provider_name: str) -> ProviderRuntimeConfig | None:
        provider_token = provider_name.strip().lower()
        if not provider_token:
            return None

        merged = self._default_provider_configs()
        merged.update(self._load_extra_provider_configs())
        return merged.get(provider_token)

    def _resolve_model_provider_config(self, model_name: str) -> ProviderRuntimeConfig | None:
        provider = self._resolve_provider_name(model_name)
        return self._resolve_provider_config(provider)

    def _resolve_model_capability(self, model_name: str, provider: str | None = None) -> ModelCapability:
        provider_token = provider or self._resolve_provider_name(model_name)
        return self._capability_registry.resolve(provider=provider_token, model_name=model_name)

    def _resolve_model_provider(self, model_name: str) -> str:
        config = self._resolve_model_provider_config(model_name)
        if config is None:
            raise ModelUnavailableError(
                f"Model '{model_name}' is not mapped to a configured provider. "
                "Add MODEL_PROVIDER_OVERRIDES_JSON or EXTRA_PROVIDER_CONFIGS_JSON in .env."
            )
        return config.provider

    def _resolve_model_adapter(self, model_name: str) -> LLMProviderAdapter:
        config = self._resolve_model_provider_config(model_name)
        if config is None:
            raise ModelUnavailableError(
                f"Model '{model_name}' is not mapped to a configured provider. "
                "Add MODEL_PROVIDER_OVERRIDES_JSON or EXTRA_PROVIDER_CONFIGS_JSON in .env."
            )
        capability = self._resolve_model_capability(model_name=model_name, provider=config.provider)
        try:
            return self._llm_adapter_factory.create(
                config=config,
                capability=capability,
                temperature=self.settings.temperature,
                max_tokens=self.settings.max_tokens,
            )
        except ModelUnavailableError as exc:
            message = str(exc)
            provider_phrase = f"Model provider '{config.provider}'"
            model_phrase = f"Model '{model_name}'"
            if message.startswith(provider_phrase):
                message = message.replace(provider_phrase, model_phrase, 1)
            raise ModelUnavailableError(message) from exc

    def resolve_model_options(self) -> list[dict[str, str | bool | int | None]]:
        options: list[dict[str, str | bool | int | None]] = []
        for model_name in self.resolve_available_models():
            provider = self._resolve_provider_name(model_name)
            config = self._resolve_provider_config(provider)
            capability = self._resolve_model_capability(model_name=model_name, provider=provider)
            provider_configured = config is not None
            api_key_configured = bool(config and config.api_key)
            base_url = (config.base_url.strip() if config and config.base_url else "") or None
            base_url_configured = bool(base_url)
            available = bool(provider_configured and api_key_configured and base_url_configured)
            reason: str | None = None
            if not provider_configured:
                reason = "Provider is not configured."
            elif not base_url_configured:
                reason = f"Missing {provider.upper()}_BASE_URL in .env."
            elif not api_key_configured:
                reason = f"Missing {provider.upper()}_API_KEY in .env."
            options.append(
                {
                    "model": model_name,
                    "provider": provider,
                    "supports_native_web_search": capability.supports_native_web_search,
                    "supports_tool_calling": capability.supports_tool_calling,
                    "supports_multimodal_input": capability.supports_multimodal_input,
                    "supports_responses_api": capability.supports_responses_api,
                    "supports_responses_streaming": capability.supports_responses_streaming,
                    "thinking_style": capability.thinking_style,
                    "deep_reasoning_effort": capability.deep_reasoning_effort if capability.supports_reasoning_effort else None,
                    "deep_thinking_budget": capability.deep_thinking_budget
                    if capability.supports_thinking_budget and capability.deep_thinking_budget
                    else None,
                    "provider_configured": provider_configured,
                    "api_key_configured": api_key_configured,
                    "base_url": base_url,
                    "base_url_configured": base_url_configured,
                    "available": available,
                    "unavailable_reason": reason,
                }
            )
        return options

    def _provider_supports_native_web_search(self, provider: str, model_name: str) -> bool:
        return self._capability_registry.supports_native_web_search(
            provider=provider,
            model_name=model_name,
        )

    def _resolve_web_search_plan(
        self,
        *,
        model_name: str,
        native_web_search: bool,
        external_web_search: bool,
        web_search_legacy: bool,
    ) -> tuple[bool, bool]:
        provider = self._resolve_provider_name(model_name)
        supports_native = self._provider_supports_native_web_search(provider, model_name)
        use_native = bool(native_web_search and supports_native)

        # Legacy single switch keeps old behavior for older frontends.
        legacy_external = bool(web_search_legacy and not native_web_search and not external_web_search)
        use_external = bool(external_web_search or legacy_external)

        # Native web search has priority; external fallback can be enabled by turning native off.
        if use_native:
            use_external = False

        return use_native, use_external

    @property
    def vector_store(self) -> Chroma:
        if self._vector_store is None:
            self._vector_store = self._build_vector_store()
        return self._vector_store

    def _is_missing_chroma_collection_error(self, exc: Exception) -> bool:
        message = str(exc).lower()
        return "collection" in message and (
            "does not exist" in message
            or "not found" in message
        )

    def _current_user_filter(
        self,
        *,
        scope_type: str = "all",
        scope_id: int | None = None,
        workspace_key: str | None = None,
    ) -> dict[str, Any] | None:
        try:
            current_user_id = get_current_user_id()
            if current_user_id is not None:
                user_id = int(current_user_id)
            else:
                user_id = self.document_library.get_default_user_id()
            conditions: list[dict[str, Any]] = [{"user_id": user_id}]
            normalized_scope = str(scope_type or "all").strip().lower()
            if normalized_scope == "folder" and scope_id:
                conditions.append({"folder_id": int(scope_id)})
            elif normalized_scope == "kb" and scope_id:
                conditions.append({"kb_id": int(scope_id)})
            elif normalized_scope == "workspace" and workspace_key:
                conditions.append({"workspace_key": str(workspace_key)})

            if len(conditions) == 1:
                return conditions[0]
            return {"$and": conditions}
        except Exception as exc:
            logger.warning("Failed to resolve current document user for Chroma filtering. error=%s", exc)
            return None

    def _run_similarity_search(self, *, query: str, k: int, where_filter: dict[str, Any] | None = None):
        kwargs: dict[str, Any] = {"query": query, "k": k}
        if where_filter:
            kwargs["filter"] = where_filter
        return self.vector_store.similarity_search_with_relevance_scores(**kwargs)

    def _similarity_search_with_recovery(self, *, query: str, k: int, where_filter: dict[str, Any] | None = None):
        try:
            return self._run_similarity_search(query=query, k=k, where_filter=where_filter)
        except Exception as exc:
            if not self._is_missing_chroma_collection_error(exc):
                raise

        # Chroma can keep an in-memory collection handle whose id was removed
        # after a rebuild/reload. Drop that handle and try to reopen by name.
        self._vector_store = None
        try:
            return self._run_similarity_search(query=query, k=k, where_filter=where_filter)
        except Exception as retry_exc:
            if not self._is_missing_chroma_collection_error(retry_exc):
                raise

        # If reopening by name still points to a broken collection, rebuild the
        # index from source files once and retry. The RLock in rebuild_index
        # keeps this safe when multiple requests arrive together.
        stats = self.rebuild_index()
        if stats.chunks_indexed <= 0:
            return []
        return self._run_similarity_search(query=query, k=k, where_filter=where_filter)

    def _similarity_search_for_current_user(self, *, query: str, k: int, scope_type: str = "all", scope_id: int | None = None, workspace_key: str | None = None):
        normalized_scope = str(scope_type or "all").strip().lower()
        if normalized_scope == "folder" and scope_id:
            try:
                folder_ids = self.document_library.get_descendant_folder_ids(int(scope_id))
            except Exception as exc:
                logger.warning("Failed to resolve folder descendants for scoped retrieval. error=%s", exc)
                return []

            if not folder_ids:
                return []

            best_hits: dict[tuple[str, int | None, int], tuple[Any, float]] = {}
            for folder_id in folder_ids:
                try:
                    user_filter = self._current_user_filter(scope_type="folder", scope_id=int(folder_id))
                except Exception as exc:
                    logger.warning("Failed to resolve folder filter for scoped retrieval. error=%s", exc)
                    continue
                if not user_filter:
                    continue

                for doc, relevance in self._similarity_search_with_recovery(
                    query=query,
                    k=max(k, 1),
                    where_filter=user_filter,
                ):
                    metadata = doc.metadata or {}
                    score = float(relevance) if relevance is not None else 0.0
                    key = (
                        str(metadata.get("source", "unknown")),
                        self._metadata_int(metadata, "page"),
                        int(metadata.get("chunk_index", 0)),
                    )
                    previous = best_hits.get(key)
                    if previous is None or score > previous[1]:
                        best_hits[key] = ((doc, relevance), score)

            ordered_keys = sorted(best_hits.keys(), key=lambda item: best_hits[item][1], reverse=True)
            return [best_hits[key][0] for key in ordered_keys]

        where_filter = self._current_user_filter(scope_type=scope_type, scope_id=scope_id, workspace_key=workspace_key)
        if not where_filter:
            return []

        return self._similarity_search_with_recovery(query=query, k=k, where_filter=where_filter)

    def resolve_available_models(self) -> list[str]:
        models = list(self.settings.available_models)
        if not models:
            models = [self.settings.deepseek_model]
        if self.settings.deepseek_model not in models:
            models.insert(0, self.settings.deepseek_model)
        deduped: list[str] = []
        seen: set[str] = set()
        for model in models:
            name = model.strip()
            if not name or name in seen:
                continue
            seen.add(name)
            deduped.append(name)
        return deduped

    def resolve_model(self, requested_model: str | None) -> str:
        if not requested_model:
            return self.settings.deepseek_model
        model_name = requested_model.strip()
        if not model_name:
            return self.settings.deepseek_model
        return model_name

    def is_web_search_available(self) -> bool:
        provider = self.settings.web_search_provider
        if provider == "none":
            return False
        if provider in {"serper", "tavily"} and not self.settings.web_search_api_key:
            return False
        return provider in {"serper", "tavily"}

    def _load_model_pricing(self) -> dict[str, dict[str, float]]:
        if self._model_pricing_cache is not None:
            return self._model_pricing_cache

        raw = self.settings.model_pricing_json.strip()
        if not raw:
            self._model_pricing_cache = {}
            return self._model_pricing_cache

        try:
            parsed = json.loads(raw)
        except Exception:
            self._model_pricing_cache = {}
            return self._model_pricing_cache

        if not isinstance(parsed, dict):
            self._model_pricing_cache = {}
            return self._model_pricing_cache

        normalized: dict[str, dict[str, float]] = {}
        for model_name, pricing in parsed.items():
            if not isinstance(model_name, str) or not isinstance(pricing, dict):
                continue
            input_price = pricing.get("input_per_1m_tokens")
            output_price = pricing.get("output_per_1m_tokens")
            if input_price is None or output_price is None:
                continue
            try:
                normalized[model_name.strip()] = {
                    "input_per_1m_tokens": float(input_price),
                    "output_per_1m_tokens": float(output_price),
                }
            except Exception:
                continue

        self._model_pricing_cache = normalized
        return self._model_pricing_cache

    def _resolve_model_pricing(self, model_name: str) -> dict[str, float] | None:
        pricing_map = self._load_model_pricing()
        if not pricing_map:
            return None

        if model_name in pricing_map:
            return pricing_map[model_name]

        # Prefix match fallback: useful for versioned model ids.
        sorted_keys = sorted(pricing_map.keys(), key=len, reverse=True)
        for key in sorted_keys:
            if model_name.startswith(key):
                return pricing_map[key]
        return None

    def _estimate_tokens_from_text(self, text: str) -> int:
        compact = text.strip()
        if not compact:
            return 0
        # Coarse but stable fallback: mixed Chinese/English average.
        return max(1, len(compact) // 2)

    def _normalize_usage(
        self,
        usage_obj: Any,
        *,
        prompt_fallback_text: str = "",
        completion_fallback_text: str = "",
    ) -> dict[str, int]:
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0

        if usage_obj is not None:
            try:
                if isinstance(usage_obj, dict):
                    prompt_tokens = int(usage_obj.get("prompt_tokens", 0) or 0)
                    completion_tokens = int(usage_obj.get("completion_tokens", 0) or 0)
                    total_tokens = int(usage_obj.get("total_tokens", 0) or 0)
                else:
                    prompt_tokens = int(getattr(usage_obj, "prompt_tokens", 0) or 0)
                    completion_tokens = int(getattr(usage_obj, "completion_tokens", 0) or 0)
                    total_tokens = int(getattr(usage_obj, "total_tokens", 0) or 0)
            except Exception:
                prompt_tokens = 0
                completion_tokens = 0
                total_tokens = 0

        if prompt_tokens <= 0:
            prompt_tokens = self._estimate_tokens_from_text(prompt_fallback_text)
        if completion_tokens <= 0:
            completion_tokens = self._estimate_tokens_from_text(completion_fallback_text)
        if total_tokens <= 0:
            total_tokens = prompt_tokens + completion_tokens

        return {
            "prompt_tokens": max(prompt_tokens, 0),
            "completion_tokens": max(completion_tokens, 0),
            "total_tokens": max(total_tokens, 0),
        }

    def _estimate_cost(self, model_name: str, usage: dict[str, int]) -> dict[str, Any] | None:
        pricing = self._resolve_model_pricing(model_name)
        if not pricing:
            return None

        input_per_1m = pricing.get("input_per_1m_tokens")
        output_per_1m = pricing.get("output_per_1m_tokens")
        if input_per_1m is None or output_per_1m is None:
            return None

        prompt_tokens = max(int(usage.get("prompt_tokens", 0)), 0)
        completion_tokens = max(int(usage.get("completion_tokens", 0)), 0)
        input_cost = round(prompt_tokens * float(input_per_1m) / 1_000_000, 6)
        output_cost = round(completion_tokens * float(output_per_1m) / 1_000_000, 6)
        total_cost = round(input_cost + output_cost, 6)

        return {
            "currency": self.settings.cost_currency or "CNY",
            "input_per_1m_tokens": float(input_per_1m),
            "output_per_1m_tokens": float(output_per_1m),
            "input_cost": input_cost,
            "output_cost": output_cost,
            "total_cost": total_cost,
            "estimated": True,
        }

    def _build_vector_store(self) -> Chroma:
        client_settings = ChromaSettings(
            anonymized_telemetry=False,
            is_persistent=True,
            persist_directory=str(self.settings.chroma_dir),
        )
        return Chroma(
            collection_name=self.settings.collection_name,
            embedding_function=self.embedder,
            persist_directory=str(self.settings.chroma_dir),
            client_settings=client_settings,
            collection_metadata={"hnsw:space": "cosine"},
        )

    def _build_chroma_client(self) -> PersistentClient:
        client_settings = ChromaSettings(anonymized_telemetry=False)
        return PersistentClient(path=str(self.settings.chroma_dir), settings=client_settings)

    def ensure_directories(self) -> None:
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.settings.user_docs_dir.mkdir(parents=True, exist_ok=True)
        self.settings.chroma_dir.mkdir(parents=True, exist_ok=True)
        self.settings.preview_pdf_dir.mkdir(parents=True, exist_ok=True)

    def reset_collection(self) -> None:
        self._vector_store = None
        client = self._build_chroma_client()
        try:
            client.delete_collection(name=self.settings.collection_name)
        except Exception:
            # Normal on first launch or missing collection.
            pass
        self._vector_store = self._build_vector_store()

    def _db_index_metadata_for_path(self, path: Path) -> dict[str, Any] | None:
        try:
            relative_source = self._relative_source_path(path.resolve())
            metadata = self.document_library.get_index_metadata_by_storage_path(relative_source)
        except Exception as exc:
            logger.warning("Failed to load document DB metadata for indexing. path=%s error=%s", path, exc)
            return None
        if not metadata:
            logger.warning("Skip indexing file without DB document metadata. path=%s", path)
            return None
        return metadata

    def _attach_index_metadata(self, documents: list[Document], metadata: dict[str, Any]) -> list[Document]:
        if not metadata:
            return documents
        return [
            Document(page_content=document.page_content, metadata={**document.metadata, **metadata})
            for document in documents
        ]

    def _collect_file_ids_from_documents(self, documents: list[Document]) -> list[int]:
        file_ids: list[int] = []
        seen: set[int] = set()
        for document in documents:
            metadata = document.metadata or {}
            raw_file_id = metadata.get("file_id")
            try:
                file_id = int(raw_file_id)
            except Exception:
                continue
            if file_id in seen:
                continue
            seen.add(file_id)
            file_ids.append(file_id)
        return file_ids

    def load_corpus(self) -> tuple[list[Document], list[str]]:
        documents: list[Document] = []
        loaded_files: list[str] = []

        for path in iter_source_files():
            docs = load_documents_from_file(path)
            if not docs:
                continue
            index_metadata = self._db_index_metadata_for_path(path)
            if index_metadata is None:
                continue
            docs = self._attach_index_metadata(docs, index_metadata)
            documents.extend(docs)
            loaded_files.append(str(path.relative_to(self.settings.root_dir)).replace("\\", "/"))

        return documents, loaded_files

    def split_documents(self, documents: list[Document]) -> list[Document]:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.settings.chunk_size,
            chunk_overlap=self.settings.chunk_overlap,
            separators=[
                "\n\n",
                "\n",
                ".",
                "!",
                "?",
                ";",
                "\u3002",
                "\uFF01",
                "\uFF1F",
                "\uFF1B",
                " ",
                "",
            ],
        )
        chunks = splitter.split_documents(documents)
        for index, chunk in enumerate(chunks, start=1):
            chunk.metadata["chunk_index"] = index
            chunk.metadata["char_count"] = len(chunk.page_content)
        return chunks

    def _hash_chunk(self, content: str, metadata: dict[str, Any]) -> str:
        payload = json.dumps({"content": content, "metadata": metadata}, ensure_ascii=False, sort_keys=True)
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()

    def _format_preview(self, text: str, length: int = 220) -> str:
        normalized = " ".join(text.split())
        if len(normalized) <= length:
            return normalized
        return normalized[: length - 1] + "..."

    def _normalize_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in metadata.items() if value not in (None, "")}

    def _relative_source_path(self, path: Path) -> str:
        return str(path.resolve().relative_to(self.settings.root_dir)).replace("\\", "/")

    def _upsert_chunks(self, chunks: list[Document]) -> None:
        if not chunks:
            return
        batch_size = 64
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            ids: list[str] = []
            normalized_docs: list[Document] = []
            for chunk in batch:
                metadata = self._normalize_metadata(chunk.metadata)
                ids.append(self._hash_chunk(chunk.page_content, metadata))
                normalized_docs.append(Document(page_content=chunk.page_content, metadata=metadata))
            try:
                self.vector_store.add_documents(documents=normalized_docs, ids=ids)
            except Exception as exc:
                if not self._is_missing_chroma_collection_error(exc):
                    raise
                self._vector_store = self._build_vector_store()
                self.vector_store.add_documents(documents=normalized_docs, ids=ids)

    def _delete_chunks_by_source(self, source_path: str) -> None:
        client = self._build_chroma_client()
        try:
            collection = client.get_collection(name=self.settings.collection_name)
        except Exception:
            return
        try:
            collection.delete(where={"source": source_path})
        except Exception:
            # Keep callback robust across collection schema/runtime differences.
            return

    def delete_chunks_by_file_ids(self, file_ids: list[int]) -> IngestStats:
        with self._lock:
            self.ensure_directories()
            normalized_ids = sorted({int(file_id) for file_id in file_ids if file_id is not None})
            if not normalized_ids:
                return IngestStats(documents_loaded=0, chunks_indexed=self.count_chunks(), source_files=[])

            client = self._build_chroma_client()
            try:
                collection = client.get_collection(name=self.settings.collection_name)
            except Exception:
                return IngestStats(documents_loaded=0, chunks_indexed=0, source_files=[])

            deleted_refs: list[str] = []
            for file_id in normalized_ids:
                try:
                    collection.delete(where={"file_id": file_id})
                    deleted_refs.append(f"file_id:{file_id}")
                except Exception as exc:
                    logger.warning("Failed to delete Chroma chunks by file_id=%s error=%s", file_id, exc)

            return IngestStats(
                documents_loaded=0,
                chunks_indexed=self.count_chunks(),
                source_files=deleted_refs,
            )

    def rebuild_index(self) -> IngestStats:
        with self._lock:
            self.ensure_directories()
            documents, loaded_files = self.load_corpus()
            chunks = self.split_documents(documents)
            indexed_file_ids = self._collect_file_ids_from_documents(documents)

            self.reset_collection()
            if not chunks:
                if indexed_file_ids:
                    try:
                        self.document_library.update_file_index_states(indexed_file_ids, index_status="success")
                    except Exception as exc:
                        logger.warning("Failed to update file index state after empty rebuild: %s", exc)
                return IngestStats(documents_loaded=len(documents), chunks_indexed=0, source_files=loaded_files)

            self._upsert_chunks(chunks)
            if indexed_file_ids:
                try:
                    self.document_library.update_file_index_states(indexed_file_ids, index_status="success")
                except Exception as exc:
                    logger.warning("Failed to update file index state after rebuild: %s", exc)

            return IngestStats(
                documents_loaded=len(documents),
                chunks_indexed=len(chunks),
                source_files=loaded_files,
            )

    def reindex_source_file(self, path: Path) -> IngestStats:
        with self._lock:
            self.ensure_directories()
            target = path.resolve()
            if not target.exists() or not target.is_file():
                raise FileNotFoundError(f"File not found: {target}")

            relative_source = self._relative_source_path(target)

            index_metadata = self._db_index_metadata_for_path(target)
            documents = (
                self._attach_index_metadata(load_documents_from_file(target), index_metadata)
                if index_metadata is not None
                else []
            )
            chunks = self.split_documents(documents)
            indexed_file_ids = self._collect_file_ids_from_documents(documents)
            if chunks:
                # Ensure embedding/vector store can initialize before removing
                # the previous chunks for this file.
                _ = self.vector_store
            self._delete_chunks_by_source(relative_source)
            self._upsert_chunks(chunks)
            if indexed_file_ids:
                try:
                    self.document_library.update_file_index_states(indexed_file_ids, index_status="success")
                except Exception as exc:
                    logger.warning("Failed to update file index state after reindex: %s", exc)

            return IngestStats(
                documents_loaded=len(documents),
                chunks_indexed=len(chunks),
                source_files=[relative_source],
            )

    def reindex_document_files(self, *, file_ids: list[int], source_paths: list[str]) -> IngestStats:
        """Replace chunks for specific DB files and rebuild them from current metadata."""
        with self._lock:
            self.ensure_directories()
            normalized_ids = sorted({int(file_id) for file_id in file_ids if file_id is not None})
            normalized_sources: list[str] = []
            seen_sources: set[str] = set()
            for source_path in source_paths:
                normalized = str(source_path or "").strip().replace("\\", "/").strip("/")
                if not normalized or normalized in seen_sources:
                    continue
                seen_sources.add(normalized)
                normalized_sources.append(normalized)

            if normalized_ids:
                self.delete_chunks_by_file_ids(normalized_ids)

            documents_loaded = 0
            chunks_indexed = 0
            indexed_sources: list[str] = []
            indexed_file_ids: list[int] = []
            seen_file_ids: set[int] = set()
            for source_path in normalized_sources:
                target = (self.settings.root_dir / source_path).resolve()
                if not target.exists() or not target.is_file():
                    logger.warning("Skip reindexing missing document source after metadata change: %s", source_path)
                    continue

                index_metadata = self._db_index_metadata_for_path(target)
                documents = (
                    self._attach_index_metadata(load_documents_from_file(target), index_metadata)
                    if index_metadata is not None
                    else []
                )
                chunks = self.split_documents(documents)
                if chunks:
                    _ = self.vector_store
                self._delete_chunks_by_source(self._relative_source_path(target))
                self._upsert_chunks(chunks)
                for file_id in self._collect_file_ids_from_documents(documents):
                    if file_id in seen_file_ids:
                        continue
                    seen_file_ids.add(file_id)
                    indexed_file_ids.append(file_id)

                documents_loaded += len(documents)
                chunks_indexed += len(chunks)
                indexed_sources.append(source_path)

            if indexed_file_ids:
                try:
                    self.document_library.update_file_index_states(indexed_file_ids, index_status="success")
                except Exception as exc:
                    logger.warning("Failed to update file index state after document reindex: %s", exc)

            return IngestStats(
                documents_loaded=documents_loaded,
                chunks_indexed=chunks_indexed,
                source_files=indexed_sources,
            )

    def delete_source_file_and_rebuild(self, path: Path) -> IngestStats:
        with self._lock:
            self.ensure_directories()
            if not path.exists() or not path.is_file():
                raise FileNotFoundError(f"File not found: {path}")

            preview_cache_path: Path | None = None
            if path.suffix.lower() in {".doc", ".docx", ".ppt", ".pptx"}:
                try:
                    preview_cache_path = get_preview_pdf_cache_path(path)
                except Exception:
                    preview_cache_path = None

            path.unlink()
            if preview_cache_path and preview_cache_path.exists():
                preview_cache_path.unlink(missing_ok=True)

            return self.rebuild_index()

    def count_chunks(self) -> int:
        self.ensure_directories()
        client = self._build_chroma_client()
        try:
            collection = client.get_collection(name=self.settings.collection_name)
        except Exception:
            return 0

        where_filter = self._current_user_filter()
        try:
            payload = collection.get(where=where_filter, include=[]) if where_filter else collection.get(include=[])
            return len(payload.get("ids", []))
        except Exception as exc:
            if where_filter:
                logger.warning("Failed to count user-scoped Chroma chunks. filter=%s error=%s", where_filter, exc)
                return 0
        try:
            return int(collection.count())
        except Exception:
            try:
                payload = collection.get(include=[])
                return len(payload.get("ids", []))
            except Exception:
                return 0

    def _compose_search_query(self, question: str, history: list[ChatHistoryItem] | None) -> str:
        if not history:
            return question
        recent_turns = history[-6:]
        history_text = "\n".join(f"{item.role}: {item.content}" for item in recent_turns)
        return f"Conversation context:\n{history_text}\n\nCurrent question:\n{question}"

    @classmethod
    def _message_content_text(cls, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                item_type = str(item.get("type") or "")
                if item_type == "text":
                    text_value = str(item.get("text") or "").strip()
                    if text_value:
                        parts.append(text_value)
                elif item_type == "image_url":
                    image_payload = item.get("image_url")
                    image_url = image_payload.get("url") if isinstance(image_payload, dict) else image_payload
                    if image_url:
                        parts.append(cls._format_image_reference_text(str(image_url)))
                elif item_type == "file_ref":
                    parts.append(
                        "[file_ref] "
                        f"file_id={item.get('file_id') or ''} "
                        f"file_name={item.get('file_name') or ''} "
                        f"mime_type={item.get('mime_type') or ''}".strip()
                    )
            return "\n".join(parts)
        return str(content or "")

    @staticmethod
    def _normalize_message_parts(question: str, message_parts: list[ChatMessagePart] | None) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        has_text = False
        for part in message_parts or []:
            part_type = str(part.type or "text")
            if part_type == "text":
                text_value = str(part.text or "").strip()
                if text_value:
                    normalized.append({"type": "text", "text": text_value})
                    has_text = True
                continue
            if part_type == "image_url":
                image_url = str(part.image_url or "").strip()
                if image_url:
                    normalized.append({"type": "image_url", "image_url": {"url": image_url}})
                continue
            if part_type == "file_ref":
                normalized.append(
                    {
                        "type": "file_ref",
                        "file_id": part.file_id,
                        "file_name": str(part.file_name or "").strip(),
                        "mime_type": str(part.mime_type or "").strip(),
                    }
                )

        question_text = question.strip()
        if question_text and not has_text:
            normalized.insert(0, {"type": "text", "text": question_text})
        return normalized

    @classmethod
    def _message_parts_to_prompt_text(cls, message_parts: list[dict[str, Any]]) -> str:
        return cls._message_content_text(message_parts)

    @staticmethod
    def _format_image_reference_text(image_url: str) -> str:
        image_url = str(image_url or "").strip()
        if not image_url:
            return ""
        if image_url.startswith("data:image/"):
            mime_type = image_url.split(";", 1)[0].replace("data:", "", 1) or "image"
            return f"[image_url] pasted inline image ({mime_type})"
        return f"[image_url] {image_url}"

    def _message_parts_to_provider_content(
        self,
        message_parts: list[dict[str, Any]],
        fallback_text: str,
        *,
        capability: ModelCapability,
        diagnostics: dict[str, Any] | None = None,
    ) -> str | list[dict[str, Any]]:
        provider_parts: list[dict[str, Any]] = []
        file_lines: list[str] = []
        image_lines: list[str] = []
        for part in message_parts:
            part_type = str(part.get("type") or "")
            if part_type == "text":
                text_value = str(part.get("text") or "").strip()
                if text_value:
                    provider_parts.append({"type": "text", "text": text_value})
                continue
            if part_type == "image_url":
                image_payload = part.get("image_url")
                image_url = image_payload.get("url") if isinstance(image_payload, dict) else image_payload
                image_url = str(image_url or "").strip()
                if image_url:
                    if capability.supports_multimodal_input:
                        provider_parts.append({"type": "image_url", "image_url": {"url": image_url}})
                    else:
                        image_lines.append(self._format_image_reference_text(image_url))
                continue
            if part_type == "file_ref":
                file_lines.append(
                    "File reference: "
                    f"id={part.get('file_id') or ''}, "
                    f"name={part.get('file_name') or ''}, "
                    f"mime_type={part.get('mime_type') or ''}"
                )

        if image_lines:
            provider_parts.append({"type": "text", "text": "\n".join(image_lines)})
            self._append_model_diagnostic_warning(
                diagnostics,
                "当前模型未声明支持原生图片输入，图片 URL 已作为文本引用传入。",
            )
        if file_lines:
            provider_parts.append({"type": "text", "text": "\n".join(file_lines)})
        if not provider_parts:
            return fallback_text
        if len(provider_parts) == 1 and provider_parts[0].get("type") == "text":
            return str(provider_parts[0].get("text") or fallback_text)
        return provider_parts

    def _classify_question_mode(self, question: str) -> QuestionMode:
        normalized = re.sub(r"\s+", "", question.lower())

        overview_keywords = (
            "\u8bb2\u4e86\u4ec0\u4e48",
            "\u4e3b\u8981\u8bb2",
            "\u4e3b\u8981\u5185\u5bb9",
            "\u6982\u8ff0",
            "\u603b\u7ed3",
            "\u4ecb\u7ecd\u4e00\u4e0b",
            "\u6574\u4f53",
            "\u80cc\u666f\u548c\u76ee\u6807",
            "\u603b\u4f53",
            "overview",
            "summary",
            "introduction",
        )
        comparison_keywords = (
            "\u5bf9\u6bd4",
            "\u533a\u522b",
            "\u5dee\u5f02",
            "\u4e0d\u540c",
            "\u4f18\u7f3a\u70b9",
            "\u54ea\u4e2a\u597d",
            "compare",
            "vs",
        )
        list_keywords = (
            "\u5217\u51fa",
            "\u6e05\u5355",
            "\u5217\u8868",
            "\u6709\u54ea\u4e9b",
            "\u5305\u542b\u54ea\u4e9b",
            "\u5206\u7c7b",
            "list",
        )
        technical_keywords = (
            "\u6280\u672f",
            "\u7b97\u6cd5",
            "\u5b9e\u73b0",
            "\u67b6\u6784",
            "\u539f\u7406",
            "\u6d41\u7a0b",
            "\u63a5\u53e3",
            "\u4ee3\u7801",
            "\u6a21\u578b",
            "technical",
            "architecture",
        )

        if any(keyword in normalized for keyword in comparison_keywords):
            return "comparison"
        if any(keyword in normalized for keyword in list_keywords):
            return "list"
        if any(keyword in normalized for keyword in technical_keywords):
            return "technical"
        if any(keyword in normalized for keyword in overview_keywords):
            return "overview"
        return "general"

    def _build_retrieval_queries(self, question: str, rewritten_question: str, question_mode: QuestionMode) -> list[str]:
        queries: list[str] = [rewritten_question, question]

        if question_mode in ("overview", "general"):
            queries.extend(
                [
                    f"{question} project background objective scope core capabilities",
                    f"{question} system architecture modules workflow stakeholders",
                    f"{question} key technologies value risks assumptions",
                ]
            )
        elif question_mode == "technical":
            queries.extend(
                [
                    f"{question} architecture modules implementation flow parameters constraints",
                    f"{question} model algorithm interface code configuration",
                ]
            )
        elif question_mode == "comparison":
            queries.extend(
                [
                    f"{question} comparison dimensions differences tradeoffs costs risks",
                    f"{question} advantages disadvantages use cases recommendation",
                ]
            )
        elif question_mode == "list":
            queries.extend(
                [
                    f"{question} list categories items checklist",
                    f"{question} composition structure details",
                ]
            )

        deduped: list[str] = []
        seen: set[str] = set()
        for query in queries:
            cleaned = query.strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            deduped.append(cleaned)
        return deduped

    def _is_code_heavy(self, text: str) -> bool:
        lowered = text.lower()
        code_markers = (
            "def ",
            "class ",
            "import ",
            "from ",
            "keras",
            "tensorflow",
            "torch",
            "yolo",
            "conv2d",
            "dropout(",
            "relu",
            "optimizer",
            "epoch",
            "model.",
            "model.add",
            "return ",
        )
        marker_hits = sum(1 for marker in code_markers if marker in lowered)
        symbol_count = sum(1 for char in text if char in "{}[]();=<>\t")
        length = max(len(text), 1)
        symbol_ratio = symbol_count / length
        ascii_ratio = sum(1 for char in text if char.isascii()) / length

        return marker_hits >= 3 or (marker_hits >= 1 and symbol_ratio >= 0.03 and ascii_ratio >= 0.45)

    def _metadata_int(self, metadata: dict[str, Any], key: str) -> int | None:
        value = metadata.get(key)
        if value is None or value == "":
            return None
        try:
            return int(value)
        except Exception:
            return None

    def _search_hit_from_document(self, doc: Document, relevance: float | None) -> SearchHit:
        metadata = doc.metadata or {}
        score = float(relevance) if relevance is not None else 0.0
        return SearchHit(
            source=str(metadata.get("source", "unknown")),
            chunk_index=int(metadata.get("chunk_index", 0)),
            page=self._metadata_int(metadata, "page"),
            score=round(score, 4) if relevance is not None else None,
            preview=self._format_preview(doc.page_content),
            content=doc.page_content,
            file_id=self._metadata_int(metadata, "file_id"),
            folder_id=self._metadata_int(metadata, "folder_id"),
            display_name=str(metadata.get("display_name") or "") or None,
            display_path=str(metadata.get("display_path") or "") or None,
            folder_path=str(metadata.get("folder_path") or "") or None,
        )

    def _retrieve_candidates(
        self,
        queries: list[str],
        per_query_limit: int,
        *,
        scope_type: str = "all",
        scope_id: int | None = None,
        workspace_key: str | None = None,
    ) -> list[SearchHit]:
        if self.count_chunks() == 0:
            return []

        best_hits: dict[tuple[str, int | None, int], SearchHit] = {}
        best_scores: dict[tuple[str, int | None, int], float] = {}

        for query in queries:
            results = self._similarity_search_for_current_user(
                query=query,
                k=per_query_limit,
                scope_type=scope_type,
                scope_id=scope_id,
                workspace_key=workspace_key,
            )
            for doc, relevance in results:
                metadata = doc.metadata or {}
                score = float(relevance) if relevance is not None else 0.0
                key = (
                    str(metadata.get("source", "unknown")),
                    self._metadata_int(metadata, "page"),
                    int(metadata.get("chunk_index", 0)),
                )

                hit = self._search_hit_from_document(doc, relevance)

                previous_score = best_scores.get(key, -1.0)
                if score > previous_score:
                    best_scores[key] = score
                    best_hits[key] = hit

        ordered_keys = sorted(best_scores.keys(), key=lambda item: best_scores[item], reverse=True)
        return [best_hits[key] for key in ordered_keys]

    def _select_hits_for_answer(self, candidates: list[SearchHit], limit: int, question_mode: QuestionMode) -> list[SearchHit]:
        if not candidates:
            return []

        if question_mode == "technical":
            return candidates[:limit]

        non_code_hits = [hit for hit in candidates if not self._is_code_heavy(hit.content)]
        pool = candidates
        if question_mode in ("overview", "comparison", "list", "general") and len(non_code_hits) >= max(4, limit // 2):
            pool = non_code_hits

        selected: list[SearchHit] = []
        used_pages: set[int] = set()
        used_keys: set[tuple[str, int | None, int]] = set()

        for hit in pool:
            key = (hit.source, hit.page, hit.chunk_index)
            if key in used_keys:
                continue
            if hit.page is not None and hit.page in used_pages:
                continue
            selected.append(hit)
            used_keys.add(key)
            if hit.page is not None:
                used_pages.add(hit.page)
            if len(selected) >= limit:
                break

        if len(selected) < limit:
            for hit in pool:
                key = (hit.source, hit.page, hit.chunk_index)
                if key in used_keys:
                    continue
                selected.append(hit)
                used_keys.add(key)
                if len(selected) >= limit:
                    break

        if len(selected) < limit:
            for hit in candidates:
                key = (hit.source, hit.page, hit.chunk_index)
                if key in used_keys:
                    continue
                selected.append(hit)
                used_keys.add(key)
                if len(selected) >= limit:
                    break

        return sorted(
            selected,
            key=lambda hit: (
                hit.page is None,
                hit.page if hit.page is not None else 10**9,
                -(hit.score or 0.0),
            ),
        )

    def _context_excerpt_limit(self, question_mode: QuestionMode) -> int:
        if question_mode == "overview":
            return 1200
        if question_mode == "comparison":
            return 1000
        if question_mode == "list":
            return 900
        if question_mode == "technical":
            return 1400
        return 1000

    def _truncate_for_context(self, text: str, limit: int) -> str:
        normalized = text.strip()
        if len(normalized) <= limit:
            return normalized
        return normalized[: limit - 1] + "..."

    def _group_hits_for_context(
        self,
        hits: list[SearchHit],
        question_mode: QuestionMode,
        max_groups: int,
    ) -> list[dict[str, Any]]:
        group_map: dict[tuple[str, int | None], dict[str, Any]] = {}
        order_keys: list[tuple[str, int | None]] = []

        for hit in hits:
            key = (hit.source, hit.page)
            if key not in group_map:
                group_map[key] = {
                    "source": hit.source,
                    "page": hit.page,
                    "score": hit.score or 0.0,
                    "file_id": hit.file_id,
                    "folder_id": hit.folder_id,
                    "display_name": hit.display_name,
                    "display_path": hit.display_path,
                    "folder_path": hit.folder_path,
                    "hits": [],
                }
                order_keys.append(key)

            group = group_map[key]
            group["score"] = max(float(group["score"]), float(hit.score or 0.0))
            if len(group["hits"]) < 2:
                group["hits"].append(hit)

        groups = [group_map[key] for key in order_keys]
        if question_mode in ("overview", "general"):
            groups.sort(key=lambda item: (item["page"] is None, item["page"] if item["page"] is not None else 10**9, -item["score"]))
        else:
            groups.sort(key=lambda item: (-item["score"], item["page"] is None, item["page"] if item["page"] is not None else 10**9))

        return groups[:max_groups]

    def retrieve(
        self,
        query: str,
        top_k: int | None = None,
        *,
        scope_type: str = "all",
        scope_id: int | None = None,
        workspace_key: str | None = None,
    ) -> list[SearchHit]:
        if self.count_chunks() == 0:
            return []

        limit = top_k or self.settings.top_k
        results = self._similarity_search_for_current_user(
            query=query,
            k=limit,
            scope_type=scope_type,
            scope_id=scope_id,
            workspace_key=workspace_key,
        )

        hits: list[SearchHit] = []
        for doc, relevance in results:
            hits.append(self._search_hit_from_document(doc, relevance))
        return hits

    def search(
        self,
        query: str,
        top_k: int | None = None,
        *,
        scope_type: str = "all",
        scope_id: int | None = None,
        workspace_key: str | None = None,
    ) -> list[SearchHit]:
        return self.retrieve(
            query=query,
            top_k=top_k,
            scope_type=scope_type,
            scope_id=scope_id,
            workspace_key=workspace_key,
        )

    def _build_context(self, hits: list[SearchHit], question_mode: QuestionMode) -> tuple[str, str, list[dict[str, Any]]]:
        groups = self._group_hits_for_context(hits=hits, question_mode=question_mode, max_groups=max(6, min(12, len(hits))))
        excerpt_limit = self._context_excerpt_limit(question_mode)

        blocks: list[str] = []
        citation_lines: list[str] = []
        citation_items: list[dict[str, Any]] = []
        for index, group in enumerate(groups, start=1):
            label = f"S{index}"
            source = group["source"]
            page = group["page"]
            score = round(float(group["score"]), 4)
            page_text = f"page={page}" if page is not None else "page=unknown"
            display_source = str(group.get("display_path") or source)
            citation_lines.append(f"[{label}] {display_source}, {page_text}")
            citation_items.append(
                {
                    "label": label,
                    "source": source,
                    "page": page,
                    "chunk_indices": [int(hit.chunk_index) for hit in group["hits"]],
                    "score": score,
                    "preview": group["hits"][0].preview if group["hits"] else "",
                    "file_id": group.get("file_id"),
                    "folder_id": group.get("folder_id"),
                    "display_name": group.get("display_name"),
                    "display_path": group.get("display_path"),
                    "folder_path": group.get("folder_path"),
                }
            )

            excerpts: list[str] = []
            for hit in group["hits"]:
                score_part = f", score={hit.score}" if hit.score is not None else ""
                snippets = self._truncate_for_context(hit.content, excerpt_limit)
                excerpts.append(f"- chunk={hit.chunk_index}{score_part}\n{snippets}")

            blocks.append(
                f"[{label}] source={display_source}, storage_source={source}, {page_text}, group_score={score}\n"
                + "\n".join(excerpts)
            )

        context = "\n\n".join(blocks)
        citation_guide = "\n".join(citation_lines)
        return context, citation_guide, citation_items

    def _request_json(
        self,
        *,
        url: str,
        method: str,
        headers: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
        timeout_sec: int = 12,
    ) -> dict[str, Any]:
        body: bytes | None = None
        request_headers = dict(headers or {})
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")

        req = urllib_request.Request(
            url=url,
            data=body,
            headers=request_headers,
            method=method.upper(),
        )
        with urllib_request.urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            if not raw:
                return {}
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
            return {"data": parsed}

    def _search_serper(self, query: str, top_k: int) -> list[WebSearchHit]:
        api_key = self.settings.web_search_api_key
        if not api_key:
            return []

        data = self._request_json(
            url="https://google.serper.dev/search",
            method="POST",
            headers={"X-API-KEY": api_key},
            payload={"q": query, "num": max(1, min(top_k, 10))},
            timeout_sec=12,
        )
        results = data.get("organic")
        if not isinstance(results, list):
            return []

        hits: list[WebSearchHit] = []
        for item in results[:top_k]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).strip()
            link = str(item.get("link", "")).strip()
            snippet = str(item.get("snippet", "")).strip()
            if not link:
                continue
            hits.append(WebSearchHit(title=title or link, url=link, snippet=snippet))
        return hits

    def _search_tavily(self, query: str, top_k: int) -> list[WebSearchHit]:
        api_key = self.settings.web_search_api_key
        if not api_key:
            return []

        data = self._request_json(
            url="https://api.tavily.com/search",
            method="POST",
            payload={
                "api_key": api_key,
                "query": query,
                "search_depth": "basic",
                "max_results": max(1, min(top_k, 10)),
                "include_answer": False,
                "include_raw_content": False,
            },
            timeout_sec=12,
        )
        results = data.get("results")
        if not isinstance(results, list):
            return []

        hits: list[WebSearchHit] = []
        for item in results[:top_k]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).strip()
            url = str(item.get("url", "")).strip()
            snippet = str(item.get("content", "")).strip()
            if not url:
                continue
            hits.append(WebSearchHit(title=title or url, url=url, snippet=snippet))
        return hits

    def _search_web(self, query: str, top_k: int) -> list[WebSearchHit]:
        provider = self.settings.web_search_provider
        if provider == "none":
            return []

        try:
            if provider == "serper":
                return self._search_serper(query=query, top_k=top_k)
            if provider == "tavily":
                return self._search_tavily(query=query, top_k=top_k)
        except (urllib_error.HTTPError, urllib_error.URLError, TimeoutError, json.JSONDecodeError):
            return []
        except Exception:
            return []
        return []

    def _build_web_context(self, web_hits: list[WebSearchHit]) -> tuple[str, list[dict[str, Any]]]:
        if not web_hits:
            return "", []

        blocks: list[str] = []
        citations: list[dict[str, Any]] = []
        for index, hit in enumerate(web_hits, start=1):
            label = f"W{index}"
            snippet = self._truncate_for_context(hit.snippet or hit.title, 560)
            blocks.append(f"[{label}] title={hit.title}\nurl={hit.url}\nsnippet={snippet}")
            citations.append(
                {
                    "label": label,
                    "source": hit.url,
                    "page": None,
                    "chunk_indices": [],
                    "score": None,
                    "preview": snippet,
                }
            )
        return "\n\n".join(blocks), citations

    def _build_system_prompt(self, question_mode: QuestionMode, thinking_mode: ThinkingMode) -> str:
        base_rules = (
            "You are a helpful assistant. "
            "Prefer evidence from the provided knowledge base and web context when available. "
            "If there is no relevant evidence, still answer using general knowledge instead of refusing. "
            "Do not fabricate citations. Only use [Sx]/[Wx] labels when evidence truly exists. "
            "Answer in the same language as the user. "
            "Do not add role-playing preambles like 'I am an enterprise knowledge base assistant' unless asked."
        )

        mode_rules: dict[QuestionMode, str] = {
            "overview": (
                "For overview questions, answer with: summary, background, key scope, core capabilities, and practical value."
            ),
            "technical": (
                "For technical questions, answer with: architecture, modules, flow, key parameters/constraints, and risks."
            ),
            "comparison": (
                "For comparison questions, answer with: dimensions, differences, trade-offs, and recommendation."
            ),
            "list": "For list questions, group items by topic and keep coverage complete.",
            "general": "State the conclusion first, then concise supporting points.",
        }

        depth_rule = (
            " Keep the answer concise."
            if thinking_mode == "quick"
            else " Provide a deeper and more complete answer."
        )
        return f"{base_rules} {mode_rules[question_mode]}{depth_rule}"

    def _is_model_identity_question(self, question: str) -> bool:
        normalized = re.sub(r"\s+", "", question.lower())
        keywords = (
            "你是什么模型",
            "你是啥模型",
            "你现在用的什么模型",
            "你调用的什么模型",
            "你调用的是哪个模型",
            "你用的是什么模型",
            "你用的是哪个模型",
            "当前模型",
            "实际模型",
            "后端模型",
            "你是不是千问",
            "你是不是qwen",
            "你是不是deepseek",
            "whatmodel",
            "whichmodel",
            "modelareyou",
        )
        return any(keyword in normalized for keyword in keywords)

    def _build_model_identity_answer(self, model_name: str) -> str:
        provider = self._resolve_provider_name(model_name)
        return (
            f"当前这次回答后端实际路由到的模型是：{model_name}\n"
            f"Provider：{provider}\n"
            "说明：模型正文里的自我介绍不一定可靠，请以后端返回的模型诊断信息为准。"
        )

    def _build_model_diagnostics(
        self,
        *,
        requested_model: str | None,
        model_name: str,
        provider: str,
        resolved_model: str | None = None,
        native_web_search_used: bool = False,
        external_web_search_used: bool = False,
        thinking_mode: ThinkingMode = "quick",
    ) -> dict[str, Any]:
        capability = self._resolve_model_capability(model_name=model_name, provider=provider)
        return {
            "requested_model": requested_model or model_name,
            "provider": provider,
            "resolved_model": resolved_model or model_name,
            "native_web_search_used": bool(native_web_search_used),
            "external_web_search_used": bool(external_web_search_used),
            "thinking_mode": thinking_mode,
            "provider_api": "chat_completions",
            "capabilities": {
                "supports_native_web_search": capability.supports_native_web_search,
                "supports_tool_calling": capability.supports_tool_calling,
                "supports_multimodal_input": capability.supports_multimodal_input,
                "supports_responses_api": capability.supports_responses_api,
                "supports_responses_streaming": capability.supports_responses_streaming,
                "thinking_style": capability.thinking_style,
            },
            "option_fallback_used": False,
            "warnings": [],
        }

    def _should_polish_answer(self, answer: str, question_mode: QuestionMode, thinking_mode: ThinkingMode) -> bool:
        compact = re.sub(r"\s+", "", answer)
        if len(compact) < 120:
            return True
        if question_mode in ("overview", "comparison", "list") and len(compact) < 260:
            return True
        if thinking_mode == "deep" and len(compact) < 360:
            return True
        label_mentions = len(re.findall(r"\[[SW]\d+\]", answer))
        if question_mode in ("overview", "comparison") and label_mentions <= 1:
            return True
        return False

    def _chat_completion(
        self,
        *,
        model_name: str,
        messages: list[dict[str, Any]],
        thinking_mode: ThinkingMode,
        stream: bool,
        native_web_search: bool = False,
        diagnostics: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ):
        adapter = self._resolve_model_adapter(model_name)
        return adapter.create_chat_completion(
            model_name=model_name,
            messages=messages,
            thinking_mode=thinking_mode,
            stream=stream,
            native_web_search=native_web_search,
            diagnostics=diagnostics,
            tools=tools,
            tool_choice=tool_choice,
        )

    def _build_tool_registry(
        self,
        *,
        include_web_search: bool = False,
        scope_type: str = "all",
        scope_id: int | None = None,
        workspace_key: str | None = None,
    ) -> ToolRegistry:
        return build_readonly_tool_registry(
            search_knowledge_base=lambda query, top_k: self.search(
                query=query,
                top_k=top_k,
                scope_type=scope_type,
                scope_id=scope_id,
                workspace_key=workspace_key,
            ),
            search_web=self._search_web,
            web_search_available=self.is_web_search_available,
            include_web_search=include_web_search,
        )

    @staticmethod
    def _parse_tool_arguments(raw_arguments: Any) -> dict[str, Any]:
        if isinstance(raw_arguments, dict):
            return raw_arguments
        if raw_arguments is None:
            return {}
        try:
            parsed = json.loads(str(raw_arguments or "{}"))
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _append_tool_diagnostic(self, diagnostics: dict[str, Any] | None, tool_name: str) -> None:
        if diagnostics is None:
            return
        tool_calls = diagnostics.setdefault("tool_calls", [])
        if isinstance(tool_calls, list):
            tool_calls.append({"name": tool_name})

    def _append_model_diagnostic_warning(self, diagnostics: dict[str, Any] | None, message: str) -> None:
        if diagnostics is None:
            return
        warnings = diagnostics.setdefault("warnings", [])
        if isinstance(warnings, list) and message not in warnings:
            warnings.append(message)

    def _chat_completion_with_tools(
        self,
        *,
        model_name: str,
        messages: list[dict[str, Any]],
        thinking_mode: ThinkingMode,
        native_web_search: bool,
        diagnostics: dict[str, Any] | None,
        tool_registry: ToolRegistry | None,
        max_tool_rounds: int = 2,
    ):
        if tool_registry is None or tool_registry.is_empty():
            return self._chat_completion(
                model_name=model_name,
                messages=messages,
                thinking_mode=thinking_mode,
                stream=False,
                native_web_search=native_web_search,
                diagnostics=diagnostics,
            )

        tool_messages = [dict(message) for message in messages]
        tools = tool_registry.openai_tools()
        try:
            completion = self._chat_completion(
                model_name=model_name,
                messages=tool_messages,
                thinking_mode=thinking_mode,
                stream=False,
                native_web_search=native_web_search,
                diagnostics=diagnostics,
                tools=tools,
                tool_choice="auto",
            )
        except Exception as exc:
            self._append_model_diagnostic_warning(
                diagnostics,
                f"模型工具调用初始化失败，已退回普通模型回答：{exc}",
            )
            return self._chat_completion(
                model_name=model_name,
                messages=messages,
                thinking_mode=thinking_mode,
                stream=False,
                native_web_search=native_web_search,
                diagnostics=diagnostics,
            )

        for _ in range(max_tool_rounds):
            message = completion.choices[0].message
            tool_calls = getattr(message, "tool_calls", None) or []
            if not tool_calls:
                return completion

            tool_messages.append(message.model_dump(exclude_none=True))
            for tool_call in tool_calls:
                function = getattr(tool_call, "function", None)
                tool_name = str(getattr(function, "name", "") or "")
                arguments = self._parse_tool_arguments(getattr(function, "arguments", "{}"))
                tool_result = tool_registry.execute(tool_name, arguments)
                self._append_tool_diagnostic(diagnostics, tool_name)
                tool_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": getattr(tool_call, "id", ""),
                        "content": tool_result,
                    }
                )

            try:
                completion = self._chat_completion(
                    model_name=model_name,
                    messages=tool_messages,
                    thinking_mode=thinking_mode,
                    stream=False,
                    native_web_search=native_web_search,
                    diagnostics=diagnostics,
                    tools=tools,
                    tool_choice="auto",
                )
            except Exception as exc:
                self._append_model_diagnostic_warning(
                    diagnostics,
                    f"工具结果回传模型失败，已退回普通模型回答：{exc}",
                )
                return self._chat_completion(
                    model_name=model_name,
                    messages=messages,
                    thinking_mode=thinking_mode,
                    stream=False,
                    native_web_search=native_web_search,
                    diagnostics=diagnostics,
                )

        return completion

    @staticmethod
    def _extract_message_reasoning_parts(message: Any) -> list[str]:
        parts: list[str] = []
        for attr_name in ("reasoning_content", "reasoning", "reasoning_text", "reasoning_details", "reasoning_detail"):
            value = getattr(message, attr_name, None)
            if isinstance(value, str) and value.strip():
                parts.append(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        text = item.get("text") or item.get("content") or item.get("reasoning_content")
                        if str(text or "").strip():
                            parts.append(str(text))
                    elif str(item).strip():
                        parts.append(str(item))
            elif isinstance(value, dict):
                text = value.get("text") or value.get("content") or value.get("reasoning_content")
                if str(text or "").strip():
                    parts.append(str(text))
        return parts

    @staticmethod
    def _merge_tool_call_delta(
        state: dict[int, dict[str, Any]],
        tool_call: Any,
    ) -> None:
        index = int(getattr(tool_call, "index", 0) or 0)
        item = state.setdefault(
            index,
            {
                "id": "",
                "type": "function",
                "function": {"name": "", "arguments": ""},
            },
        )
        tool_call_id = str(getattr(tool_call, "id", "") or "")
        if tool_call_id:
            item["id"] = tool_call_id
        tool_type = str(getattr(tool_call, "type", "") or "")
        if tool_type:
            item["type"] = tool_type

        function = getattr(tool_call, "function", None)
        if function is None:
            return
        name = str(getattr(function, "name", "") or "")
        arguments = str(getattr(function, "arguments", "") or "")
        if name:
            item["function"]["name"] += name
        if arguments:
            item["function"]["arguments"] += arguments

    @staticmethod
    def _tool_call_state_to_messages(state: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        for index in sorted(state):
            item = state[index]
            messages.append(
                {
                    "id": item.get("id") or f"tool_call_{index}",
                    "type": item.get("type") or "function",
                    "function": {
                        "name": str((item.get("function") or {}).get("name") or ""),
                        "arguments": str((item.get("function") or {}).get("arguments") or "{}"),
                    },
                }
            )
        return messages

    def _execute_tool_call_messages(
        self,
        *,
        tool_calls: list[dict[str, Any]],
        tool_registry: ToolRegistry,
        diagnostics: dict[str, Any] | None,
    ) -> tuple[list[dict[str, Any]], list[StreamingEvent]]:
        tool_result_messages: list[dict[str, Any]] = []
        events: list[StreamingEvent] = []
        for tool_call in tool_calls:
            function = tool_call.get("function") or {}
            tool_name = str(function.get("name") or "")
            arguments = self._parse_tool_arguments(function.get("arguments"))
            self._append_tool_diagnostic(diagnostics, tool_name)
            events.append(
                tool_call_delta(
                    {
                        "id": tool_call.get("id") or "",
                        "name": tool_name,
                        "arguments": arguments,
                    }
                )
            )
            tool_result = tool_registry.execute(tool_name, arguments)
            tool_result_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.get("id") or "",
                    "content": tool_result,
                }
            )
        return tool_result_messages, events

    def _stream_completion_with_tools(
        self,
        *,
        model_name: str,
        messages: list[dict[str, Any]],
        thinking_mode: ThinkingMode,
        native_web_search: bool,
        diagnostics: dict[str, Any],
        tool_registry: ToolRegistry | None,
        reasoning_parts: list[str] | None = None,
        max_tool_rounds: int = 2,
    ) -> Iterator[StreamingEvent]:
        if tool_registry is None or tool_registry.is_empty():
            stream = self._chat_completion(
                model_name=model_name,
                messages=messages,
                thinking_mode=thinking_mode,
                stream=True,
                native_web_search=native_web_search,
                diagnostics=diagnostics,
            )
            yield from self._consume_content_stream(
                stream=stream,
                diagnostics=diagnostics,
                reasoning_parts=reasoning_parts,
            )
            return

        tool_messages = [dict(message) for message in messages]
        tools = tool_registry.openai_tools()

        for round_index in range(max_tool_rounds + 1):
            try:
                stream = self._chat_completion(
                    model_name=model_name,
                    messages=tool_messages,
                    thinking_mode=thinking_mode,
                    stream=True,
                    native_web_search=native_web_search,
                    diagnostics=diagnostics,
                    tools=tools,
                    tool_choice="auto",
                )
            except Exception as exc:
                self._append_model_diagnostic_warning(
                    diagnostics,
                    f"流式工具调用初始化失败，已退回普通流式回答：{exc}",
                )
                fallback_stream = self._chat_completion(
                    model_name=model_name,
                    messages=messages,
                    thinking_mode=thinking_mode,
                    stream=True,
                    native_web_search=native_web_search,
                    diagnostics=diagnostics,
                )
                yield from self._consume_content_stream(
                    stream=fallback_stream,
                    diagnostics=diagnostics,
                    reasoning_parts=reasoning_parts,
                )
                return

            tool_call_state: dict[int, dict[str, Any]] = {}
            assistant_content_parts: list[str] = []
            for event in self._consume_content_stream(
                stream=stream,
                diagnostics=diagnostics,
                tool_call_state=tool_call_state,
                collected=assistant_content_parts,
                reasoning_parts=reasoning_parts,
            ):
                yield event

            tool_calls = self._tool_call_state_to_messages(tool_call_state)
            if not tool_calls:
                return

            if round_index >= max_tool_rounds:
                self._append_model_diagnostic_warning(
                    diagnostics,
                    "模型工具调用轮数超过限制，已停止继续调用工具。",
                )
                return

            tool_messages.append(
                {
                    "role": "assistant",
                    "content": "".join(assistant_content_parts),
                    "tool_calls": tool_calls,
                }
            )
            tool_result_messages, tool_events = self._execute_tool_call_messages(
                tool_calls=tool_calls,
                tool_registry=tool_registry,
                diagnostics=diagnostics,
            )
            for event in tool_events:
                yield event
            tool_messages.extend(tool_result_messages)

    def _consume_content_stream(
        self,
        *,
        stream: Any,
        diagnostics: dict[str, Any],
        tool_call_state: dict[int, dict[str, Any]] | None = None,
        collected: list[str] | None = None,
        reasoning_parts: list[str] | None = None,
    ) -> Iterator[StreamingEvent]:
        for chunk in stream:
            chunk_model = getattr(chunk, "model", None)
            if chunk_model:
                diagnostics["resolved_model"] = str(chunk_model)

            if not chunk.choices:
                continue

            delta_piece = chunk.choices[0].delta
            for tool_call in getattr(delta_piece, "tool_calls", None) or []:
                if tool_call_state is not None:
                    self._merge_tool_call_delta(tool_call_state, tool_call)

            reasoning_content = (
                getattr(delta_piece, "reasoning_content", None)
                or getattr(delta_piece, "reasoning", None)
                or getattr(delta_piece, "reasoning_text", None)
            )
            if reasoning_content:
                text = str(reasoning_content)
                if reasoning_parts is not None:
                    reasoning_parts.append(text)
                yield reasoning_delta(text)
                continue

            delta = delta_piece.content or ""
            if not delta:
                continue
            if collected is not None:
                collected.append(delta)
            yield content_delta(delta)

    def _polish_answer(
        self,
        *,
        answer: str,
        question: str,
        question_mode: QuestionMode,
        citation_guide: str,
        model_name: str,
        thinking_mode: ThinkingMode,
    ) -> str:
        polish_system_prompt = (
            "You are a response editor. Improve structure and readability without changing facts. "
            "Do not add unsupported facts. Keep citation markers [Sx]/[Wx] only when they already exist."
        )
        polish_user_prompt = f"""Original question:\n{question}\n\nQuestion mode:\n{question_mode}\n\nEvidence labels:\n{citation_guide}\n\nDraft answer:\n{answer}\n\nRequirements:\n1) Keep facts unchanged\n2) Improve clarity and structure\n3) Keep or improve citation marker placement\n4) Do not invent new facts"""

        completion = self._chat_completion(
            model_name=model_name,
            messages=[
                {"role": "system", "content": polish_system_prompt},
                {"role": "user", "content": polish_user_prompt},
            ],
            thinking_mode=thinking_mode,
            stream=False,
            native_web_search=False,
        )
        polished_text = (completion.choices[0].message.content or "").strip()
        if not polished_text:
            return answer
        return polished_text

    def _prepare_answer(
        self,
        *,
        question: str,
        message_parts: list[ChatMessagePart] | None,
        history: list[ChatHistoryItem] | None,
        top_k: int | None,
        web_search: bool,
        capability: ModelCapability,
        diagnostics: dict[str, Any] | None,
        scope_type: str = "all",
        scope_id: int | None = None,
        workspace_key: str | None = None,
    ) -> dict[str, Any]:
        normalized_parts = self._normalize_message_parts(question, message_parts)
        prompt_question = self._message_parts_to_prompt_text(normalized_parts) or question
        provider_content = self._message_parts_to_provider_content(
            normalized_parts,
            fallback_text=prompt_question,
            capability=capability,
            diagnostics=diagnostics,
        )
        rewritten_question = self._compose_search_query(prompt_question, history)
        question_mode = self._classify_question_mode(prompt_question)
        requested_top_k = top_k or self.settings.top_k

        per_query_limit = max(requested_top_k, 4)
        if question_mode in ("overview", "comparison", "list", "general"):
            per_query_limit = max(requested_top_k * 3, 12)
        elif question_mode == "technical":
            per_query_limit = max(requested_top_k * 2, 8)

        queries = self._build_retrieval_queries(
            question=prompt_question,
            rewritten_question=rewritten_question,
            question_mode=question_mode,
        )
        candidates = self._retrieve_candidates(
            queries=queries,
            per_query_limit=per_query_limit,
            scope_type=scope_type,
            scope_id=scope_id,
            workspace_key=workspace_key,
        )

        answer_hit_limit = max(requested_top_k, 4)
        if question_mode in ("overview", "comparison", "list", "general"):
            answer_hit_limit = max(requested_top_k * 2, 8)
        elif question_mode == "technical":
            answer_hit_limit = max(requested_top_k * 2, 6)

        hits = self._select_hits_for_answer(candidates=candidates, limit=answer_hit_limit, question_mode=question_mode)

        web_context = ""
        web_citations: list[dict[str, Any]] = []
        if web_search and self.is_web_search_available():
            web_hits = self._search_web(prompt_question, top_k=max(1, min(self.settings.web_search_top_k, 8)))
            web_context, web_citations = self._build_web_context(web_hits)

        if not hits and not web_context:
            # No retrieval evidence: fall back to normal model chat while keeping structured prompt context.
            pass

        context = ""
        citation_items: list[dict[str, Any]] = []
        if hits:
            context, _, citation_items = self._build_context(hits, question_mode=question_mode)

        combined_citations = [*citation_items, *web_citations]
        citation_lines = [f"[{item['label']}] {item['source']}" for item in combined_citations]
        combined_citation_guide = "\n".join(citation_lines)

        history_text = "\n".join(f"{item.role}: {item.content}" for item in (history or []))
        user_prompt_parts = [
            f"Question:\n{prompt_question}",
            f"Conversation history:\n{history_text or '(none)'}",
            f"Question mode:\n{question_mode}",
            f"Evidence labels:\n{combined_citation_guide or '(none)'}",
            f"Knowledge-base context:\n{context or '(none)'}",
            "Instruction: Prioritize the provided evidence when relevant. "
            "If evidence is missing or irrelevant, answer normally using general model knowledge. "
            "Answer the question directly without unnecessary self-introduction.",
        ]
        if web_context:
            user_prompt_parts.append(f"External web context:\n{web_context}")

        messages: list[dict[str, Any]] = [{"role": "system", "content": ""}]
        has_native_image_part = capability.supports_multimodal_input and any(
            part.get("type") == "image_url" for part in normalized_parts
        )
        if has_native_image_part and isinstance(provider_content, list):
            messages.append({"role": "user", "content": provider_content})
        messages.append({"role": "user", "content": "\n\n".join(user_prompt_parts)})

        return {
            "fallback_answer": None,
            "rewritten_question": rewritten_question,
            "hits": hits,
            "citations": combined_citations,
            "question_mode": question_mode,
            "citation_guide": combined_citation_guide,
            "messages": messages,
            "prompt_question": prompt_question,
            "message_parts": normalized_parts,
        }

    def answer(
        self,
        question: str,
        history: list[ChatHistoryItem] | None = None,
        top_k: int | None = None,
        model: str | None = None,
        thinking_mode: ThinkingMode = "quick",
        web_search: bool = False,
        native_web_search: bool = False,
        external_web_search: bool = False,
        scope_type: str = "all",
        scope_id: int | None = None,
        workspace_key: str | None = None,
        message_parts: list[ChatMessagePart] | None = None,
    ) -> dict[str, Any]:
        model_name = self.resolve_model(model)
        provider = self._resolve_model_provider(model_name)
        if self._is_model_identity_question(question):
            fallback_answer = self._build_model_identity_answer(model_name)
            usage = self._normalize_usage(
                None,
                prompt_fallback_text=question,
                completion_fallback_text=fallback_answer,
            )
            diagnostics = self._build_model_diagnostics(
                requested_model=model,
                model_name=model_name,
                provider=provider,
                resolved_model=model_name,
                thinking_mode=thinking_mode,
            )
            return {
                "answer": fallback_answer,
                "rewritten_question": question,
                "hits": [],
                "citations": [],
                "model": model_name,
                "usage": usage,
                "cost_estimate": self._estimate_cost(model_name, usage),
                "model_diagnostics": diagnostics,
            }
        use_native_web_search, use_external_web_search = self._resolve_web_search_plan(
            model_name=model_name,
            native_web_search=native_web_search,
            external_web_search=external_web_search,
            web_search_legacy=web_search,
        )
        diagnostics = self._build_model_diagnostics(
            requested_model=model,
            model_name=model_name,
            provider=provider,
            native_web_search_used=use_native_web_search,
            external_web_search_used=use_external_web_search,
            thinking_mode=thinking_mode,
        )
        capability = self._resolve_model_capability(model_name=model_name, provider=provider)
        if thinking_mode == "deep" and not (
            capability.supports_thinking_budget or capability.supports_reasoning_effort
        ):
            self._append_model_diagnostic_warning(
                diagnostics,
                "当前模型未声明支持原生深度思考参数，后端会保留更完整回答提示，但不保证返回可展示的思考片段。",
            )
        prepared = self._prepare_answer(
            question=question,
            message_parts=message_parts,
            history=history,
            top_k=top_k,
            web_search=use_external_web_search,
            capability=capability,
            diagnostics=diagnostics,
            scope_type=scope_type,
            scope_id=scope_id,
            workspace_key=workspace_key,
        )

        fallback_answer = prepared["fallback_answer"]
        if fallback_answer:
            usage = self._normalize_usage(
                None,
                prompt_fallback_text=question,
                completion_fallback_text=fallback_answer,
            )
            return {
                "answer": fallback_answer,
                "rewritten_question": prepared["rewritten_question"],
                "hits": [],
                "citations": [],
                "model": model_name,
                "usage": usage,
                "cost_estimate": self._estimate_cost(model_name, usage),
                "model_diagnostics": diagnostics,
            }

        prepared["messages"][0]["content"] = self._build_system_prompt(
            question_mode=prepared["question_mode"],
            thinking_mode=thinking_mode,
        )

        tool_registry: ToolRegistry | None = None
        if capability.supports_tool_calling and not (
            provider == "qwen" and self.settings.qwen_responses_api_enabled and use_native_web_search
        ):
            tool_registry = self._build_tool_registry(
                include_web_search=use_external_web_search,
                scope_type=scope_type,
                scope_id=scope_id,
                workspace_key=workspace_key,
            )
        elif not capability.supports_tool_calling:
            self._append_model_diagnostic_warning(
                diagnostics,
                "当前模型未声明支持工具调用，已跳过后端只读工具闭环。",
            )
        completion = self._chat_completion_with_tools(
            model_name=model_name,
            messages=prepared["messages"],
            thinking_mode=thinking_mode,
            native_web_search=use_native_web_search,
            diagnostics=diagnostics,
            tool_registry=tool_registry,
        )
        resolved_model_name = str(getattr(completion, "model", "") or model_name)
        diagnostics["resolved_model"] = resolved_model_name
        message = completion.choices[0].message
        answer = (message.content or "").strip()
        reasoning_parts = self._extract_message_reasoning_parts(message)

        if self._should_polish_answer(answer, prepared["question_mode"], thinking_mode):
            answer = self._polish_answer(
                answer=answer,
                question=question,
                question_mode=prepared["question_mode"],
                citation_guide=prepared["citation_guide"],
                model_name=model_name,
                thinking_mode=thinking_mode,
            )

        prompt_text = "\n".join(self._message_content_text(message.get("content", "")) for message in prepared["messages"])
        usage = self._normalize_usage(
            getattr(completion, "usage", None),
            prompt_fallback_text=prompt_text,
            completion_fallback_text=answer,
        )
        cost_estimate = self._estimate_cost(model_name, usage)

        return {
            "answer": answer,
            "rewritten_question": prepared["rewritten_question"],
            "hits": prepared["hits"],
            "citations": prepared["citations"],
            "model": resolved_model_name,
            "usage": usage,
            "cost_estimate": cost_estimate,
            "model_diagnostics": diagnostics,
            "reasoning_parts": reasoning_parts,
        }

    def stream_answer(
        self,
        question: str,
        history: list[ChatHistoryItem] | None = None,
        top_k: int | None = None,
        model: str | None = None,
        thinking_mode: ThinkingMode = "quick",
        web_search: bool = False,
        native_web_search: bool = False,
        external_web_search: bool = False,
        scope_type: str = "all",
        scope_id: int | None = None,
        workspace_key: str | None = None,
        message_parts: list[ChatMessagePart] | None = None,
    ) -> Iterator[StreamingEvent]:
        model_name = self.resolve_model(model)
        provider = self._resolve_model_provider(model_name)
        if self._is_model_identity_question(question):
            fallback_answer = self._build_model_identity_answer(model_name)
            usage = self._normalize_usage(
                None,
                prompt_fallback_text=question,
                completion_fallback_text=fallback_answer,
            )
            diagnostics = self._build_model_diagnostics(
                requested_model=model,
                model_name=model_name,
                provider=provider,
                resolved_model=model_name,
                thinking_mode=thinking_mode,
            )
            yield content_delta(fallback_answer)
            yield done_event(
                answer=fallback_answer,
                rewritten_question=question,
                hits=[],
                citations=[],
                model=model_name,
                usage=usage,
                cost_estimate=self._estimate_cost(model_name, usage),
                model_diagnostics=diagnostics,
            )
            return
        use_native_web_search, use_external_web_search = self._resolve_web_search_plan(
            model_name=model_name,
            native_web_search=native_web_search,
            external_web_search=external_web_search,
            web_search_legacy=web_search,
        )
        diagnostics = self._build_model_diagnostics(
            requested_model=model,
            model_name=model_name,
            provider=provider,
            native_web_search_used=use_native_web_search,
            external_web_search_used=use_external_web_search,
            thinking_mode=thinking_mode,
        )
        capability = self._resolve_model_capability(model_name=model_name, provider=provider)
        if thinking_mode == "deep" and not (
            capability.supports_thinking_budget or capability.supports_reasoning_effort
        ):
            self._append_model_diagnostic_warning(
                diagnostics,
                "当前模型未声明支持原生深度思考参数，后端会保留更完整回答提示，但不保证返回可展示的思考片段。",
            )
        prepared = self._prepare_answer(
            question=question,
            message_parts=message_parts,
            history=history,
            top_k=top_k,
            web_search=use_external_web_search,
            capability=capability,
            diagnostics=diagnostics,
            scope_type=scope_type,
            scope_id=scope_id,
            workspace_key=workspace_key,
        )
        fallback_answer = prepared["fallback_answer"]
        hits = prepared["hits"]
        rewritten_question = prepared["rewritten_question"]

        if fallback_answer:
            usage = self._normalize_usage(
                None,
                prompt_fallback_text=question,
                completion_fallback_text=fallback_answer,
            )
            yield content_delta(fallback_answer)
            yield done_event(
                answer=fallback_answer,
                rewritten_question=rewritten_question,
                hits=hits,
                citations=[],
                model=model_name,
                usage=usage,
                cost_estimate=self._estimate_cost(model_name, usage),
                model_diagnostics=diagnostics,
            )
            return

        prepared["messages"][0]["content"] = self._build_system_prompt(
            question_mode=prepared["question_mode"],
            thinking_mode=thinking_mode,
        )

        collected: list[str] = []
        reasoning_parts: list[str] = []
        tool_registry: ToolRegistry | None = None
        if capability.supports_tool_calling and not (
            provider == "qwen" and self.settings.qwen_responses_api_enabled and use_native_web_search
        ):
            tool_registry = self._build_tool_registry(
                include_web_search=use_external_web_search,
                scope_type=scope_type,
                scope_id=scope_id,
                workspace_key=workspace_key,
            )
        elif not capability.supports_tool_calling:
            self._append_model_diagnostic_warning(
                diagnostics,
                "当前模型未声明支持工具调用，已跳过后端只读工具闭环。",
            )
        for event in self._stream_completion_with_tools(
            model_name=model_name,
            messages=prepared["messages"],
            thinking_mode=thinking_mode,
            native_web_search=use_native_web_search,
            diagnostics=diagnostics,
            tool_registry=tool_registry,
            reasoning_parts=reasoning_parts,
        ):
            if event.get("type") == "content_delta":
                collected.append(str(event.get("content_delta") or ""))
            yield event

        final_answer = "".join(collected).strip()
        if not final_answer:
            final_answer = "The model returned an empty response. Please try again."
        # 流式链路里正文已经逐段发给前端，结束后不能再同步发起二次润色模型调用。
        # 否则前端要等润色调用结束才收到 done，看起来就像回答结束后还卡在流式状态。

        prompt_text = "\n".join(self._message_content_text(message.get("content", "")) for message in prepared["messages"])
        usage = self._normalize_usage(
            None,
            prompt_fallback_text=prompt_text,
            completion_fallback_text=final_answer,
        )
        cost_estimate = self._estimate_cost(model_name, usage)
        resolved_model_name = str(diagnostics.get("resolved_model") or model_name)

        yield done_event(
            answer=final_answer,
            rewritten_question=rewritten_question,
            hits=hits,
            citations=prepared["citations"],
            model=resolved_model_name,
            usage=usage,
            cost_estimate=cost_estimate,
            model_diagnostics=diagnostics,
            reasoning_parts=reasoning_parts,
        )


