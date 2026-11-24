"""Authentication helpers."""

from __future__ import annotations

import secrets
import time
from collections import OrderedDict
from typing import Optional

from fastapi import HTTPException, Request, status

from .config import Settings


class AuthThrottle:
    """Small bounded failure throttle keyed by client address."""

    def __init__(self, threshold: int = 5, window_seconds: int = 60, max_clients: int = 1024):
        self.threshold = max(1, threshold)
        self.window_seconds = max(1, window_seconds)
        self.max_clients = max(1, max_clients)
        self._failures: dict[str, list[float]] = {}
        self._order: OrderedDict[str, None] = OrderedDict()

    def _prune(self, address: str, now: float) -> list[float]:
        entries = self._failures.get(address, [])
        cutoff = now - self.window_seconds
        entries = [ts for ts in entries if ts >= cutoff]
        if entries:
            self._failures[address] = entries
        else:
            self._failures.pop(address, None)
        return entries

    def is_blocked(self, address: str) -> bool:
        now = time.monotonic()
        entries = self._prune(address, now)
        return len(entries) >= self.threshold

    def record_failure(self, address: str) -> None:
        now = time.monotonic()
        self._prune(address, now)
        self._failures.setdefault(address, []).append(now)
        self._order.move_to_end(address) if address in self._order else self._order.__setitem__(address, None)
        # Bound number of tracked clients.
        while len(self._order) > self.max_clients:
            oldest, _ = self._order.popitem(last=False)
            self._failures.pop(oldest, None)

    def reset(self, address: str) -> None:
        self._failures.pop(address, None)
        self._order.pop(address, None)


def _client_address(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _extract_bearer(request: Request) -> Optional[str]:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def authenticate(request: Request) -> str:
    settings: Settings = request.app.state.settings
    throttle: AuthThrottle = request.app.state.throttle
    address = _client_address(request)

    if throttle.is_blocked(address):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many authentication failures",
        )

    token = _extract_bearer(request)
    reader = settings.reader_value()
    admin = settings.admin_value()

    if token is None:
        throttle.record_failure(address)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    is_reader = bool(reader) and secrets.compare_digest(token, reader)
    is_admin = bool(admin) and secrets.compare_digest(token, admin)

    if not (is_reader or is_admin):
        throttle.record_failure(address)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    identity = "admin" if is_admin else "reader"
    request.state.identity = identity
    throttle.reset(address)
    return identity


def require_admin(request: Request) -> str:
    identity = authenticate(request)
    if identity != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin token required")
    return identity
