"""Every error leaves the API in the envelope {error_code, message, details, request_id}."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.errors import AppError

ENVELOPE_KEYS = {"error_code", "message", "details", "request_id"}


class _Body(BaseModel):
    count: int


@pytest.fixture
def app_with_routes(app: FastAPI) -> FastAPI:
    @app.get("/test/app-error")
    async def app_error() -> None:
        raise AppError(409, "EMAIL_EXISTS", "An account with this email already exists")

    @app.get("/test/http-401")
    async def http_401() -> None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    @app.get("/test/http-403")
    async def http_403() -> None:
        raise HTTPException(status_code=403)

    @app.get("/test/http-429")
    async def http_429() -> None:
        raise HTTPException(status_code=429, headers={"Retry-After": "30"})

    @app.get("/test/http-418")
    async def http_418() -> None:
        raise HTTPException(status_code=418)

    @app.post("/test/validate")
    async def validate(body: _Body) -> dict[str, int]:
        return {"count": body.count}

    @app.get("/test/boom")
    async def boom() -> None:
        raise RuntimeError("secret internal detail")

    return app


@pytest.fixture
def c(app_with_routes: FastAPI) -> TestClient:
    return TestClient(app_with_routes, raise_server_exceptions=False)


def _assert_envelope(body: dict[str, Any], code: str) -> None:
    assert set(body) == ENVELOPE_KEYS
    assert body["error_code"] == code
    assert isinstance(body["message"], str)
    assert body["message"]
    assert isinstance(body["request_id"], str)
    assert body["request_id"]


def test_app_error_uses_its_own_code(c: TestClient) -> None:
    response = c.get("/test/app-error")
    assert response.status_code == 409
    _assert_envelope(response.json(), "EMAIL_EXISTS")


@pytest.mark.parametrize(
    ("path", "status", "code"),
    [
        ("/test/http-401", 401, "UNAUTHENTICATED"),
        ("/test/http-403", 403, "NOT_PERMITTED"),
        ("/test/http-429", 429, "RATE_LIMITED"),
        ("/test/http-418", 418, "BAD_REQUEST"),
        ("/does-not-exist", 404, "NOT_FOUND"),
    ],
)
def test_http_errors_are_mapped(c: TestClient, path: str, status: int, code: str) -> None:
    response = c.get(path)
    assert response.status_code == status
    _assert_envelope(response.json(), code)


def test_method_not_allowed(c: TestClient) -> None:
    response = c.delete("/healthz")
    assert response.status_code == 405
    _assert_envelope(response.json(), "METHOD_NOT_ALLOWED")


def test_http_error_keeps_headers(c: TestClient) -> None:
    response = c.get("/test/http-429")
    assert response.headers["Retry-After"] == "30"


def test_validation_error_lists_fields(c: TestClient) -> None:
    response = c.post("/test/validate", json={"count": "not-a-number"})
    assert response.status_code == 422
    body = response.json()
    _assert_envelope(body, "VALIDATION_ERROR")
    assert body["details"][0]["loc"] == ["body", "count"]


def test_unhandled_error_hides_internals_and_keeps_request_id(c: TestClient) -> None:
    response = c.get("/test/boom", headers={"X-Request-ID": "trace-12345678"})
    assert response.status_code == 500
    body = response.json()
    _assert_envelope(body, "INTERNAL_ERROR")
    assert "secret internal detail" not in response.text
    assert body["request_id"] == "trace-12345678"
    assert response.headers["X-Request-ID"] == "trace-12345678"


def test_envelope_request_id_matches_header(c: TestClient) -> None:
    response = c.get("/test/app-error")
    assert response.json()["request_id"] == response.headers["X-Request-ID"]
