"""Agent tool confirmation queue and executors."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import RLock
from typing import Any, Callable, Literal

from app.core.request_context import get_current_user_id


ConfirmationStatus = Literal["pending", "running", "confirmed", "cancelled", "expired", "failed"]
ToolExecutor = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass
class ToolConfirmation:
    """One pending Agent tool action awaiting user confirmation."""

    confirmation_id: str
    user_id: int | None
    tool_name: str
    display_name: str
    arguments: dict[str, Any]
    message: str
    status: ConfirmationStatus
    created_at: datetime
    expires_at: datetime
    result: dict[str, Any] | None = None
    error: str | None = None
    confirmed_at: datetime | None = None
    cancelled_at: datetime | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "confirmation_id": self.confirmation_id,
            "user_id": self.user_id,
            "tool_name": self.tool_name,
            "display_name": self.display_name,
            "arguments": self.arguments,
            "message": self.message,
            "status": self.status,
            "created_at": self.created_at.isoformat(timespec="seconds"),
            "expires_at": self.expires_at.isoformat(timespec="seconds"),
            "result": self.result,
            "error": self.error,
            "confirmed_at": self.confirmed_at.isoformat(timespec="seconds") if self.confirmed_at else None,
            "cancelled_at": self.cancelled_at.isoformat(timespec="seconds") if self.cancelled_at else None,
        }


class AgentToolConfirmationService:
    """In-process confirmation store for Agent write/dangerous tools.

    This is intentionally small for the current quick core version. The public
    API shape matches the future MySQL-backed table, so persistence can be
    swapped in later without changing tool specs or frontend contracts.
    """

    def __init__(self, ttl_minutes: int = 30) -> None:
        self._ttl = timedelta(minutes=ttl_minutes)
        self._items: dict[str, ToolConfirmation] = {}
        self._executors: dict[str, ToolExecutor] = {}
        self._lock = RLock()

    def register_executor(self, tool_name: str, executor: ToolExecutor) -> None:
        with self._lock:
            self._executors[tool_name] = executor

    def create(
        self,
        *,
        tool_name: str,
        display_name: str,
        arguments: dict[str, Any],
        message: str,
        user_id: int | None = None,
    ) -> ToolConfirmation:
        now_value = datetime.now()
        confirmation = ToolConfirmation(
            confirmation_id=f"confirm_{uuid.uuid4().hex}",
            user_id=user_id if user_id is not None else get_current_user_id(),
            tool_name=tool_name,
            display_name=display_name,
            arguments=dict(arguments or {}),
            message=message,
            status="pending",
            created_at=now_value,
            expires_at=now_value + self._ttl,
        )
        with self._lock:
            self._items[confirmation.confirmation_id] = confirmation
        return confirmation

    def get(self, confirmation_id: str) -> ToolConfirmation | None:
        with self._lock:
            item = self._items.get(confirmation_id)
            if item is not None and item.status == "pending" and item.expires_at < datetime.now():
                item.status = "expired"
                item.error = "Confirmation expired."
            return item

    def cancel(self, confirmation_id: str, *, user_id: int | None = None) -> ToolConfirmation:
        item = self._require_pending_for_user(confirmation_id, user_id=user_id)
        with self._lock:
            item.status = "cancelled"
            item.cancelled_at = datetime.now()
        return item

    def confirm(self, confirmation_id: str, *, user_id: int | None = None) -> ToolConfirmation:
        item = self._require_pending_for_user(confirmation_id, user_id=user_id)
        with self._lock:
            executor = self._executors.get(item.tool_name)
        if executor is None:
            with self._lock:
                item.status = "failed"
                item.error = f"No executor registered for tool: {item.tool_name}"
            return item

        with self._lock:
            item.status = "running"
        try:
            result = executor(dict(item.arguments or {}))
        except Exception as exc:
            with self._lock:
                item.status = "failed"
                item.error = str(exc)
            return item

        with self._lock:
            item.status = "confirmed"
            item.confirmed_at = datetime.now()
            item.result = result
        return item

    def _require_pending_for_user(self, confirmation_id: str, *, user_id: int | None = None) -> ToolConfirmation:
        item = self.get(confirmation_id)
        if item is None:
            raise KeyError(f"Confirmation not found: {confirmation_id}")
        if user_id is not None and item.user_id is not None and item.user_id != user_id:
            raise PermissionError("Confirmation does not belong to current user.")
        if item.status != "pending":
            raise ValueError(f"Confirmation is not pending: {item.status}")
        return item
