"""HTTP API routes."""
# FastAPI 后端服务的路由层，负责处理 HTTP 请求，调用底层的知识库服务（KnowledgeBaseService），并返回响应


# 允许在类型注解中使用字符串形式的类名（例如 'KnowledgeBaseService'），避免循环导入问题。
from __future__ import annotations


import json
import logging
import mimetypes
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import urlparse, urlunparse

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool

from app.core.database import DatabaseUnavailableError
from app.core.request_context import get_current_user_id, reset_current_user_id, set_current_user_id
from app.core.settings import settings
from app.dependencies import get_auth_service, get_chat_memory_service, get_document_library_service, get_knowledge_base_service
from app.dependencies import get_agent_tool_confirmation_service
from app.schemas import (
    AgentToolConfirmationActionRequest,
    AgentToolConfirmationResponse,
    AuthRequest,
    AuthResponse,
    CitationRef,
    CostEstimate,
    ChatConversationListResponse,
    ChatConversationSummary,
    ChatMessagePageResponse,
    ChatMessageRecord,
    ChatRequest,
    CreateDocumentFolderRequest,
    CreateDocumentFolderResponse,
    DocumentMutationRequest,
    DocumentMutationResponse,
    ModelDiagnostics,
    ChatOptionsResponse,
    ChatResponse,
    DocumentInfo,
    KnowledgeBaseScopeOption,
    FileEditTextResponse,
    FileEditTextSaveRequest,
    FileEditTextSaveResponse,
    HealthResponse,
    IndexFileListResponse,
    IndexFileStatusCounts,
    IngestResponse,
    OfficeEditorConfigResponse,
    OfficeCallbackStatusResponse,
    OfficeHealthResponse,
    SearchRequest,
    SearchResponse,
    SourceHit,
    WorkspaceScopeOption,
    UserProfile,
    TokenUsage,
)
from app.services.agent_tools import AgentToolConfirmationService
from app.services.auth import AuthError, UserAuthService
from app.services.files import TEXT_FILE_EXTENSIONS, read_file_page_text
from app.services.chat_memory import ChatMemoryService
from app.services.document_library import DocumentLibraryService
from app.services.knowledge_base import KnowledgeBaseService, ModelUnavailableError, SearchHit
from app.services.onlyoffice import (
    OFFICE_EDITOR_EXTENSIONS,
    build_callback_url,
    build_onlyoffice_document_key,
    build_path_token,
    build_public_file_url,
    callback_signing_secret,
    decode_hs256_jwt,
    decode_path_token,
    download_binary,
    encode_hs256_jwt,
    extract_bearer_token,
    is_onlyoffice_editable_extension,
    to_onlyoffice_document_type,
)
from app.services.preview_pdf import get_preview_pdf_path


router = APIRouter(prefix="/api", tags=["rag"])
logger = logging.getLogger(__name__)
TEXT_EDIT_MAX_BYTES = 2 * 1024 * 1024
TEXT_EDIT_ENCODINGS: tuple[str, ...] = ("utf-8", "utf-8-sig", "gb18030")
EDITABLE_TEXT_EXTENSIONS = set(TEXT_FILE_EXTENSIONS)
OFFICE_CALLBACK_SAVE_STATUSES = {2, 6}
_office_callback_status_lock = threading.Lock()
_office_callback_status_by_path: dict[str, dict[str, Any]] = {}
SESSION_COOKIE_NAME = UserAuthService.SESSION_COOKIE_NAME
_index_job_lock = threading.Lock()
_index_job_running = False
_index_job_queue: list[dict[str, Any]] = []


def _to_source_hit(hit: SearchHit) -> SourceHit:
    return SourceHit(
        source=hit.source,
        chunk_index=hit.chunk_index,
        page=hit.page,
        score=hit.score,
        preview=hit.preview,
        file_id=hit.file_id,
        folder_id=hit.folder_id,
        display_name=hit.display_name,
        display_path=hit.display_path,
        folder_path=hit.folder_path,
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
        file_id=int(payload["file_id"]) if payload.get("file_id") is not None else None,
        folder_id=int(payload["folder_id"]) if payload.get("folder_id") is not None else None,
        display_name=str(payload.get("display_name") or "") or None,
        display_path=str(payload.get("display_path") or "") or None,
        folder_path=str(payload.get("folder_path") or "") or None,
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


def _to_model_diagnostics(payload: dict | None) -> ModelDiagnostics | None:
    if not payload or not isinstance(payload, dict):
        return None
    try:
        return ModelDiagnostics(
            requested_model=str(payload.get("requested_model") or "") or None,
            provider=str(payload.get("provider") or "") or None,
            resolved_model=str(payload.get("resolved_model") or "") or None,
            native_web_search_used=bool(payload.get("native_web_search_used", False)),
            external_web_search_used=bool(payload.get("external_web_search_used", False)),
            thinking_mode=str(payload.get("thinking_mode") or "") or None,
            run_mode=str(payload.get("run_mode") or "") or None,
            provider_api=str(payload.get("provider_api") or "") or None,
            option_fallback_used=bool(payload.get("option_fallback_used", False)),
            warnings=[str(item) for item in payload.get("warnings", []) if item],
            tool_calls=[
                dict(item)
                for item in payload.get("tool_calls", [])
                if isinstance(item, dict)
            ],
            capabilities=dict(payload.get("capabilities"))
            if isinstance(payload.get("capabilities"), dict)
            else None,
        )
    except Exception:
        return None


def _to_user_profile(payload: dict | None) -> UserProfile | None:
    if not payload or not isinstance(payload, dict):
        return None
    try:
        return UserProfile(
            id=int(payload["id"]),
            username=str(payload.get("username") or ""),
            nickname=str(payload.get("nickname") or "") or None,
            avatar_url=str(payload.get("avatar_url") or "") or None,
            user_type=str(payload.get("user_type") or "local"),
            is_default=bool(payload.get("is_default", False)),
            status=int(payload.get("status", 1)),
            last_login_at=str(payload.get("last_login_at") or "") or None,
            created_at=str(payload.get("created_at") or "") or None,
            updated_at=str(payload.get("updated_at") or "") or None,
            authenticated=bool(payload.get("authenticated", False)),
            is_guest=bool(payload.get("is_guest", False)),
        )
    except Exception:
        return None


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=UserAuthService.SESSION_TTL_SEC,
        httponly=True,
        samesite="lax",
        secure=False,
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")


def _normalize_current_request_user(http_request: Request) -> None:
    token = http_request.cookies.get(SESSION_COOKIE_NAME) or http_request.headers.get("Authorization")
    if token and str(token).lower().startswith("bearer "):
        token = str(token)[7:].strip()
    if not token:
        return
    auth_service = get_auth_service()
    try:
        user_id = auth_service.resolve_effective_user_id_from_request(http_request)
    except Exception:
        return
    set_current_user_id(user_id)


def _bind_request_user(http_request: Request) -> None:
    _normalize_current_request_user(http_request)


@router.get("/auth/me", response_model=UserProfile)
async def auth_me(
    request: Request,
    auth_service: UserAuthService = Depends(get_auth_service),
) -> UserProfile:
    try:
        payload = await run_in_threadpool(auth_service.resolve_current_user, request)
        user = _to_user_profile(payload)
        if user is None:
            raise HTTPException(status_code=500, detail="Failed to resolve current user.")
        return user
    except DatabaseUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/auth/login", response_model=AuthResponse)
async def auth_login(
    payload: AuthRequest,
    response: Response,
    auth_service: UserAuthService = Depends(get_auth_service),
) -> AuthResponse:
    try:
        result = await run_in_threadpool(auth_service.login, payload.username, payload.password)
        token = str(result.pop("session_token"))
        _set_session_cookie(response, token)
        user = _to_user_profile(result)
        if user is None:
            raise HTTPException(status_code=500, detail="Failed to build user profile.")
        return AuthResponse(user=user, session_token=token)
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DatabaseUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/auth/register", response_model=AuthResponse)
async def auth_register(
    payload: AuthRequest,
    response: Response,
    auth_service: UserAuthService = Depends(get_auth_service),
) -> AuthResponse:
    try:
        result = await run_in_threadpool(auth_service.register, payload.username, payload.password, payload.nickname)
        token = str(result.pop("session_token"))
        _set_session_cookie(response, token)
        user = _to_user_profile(result)
        if user is None:
            raise HTTPException(status_code=500, detail="Failed to build user profile.")
        return AuthResponse(user=user, session_token=token)
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DatabaseUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/auth/logout")
async def auth_logout(
    response: Response,
    request: Request,
    auth_service: UserAuthService = Depends(get_auth_service),
) -> dict[str, bool]:
    token = request.cookies.get(SESSION_COOKIE_NAME) or request.headers.get("Authorization")
    if token and str(token).lower().startswith("bearer "):
        token = str(token)[7:].strip()
    try:
        await run_in_threadpool(auth_service.logout, str(token or ""))
    finally:
        _clear_session_cookie(response)
    return {"ok": True}


def _source_hits_payload(hits: list[SearchHit]) -> list[dict[str, Any]]:
    return [_to_source_hit(hit).model_dump() for hit in hits]


def _citation_refs_payload(citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_to_citation_ref(item).model_dump() for item in citations]


def _resolve_chat_memory_context(
    chat_memory: ChatMemoryService,
    request: ChatRequest,
) -> tuple[int | None, list]:
    try:
        conversation = chat_memory.resolve_conversation(
            request.conversation_id,
            title_seed=request.question,
            scope_type=request.scope_type,
            scope_id=request.scope_id,
            workspace_key=request.workspace_key,
        )
        history = chat_memory.resolve_history(conversation.conversation_id, request.history)
        return conversation.conversation_id, history
    except Exception as exc:
        logger.warning("Chat memory is unavailable; falling back to request history: %s", exc)
        return request.conversation_id, list(request.history)


def _get_request_user_context(request: Request) -> int | None:
    token = request.cookies.get(SESSION_COOKIE_NAME) or request.headers.get("Authorization")
    if token and str(token).lower().startswith("bearer "):
        token = str(token)[7:].strip()
    auth_service = UserAuthService()
    try:
        return auth_service.resolve_effective_user_id_from_request(request)
    except Exception:
        return None


def _get_context_user_id_for_confirmation() -> int | None:
    try:
        return get_current_user_id()
    except Exception:
        return None


async def _ensure_request_user_context(request: Request) -> None:
    user_id = await run_in_threadpool(_get_request_user_context, request)
    if user_id is None:
        return
    set_current_user_id(user_id)


async def _reindex_mutated_document_files(
    library: DocumentLibraryService,
    service: KnowledgeBaseService,
    *,
    file_ids: list[int],
    source_paths: list[str],
):
    normalized_ids = sorted({int(item) for item in file_ids if item is not None})
    normalized_sources = [str(item).strip() for item in source_paths if str(item).strip()]
    index_job = await run_in_threadpool(library.create_index_job, job_type="files", file_ids=normalized_ids)
    job_id = index_job.get("job_id")
    normalized_ids = [int(item) for item in index_job.get("file_ids", normalized_ids) if item is not None]
    normalized_sources = [str(item) for item in index_job.get("source_paths", normalized_sources) if str(item).strip()]

    await run_in_threadpool(library.start_index_job, int(job_id) if job_id is not None else None)

    def progress_callback(event: dict[str, Any]) -> None:
        library.update_index_job_file(
            job_id=int(job_id) if job_id is not None else None,
            file_id=event.get("file_id"),
            status=event.get("status"),
            stage=event.get("stage"),
            progress=event.get("progress"),
            total_chunks=event.get("total_chunks"),
            indexed_chunks=event.get("indexed_chunks"),
            error_message=event.get("error_message"),
        )

    try:
        stats = await run_in_threadpool(
            service.reindex_document_files,
            file_ids=normalized_ids,
            source_paths=normalized_sources,
            progress_callback=progress_callback,
        )
    except Exception as exc:
        if normalized_ids:
            await run_in_threadpool(
                library.update_file_index_states,
                normalized_ids,
                index_status="failed",
                parse_error=str(exc),
            )
        await run_in_threadpool(
            library.finish_index_job,
            int(job_id) if job_id is not None else None,
            status="failed",
            error_message=str(exc),
        )
        raise
    await run_in_threadpool(library.finish_index_job, int(job_id) if job_id is not None else None)
    return stats


def _enqueue_index_job(
    background_tasks: BackgroundTasks,
    library: DocumentLibraryService,
    service: KnowledgeBaseService,
    *,
    user_id: int | None,
    kind: str,
    job_id: int | None = None,
    file_ids: list[int] | None = None,
    source_paths: list[str] | None = None,
) -> None:
    global _index_job_running

    normalized_file_ids = sorted({int(item) for item in (file_ids or []) if item is not None})
    normalized_source_paths = [str(item).strip() for item in (source_paths or []) if str(item).strip()]
    job = {
        "kind": kind,
        "job_id": job_id,
        "user_id": user_id,
        "file_ids": normalized_file_ids,
        "source_paths": normalized_source_paths,
    }

    should_start = False
    with _index_job_lock:
        _index_job_queue.append(job)
        if not _index_job_running:
            _index_job_running = True
            should_start = True

    if should_start:
        background_tasks.add_task(_run_index_job_queue, library, service)


def _pop_index_job() -> dict[str, Any] | None:
    global _index_job_running

    with _index_job_lock:
        if not _index_job_queue:
            _index_job_running = False
            return None
        return _index_job_queue.pop(0)


def _run_index_job_queue(library: DocumentLibraryService, service: KnowledgeBaseService) -> None:
    while True:
        job = _pop_index_job()
        if job is None:
            return

        user_id = job.get("user_id")
        token = set_current_user_id(int(user_id) if user_id is not None else None)
        try:
            kind = str(job.get("kind") or "")
            raw_job_id = job.get("job_id")
            job_id = int(raw_job_id) if raw_job_id is not None else None
            file_ids = [int(item) for item in job.get("file_ids", []) if item is not None]
            source_paths = [str(item) for item in job.get("source_paths", []) if str(item).strip()]

            if job_id is not None:
                library.start_index_job(job_id)

            def progress_callback(event: dict[str, Any]) -> None:
                library.update_index_job_file(
                    job_id=job_id,
                    file_id=event.get("file_id"),
                    status=event.get("status"),
                    stage=event.get("stage"),
                    progress=event.get("progress"),
                    total_chunks=event.get("total_chunks"),
                    indexed_chunks=event.get("indexed_chunks"),
                    error_message=event.get("error_message"),
                )

            if kind == "full":
                if not file_ids:
                    targets = library.list_document_index_targets()
                    file_ids = [int(item) for item in targets.get("file_ids", []) if item is not None]
                    source_paths = [str(item) for item in targets.get("source_paths", []) if str(item).strip()]
                if file_ids:
                    library.update_file_index_states(
                        file_ids,
                        index_status="running",
                        parse_status="running",
                        parse_error=None,
                    )
                logger.info("Starting queued full index rebuild. user_id=%s", user_id)
                stats = service.reindex_document_files(
                    file_ids=file_ids,
                    source_paths=source_paths,
                    reset_collection=True,
                    progress_callback=progress_callback,
                )
                if job_id is not None:
                    library.finish_index_job(job_id)
                logger.info(
                    "Queued full index rebuild finished. documents=%s chunks=%s",
                    stats.documents_loaded,
                    stats.chunks_indexed,
                )
                continue

            if kind == "files":
                if file_ids:
                    library.update_file_index_states(
                        file_ids,
                        index_status="running",
                        parse_status="running",
                        parse_error=None,
                    )
                logger.info("Starting queued file reindex. user_id=%s file_ids=%s", user_id, file_ids)
                stats = service.reindex_document_files(
                    file_ids=file_ids,
                    source_paths=source_paths,
                    progress_callback=progress_callback,
                )
                if job_id is not None:
                    library.finish_index_job(job_id)
                logger.info(
                    "Queued file reindex finished. documents=%s chunks=%s file_ids=%s",
                    stats.documents_loaded,
                    stats.chunks_indexed,
                    file_ids,
                )
                continue

            logger.warning("Unknown queued index job kind: %s", kind)
            if job_id is not None:
                library.finish_index_job(job_id, status="failed", error_message=f"Unknown index job kind: {kind}")
        except Exception as exc:
            raw_job_id = job.get("job_id")
            job_id = int(raw_job_id) if raw_job_id is not None else None
            file_ids = [int(item) for item in job.get("file_ids", []) if item is not None]
            if not file_ids and str(job.get("kind") or "") == "full":
                try:
                    file_ids = library.list_document_file_ids()
                except Exception:
                    file_ids = []
            if file_ids:
                try:
                    library.update_file_index_states(
                        file_ids,
                        index_status="failed",
                        parse_status="failed",
                        parse_error=str(exc),
                    )
                except Exception:
                    logger.exception("Failed to mark queued index job as failed.")
            if job_id is not None:
                try:
                    library.finish_index_job(job_id, status="failed", error_message=str(exc))
                except Exception:
                    logger.exception("Failed to mark index job as failed.")
            logger.exception("Queued index job failed: %s", exc)
        finally:
            reset_current_user_id(token)


def _save_chat_memory_turn(
    chat_memory: ChatMemoryService,
    *,
    conversation_id: int | None,
    request: ChatRequest,
    result: dict[str, Any],
) -> None:
    if conversation_id is None:
        return
    try:
        chat_memory.save_turn(
            conversation_id=conversation_id,
            question=request.question,
            answer=str(result.get("answer") or ""),
            model_name=str(result.get("model") or request.model or "") or None,
            message_parts=[item.model_dump(exclude_none=True) for item in request.message_parts],
            citations=_citation_refs_payload(result.get("citations", [])),
            usage=result.get("usage"),
            model_diagnostics=result.get("model_diagnostics"),
            reasoning_parts=[str(item) for item in result.get("reasoning_parts", []) if str(item).strip()],
            rewritten_question=str(result.get("rewritten_question") or ""),
            question_mode=str(result.get("question_mode") or "") or None,
        )
    except Exception as exc:
        logger.warning("Failed to save chat memory turn: %s", exc)


def _to_agent_confirmation_response(payload: dict[str, Any]) -> AgentToolConfirmationResponse:
    return AgentToolConfirmationResponse(
        confirmation_id=str(payload.get("confirmation_id") or ""),
        user_id=int(payload["user_id"]) if payload.get("user_id") is not None else None,
        tool_name=str(payload.get("tool_name") or ""),
        display_name=str(payload.get("display_name") or ""),
        arguments=dict(payload.get("arguments") or {}),
        message=str(payload.get("message") or ""),
        status=str(payload.get("status") or "pending"),
        created_at=str(payload.get("created_at") or ""),
        expires_at=str(payload.get("expires_at") or ""),
        result=dict(payload.get("result")) if isinstance(payload.get("result"), dict) else None,
        error=str(payload.get("error") or "") or None,
        assistant_followup=str(payload.get("assistant_followup") or "") or None,
        confirmed_at=str(payload.get("confirmed_at") or "") or None,
        cancelled_at=str(payload.get("cancelled_at") or "") or None,
    )


def _persist_tool_confirmation_state(
    chat_memory: ChatMemoryService,
    *,
    conversation_id: int | None,
    payload: dict[str, Any],
) -> str | None:
    if conversation_id is None:
        return None
    try:
        assistant_followup = chat_memory.update_tool_confirmation_state(
            conversation_id=int(conversation_id),
            confirmation_id=str(payload.get("confirmation_id") or ""),
            status=str(payload.get("status") or ""),
            result=dict(payload.get("result")) if isinstance(payload.get("result"), dict) else None,
            error=str(payload.get("error") or "") or None,
            confirmed_at=str(payload.get("confirmed_at") or "") or None,
            cancelled_at=str(payload.get("cancelled_at") or "") or None,
        )
        if assistant_followup:
            payload["assistant_followup"] = assistant_followup
        return assistant_followup
    except Exception:
        logger.exception("Failed to persist agent tool confirmation state.")
        return None


def _streaming_event_payload(
    event: dict[str, Any],
    *,
    conversation_id: int | None,
    request: ChatRequest,
    service: KnowledgeBaseService,
) -> dict[str, Any]:
    event_type = str(event.get("type") or "")

    # Backward-compatible SSE event for the current frontend.
    if event_type == "content_delta":
        return {"type": "delta", "delta": str(event.get("content_delta") or "")}

    if event_type == "reasoning_delta":
        return {"type": "reasoning_delta", "delta": str(event.get("reasoning_delta") or "")}

    if event_type == "tool_call_delta":
        return {
            "type": "tool_call_delta",
            "tool_call_delta": event.get("tool_call_delta") or {},
        }

    if event_type == "usage":
        usage = _to_token_usage(event.get("usage"))
        return {"type": "usage", "usage": usage.model_dump() if usage else None}

    if event_type == "diagnostics":
        return {"type": "diagnostics", "model_diagnostics": event.get("diagnostics")}

    if event_type == "done":
        usage = _to_token_usage(event.get("usage"))
        cost_estimate = _to_cost_estimate(event.get("cost_estimate"))
        return {
            "type": "done",
            "answer": event.get("answer", ""),
            "conversation_id": conversation_id,
            "rewritten_question": event.get("rewritten_question", ""),
            "sources": _source_hits_payload(event.get("hits", [])),
            "citations": _citation_refs_payload(event.get("citations", [])),
            "model": event.get("model", request.model or service.settings.deepseek_model),
            "usage": usage.model_dump() if usage else None,
            "cost_estimate": cost_estimate.model_dump() if cost_estimate else None,
            "model_diagnostics": event.get("model_diagnostics"),
            "reasoning_parts": [str(item) for item in event.get("reasoning_parts", []) if str(item).strip()],
        }

    if event_type == "error":
        return {"type": "error", "error": str(event.get("error") or "Stream error.")}

    return {"type": "error", "error": f"Unknown stream event type: {event_type or '(empty)'}"}


def _resolve_file_path(path_value: str) -> Path:
    if not path_value:
        raise HTTPException(status_code=400, detail="path is required")

    candidate = (settings.root_dir / path_value).resolve()
    allowed_roots = [
        settings.user_docs_dir.resolve(),
    ]
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


def _atomic_write_bytes(file_path: Path, content: bytes) -> int:
    temp_path = file_path.with_name(f"{file_path.name}.tmp")
    with temp_path.open("wb") as temp_file:
        temp_file.write(content)
        temp_file.flush()
        os.fsync(temp_file.fileno())
    temp_path.replace(file_path)
    return len(content)


def _public_backend_url() -> str:
    value = (settings.public_backend_url or "").strip().rstrip("/")
    return value or "http://127.0.0.1:8000"


def _public_backend_internal_url() -> str:
    value = (settings.public_backend_internal_url or "").strip().rstrip("/")
    return value


def _onlyoffice_callback_secret() -> str:
    return callback_signing_secret(settings.root_dir, settings.onlyoffice_jwt_secret)


def _effective_onlyoffice_index_update_mode() -> str:
    mode = (settings.onlyoffice_index_update_mode or "").strip().lower()
    if mode in {"incremental", "full"}:
        return mode
    return "incremental"


def _set_office_callback_status(
    relative_path: str,
    *,
    success: bool,
    message: str = "",
    callback_status: int | None = None,
) -> None:
    now_iso = datetime.now().isoformat(timespec="seconds")
    status = "success" if success else "failed"
    with _office_callback_status_lock:
        previous = dict(_office_callback_status_by_path.get(relative_path, {}))
        payload: dict[str, Any] = {
            "path": relative_path,
            "has_event": True,
            "status": status,
            "success": success,
            "message": message.strip(),
            "callback_status": callback_status,
            "updated_at": now_iso,
            "index_status": str(previous.get("index_status", "idle")),
            "index_message": str(previous.get("index_message", "")),
            "index_updated_at": previous.get("index_updated_at"),
        }
        _office_callback_status_by_path[relative_path] = payload


def _get_office_callback_status(relative_path: str) -> OfficeCallbackStatusResponse:
    with _office_callback_status_lock:
        payload = _office_callback_status_by_path.get(relative_path)
    if not payload:
        return OfficeCallbackStatusResponse(path=relative_path)
    return OfficeCallbackStatusResponse(**payload)


def _set_office_index_status(
    relative_path: str,
    *,
    index_status: str,
    index_message: str = "",
) -> None:
    now_iso = datetime.now().isoformat(timespec="seconds")
    with _office_callback_status_lock:
        previous = dict(_office_callback_status_by_path.get(relative_path, {}))
        payload: dict[str, Any] = {
            "path": relative_path,
            "has_event": bool(previous.get("has_event", False)),
            "status": str(previous.get("status", "unknown")),
            "success": previous.get("success"),
            "message": str(previous.get("message", "")),
            "callback_status": previous.get("callback_status"),
            "updated_at": previous.get("updated_at"),
            "index_status": index_status,
            "index_message": index_message.strip(),
            "index_updated_at": now_iso,
        }
        _office_callback_status_by_path[relative_path] = payload


def _run_onlyoffice_index_update(
    relative_path: str,
    absolute_path: str,
    mode: str,
    service: KnowledgeBaseService,
) -> None:
    _set_office_index_status(relative_path, index_status="running", index_message=f"Indexing ({mode})...")
    try:
        if mode == "full":
            stats = service.rebuild_index()
        else:
            stats = service.reindex_source_file(Path(absolute_path))
        _set_office_index_status(
            relative_path,
            index_status="success",
            index_message=f"Indexed chunks: {stats.chunks_indexed}.",
        )
    except Exception as exc:
        logger.exception("ONLYOFFICE index update failed for %s: %s", relative_path, exc)
        _set_office_index_status(
            relative_path,
            index_status="failed",
            index_message=f"Index update failed: {exc}",
        )


def _http_probe(url: str, *, method: str = "GET", timeout_sec: int = 6, headers: dict[str, str] | None = None, body: bytes | None = None) -> tuple[bool, int | None, str]:
    request = urllib_request.Request(url=url, method=method)
    if headers:
        for key, value in headers.items():
            request.add_header(key, value)

    try:
        with urllib_request.urlopen(request, data=body, timeout=max(2, int(timeout_sec))) as response:
            status = int(getattr(response, "status", 200))
            text = response.read(2048).decode("utf-8", errors="ignore")
            return True, status, text
    except urllib_error.HTTPError as exc:
        try:
            text = exc.read().decode("utf-8", errors="ignore")
        except Exception:
            text = str(exc)
        return True, int(exc.code), text
    except Exception as exc:  # pragma: no cover - network/runtime variance
        return False, None, str(exc)


def _resolve_callback_download_url(download_url: str) -> str:
    value = (download_url or "").strip()
    if not value:
        return value

    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        return value

    # Preferred override: explicit backend-internal URL for callback downloads.
    internal_base = _public_backend_internal_url()
    if internal_base:
        internal_parsed = urlparse(internal_base)
        public_parsed = urlparse(_public_backend_url())
        if parsed.netloc == public_parsed.netloc:
            rewritten = parsed._replace(
                scheme=internal_parsed.scheme or parsed.scheme,
                netloc=internal_parsed.netloc or parsed.netloc,
            )
            return urlunparse(rewritten)

    # Host-mode fallback: backend on host cannot always fetch host.docker.internal.
    host = (parsed.hostname or "").strip().lower()
    if host in {"host.docker.internal", "gateway.docker.internal"}:
        port = f":{parsed.port}" if parsed.port else ""
        rewritten = parsed._replace(netloc=f"127.0.0.1{port}")
        return urlunparse(rewritten)

    return value


def _probe_onlyoffice_health() -> OfficeHealthResponse:
    now_iso = datetime.now().isoformat(timespec="seconds")
    ds_public_url = (settings.onlyoffice_document_server_url or "").strip().rstrip("/")
    ds_internal_url = (settings.onlyoffice_document_server_internal_url or "").strip().rstrip("/")
    ds_probe_url = ds_internal_url or ds_public_url
    backend_url = _public_backend_url()
    backend_internal_url = _public_backend_internal_url()
    jwt_enabled = bool(settings.onlyoffice_jwt_enabled)
    jwt_secret_set = bool((settings.onlyoffice_jwt_secret or "").strip())
    callback_signing_ready = bool(_onlyoffice_callback_secret())
    configured = bool(ds_public_url)
    notes: list[str] = []

    ds_reachable = False
    ds_status: int | None = None
    command_ok = False
    command_status: int | None = None
    ds_version: str | None = None
    jwt_match: bool | None = None
    callback_reachable = False
    callback_status: int | None = None

    if not configured:
        notes.append("ONLYOFFICE_DOCUMENT_SERVER_URL is empty.")
    if jwt_enabled and not jwt_secret_set:
        notes.append("ONLYOFFICE_JWT_ENABLED=true but ONLYOFFICE_JWT_SECRET is empty.")

    if configured:
        api_reachable, api_status, _ = _http_probe(f"{ds_probe_url}/web-apps/apps/api/documents/api.js", timeout_sec=6)
        health_reachable, health_status, _ = _http_probe(f"{ds_probe_url}/healthcheck", timeout_sec=6)
        root_reachable, root_status, _ = _http_probe(f"{ds_probe_url}/", timeout_sec=6)
        status_candidates = (
            (api_reachable, api_status),
            (health_reachable, health_status),
            (root_reachable, root_status),
        )
        ds_status = api_status if api_reachable else (health_status if health_reachable else root_status)
        api_ok = api_reachable and api_status is not None and api_status < 400
        root_ok = root_reachable and root_status is not None and root_status < 400
        ds_reachable = api_ok
        if not ds_reachable:
            if root_ok:
                notes.append("Document Server root is reachable, but ONLYOFFICE DocsAPI script is unavailable. Check the document server URL or port mapping.")
            else:
                notes.append("Document Server is unreachable from backend.")
        elif api_status is not None and api_status >= 400:
            notes.append(f"ONLYOFFICE DocsAPI script returned HTTP {api_status}.")
        elif health_status is not None and health_status >= 400:
            notes.append(f"Document Server is reachable, but optional /healthcheck returned HTTP {health_status}.")

        command_payload = {"c": "version"}
        command_body = json.dumps(command_payload, ensure_ascii=False).encode("utf-8")
        command_headers = {"Content-Type": "application/json"}
        if jwt_enabled and jwt_secret_set:
            command_token = encode_hs256_jwt(command_payload, settings.onlyoffice_jwt_secret)
            command_headers["Authorization"] = f"Bearer {command_token}"

        cmd_reachable = False
        cmd_status: int | None = None
        cmd_text = ""
        command_candidates = (
            f"{ds_probe_url}/command",
            f"{ds_probe_url}/coauthoring/CommandService.ashx",
        )
        for endpoint in command_candidates:
            probe_reachable, probe_status, probe_text = _http_probe(
                endpoint,
                method="POST",
                timeout_sec=8,
                headers=command_headers,
                body=command_body,
            )
            if not probe_reachable:
                continue
            cmd_reachable = True
            cmd_status = probe_status
            cmd_text = probe_text
            # Use the first endpoint that doesn't return plain 404.
            if probe_status != 404:
                break

        command_status = cmd_status
        if cmd_reachable:
            try:
                parsed = json.loads(cmd_text) if cmd_text.strip() else {}
            except Exception:
                parsed = {}
            err_code = parsed.get("error")
            if err_code in (0, "0"):
                command_ok = True
                version_val = parsed.get("version")
                ds_version = str(version_val) if version_val is not None else None
                jwt_match = True if jwt_enabled else None
            elif err_code in (6, "6"):
                # Official callback/command error style: permission token mismatch.
                command_ok = False
                jwt_match = False if jwt_enabled else None
                notes.append("CommandService token check failed (possible JWT secret mismatch).")
            else:
                command_ok = False
                lower_text = cmd_text.lower()
                explicit_jwt_error = any(keyword in lower_text for keyword in ("jwt", "token", "signature")) and any(
                    keyword in lower_text for keyword in ("invalid", "mismatch", "expired", "permission", "unauthorized")
                )
                if jwt_enabled and explicit_jwt_error:
                    jwt_match = False
                    notes.append("CommandService returned an explicit JWT/token error.")
                elif cmd_status == 404:
                    notes.append("CommandService endpoint returned HTTP 404; JWT status could not be verified.")
                elif parsed:
                    notes.append("CommandService returned a non-zero or unsupported response; JWT status could not be verified.")
                else:
                    notes.append("CommandService did not return JSON; JWT status could not be verified.")
        else:
            notes.append("CommandService endpoint is unreachable from backend.")

    sample_token = build_path_token("data/user_docs/healthcheck.docx", _onlyoffice_callback_secret(), settings.onlyoffice_callback_ttl_sec)
    callback_base = backend_internal_url
    if not callback_base:
        parsed_backend = urlparse(backend_url)
        if (parsed_backend.hostname or "").strip().lower() in {"host.docker.internal", "gateway.docker.internal"}:
            host = "127.0.0.1"
            port = f":{parsed_backend.port}" if parsed_backend.port else ""
            callback_base = f"{parsed_backend.scheme}://{host}{port}"
        else:
            callback_base = backend_url
    callback_url = build_callback_url(callback_base, sample_token)
    cb_reachable, cb_status, _ = _http_probe(callback_url, method="GET", timeout_sec=4)
    if cb_reachable and cb_status is not None:
        callback_reachable = cb_status in {200, 400, 401, 403, 404, 405, 422}
        callback_status = cb_status
    if not callback_reachable:
        notes.append("Public callback URL is not reachable from backend self-check.")

    return OfficeHealthResponse(
        checked_at=now_iso,
        configured=configured,
        document_server_url=ds_public_url or None,
        document_server_internal_url=ds_internal_url or None,
        public_backend_url=backend_url,
        public_backend_internal_url=backend_internal_url or None,
        index_update_mode=_effective_onlyoffice_index_update_mode(),
        auto_rebuild_index_on_save=settings.onlyoffice_auto_rebuild_index_on_save,
        jwt_enabled=jwt_enabled,
        jwt_secret_configured=jwt_secret_set,
        callback_token_signing_ready=callback_signing_ready,
        document_server_reachable=ds_reachable,
        document_server_http_status=ds_status,
        command_service_ok=command_ok,
        command_service_http_status=command_status,
        document_server_version=ds_version,
        jwt_match=jwt_match,
        callback_reachable=callback_reachable,
        callback_http_status=callback_status,
        notes=notes,
    )


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


def _document_info_from_payload(item: dict[str, Any]) -> DocumentInfo:
    return DocumentInfo(
        id=int(item["id"]) if item.get("id") is not None else None,
        path=str(item.get("path") or ""),
        display_path=str(item.get("display_path") or "") or None,
        size_bytes=int(item.get("size_bytes", 0) or 0),
        modified_at=str(item.get("modified_at") or ""),
        extension=str(item.get("extension") or ""),
        is_directory=bool(item.get("is_directory", False)),
        parent_id=int(item["parent_id"]) if item.get("parent_id") is not None else None,
        folder_id=int(item["folder_id"]) if item.get("folder_id") is not None else None,
        name=str(item.get("name") or "") or None,
        source_type=str(item.get("source_type") or "db"),
        parse_status=str(item.get("parse_status") or "") or None,
        index_status=str(item.get("index_status") or "") or None,
        parse_error=str(item.get("parse_error") or "") or None,
        last_indexed_at=str(item.get("last_indexed_at") or "") or None,
        index_job_id=int(item["index_job_id"]) if item.get("index_job_id") is not None else None,
        index_job_file_id=int(item["index_job_file_id"]) if item.get("index_job_file_id") is not None else None,
        index_job_type=str(item.get("index_job_type") or "") or None,
        index_stage=str(item.get("index_stage") or "") or None,
        index_progress=int(item["index_progress"]) if item.get("index_progress") is not None else None,
        index_total_chunks=int(item["index_total_chunks"]) if item.get("index_total_chunks") is not None else None,
        index_indexed_chunks=int(item["index_indexed_chunks"]) if item.get("index_indexed_chunks") is not None else None,
        index_error_message=str(item.get("index_error_message") or "") or None,
        index_updated_at=str(item.get("index_updated_at") or "") or None,
        index_started_at=str(item.get("index_started_at") or "") or None,
        index_finished_at=str(item.get("index_finished_at") or "") or None,
    )


def _document_mutation_response(result: dict[str, Any], stats) -> DocumentMutationResponse:
    return DocumentMutationResponse(
        previous_path=str(result.get("previous_path") or ""),
        path=str(result.get("path") or ""),
        id=int(result["file_id"]) if result.get("file_id") is not None else (
            int(result["folder_id"]) if result.get("folder_id") is not None else None
        ),
        file_id=int(result["file_id"]) if result.get("file_id") is not None else None,
        folder_id=int(result["folder_id"]) if result.get("folder_id") is not None else None,
        documents_loaded=int(getattr(stats, "documents_loaded", 0) or 0),
        chunks_indexed=int(getattr(stats, "chunks_indexed", 0) or 0),
        source_files=[
            *[str(item) for item in result.get("source_files", []) if item],
            *[str(item) for item in getattr(stats, "source_files", []) if item],
        ],
    )


async def _resolve_document_path_by_request(
    library: DocumentLibraryService,
    *,
    path: str = "",
    file_id: int | None = None,
) -> str:
    if file_id is not None:
        try:
            payload = await run_in_threadpool(library.get_document_by_id, int(file_id))
            resolved_path = str(payload.get("path") or "")
            if resolved_path:
                return resolved_path
        except Exception:
            pass

    normalized_path = str(path or "").strip()
    if not normalized_path:
        raise HTTPException(status_code=400, detail="path or file_id is required")
    return normalized_path


@router.get("/documents", response_model=list[DocumentInfo])
async def list_documents(
    library: DocumentLibraryService = Depends(get_document_library_service),
) -> list[DocumentInfo]:
    try:
        raw_items = await run_in_threadpool(library.list_documents)
        infos_by_path: dict[str, DocumentInfo] = {}
        for item in raw_items:
            info = _document_info_from_payload(item)
            key = f"{info.source_type}:{info.path}"
            infos_by_path[key] = info

        return sorted(
            infos_by_path.values(),
            key=lambda item: (
                (item.display_path or item.path).lower(),
                not item.is_directory,
            ),
        )
    except DatabaseUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/index/files", response_model=IndexFileListResponse)
async def list_index_files(
    page: int = 1,
    page_size: int = 50,
    status: str = "all",
    keyword: str = "",
    library: DocumentLibraryService = Depends(get_document_library_service),
) -> IndexFileListResponse:
    try:
        payload = await run_in_threadpool(
            library.list_index_file_statuses,
            page=page,
            page_size=page_size,
            status=status,
            keyword=keyword,
        )
        return IndexFileListResponse(
            items=[_document_info_from_payload(item) for item in payload.get("items", [])],
            total=int(payload.get("total", 0) or 0),
            page=int(payload.get("page", page) or page),
            page_size=int(payload.get("page_size", page_size) or page_size),
            status_counts=IndexFileStatusCounts(**dict(payload.get("status_counts", {}) or {})),
        )
    except DatabaseUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/document-folders", response_model=CreateDocumentFolderResponse)
async def create_document_folder(
    payload: CreateDocumentFolderRequest,
    library: DocumentLibraryService = Depends(get_document_library_service),
) -> CreateDocumentFolderResponse:
    try:
        created = await run_in_threadpool(library.create_folder, payload.parent_path, payload.parent_id, payload.name)
        path = str(created.get("path") or "")
        return CreateDocumentFolderResponse(
            path=path,
            id=int(created["id"]) if created.get("id") is not None else None,
            parent_id=int(created["parent_id"]) if created.get("parent_id") is not None else None,
            created=True,
        )
    except DatabaseUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.put("/document-folders/rename", response_model=DocumentMutationResponse)
async def rename_document_folder(
    payload: DocumentMutationRequest,
    library: DocumentLibraryService = Depends(get_document_library_service),
    service: KnowledgeBaseService = Depends(get_knowledge_base_service),
) -> DocumentMutationResponse:
    if not payload.new_name:
        raise HTTPException(status_code=400, detail="new_name is required")
    try:
        result = await run_in_threadpool(library.rename_folder, payload.path, payload.new_name)
        stats = await _reindex_mutated_document_files(
            library,
            service,
            file_ids=[int(item) for item in result.get("file_ids", []) if item is not None],
            source_paths=[str(item) for item in result.get("source_files", []) if item],
        )
        return _document_mutation_response(result, stats)
    except DatabaseUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.put("/document-folders/move", response_model=DocumentMutationResponse)
async def move_document_folder(
    payload: DocumentMutationRequest,
    library: DocumentLibraryService = Depends(get_document_library_service),
    service: KnowledgeBaseService = Depends(get_knowledge_base_service),
) -> DocumentMutationResponse:
    try:
        result = await run_in_threadpool(library.move_folder, payload.path, payload.parent_path, payload.parent_id)
        stats = await _reindex_mutated_document_files(
            library,
            service,
            file_ids=[int(item) for item in result.get("file_ids", []) if item is not None],
            source_paths=[str(item) for item in result.get("source_files", []) if item],
        )
        return _document_mutation_response(result, stats)
    except DatabaseUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/document-folders", response_model=IngestResponse)
async def delete_document_folder(
    path: str,
    library: DocumentLibraryService = Depends(get_document_library_service),
    service: KnowledgeBaseService = Depends(get_knowledge_base_service),
) -> IngestResponse:
    try:
        result = await run_in_threadpool(library.delete_folder, path)
        deleted_sources = [str(item) for item in result.get("source_files", []) if item]
        deleted_file_ids = [int(item) for item in result.get("file_ids", []) if item is not None]
        stats = await run_in_threadpool(service.delete_chunks_by_file_ids, deleted_file_ids)
        return IngestResponse(
            documents_loaded=stats.documents_loaded,
            chunks_indexed=stats.chunks_indexed,
            source_files=deleted_sources + stats.source_files,
        )
    except DatabaseUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.put("/documents/rename", response_model=DocumentMutationResponse)
async def rename_document(
    payload: DocumentMutationRequest,
    library: DocumentLibraryService = Depends(get_document_library_service),
    service: KnowledgeBaseService = Depends(get_knowledge_base_service),
) -> DocumentMutationResponse:
    if not payload.new_name:
        raise HTTPException(status_code=400, detail="new_name is required")
    try:
        if payload.file_id is not None:
            result = await run_in_threadpool(library.rename_file_by_id, int(payload.file_id), payload.new_name)
        else:
            document_path = await _resolve_document_path_by_request(
                library,
                path=payload.path,
                file_id=payload.file_id,
            )
            result = await run_in_threadpool(library.rename_file, document_path, payload.new_name)
        stats = await _reindex_mutated_document_files(
            library,
            service,
            file_ids=[int(result["file_id"])] if result.get("file_id") is not None else [],
            source_paths=[str(item) for item in result.get("source_files", []) if item],
        )
        return _document_mutation_response(result, stats)
    except DatabaseUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.put("/documents/move", response_model=DocumentMutationResponse)
async def move_document(
    payload: DocumentMutationRequest,
    library: DocumentLibraryService = Depends(get_document_library_service),
    service: KnowledgeBaseService = Depends(get_knowledge_base_service),
) -> DocumentMutationResponse:
    try:
        if payload.file_id is not None:
            result = await run_in_threadpool(library.move_file_by_id, int(payload.file_id), payload.parent_path, payload.parent_id)
        else:
            document_path = await _resolve_document_path_by_request(
                library,
                path=payload.path,
                file_id=payload.file_id,
            )
            result = await run_in_threadpool(library.move_file, document_path, payload.parent_path, payload.parent_id)
        stats = await _reindex_mutated_document_files(
            library,
            service,
            file_ids=[int(result["file_id"])] if result.get("file_id") is not None else [],
            source_paths=[str(item) for item in result.get("source_files", []) if item],
        )
        return _document_mutation_response(result, stats)
    except DatabaseUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/documents", response_model=IngestResponse)
async def delete_document(
    path: str = "",
    file_id: int | None = None,
    library: DocumentLibraryService = Depends(get_document_library_service),
    service: KnowledgeBaseService = Depends(get_knowledge_base_service),
) -> IngestResponse:
    try:
        if file_id is not None:
            result = await run_in_threadpool(library.delete_document_by_id, int(file_id))
            deleted_path = str(result.get("path") or "")
        else:
            document_path = await _resolve_document_path_by_request(
                library,
                path=path,
                file_id=file_id,
            )
            result = await run_in_threadpool(library.delete_document, document_path)
            deleted_path = str(result.get("path") or document_path)
        deleted_file_id = result.get("file_id")
        deleted_file_ids = [int(deleted_file_id)] if deleted_file_id is not None else []
        stats = await run_in_threadpool(service.delete_chunks_by_file_ids, deleted_file_ids)
        return IngestResponse(
            documents_loaded=stats.documents_loaded,
            chunks_indexed=stats.chunks_indexed,
            source_files=[deleted_path, *stats.source_files],
        )
    except DatabaseUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/file")
async def open_file(path: str = "", file_id: int | None = None, library: DocumentLibraryService = Depends(get_document_library_service)) -> FileResponse:
    if file_id is not None:
        payload = await run_in_threadpool(library.get_document_by_id, int(file_id))
        path = str(payload.get("path") or "")
    file_path = _resolve_file_path(path)
    media_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
    return FileResponse(
        path=str(file_path),
        media_type=media_type,
    )


@router.get("/file/edit-text", response_model=FileEditTextResponse)
async def get_file_edit_text(path: str = "", file_id: int | None = None, library: DocumentLibraryService = Depends(get_document_library_service)) -> FileEditTextResponse:
    if file_id is not None:
        payload = await run_in_threadpool(library.get_document_by_id, int(file_id))
        path = str(payload.get("path") or "")
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
async def save_file_edit_text(
    payload: FileEditTextSaveRequest,
    library: DocumentLibraryService = Depends(get_document_library_service),
) -> FileEditTextSaveResponse:
    path_value = payload.path
    if payload.file_id is not None:
        document = await run_in_threadpool(library.get_document_by_id, int(payload.file_id))
        path_value = str(document.get("path") or "")
    file_path = _resolve_file_path(path_value)
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


@router.get("/office/editor-config", response_model=OfficeEditorConfigResponse)
async def office_editor_config(
    path: str = "",
    file_id: int | None = None,
    mode: str = "edit",
    lang: str = "zh-CN",
    library: DocumentLibraryService = Depends(get_document_library_service),
) -> OfficeEditorConfigResponse:
    if file_id is not None:
        payload = await run_in_threadpool(library.get_document_by_id, int(file_id))
        path = str(payload.get("path") or "")
    file_path = _resolve_file_path(path)
    extension = file_path.suffix.lower()
    if not is_onlyoffice_editable_extension(extension):
        allowed = ", ".join(OFFICE_EDITOR_EXTENSIONS)
        raise HTTPException(
            status_code=400,
            detail=f"ONLYOFFICE editing supports: {allowed}.",
        )

    document_server_url = (settings.onlyoffice_document_server_url or "").strip().rstrip("/")
    if not document_server_url:
        raise HTTPException(
            status_code=503,
            detail="ONLYOFFICE_DOCUMENT_SERVER_URL is not configured.",
        )

    if settings.onlyoffice_jwt_enabled and not settings.onlyoffice_jwt_secret:
        raise HTTPException(
            status_code=503,
            detail="ONLYOFFICE_JWT_ENABLED=true but ONLYOFFICE_JWT_SECRET is empty.",
        )

    relative_path = _relative_path_from_root(file_path)
    path_token = build_path_token(relative_path, _onlyoffice_callback_secret(), settings.onlyoffice_callback_ttl_sec)
    editor_mode = "view" if mode.strip().lower() == "view" else "edit"

    config = {
        "documentType": to_onlyoffice_document_type(extension),
        "type": "desktop",
        "document": {
            "title": file_path.name,
            "url": build_public_file_url(relative_path, _public_backend_url()),
            "fileType": extension[1:],
            "key": build_onlyoffice_document_key(file_path),
            "permissions": {
                "edit": editor_mode == "edit",
                "download": True,
                "print": True,
                "comment": True,
                "copy": True,
            },
        },
        "editorConfig": {
            "callbackUrl": build_callback_url(_public_backend_url(), path_token),
            "mode": editor_mode,
            "lang": lang or "zh-CN",
            "user": {
                "id": "local-user",
                "name": "Local User",
            },
            "customization": {
                "forcesave": True,
            },
        },
    }

    if settings.onlyoffice_jwt_enabled and settings.onlyoffice_jwt_secret:
        config["token"] = encode_hs256_jwt(config, settings.onlyoffice_jwt_secret)

    return OfficeEditorConfigResponse(
        path=relative_path,
        mode=editor_mode,
        document_server_url=document_server_url,
        config=config,
        callback_token_ttl_sec=settings.onlyoffice_callback_ttl_sec,
        auto_rebuild_index_on_save=settings.onlyoffice_auto_rebuild_index_on_save,
    )


@router.get("/office/health", response_model=OfficeHealthResponse)
async def office_health() -> OfficeHealthResponse:
    return await run_in_threadpool(_probe_onlyoffice_health)


@router.get("/office/callback-status", response_model=OfficeCallbackStatusResponse)
async def office_callback_status(path: str = "", file_id: int | None = None, library: DocumentLibraryService = Depends(get_document_library_service)) -> OfficeCallbackStatusResponse:
    if file_id is not None:
        payload = await run_in_threadpool(library.get_document_by_id, int(file_id))
        path = str(payload.get("path") or "")
    file_path = _resolve_file_path(path)
    relative_path = _relative_path_from_root(file_path)
    return _get_office_callback_status(relative_path)


@router.post("/office/callback")
async def office_editor_callback(
    request: Request,
    background_tasks: BackgroundTasks,
    service: KnowledgeBaseService = Depends(get_knowledge_base_service),
) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": 1, "message": "Invalid callback payload."}, status_code=200)

    if not isinstance(payload, dict):
        return JSONResponse({"error": 1, "message": "Invalid callback body."}, status_code=200)

    if settings.onlyoffice_verify_callback_token and settings.onlyoffice_jwt_secret:
        bearer = extract_bearer_token(request.headers.get("Authorization"))
        claims = decode_hs256_jwt(bearer, settings.onlyoffice_jwt_secret) if bearer else None
        if not claims:
            return JSONResponse({"error": 1, "message": "Invalid callback token."}, status_code=200)

    status_raw = payload.get("status")
    try:
        status = int(status_raw)
    except Exception:
        return JSONResponse({"error": 1, "message": "Missing callback status."}, status_code=200)

    path_token = request.query_params.get("path_token", "").strip()
    if not path_token:
        return JSONResponse({"error": 1, "message": "Missing path token."}, status_code=200)

    relative_path = decode_path_token(path_token, _onlyoffice_callback_secret())
    if not relative_path:
        return JSONResponse({"error": 1, "message": "Invalid or expired path token."}, status_code=200)

    try:
        file_path = _resolve_file_path(relative_path)
    except HTTPException as exc:
        return JSONResponse({"error": 1, "message": str(exc.detail)}, status_code=200)

    if status in OFFICE_CALLBACK_SAVE_STATUSES:
        download_url = str(payload.get("url") or "").strip()
        if not download_url:
            _set_office_index_status(relative_path, index_status="failed", index_message="No download URL in callback payload.")
            _set_office_callback_status(
                relative_path,
                success=False,
                message="Callback missing download url.",
                callback_status=status,
            )
            return JSONResponse({"error": 1, "message": "Callback missing download url."}, status_code=200)
        resolved_download_url = _resolve_callback_download_url(download_url)

        try:
            content = await run_in_threadpool(download_binary, resolved_download_url, settings.preview_convert_timeout_sec)
            _atomic_write_bytes(file_path, content)
            if settings.onlyoffice_auto_rebuild_index_on_save:
                mode = _effective_onlyoffice_index_update_mode()
                _set_office_index_status(relative_path, index_status="queued", index_message=f"Queued index update ({mode}).")
                background_tasks.add_task(
                    _run_onlyoffice_index_update,
                    relative_path,
                    str(file_path.resolve()),
                    mode,
                    service,
                )
            else:
                _set_office_index_status(relative_path, index_status="idle", index_message="Auto index update is disabled.")
            _set_office_callback_status(
                relative_path,
                success=True,
                message="Saved and queued for index refresh.",
                callback_status=status,
            )
            return JSONResponse({"error": 0}, status_code=200)
        except Exception as exc:
            message = f"Save failed: {exc}"
            _set_office_index_status(relative_path, index_status="failed", index_message=message)
            _set_office_callback_status(
                relative_path,
                success=False,
                message=message,
                callback_status=status,
            )
            logger.exception(
                "ONLYOFFICE callback save failed for %s: raw_url=%s resolved_url=%s err=%s",
                relative_path,
                download_url,
                resolved_download_url,
                exc,
            )
            return JSONResponse({"error": 1, "message": message}, status_code=200)

    return JSONResponse({"error": 0}, status_code=200)


@router.get("/file/preview-pdf")
async def open_file_preview_pdf(
    path: str = "",
    file_id: int | None = None,
    library: DocumentLibraryService = Depends(get_document_library_service),
) -> FileResponse:
    if file_id is not None:
        payload = await run_in_threadpool(library.get_document_by_id, int(file_id))
        path = str(payload.get("path") or "")
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
async def file_page_text(
    path: str = "",
    page: int | None = None,
    file_id: int | None = None,
    library: DocumentLibraryService = Depends(get_document_library_service),
) -> dict:
    if file_id is not None:
        payload = await run_in_threadpool(library.get_document_by_id, int(file_id))
        path = str(payload.get("path") or "")
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
async def ingest(
    background_tasks: BackgroundTasks,
    library: DocumentLibraryService = Depends(get_document_library_service),
    service: KnowledgeBaseService = Depends(get_knowledge_base_service),
) -> IngestResponse:
    file_ids = await run_in_threadpool(library.list_document_file_ids)
    index_job = await run_in_threadpool(library.create_index_job, job_type="full", file_ids=file_ids)
    job_id = index_job.get("job_id")
    file_ids = [int(item) for item in index_job.get("file_ids", []) if item is not None]
    source_paths = [str(item) for item in index_job.get("source_paths", []) if str(item).strip()]
    _enqueue_index_job(
        background_tasks,
        library,
        service,
        user_id=get_current_user_id(),
        kind="full",
        job_id=int(job_id) if job_id is not None else None,
        file_ids=file_ids,
        source_paths=source_paths,
    )
    return IngestResponse(
        documents_loaded=0,
        chunks_indexed=0,
        source_files=[],
        status="queued",
        message="Index rebuild has been queued and will run in the background.",
    )


@router.post("/upload", response_model=IngestResponse)
async def upload_files(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    folder_path: str = Form(default=""),
    parent_id: int | None = Form(default=None),
    library: DocumentLibraryService = Depends(get_document_library_service),
    service: KnowledgeBaseService = Depends(get_knowledge_base_service),
) -> IngestResponse:
    if not files:
        raise HTTPException(status_code=400, detail="Please upload at least one file.")

    try:
        saved_files = await library.save_uploaded_files(files, folder_path=folder_path, parent_id=parent_id)
    except DatabaseUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    saved_file_ids = [int(item["id"]) for item in saved_files if item.get("id") is not None]
    saved_paths = [str(item["path"]) for item in saved_files if item.get("path")]
    index_job = await run_in_threadpool(library.create_index_job, job_type="files", file_ids=saved_file_ids)
    job_id = index_job.get("job_id")
    saved_file_ids = [int(item) for item in index_job.get("file_ids", saved_file_ids) if item is not None]
    saved_paths = [str(item) for item in index_job.get("source_paths", saved_paths) if str(item).strip()]

    _enqueue_index_job(
        background_tasks,
        library,
        service,
        user_id=get_current_user_id(),
        kind="files",
        job_id=int(job_id) if job_id is not None else None,
        file_ids=saved_file_ids,
        source_paths=saved_paths,
    )

    return IngestResponse(
        documents_loaded=0,
        chunks_indexed=0,
        source_files=saved_paths,
        status="queued",
        message="Files uploaded. Indexing has been queued and will run in the background.",
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
    chat_memory: ChatMemoryService = Depends(get_chat_memory_service),
) -> ChatResponse:
    conversation_id, effective_history = await run_in_threadpool(
        _resolve_chat_memory_context,
        chat_memory,
        request,
    )
    try:
        result = await run_in_threadpool(
            service.answer,
            question=request.question,
            history=effective_history,
            top_k=request.top_k,
            model=request.model,
            thinking_mode=request.thinking_mode,
            web_search=request.web_search,
            native_web_search=request.native_web_search,
            external_web_search=request.external_web_search,
            run_mode=request.run_mode,
            scope_type=request.scope_type,
            scope_id=request.scope_id,
            workspace_key=request.workspace_key,
            message_parts=request.message_parts,
        )
    except ModelUnavailableError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    await run_in_threadpool(
        _save_chat_memory_turn,
        chat_memory,
        conversation_id=conversation_id,
        request=request,
        result=result,
    )
    return ChatResponse(
        answer=result["answer"],
        conversation_id=conversation_id,
        rewritten_question=result["rewritten_question"],
        sources=[_to_source_hit(hit) for hit in result["hits"]],
        citations=[_to_citation_ref(item) for item in result.get("citations", [])],
        model=str(result.get("model") or request.model or service.settings.deepseek_model),
        usage=_to_token_usage(result.get("usage")),
        cost_estimate=_to_cost_estimate(result.get("cost_estimate")),
        model_diagnostics=_to_model_diagnostics(result.get("model_diagnostics")),
    )


@router.post("/chat/stream")
async def chat_stream(
    request: ChatRequest,
    service: KnowledgeBaseService = Depends(get_knowledge_base_service),
    chat_memory: ChatMemoryService = Depends(get_chat_memory_service),
) -> StreamingResponse:
    conversation_id, effective_history = await run_in_threadpool(
        _resolve_chat_memory_context,
        chat_memory,
        request,
    )

    def event_stream() -> Iterator[str]:
        try:
            for event in service.stream_answer(
                question=request.question,
                history=effective_history,
                top_k=request.top_k,
                model=request.model,
                thinking_mode=request.thinking_mode,
                web_search=request.web_search,
                native_web_search=request.native_web_search,
                external_web_search=request.external_web_search,
                run_mode=request.run_mode,
                scope_type=request.scope_type,
                scope_id=request.scope_id,
                workspace_key=request.workspace_key,
                message_parts=request.message_parts,
            ):
                payload = _streaming_event_payload(
                    event,
                    conversation_id=conversation_id,
                    request=request,
                    service=service,
                )
                if event.get("type") == "done":
                    _save_chat_memory_turn(
                        chat_memory,
                        conversation_id=conversation_id,
                        request=request,
                        result={
                            "answer": payload["answer"],
                            "rewritten_question": payload["rewritten_question"],
                            "citations": event.get("citations", []),
                            "model": payload["model"],
                            "usage": event.get("usage"),
                            "model_diagnostics": event.get("model_diagnostics"),
                            "reasoning_parts": event.get("reasoning_parts", []),
                        },
                    )
                yield _sse_payload(payload)
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


@router.post("/agent/tool-confirmations/{confirmation_id}/confirm", response_model=AgentToolConfirmationResponse)
async def confirm_agent_tool(
    confirmation_id: str,
    payload: AgentToolConfirmationActionRequest,
    confirmation_service: AgentToolConfirmationService = Depends(get_agent_tool_confirmation_service),
    chat_memory: ChatMemoryService = Depends(get_chat_memory_service),
) -> AgentToolConfirmationResponse:
    try:
        item = await run_in_threadpool(
            confirmation_service.confirm,
            confirmation_id,
            user_id=_get_context_user_id_for_confirmation(),
        )
        response_payload = item.to_payload()
        await run_in_threadpool(
            _persist_tool_confirmation_state,
            chat_memory,
            conversation_id=payload.conversation_id,
            payload=response_payload,
        )
        return _to_agent_confirmation_response(response_payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/agent/tool-confirmations/{confirmation_id}/cancel", response_model=AgentToolConfirmationResponse)
async def cancel_agent_tool(
    confirmation_id: str,
    payload: AgentToolConfirmationActionRequest,
    confirmation_service: AgentToolConfirmationService = Depends(get_agent_tool_confirmation_service),
    chat_memory: ChatMemoryService = Depends(get_chat_memory_service),
) -> AgentToolConfirmationResponse:
    try:
        item = await run_in_threadpool(
            confirmation_service.cancel,
            confirmation_id,
            user_id=_get_context_user_id_for_confirmation(),
        )
        response_payload = item.to_payload()
        await run_in_threadpool(
            _persist_tool_confirmation_state,
            chat_memory,
            conversation_id=payload.conversation_id,
            payload=response_payload,
        )
        return _to_agent_confirmation_response(response_payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/chat/conversations", response_model=ChatConversationListResponse)
async def list_chat_conversations(
    page: int = 1,
    page_size: int = 20,
    chat_memory: ChatMemoryService = Depends(get_chat_memory_service),
) -> ChatConversationListResponse:
    try:
        items, has_more = await run_in_threadpool(
            chat_memory.list_conversations,
            page=max(1, page),
            page_size=max(1, min(50, page_size)),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return ChatConversationListResponse(
        items=[ChatConversationSummary(**item) for item in items],
        page=max(1, page),
        page_size=max(1, min(50, page_size)),
        has_more=has_more,
    )


@router.get("/chat/conversations/{conversation_id}/messages", response_model=ChatMessagePageResponse)
async def list_chat_messages(
    conversation_id: int,
    limit: int = 30,
    before_seq_no: int | None = None,
    chat_memory: ChatMemoryService = Depends(get_chat_memory_service),
) -> ChatMessagePageResponse:
    try:
        items, has_more = await run_in_threadpool(
            chat_memory.list_messages,
            conversation_id,
            limit=max(1, min(100, limit)),
            before_seq_no=before_seq_no,
        )
    except DatabaseUnavailableError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    seq_values = [int(item["seq_no"]) for item in items]
    return ChatMessagePageResponse(
        items=[ChatMessageRecord(**item) for item in items],
        conversation_id=conversation_id,
        limit=max(1, min(100, limit)),
        has_more=has_more,
        oldest_seq_no=min(seq_values) if seq_values else None,
        newest_seq_no=max(seq_values) if seq_values else None,
    )


@router.get("/chat/options", response_model=ChatOptionsResponse)
async def chat_options(
    service: KnowledgeBaseService = Depends(get_knowledge_base_service),
    library: DocumentLibraryService = Depends(get_document_library_service),
) -> ChatOptionsResponse:
    model_options = service.resolve_model_options()
    try:
        kb_options = [KnowledgeBaseScopeOption(**item) for item in library.list_kb_scope_options()]
    except Exception:
        kb_options = []
    try:
        workspace_options = [WorkspaceScopeOption(**item) for item in library.list_workspace_scope_options()]
    except Exception:
        workspace_options = []
    return ChatOptionsResponse(
        default_model=service.settings.deepseek_model,
        models=service.resolve_available_models(),
        model_options=model_options,
        knowledge_bases=kb_options,
        workspaces=workspace_options,
        web_search_available=service.is_web_search_available(),
        external_web_search_available=service.is_web_search_available(),
        thinking_modes=["quick", "deep"],
    )
