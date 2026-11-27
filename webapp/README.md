# Linux Monitor Web

Modern, responsive HTMX + CSS dashboard for the Linux Monitor server.

## Setup

```bash
cd webapp
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run locally for development

```bash
LINUX_MONITOR_API_URL=http://127.0.0.1:8000 python app.py
```

Or with uvicorn:

```bash
LINUX_MONITOR_API_URL=http://127.0.0.1:8000 uvicorn app:app --host 127.0.0.1 --port 8080
```

Default bind is `127.0.0.1:8080`.

For access over Tailscale and automatic startup at boot, follow the
[dashboard runbook](../README.md#3-start-the-dashboard-on-tailscale-and-enable-it-at-boot).

## Configuration

- `LINUX_MONITOR_API_URL`: fixed upstream Linux Monitor server URL (default `http://127.0.0.1:8000`). Set at startup only.
- `LINUX_MONITOR_SESSION_TTL`: session idle expiry in seconds (default `1800`).
- `LINUX_MONITOR_MAX_SESSIONS`: maximum stored sessions (default `1000`).

The web app does not accept a user-controlled upstream target and does not proxy arbitrary requests.

## Authentication and roles

Open the app, choose **Connect**, and paste a reader or admin bearer token. The token is validated once with `GET /api/v1/system`, then kept in server memory in a bounded, expiring per-browser session. The browser receives only an opaque, `HttpOnly`, `SameSite=Strict` cookie (secure when served over HTTPS). Use **Disconnect** to revoke the session.

Tokens must contain only visible ASCII characters. Reader tokens can view dashboards; admin tokens can run update and power actions.

## Control page

Control confirms and tracks active jobs and power actions per browser session. Update and power mutations require an admin token and exact confirmation (checkbox value `yes` for updates, typed action name for power actions). The latest job/action ID is recorded only when an operation is created; polling and status views do not overwrite or clear newer IDs. Cancel is allowed only for the currently tracked power action.

## Session storage and expiry

Sessions are stored in server memory with an idle TTL. The cookie is a browser session cookie, so expiry is enforced by the memory store rather than a fixed client-side deadline. Active polling keeps a session alive. Server restarts clear all sessions and tracked job/action IDs; users reconnect afterward.

## Single-worker limits

The in-memory session store is process-local. Run a single worker/process for consistent session and job tracking.

## HTTPS proxy

When deployed behind a proxy, preserve the original `Host` header and trusted scheme so origin checks and secure cookies work correctly (for example, `X-Forwarded-Proto` handling at the proxy). The app trusts the request URL scheme for cookie security.

## Tests

```bash
pytest
```
