"""Uniform error envelope ``{error_code, message, details, request_id}``.

See the SDS section "Global error handling".

Use-case error codes (``EMAIL_EXISTS``, ``NOT_FOUND`` ...) are raised as :class:`AppError` by the
services that own them. Generic codes for framework-level failures are defined here; see
``docs/adr/0001-d0-foundations.md`` (gap G-a) for why they exist.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.request_id import REQUEST_ID_HEADER, current_request_id

logger = logging.getLogger("app.errors")


class GenericErrorCode(StrEnum):
    """Framework-level codes (ADR-0001, G-a). Use-case codes come from the SDS."""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    BAD_REQUEST = "BAD_REQUEST"  # any other 4xx without a dedicated code
    UNAUTHENTICATED = "UNAUTHENTICATED"
    NOT_PERMITTED = "NOT_PERMITTED"  # SDS SD3 code, reused for any plain 403
    NOT_FOUND = "NOT_FOUND"  # SDS SD3 code, reused for unknown routes
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    RATE_LIMITED = "RATE_LIMITED"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


_STATUS_TO_CODE: dict[int, GenericErrorCode] = {
    400: GenericErrorCode.BAD_REQUEST,
    401: GenericErrorCode.UNAUTHENTICATED,
    403: GenericErrorCode.NOT_PERMITTED,
    404: GenericErrorCode.NOT_FOUND,
    405: GenericErrorCode.METHOD_NOT_ALLOWED,
    422: GenericErrorCode.VALIDATION_ERROR,
    429: GenericErrorCode.RATE_LIMITED,
    503: GenericErrorCode.SERVICE_UNAVAILABLE,
}


class ErrorEnvelope(BaseModel):
    error_code: str
    message: str
    details: Any = None
    request_id: str | None


class AppError(Exception):
    """An expected, client-visible error with a stable machine-readable code."""

    def __init__(
        self,
        status_code: int,
        error_code: str,
        message: str,
        details: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        self.details = details
        self.headers = headers


def _request_id_of(request: Request) -> str | None:
    rid = getattr(request.state, "request_id", None)
    return rid if isinstance(rid, str) else current_request_id()


def error_response(
    request: Request,
    status_code: int,
    error_code: str,
    message: str,
    details: Any = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = _request_id_of(request)
    body = ErrorEnvelope(
        error_code=error_code, message=message, details=details, request_id=request_id
    )
    out_headers = dict(headers or {})
    if request_id:
        out_headers[REQUEST_ID_HEADER] = request_id
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(body.model_dump()),
        headers=out_headers,
    )


async def _app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)  # noqa: S101 - registered only for AppError
    return error_response(
        request, exc.status_code, exc.error_code, exc.message, exc.details, exc.headers
    )


async def _http_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)  # noqa: S101
    code = _STATUS_TO_CODE.get(
        exc.status_code,
        GenericErrorCode.INTERNAL_ERROR if exc.status_code >= 500 else GenericErrorCode.BAD_REQUEST,
    )
    message = exc.detail if isinstance(exc.detail, str) else code.value.replace("_", " ").lower()
    headers = dict(exc.headers) if exc.headers else None
    return error_response(request, exc.status_code, code.value, message, None, headers)


async def _validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)  # noqa: S101
    details = [
        {"loc": list(err.get("loc", ())), "msg": err.get("msg"), "type": err.get("type")}
        for err in exc.errors()
    ]
    return error_response(
        request, 422, GenericErrorCode.VALIDATION_ERROR.value, "Request validation failed", details
    )


async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = _request_id_of(request)
    logger.exception("unhandled error", extra={"request_id": request_id})
    # Never leak internals to the client.
    return error_response(
        request, 500, GenericErrorCode.INTERNAL_ERROR.value, "An unexpected error occurred"
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(Exception, _unhandled_error_handler)
