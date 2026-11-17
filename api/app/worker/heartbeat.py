"""Worker heartbeat.

D0 stores the heartbeat in a container-local file so Docker can check liveness. Phase D1 moves it
to the ``worker_heartbeats`` table (plan section 10, gap 7) so ``/api/v1/admin/health`` can read it.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime
from pathlib import Path

from app.core.time import to_iso_utc, utc_now


def write_heartbeat(path: str | Path, now: datetime | None = None) -> datetime:
    """Atomically write the current UTC time (ISO 8601) to ``path``."""
    stamp = now or utc_now()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".heartbeat-")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(to_iso_utc(stamp))
    os.replace(tmp, target)
    return stamp


def read_heartbeat(path: str | Path) -> datetime | None:
    try:
        raw = Path(path).read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def is_fresh(path: str | Path, max_age_seconds: float, now: datetime | None = None) -> bool:
    beat = read_heartbeat(path)
    if beat is None:
        return False
    age = ((now or utc_now()) - beat).total_seconds()
    return 0 <= age <= max_age_seconds
