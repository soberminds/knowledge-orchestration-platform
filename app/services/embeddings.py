"""Embedding 适配器。

这个文件把 sentence-transformers 包装成 LangChain 的 Embeddings 接口，
这样后面接 Chroma、Retriever、Agent 都能直接复用。
"""

from __future__ import annotations

from functools import lru_cache

from langchain_core.embeddings import Embeddings


class LocalSentenceTransformerEmbeddings(Embeddings):
    """本地 Embedding 模型适配器。"""

    def __init__(self, model_name: str, device: str = "cpu") -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - 依赖缺失时给出明确错误
            raise RuntimeError("Missing dependency: sentence-transformers") from exc

        # 模型只加载一次，避免每次请求都重复初始化。
        self._model = SentenceTransformer(model_name, device=device)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """把一批文档转成向量。"""
        vectors = self._model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return vectors.tolist()

    def embed_query(self, text: str) -> list[float]:
        """把单个问题转成向量。"""
        vector = self._model.encode(
            [text],
            normalize_embeddings=True,
            show_progress_bar=False,
        )[0]
        return vector.tolist()


@lru_cache(maxsize=1)
def get_embedding_model(model_name: str, device: str) -> LocalSentenceTransformerEmbeddings:
    """进程级缓存，防止重复加载 embedding 模型。"""
    return LocalSentenceTransformerEmbeddings(model_name=model_name, device=device)

