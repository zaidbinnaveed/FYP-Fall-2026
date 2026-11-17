"""Request IDs, JSON logging and the error envelope for the inference service.

Behaviour mirrors ``api/app/core`` so logs and errors look the same across services.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,128}$")
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_STATUS_TO_CODE = {
    400: "BAD_REQUEST",
    401: "UNAUTHENTICATED",
    403: "NOT_PERMITTED",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    503: "SERVICE_UNAVAILABLE",
}

_access_log = logging.getLogger("inference.access")
_error_log = logging.getLogger("inference.errors")
_RESERVED = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime"}


def resolve_request_id(incoming: str | None) -> str:
    if incoming and _VALID_REQUEST_ID.fullmatch(incoming):
        return incoming
    return str(uuid.uuid4())


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = next(
            (
                v.decode("latin-1")
                for k, v in scope.get("headers", [])
                if k.lower() == b"x-request-id"
            ),
            None,
        )
        request_id = resolve_request_id(incoming)
        scope.setdefault("state", {})["request_id"] = request_id
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status = {"code": 500}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            _access_log.info(
                "request completed",
                extra={
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                    "status": status["code"],
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            request_id_var.reset(token)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "service": "inference",
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None) or request_id_var.get(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and key not in payload:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


class StdoutHandler(logging.StreamHandler):  # type: ignore[type-arg]
    """Writes to whatever ``sys.stdout`` is at emit time (robust to stream swapping)."""

    def __init__(self) -> None:
        super().__init__(sys.stdout)

    def emit(self, record: logging.LogRecord) -> None:
        self.stream = sys.stdout
        super().emit(record)


def configure_logging(level: str) -> None:
    handler = StdoutHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True
    logging.getLogger("uvicorn.access").disabled = True


def _envelope(
    request: Request, status: int, code: str, message: str, details: Any = None
) -> JSONResponse:
    rid = getattr(request.state, "request_id", None) or request_id_var.get()
    body = {"error_code": code, "message": message, "details": details, "request_id": rid}
    headers = {REQUEST_ID_HEADER: rid} if rid else {}
    return JSONResponse(status_code=status, content=jsonable_encoder(body), headers=headers)


async def _http_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)  # noqa: S101
    code = _STATUS_TO_CODE.get(
        exc.status_code, "INTERNAL_ERROR" if exc.status_code >= 500 else "BAD_REQUEST"
    )
    message = exc.detail if isinstance(exc.detail, str) else code.replace("_", " ").lower()
    return _envelope(request, exc.status_code, code, message)


async def _validation_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)  # noqa: S101
    details = [
        {"loc": list(e.get("loc", ())), "msg": e.get("msg"), "type": e.get("type")}
        for e in exc.errors()
    ]
    return _envelope(request, 422, "VALIDATION_ERROR", "Request validation failed", details)


async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    _error_log.exception(
        "unhandled error", extra={"request_id": getattr(request.state, "request_id", None)}
    )
    return _envelope(request, 500, "INTERNAL_ERROR", "An unexpected error occurred")


def install(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, _http_handler)
    app.add_exception_handler(RequestValidationError, _validation_handler)
    app.add_exception_handler(Exception, _unhandled_handler)
    app.add_middleware(RequestIdMiddleware)
