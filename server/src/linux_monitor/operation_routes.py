"""Operation API routes."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import Depends, Request

from .auth import require_admin
from .main import ensure_operation_resources
from .operations import JobManager, NotFoundError, PowerService, utcnow
from .schemas import JobResponse, PowerActionCreateRequest, PowerActionResponse


def _job_manager(request: Request) -> JobManager:
    ensure_operation_resources(request.app)
    return request.app.state.job_manager


def _power_service(request: Request) -> PowerService:
    ensure_operation_resources(request.app)
    return request.app.state.power_service


def _job_response(job: Any, request: Request) -> JobResponse:
    poll_url = f"/api/v1/jobs/{job.id}"
    return JobResponse(
        id=job.id,
        kind=job.job_type,
        status=job.status,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        result=job.result,
        output=job.output,
        output_truncated=bool(job.output_truncated),
        error_code=job.error_code,
        error_message=job.error_message,
        poll_url=poll_url,
    )


def _power_response(action: Any) -> PowerActionResponse:
    now = utcnow()
    scheduled_for = action.scheduled_for
    cancellable = (
        action.status == "pending"
        and (scheduled_for is None or scheduled_for > now)
    )
    return PowerActionResponse(
        id=action.id,
        action=action.action_type,
        status=action.status,
        created_at=action.created_at,
        scheduled_for=scheduled_for,
        cancellable=cancellable,
    )


def register_operation_routes(app) -> None:
    @app.post("/api/v1/updates/check", status_code=202, response_model=JobResponse)
    async def updates_check(request: Request, identity: str = Depends(require_admin)) -> JobResponse:
        job_manager: JobManager = _job_manager(request)
        correlation_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        job = await job_manager.start_job(
            "update_check",
            credential_identity=identity,
            correlation_id=correlation_id,
        )
        response = _job_response(job, request)
        return response

    @app.post("/api/v1/updates/apply", status_code=202, response_model=JobResponse)
    async def updates_apply(request: Request, identity: str = Depends(require_admin)) -> JobResponse:
        job_manager: JobManager = _job_manager(request)
        correlation_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        job = await job_manager.start_job(
            "update_apply",
            credential_identity=identity,
            correlation_id=correlation_id,
        )
        return _job_response(job, request)

    @app.get("/api/v1/jobs/{job_id}", response_model=JobResponse)
    async def get_job(job_id: str, request: Request, identity: str = Depends(require_admin)) -> JobResponse:
        job_manager: JobManager = _job_manager(request)
        job = job_manager.get_job(job_id)
        if job is None:
            raise NotFoundError("job_not_found", "job not found")
        return _job_response(job, request)

    @app.post("/api/v1/power-actions", status_code=202, response_model=PowerActionResponse)
    async def create_power_action(
        body: PowerActionCreateRequest,
        request: Request,
        identity: str = Depends(require_admin),
    ) -> PowerActionResponse:
        power_service: PowerService = _power_service(request)
        correlation_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        action = await power_service.schedule(
            body.action,
            body.delay_seconds,
            credential_identity=identity,
            correlation_id=correlation_id,
            confirmed=True,
        )
        return _power_response(action)

    @app.get("/api/v1/power-actions/{action_id}", response_model=PowerActionResponse)
    async def get_power_action(
        action_id: str, request: Request, identity: str = Depends(require_admin)
    ) -> PowerActionResponse:
        power_service: PowerService = _power_service(request)
        action = power_service.get_power_action(action_id)
        if action is None:
            raise NotFoundError("power_action_not_found", "power action not found")
        return _power_response(action)

    @app.delete("/api/v1/power-actions/{action_id}", response_model=PowerActionResponse)
    async def cancel_power_action(
        action_id: str, request: Request, identity: str = Depends(require_admin)
    ) -> PowerActionResponse:
        power_service: PowerService = _power_service(request)
        action = await power_service.cancel(
            action_id,
            credential_identity=identity,
        )
        return _power_response(action)
