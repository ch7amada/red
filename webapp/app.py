"""Linux Monitor web adapter (FastAPI + Jinja + HTMX)."""

from __future__ import annotations

import os
import secrets
import threading
import time
import uuid
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
    last_update_job_id: Optional[str] = None
    last_power_action_id: Optional[str] = None


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


def _is_uuid(value: Any) -> bool:
    try:
        uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return False
    return True


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
            limits=httpx.Limits(keepalive_expiry=2.0),
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

    def _error_detail(response: httpx.Response) -> str:
        try:
            data = response.json()
            if isinstance(data, dict):
                err = data.get("error", {})
                if isinstance(err, dict):
                    code = err.get("code")
                    msg = err.get("message")
                    if code and msg:
                        return f"{code}: {msg}"
                    if msg:
                        return str(msg)
                    if code:
                        return str(code)
        except (ValueError, AttributeError, TypeError):
            pass
        return f"HTTP {response.status_code}"

    async def _call(
        token: str,
        method: str,
        path: str,
        *,
        timeout: float = 10.0,
        json_body: Optional[dict] = None,
    ) -> tuple[Optional[dict], str, str]:
        try:
            response = await upstream.request(
                method,
                path,
                headers={"Authorization": f"Bearer {token}"},
                timeout=httpx.Timeout(timeout),
                json=json_body,
            )
        except httpx.HTTPError:
            return None, "unavailable", "Monitoring server unavailable."
        status = response.status_code
        data: Optional[dict] = None
        parsed_object = False
        if response.content:
            try:
                parsed = response.json()
                if isinstance(parsed, dict):
                    data = parsed
                    parsed_object = True
            except (ValueError, TypeError):
                pass
        if status == 401:
            kind = "unauthorized"
        elif status == 403:
            kind = "forbidden"
        elif status == 404:
            kind = "not_found"
        elif status == 409:
            kind = "conflict"
        elif status == 422:
            kind = "invalid"
        elif status in (503, 504):
            kind = "unavailable"
        elif 200 <= status < 300:
            kind = "ok"
        else:
            kind = "unavailable"
        if kind == "ok":
            if not parsed_object:
                return None, "unavailable", "Invalid response from monitoring server."
            return data, "ok", ""
        detail = _error_detail(response)
        return None, kind, detail if detail else f"HTTP {status}"

    async def fetch_system(token: str, include_llama_context: bool = False) -> tuple[Optional[dict], str]:
        path = "/api/v1/system?include_llama_context=true" if include_llama_context else "/api/v1/system"
        data, kind, _ = await _call(token, "GET", path, timeout=10.0)
        if kind == "ok":
            return data, ""
        if kind in ("unauthorized", "forbidden"):
            return None, "invalid"
        return None, "unavailable"

    ZERO_JOB_ID = "00000000-0000-0000-0000-000000000000"

    async def fetch_job(token: str, job_id: str) -> tuple[Optional[dict], str, str]:
        if not _is_uuid(job_id):
            return None, "not_found", "Job not found."
        return await _call(token, "GET", f"/api/v1/jobs/{job_id}", timeout=10.0)

    async def fetch_power(token: str, action_id: str) -> tuple[Optional[dict], str, str]:
        if not _is_uuid(action_id):
            return None, "not_found", "Power action not found."
        return await _call(token, "GET", f"/api/v1/power-actions/{action_id}", timeout=10.0)

    async def create_update_job(token: str, kind: str) -> tuple[Optional[dict], str, str]:
        path = "/api/v1/updates/check" if kind == "check" else "/api/v1/updates/apply"
        return await _call(token, "POST", path, timeout=10.0)

    async def create_power_action(token: str, action: str, delay: int, confirmation: str) -> tuple[Optional[dict], str, str]:
        return await _call(
            token,
            "POST",
            "/api/v1/power-actions",
            timeout=120.0,
            json_body={"action": action, "delay_seconds": delay, "confirmation": confirmation},
        )

    async def cancel_power_action(token: str, action_id: str) -> tuple[Optional[dict], str, str]:
        if not _is_uuid(action_id):
            return None, "not_found", "Power action not found."
        return await _call(token, "DELETE", f"/api/v1/power-actions/{action_id}", timeout=120.0)

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
                request, "connect.html",
                {"error": "Token is required."},
                status_code=400,
            )
        if any(ord(ch) < 0x21 or ord(ch) > 0x7E for ch in token):
            return templates.TemplateResponse(
                request, "connect.html",
                {"error": "Token must contain only visible ASCII characters."},
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
        return await _render_system_fragment(request, session, "partials/overview.html")

    def _is_hx(request: Request) -> bool:
        return bool(request.headers.get("HX-Request"))

    async def _render_system_fragment(
        request: Request,
        session: Session,
        template_name: str,
        *,
        include_llama_context: bool = False,
    ) -> Any:
        payload, kind = await fetch_system(session.token, include_llama_context=include_llama_context)
        if kind == "invalid":
            session_store.revoke(request.cookies.get(settings.cookie_name))
            raise HTTPException(status_code=401, detail="Upstream rejected credentials")
        if kind == "unavailable":
            hx = _is_hx(request)
            status_code = 200 if hx else 503
            response = templates.TemplateResponse(
                request, template_name,
                {"error": "Monitoring server unavailable or degraded.", "snapshot": None},
                status_code=status_code,
            )
            if hx:
                response.headers["HX-Reswap"] = "innerHTML"
            return response
        return templates.TemplateResponse(
            request, template_name,
            {"error": None, "snapshot": payload},
        )

    def _session_or_401(request: Request) -> Session:
        session = get_session(request)
        if session is None:
            raise HTTPException(status_code=401, detail="Session expired or missing")
        return session

    async def _control_context(request: Request, session: Session) -> dict[str, Any]:
        job_id = session.last_update_job_id
        power_id = session.last_power_action_id
        job = None
        power = None
        role = "admin"
        error = None
        unavailable = False
        data, kind, detail = await fetch_job(session.token, ZERO_JOB_ID)
        if kind == "unauthorized":
            session_store.revoke(request.cookies.get(settings.cookie_name))
            raise HTTPException(status_code=401, detail="Upstream rejected credentials")
        if kind == "forbidden":
            role = "reader"
        elif kind == "not_found" and str(detail).startswith("job_not_found:"):
            role = "admin"
        else:
            role = "unknown"
            unavailable = True
            error = detail or "Monitoring server unavailable."
        if job_id and _is_uuid(job_id):
            jdata, jkind, jdetail = await fetch_job(session.token, job_id)
            if jkind == "unauthorized":
                session_store.revoke(request.cookies.get(settings.cookie_name))
                raise HTTPException(status_code=401, detail="Upstream rejected credentials")
            if jkind == "ok":
                job = jdata
        if power_id and _is_uuid(power_id):
            pdata, pkind, pdetail = await fetch_power(session.token, power_id)
            if pkind == "unauthorized":
                session_store.revoke(request.cookies.get(settings.cookie_name))
                raise HTTPException(status_code=401, detail="Upstream rejected credentials")
            if pkind == "ok":
                power = pdata
        return {
            "role": role,
            "error": error,
            "unavailable": unavailable,
            "job_id": job_id,
            "power_id": power_id,
            "job": job,
            "power": power,
        }

    @app.get("/control", response_class=HTMLResponse)
    async def control_page(request: Request) -> Any:
        session = _session_or_401(request)
        ctx = await _control_context(request, session)
        return templates.TemplateResponse(request, "control.html", ctx)

    @app.get("/docker", response_class=HTMLResponse)
    async def docker_page(request: Request) -> Any:
        _session_or_401(request)
        return templates.TemplateResponse(request, "docker.html", {})

    @app.get("/llama", response_class=HTMLResponse)
    async def llama_page(request: Request) -> Any:
        _session_or_401(request)
        return templates.TemplateResponse(request, "llama.html", {})

    @app.get("/fragments/docker", response_class=HTMLResponse)
    async def docker_fragment(request: Request) -> Any:
        session = require_session(request)
        return await _render_system_fragment(request, session, "partials/docker.html")

    @app.get("/fragments/llama", response_class=HTMLResponse)
    async def llama_fragment(request: Request) -> Any:
        session = require_session(request)
        return await _render_system_fragment(request, session, "partials/llama.html")

    @app.get("/fragments/llama/context", response_class=HTMLResponse)
    async def llama_context_fragment(request: Request) -> Any:
        session = require_session(request)
        return await _render_system_fragment(
            request, session, "partials/llama_context.html", include_llama_context=True
        )

    @app.get("/control/jobs/{job_id}", response_class=HTMLResponse)
    async def control_job_status(request: Request, job_id: str) -> Any:
        session = _session_or_401(request)
        if not _is_uuid(job_id):
            return templates.TemplateResponse(
                request, "partials/job_status.html",
                {"job": None, "error": "Invalid operation id.", "job_id": None},
                status_code=400,
            )
        data, kind, detail = await fetch_job(session.token, job_id)
        if kind == "unauthorized":
            session_store.revoke(request.cookies.get(settings.cookie_name))
            raise HTTPException(status_code=401, detail="Upstream rejected credentials")
        if kind == "not_found":
            if session.last_update_job_id == job_id:
                session.last_update_job_id = None
            return templates.TemplateResponse(
                request, "partials/job_status.html",
                {"job": None, "error": detail or "Operation not found.", "job_id": None},
                status_code=200,
            )
        if kind == "forbidden":
            return templates.TemplateResponse(
                request, "partials/job_status.html",
                {"job": None, "error": detail or "Operation forbidden.", "job_id": None},
                status_code=200,
            )
        if kind != "ok":
            return templates.TemplateResponse(
                request, "partials/job_status.html",
                {"job": None, "error": detail or "Operation unavailable.", "job_id": job_id},
                status_code=200,
            )
        return templates.TemplateResponse(
            request, "partials/job_status.html",
            {"job": data, "error": None, "job_id": job_id},
        )

    @app.get("/control/power-actions/{action_id}", response_class=HTMLResponse)
    async def control_power_status(request: Request, action_id: str) -> Any:
        session = _session_or_401(request)
        if not _is_uuid(action_id):
            return templates.TemplateResponse(
                request, "partials/power_status.html",
                {"power": None, "error": "Invalid power action id.", "action_id": None},
                status_code=400,
            )
        data, kind, detail = await fetch_power(session.token, action_id)
        if kind == "unauthorized":
            session_store.revoke(request.cookies.get(settings.cookie_name))
            raise HTTPException(status_code=401, detail="Upstream rejected credentials")
        if kind == "not_found":
            if session.last_power_action_id == action_id:
                session.last_power_action_id = None
            return templates.TemplateResponse(
                request, "partials/power_status.html",
                {"power": None, "error": detail or "Power action not found.", "action_id": None},
                status_code=200,
            )
        if kind == "forbidden":
            return templates.TemplateResponse(
                request, "partials/power_status.html",
                {"power": None, "error": detail or "Power action forbidden.", "action_id": None},
                status_code=200,
            )
        if kind != "ok":
            return templates.TemplateResponse(
                request, "partials/power_status.html",
                {"power": None, "error": detail or "Power action unavailable.", "action_id": action_id},
                status_code=200,
            )
        return templates.TemplateResponse(
            request, "partials/power_status.html",
            {"power": data, "error": None, "action_id": action_id},
        )

    async def _handle_updates_check(request: Request, session: Session) -> Any:
        hx = _is_hx(request)
        data, kind, detail = await create_update_job(session.token, "check")
        if kind == "unauthorized":
            session_store.revoke(request.cookies.get(settings.cookie_name))
            raise HTTPException(status_code=401, detail="Upstream rejected credentials")
        if kind != "ok":
            msg = detail or "Update check failed."
            if kind == "forbidden":
                msg = "Admin token required for update checks."
            if kind == "conflict":
                msg = msg or "Operation conflict."
            if hx:
                return templates.TemplateResponse(
                    request, "partials/job_status.html",
                    {"job": None, "error": msg, "job_id": None},
                    status_code=200,
                )
            ctx = await _control_context(request, session)
            ctx["error"] = msg
            return templates.TemplateResponse(request, "control.html", ctx, status_code=400)
        session.last_update_job_id = data.get("id")
        if hx:
            return templates.TemplateResponse(
                request, "partials/job_status.html",
                {"job": data, "error": None, "job_id": data.get("id")},
            )
        return RedirectResponse("/control", status_code=303)

    @app.post("/control/updates/check", response_class=HTMLResponse)
    async def control_updates_check(request: Request) -> Any:
        if not _origin_ok(request):
            raise HTTPException(status_code=403, detail="Cross-origin request rejected")
        session = _session_or_401(request)
        return await _handle_updates_check(request, session)

    async def _handle_updates_apply(request: Request, session: Session) -> Any:
        hx = _is_hx(request)
        form = await request.form()
        confirm = form.get("confirm")
        if confirm != "yes":
            msg = "Confirmation required: check the box to install updates."
            if hx:
                return templates.TemplateResponse(
                    request, "partials/job_status.html",
                    {"job": None, "error": msg, "job_id": None},
                    status_code=200,
                )
            ctx = await _control_context(request, session)
            ctx["error"] = msg
            return templates.TemplateResponse(request, "control.html", ctx, status_code=400)
        data, kind, detail = await create_update_job(session.token, "apply")
        if kind == "unauthorized":
            session_store.revoke(request.cookies.get(settings.cookie_name))
            raise HTTPException(status_code=401, detail="Upstream rejected credentials")
        if kind != "ok":
            msg = detail or "Update install failed."
            if kind == "forbidden":
                msg = "Admin token required to install updates."
            if kind == "conflict":
                msg = msg or "Operation conflict."
            if hx:
                return templates.TemplateResponse(
                    request, "partials/job_status.html",
                    {"job": None, "error": msg, "job_id": None},
                    status_code=200,
                )
            ctx = await _control_context(request, session)
            ctx["error"] = msg
            return templates.TemplateResponse(request, "control.html", ctx, status_code=400)
        session.last_update_job_id = data.get("id")
        if hx:
            return templates.TemplateResponse(
                request, "partials/job_status.html",
                {"job": data, "error": None, "job_id": data.get("id")},
            )
        return RedirectResponse("/control", status_code=303)

    @app.post("/control/updates/apply", response_class=HTMLResponse)
    async def control_updates_apply(request: Request) -> Any:
        if not _origin_ok(request):
            raise HTTPException(status_code=403, detail="Cross-origin request rejected")
        session = _session_or_401(request)
        return await _handle_updates_apply(request, session)

    @app.post("/control/power-actions", response_class=HTMLResponse)
    async def control_power_create(request: Request) -> Any:
        if not _origin_ok(request):
            raise HTTPException(status_code=403, detail="Cross-origin request rejected")
        session = _session_or_401(request)
        hx = _is_hx(request)
        form = await request.form()
        action = str(form.get("action") or "").strip().lower()
        if action not in ("reboot", "shutdown"):
            msg = "Invalid power action."
            if hx:
                return templates.TemplateResponse(
                    request, "partials/power_status.html",
                    {"power": None, "error": msg, "action_id": None},
                    status_code=200,
                )
            ctx = await _control_context(request, session)
            ctx["error"] = msg
            return templates.TemplateResponse(request, "control.html", ctx, status_code=400)
        raw_delay = form.get("delay_seconds")
        try:
            delay = int(str(raw_delay).strip()) if raw_delay is not None and str(raw_delay).strip() != "" else 60
        except (TypeError, ValueError):
            delay = -1
        if delay < 10 or delay > 3600:
            msg = "Delay must be between 10 and 3600 seconds."
            if hx:
                return templates.TemplateResponse(
                    request, "partials/power_status.html",
                    {"power": None, "error": msg, "action_id": None},
                    status_code=200,
                )
            ctx = await _control_context(request, session)
            ctx["error"] = msg
            return templates.TemplateResponse(request, "control.html", ctx, status_code=400)
        confirmation = str(form.get("confirmation") or "").strip()
        if confirmation != action:
            msg = "Confirmation must exactly match the action."
            if hx:
                return templates.TemplateResponse(
                    request, "partials/power_status.html",
                    {"power": None, "error": msg, "action_id": None},
                    status_code=200,
                )
            ctx = await _control_context(request, session)
            ctx["error"] = msg
            return templates.TemplateResponse(request, "control.html", ctx, status_code=400)

        data, kind, detail = await create_power_action(session.token, action, delay, confirmation)
        if kind == "unauthorized":
            session_store.revoke(request.cookies.get(settings.cookie_name))
            raise HTTPException(status_code=401, detail="Upstream rejected credentials")
        if kind != "ok":
            msg = detail or "Power action failed."
            if kind == "forbidden":
                msg = "Admin token required for power actions."
            if kind == "conflict":
                msg = msg or "Operation conflict."
            if hx:
                return templates.TemplateResponse(
                    request, "partials/power_status.html",
                    {"power": None, "error": msg, "action_id": None},
                    status_code=200,
                )
            ctx = await _control_context(request, session)
            ctx["error"] = msg
            return templates.TemplateResponse(request, "control.html", ctx, status_code=400)
        session.last_power_action_id = data.get("id")
        if hx:
            return templates.TemplateResponse(
                request, "partials/power_status.html",
                {"power": data, "error": None, "action_id": data.get("id")},
            )
        return RedirectResponse("/control", status_code=303)

    @app.post("/control/power-actions/{action_id}/cancel", response_class=HTMLResponse)
    async def control_power_cancel(request: Request, action_id: str) -> Any:
        if not _origin_ok(request):
            raise HTTPException(status_code=403, detail="Cross-origin request rejected")
        session = _session_or_401(request)
        hx = _is_hx(request)
        if not _is_uuid(action_id):
            msg = "Invalid power action id."
            if hx:
                return templates.TemplateResponse(
                    request, "partials/power_status.html",
                    {"power": None, "error": msg, "action_id": action_id},
                    status_code=200,
                )
            ctx = await _control_context(request, session)
            ctx["error"] = msg
            return templates.TemplateResponse(request, "control.html", ctx, status_code=400)
        if session.last_power_action_id != action_id:
            msg = "Not the tracked power action."
            if hx:
                return templates.TemplateResponse(
                    request, "partials/power_status.html",
                    {"power": None, "error": msg, "action_id": action_id},
                    status_code=409,
                )
            ctx = await _control_context(request, session)
            ctx["error"] = msg
            return templates.TemplateResponse(request, "control.html", ctx, status_code=409)
        data, kind, detail = await cancel_power_action(session.token, action_id)
        if kind == "unauthorized":
            session_store.revoke(request.cookies.get(settings.cookie_name))
            raise HTTPException(status_code=401, detail="Upstream rejected credentials")
        if kind != "ok":
            msg = detail or "Cancel failed."
            if kind == "conflict":
                msg = msg or "Action is no longer cancellable."
            current, ckind, _ = await fetch_power(session.token, action_id)
            if hx:
                if ckind == "ok" and current is not None:
                    return templates.TemplateResponse(
                        request, "partials/power_status.html",
                        {"power": current, "error": msg, "action_id": action_id},
                        status_code=200,
                    )
                return templates.TemplateResponse(
                    request, "partials/power_status.html",
                    {"power": None, "error": msg, "action_id": action_id},
                    status_code=200,
                )
            ctx = await _control_context(request, session)
            ctx["error"] = msg
            return templates.TemplateResponse(request, "control.html", ctx, status_code=400)
        if hx:
            return templates.TemplateResponse(
                request, "partials/power_status.html",
                {"power": data, "error": None, "action_id": data.get("id") if isinstance(data, dict) else action_id},
            )
        return RedirectResponse("/control", status_code=303)

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="127.0.0.1", port=8080)
