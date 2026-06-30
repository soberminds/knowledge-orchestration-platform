"""Chat memory persistence layer backed by MySQL and Redis."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.core.database import DatabaseUnavailableError, session_scope
from app.core.request_context import get_current_user_id
from app.core.redis_client import RedisUnavailableError, get_redis_client
from app.core.settings import settings
from app.schemas import ChatHistoryItem

try:
    from sqlalchemy import text
except Exception:  # pragma: no cover - optional dependency path
    text = None  # type: ignore[assignment]


@dataclass(frozen=True)
class ConversationState:
    conversation_id: int
    user_id: int
    title: str
    workspace_key: str | None
    scope_type: str
    scope_id: int
    created: bool = False


class ChatMemoryService:
    """Persist chat messages and load recent context."""

    def __init__(self) -> None:
        self._redis_client = None

    def _now(self) -> datetime:
        return datetime.now()

    def _safe_redis(self):
        if self._redis_client is not None:
            return self._redis_client
        try:
            self._redis_client = get_redis_client()
        except (RedisUnavailableError, Exception):
            self._redis_client = False
        return None if self._redis_client is False else self._redis_client

    def _conversation_cache_key(self, conversation_id: int) -> str:
        return f"chat:conversation:{conversation_id}:recent"

    def _conversation_summary_key(self, conversation_id: int) -> str:
        return f"chat:conversation:{conversation_id}:summary"

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
            {"username": settings.chat_default_username},
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
                "username": settings.chat_default_username,
                "created_at": self._now(),
                "updated_at": self._now(),
            },
        )
        return int(result.lastrowid)

    def _normalize_scope_type(self, scope_type: str | None) -> str:
        token = str(scope_type or "all").strip().lower()
        if token not in {"all", "folder", "kb", "workspace"}:
            return "all"
        return token

    def _normalize_scope_id(self, scope_id: int | None) -> int:
        try:
            value = int(scope_id or 0)
        except Exception:
            return 0
        return max(0, value)

    def _normalize_workspace_key(self, workspace_key: str | None) -> str | None:
        value = str(workspace_key or "").strip()
        return value or None

    def _resolve_scope_name(
        self,
        session,
        *,
        scope_type: str,
        scope_id: int,
        workspace_key: str | None,
    ) -> str | None:
        normalized_scope_type = self._normalize_scope_type(scope_type)
        normalized_scope_id = self._normalize_scope_id(scope_id)
        normalized_workspace_key = self._normalize_workspace_key(workspace_key)

        if normalized_scope_type == "all":
            return "全部范围"

        if normalized_scope_type == "workspace":
            if normalized_workspace_key:
                row = session.execute(
                    text(
                        """
                        SELECT workspace_name
                        FROM kop_workspace
                        WHERE workspace_key = :workspace_key
                          AND status = 1
                        LIMIT 1
                        """
                    ),
                    {"workspace_key": normalized_workspace_key},
                ).first()
                if row and row[0]:
                    return "工作区 / " + str(row[0])
            if normalized_workspace_key:
                return "工作区 / " + normalized_workspace_key
            return "工作区"

        if normalized_scope_type == "kb" and normalized_scope_id:
            row = session.execute(
                text(
                    """
                    SELECT k.kb_name, w.workspace_name, w.workspace_key
                    FROM kop_kb k
                    LEFT JOIN kop_workspace w ON w.id = k.workspace_id
                    WHERE k.id = :kb_id
                      AND k.is_deleted = 0
                    LIMIT 1
                    """
                ),
                {"kb_id": normalized_scope_id},
            ).first()
            if row:
                kb_name = str(row[0]) if row[0] is not None else ""
                workspace_name = str(row[1]) if row[1] is not None else ""
                workspace_key_value = str(row[2]) if row[2] is not None else ""
                if workspace_name and kb_name:
                    return workspace_name + " / " + kb_name
                if workspace_name:
                    return workspace_name
                if kb_name:
                    return kb_name
                if workspace_key_value:
                    return workspace_key_value
            return "知识库 #" + str(normalized_scope_id)

        if normalized_scope_type == "folder" and normalized_scope_id:
            row = session.execute(
                text(
                    """
                    WITH RECURSIVE folder_chain AS (
                        SELECT
                            id,
                            parent_id,
                            folder_name,
                            CAST(folder_name AS CHAR(1024)) AS full_path
                        FROM kop_document_folder
                        WHERE id = :folder_id
                          AND is_deleted = 0
                        UNION ALL
                        SELECT
                            p.id,
                            p.parent_id,
                            p.folder_name,
                            CONCAT(p.folder_name, '/', fc.full_path)
                        FROM kop_document_folder p
                        INNER JOIN folder_chain fc ON fc.parent_id = p.id
                        WHERE p.is_deleted = 0
                    )
                    SELECT full_path
                    FROM folder_chain
                    WHERE id = :folder_id
                    LIMIT 1
                    """
                ),
                {"folder_id": normalized_scope_id},
            ).first()
            if row and row[0]:
                return "文件夹 / " + str(row[0])
            return "文件夹 #" + str(normalized_scope_id)

        return None

    def _get_conversation_row(self, session, conversation_id: int):
        current_user_id = get_current_user_id()
        row = session.execute(
            text(
                """
                SELECT id, user_id, title, workspace_key, scope_type, scope_id, status
                FROM kop_chat_conversation
                WHERE id = :conversation_id
                  AND (:current_user_id IS NULL OR user_id = :current_user_id)
                LIMIT 1
                """
            ),
            {"conversation_id": conversation_id, "current_user_id": current_user_id},
        ).first()
        return row

    def _conversation_to_state(self, row, *, created: bool = False, fallback_title: str | None = None) -> ConversationState:
        title = str(row[2] or "").strip() if row[2] is not None else ""
        if not title:
            title = self._build_title(fallback_title or "Chat")
        return ConversationState(
            conversation_id=int(row[0]),
            user_id=int(row[1]),
            title=title,
            workspace_key=str(row[3]) if row[3] is not None else None,
            scope_type=self._normalize_scope_type(row[4]),
            scope_id=self._normalize_scope_id(row[5]),
            created=created,
        )

    def resolve_conversation(
        self,
        conversation_id: int | None,
        *,
        title_seed: str | None = None,
        scope_type: str | None = None,
        scope_id: int | None = None,
        workspace_key: str | None = None,
    ) -> ConversationState:
        if text is None:
            raise DatabaseUnavailableError("SQLAlchemy is not installed.")

        with session_scope() as session:
            user_id = self._get_or_create_default_user_id(session)
            normalized_scope_type = self._normalize_scope_type(scope_type)
            normalized_scope_id = self._normalize_scope_id(scope_id)
            normalized_workspace_key = self._normalize_workspace_key(workspace_key)

            if conversation_id is not None:
                row = self._get_conversation_row(session, conversation_id)
                if row:
                    row_workspace_key = str(row[3]) if row[3] is not None else None
                    row_scope_type = self._normalize_scope_type(row[4])
                    row_scope_id = self._normalize_scope_id(row[5])
                    if (
                        row_workspace_key != normalized_workspace_key
                        or row_scope_type != normalized_scope_type
                        or row_scope_id != normalized_scope_id
                    ):
                        session.execute(
                            text(
                                """
                                UPDATE kop_chat_conversation
                                SET workspace_key = :workspace_key,
                                    scope_type = :scope_type,
                                    scope_id = :scope_id,
                                    updated_at = :updated_at
                                WHERE id = :conversation_id
                                """
                            ),
                            {
                                "workspace_key": normalized_workspace_key,
                                "scope_type": normalized_scope_type,
                                "scope_id": normalized_scope_id,
                                "updated_at": self._now(),
                                "conversation_id": conversation_id,
                            },
                        )
                        row = self._get_conversation_row(session, conversation_id) or row
                    title = str(row[2] or "").strip()
                    if not title and title_seed:
                        title = self._build_title(title_seed)
                        session.execute(
                            text(
                                """
                                UPDATE kop_chat_conversation
                                SET title = :title,
                                    updated_at = :updated_at
                                WHERE id = :conversation_id
                                """
                            ),
                            {
                                "title": title,
                                "updated_at": self._now(),
                                "conversation_id": conversation_id,
                            },
                        )
                        row = self._get_conversation_row(session, conversation_id) or row
                    return self._conversation_to_state(row, fallback_title=title_seed or "Chat")

            title = self._build_title(title_seed or "Chat")
            now_value = self._now()
            result = session.execute(
                text(
                    """
                    INSERT INTO kop_chat_conversation
                        (user_id, title, workspace_key, model_name, scope_type, scope_id, summary, summary_updated_at, status, last_message_at, created_at, updated_at)
                    VALUES
                        (:user_id, :title, :workspace_key, NULL, :scope_type, :scope_id, NULL, NULL, 1, :last_message_at, :created_at, :updated_at)
                    """
                ),
                {
                    "user_id": user_id,
                    "title": title,
                    "workspace_key": normalized_workspace_key,
                    "scope_type": normalized_scope_type,
                    "scope_id": normalized_scope_id,
                    "last_message_at": now_value,
                    "created_at": now_value,
                    "updated_at": now_value,
                },
            )
            conversation_id = int(result.lastrowid)
            row = self._get_conversation_row(session, conversation_id)
            if row is None:
                raise RuntimeError("Conversation created but could not be reloaded.")
            return self._conversation_to_state(row, created=True, fallback_title=title)

    def _build_title(self, text_value: str) -> str:
        text_value = " ".join((text_value or "").split()).strip()
        if not text_value:
            return "Chat"
        return text_value[:32] if len(text_value) > 32 else text_value

    def _to_iso(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.isoformat(timespec="seconds")
        return str(value)

    def _parse_json_value(self, value: Any, fallback: Any) -> Any:
        if value is None:
            return fallback
        if isinstance(value, (dict, list)):
            return value
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="ignore")
        if not isinstance(value, str) or not value.strip():
            return fallback
        try:
            return json.loads(value)
        except Exception:
            return fallback

    def _normalize_citation(self, citation: dict[str, Any], index: int) -> dict[str, Any]:
        chunk_indices = citation.get("chunk_indices") or []
        if not isinstance(chunk_indices, list):
            chunk_indices = []
        normalized_chunk_indices: list[int] = []
        for value in chunk_indices:
            try:
                normalized_chunk_indices.append(int(value))
            except Exception:
                continue

        page = citation.get("page")
        try:
            page = int(page) if page is not None else None
        except Exception:
            page = None

        score = citation.get("score")
        try:
            score = float(score) if score is not None else None
        except Exception:
            score = None

        return {
            "label": str(citation.get("label") or f"S{index + 1}"),
            "source": str(citation.get("source") or "unknown"),
            "page": page,
            "chunk_indices": normalized_chunk_indices,
            "score": score,
            "preview": str(citation.get("preview") or ""),
            "file_id": citation.get("file_id"),
            "folder_id": citation.get("folder_id"),
            "display_name": citation.get("display_name"),
            "display_path": citation.get("display_path"),
            "folder_path": citation.get("folder_path"),
        }

    def _citation_to_source(self, citation: dict[str, Any]) -> dict[str, Any]:
        chunk_indices = citation.get("chunk_indices") or []
        chunk_index = 0
        if isinstance(chunk_indices, list) and chunk_indices:
            try:
                chunk_index = int(chunk_indices[0])
            except Exception:
                chunk_index = 0
        return {
            "source": str(citation.get("source") or "unknown"),
            "chunk_index": chunk_index,
            "page": citation.get("page"),
            "score": citation.get("score"),
            "preview": str(citation.get("preview") or ""),
            "file_id": citation.get("file_id"),
            "folder_id": citation.get("folder_id"),
            "display_name": citation.get("display_name"),
            "display_path": citation.get("display_path"),
            "folder_path": citation.get("folder_path"),
        }

    def list_conversations(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], bool]:
        if text is None:
            raise DatabaseUnavailableError("SQLAlchemy is not installed.")

        page_value = max(1, int(page or 1))
        page_size_value = max(1, min(50, int(page_size or 20)))
        offset = (page_value - 1) * page_size_value

        with session_scope() as session:
            user_id = self._get_or_create_default_user_id(session)
            rows = session.execute(
                text(
                    """
                    SELECT
                        c.id,
                        c.title,
                        c.workspace_key,
                        c.scope_type,
                        c.scope_id,
                        c.model_name,
                        c.last_message_at,
                        c.created_at,
                        c.updated_at,
                        (
                            SELECT COUNT(*)
                            FROM kop_chat_message m
                            WHERE m.conversation_id = c.id
                        ) AS message_count,
                        (
                            SELECT m.content
                            FROM kop_chat_message m
                            WHERE m.conversation_id = c.id
                            ORDER BY m.seq_no DESC
                            LIMIT 1
                        ) AS preview
                    FROM kop_chat_conversation c
                    WHERE c.user_id = :user_id
                      AND c.status = 1
                    ORDER BY COALESCE(c.last_message_at, c.updated_at, c.created_at) DESC, c.id DESC
                    LIMIT :limit_value
                    OFFSET :offset_value
                    """
                ),
                {
                    "user_id": user_id,
                    "limit_value": page_size_value + 1,
                    "offset_value": offset,
                },
            ).all()

            has_more = len(rows) > page_size_value
            items: list[dict[str, Any]] = []
            for row in rows[:page_size_value]:
                preview = " ".join(str(row[10] or "").split())
                scope_name = self._resolve_scope_name(
                    session,
                    scope_type=str(row[3] or "all"),
                    scope_id=int(row[4] or 0),
                    workspace_key=str(row[2]) if row[2] is not None else None,
                )
                items.append(
                    {
                        "id": int(row[0]),
                        "title": str(row[1] or "") or self._build_title(preview or "Chat"),
                        "workspace_key": str(row[2]) if row[2] is not None else None,
                        "scope_type": self._normalize_scope_type(row[3]),
                        "scope_id": int(row[4] or 0),
                        "scope_name": scope_name,
                        "model": str(row[5]) if row[5] is not None else None,
                        "last_message_at": self._to_iso(row[6]),
                        "created_at": self._to_iso(row[7]) or "",
                        "updated_at": self._to_iso(row[8]) or "",
                        "message_count": int(row[9] or 0),
                        "preview": preview[:160],
                    }
                )
            return items, has_more
    def list_messages(
        self,
        conversation_id: int,
        *,
        limit: int = 30,
        before_seq_no: int | None = None,
    ) -> tuple[list[dict[str, Any]], bool]:
        if text is None:
            raise DatabaseUnavailableError("SQLAlchemy is not installed.")

        limit_value = max(1, min(100, int(limit or 30)))
        with session_scope() as session:
            user_id = self._get_or_create_default_user_id(session)
            conversation_row = session.execute(
                text(
                    """
                    SELECT id
                    FROM kop_chat_conversation
                    WHERE id = :conversation_id
                      AND user_id = :user_id
                      AND status = 1
                    LIMIT 1
                    """
                ),
                {"conversation_id": conversation_id, "user_id": user_id},
            ).first()
            if not conversation_row:
                raise DatabaseUnavailableError(f"Conversation {conversation_id} does not exist for current user.")

            params: dict[str, Any] = {
                "conversation_id": conversation_id,
                "limit_value": limit_value + 1,
            }
            where_extra = ""
            if before_seq_no is not None:
                where_extra = "AND seq_no < :before_seq_no"
                params["before_seq_no"] = int(before_seq_no)

            rows = session.execute(
                text(
                    f"""
                    SELECT
                        id,
                        conversation_id,
                        sender_user_id,
                        role,
                        content,
                        seq_no,
                        created_at,
                        meta_json,
                        citations_json,
                        token_count
                    FROM kop_chat_message
                    WHERE conversation_id = :conversation_id
                      AND role IN ('system', 'user', 'assistant', 'tool')
                      {where_extra}
                    ORDER BY seq_no DESC
                    LIMIT :limit_value
                    """
                ),
                params,
            ).all()

        has_more = len(rows) > limit_value
        display_rows = list(reversed(rows[:limit_value]))
        items: list[dict[str, Any]] = []
        for row in display_rows:
            citations = self._parse_json_value(row[8], [])
            if not isinstance(citations, list):
                citations = []
            normalized_citations = [
                self._normalize_citation(item, index)
                for index, item in enumerate(citations)
                if isinstance(item, dict)
            ]

            meta = self._parse_json_value(row[7], {})
            if not isinstance(meta, dict):
                meta = {}
            usage = meta.get("usage")
            if not isinstance(usage, dict):
                usage = None
            model_diagnostics = meta.get("model_diagnostics")
            if not isinstance(model_diagnostics, dict):
                model_diagnostics = None
            message_parts = meta.get("message_parts")
            if not isinstance(message_parts, list):
                message_parts = []
            reasoning_parts = meta.get("reasoning_parts")
            if not isinstance(reasoning_parts, list):
                reasoning_parts = []

            sources = [self._citation_to_source(citation) for citation in normalized_citations]
            items.append(
                {
                    "id": int(row[0]),
                    "conversation_id": int(row[1]),
                    "sender_user_id": int(row[2]) if row[2] is not None else None,
                    "role": str(row[3]),
                    "content": str(row[4] or ""),
                    "message_parts": [item for item in message_parts if isinstance(item, dict)],
                    "seq_no": int(row[5]),
                    "created_at": self._to_iso(row[6]) or "",
                    "model": str(meta.get("model") or "") or None,
                    "citations": normalized_citations,
                    "sources": sources,
                    "usage": usage,
                    "model_diagnostics": model_diagnostics,
                    "reasoning_parts": [str(item) for item in reasoning_parts if str(item).strip()],
                }
            )
        return items, has_more

    def _cache_recent_history(self, conversation_id: int, history: list[ChatHistoryItem]) -> None:
        client = self._safe_redis()
        if client is None:
            return
        payload = json.dumps([item.model_dump() for item in history], ensure_ascii=False)
        client.set(self._conversation_cache_key(conversation_id), payload, ex=settings.chat_cache_ttl_sec)

    def _delete_recent_history_cache(self, conversation_id: int) -> None:
        client = self._safe_redis()
        if client is None:
            return
        client.delete(self._conversation_cache_key(conversation_id))

    def _read_recent_history_cache(self, conversation_id: int) -> list[ChatHistoryItem] | None:
        client = self._safe_redis()
        if client is None:
            return None
        raw = client.get(self._conversation_cache_key(conversation_id))
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
        except Exception:
            return None
        if not isinstance(parsed, list):
            return None
        history: list[ChatHistoryItem] = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            try:
                history.append(ChatHistoryItem(**item))
            except Exception:
                continue
        return history or None

    def _load_conversation_history_from_db(self, conversation_id: int, limit: int) -> list[ChatHistoryItem]:
        if text is None:
            raise DatabaseUnavailableError("SQLAlchemy is not installed.")

        with session_scope() as session:
            rows = session.execute(
                text(
                    """
                    SELECT role, content
                    FROM kop_chat_message
                    WHERE conversation_id = :conversation_id
                      AND role IN ('system', 'user', 'assistant')
                    ORDER BY seq_no DESC
                    LIMIT :limit_value
                    """
                ),
                {"conversation_id": conversation_id, "limit_value": limit},
            ).all()

        history = [ChatHistoryItem(role=str(row[0]), content=str(row[1])) for row in reversed(rows)]
        if history:
            self._cache_recent_history(conversation_id, history)
        return history

    def load_recent_history(self, conversation_id: int, limit: int | None = None) -> list[ChatHistoryItem]:
        limit_value = max(1, limit or settings.chat_recent_message_limit)
        cached = self._read_recent_history_cache(conversation_id)
        if cached is not None:
            return cached[-limit_value:]
        return self._load_conversation_history_from_db(conversation_id, limit_value)

    def resolve_history(
        self,
        conversation_id: int | None,
        request_history: list[ChatHistoryItem] | None,
    ) -> list[ChatHistoryItem]:
        if conversation_id is None:
            return list(request_history or [])

        try:
            history = self.load_recent_history(conversation_id)
            if history:
                return history
        except Exception:
            pass
        return list(request_history or [])

    def save_turn(
        self,
        *,
        conversation_id: int,
        question: str,
        answer: str,
        model_name: str | None,
        message_parts: list[dict[str, Any]] | None = None,
        citations: list[dict[str, Any]] | None = None,
        usage: dict[str, Any] | None = None,
        model_diagnostics: dict[str, Any] | None = None,
        reasoning_parts: list[str] | None = None,
        rewritten_question: str | None = None,
        question_mode: str | None = None,
    ) -> None:
        if text is None:
            raise DatabaseUnavailableError("SQLAlchemy is not installed.")

        question = question.strip()
        answer = answer.strip()
        if not question and not answer:
            return

        with session_scope() as session:
            conversation_row = self._get_conversation_row(session, conversation_id)
            if not conversation_row:
                raise DatabaseUnavailableError(f"Conversation {conversation_id} does not exist.")

            user_id = self._get_or_create_default_user_id(session)
            next_seq_row = session.execute(
                text(
                    """
                    SELECT COALESCE(MAX(seq_no), 0)
                    FROM kop_chat_message
                    WHERE conversation_id = :conversation_id
                    """
                ),
                {"conversation_id": conversation_id},
            ).first()
            seq_no = int(next_seq_row[0] or 0)
            now_value = self._now()

            seq_no += 1
            session.execute(
                text(
                    """
                    INSERT INTO kop_chat_message
                        (conversation_id, sender_user_id, role, content, seq_no, meta_json, citations_json, token_count, created_at, updated_at)
                    VALUES
                        (:conversation_id, :sender_user_id, 'user', :content, :seq_no, :meta_json, NULL, NULL, :created_at, :updated_at)
                    """
                ),
                {
                    "conversation_id": conversation_id,
                    "sender_user_id": user_id,
                    "content": question,
                    "seq_no": seq_no,
                    "meta_json": json.dumps({"message_parts": message_parts or []}, ensure_ascii=False)
                    if message_parts
                    else None,
                    "created_at": now_value,
                    "updated_at": now_value,
                },
            )

            seq_no += 1
            meta_json = {
                "rewritten_question": rewritten_question,
                "question_mode": question_mode,
                "usage": usage,
                "model_diagnostics": model_diagnostics,
                "reasoning_parts": [str(item) for item in (reasoning_parts or []) if str(item).strip()],
                "model": model_name,
            }
            session.execute(
                text(
                    """
                    INSERT INTO kop_chat_message
                        (conversation_id, sender_user_id, role, content, seq_no, meta_json, citations_json, token_count, created_at, updated_at)
                    VALUES
                        (:conversation_id, :sender_user_id, 'assistant', :content, :seq_no, :meta_json, :citations_json, :token_count, :created_at, :updated_at)
                    """
                ),
                {
                    "conversation_id": conversation_id,
                    "sender_user_id": user_id,
                    "content": answer,
                    "seq_no": seq_no,
                    "meta_json": json.dumps(meta_json, ensure_ascii=False),
                    "citations_json": json.dumps(citations or [], ensure_ascii=False),
                    "token_count": int((usage or {}).get("total_tokens", 0) or 0) or None,
                    "created_at": now_value,
                    "updated_at": now_value,
                },
            )

            session.execute(
                text(
                    """
                    UPDATE kop_chat_conversation
                    SET last_message_at = :last_message_at,
                        model_name = COALESCE(:model_name, model_name),
                        updated_at = :updated_at
                    WHERE id = :conversation_id
                    """
                ),
                {
                    "last_message_at": now_value,
                    "updated_at": now_value,
                    "model_name": model_name,
                    "conversation_id": conversation_id,
                },
            )

        self._delete_recent_history_cache(conversation_id)
        self._cache_recent_history(conversation_id, self.load_recent_history(conversation_id))

    def summarize_placeholder(self, conversation_id: int) -> None:
        client = self._safe_redis()
        if client is not None:
            client.set(self._conversation_summary_key(conversation_id), "", ex=settings.chat_cache_ttl_sec)
