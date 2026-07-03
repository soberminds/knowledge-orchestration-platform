"""Authentication and current-user resolution helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime
from typing import Any

from fastapi import Request

from app.core.database import DatabaseUnavailableError, session_scope
from app.core.redis_client import RedisUnavailableError, get_redis_client
from app.core.request_context import get_current_user_id
from app.core.settings import settings
from app.core.time_utils import now_china

try:
    from sqlalchemy import text
except Exception:  # pragma: no cover - optional dependency path
    text = None  # type: ignore[assignment]


class AuthError(RuntimeError):
    """Raised when authentication or user management fails."""


class UserAuthService:
    """Minimal login/register/session service backed by MySQL and Redis."""

    SESSION_COOKIE_NAME = "kop_session"
    SESSION_TTL_SEC = 30 * 24 * 60 * 60
    SESSION_KEY_PREFIX = "kop:auth:session:"
    PASSWORD_HASH_PREFIX = "pbkdf2_sha256"
    PASSWORD_HASH_ITERATIONS = 120_000

    def __init__(self) -> None:
        self._redis_client = None

    def _ensure_sql(self) -> None:
        if text is None:
            raise DatabaseUnavailableError("SQLAlchemy is not installed.")

    def _now(self) -> datetime:
        return now_china()

    def _safe_redis(self):
        if self._redis_client is not None:
            return self._redis_client
        try:
            self._redis_client = get_redis_client()
        except (RedisUnavailableError, Exception):
            self._redis_client = False
        return None if self._redis_client is False else self._redis_client

    def _session_key(self, token: str) -> str:
        return f"{self.SESSION_KEY_PREFIX}{token}"

    def _normalize_username(self, username: str) -> str:
        value = str(username or "").strip()
        if not value:
            raise ValueError("username is required")
        if len(value) > 64:
            raise ValueError("username is too long")
        return value

    def _normalize_password(self, password: str) -> str:
        value = str(password or "")
        if len(value) < 4:
            raise ValueError("password is too short")
        if len(value) > 128:
            raise ValueError("password is too long")
        return value

    def _normalize_nickname(self, nickname: str | None) -> str | None:
        value = str(nickname or "").strip()
        return value[:128] if value else None

    def _hash_password(self, password: str, salt: bytes | None = None) -> str:
        salt_bytes = salt or secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt_bytes,
            self.PASSWORD_HASH_ITERATIONS,
        )
        salt_segment = base64.urlsafe_b64encode(salt_bytes).decode("ascii").rstrip("=")
        digest_segment = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        return f"{self.PASSWORD_HASH_PREFIX}${self.PASSWORD_HASH_ITERATIONS}${salt_segment}${digest_segment}"

    def _verify_password(self, password: str, password_hash: str | None) -> bool:
        if not password_hash:
            return False
        try:
            prefix, iterations_raw, salt_segment, digest_segment = str(password_hash).split("$", 3)
            if prefix != self.PASSWORD_HASH_PREFIX:
                return False
            iterations = int(iterations_raw)
            salt = base64.urlsafe_b64decode(salt_segment + "=" * (-len(salt_segment) % 4))
            expected = base64.urlsafe_b64decode(digest_segment + "=" * (-len(digest_segment) % 4))
        except Exception:
            return False

        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(expected, actual)

    def _get_redis(self):
        client = self._safe_redis()
        return client

    def _get_user_row(self, session, user_id: int):
        row = session.execute(
            text(
                """
                SELECT
                    id, username, password_hash, nickname, avatar_url, user_type,
                    is_default, status, last_login_at, created_at, updated_at
                FROM kop_user
                WHERE id = :user_id
                LIMIT 1
                """
            ),
            {"user_id": int(user_id)},
        ).first()
        return row

    def _get_user_row_by_username(self, session, username: str):
        row = session.execute(
            text(
                """
                SELECT
                    id, username, password_hash, nickname, avatar_url, user_type,
                    is_default, status, last_login_at, created_at, updated_at
                FROM kop_user
                WHERE username = :username
                LIMIT 1
                """
            ),
            {"username": username},
        ).first()
        return row

    def _row_to_payload(self, row, *, authenticated: bool, is_guest: bool) -> dict[str, Any]:
        return {
            "id": int(row[0]),
            "username": str(row[1]),
            "nickname": str(row[3]) if row[3] is not None else None,
            "avatar_url": str(row[4]) if row[4] is not None else None,
            "user_type": str(row[5] or "local"),
            "is_default": bool(row[6]),
            "status": int(row[7] or 0),
            "last_login_at": row[8].isoformat(timespec="seconds") if row[8] is not None else None,
            "created_at": row[9].isoformat(timespec="seconds") if row[9] is not None else None,
            "updated_at": row[10].isoformat(timespec="seconds") if row[10] is not None else None,
            "authenticated": authenticated,
            "is_guest": is_guest,
        }

    def _store_session_token(self, token: str, user_id: int) -> None:
        client = self._get_redis()
        if client is None:
            return
        client.set(self._session_key(token), str(int(user_id)), ex=self.SESSION_TTL_SEC)

    def _delete_session_token(self, token: str) -> None:
        client = self._get_redis()
        if client is None:
            return
        client.delete(self._session_key(token))

    def _resolve_session_user_id(self, token: str | None) -> int | None:
        token_value = str(token or "").strip()
        if not token_value:
            return None
        client = self._get_redis()
        if client is None:
            return None
        try:
            raw_user_id = client.get(self._session_key(token_value))
        except Exception:
            return None
        if raw_user_id is None:
            return None
        try:
            return int(raw_user_id)
        except Exception:
            return None

    def _resolve_guest_user_id(self, session) -> int:
        row = self._get_user_row_by_username(session, settings.chat_default_username)
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

    def _resolve_effective_user_id(self, session, token: str | None) -> int:
        current_context_user_id = get_current_user_id()
        if current_context_user_id is not None:
            row = self._get_user_row(session, int(current_context_user_id))
            if row is not None and int(row[7] or 0) == 1:
                return int(row[0])

        session_user_id = self._resolve_session_user_id(token)
        if session_user_id is not None:
            row = self._get_user_row(session, session_user_id)
            if row is not None and int(row[7] or 0) == 1:
                return int(row[0])

        return self._resolve_guest_user_id(session)

    def resolve_current_user(self, request: Request) -> dict[str, Any]:
        self._ensure_sql()
        token = request.cookies.get(self.SESSION_COOKIE_NAME) or request.headers.get("Authorization")
        if token and str(token).lower().startswith("bearer "):
            token = str(token)[7:].strip()
        with session_scope() as session:
            effective_user_id = self._resolve_effective_user_id(session, str(token or ""))
            row = self._get_user_row(session, effective_user_id)
            if row is None:
                raise AuthError("Unable to resolve current user.")
            is_guest = str(row[1]) == settings.chat_default_username
            return self._row_to_payload(row, authenticated=not is_guest, is_guest=is_guest)

    def resolve_effective_user_id_from_request(self, request: Request) -> int:
        self._ensure_sql()
        token = request.cookies.get(self.SESSION_COOKIE_NAME) or request.headers.get("Authorization")
        if token and str(token).lower().startswith("bearer "):
            token = str(token)[7:].strip()
        with session_scope() as session:
            return self._resolve_effective_user_id(session, str(token or ""))

    def get_guest_user(self) -> dict[str, Any]:
        self._ensure_sql()
        with session_scope() as session:
            user_id = self._resolve_guest_user_id(session)
            row = self._get_user_row(session, user_id)
            if row is None:
                raise AuthError("Guest user could not be loaded.")
            return self._row_to_payload(row, authenticated=False, is_guest=True)

    def login(self, username: str, password: str) -> dict[str, Any]:
        self._ensure_sql()
        safe_username = self._normalize_username(username)
        safe_password = self._normalize_password(password)

        with session_scope() as session:
            row = self._get_user_row_by_username(session, safe_username)
            if row is None or int(row[7] or 0) != 1:
                raise AuthError("用户名或密码错误。")
            if not self._verify_password(safe_password, str(row[2]) if row[2] is not None else None):
                raise AuthError("用户名或密码错误。")

            now_value = self._now()
            session.execute(
                text(
                    """
                    UPDATE kop_user
                    SET last_login_at = :last_login_at,
                        updated_at = :updated_at
                    WHERE id = :user_id
                    """
                ),
                {
                    "user_id": int(row[0]),
                    "last_login_at": now_value,
                    "updated_at": now_value,
                },
            )

            token = secrets.token_urlsafe(32)
            self._store_session_token(token, int(row[0]))
            payload = self._row_to_payload(row, authenticated=True, is_guest=False)
            payload["session_token"] = token
            return payload

    def register(self, username: str, password: str, nickname: str | None = None) -> dict[str, Any]:
        self._ensure_sql()
        safe_username = self._normalize_username(username)
        safe_password = self._normalize_password(password)
        safe_nickname = self._normalize_nickname(nickname)

        with session_scope() as session:
            existing = self._get_user_row_by_username(session, safe_username)
            if existing is not None:
                raise AuthError("用户名已存在。")

            now_value = self._now()
            password_hash = self._hash_password(safe_password)
            result = session.execute(
                text(
                    """
                    INSERT INTO kop_user
                        (username, password_hash, nickname, avatar_url, user_type, is_default, status, last_login_at, created_at, updated_at)
                    VALUES
                        (:username, :password_hash, :nickname, NULL, 'registered', 0, 1, :last_login_at, :created_at, :updated_at)
                    """
                ),
                {
                    "username": safe_username,
                    "password_hash": password_hash,
                    "nickname": safe_nickname,
                    "last_login_at": now_value,
                    "created_at": now_value,
                    "updated_at": now_value,
                },
            )
            user_id = int(result.lastrowid)
            row = self._get_user_row(session, user_id)
            if row is None:
                raise AuthError("注册成功但无法读取用户信息。")

            token = secrets.token_urlsafe(32)
            self._store_session_token(token, user_id)
            payload = self._row_to_payload(row, authenticated=True, is_guest=False)
            payload["session_token"] = token
            return payload

    def logout(self, token: str | None) -> None:
        if not token:
            return
        self._delete_session_token(token)
