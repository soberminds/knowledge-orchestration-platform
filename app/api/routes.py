"""HTTP API routes."""
# FastAPI 后端服务的路由层，负责处理 HTTP 请求，调用底层的知识库服务（KnowledgeBaseService），并返回响应


# 允许在类型注解中使用字符串形式的类名（例如 'KnowledgeBaseService'），避免循环导入问题。
from __future__ import annotations


import json
import logging
import mimetypes
import os
from datetime import datetime
from pathlib import Path
from typing import Iterator

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool

from app.core.settings import settings
from app.dependencies import get_knowledge_base_service
from app.schemas import (
    CitationRef,
    CostEstimate,
    ChatRequest,
    ChatOptionsResponse,
    ChatResponse,
    DocumentInfo,
    FileEditTextResponse,
    FileEditTextSaveRequest,
    FileEditTextSaveResponse,
    HealthResponse,
    IngestResponse,
    SearchRequest,
    SearchResponse,
    SourceHit,
    TokenUsage,
)
from app.services.files import TEXT_FILE_EXTENSIONS, read_file_page_text
from app.services.knowledge_base import KnowledgeBaseService, ModelUnavailableError, SearchHit
from app.services.preview_pdf import get_preview_pdf_path


router = APIRouter(prefix="/api", tags=["rag"])
logger = logging.getLogger(__name__)
TEXT_EDIT_MAX_BYTES = 2 * 1024 * 1024
TEXT_EDIT_ENCODINGS: tuple[str, ...] = ("utf-8", "utf-8-sig", "gb18030")
EDITABLE_TEXT_EXTENSIONS = set(TEXT_FILE_EXTENSIONS)


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


def _to_token_usage(payload: dict | None) -> TokenUsage | None:
    if not payload:
        return None
    try:
        return TokenUsage(
            prompt_tokens=int(payload.get("prompt_tokens", 0)),
            completion_tokens=int(payload.get("completion_tokens", 0)),
            total_tokens=int(payload.get("total_tokens", 0)),
        )
    except Exception:
        return None


def _to_cost_estimate(payload: dict | None) -> CostEstimate | None:
    if not payload:
        return None
    try:
        return CostEstimate(
            currency=str(payload.get("currency", "CNY")),
            input_per_1m_tokens=float(payload["input_per_1m_tokens"]) if payload.get("input_per_1m_tokens") is not None else None,
            output_per_1m_tokens=float(payload["output_per_1m_tokens"]) if payload.get("output_per_1m_tokens") is not None else None,
            input_cost=float(payload["input_cost"]) if payload.get("input_cost") is not None else None,
            output_cost=float(payload["output_cost"]) if payload.get("output_cost") is not None else None,
            total_cost=float(payload["total_cost"]) if payload.get("total_cost") is not None else None,
            estimated=bool(payload.get("estimated", True)),
        )
    except Exception:
        return None


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


def _relative_path_from_root(file_path: Path) -> str:
    return str(file_path.relative_to(settings.root_dir)).replace("\\", "/")


def _validate_text_edit_file(file_path: Path) -> tuple[str, int]:
    extension = file_path.suffix.lower()
    if extension not in EDITABLE_TEXT_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported editable extension: {extension}.",
        )

    size_bytes = int(file_path.stat().st_size)
    if size_bytes > TEXT_EDIT_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large to edit inline ({size_bytes} bytes > {TEXT_EDIT_MAX_BYTES} bytes).",
        )
    return extension, size_bytes


def _decode_text_bytes(raw: bytes) -> tuple[str, str]:
    for encoding in TEXT_EDIT_ENCODINGS:
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise HTTPException(
        status_code=415,
        detail="Cannot decode this file as text. Please use UTF-8 or GB18030 encoded text files.",
    )


def _atomic_write_text(file_path: Path, content: str, encoding: str = "utf-8") -> int:
    encoded = content.encode(encoding)
    if len(encoded) > TEXT_EDIT_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Saved content too large ({len(encoded)} bytes > {TEXT_EDIT_MAX_BYTES} bytes).",
        )

    temp_path = file_path.with_name(f"{file_path.name}.tmp")
    with temp_path.open("wb") as temp_file:
        temp_file.write(encoded)
        temp_file.flush()
        os.fsync(temp_file.fileno())
    temp_path.replace(file_path)
    return len(encoded)


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


@router.delete("/documents", response_model=IngestResponse)
async def delete_document(
    path: str,
    service: KnowledgeBaseService = Depends(get_knowledge_base_service),
) -> IngestResponse:
    file_path = _resolve_file_path(path)
    try:
        stats = await run_in_threadpool(service.delete_source_file_and_rebuild, file_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return IngestResponse(
        documents_loaded=stats.documents_loaded,
        chunks_indexed=stats.chunks_indexed,
        source_files=stats.source_files,
    )


@router.get("/file")
async def open_file(path: str) -> FileResponse:
    file_path = _resolve_file_path(path)
    media_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
    return FileResponse(
        path=str(file_path),
        media_type=media_type,
    )


@router.get("/file/edit-text", response_model=FileEditTextResponse)
async def get_file_edit_text(path: str) -> FileEditTextResponse:
    file_path = _resolve_file_path(path)
    extension, size_bytes = _validate_text_edit_file(file_path)
    raw = file_path.read_bytes()
    content, encoding = _decode_text_bytes(raw)
    return FileEditTextResponse(
        path=_relative_path_from_root(file_path),
        extension=extension,
        content=content,
        encoding=encoding,
        size_bytes=size_bytes,
        editable=True,
    )


@router.put("/file/edit-text", response_model=FileEditTextSaveResponse)
async def save_file_edit_text(payload: FileEditTextSaveRequest) -> FileEditTextSaveResponse:
    file_path = _resolve_file_path(payload.path)
    extension, _ = _validate_text_edit_file(file_path)
    size_bytes = _atomic_write_text(file_path, payload.content, encoding="utf-8")
    modified_at = datetime.fromtimestamp(file_path.stat().st_mtime).isoformat(timespec="seconds")
    return FileEditTextSaveResponse(
        path=_relative_path_from_root(file_path),
        saved=True,
        extension=extension,
        encoding="utf-8",
        size_bytes=size_bytes,
        modified_at=modified_at,
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
        result = await run_in_threadpool(
            service.answer,
            request.question,
            request.history,
            request.top_k,
            request.model,
            request.thinking_mode,
            request.web_search,
            request.native_web_search,
            request.external_web_search,
        )
    except ModelUnavailableError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ChatResponse(
        answer=result["answer"],
        rewritten_question=result["rewritten_question"],
        sources=[_to_source_hit(hit) for hit in result["hits"]],
        citations=[_to_citation_ref(item) for item in result.get("citations", [])],
        model=str(result.get("model") or request.model or service.settings.deepseek_model),
        usage=_to_token_usage(result.get("usage")),
        cost_estimate=_to_cost_estimate(result.get("cost_estimate")),
    )


@router.post("/chat/stream")
async def chat_stream(
    request: ChatRequest,
    service: KnowledgeBaseService = Depends(get_knowledge_base_service),
) -> StreamingResponse:
    def event_stream() -> Iterator[str]:
        try:
            for event in service.stream_answer(
                request.question,
                request.history,
                request.top_k,
                request.model,
                request.thinking_mode,
                request.web_search,
                request.native_web_search,
                request.external_web_search,
            ):
                if event.get("type") == "done":
                    usage = _to_token_usage(event.get("usage"))
                    cost_estimate = _to_cost_estimate(event.get("cost_estimate"))
                    payload = {
                        "type": "done",
                        "answer": event.get("answer", ""),
                        "rewritten_question": event.get("rewritten_question", ""),
                        "sources": [_to_source_hit(hit).model_dump() for hit in event.get("hits", [])],
                        "citations": [_to_citation_ref(item).model_dump() for item in event.get("citations", [])],
                        "model": event.get("model", request.model or service.settings.deepseek_model),
                        "usage": usage.model_dump() if usage else None,
                        "cost_estimate": cost_estimate.model_dump() if cost_estimate else None,
                    }
                    yield _sse_payload(payload)
                    continue
                yield _sse_payload(event)
        except ModelUnavailableError as exc:
            yield _sse_payload({"type": "error", "error": str(exc)})
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


@router.get("/chat/options", response_model=ChatOptionsResponse)
async def chat_options(service: KnowledgeBaseService = Depends(get_knowledge_base_service)) -> ChatOptionsResponse:
    model_options = service.resolve_model_options()
    return ChatOptionsResponse(
        default_model=service.settings.deepseek_model,
        models=service.resolve_available_models(),
        model_options=model_options,
        web_search_available=service.is_web_search_available(),
        external_web_search_available=service.is_web_search_available(),
        thinking_modes=["quick", "deep"],
    )
