"""Document library metadata service backed by MySQL."""

from __future__ import annotations

import hashlib
import mimetypes
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import UploadFile

from app.core.database import DatabaseUnavailableError, session_scope
from app.core.settings import settings
from app.services.preview_pdf import get_preview_pdf_cache_path

try:
    from sqlalchemy import text
except Exception:  # pragma: no cover - optional dependency path
    text = None  # type: ignore[assignment]


@dataclass(frozen=True)
class DocumentFolderRow:
    id: int
    user_id: int
    parent_id: int | None
    name: str
    path_cache: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class DocumentFileRow:
    id: int
    user_id: int
    folder_id: int | None
    display_name: str
    original_name: str
    stored_name: str
    storage_path: str
    extension: str
    mime_type: str | None
    size_bytes: int
    sha256: str | None
    index_status: str
    index_message: str | None
    created_at: datetime
    updated_at: datetime


class DocumentLibraryService:
    """Persist document folders/files and expose UI-friendly listings."""

    def __init__(self) -> None:
        self.settings = settings

    def _now(self) -> datetime:
        return datetime.now()

    def _ensure_sql(self) -> None:
        if text is None:
            raise DatabaseUnavailableError("SQLAlchemy is not installed.")

    def _get_or_create_default_user_id(self, session) -> int:
        row = session.execute(
            text("SELECT id FROM kop_user WHERE username = :username LIMIT 1"),
            {"username": self.settings.chat_default_username},
        ).first()
        if row:
            return int(row[0])

        result = session.execute(
            text(
                """
                INSERT INTO kop_user (username, status)
                VALUES (:username, 1)
                """
            ),
            {"username": self.settings.chat_default_username},
        )
        return int(result.lastrowid)

    def _get_folder_row(self, session, folder_id: int) -> DocumentFolderRow | None:
        row = session.execute(
            text(
                """
                SELECT id, user_id, parent_id, name, path_cache, created_at, updated_at
                FROM kop_doc_folder
                WHERE id = :folder_id AND status = 1
                LIMIT 1
                """
            ),
            {"folder_id": folder_id},
        ).first()
        if not row:
            return None
        return DocumentFolderRow(
            id=int(row[0]),
            user_id=int(row[1]),
            parent_id=int(row[2]) if row[2] is not None else None,
            name=str(row[3]),
            path_cache=str(row[4] or ""),
            created_at=row[5],
            updated_at=row[6],
        )

    def _get_folder_by_parent_and_name(self, session, user_id: int, parent_id: int | None, name: str) -> DocumentFolderRow | None:
        row = session.execute(
            text(
                """
                SELECT id, user_id, parent_id, name, path_cache, created_at, updated_at
                FROM kop_doc_folder
                WHERE user_id = :user_id
                  AND status = 1
                  AND ((parent_id IS NULL AND :parent_id IS NULL) OR parent_id = :parent_id)
                  AND name = :name
                LIMIT 1
                """
            ),
            {"user_id": user_id, "parent_id": parent_id, "name": name},
        ).first()
        if not row:
            return None
        return DocumentFolderRow(
            id=int(row[0]),
            user_id=int(row[1]),
            parent_id=int(row[2]) if row[2] is not None else None,
            name=str(row[3]),
            path_cache=str(row[4] or ""),
            created_at=row[5],
            updated_at=row[6],
        )

    def _get_file_row(self, session, file_id: int) -> DocumentFileRow | None:
        row = session.execute(
            text(
                """
                SELECT
                    id, user_id, folder_id, display_name, original_name, stored_name,
                    storage_path, extension, mime_type, size_bytes, sha256,
                    index_status, index_message, created_at, updated_at
                FROM kop_doc_file
                WHERE id = :file_id AND status = 1
                LIMIT 1
                """
            ),
            {"file_id": file_id},
        ).first()
        if not row:
            return None
        return DocumentFileRow(
            id=int(row[0]),
            user_id=int(row[1]),
            folder_id=int(row[2]) if row[2] is not None else None,
            display_name=str(row[3]),
            original_name=str(row[4]),
            stored_name=str(row[5]),
            storage_path=str(row[6]),
            extension=str(row[7] or ""),
            mime_type=str(row[8]) if row[8] is not None else None,
            size_bytes=int(row[9] or 0),
            sha256=str(row[10]) if row[10] is not None else None,
            index_status=str(row[11] or "pending"),
            index_message=str(row[12]) if row[12] is not None else None,
            created_at=row[13],
            updated_at=row[14],
        )

    def _folder_path_cache(self, session, folder_id: int | None) -> str:
        if folder_id is None:
            return ""
        folder = self._get_folder_row(session, folder_id)
        if folder is None:
            return ""
        return folder.path_cache

    def _build_folder_cache(self, parent_cache: str, name: str) -> str:
        base = parent_cache.strip("/")
        name = name.strip("/")
        if not base:
            return f"/{name}" if name else "/"
        return f"{base}/{name}"

    def _normalize_folder_name(self, name: str) -> str:
        candidate = Path(name.strip()).name
        if not candidate or candidate in {".", ".."}:
            raise ValueError("Folder name is required.")
        if candidate != name.strip() or any(char in candidate for char in ("/", "\\")):
            raise ValueError("Folder name cannot contain path separators.")
        return candidate

    def _ensure_user_docs_root(self) -> None:
        self.settings.user_docs_dir.mkdir(parents=True, exist_ok=True)

    def _normalize_storage_path(self, path_value: str) -> str:
        return str(path_value or "").strip().replace("\\", "/").strip("/")

    def _folder_storage_dir(self, user_id: int, folder_id: int | None) -> Path:
        root = self.settings.user_docs_dir / str(user_id)
        if folder_id is None:
            return root
        return root / str(folder_id)

    def _make_file_storage_name(self, original_name: str, file_bytes: bytes) -> tuple[str, str]:
        path = Path(original_name)
        extension = path.suffix.lower()
        stem = path.stem or "upload"
        sha256 = hashlib.sha256(file_bytes).hexdigest()
        stored_name = f"{stem}_{sha256[:12]}{extension}"
        return stored_name, sha256

    def _resolve_folder_by_path(self, session, user_id: int, parent_path: str | None) -> DocumentFolderRow | None:
        raw = (parent_path or "").strip().replace("\\", "/").strip("/")
        if not raw:
            return None

        parts = [part for part in raw.split("/") if part]
        current_parent: int | None = None
        current_row: DocumentFolderRow | None = None
        for part in parts:
            current_row = self._get_folder_by_parent_and_name(session, user_id, current_parent, part)
            if current_row is None:
                return None
            current_parent = current_row.id
        return current_row

    def _folder_to_payload(self, folder: DocumentFolderRow) -> dict[str, Any]:
        return {
            "id": folder.id,
            "path": folder.path_cache.lstrip("/"),
            "display_path": folder.path_cache.lstrip("/"),
            "size_bytes": 0,
            "modified_at": folder.updated_at.isoformat(timespec="seconds"),
            "extension": "",
            "is_directory": True,
            "parent_id": folder.parent_id,
            "folder_id": folder.id,
            "name": folder.name,
            "source_type": "db",
        }

    def _file_to_payload(self, file_row: DocumentFileRow, folder_cache: str = "") -> dict[str, Any]:
        display_path = f"{folder_cache.lstrip('/')}/{file_row.display_name}" if folder_cache else file_row.display_name
        return {
            "id": file_row.id,
            "path": file_row.storage_path,
            "display_path": display_path,
            "size_bytes": file_row.size_bytes,
            "modified_at": file_row.updated_at.isoformat(timespec="seconds"),
            "extension": file_row.extension,
            "is_directory": False,
            "parent_id": file_row.folder_id,
            "folder_id": file_row.folder_id,
            "name": file_row.display_name,
            "source_type": "db",
        }

    def list_documents(self) -> list[dict[str, Any]]:
        self._ensure_sql()
        with session_scope() as session:
            user_id = self._get_or_create_default_user_id(session)
            payload: list[dict[str, Any]] = []

            folder_rows = session.execute(
                text(
                    """
                    SELECT id, user_id, parent_id, name, path_cache, created_at, updated_at
                    FROM kop_doc_folder
                    WHERE user_id = :user_id AND status = 1
                    ORDER BY path_cache ASC, id ASC
                    """
                ),
                {"user_id": user_id},
            ).all()
            for row in folder_rows:
                payload.append(
                    self._folder_to_payload(
                        DocumentFolderRow(
                            id=int(row[0]),
                            user_id=int(row[1]),
                            parent_id=int(row[2]) if row[2] is not None else None,
                            name=str(row[3]),
                            path_cache=str(row[4] or ""),
                            created_at=row[5],
                            updated_at=row[6],
                        )
                    )
                )

            file_rows = session.execute(
                text(
                    """
                    SELECT
                        id, user_id, folder_id, display_name, original_name, stored_name,
                        storage_path, extension, mime_type, size_bytes, sha256,
                        index_status, index_message, created_at, updated_at
                    FROM kop_doc_file
                    WHERE user_id = :user_id AND status = 1
                    ORDER BY updated_at DESC, id DESC
                    """
                ),
                {"user_id": user_id},
            ).all()
            for row in file_rows:
                folder_cache = self._folder_path_cache(session, int(row[2]) if row[2] is not None else None)
                payload.append(
                    self._file_to_payload(
                        DocumentFileRow(
                            id=int(row[0]),
                            user_id=int(row[1]),
                            folder_id=int(row[2]) if row[2] is not None else None,
                            display_name=str(row[3]),
                            original_name=str(row[4]),
                            stored_name=str(row[5]),
                            storage_path=str(row[6]),
                            extension=str(row[7] or ""),
                            mime_type=str(row[8]) if row[8] is not None else None,
                            size_bytes=int(row[9] or 0),
                            sha256=str(row[10]) if row[10] is not None else None,
                            index_status=str(row[11] or "pending"),
                            index_message=str(row[12]) if row[12] is not None else None,
                            created_at=row[13],
                            updated_at=row[14],
                        ),
                        folder_cache=folder_cache,
                    )
                )

            return sorted(
                payload,
                key=lambda item: (str(item.get("display_path") or item.get("path") or "").lower(), not bool(item.get("is_directory"))),
            )

    def create_folder(self, parent_path: str | None, parent_id: int | None, name: str) -> dict[str, Any]:
        self._ensure_sql()
        safe_name = self._normalize_folder_name(name)
        with session_scope() as session:
            user_id = self._get_or_create_default_user_id(session)
            parent_row = None
            if parent_id is not None:
                parent_row = self._get_folder_row(session, int(parent_id))
                if parent_row is None:
                    raise ValueError(f"Parent folder not found: {parent_id}")
            elif parent_path:
                parent_row = self._resolve_folder_by_path(session, user_id, parent_path)
                if parent_row is None:
                    raise ValueError(f"Parent folder not found: {parent_path}")

            normalized_parent_id = parent_row.id if parent_row else None
            exists = self._get_folder_by_parent_and_name(session, user_id, normalized_parent_id, safe_name)
            if exists:
                return self._folder_to_payload(exists)

            parent_cache = parent_row.path_cache if parent_row else ""
            path_cache = self._build_folder_cache(parent_cache, safe_name)
            result = session.execute(
                text(
                    """
                    INSERT INTO kop_doc_folder
                        (user_id, parent_id, name, path_cache, sort_order, status, created_at, updated_at)
                    VALUES
                        (:user_id, :parent_id, :name, :path_cache, 0, 1, :created_at, :updated_at)
                    """
                ),
                {
                    "user_id": user_id,
                    "parent_id": normalized_parent_id,
                    "name": safe_name,
                    "path_cache": path_cache,
                    "created_at": self._now(),
                    "updated_at": self._now(),
                },
            )
            folder_id = int(result.lastrowid)
            created = self._get_folder_row(session, folder_id)
            if created is None:
                raise RuntimeError("Folder created but could not be reloaded.")
            return self._folder_to_payload(created)

    def _store_file(self, session, user_id: int, folder_id: int | None, upload: UploadFile, content: bytes) -> dict[str, Any]:
        original_name = Path(upload.filename or "upload").name
        stored_name, sha256 = self._make_file_storage_name(original_name, content)
        extension = Path(original_name).suffix.lower()
        storage_dir = self._folder_storage_dir(user_id, folder_id)
        storage_dir.mkdir(parents=True, exist_ok=True)
        storage_path = storage_dir / stored_name
        storage_path.write_bytes(content)
        mime_type = upload.content_type or mimetypes.guess_type(original_name)[0]

        result = session.execute(
            text(
                """
                INSERT INTO kop_doc_file
                    (user_id, folder_id, display_name, original_name, stored_name, storage_path,
                     extension, mime_type, size_bytes, sha256, index_status, index_message,
                     status, created_at, updated_at)
                VALUES
                    (:user_id, :folder_id, :display_name, :original_name, :stored_name, :storage_path,
                     :extension, :mime_type, :size_bytes, :sha256, 'pending', NULL,
                     1, :created_at, :updated_at)
                """
            ),
            {
                "user_id": user_id,
                "folder_id": folder_id,
                "display_name": original_name,
                "original_name": original_name,
                "stored_name": stored_name,
                "storage_path": str(storage_path.relative_to(self.settings.root_dir)).replace("\\", "/"),
                "extension": extension,
                "mime_type": mime_type,
                "size_bytes": len(content),
                "sha256": sha256,
                "created_at": self._now(),
                "updated_at": self._now(),
            },
        )
        file_id = int(result.lastrowid)
        row = self._get_file_row(session, file_id)
        if row is None:
            raise RuntimeError("File created but could not be reloaded.")
        return self._file_to_payload(row)

    async def save_uploaded_files(self, uploads: list[UploadFile], folder_path: str | None = None, parent_id: int | None = None) -> list[str]:
        self._ensure_sql()
        self._ensure_user_docs_root()
        prepared_uploads: list[tuple[UploadFile, bytes]] = []
        for upload in uploads:
            filename = Path(upload.filename or "upload").name
            suffix = Path(filename).suffix.lower()
            if suffix not in settings.supported_extensions:
                raise ValueError(f"Unsupported file type: {suffix or '[no extension]'}")

            content = await upload.read()
            max_bytes = self.settings.max_upload_mb * 1024 * 1024
            if len(content) > max_bytes:
                raise ValueError(f"File too large. Limit: {self.settings.max_upload_mb} MB")
            prepared_uploads.append((upload, content))

        saved_paths: list[str] = []
        with session_scope() as session:
            user_id = self._get_or_create_default_user_id(session)
            folder_row = None
            if parent_id is not None:
                folder_row = self._get_folder_row(session, int(parent_id))
                if folder_row is None:
                    raise ValueError(f"Folder not found: {parent_id}")
            elif folder_path:
                folder_row = self._resolve_folder_by_path(session, user_id, folder_path)
                if folder_row is None:
                    raise ValueError(f"Folder not found: {folder_path}")

            folder_id = folder_row.id if folder_row else None
            for upload, content in prepared_uploads:
                payload = self._store_file(session, user_id, folder_id, upload, content)
                saved_paths.append(str(payload["path"]))
        return saved_paths

    def _get_file_by_storage_path(self, session, user_id: int, storage_path: str) -> DocumentFileRow | None:
        normalized = self._normalize_storage_path(storage_path)
        row = session.execute(
            text(
                """
                SELECT
                    id, user_id, folder_id, display_name, original_name, stored_name,
                    storage_path, extension, mime_type, size_bytes, sha256,
                    index_status, index_message, created_at, updated_at
                FROM kop_doc_file
                WHERE user_id = :user_id
                  AND status = 1
                  AND storage_path = :storage_path
                LIMIT 1
                """
            ),
            {"user_id": user_id, "storage_path": normalized},
        ).first()
        if not row:
            return None
        return DocumentFileRow(
            id=int(row[0]),
            user_id=int(row[1]),
            folder_id=int(row[2]) if row[2] is not None else None,
            display_name=str(row[3]),
            original_name=str(row[4]),
            stored_name=str(row[5]),
            storage_path=str(row[6]),
            extension=str(row[7] or ""),
            mime_type=str(row[8]) if row[8] is not None else None,
            size_bytes=int(row[9] or 0),
            sha256=str(row[10]) if row[10] is not None else None,
            index_status=str(row[11] or "pending"),
            index_message=str(row[12]) if row[12] is not None else None,
            created_at=row[13],
            updated_at=row[14],
        )

    def _list_user_folder_rows(self, session, user_id: int) -> list[DocumentFolderRow]:
        rows = session.execute(
            text(
                """
                SELECT id, user_id, parent_id, name, path_cache, created_at, updated_at
                FROM kop_doc_folder
                WHERE user_id = :user_id AND status = 1
                ORDER BY path_cache ASC, id ASC
                """
            ),
            {"user_id": user_id},
        ).all()
        return [
            DocumentFolderRow(
                id=int(row[0]),
                user_id=int(row[1]),
                parent_id=int(row[2]) if row[2] is not None else None,
                name=str(row[3]),
                path_cache=str(row[4] or ""),
                created_at=row[5],
                updated_at=row[6],
            )
            for row in rows
        ]

    def _list_user_file_rows(self, session, user_id: int) -> list[DocumentFileRow]:
        rows = session.execute(
            text(
                """
                SELECT
                    id, user_id, folder_id, display_name, original_name, stored_name,
                    storage_path, extension, mime_type, size_bytes, sha256,
                    index_status, index_message, created_at, updated_at
                FROM kop_doc_file
                WHERE user_id = :user_id AND status = 1
                ORDER BY updated_at DESC, id DESC
                """
            ),
            {"user_id": user_id},
        ).all()
        return [
            DocumentFileRow(
                id=int(row[0]),
                user_id=int(row[1]),
                folder_id=int(row[2]) if row[2] is not None else None,
                display_name=str(row[3]),
                original_name=str(row[4]),
                stored_name=str(row[5]),
                storage_path=str(row[6]),
                extension=str(row[7] or ""),
                mime_type=str(row[8]) if row[8] is not None else None,
                size_bytes=int(row[9] or 0),
                sha256=str(row[10]) if row[10] is not None else None,
                index_status=str(row[11] or "pending"),
                index_message=str(row[12]) if row[12] is not None else None,
                created_at=row[13],
                updated_at=row[14],
            )
            for row in rows
        ]

    def _collect_descendant_folder_ids(self, folders: list[DocumentFolderRow], folder_id: int) -> list[int]:
        children_by_parent: dict[int | None, list[int]] = {}
        for folder in folders:
            children_by_parent.setdefault(folder.parent_id, []).append(folder.id)

        ordered_ids: list[int] = []

        def append_children(current_id: int) -> None:
            ordered_ids.append(current_id)
            for child_id in children_by_parent.get(current_id, []):
                append_children(child_id)

        append_children(folder_id)
        return ordered_ids

    def delete_document(self, path_value: str) -> dict[str, Any]:
        self._ensure_sql()
        normalized_path = self._normalize_storage_path(path_value)
        if not normalized_path:
            raise ValueError("File path is required.")

        self._ensure_user_docs_root()
        preview_cache_path: Path | None = None
        deleted_path: str | None = None

        with session_scope() as session:
            user_id = self._get_or_create_default_user_id(session)
            row = self._get_file_by_storage_path(session, user_id, normalized_path)
            if row is None:
                raise FileNotFoundError(f"File not found: {path_value}")

            file_path = (self.settings.root_dir / row.storage_path).resolve()
            if row.extension.lower() in {".doc", ".docx", ".ppt", ".pptx"}:
                try:
                    preview_cache_path = get_preview_pdf_cache_path(file_path)
                except Exception:
                    preview_cache_path = None

            session.execute(
                text("DELETE FROM kop_doc_file WHERE id = :file_id"),
                {"file_id": row.id},
            )

            if file_path.exists():
                file_path.unlink()
            if preview_cache_path and preview_cache_path.exists():
                preview_cache_path.unlink(missing_ok=True)
            deleted_path = row.storage_path

        return {"path": deleted_path or normalized_path}

    def delete_folder(self, path_value: str) -> dict[str, Any]:
        self._ensure_sql()
        normalized_path = self._normalize_storage_path(path_value)
        if not normalized_path:
            raise ValueError("Folder path is required.")

        self._ensure_user_docs_root()
        deleted_file_paths: list[str] = []
        deleted_folder_path = normalized_path

        with session_scope() as session:
            user_id = self._get_or_create_default_user_id(session)
            folder = self._resolve_folder_by_path(session, user_id, normalized_path)
            if folder is None:
                raise FileNotFoundError(f"Folder not found: {path_value}")

            folder_rows = self._list_user_folder_rows(session, user_id)
            descendant_folder_ids = self._collect_descendant_folder_ids(folder_rows, folder.id)
            descendant_id_set = set(descendant_folder_ids)
            file_rows = [
                file_row
                for file_row in self._list_user_file_rows(session, user_id)
                if file_row.folder_id in descendant_id_set
            ]

            preview_cache_paths: list[Path] = []
            for file_row in file_rows:
                file_path = (self.settings.root_dir / file_row.storage_path).resolve()
                if file_row.extension.lower() in {".doc", ".docx", ".ppt", ".pptx"}:
                    try:
                        preview_cache_paths.append(get_preview_pdf_cache_path(file_path))
                    except Exception:
                        pass

                session.execute(
                    text("DELETE FROM kop_doc_file WHERE id = :file_id"),
                    {"file_id": file_row.id},
                )

                if file_path.exists():
                    file_path.unlink()
                deleted_file_paths.append(file_row.storage_path)

            for preview_cache_path in preview_cache_paths:
                if preview_cache_path.exists():
                    preview_cache_path.unlink(missing_ok=True)

            for folder_id in reversed(descendant_folder_ids):
                session.execute(
                    text("DELETE FROM kop_doc_folder WHERE id = :folder_id"),
                    {"folder_id": folder_id},
                )
                shutil.rmtree(self._folder_storage_dir(user_id, folder_id), ignore_errors=True)

            deleted_folder_path = folder.path_cache.lstrip("/")

        return {
            "path": deleted_folder_path,
            "source_files": [deleted_folder_path, *deleted_file_paths],
        }
