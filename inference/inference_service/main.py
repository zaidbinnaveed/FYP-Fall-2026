"""Inference service application factory.

D0 exposes only liveness/readiness. ``POST /internal/infer`` and ``POST /internal/models/load``
(SDS Appendix B) are implemented in Phase D2 against the ``dummy-v0`` model first.
"""

from __future__ import annotations

from typing import Literal

from fastapi import FastAPI
from pydantic_settings import BaseSettings, SettingsConfigDict

from inference_service import __version__
from inference_service.observability import configure_logging, install


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title="OSCC Inference Service (internal)",
        version=__version__,
        docs_url="/internal/docs",
        openapi_url="/internal/openapi.json",
        redoc_url=None,
    )
    app.state.loaded_models = {}
    install(app)

    @app.get("/healthz", tags=["infrastructure"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", tags=["infrastructure"])
    async def readyz() -> dict[str, object]:
        # Stateless and dependency-free until D2; ready means the process can serve requests.
        return {"status": "ready", "models_loaded": len(app.state.loaded_models)}

    return app
