"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import Any, Callable, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .auth import AuthThrottle, authenticate
from .config import Settings
from .collectors.system import collect_system
from .errors import ErrorResponse, ErrorDetail
from .operations import (
    AsyncSubprocessRunner,
    JobManager,
    OperationError,
    PowerService,
    StateStore,
)
from .operations.errors import (
    ConflictError,
    ExecutionError,
    InvalidInputError,
    NotFoundError,
    TimeoutOperationError,
)
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
        503: "service_unavailable",
        504: "gateway_timeout",
    }
    return mapping.get(status_code, "error")


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Any:
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


def _resolve_settings(settings: Optional[Settings]) -> Settings:
    if settings is None:
        settings = Settings()
    settings.validate_tokens()
    return settings


def ensure_operation_resources(app: FastAPI) -> None:
    """Lazily create operation resources if they do not already exist."""
    settings: Settings = app.state.settings
    if getattr(app.state, "store", None) is None:
        app.state.store = StateStore(settings.database_path)
    if getattr(app.state, "operation_lock", None) is None:
        app.state.operation_lock = asyncio.Lock()
    if getattr(app.state, "runner", None) is None:
        app.state.runner = AsyncSubprocessRunner()

    store = app.state.store
    lock = app.state.operation_lock
    runner = app.state.runner

    if getattr(app.state, "job_manager", None) is None:
        app.state.job_manager = JobManager(
            store,
            runner,
            settings.privileged_helper_path,
            sudo_path=settings.sudo_path,
            use_sudo=True,
            operation_lock=lock,
        )
    job_manager = app.state.job_manager

    if getattr(app.state, "power_service", None) is None:
        app.state.power_service = PowerService(
            store,
            runner,
            settings.privileged_helper_path,
            sudo_path=settings.sudo_path,
            use_sudo=True,
            job_manager=job_manager,
            operation_lock=lock,
        )
    power_service = app.state.power_service

    job_manager.set_power_service(power_service)
    power_service.set_job_manager(job_manager)


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_operation_resources(app)
    store = app.state.store
    try:
        yield
    finally:
        if store is not None:
            store.close()


def create_app(
    settings: Optional[Settings] = None,
    *,
    runner: Any = None,
    store: Any = None,
    operation_lock: Any = None,
) -> FastAPI:
    settings = _resolve_settings(settings)

    docs_url = "/docs" if settings.docs_enabled else None
    redoc_url = "/redoc" if settings.docs_enabled else None
    openapi_url = "/openapi.json" if settings.docs_enabled else None

    app = FastAPI(
        title="Linux Monitor",
        version="0.1.0",
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
        lifespan=lifespan,
    )

    app.state.settings = settings
    app.state.throttle = AuthThrottle(
        threshold=settings.auth_failure_threshold,
        window_seconds=settings.auth_failure_window_seconds,
        max_clients=settings.auth_throttle_max_clients,
    )

    # Injection hooks for tests.
    if runner is not None:
        app.state.runner = runner
    if store is not None:
        app.state.store = store
    if operation_lock is not None:
        app.state.operation_lock = operation_lock

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

    @app.exception_handler(OperationError)
    async def operation_error_handler(request: Request, exc: OperationError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        status_code = exc.http_status
        if isinstance(exc, InvalidInputError):
            status_code = 422
        elif isinstance(exc, NotFoundError):
            status_code = 404
        elif isinstance(exc, ConflictError):
            status_code = 409
        elif isinstance(exc, TimeoutOperationError):
            status_code = 504
        elif isinstance(exc, ExecutionError):
            status_code = 503
        body = ErrorResponse(
            error=ErrorDetail(
                code=exc.code,
                message=exc.message,
                request_id=request_id,
            )
        )
        return JSONResponse(status_code=status_code, content=body.model_dump(), headers={"X-Request-ID": request_id})

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

    # Register operation routes.
    from .operation_routes import register_operation_routes

    register_operation_routes(app)

    return app


app = create_app()