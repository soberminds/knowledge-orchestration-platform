"""HTTP API routes."""

from __future__ import annotations

import json
import logging
import mimetypes
from pathlib import Path
from typing import Iterator

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool

from app.core.settings import settings
from app.dependencies import get_knowledge_base_service
from app.schemas import (
    CitationRef,
    ChatRequest,
    ChatResponse,
    DocumentInfo,
    HealthResponse,
    IngestResponse,
    SearchRequest,
    SearchResponse,
    SourceHit,
)
from app.services.files import read_file_page_text
from app.services.knowledge_base import KnowledgeBaseService, SearchHit
from app.services.preview_pdf import get_preview_pdf_path


router = APIRouter(prefix="/api", tags=["rag"])
logger = logging.getLogger(__name__)


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


def _to_citation_ref(payload: dict) -> CitationRef:
    return CitationRef(
        label=str(payload.get("label", "")),
        source=str(payload.get("source", "unknown")),
        page=int(payload["page"]) if payload.get("page") is not None else None,
        chunk_indices=[int(value) for value in payload.get("chunk_indices", [])],
        score=float(payload["score"]) if payload.get("score") is not None else None,
        preview=str(payload.get("preview", "")),
    )


def _resolve_file_path(path_value: str) -> Path:
    if not path_value:
        raise HTTPException(status_code=400, detail="path is required")

    candidate = (settings.root_dir / path_value).resolve()
    allowed_roots = [settings.docs_dir.resolve(), settings.uploads_dir.resolve()]
    if not any(root == candidate or root in candidate.parents for root in allowed_roots):
        raise HTTPException(status_code=403, detail="File path is not allowed.")
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    return candidate


@router.get("/health", response_model=HealthResponse)
async def health(service: KnowledgeBaseService = Depends(get_knowledge_base_service)) -> HealthResponse:
    indexed_chunks = 0
    status = "ok"
    try:
        indexed_chunks = await run_in_threadpool(service.count_chunks)
    except Exception as exc:
        status = "degraded"
        logger.warning("Health chunk count failed, falling back to 0: %s", exc)

    return HealthResponse(
        status=status,
        collection_name=service.settings.collection_name,
        indexed_chunks=indexed_chunks,
    )


@router.get("/documents", response_model=list[DocumentInfo])
async def list_documents(service: KnowledgeBaseService = Depends(get_knowledge_base_service)) -> list[DocumentInfo]:
    try:
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
    except Exception as exc:
        logger.warning("List documents failed, returning empty list: %s", exc)
        return []


@router.get("/file")
async def open_file(path: str) -> FileResponse:
    file_path = _resolve_file_path(path)
    media_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
    return FileResponse(
        path=str(file_path),
        media_type=media_type,
    )


@router.get("/file/preview-pdf")
async def open_file_preview_pdf(path: str) -> FileResponse:
    source_path = _resolve_file_path(path)
    try:
        preview_path = await run_in_threadpool(get_preview_pdf_path, source_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Preview conversion failed: {exc}") from exc

    return FileResponse(
        path=str(preview_path),
        media_type="application/pdf",
        filename=f"{source_path.stem}.pdf",
    )


@router.get("/file/page-text")
async def file_page_text(path: str, page: int | None = None) -> dict:
    file_path = _resolve_file_path(path)
    try:
        payload = read_file_page_text(file_path, page=page)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Failed to read file: {exc}") from exc
    return {"path": path, **payload}


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
        citations=[_to_citation_ref(item) for item in result.get("citations", [])],
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
                        "citations": [_to_citation_ref(item).model_dump() for item in event.get("citations", [])],
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
