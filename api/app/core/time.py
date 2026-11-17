"""Time helpers. Timestamps are stored and exchanged in UTC (ISO 8601) and shown in PKT."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

PKT = timezone(timedelta(hours=5), name="PKT")


def utc_now() -> datetime:
    """Current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)


def to_iso_utc(value: datetime) -> str:
    """Serialize as ISO 8601 in UTC with a ``Z`` suffix. Naive datetimes are rejected."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("naive datetimes are not allowed; attach a timezone first")
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def to_pkt(value: datetime) -> datetime:
    """Convert an aware datetime to Pakistan Standard Time for display."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("naive datetimes are not allowed; attach a timezone first")
    return value.astimezone(PKT)
