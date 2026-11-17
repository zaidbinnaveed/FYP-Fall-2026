from __future__ import annotations

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_healthz_is_always_ok(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_ok_when_dependencies_ok(client: TestClient) -> None:
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"db": "ok", "storage": "ok"}}


async def _fail() -> None:
    raise ConnectionError("db down")


async def _hang() -> None:
    await asyncio.sleep(10)


def test_readyz_503_envelope_when_db_down(app: FastAPI, client: TestClient) -> None:
    app.state.probes["db"] = _fail
    response = client.get("/readyz")
    assert response.status_code == 503
    body = response.json()
    assert body["error_code"] == "SERVICE_UNAVAILABLE"
    assert body["details"] == {"checks": {"db": "unavailable", "storage": "ok"}}
    assert "db down" not in response.text


def test_readyz_times_out_slow_dependency(app: FastAPI, client: TestClient) -> None:
    app.state.probes["storage"] = _hang
    response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["details"]["checks"]["storage"] == "unavailable"


def test_openapi_is_served_under_api_v1(client: TestClient) -> None:
    response = client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["title"] == "OSCC Health Intelligence API"
