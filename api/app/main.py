"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from app import __version__
from app.adapters.storage import StorageAdapter
from app.core.config import Settings, get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.core.request_id import RequestIdMiddleware
from app.db.session import create_engine, ping
from app.routers import health

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, service="api")

    engine = create_engine(settings)
    storage = StorageAdapter(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await engine.dispose()

    app = FastAPI(
        title="OSCC Health Intelligence API",
        version=__version__,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.storage = storage
    app.state.readiness_timeout_seconds = settings.readiness_timeout_seconds

    async def db_probe() -> None:
        await ping(engine, settings.readiness_timeout_seconds)

    async def storage_probe() -> None:
        await run_in_threadpool(storage.ping)

    app.state.probes = {"db": db_probe, "storage": storage_probe}

    register_error_handlers(app)
    app.add_middleware(RequestIdMiddleware)
    app.include_router(health.router)
    return app
