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
from app.core.request_context import get_current_user_id
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
    parent_id: int
    folder_name: str
    sort_order: int
    is_deleted: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class DocumentFileRow:
    id: int
    user_id: int
    folder_id: int
    kb_id: int
    original_name: str
    stored_name: str
    file_path: str
    file_ext: str
    mime_type: str | None
    file_size: int
    file_hash: str | None
    source_type: str
    parse_status: str
    index_status: str
    parse_error: str | None
    last_indexed_at: datetime | None
    is_deleted: int
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
        current_user_id = get_current_user_id()
        if current_user_id is not None:
            row = session.execute(
                text(
                    """
                    SELECT id
                    FROM kop_user
                    WHERE id = :user_id
                      AND status = 1
                    LIMIT 1
                    """
                ),
                {"user_id": int(current_user_id)},
            ).first()
            if row:
                return int(row[0])

        row = session.execute(
            text(
                """
                SELECT id
                FROM kop_user
                WHERE username = :username
                LIMIT 1
                """
            ),
            {"username": self.settings.chat_default_username},
        ).first()
        if row:
            user_id = int(row[0])
            session.execute(
                text(
                    """
                    UPDATE kop_user
                    SET user_type = 'local',
                        is_default = 1,
                        status = 1,
                        updated_at = :updated_at
                    WHERE id = :user_id
                    """
                ),
                {"user_id": user_id, "updated_at": self._now()},
            )
            return user_id

        result = session.execute(
            text(
                """
                INSERT INTO kop_user
                    (username, password_hash, nickname, avatar_url, user_type, is_default, status, last_login_at, created_at, updated_at)
                VALUES
                    (:username, NULL, 'Local User', NULL, 'local', 1, 1, NULL, :created_at, :updated_at)
                """
            ),
            {
                "username": self.settings.chat_default_username,
                "created_at": self._now(),
                "updated_at": self._now(),
            },
        )
        return int(result.lastrowid)

    def get_default_user_id(self) -> int:
        self._ensure_sql()
        with session_scope() as session:
            return self._get_or_create_default_user_id(session)

    def resolve_current_user_id(self) -> int:
        self._ensure_sql()
        with session_scope() as session:
            return self._get_or_create_default_user_id(session)

    def _normalize_path(self, value: str | None) -> str:
        return str(value or "").strip().replace("\\", "/").strip("/")

    def _normalize_folder_name(self, name: str) -> str:
        candidate = Path(name.strip()).name
        if not candidate or candidate in {".", ".."}:
            raise ValueError("Folder name is required.")
        if candidate != name.strip() or any(char in candidate for char in ("/", "\\")):
            raise ValueError("Folder name cannot contain path separators.")
        return candidate

    def _normalize_file_name(self, name: str, required_extension: str | None = None) -> str:
        candidate = Path(name.strip()).name
        if not candidate or candidate in {".", ".."}:
            raise ValueError("File name is required.")
        if candidate != name.strip() or any(char in candidate for char in ("/", "\\")):
            raise ValueError("File name cannot contain path separators.")

        required_ext = str(required_extension or "").strip().lower()
        if required_ext:
            actual_ext = Path(candidate).suffix.lower()
            if actual_ext and actual_ext != required_ext:
                raise ValueError(f"File extension cannot be changed. Keep {required_ext}.")
            if not actual_ext:
                candidate = f"{candidate}{required_ext}"
        return candidate

    def _folder_storage_dir(self, user_id: int, folder_id: int | None) -> Path:
        root = self.settings.user_docs_dir / str(user_id)
        if not folder_id:
            return root
        return root / str(folder_id)

    def _ensure_user_docs_root(self) -> None:
        self.settings.user_docs_dir.mkdir(parents=True, exist_ok=True)

    def _get_folder_row(self, session, folder_id: int) -> DocumentFolderRow | None:
        row = session.execute(
            text(
                """
                SELECT id, user_id, parent_id, folder_name, sort_order, is_deleted, created_at, updated_at
                FROM kop_document_folder
                WHERE id = :folder_id
                  AND is_deleted = 0
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
            parent_id=int(row[2] or 0),
            folder_name=str(row[3]),
            sort_order=int(row[4] or 0),
            is_deleted=int(row[5] or 0),
            created_at=row[6],
            updated_at=row[7],
        )

    def _get_folder_by_parent_and_name(self, session, user_id: int, parent_id: int, name: str) -> DocumentFolderRow | None:
        row = session.execute(
            text(
                """
                SELECT id, user_id, parent_id, folder_name, sort_order, is_deleted, created_at, updated_at
                FROM kop_document_folder
                WHERE user_id = :user_id
                  AND parent_id = :parent_id
                  AND is_deleted = 0
                  AND folder_name = :folder_name
                LIMIT 1
                """
            ),
            {"user_id": user_id, "parent_id": parent_id, "folder_name": name},
        ).first()
        if not row:
            return None
        return DocumentFolderRow(
            id=int(row[0]),
            user_id=int(row[1]),
            parent_id=int(row[2] or 0),
            folder_name=str(row[3]),
            sort_order=int(row[4] or 0),
            is_deleted=int(row[5] or 0),
            created_at=row[6],
            updated_at=row[7],
        )

    def _get_file_row(self, session, file_id: int) -> DocumentFileRow | None:
        row = session.execute(
            text(
                """
                SELECT
                    id, user_id, folder_id, kb_id, original_name, stored_name, file_path, file_ext,
                    mime_type, file_size, file_hash, source_type, parse_status, index_status,
                    parse_error, last_indexed_at, is_deleted, created_at, updated_at
                FROM kop_document_file
                WHERE id = :file_id
                  AND is_deleted = 0
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
            folder_id=int(row[2] or 0),
            kb_id=int(row[3] or 0),
            original_name=str(row[4]),
            stored_name=str(row[5]),
            file_path=str(row[6]),
            file_ext=str(row[7] or ""),
            mime_type=str(row[8]) if row[8] is not None else None,
            file_size=int(row[9] or 0),
            file_hash=str(row[10]) if row[10] is not None else None,
            source_type=str(row[11] or "upload"),
            parse_status=str(row[12] or "pending"),
            index_status=str(row[13] or "pending"),
            parse_error=str(row[14]) if row[14] is not None else None,
            last_indexed_at=row[15],
            is_deleted=int(row[16] or 0),
            created_at=row[17],
            updated_at=row[18],
        )

    def _get_file_by_storage_path(self, session, user_id: int, storage_path: str) -> DocumentFileRow | None:
        normalized = self._normalize_path(storage_path)
        if not normalized:
            return None
        row = session.execute(
            text(
                """
                SELECT
                    id, user_id, folder_id, kb_id, original_name, stored_name, file_path, file_ext,
                    mime_type, file_size, file_hash, source_type, parse_status, index_status,
                    parse_error, last_indexed_at, is_deleted, created_at, updated_at
                FROM kop_document_file
                WHERE user_id = :user_id
                  AND file_path = :file_path
                  AND is_deleted = 0
                LIMIT 1
                """
            ),
            {"user_id": user_id, "file_path": normalized},
        ).first()
        if not row:
            return None
        return DocumentFileRow(
            id=int(row[0]),
            user_id=int(row[1]),
            folder_id=int(row[2] or 0),
            kb_id=int(row[3] or 0),
            original_name=str(row[4]),
            stored_name=str(row[5]),
            file_path=str(row[6]),
            file_ext=str(row[7] or ""),
            mime_type=str(row[8]) if row[8] is not None else None,
            file_size=int(row[9] or 0),
            file_hash=str(row[10]) if row[10] is not None else None,
            source_type=str(row[11] or "upload"),
            parse_status=str(row[12] or "pending"),
            index_status=str(row[13] or "pending"),
            parse_error=str(row[14]) if row[14] is not None else None,
            last_indexed_at=row[15],
            is_deleted=int(row[16] or 0),
            created_at=row[17],
            updated_at=row[18],
        )

    def _get_file_by_storage_path_any_user(self, session, storage_path: str) -> DocumentFileRow | None:
        normalized = self._normalize_path(storage_path)
        if not normalized:
            return None
        row = session.execute(
            text(
                """
                SELECT
                    id, user_id, folder_id, kb_id, original_name, stored_name, file_path, file_ext,
                    mime_type, file_size, file_hash, source_type, parse_status, index_status,
                    parse_error, last_indexed_at, is_deleted, created_at, updated_at
                FROM kop_document_file
                WHERE file_path = :file_path
                  AND is_deleted = 0
                LIMIT 1
                """
            ),
            {"file_path": normalized},
        ).first()
        if not row:
            return None
        return DocumentFileRow(
            id=int(row[0]),
            user_id=int(row[1]),
            folder_id=int(row[2] or 0),
            kb_id=int(row[3] or 0),
            original_name=str(row[4]),
            stored_name=str(row[5]),
            file_path=str(row[6]),
            file_ext=str(row[7] or ""),
            mime_type=str(row[8]) if row[8] is not None else None,
            file_size=int(row[9] or 0),
            file_hash=str(row[10]) if row[10] is not None else None,
            source_type=str(row[11] or "upload"),
            parse_status=str(row[12] or "pending"),
            index_status=str(row[13] or "pending"),
            parse_error=str(row[14]) if row[14] is not None else None,
            last_indexed_at=row[15],
            is_deleted=int(row[16] or 0),
            created_at=row[17],
            updated_at=row[18],
        )

    def _get_file_by_id(self, session, user_id: int, file_id: int) -> DocumentFileRow | None:
        row = self._get_file_row(session, file_id)
        if row is None or row.user_id != user_id:
            return None
        return row

    def _resolve_file_row(
        self,
        session,
        user_id: int,
        path_value: str | None = None,
        file_id: int | None = None,
    ) -> DocumentFileRow | None:
        if file_id is not None:
            try:
                resolved = self._get_file_by_id(session, user_id, int(file_id))
            except Exception:
                resolved = None
            if resolved is not None:
                return resolved
        if path_value:
            return self._get_file_by_storage_path(session, user_id, path_value)
        return None

    def _get_file_by_folder_and_name(
        self,
        session,
        user_id: int,
        folder_id: int,
        original_name: str,
        *,
        exclude_file_id: int | None = None,
    ) -> DocumentFileRow | None:
        row = session.execute(
            text(
                """
                SELECT
                    id, user_id, folder_id, kb_id, original_name, stored_name, file_path, file_ext,
                    mime_type, file_size, file_hash, source_type, parse_status, index_status,
                    parse_error, last_indexed_at, is_deleted, created_at, updated_at
                FROM kop_document_file
                WHERE user_id = :user_id
                  AND folder_id = :folder_id
                  AND original_name = :original_name
                  AND is_deleted = 0
                  AND (:exclude_file_id IS NULL OR id <> :exclude_file_id)
                LIMIT 1
                """
            ),
            {
                "user_id": user_id,
                "folder_id": folder_id,
                "original_name": original_name,
                "exclude_file_id": exclude_file_id,
            },
        ).first()
        if not row:
            return None
        return DocumentFileRow(
            id=int(row[0]),
            user_id=int(row[1]),
            folder_id=int(row[2] or 0),
            kb_id=int(row[3] or 0),
            original_name=str(row[4]),
            stored_name=str(row[5]),
            file_path=str(row[6]),
            file_ext=str(row[7] or ""),
            mime_type=str(row[8]) if row[8] is not None else None,
            file_size=int(row[9] or 0),
            file_hash=str(row[10]) if row[10] is not None else None,
            source_type=str(row[11] or "upload"),
            parse_status=str(row[12] or "pending"),
            index_status=str(row[13] or "pending"),
            parse_error=str(row[14]) if row[14] is not None else None,
            last_indexed_at=row[15],
            is_deleted=int(row[16] or 0),
            created_at=row[17],
            updated_at=row[18],
        )

    def _list_user_folder_rows(self, session, user_id: int) -> list[DocumentFolderRow]:
        rows = session.execute(
            text(
                """
                SELECT id, user_id, parent_id, folder_name, sort_order, is_deleted, created_at, updated_at
                FROM kop_document_folder
                WHERE user_id = :user_id
                  AND is_deleted = 0
                ORDER BY parent_id ASC, sort_order ASC, folder_name ASC, id ASC
                """
            ),
            {"user_id": user_id},
        ).all()
        return [
            DocumentFolderRow(
                id=int(row[0]),
                user_id=int(row[1]),
                parent_id=int(row[2] or 0),
                folder_name=str(row[3]),
                sort_order=int(row[4] or 0),
                is_deleted=int(row[5] or 0),
                created_at=row[6],
                updated_at=row[7],
            )
            for row in rows
        ]

    def _list_user_file_rows(self, session, user_id: int) -> list[DocumentFileRow]:
        rows = session.execute(
            text(
                """
                SELECT
                    id, user_id, folder_id, kb_id, original_name, stored_name, file_path, file_ext,
                    mime_type, file_size, file_hash, source_type, parse_status, index_status,
                    parse_error, last_indexed_at, is_deleted, created_at, updated_at
                FROM kop_document_file
                WHERE user_id = :user_id
                  AND is_deleted = 0
                ORDER BY updated_at DESC, id DESC
                """
            ),
            {"user_id": user_id},
        ).all()
        return [
            DocumentFileRow(
                id=int(row[0]),
                user_id=int(row[1]),
                folder_id=int(row[2] or 0),
                kb_id=int(row[3] or 0),
                original_name=str(row[4]),
                stored_name=str(row[5]),
                file_path=str(row[6]),
                file_ext=str(row[7] or ""),
                mime_type=str(row[8]) if row[8] is not None else None,
                file_size=int(row[9] or 0),
                file_hash=str(row[10]) if row[10] is not None else None,
                source_type=str(row[11] or "upload"),
                parse_status=str(row[12] or "pending"),
                index_status=str(row[13] or "pending"),
                parse_error=str(row[14]) if row[14] is not None else None,
                last_indexed_at=row[15],
                is_deleted=int(row[16] or 0),
                created_at=row[17],
                updated_at=row[18],
            )
            for row in rows
        ]

    def _folder_payload_path_map(self, folders: list[DocumentFolderRow]) -> dict[int, str]:
        children_by_parent: dict[int, list[DocumentFolderRow]] = {}
        for folder in folders:
            children_by_parent.setdefault(folder.parent_id or 0, []).append(folder)

        for items in children_by_parent.values():
            items.sort(key=lambda item: (item.sort_order, item.folder_name.lower(), item.id))

        path_map: dict[int, str] = {}

        def walk(folder: DocumentFolderRow, parent_path: str) -> None:
            current_path = f"{parent_path}/{folder.folder_name}" if parent_path else folder.folder_name
            path_map[folder.id] = current_path
            for child in children_by_parent.get(folder.id, []):
                walk(child, current_path)

        for root in children_by_parent.get(0, []):
            walk(root, "")
        return path_map

    def _folder_path_cache(self, session, user_id: int, folder_id: int | None) -> str:
        if not folder_id:
            return ""
        folders = self._list_user_folder_rows(session, user_id)
        return self._folder_payload_path_map(folders).get(folder_id, "")

    def _resolve_folder_by_path(self, session, user_id: int, folder_path: str | None) -> DocumentFolderRow | None:
        raw = self._normalize_path(folder_path)
        if not raw:
            return None

        current_parent = 0
        current_row: DocumentFolderRow | None = None
        for part in [segment for segment in raw.split("/") if segment]:
            current_row = self._get_folder_by_parent_and_name(session, user_id, current_parent, part)
            if current_row is None:
                return None
            current_parent = current_row.id
        return current_row

    def _resolve_folder_row(self, session, user_id: int, parent_path: str | None, parent_id: int | None) -> DocumentFolderRow | None:
        if parent_id is not None:
            folder = self._get_folder_row(session, int(parent_id))
            if folder is None or folder.user_id != user_id:
                return None
            return folder
        if parent_path:
            return self._resolve_folder_by_path(session, user_id, parent_path)
        return None

    def _build_folder_cache(self, parent_cache: str, name: str) -> str:
        base = parent_cache.strip("/")
        name = name.strip("/")
        if not base:
            return name
        if not name:
            return base
        return f"{base}/{name}"

    def _file_to_payload(self, file_row: DocumentFileRow, folder_cache: str = "") -> dict[str, Any]:
        display_path = f"{folder_cache}/{file_row.original_name}" if folder_cache else file_row.original_name
        return {
            "id": file_row.id,
            "path": file_row.file_path,
            "display_path": display_path,
            "size_bytes": file_row.file_size,
            "modified_at": file_row.updated_at.isoformat(timespec="seconds"),
            "extension": file_row.file_ext,
            "is_directory": False,
            "parent_id": file_row.folder_id or None,
            "folder_id": file_row.folder_id or None,
            "name": file_row.original_name,
            "source_type": file_row.source_type,
        }

    def _folder_to_payload(self, folder: DocumentFolderRow, folder_path: str) -> dict[str, Any]:
        parent_path = self._build_folder_cache("", folder_path.rsplit("/", 1)[0]) if "/" in folder_path else ""
        return {
            "id": folder.id,
            "path": folder_path,
            "display_path": folder_path,
            "size_bytes": 0,
            "modified_at": folder.updated_at.isoformat(timespec="seconds"),
            "extension": "",
            "is_directory": True,
            "parent_id": folder.parent_id or None,
            "folder_id": folder.id,
            "name": folder.folder_name,
            "source_type": "db",
        }

    def _resolve_kb_info(self, session, kb_id: int) -> dict[str, Any]:
        if not kb_id:
            return {
                "kb_id": 0,
                "workspace_id": 0,
                "workspace_key": None,
                "kb_name": None,
            }

        row = session.execute(
            text(
                """
                SELECT k.id, k.workspace_id, w.workspace_key, k.kb_name
                FROM kop_kb k
                LEFT JOIN kop_workspace w ON w.id = k.workspace_id
                WHERE k.id = :kb_id
                  AND k.is_deleted = 0
                LIMIT 1
                """
            ),
            {"kb_id": kb_id},
        ).first()
        if not row:
            return {
                "kb_id": kb_id,
                "workspace_id": 0,
                "workspace_key": None,
                "kb_name": None,
            }
        return {
            "kb_id": int(row[0] or 0),
            "workspace_id": int(row[1] or 0),
            "workspace_key": str(row[2]) if row[2] is not None else None,
            "kb_name": str(row[3]) if row[3] is not None else None,
        }

    def list_kb_scope_options(self) -> list[dict[str, Any]]:
        self._ensure_sql()
        with session_scope() as session:
            user_id = self._get_or_create_default_user_id(session)
            rows = session.execute(
                text(
                    """
                    SELECT
                        k.id,
                        k.workspace_id,
                        w.workspace_key,
                        w.workspace_name,
                        k.kb_name,
                        k.folder_id
                    FROM kop_kb k
                    LEFT JOIN kop_workspace w ON w.id = k.workspace_id
                    WHERE k.user_id = :user_id
                      AND k.is_deleted = 0
                    ORDER BY COALESCE(w.workspace_name, ''), k.kb_name ASC, k.id ASC
                    """
                ),
                {"user_id": user_id},
            ).all()

        options: list[dict[str, Any]] = []
        for row in rows:
            kb_id = int(row[0] or 0)
            workspace_id = int(row[1] or 0) if row[1] is not None else None
            workspace_key = str(row[2]) if row[2] is not None else None
            workspace_name = str(row[3]) if row[3] is not None else None
            kb_name = str(row[4]) if row[4] is not None else None
            folder_id = int(row[5] or 0) if row[5] is not None else None
            label_parts = [part for part in [workspace_name, kb_name] if part]
            label = " / ".join(label_parts) if label_parts else f"KB #{kb_id}"
            options.append(
                {
                    "id": kb_id,
                    "label": label,
                    "workspace_id": workspace_id,
                    "workspace_key": workspace_key,
                    "workspace_name": workspace_name,
                    "folder_id": folder_id if folder_id and folder_id > 0 else None,
                }
            )
        return options

    def list_workspace_scope_options(self) -> list[dict[str, Any]]:
        self._ensure_sql()
        with session_scope() as session:
            user_id = self._get_or_create_default_user_id(session)
            rows = session.execute(
                text(
                    """
                    SELECT id, workspace_key, workspace_name
                    FROM kop_workspace
                    WHERE user_id = :user_id
                      AND status = 1
                    ORDER BY is_default DESC, workspace_name ASC, id ASC
                    """
                ),
                {"user_id": user_id},
            ).all()

        options: list[dict[str, Any]] = []
        for row in rows:
            workspace_id = int(row[0] or 0)
            workspace_key = str(row[1]) if row[1] is not None else ""
            workspace_name = str(row[2]) if row[2] is not None else ""
            label = workspace_name or workspace_key or f"Workspace #{workspace_id}"
            options.append(
                {
                    "id": workspace_id,
                    "key": workspace_key,
                    "label": label,
                    "workspace_name": workspace_name or None,
                }
            )
        return options

    def _file_to_index_metadata(
        self,
        file_row: DocumentFileRow,
        folder_cache: str = "",
        kb_info: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        display_path = f"{folder_cache}/{file_row.original_name}" if folder_cache else file_row.original_name
        kb_data = kb_info or {
            "kb_id": file_row.kb_id or 0,
            "workspace_id": 0,
            "workspace_key": None,
            "kb_name": None,
        }
        metadata = {
            "user_id": file_row.user_id,
            "file_id": file_row.id,
            "folder_id": file_row.folder_id or 0,
            "kb_id": file_row.kb_id or 0,
            "workspace_id": kb_data.get("workspace_id", 0),
            "workspace_key": kb_data.get("workspace_key"),
            "original_name": file_row.original_name,
            "stored_name": file_row.stored_name,
            "display_name": file_row.original_name,
            "display_path": display_path,
            "folder_path": folder_cache,
            "file_path": file_row.file_path,
            "source_type": file_row.source_type,
        }
        if kb_data.get("kb_name"):
            metadata["kb_name"] = kb_data.get("kb_name")
        return metadata

    def get_index_metadata_by_storage_path(self, storage_path: str) -> dict[str, Any] | None:
        self._ensure_sql()
        normalized_path = self._normalize_path(storage_path)
        if not normalized_path:
            return None

        with session_scope() as session:
            user_id = self._get_or_create_default_user_id(session)
            file_row = self._get_file_by_storage_path(session, user_id, normalized_path)
            if file_row is None:
                file_row = self._get_file_by_storage_path_any_user(session, normalized_path)
            if file_row is None:
                return None
            folder_cache = self._folder_path_cache(session, user_id, file_row.folder_id)
            if file_row.user_id != user_id:
                folder_cache = self._folder_path_cache(session, file_row.user_id, file_row.folder_id)
            kb_info = self._resolve_kb_info(session, file_row.kb_id)
            return self._file_to_index_metadata(file_row, folder_cache=folder_cache, kb_info=kb_info)

    def _make_file_storage_name(self, original_name: str, file_bytes: bytes) -> tuple[str, str]:
        path = Path(original_name)
        extension = path.suffix.lower()
        stem = path.stem or "upload"
        sha256 = hashlib.sha256(file_bytes).hexdigest()
        stored_name = f"{stem}_{sha256[:12]}{extension}"
        return stored_name, sha256

    def _store_file(self, session, user_id: int, folder_id: int, upload: UploadFile, content: bytes) -> dict[str, Any]:
        original_name = Path(upload.filename or "upload").name
        stored_name, sha256 = self._make_file_storage_name(original_name, content)
        extension = Path(original_name).suffix.lower()
        storage_dir = self._folder_storage_dir(user_id, folder_id or None)
        storage_dir.mkdir(parents=True, exist_ok=True)
        storage_path = storage_dir / stored_name
        storage_path.write_bytes(content)
        mime_type = upload.content_type or mimetypes.guess_type(original_name)[0]

        relative_storage_path = str(storage_path.relative_to(self.settings.root_dir)).replace("\\", "/")
        now_value = self._now()
        result = session.execute(
            text(
                """
                INSERT INTO kop_document_file
                    (user_id, folder_id, kb_id, original_name, stored_name, file_path, file_ext, mime_type,
                     file_size, file_hash, source_type, parse_status, index_status, parse_error,
                     last_indexed_at, is_deleted, created_at, updated_at)
                VALUES
                    (:user_id, :folder_id, 0, :original_name, :stored_name, :file_path, :file_ext, :mime_type,
                     :file_size, :file_hash, 'upload', 'pending', 'pending', NULL,
                     NULL, 0, :created_at, :updated_at)
                """
            ),
            {
                "user_id": user_id,
                "folder_id": folder_id,
                "original_name": original_name,
                "stored_name": stored_name,
                "file_path": relative_storage_path,
                "file_ext": extension,
                "mime_type": mime_type,
                "file_size": len(content),
                "file_hash": sha256,
                "created_at": now_value,
                "updated_at": now_value,
            },
        )
        file_id = int(result.lastrowid)
        row = self._get_file_row(session, file_id)
        if row is None:
            raise RuntimeError("File created but could not be reloaded.")

        folder_cache = self._folder_path_cache(session, user_id, row.folder_id)
        return self._file_to_payload(row, folder_cache=folder_cache)

    def _collect_descendant_folder_ids(self, folders: list[DocumentFolderRow], folder_id: int) -> list[int]:
        children_by_parent: dict[int, list[int]] = {}
        for folder in folders:
            children_by_parent.setdefault(folder.parent_id or 0, []).append(folder.id)

        for children in children_by_parent.values():
            children.sort()

        ordered_ids: list[int] = []

        def walk(current_id: int) -> None:
            ordered_ids.append(current_id)
            for child_id in children_by_parent.get(current_id, []):
                walk(child_id)

        walk(folder_id)
        return ordered_ids

    def get_descendant_folder_ids(self, folder_id: int) -> list[int]:
        self._ensure_sql()
        with session_scope() as session:
            user_id = self._get_or_create_default_user_id(session)
            folders = self._list_user_folder_rows(session, user_id)
            return self._collect_descendant_folder_ids(folders, folder_id)

    def _file_row_to_disk_path(self, file_row: DocumentFileRow) -> Path:
        return (self.settings.root_dir / file_row.file_path).resolve()

    def _unique_storage_path(self, directory: Path, stored_name: str, file_id: int, source_path: Path) -> tuple[Path, str]:
        directory.mkdir(parents=True, exist_ok=True)
        candidate = directory / stored_name
        try:
            if candidate.resolve() == source_path.resolve():
                return candidate, stored_name
        except Exception:
            pass
        if not candidate.exists():
            return candidate, stored_name

        stem = Path(stored_name).stem or "file"
        suffix = Path(stored_name).suffix
        for index in range(1, 1000):
            next_name = f"{stem}_{file_id}_{index}{suffix}"
            next_path = directory / next_name
            if not next_path.exists():
                return next_path, next_name
        raise FileExistsError("Could not allocate a unique storage path.")

    def _list_file_rows_for_folder_ids(self, session, user_id: int, folder_ids: set[int]) -> list[DocumentFileRow]:
        if not folder_ids:
            return []
        return [
            file_row
            for file_row in self._list_user_file_rows(session, user_id)
            if file_row.folder_id in folder_ids
        ]

    def _folder_row_to_payload(self, folder_row: DocumentFolderRow, folder_path: str) -> dict[str, Any]:
        return {
            "id": folder_row.id,
            "path": folder_path,
            "display_path": folder_path,
            "size_bytes": 0,
            "modified_at": folder_row.updated_at.isoformat(timespec="seconds"),
            "extension": "",
            "is_directory": True,
            "parent_id": folder_row.parent_id or None,
            "folder_id": folder_row.id,
            "name": folder_row.folder_name,
            "source_type": "db",
        }

    def update_file_index_states(
        self,
        file_ids: list[int],
        *,
        index_status: str,
        last_indexed_at: datetime | None = None,
        parse_error: str | None = None,
    ) -> int:
        self._ensure_sql()
        normalized_ids = sorted({int(file_id) for file_id in file_ids if file_id is not None})
        if not normalized_ids:
            return 0

        now_value = last_indexed_at or self._now()
        set_clauses = [
            "index_status = :index_status",
            "updated_at = :updated_at",
        ]
        params: dict[str, Any] = {
            "index_status": str(index_status or "idle"),
            "updated_at": now_value,
        }

        if index_status == "success" or last_indexed_at is not None:
            set_clauses.append("last_indexed_at = :last_indexed_at")
            params["last_indexed_at"] = now_value
        if parse_error is None:
            if index_status in {"queued", "running", "success"}:
                set_clauses.append("parse_error = NULL")
        else:
            set_clauses.append("parse_error = :parse_error")
            params["parse_error"] = parse_error

        statement = text(
            f"""
            UPDATE kop_document_file
            SET {", ".join(set_clauses)}
            WHERE id = :file_id
            """
        )

        affected = 0
        with session_scope() as session:
            user_id = self._get_or_create_default_user_id(session)
            for file_id in normalized_ids:
                row = self._get_file_by_id(session, user_id, file_id)
                if row is None:
                    continue
                session.execute(statement, {**params, "file_id": file_id})
                affected += 1
        return affected

    def get_document_by_id(self, file_id: int) -> dict[str, Any]:
        self._ensure_sql()
        with session_scope() as session:
            user_id = self._get_or_create_default_user_id(session)
            row = self._get_file_by_id(session, user_id, int(file_id))
            if row is None:
                raise FileNotFoundError(f"File not found: {file_id}")
            folder_cache = self._folder_path_cache(session, user_id, row.folder_id)
            return self._file_to_payload(row, folder_cache=folder_cache)

    def list_documents(self) -> list[dict[str, Any]]:
        self._ensure_sql()
        with session_scope() as session:
            user_id = self._get_or_create_default_user_id(session)
            payload: list[dict[str, Any]] = []

            folder_rows = self._list_user_folder_rows(session, user_id)
            folder_paths = self._folder_payload_path_map(folder_rows)
            for folder_row in folder_rows:
                folder_path = folder_paths.get(folder_row.id, folder_row.folder_name)
                payload.append(self._folder_row_to_payload(folder_row, folder_path))

            file_rows = self._list_user_file_rows(session, user_id)
            for file_row in file_rows:
                folder_cache = self._folder_path_cache(session, user_id, file_row.folder_id)
                payload.append(self._file_to_payload(file_row, folder_cache=folder_cache))

            return sorted(
                payload,
                key=lambda item: (
                    str(item.get("display_path") or item.get("path") or "").lower(),
                    not bool(item.get("is_directory")),
                ),
            )

    def create_folder(self, parent_path: str | None, parent_id: int | None, name: str) -> dict[str, Any]:
        self._ensure_sql()
        safe_name = self._normalize_folder_name(name)

        with session_scope() as session:
            user_id = self._get_or_create_default_user_id(session)
            parent_row = self._resolve_folder_row(session, user_id, parent_path, parent_id)
            normalized_parent_id = parent_row.id if parent_row else 0

            exists = self._get_folder_by_parent_and_name(session, user_id, normalized_parent_id, safe_name)
            if exists:
                folder_rows = self._list_user_folder_rows(session, user_id)
                folder_path = self._folder_payload_path_map(folder_rows).get(exists.id, safe_name)
                return self._folder_row_to_payload(exists, folder_path)

            now_value = self._now()
            result = session.execute(
                text(
                    """
                    INSERT INTO kop_document_folder
                        (user_id, parent_id, folder_name, sort_order, is_deleted, created_at, updated_at)
                    VALUES
                        (:user_id, :parent_id, :folder_name, 0, 0, :created_at, :updated_at)
                    """
                ),
                {
                    "user_id": user_id,
                    "parent_id": normalized_parent_id,
                    "folder_name": safe_name,
                    "created_at": now_value,
                    "updated_at": now_value,
                },
            )
            folder_id = int(result.lastrowid)
            created = self._get_folder_row(session, folder_id)
            if created is None:
                raise RuntimeError("Folder created but could not be reloaded.")

            folder_rows = self._list_user_folder_rows(session, user_id)
            folder_path = self._folder_payload_path_map(folder_rows).get(folder_id, safe_name)
            return self._folder_row_to_payload(created, folder_path)

    def _rename_file_row(self, session, row: DocumentFileRow, new_name: str) -> dict[str, Any]:
        safe_name = self._normalize_file_name(new_name, row.file_ext)
        duplicate = self._get_file_by_folder_and_name(
            session,
            row.user_id,
            row.folder_id,
            safe_name,
            exclude_file_id=row.id,
        )
        if duplicate is not None:
            raise FileExistsError(f"File already exists in this folder: {safe_name}")

        now_value = self._now()
        session.execute(
            text(
                """
                UPDATE kop_document_file
                SET original_name = :original_name,
                    index_status = 'queued',
                    parse_error = NULL,
                    updated_at = :updated_at
                WHERE id = :file_id
                """
            ),
            {
                "file_id": row.id,
                "original_name": safe_name,
                "updated_at": now_value,
            },
        )
        updated = self._get_file_row(session, row.id)
        if updated is None:
            raise RuntimeError("File renamed but could not be reloaded.")
        folder_cache = self._folder_path_cache(session, row.user_id, updated.folder_id)
        payload = self._file_to_payload(updated, folder_cache=folder_cache)
        return {
            "previous_path": row.file_path,
            "path": updated.file_path,
            "file_id": updated.id,
            "source_files": [updated.file_path],
            "item": payload,
        }

    def _move_file_row(
        self,
        session,
        row: DocumentFileRow,
        parent_path: str | None = None,
        parent_id: int | None = None,
    ) -> dict[str, Any]:
        self._ensure_user_docs_root()
        target_folder = self._resolve_folder_row(session, row.user_id, parent_path, parent_id)
        target_folder_id = target_folder.id if target_folder else 0
        if row.folder_id == target_folder_id:
            folder_cache = self._folder_path_cache(session, row.user_id, row.folder_id)
            return {
                "previous_path": row.file_path,
                "path": row.file_path,
                "file_id": row.id,
                "source_files": [row.file_path],
                "item": self._file_to_payload(row, folder_cache=folder_cache),
            }

        duplicate = self._get_file_by_folder_and_name(
            session,
            row.user_id,
            target_folder_id,
            row.original_name,
            exclude_file_id=row.id,
        )
        if duplicate is not None:
            raise FileExistsError(f"File already exists in target folder: {row.original_name}")

        source_path = self._file_row_to_disk_path(row)
        if not source_path.exists() or not source_path.is_file():
            raise FileNotFoundError(f"Stored file not found: {row.file_path}")

        target_dir = self._folder_storage_dir(row.user_id, target_folder_id or None)
        target_path, target_stored_name = self._unique_storage_path(target_dir, row.stored_name, row.id, source_path)
        if target_path.resolve() != source_path.resolve():
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source_path), str(target_path))

        relative_target_path = str(target_path.relative_to(self.settings.root_dir)).replace("\\", "/")
        now_value = self._now()
        session.execute(
            text(
                """
                UPDATE kop_document_file
                SET folder_id = :folder_id,
                    stored_name = :stored_name,
                    file_path = :file_path,
                    index_status = 'queued',
                    parse_error = NULL,
                    updated_at = :updated_at
                WHERE id = :file_id
                """
            ),
            {
                "file_id": row.id,
                "folder_id": target_folder_id,
                "stored_name": target_stored_name,
                "file_path": relative_target_path,
                "updated_at": now_value,
            },
        )
        updated = self._get_file_row(session, row.id)
        if updated is None:
            raise RuntimeError("File moved but could not be reloaded.")
        folder_cache = self._folder_path_cache(session, row.user_id, updated.folder_id)
        return {
            "previous_path": row.file_path,
            "path": updated.file_path,
            "file_id": updated.id,
            "source_files": [updated.file_path],
            "item": self._file_to_payload(updated, folder_cache=folder_cache),
        }

    def _delete_file_row(self, session, row: DocumentFileRow) -> dict[str, Any]:
        file_path = self._file_row_to_disk_path(row)
        preview_cache_path: Path | None = None
        if row.file_ext.lower() in {".doc", ".docx", ".ppt", ".pptx"}:
            try:
                preview_cache_path = get_preview_pdf_cache_path(file_path)
            except Exception:
                preview_cache_path = None

        session.execute(
            text("DELETE FROM kop_document_file WHERE id = :file_id"),
            {"file_id": row.id},
        )

        if file_path.exists():
            file_path.unlink()
        if preview_cache_path and preview_cache_path.exists():
            preview_cache_path.unlink(missing_ok=True)
        return {"path": row.file_path, "file_id": row.id}

    def rename_file(self, path_value: str, new_name: str) -> dict[str, Any]:
        self._ensure_sql()
        normalized_path = self._normalize_path(path_value)
        if not normalized_path:
            raise ValueError("File path is required.")

        with session_scope() as session:
            user_id = self._get_or_create_default_user_id(session)
            row = self._get_file_by_storage_path(session, user_id, normalized_path)
            if row is None:
                raise FileNotFoundError(f"File not found: {path_value}")
            return self._rename_file_row(session, row, new_name)

    def rename_file_by_id(self, file_id: int, new_name: str) -> dict[str, Any]:
        self._ensure_sql()
        with session_scope() as session:
            user_id = self._get_or_create_default_user_id(session)
            row = self._get_file_by_id(session, user_id, int(file_id))
            if row is None:
                raise FileNotFoundError(f"File not found: {file_id}")
            return self._rename_file_row(session, row, new_name)

    def move_file(
        self,
        path_value: str,
        parent_path: str | None = None,
        parent_id: int | None = None,
    ) -> dict[str, Any]:
        self._ensure_sql()
        normalized_path = self._normalize_path(path_value)
        if not normalized_path:
            raise ValueError("File path is required.")

        self._ensure_user_docs_root()
        with session_scope() as session:
            user_id = self._get_or_create_default_user_id(session)
            row = self._get_file_by_storage_path(session, user_id, normalized_path)
            if row is None:
                raise FileNotFoundError(f"File not found: {path_value}")
            return self._move_file_row(session, row, parent_path, parent_id)

    def move_file_by_id(
        self,
        file_id: int,
        parent_path: str | None = None,
        parent_id: int | None = None,
    ) -> dict[str, Any]:
        self._ensure_sql()
        with session_scope() as session:
            user_id = self._get_or_create_default_user_id(session)
            row = self._get_file_by_id(session, user_id, int(file_id))
            if row is None:
                raise FileNotFoundError(f"File not found: {file_id}")
            return self._move_file_row(session, row, parent_path, parent_id)

    def rename_folder(self, path_value: str, new_name: str) -> dict[str, Any]:
        self._ensure_sql()
        normalized_path = self._normalize_path(path_value)
        if not normalized_path:
            raise ValueError("Folder path is required.")
        safe_name = self._normalize_folder_name(new_name)

        with session_scope() as session:
            user_id = self._get_or_create_default_user_id(session)
            folder = self._resolve_folder_by_path(session, user_id, normalized_path)
            if folder is None:
                raise FileNotFoundError(f"Folder not found: {path_value}")

            duplicate = self._get_folder_by_parent_and_name(session, user_id, folder.parent_id, safe_name)
            if duplicate is not None and duplicate.id != folder.id:
                raise FileExistsError(f"Folder already exists here: {safe_name}")

            folder_rows = self._list_user_folder_rows(session, user_id)
            descendant_folder_ids = self._collect_descendant_folder_ids(folder_rows, folder.id)
            file_rows = self._list_file_rows_for_folder_ids(session, user_id, set(descendant_folder_ids))
            previous_paths = self._folder_payload_path_map(folder_rows)

            now_value = self._now()
            session.execute(
                text(
                    """
                    UPDATE kop_document_folder
                    SET folder_name = :folder_name,
                        updated_at = :updated_at
                    WHERE id = :folder_id
                    """
                ),
                {
                    "folder_id": folder.id,
                    "folder_name": safe_name,
                    "updated_at": now_value,
                },
            )

            updated_folder = self._get_folder_row(session, folder.id)
            if updated_folder is None:
                raise RuntimeError("Folder renamed but could not be reloaded.")
            updated_rows = self._list_user_folder_rows(session, user_id)
            updated_paths = self._folder_payload_path_map(updated_rows)
            return {
                "previous_path": previous_paths.get(folder.id, normalized_path),
                "path": updated_paths.get(folder.id, safe_name),
                "folder_id": folder.id,
                "file_ids": [row.id for row in file_rows],
                "source_files": [row.file_path for row in file_rows],
                "item": self._folder_row_to_payload(updated_folder, updated_paths.get(folder.id, safe_name)),
            }

    def move_folder(
        self,
        path_value: str,
        parent_path: str | None = None,
        parent_id: int | None = None,
    ) -> dict[str, Any]:
        self._ensure_sql()
        normalized_path = self._normalize_path(path_value)
        if not normalized_path:
            raise ValueError("Folder path is required.")

        with session_scope() as session:
            user_id = self._get_or_create_default_user_id(session)
            folder = self._resolve_folder_by_path(session, user_id, normalized_path)
            if folder is None:
                raise FileNotFoundError(f"Folder not found: {path_value}")

            target_folder = self._resolve_folder_row(session, user_id, parent_path, parent_id)
            target_parent_id = target_folder.id if target_folder else 0
            folder_rows = self._list_user_folder_rows(session, user_id)
            descendant_folder_ids = self._collect_descendant_folder_ids(folder_rows, folder.id)
            if target_parent_id == folder.id or target_parent_id in set(descendant_folder_ids):
                raise ValueError("Cannot move a folder into itself or one of its descendants.")
            if target_parent_id == folder.parent_id:
                previous_paths = self._folder_payload_path_map(folder_rows)
                descendant_id_set = set(descendant_folder_ids)
                file_rows = self._list_file_rows_for_folder_ids(session, user_id, descendant_id_set)
                return {
                    "previous_path": previous_paths.get(folder.id, normalized_path),
                    "path": previous_paths.get(folder.id, normalized_path),
                    "folder_id": folder.id,
                    "file_ids": [row.id for row in file_rows],
                    "source_files": [row.file_path for row in file_rows],
                    "item": self._folder_row_to_payload(folder, previous_paths.get(folder.id, normalized_path)),
                }

            duplicate = self._get_folder_by_parent_and_name(session, user_id, target_parent_id, folder.folder_name)
            if duplicate is not None and duplicate.id != folder.id:
                raise FileExistsError(f"Folder already exists in target folder: {folder.folder_name}")

            previous_paths = self._folder_payload_path_map(folder_rows)
            descendant_id_set = set(descendant_folder_ids)
            file_rows = self._list_file_rows_for_folder_ids(session, user_id, descendant_id_set)
            now_value = self._now()
            session.execute(
                text(
                    """
                    UPDATE kop_document_folder
                    SET parent_id = :parent_id,
                        updated_at = :updated_at
                    WHERE id = :folder_id
                    """
                ),
                {
                    "folder_id": folder.id,
                    "parent_id": target_parent_id,
                    "updated_at": now_value,
                },
            )

            updated_folder = self._get_folder_row(session, folder.id)
            if updated_folder is None:
                raise RuntimeError("Folder moved but could not be reloaded.")
            updated_rows = self._list_user_folder_rows(session, user_id)
            updated_paths = self._folder_payload_path_map(updated_rows)
            return {
                "previous_path": previous_paths.get(folder.id, normalized_path),
                "path": updated_paths.get(folder.id, updated_folder.folder_name),
                "folder_id": folder.id,
                "file_ids": [row.id for row in file_rows],
                "source_files": [row.file_path for row in file_rows],
                "item": self._folder_row_to_payload(
                    updated_folder,
                    updated_paths.get(folder.id, updated_folder.folder_name),
                ),
            }

    async def save_uploaded_files(
        self,
        uploads: list[UploadFile],
        folder_path: str | None = None,
        parent_id: int | None = None,
    ) -> list[str]:
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
            folder_row = self._resolve_folder_row(session, user_id, folder_path, parent_id)
            folder_id = folder_row.id if folder_row else 0

            for upload, content in prepared_uploads:
                payload = self._store_file(session, user_id, folder_id, upload, content)
                saved_paths.append(str(payload["path"]))
        return saved_paths

    def delete_document(self, path_value: str) -> dict[str, Any]:
        self._ensure_sql()
        normalized_path = self._normalize_path(path_value)
        if not normalized_path:
            raise ValueError("File path is required.")

        self._ensure_user_docs_root()
        preview_cache_path: Path | None = None
        deleted_path: str | None = None
        deleted_file_id: int | None = None

        with session_scope() as session:
            user_id = self._get_or_create_default_user_id(session)
            row = self._get_file_by_storage_path(session, user_id, normalized_path)
            if row is None:
                raise FileNotFoundError(f"File not found: {path_value}")

            deleted_file_id = row.id
            deleted = self._delete_file_row(session, row)
            deleted_path = str(deleted.get("path") or row.file_path)

        return {"path": deleted_path or normalized_path, "file_id": deleted_file_id}

    def delete_document_by_id(self, file_id: int) -> dict[str, Any]:
        self._ensure_sql()
        with session_scope() as session:
            user_id = self._get_or_create_default_user_id(session)
            row = self._get_file_by_id(session, user_id, int(file_id))
            if row is None:
                raise FileNotFoundError(f"File not found: {file_id}")
            return self._delete_file_row(session, row)

    def delete_folder(self, path_value: str) -> dict[str, Any]:
        self._ensure_sql()
        normalized_path = self._normalize_path(path_value)
        if not normalized_path:
            raise ValueError("Folder path is required.")

        self._ensure_user_docs_root()
        deleted_file_paths: list[str] = []
        deleted_file_ids: list[int] = []
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
                file_path = self._file_row_to_disk_path(file_row)
                if file_row.file_ext.lower() in {".doc", ".docx", ".ppt", ".pptx"}:
                    try:
                        preview_cache_paths.append(get_preview_pdf_cache_path(file_path))
                    except Exception:
                        pass

                session.execute(
                    text("DELETE FROM kop_document_file WHERE id = :file_id"),
                    {"file_id": file_row.id},
                )

                if file_path.exists():
                    file_path.unlink()
                deleted_file_paths.append(file_row.file_path)
                deleted_file_ids.append(file_row.id)

            for preview_cache_path in preview_cache_paths:
                if preview_cache_path.exists():
                    preview_cache_path.unlink(missing_ok=True)

            for folder_id in reversed(descendant_folder_ids):
                session.execute(
                    text("DELETE FROM kop_document_folder WHERE id = :folder_id"),
                    {"folder_id": folder_id},
                )
                shutil.rmtree(self._folder_storage_dir(user_id, folder_id), ignore_errors=True)

            deleted_folder_path = normalized_path

        return {
            "path": deleted_folder_path,
            "source_files": [deleted_folder_path, *deleted_file_paths],
            "file_ids": deleted_file_ids,
        }
