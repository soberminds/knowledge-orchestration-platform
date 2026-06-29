"""Request-scoped context helpers."""

from __future__ import annotations

from contextvars import ContextVar, Token


current_user_id_var: ContextVar[int | None] = ContextVar("kop_current_user_id", default=None)


def set_current_user_id(user_id: int | None) -> Token[int | None]:
    return current_user_id_var.set(user_id)


def reset_current_user_id(token: Token[int | None]) -> None:
    current_user_id_var.reset(token)


def get_current_user_id() -> int | None:
    return current_user_id_var.get()
