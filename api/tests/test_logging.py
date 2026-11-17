from __future__ import annotations

import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.core.logging import JsonFormatter
from app.core.request_id import request_id_var


def _record(msg: str, **extra: object) -> logging.LogRecord:
    record = logging.LogRecord("app.test", logging.INFO, __file__, 1, msg, None, None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_formatter_emits_json_with_request_id() -> None:
    token = request_id_var.set("req-00000001")
    try:
        line = JsonFormatter("api").format(_record("hello", screening_id="s-1"))
    finally:
        request_id_var.reset(token)
    payload = json.loads(line)
    assert payload["message"] == "hello"
    assert payload["request_id"] == "req-00000001"
    assert payload["service"] == "api"
    assert payload["level"] == "INFO"
    assert payload["screening_id"] == "s-1"
    assert payload["timestamp"].endswith("Z")


def test_formatter_without_request_context() -> None:
    payload = json.loads(JsonFormatter("worker").format(_record("tick")))
    assert payload["request_id"] is None


def test_access_log_line_carries_request_id(
    capsys: pytest.CaptureFixture[str], client: TestClient
) -> None:
    # capsys is requested first so stdout is captured before the app binds its log handler.
    client.get("/healthz", headers={"X-Request-ID": "trace-abcdef12"})
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.startswith("{")]
    access = [x for x in lines if x.get("logger") == "app.access"]
    assert access, "expected one JSON access-log line"
    assert access[-1]["request_id"] == "trace-abcdef12"
    assert access[-1]["path"] == "/healthz"
    assert access[-1]["status"] == 200
