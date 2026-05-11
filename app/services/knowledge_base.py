"""Core RAG service: ingest, retrieve, and answer (sync + streaming)."""

from __future__ import annotations

import hashlib
import inspect
import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Literal

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

QuestionMode = Literal["overview", "technical", "comparison", "list", "general"]


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


class KnowledgeBaseService:
    """Main knowledge-base service used by API routes."""

    def __init__(self) -> None:
        _patch_posthog_capture_signature()
        self.settings = settings
        self._lock = threading.RLock()
        self._embedder = None
        self._vector_store: Chroma | None = None
        self._llm_client: OpenAI | None = None

    @property
    def embedder(self):
        if self._embedder is None:
            self._embedder = get_embedding_model(
                model_name=self.settings.embedding_model,
                device=self.settings.embedding_device,
            )
        return self._embedder

    @property
    def llm_client(self) -> OpenAI:
        if self._llm_client is None:
            if not self.settings.deepseek_api_key:
                raise RuntimeError("DEEPSEEK_API_KEY is missing. Put it in .env before starting.")
            self._llm_client = OpenAI(
                api_key=self.settings.deepseek_api_key,
                base_url=self.settings.deepseek_base_url,
            )
        return self._llm_client

    @property
    def vector_store(self) -> Chroma:
        if self._vector_store is None:
            self._vector_store = self._build_vector_store()
        return self._vector_store

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
            separators=["\n\n", "\n", "。", "！", "？", "；", "：", " ", ""],
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
        normalized = re.sub(r"\s+", "", question)

        overview_keywords = (
            "讲了什么",
            "主要讲",
            "主要内容",
            "概述",
            "总结",
            "介绍一下",
            "整体",
            "背景和目标",
            "项目内容",
            "核心内容",
            "这个项目",
            "总体",
        )
        comparison_keywords = ("对比", "区别", "差异", "不同", "优缺点", "哪个好", "哪种更")
        list_keywords = ("列出", "清单", "列表", "有哪些", "包含哪些", "都有什么", "分类")
        technical_keywords = ("技术", "算法", "实现", "架构", "原理", "流程", "接口", "代码", "模型")

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
            "fromkeras",
            "tf.contrib",
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
        fallback_hits = candidates
        if question_mode in ("overview", "comparison", "list", "general") and len(non_code_hits) >= max(4, limit // 2):
            fallback_hits = non_code_hits

        selected: list[SearchHit] = []
        used_pages: set[int] = set()
        used_keys: set[tuple[str, int | None, int]] = set()

        for hit in fallback_hits:
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
            for hit in fallback_hits:
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
                excerpts.append(
                    f"- chunk={hit.chunk_index}{score_part}\n{snippets}"
                )

            block = (
                f"[{label}] source={source}, {page_text}, group_score={score}\n"
                + "\n".join(excerpts)
            )
            blocks.append(block)

        context = "\n\n".join(blocks)
        citation_guide = "\n".join(citation_lines)
        return context, citation_guide, citation_items

    def _build_system_prompt(self, question_mode: QuestionMode) -> str:
        base_rules = (
            "你是一个企业/个人知识库助手，只能基于提供的参考上下文回答。"
            "如果上下文信息不足，请直接说明无法从知识库确认，不要编造。"
            "回答时请优先引用证据标签（如[S1][S2]），并在关键结论后附上标签。"
        )

        if question_mode == "overview":
            return (
                base_rules
                + "当前问题是概述类问题，请优先产出项目级总结，不要只摘抄技术代码。"
                "输出结构："
                "1) 一句话总述；"
                "2) 项目背景与目标；"
                "3) 建设内容与范围；"
                "4) 核心功能与技术路线；"
                "5) 交付对象与业务价值；"
                "6) 信息缺口（若有）；"
                "7) 最后列出“引用来源”并保留[Sx]标签。"
            )
        if question_mode == "technical":
            return (
                base_rules
                + "当前问题是技术类问题，请按“架构-模块-流程-关键参数/约束-风险与改进建议”回答。"
                "如果资料中包含代码片段，先解释业务意义再讲实现细节。"
            )
        if question_mode == "comparison":
            return (
                base_rules
                + "当前问题是对比类问题，请输出对比表述：对比维度、差异、适用场景、结论建议。"
                "不要只罗列条目，需给出取舍理由。"
            )
        if question_mode == "list":
            return (
                base_rules
                + "当前问题是清单类问题，请给出完整条目列表，并按主题分组。"
                "每组不超过7条，避免信息堆叠。"
            )
        return (
            base_rules
            + "回答要求：先结论后要点，使用中文，最后列出引用来源。"
        )

    def _should_polish_answer(self, answer: str, question_mode: QuestionMode) -> bool:
        compact = re.sub(r"\s+", "", answer)
        if len(compact) < 120:
            return True
        if question_mode in ("overview", "comparison", "list") and len(compact) < 260:
            return True
        # If evidence labels exist but answer almost does not use them, refine once.
        label_mentions = len(re.findall(r"\[S\d+\]", answer))
        if question_mode in ("overview", "comparison") and label_mentions <= 1:
            return True
        return False

    def _polish_answer(
        self,
        answer: str,
        question: str,
        question_mode: QuestionMode,
        citation_guide: str,
    ) -> str:
        polish_system_prompt = (
            "你是知识库回答润色器。"
            "只允许在不改变事实的前提下优化表达、结构和完整度。"
            "禁止添加上下文里没有的信息。"
            "保留并尽量补齐证据标签格式 [Sx]。"
        )
        polish_user_prompt = f"""原问题：
{question}

问题模式：
{question_mode}

证据标签：
{citation_guide}

待润色回答：
{answer}

润色要求：
1) 保持原结论与事实不变；
2) 用更完整的结构表达，减少碎片化；
3) 关键句后补充证据标签 [Sx]；
4) 不要新增事实，不要编造页码。
"""
        polished = self.llm_client.chat.completions.create(
            model=self.settings.deepseek_model,
            temperature=0.1,
            max_tokens=self.settings.max_tokens,
            messages=[
                {"role": "system", "content": polish_system_prompt},
                {"role": "user", "content": polish_user_prompt},
            ],
        )
        polished_text = (polished.choices[0].message.content or "").strip()
        if not polished_text:
            return answer
        return polished_text

    def _prepare_answer(self, question: str, history: list[ChatHistoryItem] | None, top_k: int | None) -> dict[str, Any]:
        rewritten_question = self._compose_search_query(question, history)
        question_mode = self._classify_question_mode(question)
        requested_top_k = top_k or self.settings.top_k
        per_query_limit = max(requested_top_k, 4)
        if question_mode in ("overview", "comparison", "list", "general"):
            # Summary-like questions need broader recall before synthesis.
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

        if not hits:
            return {
                "fallback_answer": (
                    "知识库中没有检索到足够相关的内容。"
                    "你可以换一个更具体的问题，或者先把相关文档放到 data/docs 或 data/uploads 后重建索引。"
                ),
                "rewritten_question": rewritten_question,
                "hits": [],
                "citations": [],
                "question_mode": question_mode,
                "citation_guide": "",
                "messages": [],
            }

        context, citation_guide, citation_items = self._build_context(hits, question_mode=question_mode)
        history_text = "\n".join(f"{item.role}: {item.content}" for item in (history or []))
        system_prompt = self._build_system_prompt(question_mode)
        user_prompt = f"""问题：{question}

历史对话：{history_text or "（无）"}

问题模式：{question_mode}

证据标签说明：
{citation_guide}

参考上下文：
{context}
"""

        return {
            "fallback_answer": None,
            "rewritten_question": rewritten_question,
            "hits": hits,
            "citations": citation_items,
            "question_mode": question_mode,
            "citation_guide": citation_guide,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }

    def answer(self, question: str, history: list[ChatHistoryItem] | None = None, top_k: int | None = None) -> dict[str, Any]:
        prepared = self._prepare_answer(question=question, history=history, top_k=top_k)
        fallback_answer = prepared["fallback_answer"]
        if fallback_answer:
            return {
                "answer": fallback_answer,
                "rewritten_question": prepared["rewritten_question"],
                "hits": [],
                "citations": [],
            }

        completion = self.llm_client.chat.completions.create(
            model=self.settings.deepseek_model,
            temperature=self.settings.temperature,
            max_tokens=self.settings.max_tokens,
            messages=prepared["messages"],
        )
        answer = (completion.choices[0].message.content or "").strip()
        if self._should_polish_answer(answer, prepared["question_mode"]):
            answer = self._polish_answer(
                answer=answer,
                question=question,
                question_mode=prepared["question_mode"],
                citation_guide=prepared["citation_guide"],
            )
        return {
            "answer": answer,
            "rewritten_question": prepared["rewritten_question"],
            "hits": prepared["hits"],
            "citations": prepared["citations"],
        }

    def stream_answer(
        self,
        question: str,
        history: list[ChatHistoryItem] | None = None,
        top_k: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        prepared = self._prepare_answer(question=question, history=history, top_k=top_k)
        fallback_answer = prepared["fallback_answer"]
        hits = prepared["hits"]
        rewritten_question = prepared["rewritten_question"]

        if fallback_answer:
            yield {"type": "delta", "delta": fallback_answer}
            yield {
                "type": "done",
                "answer": fallback_answer,
                "rewritten_question": rewritten_question,
                "hits": hits,
                "citations": [],
            }
            return

        collected: list[str] = []
        stream = self.llm_client.chat.completions.create(
            model=self.settings.deepseek_model,
            temperature=self.settings.temperature,
            max_tokens=self.settings.max_tokens,
            messages=prepared["messages"],
            stream=True,
        )

        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content or ""
            if not delta:
                continue
            collected.append(delta)
            yield {"type": "delta", "delta": delta}

        final_answer = "".join(collected).strip()
        if not final_answer:
            final_answer = "模型没有返回内容，请稍后重试。"
        elif self._should_polish_answer(final_answer, prepared["question_mode"]):
            final_answer = self._polish_answer(
                answer=final_answer,
                question=question,
                question_mode=prepared["question_mode"],
                citation_guide=prepared["citation_guide"],
            )

        yield {
            "type": "done",
            "answer": final_answer,
            "rewritten_question": rewritten_question,
            "hits": hits,
            "citations": prepared["citations"],
        }
