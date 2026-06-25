"""Chat memory persistence layer backed by MySQL and Redis."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.core.database import DatabaseUnavailableError, session_scope
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
        row = session.execute(
            text(
                "SELECT id FROM kop_user WHERE username = :username LIMIT 1"
            ),
            {"username": settings.chat_default_username},
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
            {"username": settings.chat_default_username},
        )
        return int(result.lastrowid)

    def _get_conversation_row(self, session, conversation_id: int):
        row = session.execute(
            text(
                """
                SELECT id, user_id, title
                FROM kop_chat_conversation
                WHERE id = :conversation_id
                LIMIT 1
                """
            ),
            {"conversation_id": conversation_id},
        ).first()
        return row

    def resolve_conversation(self, conversation_id: int | None, *, title_seed: str | None = None) -> ConversationState:
        if text is None:
            raise DatabaseUnavailableError("SQLAlchemy is not installed.")

        with session_scope() as session:
            user_id = self._get_or_create_default_user_id(session)
            if conversation_id is not None:
                row = self._get_conversation_row(session, conversation_id)
                if row:
                    title = str(row[2] or "").strip()
                    if not title and title_seed:
                        title = self._build_title(title_seed)
                        session.execute(
                            text(
                                """
                                UPDATE kop_chat_conversation
                                SET title = :title, updated_at = :updated_at
                                WHERE id = :conversation_id
                                """
                            ),
                            {
                                "title": title,
                                "updated_at": self._now(),
                                "conversation_id": conversation_id,
                            },
                        )
                    return ConversationState(
                        conversation_id=int(row[0]),
                        user_id=int(row[1]),
                        title=title or self._build_title(title_seed or "Chat"),
                        created=False,
                    )

            title = self._build_title(title_seed or "Chat")
            result = session.execute(
                text(
                    """
                    INSERT INTO kop_chat_conversation
                        (user_id, title, model_name, status, last_message_at)
                    VALUES
                        (:user_id, :title, NULL, 1, :last_message_at)
                    """
                ),
                {
                    "user_id": user_id,
                    "title": title,
                    "last_message_at": self._now(),
                },
            )
            conversation_id = int(result.lastrowid)
            return ConversationState(
                conversation_id=conversation_id,
                user_id=user_id,
                title=title,
                created=True,
            )

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
        }

    def list_conversations(self, *, page: int = 1, page_size: int = 20) -> tuple[list[dict[str, Any]], bool]:
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
            preview = " ".join(str(row[7] or "").split())
            items.append(
                {
                    "id": int(row[0]),
                    "title": str(row[1] or "") or self._build_title(preview or "Chat"),
                    "model": str(row[2]) if row[2] is not None else None,
                    "last_message_at": self._to_iso(row[3]),
                    "created_at": self._to_iso(row[4]) or "",
                    "updated_at": self._to_iso(row[5]) or "",
                    "message_count": int(row[6] or 0),
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
                        role,
                        content,
                        seq_no,
                        created_at,
                        model_name,
                        citations_json,
                        meta_json
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
            citations = self._parse_json_value(row[7], [])
            if not isinstance(citations, list):
                citations = []
            normalized_citations = [
                self._normalize_citation(item, index)
                for index, item in enumerate(citations)
                if isinstance(item, dict)
            ]

            meta = self._parse_json_value(row[8], {})
            if not isinstance(meta, dict):
                meta = {}
            usage = meta.get("usage")
            if not isinstance(usage, dict):
                usage = None

            sources = [
                self._citation_to_source(citation)
                for citation in normalized_citations
            ]
            items.append(
                {
                    "id": int(row[0]),
                    "conversation_id": int(row[1]),
                    "role": str(row[2]),
                    "content": str(row[3] or ""),
                    "seq_no": int(row[4]),
                    "created_at": self._to_iso(row[5]) or "",
                    "model": str(row[6]) if row[6] is not None else None,
                    "citations": normalized_citations,
                    "sources": sources,
                    "usage": usage,
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

    def load_recent_history(self, conversation_id: int, limit: int | None = None) -> list[ChatHistoryItem]:
        limit_value = max(1, limit or settings.chat_recent_message_limit)

        cached = self._read_recent_history_cache(conversation_id)
        if cached is not None:
            return cached[-limit_value:]

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
                {"conversation_id": conversation_id, "limit_value": limit_value},
            ).all()

        history = [ChatHistoryItem(role=str(row[0]), content=str(row[1])) for row in reversed(rows)]
        if history:
            self._cache_recent_history(conversation_id, history)
        return history

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
        citations: list[dict[str, Any]] | None = None,
        usage: dict[str, Any] | None = None,
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
                        (conversation_id, role, content, seq_no, content_type, meta_json, citations_json, token_count, model_name, created_at)
                    VALUES
                        (:conversation_id, 'user', :content, :seq_no, 'text', NULL, NULL, NULL, NULL, :created_at)
                    """
                ),
                {
                    "conversation_id": conversation_id,
                    "content": question,
                    "seq_no": seq_no,
                    "created_at": now_value,
                },
            )

            seq_no += 1
            meta_json = {
                "rewritten_question": rewritten_question,
                "question_mode": question_mode,
                "usage": usage,
            }
            session.execute(
                text(
                    """
                    INSERT INTO kop_chat_message
                        (conversation_id, role, content, seq_no, content_type, meta_json, citations_json, token_count, model_name, created_at)
                    VALUES
                        (:conversation_id, 'assistant', :content, :seq_no, 'text', :meta_json, :citations_json, :token_count, :model_name, :created_at)
                    """
                ),
                {
                    "conversation_id": conversation_id,
                    "content": answer,
                    "seq_no": seq_no,
                    "meta_json": json.dumps(meta_json, ensure_ascii=False),
                    "citations_json": json.dumps(citations or [], ensure_ascii=False),
                    "token_count": int((usage or {}).get("total_tokens", 0) or 0) or None,
                    "model_name": model_name,
                    "created_at": now_value,
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
        """Reserve future summary support without blocking the first-stage rollout."""
        client = self._safe_redis()
        if client is not None:
            client.set(self._conversation_summary_key(conversation_id), "", ex=settings.chat_cache_ttl_sec)
