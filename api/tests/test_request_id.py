from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.request_id import resolve_request_id


def test_generates_uuid_when_missing(client: TestClient) -> None:
    response = client.get("/healthz")
    rid = response.headers["X-Request-ID"]
    assert uuid.UUID(rid).version == 4


def test_propagates_well_formed_incoming_id(client: TestClient) -> None:
    response = client.get("/healthz", headers={"X-Request-ID": "abc-DEF_123.456"})
    assert response.headers["X-Request-ID"] == "abc-DEF_123.456"


@pytest.mark.parametrize(
    "bad",
    [
        "short",  # too short
        "x" * 129,  # too long
        "id with spaces",
        "evil\r\nSet-Cookie:x",  # header injection attempt
        "<script>alert(1)</script>",
        "",
    ],
)
def test_rejects_malformed_incoming_id(bad: str) -> None:
    resolved = resolve_request_id(bad)
    assert resolved != bad
    assert uuid.UUID(resolved).version == 4


def test_each_request_gets_a_distinct_id(client: TestClient) -> None:
    ids = {client.get("/healthz").headers["X-Request-ID"] for _ in range(5)}
    assert len(ids) == 5
