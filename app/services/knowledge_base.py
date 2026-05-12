"""Core RAG service: ingest, retrieve, and answer (sync + streaming)."""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Literal
from urllib import error as urllib_error
from urllib import request as urllib_request

from app.core.settings import settings
from chromadb import PersistentClient
from chromadb.config import Settings as ChromaSettings
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from openai import OpenAI

from app.schemas import ChatHistoryItem
from app.services.embeddings import get_embedding_model
from app.services.files import file_info, iter_source_files, load_documents_from_file
from app.services.preview_pdf import get_preview_pdf_cache_path

QuestionMode = Literal["overview", "technical", "comparison", "list", "general"]
ThinkingMode = Literal["quick", "deep"]


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


@dataclass(frozen=True)
class ProviderRuntimeConfig:
    """Runtime connection config for one OpenAI-compatible provider."""

    provider: str
    base_url: str
    api_key: str


class ModelUnavailableError(RuntimeError):
    """Raised when selected model has no available provider credentials."""


class KnowledgeBaseService:
    """Main knowledge-base service used by API routes."""

    def __init__(self) -> None:
        _patch_posthog_capture_signature()
        self.settings = settings
        self._lock = threading.RLock()
        self._embedder = None
        self._vector_store: Chroma | None = None
        self._llm_clients: dict[str, OpenAI] = {}
        self._model_provider_overrides_cache: dict[str, str] | None = None
        self._extra_provider_configs_cache: dict[str, ProviderRuntimeConfig] | None = None
        self._model_pricing_cache: dict[str, dict[str, float]] | None = None

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

    def _resolve_model_client(self, model_name: str) -> tuple[str, OpenAI]:
        config = self._resolve_model_provider_config(model_name)
        if config is None:
            raise ModelUnavailableError(
                f"Model '{model_name}' is not mapped to a configured provider. "
                "Add MODEL_PROVIDER_OVERRIDES_JSON or EXTRA_PROVIDER_CONFIGS_JSON in .env."
            )

        if not config.api_key:
            env_name = f"{config.provider.upper()}_API_KEY"
            raise ModelUnavailableError(
                f"Model '{model_name}' is temporarily unavailable: missing {env_name}. "
                "Please set it in .env, then restart backend."
            )

        cache_key = f"{config.provider}|{config.base_url}|{hash(config.api_key)}"
        client = self._llm_clients.get(cache_key)
        if client is None:
            client = OpenAI(api_key=config.api_key, base_url=config.base_url)
            self._llm_clients[cache_key] = client
        return config.provider, client

    def resolve_model_options(self) -> list[dict[str, str | bool | None]]:
        options: list[dict[str, str | bool | None]] = []
        for model_name in self.resolve_available_models():
            provider = self._resolve_provider_name(model_name)
            config = self._resolve_provider_config(provider)
            available = bool(config and config.api_key)
            reason: str | None = None
            if not config:
                reason = "Provider is not configured."
            elif not config.api_key:
                reason = f"Missing {provider.upper()}_API_KEY in .env."
            options.append(
                {
                    "model": model_name,
                    "provider": provider,
                    "supports_native_web_search": self._provider_supports_native_web_search(provider),
                    "available": available,
                    "unavailable_reason": reason,
                }
            )
        return options

    def _provider_supports_native_web_search(self, provider: str) -> bool:
        token = provider.strip().lower()
        # Keep conservative by default; currently verified and enabled for DashScope/Qwen.
        return token in {"qwen"}

    def _resolve_web_search_plan(
        self,
        *,
        model_name: str,
        native_web_search: bool,
        external_web_search: bool,
        web_search_legacy: bool,
    ) -> tuple[bool, bool]:
        provider = self._resolve_provider_name(model_name)
        supports_native = self._provider_supports_native_web_search(provider)
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
        self.settings.docs_dir.mkdir(parents=True, exist_ok=True)
        self.settings.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.settings.chroma_dir.mkdir(parents=True, exist_ok=True)
        self.settings.preview_pdf_dir.mkdir(parents=True, exist_ok=True)

    def reset_collection(self) -> None:
        try:
            self.vector_store.delete_collection()
        except Exception:
            # Normal on first launch or missing collection.
            pass
        self._vector_store = self._build_vector_store()

    def source_file_infos(self) -> list[dict[str, str | int]]:
        return [file_info(path) for path in iter_source_files()]

    def load_corpus(self) -> tuple[list[Document], list[str]]:
        documents: list[Document] = []
        loaded_files: list[str] = []

        for path in iter_source_files():
            docs = load_documents_from_file(path)
            if not docs:
                continue
            documents.extend(docs)
            loaded_files.append(str(path.relative_to(self.settings.root_dir)).replace("\\", "/"))

        return documents, loaded_files

    def split_documents(self, documents: list[Document]) -> list[Document]:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.settings.chunk_size,
            chunk_overlap=self.settings.chunk_overlap,
            separators=["\n\n", "\n", "。", "；", "！", "？", " ", ""],
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
        return normalized[: length - 1] + "…"

    def _normalize_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in metadata.items() if value not in (None, "")}

    def rebuild_index(self) -> IngestStats:
        with self._lock:
            self.ensure_directories()
            documents, loaded_files = self.load_corpus()
            chunks = self.split_documents(documents)

            self.reset_collection()
            if not chunks:
                return IngestStats(documents_loaded=len(documents), chunks_indexed=0, source_files=loaded_files)

            batch_size = 64
            for start in range(0, len(chunks), batch_size):
                batch = chunks[start : start + batch_size]
                ids: list[str] = []
                normalized_docs: list[Document] = []

                for chunk in batch:
                    metadata = self._normalize_metadata(chunk.metadata)
                    ids.append(self._hash_chunk(chunk.page_content, metadata))
                    normalized_docs.append(Document(page_content=chunk.page_content, metadata=metadata))

                self.vector_store.add_documents(documents=normalized_docs, ids=ids)

            return IngestStats(
                documents_loaded=len(documents),
                chunks_indexed=len(chunks),
                source_files=loaded_files,
            )

    def delete_source_file_and_rebuild(self, path: Path) -> IngestStats:
        with self._lock:
            self.ensure_directories()
            if not path.exists() or not path.is_file():
                raise FileNotFoundError(f"File not found: {path}")

            preview_cache_path: Path | None = None
            if path.suffix.lower() in {".doc", ".docx"}:
                try:
                    preview_cache_path = get_preview_pdf_cache_path(path)
                except Exception:
                    preview_cache_path = None

            path.unlink()
            if preview_cache_path and preview_cache_path.exists():
                preview_cache_path.unlink(missing_ok=True)

            return self.rebuild_index()

    async def save_uploaded_files(self, uploads) -> list[str]:
        self.ensure_directories()
        saved_paths: list[str] = []

        for upload in uploads:
            filename = Path(upload.filename or "upload").name
            suffix = Path(filename).suffix.lower()
            if suffix not in self.settings.supported_extensions:
                raise ValueError(f"Unsupported file type: {suffix or '[no extension]'}")

            content = await upload.read()
            max_bytes = self.settings.max_upload_mb * 1024 * 1024
            if len(content) > max_bytes:
                raise ValueError(f"File too large. Limit: {self.settings.max_upload_mb} MB")

            target = self._unique_upload_path(filename)
            target.write_bytes(content)
            saved_paths.append(str(target.relative_to(self.settings.root_dir)).replace("\\", "/"))

        return saved_paths

    def _unique_upload_path(self, filename: str) -> Path:
        base = self.settings.uploads_dir / Path(filename).name
        if not base.exists():
            return base

        stem = base.stem
        suffix = base.suffix
        for index in range(1, 1000):
            candidate = self.settings.uploads_dir / f"{stem}_{index}{suffix}"
            if not candidate.exists():
                return candidate
        raise RuntimeError("Could not generate a unique filename for upload")

    def count_chunks(self) -> int:
        self.ensure_directories()
        client = self._build_chroma_client()
        try:
            collection = client.get_collection(name=self.settings.collection_name)
        except Exception:
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
        return f"对话上下文:\n{history_text}\n\n当前问题:\n{question}"

    def _classify_question_mode(self, question: str) -> QuestionMode:
        normalized = re.sub(r"\s+", "", question.lower())

        overview_keywords = (
            "讲了什么",
            "主要讲",
            "主要内容",
            "概述",
            "总结",
            "介绍一下",
            "整体",
            "背景和目标",
            "总体",
            "概括",
            "overview",
            "summary",
        )
        comparison_keywords = ("对比", "区别", "差异", "不同", "优缺点", "哪个更", "compare", "vs")
        list_keywords = ("列出", "清单", "列表", "有哪些", "包含哪些", "分类", "list")
        technical_keywords = ("技术", "算法", "实现", "架构", "原理", "流程", "接口", "代码", "模型", "technical")

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
                    f"{question} 项目背景 目标 建设内容 建设范围 核心功能",
                    f"{question} 系统架构 应用模块 服务对象 部署范围",
                    f"{question} 关键技术 实施内容 业务流程 业务价值",
                ]
            )
        elif question_mode == "technical":
            queries.extend(
                [
                    f"{question} 技术架构 模块实现 关键算法 数据流程 接口设计",
                    f"{question} 模型 引擎 平台 服务 编排",
                ]
            )
        elif question_mode == "comparison":
            queries.extend(
                [
                    f"{question} 对比 差异 优缺点 适用场景 成本 风险",
                    f"{question} 指标 效果 约束 前提",
                ]
            )
        elif question_mode == "list":
            queries.extend(
                [
                    f"{question} 清单 列表 分类 条目 模块 功能",
                    f"{question} 目录 章节 要点",
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

    def _retrieve_candidates(self, queries: list[str], per_query_limit: int) -> list[SearchHit]:
        if self.count_chunks() == 0:
            return []

        best_hits: dict[tuple[str, int | None, int], SearchHit] = {}
        best_scores: dict[tuple[str, int | None, int], float] = {}

        for query in queries:
            results = self.vector_store.similarity_search_with_relevance_scores(query=query, k=per_query_limit)
            for doc, relevance in results:
                metadata = doc.metadata or {}
                page = int(metadata["page"]) if metadata.get("page") is not None else None
                score = float(relevance) if relevance is not None else 0.0
                key = (
                    str(metadata.get("source", "unknown")),
                    page,
                    int(metadata.get("chunk_index", 0)),
                )

                hit = SearchHit(
                    source=key[0],
                    chunk_index=key[2],
                    page=page,
                    score=round(score, 4),
                    preview=self._format_preview(doc.page_content),
                    content=doc.page_content,
                )

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
        return normalized[: limit - 1] + "…"

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

    def retrieve(self, query: str, top_k: int | None = None) -> list[SearchHit]:
        if self.count_chunks() == 0:
            return []

        limit = top_k or self.settings.top_k
        results = self.vector_store.similarity_search_with_relevance_scores(query=query, k=limit)

        hits: list[SearchHit] = []
        for doc, relevance in results:
            metadata = doc.metadata or {}
            score = round(float(relevance), 4) if relevance is not None else None
            hits.append(
                SearchHit(
                    source=str(metadata.get("source", "unknown")),
                    chunk_index=int(metadata.get("chunk_index", 0)),
                    page=int(metadata["page"]) if metadata.get("page") is not None else None,
                    score=score,
                    preview=self._format_preview(doc.page_content),
                    content=doc.page_content,
                )
            )
        return hits

    def search(self, query: str, top_k: int | None = None) -> list[SearchHit]:
        return self.retrieve(query=query, top_k=top_k)

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
            citation_lines.append(f"[{label}] {source}, {page_text}")
            citation_items.append(
                {
                    "label": label,
                    "source": source,
                    "page": page,
                    "chunk_indices": [int(hit.chunk_index) for hit in group["hits"]],
                    "score": score,
                    "preview": group["hits"][0].preview if group["hits"] else "",
                }
            )

            excerpts: list[str] = []
            for hit in group["hits"]:
                score_part = f", score={hit.score}" if hit.score is not None else ""
                snippets = self._truncate_for_context(hit.content, excerpt_limit)
                excerpts.append(f"- chunk={hit.chunk_index}{score_part}\n{snippets}")

            blocks.append(f"[{label}] source={source}, {page_text}, group_score={score}\n" + "\n".join(excerpts))

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
            "你是企业知识库问答助手，只能基于提供的参考内容回答。"
            "如果证据不足，要明确说缺少哪些信息，不要编造。"
            "关键结论后请添加引用标签，例如 [S1]、[S2]、[W1]。"
        )

        mode_rules: dict[QuestionMode, str] = {
            "overview": (
                "这是概述类问题。请按以下结构回答："
                "1) 一句话总结；2) 背景与目标；3) 建设范围与内容；"
                "4) 核心能力与技术路线；5)业务价值；6) 信息缺口；7) 引用来源。"
            ),
            "technical": "这是技术类问题。请按 架构-模块-流程-关键参数/约束-风险与建议 的结构回答。",
            "comparison": "这是对比类问题。请给出对比维度、差异、适用场景和取舍建议。",
            "list": "这是清单类问题。请按主题分组列出条目，并尽量完整。",
            "general": "先给结论，再给支撑要点，并附上引用标签。",
        }

        depth_rule = "尽量简洁，避免冗长。" if thinking_mode == "quick" else "请更深入、更完整地综合信息后回答。"
        return f"{base_rules}{mode_rules[question_mode]}{depth_rule}"

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

    def _completion_options(
        self,
        thinking_mode: ThinkingMode,
        *,
        stream: bool,
        native_web_search: bool,
    ) -> dict[str, Any]:
        if thinking_mode == "deep":
            options: dict[str, Any] = {
                "max_tokens": min(self.settings.max_tokens * 2, 4096),
                "reasoning_effort": "high",
                "extra_body": {"thinking": {"type": "enabled"}},
            }
        else:
            options = {
                "temperature": self.settings.temperature,
                "max_tokens": self.settings.max_tokens,
                "extra_body": {"thinking": {"type": "disabled"}},
            }

        if native_web_search:
            options.setdefault("extra_body", {})
            options["extra_body"]["enable_search"] = True

        if stream:
            options["stream_options"] = {"include_usage": True}
        return options

    def _chat_completion(
        self,
        *,
        model_name: str,
        messages: list[dict[str, Any]],
        thinking_mode: ThinkingMode,
        stream: bool,
        native_web_search: bool = False,
    ):
        _, client = self._resolve_model_client(model_name)
        options = self._completion_options(
            thinking_mode,
            stream=stream,
            native_web_search=native_web_search,
        )
        kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "stream": stream,
            **options,
        }

        try:
            return client.chat.completions.create(**kwargs)
        except Exception:
            # Some proxy models may not support thinking params.
            fallback_kwargs: dict[str, Any] = {
                "model": model_name,
                "messages": messages,
                "stream": stream,
                "temperature": self.settings.temperature,
                "max_tokens": self.settings.max_tokens,
            }
            return client.chat.completions.create(**fallback_kwargs)

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
            "你是知识库答案润色器。"
            "只能在不改变事实的前提下优化结构、可读性和完整性。"
            "禁止添加参考材料里没有的信息。"
            "保留并尽量补齐引用标签格式 [Sx]/[Wx]。"
        )
        polish_user_prompt = f"""原问题：
{question}

问题模式：{question_mode}

证据标签：
{citation_guide}

待润色回答：
{answer}

润色要求：
1) 保持事实不变；
2) 提升结构与可读性；
3) 关键句补上引用标签；
4) 不新增事实。"""

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
        history: list[ChatHistoryItem] | None,
        top_k: int | None,
        web_search: bool,
    ) -> dict[str, Any]:
        rewritten_question = self._compose_search_query(question, history)
        question_mode = self._classify_question_mode(question)
        requested_top_k = top_k or self.settings.top_k

        per_query_limit = max(requested_top_k, 4)
        if question_mode in ("overview", "comparison", "list", "general"):
            per_query_limit = max(requested_top_k * 3, 12)
        elif question_mode == "technical":
            per_query_limit = max(requested_top_k * 2, 8)

        queries = self._build_retrieval_queries(
            question=question,
            rewritten_question=rewritten_question,
            question_mode=question_mode,
        )
        candidates = self._retrieve_candidates(queries=queries, per_query_limit=per_query_limit)

        answer_hit_limit = max(requested_top_k, 4)
        if question_mode in ("overview", "comparison", "list", "general"):
            answer_hit_limit = max(requested_top_k * 2, 8)
        elif question_mode == "technical":
            answer_hit_limit = max(requested_top_k * 2, 6)

        hits = self._select_hits_for_answer(candidates=candidates, limit=answer_hit_limit, question_mode=question_mode)

        web_context = ""
        web_citations: list[dict[str, Any]] = []
        if web_search and self.is_web_search_available():
            web_hits = self._search_web(question, top_k=max(1, min(self.settings.web_search_top_k, 8)))
            web_context, web_citations = self._build_web_context(web_hits)

        if not hits and not web_context:
            return {
                "fallback_answer": (
                    "知识库中没有检索到足够相关的内容。"
                    "你可以换更具体的问题，或先上传相关文档后重建索引。"
                ),
                "rewritten_question": rewritten_question,
                "hits": [],
                "citations": [],
                "question_mode": question_mode,
                "citation_guide": "",
                "messages": [],
            }

        context = ""
        citation_items: list[dict[str, Any]] = []
        if hits:
            context, _, citation_items = self._build_context(hits, question_mode=question_mode)

        combined_citations = [*citation_items, *web_citations]
        citation_lines = [f"[{item['label']}] {item['source']}" for item in combined_citations]
        combined_citation_guide = "\n".join(citation_lines)

        history_text = "\n".join(f"{item.role}: {item.content}" for item in (history or []))
        user_prompt_parts = [
            f"问题:\n{question}",
            f"历史对话:\n{history_text or '（无）'}",
            f"问题模式:\n{question_mode}",
            f"证据标签说明:\n{combined_citation_guide}",
            f"知识库参考上下文:\n{context}",
        ]
        if web_context:
            user_prompt_parts.append(f"联网搜索补充上下文:\n{web_context}")

        return {
            "fallback_answer": None,
            "rewritten_question": rewritten_question,
            "hits": hits,
            "citations": combined_citations,
            "question_mode": question_mode,
            "citation_guide": combined_citation_guide,
            "messages": [
                {"role": "system", "content": ""},
                {"role": "user", "content": "\n\n".join(user_prompt_parts)},
            ],
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
    ) -> dict[str, Any]:
        model_name = self.resolve_model(model)
        self._resolve_model_client(model_name)
        use_native_web_search, use_external_web_search = self._resolve_web_search_plan(
            model_name=model_name,
            native_web_search=native_web_search,
            external_web_search=external_web_search,
            web_search_legacy=web_search,
        )
        prepared = self._prepare_answer(
            question=question,
            history=history,
            top_k=top_k,
            web_search=use_external_web_search,
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
            }

        prepared["messages"][0]["content"] = self._build_system_prompt(
            question_mode=prepared["question_mode"],
            thinking_mode=thinking_mode,
        )

        completion = self._chat_completion(
            model_name=model_name,
            messages=prepared["messages"],
            thinking_mode=thinking_mode,
            stream=False,
            native_web_search=use_native_web_search,
        )
        answer = (completion.choices[0].message.content or "").strip()

        if self._should_polish_answer(answer, prepared["question_mode"], thinking_mode):
            answer = self._polish_answer(
                answer=answer,
                question=question,
                question_mode=prepared["question_mode"],
                citation_guide=prepared["citation_guide"],
                model_name=model_name,
                thinking_mode=thinking_mode,
            )

        prompt_text = "\n".join(message.get("content", "") for message in prepared["messages"])
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
            "model": model_name,
            "usage": usage,
            "cost_estimate": cost_estimate,
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
    ) -> Iterator[dict[str, Any]]:
        model_name = self.resolve_model(model)
        self._resolve_model_client(model_name)
        use_native_web_search, use_external_web_search = self._resolve_web_search_plan(
            model_name=model_name,
            native_web_search=native_web_search,
            external_web_search=external_web_search,
            web_search_legacy=web_search,
        )
        prepared = self._prepare_answer(
            question=question,
            history=history,
            top_k=top_k,
            web_search=use_external_web_search,
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
            yield {"type": "delta", "delta": fallback_answer}
            yield {
                "type": "done",
                "answer": fallback_answer,
                "rewritten_question": rewritten_question,
                "hits": hits,
                "citations": [],
                "model": model_name,
                "usage": usage,
                "cost_estimate": self._estimate_cost(model_name, usage),
            }
            return

        prepared["messages"][0]["content"] = self._build_system_prompt(
            question_mode=prepared["question_mode"],
            thinking_mode=thinking_mode,
        )

        collected: list[str] = []
        usage_obj: Any = None
        stream = self._chat_completion(
            model_name=model_name,
            messages=prepared["messages"],
            thinking_mode=thinking_mode,
            stream=True,
            native_web_search=use_native_web_search,
        )

        for chunk in stream:
            chunk_usage = getattr(chunk, "usage", None)
            if chunk_usage is not None:
                usage_obj = chunk_usage

            if not chunk.choices:
                continue

            delta_piece = chunk.choices[0].delta
            reasoning_content = getattr(delta_piece, "reasoning_content", None)
            if reasoning_content:
                # Keep internal reasoning hidden.
                continue

            delta = delta_piece.content or ""
            if not delta:
                continue
            collected.append(delta)
            yield {"type": "delta", "delta": delta}

        final_answer = "".join(collected).strip()
        if not final_answer:
            final_answer = "模型没有返回内容，请稍后重试。"
        elif self._should_polish_answer(final_answer, prepared["question_mode"], thinking_mode):
            final_answer = self._polish_answer(
                answer=final_answer,
                question=question,
                question_mode=prepared["question_mode"],
                citation_guide=prepared["citation_guide"],
                model_name=model_name,
                thinking_mode=thinking_mode,
            )

        prompt_text = "\n".join(message.get("content", "") for message in prepared["messages"])
        usage = self._normalize_usage(
            usage_obj,
            prompt_fallback_text=prompt_text,
            completion_fallback_text=final_answer,
        )
        cost_estimate = self._estimate_cost(model_name, usage)

        yield {
            "type": "done",
            "answer": final_answer,
            "rewritten_question": rewritten_question,
            "hits": hits,
            "citations": prepared["citations"],
            "model": model_name,
            "usage": usage,
            "cost_estimate": cost_estimate,
        }
