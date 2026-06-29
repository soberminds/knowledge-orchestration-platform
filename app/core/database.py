"""Database connection helpers for chat persistence."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator
from urllib.parse import quote_plus

from app.core.settings import settings

try:  # Keep the app importable before optional DB dependencies are installed.
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import Session, sessionmaker
except Exception:  # pragma: no cover - depends on local optional packages
    create_engine = None
    text = None
    Engine = object  # type: ignore[assignment]
    Session = object  # type: ignore[assignment]
    sessionmaker = None


class DatabaseUnavailableError(RuntimeError):
    """Raised when chat persistence cannot use MySQL."""


_engine: Engine | None = None
_session_factory = None


def build_mysql_url() -> str:
    if settings.mysql_url:
        return settings.mysql_url

    user = quote_plus(settings.mysql_user)
    password = quote_plus(settings.mysql_password)
    host = settings.mysql_host or "127.0.0.1"
    database = quote_plus(settings.mysql_database or "KOP")
    charset = settings.mysql_charset or "utf8mb4"
    return f"mysql+pymysql://{user}:{password}@{host}:{settings.mysql_port}/{database}?charset={charset}"


def get_engine():
    global _engine, _session_factory
    if create_engine is None or sessionmaker is None:
        raise DatabaseUnavailableError("SQLAlchemy/PyMySQL is not installed. Run: python -m pip install -r requirements.txt")

    if _engine is None:
        _engine = create_engine(
            build_mysql_url(),
            connect_args={
                "connect_timeout": settings.mysql_connect_timeout_sec,
                "read_timeout": settings.mysql_read_timeout_sec,
                "write_timeout": settings.mysql_write_timeout_sec,
            },
            pool_pre_ping=True,
            pool_recycle=1800,
            future=True,
        )
        _session_factory = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)
    return _engine


@contextmanager
def session_scope() -> Iterator[Session]:
    get_engine()
    if _session_factory is None:
        raise DatabaseUnavailableError("Database session factory is not initialized.")

    session = _session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_database() -> bool:
    if text is None:
        raise DatabaseUnavailableError("SQLAlchemy is not installed.")
    with session_scope() as session:
        session.execute(text("SELECT 1"))
    return True
