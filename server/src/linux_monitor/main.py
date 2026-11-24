"""FastAPI application factory."""

from __future__ import annotations

import uuid
from typing import Any, Callable

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .auth import AuthThrottle, authenticate
from .config import Settings
from .collectors.system import collect_system
from .errors import ErrorResponse, ErrorDetail
from .schemas import SystemInfo


def _status_code_to_code(status_code: int) -> str:
    mapping = {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        405: "method_not_allowed",
        422: "validation_error",
        429: "too_many_requests",
        500: "internal_error",
    }
    return mapping.get(status_code, "error")


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Any:
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


def create_app(settings: Settings | None = None) -> FastAPI:
    if settings is None:
        from .config import Settings as _Settings

        settings = _Settings()
    settings.validate_tokens()

    docs_url = "/docs" if settings.docs_enabled else None
    redoc_url = "/redoc" if settings.docs_enabled else None
    openapi_url = "/openapi.json" if settings.docs_enabled else None

    app = FastAPI(
        title="Linux Monitor",
        version="0.1.0",
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
    )

    app.state.settings = settings
    app.state.throttle = AuthThrottle(
        threshold=settings.auth_failure_threshold,
        window_seconds=settings.auth_failure_window_seconds,
        max_clients=settings.auth_throttle_max_clients,
    )

    app.add_middleware(RequestIDMiddleware)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        body = ErrorResponse(
            error=ErrorDetail(
                code=_status_code_to_code(exc.status_code),
                message=str(exc.detail),
                request_id=request_id,
            )
        )
        headers = dict(exc.headers or {})
        headers["X-Request-ID"] = request_id
        return JSONResponse(status_code=exc.status_code, content=body.model_dump(), headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        body = ErrorResponse(
            error=ErrorDetail(
                code="validation_error",
                message="Request validation failed",
                request_id=request_id,
            )
        )
        return JSONResponse(status_code=422, content=body.model_dump(), headers={"X-Request-ID": request_id})

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        body = ErrorResponse(
            error=ErrorDetail(
                code="internal_error",
                message="Internal server error",
                request_id=request_id,
            )
        )
        return JSONResponse(status_code=500, content=body.model_dump(), headers={"X-Request-ID": request_id})

    @app.get("/health/live")
    async def health_live() -> dict:
        return {"status": "ok"}

    @app.get("/api/v1/system", response_model=SystemInfo)
    async def system(_identity: str = Depends(authenticate)) -> SystemInfo:
        return await run_in_threadpool(collect_system, settings)

    return app


app = create_app()