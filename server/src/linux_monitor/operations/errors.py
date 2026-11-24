"""Typed operation errors for later HTTP mapping."""

from __future__ import annotations


class OperationError(Exception):
    """Base operation error."""

    code: str = "operation_error"
    http_status: int = 500

    def __init__(self, code: str | None = None, message: str = "", *, details: str | None = None) -> None:
        if code is not None:
            self.code = code
        self.message = message
        self.details = details
        super().__init__(f"{self.code}: {message}" if message else self.code)


class ConflictError(OperationError):
    code = "conflict"
    http_status = 409


class NotFoundError(OperationError):
    code = "not_found"
    http_status = 404


class InvalidInputError(OperationError):
    code = "invalid_input"
    http_status = 400


class ExecutionError(OperationError):
    code = "execution_failed"
    http_status = 502


class TimeoutOperationError(OperationError):
    code = "timeout"
    http_status = 504


class InterruptedError(OperationError):
    code = "interrupted"
    http_status = 500