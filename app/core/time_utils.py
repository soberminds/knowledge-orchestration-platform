"""Application time helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - Python without zoneinfo.
    ZoneInfo = None  # type: ignore[assignment]


def _china_timezone():
    if ZoneInfo is not None:
        try:
            return ZoneInfo("Asia/Shanghai")
        except Exception:
            pass
    return timezone(timedelta(hours=8), name="CST")


CHINA_TIME_ZONE = _china_timezone()


def now_china() -> datetime:
    """Return a naive datetime representing current China local time."""
    return datetime.now(CHINA_TIME_ZONE).replace(tzinfo=None)


def now_china_iso() -> str:
    return now_china().isoformat(timespec="seconds")


def timestamp_to_china_iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=CHINA_TIME_ZONE).replace(tzinfo=None).isoformat(timespec="seconds")
