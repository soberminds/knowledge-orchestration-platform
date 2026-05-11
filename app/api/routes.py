"""HTTP API routes."""

from __future__ import annotations

import json
from typing import Iterator

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool

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
    return SourceHit(
        source=hit.source,
        chunk_index=hit.chunk_index,
        page=hit.page,
        score=hit.score,
        preview=hit.preview,
    )


def _sse_payload(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/health", response_model=HealthResponse)
async def health(service: KnowledgeBaseService = Depends(get_knowledge_base_service)) -> HealthResponse:
    return HealthResponse(
        status="ok",
        collection_name=service.settings.collection_name,
        indexed_chunks=service.count_chunks(),
    )


@router.get("/documents", response_model=list[DocumentInfo])
async def list_documents(service: KnowledgeBaseService = Depends(get_knowledge_base_service)) -> list[DocumentInfo]:
    infos: list[DocumentInfo] = []
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
    try:
        result = await run_in_threadpool(service.answer, request.question, request.history, request.top_k)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ChatResponse(
        answer=result["answer"],
        rewritten_question=result["rewritten_question"],
        sources=[_to_source_hit(hit) for hit in result["hits"]],
    )


@router.post("/chat/stream")
async def chat_stream(
    request: ChatRequest,
    service: KnowledgeBaseService = Depends(get_knowledge_base_service),
) -> StreamingResponse:
    def event_stream() -> Iterator[str]:
        try:
            for event in service.stream_answer(request.question, request.history, request.top_k):
                if event.get("type") == "done":
                    payload = {
                        "type": "done",
                        "answer": event.get("answer", ""),
                        "rewritten_question": event.get("rewritten_question", ""),
                        "sources": [_to_source_hit(hit).model_dump() for hit in event.get("hits", [])],
                    }
                    yield _sse_payload(payload)
                    continue
                yield _sse_payload(event)
        except Exception as exc:
            yield _sse_payload({"type": "error", "error": str(exc)})

    return StreamingResponse(
        iterate_in_threadpool(event_stream()),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
