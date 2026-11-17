"""Liveness and readiness probes (ADR-0001, G-b).

These are infrastructure endpoints for Docker healthchecks, outside ``/api/v1`` and not routed
through Nginx. The administrator health report (``GET /api/v1/admin/health``) is Phase D1.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Request

from app.core.errors import AppError, GenericErrorCode

router = APIRouter(tags=["infrastructure"])

Probe = Callable[[], Awaitable[None]]


@router.get("/healthz", summary="Liveness probe")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", summary="Readiness probe (database and storage)")
async def readyz(request: Request) -> dict[str, object]:
    probes: dict[str, Probe] = request.app.state.probes
    timeout: float = request.app.state.readiness_timeout_seconds
    names = list(probes)
    results = await asyncio.gather(
        *(asyncio.wait_for(probes[name](), timeout) for name in names), return_exceptions=True
    )
    checks = {
        name: "ok" if not isinstance(result, BaseException) else "unavailable"
        for name, result in zip(names, results, strict=True)
    }
    if any(value != "ok" for value in checks.values()):
        raise AppError(
            503,
            GenericErrorCode.SERVICE_UNAVAILABLE.value,
            "One or more dependencies are unavailable",
            details={"checks": checks},
        )
    return {"status": "ready", "checks": checks}
