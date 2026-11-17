from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.core.time import to_iso_utc, to_pkt, utc_now


def test_utc_now_is_aware_utc() -> None:
    now = utc_now()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)


def test_iso_serialization_converts_to_utc() -> None:
    karachi = timezone(timedelta(hours=5))
    value = datetime(2026, 11, 17, 17, 30, 0, tzinfo=karachi)
    assert to_iso_utc(value) == "2026-11-17T12:30:00.000Z"


def test_pkt_display_is_utc_plus_five() -> None:
    value = datetime(2026, 11, 17, 12, 30, tzinfo=UTC)
    shown = to_pkt(value)
    assert shown.hour == 17
    assert shown.utcoffset() == timedelta(hours=5)


@pytest.mark.parametrize("func", [to_iso_utc, to_pkt])
def test_naive_datetimes_rejected(func: object) -> None:
    with pytest.raises(ValueError, match="naive"):
        func(datetime(2026, 1, 1))  # type: ignore[operator]
