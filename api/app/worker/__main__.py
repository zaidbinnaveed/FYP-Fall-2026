"""Entry point: ``python -m app.worker`` (run) or ``python -m app.worker healthcheck``."""

from __future__ import annotations

import asyncio
import sys

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.worker.heartbeat import is_fresh
from app.worker.loop import HEARTBEAT_INTERVAL_SECONDS, run


def main(argv: list[str]) -> int:
    settings = get_settings()
    if argv[:1] == ["healthcheck"]:
        healthy = is_fresh(settings.worker_heartbeat_file, 3 * HEARTBEAT_INTERVAL_SECONDS)
        return 0 if healthy else 1
    configure_logging(settings.log_level, service="worker")
    asyncio.run(run(settings))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
