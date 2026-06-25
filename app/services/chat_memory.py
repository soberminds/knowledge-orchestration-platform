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
