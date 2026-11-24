"""Power action service with persistent state and conflict handling."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import nullcontext
from datetime import timedelta
from typing import Any, Optional

from .errors import ConflictError, ExecutionError, InvalidInputError, NotFoundError
from .store import AuditRecord, PowerAction, StateStore, truncate_output, utcnow


class PowerService:
    def __init__(
        self,
        store: StateStore,
        process_runner: Any,
        helper_path: str,
        *,
        sudo_path: str = "/usr/bin/sudo",
        use_sudo: bool = True,
        job_manager: Optional[Any] = None,
        operation_lock: Optional[asyncio.Lock] = None,
    ) -> None:
        self.store = store
        self.process_runner = process_runner
        self.helper_path = helper_path
        self.sudo_path = sudo_path
        self.use_sudo = use_sudo
        self.job_manager = job_manager
        self.operation_lock = operation_lock
        store.reconcile_power_actions()

    def set_job_manager(self, job_manager: Any) -> None:
        self.job_manager = job_manager

    def has_pending_power(self) -> bool:
        return self.store.has_pending_power()

    def get_power_action(self, action_id: str) -> Optional[PowerAction]:
        return self.store.get_power_action(action_id)

    def list_power_actions(self, limit: int = 100) -> list[PowerAction]:
        return self.store.list_power_actions(limit=limit)

    def get_pending_power(self) -> Optional[PowerAction]:
        return self.store.get_pending_power()

    def _lock_context(self):
        if self.operation_lock is None:
            return nullcontext()
        return self.operation_lock

    def _helper_argv(self, operation: str, *extra: str) -> list[str]:
        if self.use_sudo and self.sudo_path:
            return [self.sudo_path, "-n", self.helper_path, operation, *extra]
        return [self.helper_path, operation, *extra]

    async def schedule(
        self,
        action_type: str,
        delay_seconds: int,
        credential_identity: Optional[str] = None,
        correlation_id: Optional[str] = None,
        *,
        confirmed: bool = False,
        **kwargs: Any,
    ) -> PowerAction:
        credential_identity = credential_identity or kwargs.get("credential_identity")
        correlation_id = correlation_id or kwargs.get("correlation_id")
        if action_type not in {"reboot", "shutdown"}:
            raise InvalidInputError("invalid_action", "action type must be reboot or shutdown")
        if not isinstance(delay_seconds, int) or isinstance(delay_seconds, bool):
            raise InvalidInputError("invalid_delay", "delay must be an integer")
        if delay_seconds < 10 or delay_seconds > 3600:
            raise InvalidInputError("invalid_delay", "delay must be between 10 and 3600 seconds")
        if not confirmed:
            raise InvalidInputError("confirmation_required", "power action requires confirmation")
        if credential_identity != "admin":
            raise InvalidInputError("invalid_credential", "credential identity must be admin")

        async with self._lock_context():
            if self.job_manager is not None and getattr(self.job_manager, "has_active_apt", lambda: False)():
                raise ConflictError("apt_operation_active", "an APT operation is active")
            if self.store.has_pending_power():
                raise ConflictError("power_action_pending", "a power action is already pending")

            corr = correlation_id or str(uuid.uuid4())
            action = PowerAction(
                action_type=action_type,
                delay_seconds=delay_seconds,
                credential_identity=credential_identity,
                correlation_id=corr,
                status="pending",
            )
            action.scheduled_for = action.created_at + timedelta(seconds=delay_seconds)
            self.store.create_power_action(action)

        argv = self._helper_argv("power-schedule", action_type, str(delay_seconds))
        try:
            result = await self.process_runner.run(argv, timeout=90, env=None)
        except (asyncio.TimeoutError, TimeoutError) as exc:
            self.store.update_power_action(
                action.id,
                status="failed",
                finished_at=utcnow(),
                error_code="timeout",
                error_message="power scheduling timed out",
            )
            self._record_audit(action, "power_schedule", "failure", "timeout", "power scheduling timed out")
            raise ExecutionError("timeout", "power scheduling timed out") from exc
        except Exception as exc:
            self.store.update_power_action(
                action.id,
                status="failed",
                finished_at=utcnow(),
                error_code="internal_error",
                error_message="internal error",
            )
            self._record_audit(action, "power_schedule", "failure", "internal_error", "internal error")
            raise ExecutionError("internal_error", "internal error") from exc
        timed_out = bool(getattr(result, "timed_out", False))
        if timed_out:
            self.store.update_power_action(
                action.id,
                status="failed",
                finished_at=utcnow(),
                error_code="timeout",
                error_message="power scheduling timed out",
            )
            self._record_audit(action, "power_schedule", "failure", "timeout", "power scheduling timed out")
            raise ExecutionError("timeout", "power scheduling timed out")
        returncode = getattr(result, "returncode", 1)
        stdout = getattr(result, "stdout", "") or ""
        stderr = getattr(result, "stderr", "") or ""
        if returncode != 0:
            message = (stderr.strip() or stdout.strip() or "helper failed")
            message, _ = truncate_output(message, truncated=bool(getattr(result, "stderr_truncated", False)))
            self.store.update_power_action(
                action.id,
                status="failed",
                finished_at=utcnow(),
                error_code="helper_failed",
                error_message=message,
            )
            self._record_audit(action, "power_schedule", "failure", "helper_failed", message)
            raise ExecutionError("helper_failed", message)
        output, output_truncated = truncate_output(
            stdout, truncated=bool(getattr(result, "stdout_truncated", False))
        )
        self.store.update_power_action(
            action.id,
            status="pending",
            output=output,
            output_truncated=output_truncated,
        )
        self._record_audit(action, "power_schedule", "success", None, None)
        updated = self.store.get_power_action(action.id)
        return updated or action

    async def cancel(
        self,
        action_id: str,
        *,
        credential_identity: str,
    ) -> PowerAction:
        if credential_identity != "admin":
            raise InvalidInputError("invalid_credential", "credential identity must be admin")
        action = self.store.get_power_action(action_id)
        if action is None:
            raise NotFoundError("power_action_not_found", "power action not found")
        if action.status != "pending":
            raise ConflictError("power_action_not_pending", "power action is not pending")
        now = utcnow()
        if action.scheduled_for is not None and action.scheduled_for <= now:
            raise ConflictError(
                "power_action_already_executed",
                "power action cancellation window has closed",
            )

        argv = self._helper_argv("power-cancel")
        try:
            result = await self.process_runner.run(argv, timeout=90, env=None)
        except (asyncio.TimeoutError, TimeoutError) as exc:
            self._record_audit(action, "power_cancel", "failure", "timeout", "power cancellation timed out")
            raise ExecutionError("timeout", "power cancellation timed out") from exc
        except Exception as exc:
            self._record_audit(action, "power_cancel", "failure", "internal_error", "internal error")
            raise ExecutionError("internal_error", "internal error") from exc
        timed_out = bool(getattr(result, "timed_out", False))
        if timed_out:
            self._record_audit(action, "power_cancel", "failure", "timeout", "power cancellation timed out")
            raise ExecutionError("timeout", "power cancellation timed out")
        returncode = getattr(result, "returncode", 1)
        stdout = getattr(result, "stdout", "") or ""
        stderr = getattr(result, "stderr", "") or ""
        if returncode != 0:
            message = (stderr.strip() or stdout.strip() or "helper failed")
            message, _ = truncate_output(message, truncated=bool(getattr(result, "stderr_truncated", False)))
            if action.scheduled_for is not None and action.scheduled_for <= utcnow():
                self.store.update_power_action(
                    action.id,
                    status="unknown",
                    finished_at=utcnow(),
                    error_code="unconfirmed_execution",
                    error_message="cancellation raced with execution; outcome unconfirmed",
                )
            else:
                self.store.update_power_action(
                    action.id,
                    status="failed",
                    finished_at=utcnow(),
                    error_code="helper_failed",
                    error_message=message,
                )
            self._record_audit(action, "power_cancel", "failure", "helper_failed", message)
            raise ExecutionError("helper_failed", message)
        output, output_truncated = truncate_output(
            stdout, truncated=bool(getattr(result, "stdout_truncated", False))
        )
        self.store.update_power_action(
            action.id,
            status="cancelled",
            finished_at=utcnow(),
            output=output,
            output_truncated=output_truncated,
        )
        self._record_audit(action, "power_cancel", "success", None, None)
        updated = self.store.get_power_action(action.id)
        return updated or action

    def _record_audit(self, action: PowerAction, operation: str, outcome: str, error_code: Optional[str], message: Optional[str]) -> None:
        try:
            self.store.create_audit(
                AuditRecord(
                    credential_identity=action.credential_identity,
                    correlation_id=action.correlation_id,
                    operation=operation,
                    outcome=outcome,
                    status="succeeded" if outcome == "success" else "failed",
                    error_code=error_code,
                    message=message,
                )
            )
        except Exception:
            pass
