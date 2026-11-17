"""Shared fixtures. Tests never need real secrets: dummy values are injected here."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import create_app

TEST_ENV = {
    "APP_ENV": "test",
    "LOG_LEVEL": "INFO",
    "DATABASE_URL": "postgresql+asyncpg://oscc:test-only@localhost:5432/oscc",
    "STORAGE_ENDPOINT_URL": "http://storage.internal:8333",
    "STORAGE_PUBLIC_ENDPOINT_URL": "http://localhost:8333",
    "STORAGE_REGION": "us-east-1",
    "STORAGE_BUCKET": "oscc-private",
    "STORAGE_ACCESS_KEY_ID": "test-access-key",
    "STORAGE_SECRET_ACCESS_KEY": "test-secret-key",
    "STORAGE_SIGNED_URL_TTL_SECONDS": "600",
    "INFERENCE_URL": "http://inference:8001",
    "WORKER_POLL_INTERVAL_SECONDS": "60",
    "WORKER_HEARTBEAT_FILE": "oscc-test-heartbeat",  # tests that write it use tmp_path
    "READINESS_TIMEOUT_SECONDS": "0.5",
}


@pytest.fixture(autouse=True)
def _test_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for key, value in TEST_ENV.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def settings() -> Settings:
    return get_settings()


async def _ok() -> None:
    return None


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    application = create_app(settings)
    # Unit tests never touch real dependencies; readiness tests swap these per case.
    application.state.probes = {"db": _ok, "storage": _ok}
    return application


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
