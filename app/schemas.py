"""接口数据结构定义。

这里统一放请求体和响应体模型，前后端对接时会更清晰。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ChatHistoryItem(BaseModel):
    """聊天历史中的一条消息。"""

    role: Literal["system", "user", "assistant"] = "user"
    content: str = Field(min_length=1)


class ChatRequest(BaseModel):
    """前端调用 /api/chat 时发送的请求体。"""

    question: str = Field(min_length=1, max_length=4000)
    history: list[ChatHistoryItem] = Field(default_factory=list)
    top_k: int | None = Field(default=None, ge=1, le=20)


class SourceHit(BaseModel):
    """检索命中的一段来源信息。"""

    source: str
    chunk_index: int
    page: int | None = None
    score: float | None = None
    preview: str


class ChatResponse(BaseModel):
    """/api/chat 的返回值。"""

    answer: str
    rewritten_question: str
    sources: list[SourceHit]


class SearchRequest(BaseModel):
    """前端调用 /api/search 时发送的请求体。"""

    query: str = Field(min_length=1, max_length=4000)
    top_k: int | None = Field(default=None, ge=1, le=20)


class SearchResponse(BaseModel):
    """/api/search 的返回值。"""

    query: str
    hits: list[SourceHit]


class IngestResponse(BaseModel):
    """重建索引或上传文件后的返回值。"""

    documents_loaded: int
    chunks_indexed: int
    source_files: list[str]


class DocumentInfo(BaseModel):
    """前端展示文件列表时使用。"""

    path: str
    size_bytes: int
    modified_at: str
    extension: str


class HealthResponse(BaseModel):
    """健康检查接口返回值。"""

    status: str
    collection_name: str
    indexed_chunks: int

