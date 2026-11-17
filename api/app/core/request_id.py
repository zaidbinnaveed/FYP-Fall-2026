"""Request-ID middleware (pure ASGI).

Accepts a well-formed incoming ``X-Request-ID`` or generates a UUID4, exposes it through a
context variable (for logs) and ``scope["state"]["request_id"]`` (for error handlers, including
the outermost 500 handler), echoes it in the response header and writes one access-log line.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from contextvars import ContextVar

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,128}$")

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_access_log = logging.getLogger("app.access")


def new_request_id() -> str:
    return str(uuid.uuid4())


def resolve_request_id(incoming: str | None) -> str:
    """Return the incoming ID if it is safe to log and echo, otherwise a fresh UUID4."""
    if incoming and _VALID_REQUEST_ID.fullmatch(incoming):
        return incoming
    return new_request_id()


def current_request_id() -> str | None:
    return request_id_var.get()


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = None
        for name, value in scope.get("headers", []):
            if name.lower() == b"x-request-id":
                incoming = value.decode("latin-1")
                break
        request_id = resolve_request_id(incoming)
        scope.setdefault("state", {})["request_id"] = request_id
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status_holder: dict[str, int] = {"status": 500}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                headers = MutableHeaders(scope=message)
                headers[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            _access_log.info(
                "request completed",
                extra={
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                    "status": status_holder["status"],
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            request_id_var.reset(token)
