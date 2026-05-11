"""Core RAG service: ingest, retrieve, and answer (sync + streaming)."""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from openai import OpenAI

from app.core.settings import settings
from app.schemas import ChatHistoryItem
from app.services.embeddings import get_embedding_model
from app.services.files import file_info, iter_source_files, load_documents_from_file


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
        return Chroma(
            collection_name=self.settings.collection_name,
            embedding_function=self.embedder,
            persist_directory=str(self.settings.chroma_dir),
            collection_metadata={"hnsw:space": "cosine"},
        )

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
        payload = self.vector_store.get(include=[])
        return len(payload.get("ids", []))

    def _compose_search_query(self, question: str, history: list[ChatHistoryItem] | None) -> str:
        if not history:
            return question
        recent_turns = history[-6:]
        history_text = "\n".join(f"{item.role}: {item.content}" for item in recent_turns)
        return f"对话上下文:\n{history_text}\n\n当前问题:\n{question}"

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

    def _build_context(self, hits: list[SearchHit]) -> str:
        blocks: list[str] = []
        for index, hit in enumerate(hits, start=1):
            page_part = f", page={hit.page}" if hit.page is not None else ""
            score_part = f", score={hit.score}" if hit.score is not None else ""
            blocks.append(
                f"[{index}] source={hit.source}{page_part}, chunk={hit.chunk_index}{score_part}\n"
                f"{hit.content}"
            )
        return "\n\n".join(blocks)

    def _prepare_answer(self, question: str, history: list[ChatHistoryItem] | None, top_k: int | None) -> dict[str, Any]:
        rewritten_question = self._compose_search_query(question, history)
        hits = self.retrieve(rewritten_question, top_k=top_k)
        if not hits:
            return {
                "fallback_answer": (
                    "知识库中没有检索到足够相关的内容。"
                    "你可以换一个更具体的问题，或者先把相关文档放到 data/docs 或 data/uploads 后重建索引。"
                ),
                "rewritten_question": rewritten_question,
                "hits": [],
                "messages": [],
            }

        context = self._build_context(hits)
        history_text = "\n".join(f"{item.role}: {item.content}" for item in (history or []))

        system_prompt = (
            "你是一个企业/个人知识库助手，只能基于提供的参考上下文回答。"
            "如果上下文信息不足，请直接说明无法从知识库确认，不要编造。"
            "回答要求：1) 使用中文 2) 先结论后要点 3) 最后列出引用来源。"
        )
        user_prompt = f"""问题：{question}

历史对话：{history_text or "（无）"}

参考上下文：
{context}
"""

        return {
            "fallback_answer": None,
            "rewritten_question": rewritten_question,
            "hits": hits,
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
            }

        completion = self.llm_client.chat.completions.create(
            model=self.settings.deepseek_model,
            temperature=self.settings.temperature,
            max_tokens=self.settings.max_tokens,
            messages=prepared["messages"],
        )
        answer = (completion.choices[0].message.content or "").strip()
        return {
            "answer": answer,
            "rewritten_question": prepared["rewritten_question"],
            "hits": prepared["hits"],
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

        yield {
            "type": "done",
            "answer": final_answer,
            "rewritten_question": rewritten_question,
            "hits": hits,
        }
