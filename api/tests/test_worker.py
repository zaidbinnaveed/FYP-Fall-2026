from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.core.config import Settings
from app.worker import loop
from app.worker.heartbeat import is_fresh, read_heartbeat, write_heartbeat


def test_heartbeat_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "hb"
    stamp = write_heartbeat(path, datetime(2026, 11, 17, 12, 0, tzinfo=UTC))
    assert path.read_text() == "2026-11-17T12:00:00.000Z"
    assert read_heartbeat(path) == stamp


def test_missing_or_corrupt_heartbeat_is_unhealthy(tmp_path: Path) -> None:
    assert not is_fresh(tmp_path / "absent", 30)
    corrupt = tmp_path / "corrupt"
    corrupt.write_text("not a timestamp")
    assert not is_fresh(corrupt, 30)


def test_stale_heartbeat_is_unhealthy(tmp_path: Path) -> None:
    path = tmp_path / "hb"
    now = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
    write_heartbeat(path, now - timedelta(seconds=31))
    assert not is_fresh(path, 30, now=now)
    write_heartbeat(path, now - timedelta(seconds=5))
    assert is_fresh(path, 30, now=now)


async def test_loop_writes_heartbeat_and_stops(
    tmp_path: Path, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "hb"
    monkeypatch.setattr(settings, "worker_heartbeat_file", str(path))
    stop = asyncio.Event()
    task = asyncio.create_task(loop.run(settings, stop))
    for _ in range(50):
        if path.exists():
            break
        await asyncio.sleep(0.02)
    stop.set()
    await asyncio.wait_for(task, timeout=2)
    assert is_fresh(path, 30)


def test_healthcheck_entrypoint_reflects_heartbeat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import get_settings
    from app.worker.__main__ import main

    path = tmp_path / "hb"
    monkeypatch.setenv("WORKER_HEARTBEAT_FILE", str(path))
    get_settings.cache_clear()
    assert main(["healthcheck"]) == 1  # no heartbeat yet
    write_heartbeat(path)
    assert main(["healthcheck"]) == 0
