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

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
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
    OfficeEditorConfigResponse,
    OfficeCallbackStatusResponse,
    OfficeHealthResponse,
    SearchRequest,
    SearchResponse,
    SourceHit,
    TokenUsage,
)
from app.services.files import TEXT_FILE_EXTENSIONS, read_file_page_text
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
    payload: dict[str, Any] = {
        "path": relative_path,
        "has_event": True,
        "status": status,
        "success": success,
        "message": message.strip(),
        "callback_status": callback_status,
        "updated_at": now_iso,
    }
    with _office_callback_status_lock:
        _office_callback_status_by_path[relative_path] = payload


def _get_office_callback_status(relative_path: str) -> OfficeCallbackStatusResponse:
    with _office_callback_status_lock:
        payload = _office_callback_status_by_path.get(relative_path)
    if not payload:
        return OfficeCallbackStatusResponse(path=relative_path)
    return OfficeCallbackStatusResponse(**payload)


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
        reachable, status, _ = _http_probe(f"{ds_probe_url}/healthcheck", timeout_sec=6)
        ds_reachable = reachable
        ds_status = status
        if not reachable:
            notes.append("Document Server is unreachable from backend.")
        elif status is not None and status >= 400:
            notes.append(f"Document Server /healthcheck returned HTTP {status}.")

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
                if jwt_enabled:
                    jwt_match = False
                notes.append("CommandService returned non-zero error.")
        else:
            notes.append("CommandService endpoint is unreachable from backend.")

    sample_token = build_path_token("data/uploads/healthcheck.docx", _onlyoffice_callback_secret(), settings.onlyoffice_callback_ttl_sec)
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


@router.get("/office/editor-config", response_model=OfficeEditorConfigResponse)
async def office_editor_config(
    path: str,
    mode: str = "edit",
    lang: str = "zh-CN",
) -> OfficeEditorConfigResponse:
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
async def office_callback_status(path: str) -> OfficeCallbackStatusResponse:
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
                if mode == "full":
                    background_tasks.add_task(service.rebuild_index)
                else:
                    background_tasks.add_task(service.reindex_source_file, file_path)
            _set_office_callback_status(
                relative_path,
                success=True,
                message="Saved and queued for index refresh.",
                callback_status=status,
            )
            return JSONResponse({"error": 0}, status_code=200)
        except Exception as exc:
            message = f"Save failed: {exc}"
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
