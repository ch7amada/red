"""Linux Monitor web adapter (FastAPI + Jinja + HTMX)."""

from __future__ import annotations

import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent / "static"

DEFAULT_UPSTREAM = "http://127.0.0.1:8000"
SESSION_TTL_SECONDS = int(os.getenv("LINUX_MONITOR_SESSION_TTL", "1800"))
MAX_SESSIONS = int(os.getenv("LINUX_MONITOR_MAX_SESSIONS", "1000"))


@dataclass
class Settings:
    upstream_url: str = field(default_factory=lambda: os.getenv("LINUX_MONITOR_API_URL", DEFAULT_UPSTREAM))
    session_ttl_seconds: int = SESSION_TTL_SECONDS
    max_sessions: int = MAX_SESSIONS
    cookie_name: str = "lm_session"

    def __post_init__(self) -> None:
        parsed = urlparse(self.upstream_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("LINUX_MONITOR_API_URL must be an http(s) URL")
        self.upstream_url = self.upstream_url.rstrip("/")


@dataclass
class Session:
    token: str
    created_at: float
    last_seen: float
    expires_at: float


class SessionStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def create(self, token: str) -> str:
        now = time.time()
        with self._lock:
            self._prune_locked(now)
            if len(self._sessions) >= self.settings.max_sessions:
                oldest = min(self._sessions, key=lambda k: self._sessions[k].last_seen)
                del self._sessions[oldest]
            sid = secrets.token_urlsafe(32)
            self._sessions[sid] = Session(
                token=token,
                created_at=now,
                last_seen=now,
                expires_at=now + self.settings.session_ttl_seconds,
            )
            return sid

    def get(self, sid: Optional[str]) -> Optional[Session]:
        if not sid:
            return None
        now = time.time()
        with self._lock:
            session = self._sessions.get(sid)
            if session is None:
                return None
            if session.expires_at <= now:
                del self._sessions[sid]
                return None
            session.last_seen = now
            session.expires_at = now + self.settings.session_ttl_seconds
            return session

    def revoke(self, sid: Optional[str]) -> None:
        if not sid:
            return
        with self._lock:
            self._sessions.pop(sid, None)

    def _prune_locked(self, now: float) -> None:
        expired = [k for k, v in self._sessions.items() if v.expires_at <= now]
        for key in expired:
            del self._sessions[key]


def _format_bytes(value: Any) -> str:
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if number < 0:
        number = 0
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    index = 0
    while number >= 1024 and index < len(units) - 1:
        number /= 1024
        index += 1
    if index == 0:
        return f"{int(number)} {units[index]}"
    return f"{number:.1f} {units[index]}"


def _format_uptime(value: Any) -> str:
    if value is None:
        return "—"
    try:
        total = int(float(value))
    except (TypeError, ValueError):
        return "—"
    if total < 0:
        total = 0
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    if not days and not hours:
        parts.append(f"{seconds}s")
    return " ".join(parts)


def _format_pct(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return "—"


def _format_dt(value: Any) -> str:
    if not value:
        return "—"
    try:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    except ValueError:
        return str(value)


def _origin_ok(request: Request) -> bool:
    origin = request.headers.get("origin")
    if not origin:
        return False
    expected = f"{request.url.scheme}://{request.url.netloc}"
    return origin == expected


class NoStoreMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Any:
        response = await call_next(request)
        if not request.url.path.startswith("/static"):
            response.headers["Cache-Control"] = "no-store"
        return response


def create_app(
    settings: Optional[Settings] = None,
    *,
    upstream: Optional[httpx.AsyncClient] = None,
    transport: Optional[httpx.AsyncBaseTransport] = None,
    client: Optional[httpx.AsyncClient] = None,
    sessions: Optional[SessionStore] = None,
) -> FastAPI:
    settings = settings or Settings()
    from contextlib import asynccontextmanager

    if upstream is None and client is not None:
        upstream = client
    owned_upstream = upstream is None and transport is None
    if upstream is None:
        upstream = httpx.AsyncClient(
            transport=transport,
            base_url=settings.upstream_url,
            timeout=httpx.Timeout(10.0),
            follow_redirects=False,
            trust_env=False,
        )

    session_store = sessions or SessionStore(settings)

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    templates.env.autoescape = True
    templates.env.filters["bytes"] = _format_bytes
    templates.env.filters["uptime"] = _format_uptime
    templates.env.filters["pct"] = _format_pct
    templates.env.filters["dt"] = _format_dt

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        if owned_upstream:
            await upstream.aclose()

    app = FastAPI(title="Linux Monitor", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.upstream = upstream
    app.state.sessions = session_store
    app.state.templates = templates

    app.add_middleware(NoStoreMiddleware)

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    def get_session(request: Request) -> Optional[Session]:
        return session_store.get(request.cookies.get(settings.cookie_name))

    def require_session(request: Request) -> Session:
        session = get_session(request)
        if session is None:
            raise HTTPException(status_code=401, detail="Session expired or missing")
        return session

    async def fetch_system(token: str) -> tuple[Optional[dict], str]:
        """Return (payload, error_kind) where error_kind is '' on success."""
        try:
            response = await upstream.get(
                "/api/v1/system", headers={"Authorization": f"Bearer {token}"}
            )
        except httpx.HTTPError:
            return None, "unavailable"
        if response.status_code in (401, 403):
            return None, "invalid"
        if not response.is_success:
            return None, "unavailable"
        try:
            return response.json(), ""
        except ValueError:
            return None, "unavailable"

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> Response:
        if exc.status_code == 401:
            if request.headers.get("HX-Request"):
                return Response(status_code=401, headers={"HX-Redirect": "/connect"})
            return RedirectResponse("/connect", status_code=303)
        return Response(status_code=exc.status_code, content=str(exc.detail))

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> Any:
        if get_session(request) is None:
            return RedirectResponse("/connect", status_code=303)
        return templates.TemplateResponse(request, "overview.html", {})

    @app.get("/connect", response_class=HTMLResponse)
    async def connect_page(request: Request) -> Any:
        return templates.TemplateResponse(request, "connect.html", {"error": None})

    @app.post("/connect", response_class=HTMLResponse)
    async def connect(request: Request) -> Any:
        if not _origin_ok(request):
            raise HTTPException(status_code=403, detail="Cross-origin request rejected")
        form = await request.form()
        token = str(form.get("token") or "").strip()
        if not token:
            return templates.TemplateResponse(
                "connect.html",
                {"request": request, "error": "Token is required."},
                status_code=400,
            )
        payload, kind = await fetch_system(token)
        if kind == "invalid":
            return templates.TemplateResponse(
                request, "connect.html",
                {"error": "Invalid or unauthorized token."},
                status_code=401,
            )
        if kind == "unavailable":
            return templates.TemplateResponse(
                request, "connect.html",
                {"error": "Monitoring server unavailable or degraded."},
                status_code=503,
            )
        sid = session_store.create(token)
        response = RedirectResponse("/", status_code=303)
        secure = request.url.scheme == "https"
        response.set_cookie(
            settings.cookie_name,
            sid,
            httponly=True,
            samesite="strict",
            secure=secure,
            max_age=settings.session_ttl_seconds,
            path="/",
        )
        return response

    @app.post("/logout")
    async def logout(request: Request) -> Any:
        if not _origin_ok(request):
            raise HTTPException(status_code=403, detail="Cross-origin request rejected")
        session_store.revoke(request.cookies.get(settings.cookie_name))
        response = RedirectResponse("/connect", status_code=303)
        response.delete_cookie(settings.cookie_name, path="/")
        return response

    @app.get("/fragments/overview", response_class=HTMLResponse)
    async def overview_fragment(request: Request) -> Any:
        session = require_session(request)
        payload, kind = await fetch_system(session.token)
        if kind == "invalid":
            session_store.revoke(request.cookies.get(settings.cookie_name))
            raise HTTPException(status_code=401, detail="Upstream rejected credentials")
        if kind == "unavailable":
            return templates.TemplateResponse(
                request, "partials/overview.html",
                {"error": "Monitoring server unavailable or degraded.", "snapshot": None},
                status_code=503,
            )
        return templates.TemplateResponse(
            request, "partials/overview.html",
            {"error": None, "snapshot": payload},
        )

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="127.0.0.1", port=8080)
