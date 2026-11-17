"""Scheduler loop. D0 runs no jobs yet; it only proves the process lifecycle and heartbeat.

Jobs (reminder dispatch, screening retries, nightly tasks) are registered in later phases and
claim work with ``SELECT ... FOR UPDATE SKIP LOCKED``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal

from app.core.config import Settings
from app.worker.heartbeat import write_heartbeat

logger = logging.getLogger("app.worker")

# The heartbeat is written more often than jobs run so liveness does not depend on job length.
HEARTBEAT_INTERVAL_SECONDS = 10


async def run(settings: Settings, stop: asyncio.Event | None = None) -> None:
    stop = stop or asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        # Not supported on Windows or outside the main thread; Docker (Linux) supports it.
        with contextlib.suppress(NotImplementedError, RuntimeError):
            loop.add_signal_handler(sig, stop.set)

    logger.info(
        "worker started",
        extra={"poll_interval_seconds": settings.worker_poll_interval_seconds},
    )
    while not stop.is_set():
        try:
            write_heartbeat(settings.worker_heartbeat_file)
        except OSError:
            logger.exception("could not write heartbeat")
        try:
            await asyncio.wait_for(stop.wait(), timeout=HEARTBEAT_INTERVAL_SECONDS)
        except TimeoutError:
            continue
    logger.info("worker stopped")
