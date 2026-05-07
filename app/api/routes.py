"""HTTP API 路由。

这里把知识库能力暴露给前端页面：
- 健康检查
- 查看文档
- 上传文档
- 重建索引
- 搜索
- 聊天问答
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from app.dependencies import get_knowledge_base_service
from app.schemas import (
    ChatRequest,
    ChatResponse,
    DocumentInfo,
    HealthResponse,
    IngestResponse,
    SearchRequest,
    SearchResponse,
    SourceHit,
)
from app.services.knowledge_base import KnowledgeBaseService, SearchHit


router = APIRouter(prefix="/api", tags=["rag"])


def _to_source_hit(hit: SearchHit) -> SourceHit:
    """把内部检索结构转成接口返回结构。"""
    return SourceHit(
        source=hit.source,
        chunk_index=hit.chunk_index,
        page=hit.page,
        score=hit.score,
        preview=hit.preview,
    )


@router.get("/health", response_model=HealthResponse)
async def health(service: KnowledgeBaseService = Depends(get_knowledge_base_service)) -> HealthResponse:
    """健康检查接口，前端首页会显示它。"""
    return HealthResponse(
        status="ok",
        collection_name=service.settings.collection_name,
        indexed_chunks=service.count_chunks(),
    )


@router.get("/documents", response_model=list[DocumentInfo])
async def list_documents(service: KnowledgeBaseService = Depends(get_knowledge_base_service)) -> list[DocumentInfo]:
    """列出当前知识库可见的所有文档。"""
    infos = []
    for item in service.source_file_infos():
        infos.append(
            DocumentInfo(
                path=str(item["path"]),
                size_bytes=int(item["size_bytes"]),
                modified_at=str(item["modified_at"]),
                extension=str(item["extension"]),
            )
        )
    return infos


@router.post("/ingest", response_model=IngestResponse)
async def ingest(service: KnowledgeBaseService = Depends(get_knowledge_base_service)) -> IngestResponse:
    """把 data/docs 和 data/uploads 里的文件全部重建成新索引。"""
    try:
        stats = await run_in_threadpool(service.rebuild_index)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return IngestResponse(
        documents_loaded=stats.documents_loaded,
        chunks_indexed=stats.chunks_indexed,
        source_files=stats.source_files,
    )


@router.post("/upload", response_model=IngestResponse)
async def upload_files(
    files: list[UploadFile] = File(...),
    service: KnowledgeBaseService = Depends(get_knowledge_base_service),
) -> IngestResponse:
    """接收前端上传的文件，保存后自动重建索引。"""
    if not files:
        raise HTTPException(status_code=400, detail="Please upload at least one file.")

    try:
        await service.save_uploaded_files(files)
        stats = await run_in_threadpool(service.rebuild_index)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return IngestResponse(
        documents_loaded=stats.documents_loaded,
        chunks_indexed=stats.chunks_indexed,
        source_files=stats.source_files,
    )


@router.post("/search", response_model=SearchResponse)
async def search(
    request: SearchRequest,
    service: KnowledgeBaseService = Depends(get_knowledge_base_service),
) -> SearchResponse:
    """只做检索，不调用大模型。"""
    try:
        hits = await run_in_threadpool(service.search, request.query, request.top_k)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return SearchResponse(
        query=request.query,
        hits=[_to_source_hit(hit) for hit in hits],
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    service: KnowledgeBaseService = Depends(get_knowledge_base_service),
) -> ChatResponse:
    """先检索，再把命中的片段交给 DeepSeek 生成答案。"""
    try:
        result = await run_in_threadpool(service.answer, request.question, request.history, request.top_k)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ChatResponse(
        answer=result["answer"],
        rewritten_question=result["rewritten_question"],
        sources=[_to_source_hit(hit) for hit in result["hits"]],
    )

