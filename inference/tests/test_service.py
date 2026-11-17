from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from inference_service.main import create_app

ROOT = Path(__file__).resolve().parents[1]
ENVELOPE_KEYS = {"error_code", "message", "details", "request_id"}


@pytest.fixture
def app() -> FastAPI:
    application = create_app()

    @application.get("/test/boom")
    async def boom() -> None:
        raise RuntimeError("internal detail")

    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def test_healthz(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert uuid.UUID(response.headers["X-Request-ID"]).version == 4


def test_readyz_reports_no_models_in_d0(client: TestClient) -> None:
    assert client.get("/readyz").json() == {"status": "ready", "models_loaded": 0}


def test_unknown_route_uses_envelope(client: TestClient) -> None:
    response = client.post("/internal/infer", json={}, headers={"X-Request-ID": "trace-00000042"})
    assert response.status_code == 404
    body = response.json()
    assert set(body) == ENVELOPE_KEYS
    assert body["error_code"] == "NOT_FOUND"
    assert body["request_id"] == "trace-00000042"


def test_unhandled_error_hides_internals(client: TestClient) -> None:
    response = client.get("/test/boom")
    assert response.status_code == 500
    assert response.json()["error_code"] == "INTERNAL_ERROR"
    assert "internal detail" not in response.text
    assert response.json()["request_id"] == response.headers["X-Request-ID"]


def test_malformed_request_id_is_replaced(client: TestClient) -> None:
    response = client.get("/healthz", headers={"X-Request-ID": "bad id\r\nx"})
    assert uuid.UUID(response.headers["X-Request-ID"]).version == 4


def test_access_log_is_json(capsys: pytest.CaptureFixture[str], client: TestClient) -> None:
    client.get("/healthz", headers={"X-Request-ID": "trace-00000099"})
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.startswith("{")]
    access = [x for x in lines if x.get("logger") == "inference.access"]
    assert access
    assert access[-1]["request_id"] == "trace-00000099"
    assert access[-1]["service"] == "inference"


def test_service_has_no_database_driver_loaded() -> None:
    code = (
        "import sys, inference_service.main; "
        "sys.exit(1 if any(m in sys.modules for m in ('sqlalchemy','asyncpg','psycopg')) else 0)"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=False)  # noqa: S603
    assert result.returncode == 0
