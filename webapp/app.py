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

    ZERO_JOB_ID = "00000000-0000-0000-0000-000000000000"

    def _error_detail(response: httpx.Response) -> str:
        try:
            data = response.json()
            err = data.get("error", {}) if isinstance(data, dict) else {}
            code = err.get("code") if isinstance(err, dict) else None
            msg = err.get("message") if isinstance(err, dict) else None
            if code and msg:
                return f"{code}: {msg}"
            if msg:
                return str(msg)
            if code:
                return str(code)
        except (ValueError, AttributeError):
            pass
        text = (response.text or "").strip()
        return text if text else f"HTTP {response.status_code}"

    async def fetch_job(token: str, job_id: str) -> tuple[Optional[dict], str, str]:
        try:
            response = await upstream.get(
                f"/api/v1/jobs/{job_id}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=httpx.Timeout(10.0),
            )
        except httpx.HTTPError:
            return None, "unavailable", "Monitoring server unavailable."
        if response.status_code == 401:
            return None, "unauthorized", _error_detail(response)
        if response.status_code == 403:
            return None, "forbidden", _error_detail(response)
        if response.status_code == 404:
            return None, "not_found", _error_detail(response)
        if not response.is_success:
            return None, "unavailable", _error_detail(response)
        try:
            return response.json(), "ok", ""
        except ValueError:
            return None, "unavailable", "Invalid response from monitoring server."

    async def fetch_power(token: str, action_id: str) -> tuple[Optional[dict], str, str]:
        try:
            response = await upstream.get(
                f"/api/v1/power-actions/{action_id}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=httpx.Timeout(10.0),
            )
        except httpx.HTTPError:
            return None, "unavailable", "Monitoring server unavailable."
        if response.status_code == 401:
            return None, "unauthorized", _error_detail(response)
        if response.status_code == 403:
            return None, "forbidden", _error_detail(response)
        if response.status_code == 404:
            return None, "not_found", _error_detail(response)
        if not response.is_success:
            return None, "unavailable", _error_detail(response)
        try:
            return response.json(), "ok", ""
        except ValueError:
            return None, "unavailable", "Invalid response from monitoring server."

    async def create_update_job(token: str, kind: str) -> tuple[Optional[dict], str, str]:
        path = "/api/v1/updates/check" if kind == "check" else "/api/v1/updates/apply"
        try:
            response = await upstream.post(
                path, headers={"Authorization": f"Bearer {token}"}, timeout=httpx.Timeout(10.0)
            )
        except httpx.HTTPError:
            return None, "unavailable", "Monitoring server unavailable."
        if response.status_code == 401:
            return None, "unauthorized", _error_detail(response)
        if response.status_code == 403:
            return None, "forbidden", _error_detail(response)
        if response.status_code == 404:
            return None, "not_found", _error_detail(response)
        if response.status_code == 409:
            return None, "conflict", _error_detail(response)
        if response.status_code == 422:
            return None, "invalid", _error_detail(response)
        if response.status_code in (503, 504):
            return None, "unavailable", _error_detail(response)
        if not response.is_success:
            return None, "unavailable", _error_detail(response)
        try:
            return response.json(), "ok", ""
        except ValueError:
            return None, "unavailable", "Invalid response from monitoring server."

    async def create_power_action(token: str, action: str, delay: int, confirmation: str) -> tuple[Optional[dict], str, str]:
        try:
            response = await upstream.post(
                "/api/v1/power-actions",
                headers={"Authorization": f"Bearer {token}"},
                json={"action": action, "delay_seconds": delay, "confirmation": confirmation},
                timeout=httpx.Timeout(120.0),
            )
        except httpx.HTTPError:
            return None, "unavailable", "Monitoring server unavailable."
        if response.status_code == 401:
            return None, "unauthorized", _error_detail(response)
        if response.status_code == 403:
            return None, "forbidden", _error_detail(response)
        if response.status_code == 404:
            return None, "not_found", _error_detail(response)
        if response.status_code == 409:
            return None, "conflict", _error_detail(response)
        if response.status_code == 422:
            return None, "invalid", _error_detail(response)
        if response.status_code in (503, 504):
            return None, "unavailable", _error_detail(response)
        if not response.is_success:
            return None, "unavailable", _error_detail(response)
        try:
            return response.json(), "ok", ""
        except ValueError:
            return None, "unavailable", "Invalid response from monitoring server."

    async def cancel_power_action(token: str, action_id: str) -> tuple[Optional[dict], str, str]:
        try:
            response = await upstream.delete(
                f"/api/v1/power-actions/{action_id}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=httpx.Timeout(10.0),
            )
        except httpx.HTTPError:
            return None, "unavailable", "Monitoring server unavailable."
        if response.status_code == 401:
            return None, "unauthorized", _error_detail(response)
        if response.status_code == 403:
            return None, "forbidden", _error_detail(response)
        if response.status_code == 404:
            return None, "not_found", _error_detail(response)
        if response.status_code == 409:
            return None, "conflict", _error_detail(response)
        if response.status_code == 422:
            return None, "invalid", _error_detail(response)
        if response.status_code in (503, 504):
            return None, "unavailable", _error_detail(response)
        if not response.is_success:
            return None, "unavailable", _error_detail(response)
        try:
            return response.json(), "ok", ""
        except ValueError:
            return None, "unavailable", "Invalid response from monitoring server."

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
            response = templates.TemplateResponse(
                request, "partials/overview.html",
                {"error": "Monitoring server unavailable or degraded.", "snapshot": None},
                status_code=503,
            )
            if request.headers.get("HX-Request"):
                response.headers["HX-Reswap"] = "innerHTML"
            return response
        return templates.TemplateResponse(
            request, "partials/overview.html",
            {"error": None, "snapshot": payload},
        )

    def _is_hx(request: Request) -> bool:
        return bool(request.headers.get("HX-Request"))

    def _session_or_401(request: Request) -> Session:
        session = get_session(request)
        if session is None:
            raise HTTPException(status_code=401, detail="Session expired or missing")
        return session

    async def _control_context(request: Request, session: Session) -> dict[str, Any]:
        # Determine reader vs admin using harmless job lookup.
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
        elif kind == "not_found":
            role = "admin"
        else:
            role = "unknown"
            unavailable = True
            error = detail or "Monitoring server unavailable."
        # Retain ids: fetch current status when present.
        if job_id:
            jdata, jkind, jdetail = await fetch_job(session.token, job_id)
            if jkind == "unauthorized":
                session_store.revoke(request.cookies.get(settings.cookie_name))
                raise HTTPException(status_code=401, detail="Upstream rejected credentials")
            if jkind == "not_found":
                session.last_update_job_id = None
                job_id = None
                job = None
            elif jkind == "ok":
                job = jdata
            else:
                # keep id; surface error via job None and error? store last error in job_error
                pass
        if power_id:
            pdata, pkind, pdetail = await fetch_power(session.token, power_id)
            if pkind == "unauthorized":
                session_store.revoke(request.cookies.get(settings.cookie_name))
                raise HTTPException(status_code=401, detail="Upstream rejected credentials")
            if pkind == "not_found":
                session.last_power_action_id = None
                power_id = None
                power = None
            elif pkind == "ok":
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

    @app.get("/control/jobs/{job_id}", response_class=HTMLResponse)
    async def control_job_status(request: Request, job_id: str) -> Any:
        session = _session_or_401(request)
        data, kind, detail = await fetch_job(session.token, job_id)
        if kind == "unauthorized":
            session_store.revoke(request.cookies.get(settings.cookie_name))
            raise HTTPException(status_code=401, detail="Upstream rejected credentials")
        if kind == "not_found":
            session.last_update_job_id = None
            return templates.TemplateResponse(
                request, "partials/job_status.html",
                {"job": None, "error": detail or "Operation not found."},
            )
        if kind != "ok":
            return templates.TemplateResponse(
                request, "partials/job_status.html",
                {"job": None, "error": detail or "Operation unavailable."},
            )
        session.last_update_job_id = job_id
        return templates.TemplateResponse(
            request, "partials/job_status.html", {"job": data, "error": None}
        )

    @app.get("/control/power-actions/{action_id}", response_class=HTMLResponse)
    async def control_power_status(request: Request, action_id: str) -> Any:
        session = _session_or_401(request)
        data, kind, detail = await fetch_power(session.token, action_id)
        if kind == "unauthorized":
            session_store.revoke(request.cookies.get(settings.cookie_name))
            raise HTTPException(status_code=401, detail="Upstream rejected credentials")
        if kind == "not_found":
            session.last_power_action_id = None
            return templates.TemplateResponse(
                request, "partials/power_status.html",
                {"power": None, "error": detail or "Power action not found."},
            )
        if kind != "ok":
            return templates.TemplateResponse(
                request, "partials/power_status.html",
                {"power": None, "error": detail or "Power action unavailable."},
            )
        session.last_power_action_id = action_id
        return templates.TemplateResponse(
            request, "partials/power_status.html", {"power": data, "error": None}
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
                    {"job": None, "error": msg}, status_code=200,
                )
            return RedirectResponse("/control", status_code=303)
        session.last_update_job_id = data.get("id")
        if hx:
            return templates.TemplateResponse(
                request, "partials/job_status.html", {"job": data, "error": None}
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
        confirm = str(form.get("confirm") or form.get("confirm_update") or "").strip().lower()
        if confirm not in ("yes", "on", "true", "install"):
            msg = "Confirmation required: check the box to install updates."
            if hx:
                return templates.TemplateResponse(
                    request, "partials/job_status.html",
                    {"job": None, "error": msg}, status_code=200,
                )
            # non-HTMX: render control page with error
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
                    {"job": None, "error": msg}, status_code=200,
                )
            ctx = await _control_context(request, session)
            ctx["error"] = msg
            return templates.TemplateResponse(request, "control.html", ctx, status_code=400)
        session.last_update_job_id = data.get("id")
        if hx:
            return templates.TemplateResponse(
                request, "partials/job_status.html", {"job": data, "error": None}
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
                    {"power": None, "error": msg}, status_code=200,
                )
            ctx = await _control_context(request, session)
            ctx["error"] = msg
            return templates.TemplateResponse(request, "control.html", ctx, status_code=400)
        # delay validation
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
                    {"power": None, "error": msg}, status_code=200,
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
                    {"power": None, "error": msg}, status_code=200,
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
                    {"power": None, "error": msg}, status_code=200,
                )
            ctx = await _control_context(request, session)
            ctx["error"] = msg
            return templates.TemplateResponse(request, "control.html", ctx, status_code=400)
        session.last_power_action_id = data.get("id")
        if hx:
            return templates.TemplateResponse(
                request, "partials/power_status.html", {"power": data, "error": None}
            )
        return RedirectResponse("/control", status_code=303)

    @app.post("/control/power-actions/{action_id}/cancel", response_class=HTMLResponse)
    async def control_power_cancel(request: Request, action_id: str) -> Any:
        if not _origin_ok(request):
            raise HTTPException(status_code=403, detail="Cross-origin request rejected")
        session = _session_or_401(request)
        hx = _is_hx(request)
        data, kind, detail = await cancel_power_action(session.token, action_id)
        if kind == "unauthorized":
            session_store.revoke(request.cookies.get(settings.cookie_name))
            raise HTTPException(status_code=401, detail="Upstream rejected credentials")
        if kind != "ok":
            msg = detail or "Cancel failed."
            if kind == "conflict":
                msg = msg or "Action is no longer cancellable."
            if hx:
                return templates.TemplateResponse(
                    request, "partials/power_status.html",
                    {"power": None, "error": msg}, status_code=200,
                )
            ctx = await _control_context(request, session)
            ctx["error"] = msg
            return templates.TemplateResponse(request, "control.html", ctx, status_code=400)
        if hx:
            return templates.TemplateResponse(
                request, "partials/power_status.html", {"power": data, "error": None}
            )
        return RedirectResponse("/control", status_code=303)

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="127.0.0.1", port=8080)
