"""RAG 主服务。

这个文件是整个项目的核心，负责把知识库的完整流程串起来：
1. 读取文档
2. 切分文本
3. 做向量化
4. 存入 Chroma
5. 检索相关片段
6. 调用 DeepSeek 生成答案
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from pathlib import Path

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
    """检索结果的内部结构。

    这个结构比接口返回值更完整，里面保留了最终生成时要用的 content。
    """

    source: str
    chunk_index: int
    page: int | None
    score: float | None
    preview: str
    content: str


@dataclass(frozen=True)
class IngestStats:
    """重建索引后的统计信息。"""

    documents_loaded: int
    chunks_indexed: int
    source_files: list[str]


class KnowledgeBaseService:
    """知识库主服务。

    你可以把它理解成 RAG 的“总管”：
    前端上传文件、发起问答，最后都会走到这里。
    """

    def __init__(self) -> None:
        self.settings = settings
        # 重建索引是写操作，最好串行执行，避免并发写库出问题。
        self._lock = threading.RLock()
        self._embedder = None
        self._vector_store: Chroma | None = None
        self._llm_client: OpenAI | None = None

    @property
    def embedder(self):
        """懒加载本地 embedding 模型。

        第一次用的时候再加载，避免项目启动太慢。
        """
        if self._embedder is None:
            self._embedder = get_embedding_model(
                model_name=self.settings.embedding_model,
                device=self.settings.embedding_device,
            )
        return self._embedder

    @property
    def llm_client(self) -> OpenAI:
        """懒加载 DeepSeek 客户端。

        DeepSeek 兼容 OpenAI SDK，所以这里直接使用 OpenAI 类。
        """
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
        """懒加载 LangChain 的 Chroma 向量库封装。"""
        if self._vector_store is None:
            self._vector_store = self._build_vector_store()
        return self._vector_store

    def _build_vector_store(self) -> Chroma:
        """创建 LangChain Chroma 向量库。

        这里就是“用 LangChain 进行检索”的关键位置。
        后面我们调用的 similarity_search_with_relevance_scores 也是它提供的能力。
        """
        return Chroma(
            collection_name=self.settings.collection_name,
            embedding_function=self.embedder,
            persist_directory=str(self.settings.chroma_dir),
            collection_metadata={"hnsw:space": "cosine"},
        )

    def ensure_directories(self) -> None:
        """确保 data 相关目录存在。"""
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.settings.docs_dir.mkdir(parents=True, exist_ok=True)
        self.settings.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.settings.chroma_dir.mkdir(parents=True, exist_ok=True)

    def reset_collection(self) -> None:
        """删除旧索引，重新创建集合。

        新手阶段推荐“全量重建”策略，逻辑简单，也不容易残留脏数据。
        """
        try:
            self.vector_store.delete_collection()
        except Exception:
            # 第一次启动或集合不存在时，删除失败是正常的。
            pass
        self._vector_store = self._build_vector_store()

    def source_file_infos(self) -> list[dict[str, str | int]]:
        """返回前端展示所需的文件信息。"""
        return [file_info(path) for path in iter_source_files()]

    def load_corpus(self) -> tuple[list[Document], list[str]]:
        """读取所有知识库文件，并转成 LangChain Document。"""
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
        """把长文档切成更适合检索的小块。

        为什么要切片：
        - 直接整篇文档去检索，命中不稳定
        - 小块更容易找到“真正相关”的段落
        - 也更省 token
        """
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.settings.chunk_size,
            chunk_overlap=self.settings.chunk_overlap,
            separators=["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""],
        )
        chunks = splitter.split_documents(documents)
        for index, chunk in enumerate(chunks, start=1):
            # 给每个 chunk 打上编号，后面方便在前端展示来源。
            chunk.metadata["chunk_index"] = index
            chunk.metadata["char_count"] = len(chunk.page_content)
        return chunks

    def _hash_chunk(self, content: str, metadata: dict) -> str:
        """给 chunk 生成稳定 ID，避免重复入库。"""
        payload = json.dumps({"content": content, "metadata": metadata}, ensure_ascii=False, sort_keys=True)
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()

    def _format_preview(self, text: str, length: int = 220) -> str:
        """把长文本压缩成前端展示用的短预览。"""
        normalized = " ".join(text.split())
        if len(normalized) <= length:
            return normalized
        return normalized[: length - 1] + "…"

    def _normalize_metadata(self, metadata: dict) -> dict:
        """清理元数据，避免把 None 和空字符串写进 Chroma。"""
        return {
            key: value
            for key, value in metadata.items()
            if value not in (None, "")
        }

    def rebuild_index(self) -> IngestStats:
        """全量重建索引。

        这一步会把 data/docs 和 data/uploads 里的文件全部重新切片并入库。
        """
        with self._lock:
            self.ensure_directories()
            documents, loaded_files = self.load_corpus()
            chunks = self.split_documents(documents)

            # 先删旧库，再建新库，保证结果干净、可重复。
            self.reset_collection()
            if not chunks:
                return IngestStats(documents_loaded=len(documents), chunks_indexed=0, source_files=loaded_files)

            # 分批入库，防止一次性写太多导致内存压力过大。
            batch_size = 64
            for start in range(0, len(chunks), batch_size):
                batch = chunks[start : start + batch_size]
                ids: list[str] = []
                normalized_docs: list[Document] = []

                for chunk in batch:
                    metadata = self._normalize_metadata(chunk.metadata)
                    ids.append(self._hash_chunk(chunk.page_content, metadata))
                    normalized_docs.append(
                        Document(
                            page_content=chunk.page_content,
                            metadata=metadata,
                        )
                    )

                self.vector_store.add_documents(documents=normalized_docs, ids=ids)

            return IngestStats(
                documents_loaded=len(documents),
                chunks_indexed=len(chunks),
                source_files=loaded_files,
            )

    async def save_uploaded_files(self, uploads) -> list[str]:
        """把前端上传的文件保存到 data/uploads。

        这里会做三层校验：
        1. 文件类型
        2. 文件大小
        3. 重名处理
        """
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
        """如果文件名重复，就自动追加序号。"""
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
        """统计当前知识库里有多少个 chunk。"""
        payload = self.vector_store.get(include=[])
        return len(payload.get("ids", []))

    def _compose_search_query(self, question: str, history: list[ChatHistoryItem] | None) -> str:
        """把历史对话和当前问题拼起来，提升检索命中率。"""
        if not history:
            return question

        recent_turns = history[-6:]
        history_text = "\n".join(f"{item.role}: {item.content}" for item in recent_turns)
        return f"对话上下文:\n{history_text}\n\n当前问题:\n{question}"

    def retrieve(self, query: str, top_k: int | None = None) -> list[SearchHit]:
        """执行检索。

        这里用的是 LangChain 的 Chroma 检索接口，
        不是我们自己手写相似度计算。
        """
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
        """对外暴露一个“只检索”的方法。"""
        return self.retrieve(query=query, top_k=top_k)

    def _build_context(self, hits: list[SearchHit]) -> str:
        """把检索结果拼成给 LLM 的上下文。"""
        blocks: list[str] = []
        for index, hit in enumerate(hits, start=1):
            page_part = f", page={hit.page}" if hit.page is not None else ""
            score_part = f", score={hit.score}" if hit.score is not None else ""
            blocks.append(
                f"[{index}] source={hit.source}{page_part}, chunk={hit.chunk_index}{score_part}\n"
                f"{hit.content}"
            )
        return "\n\n".join(blocks)

    def answer(self, question: str, history: list[ChatHistoryItem] | None = None, top_k: int | None = None) -> dict:
        """完整问答流程。

        先检索，再把检索到的内容交给 DeepSeek 生成答案。
        """
        rewritten_question = self._compose_search_query(question, history)
        hits = self.retrieve(rewritten_question, top_k=top_k)
        if not hits:
            return {
                "answer": (
                    "知识库中没有检索到足够相关的内容。"
                    "你可以换一个更具体的问题，或者先把相关文档放进 data/docs / data/uploads 再重建索引。"
                ),
                "rewritten_question": rewritten_question,
                "hits": [],
            }

        # 把检索到的片段拼成上下文，交给大模型回答。
        context = self._build_context(hits)
        history_text = "\n".join(f"{item.role}: {item.content}" for item in (history or []))

        system_prompt = (
            "你是一个企业/个人知识库助手，只能基于提供的参考上下文回答。"
            "如果上下文没有足够信息，请直接说明无法从知识库中确认，不要编造。"
            "回答要求：1) 中文回答 2) 先给结论再给要点 3) 最后列出引用来源。"
        )

        user_prompt = f"""问题：
{question}

历史对话：
{history_text or "（无）"}

参考上下文：
{context}
"""

        completion = self.llm_client.chat.completions.create(
            model=self.settings.deepseek_model,
            temperature=self.settings.temperature,
            max_tokens=self.settings.max_tokens,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )

        answer = (completion.choices[0].message.content or "").strip()

        return {
            "answer": answer,
            "rewritten_question": rewritten_question,
            "hits": hits,
        }

