# Linux Monitor Web

Modern, responsive HTMX + CSS dashboard for the Linux Monitor server.

## Setup

```bash
cd webapp
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
LINUX_MONITOR_API_URL=http://127.0.0.1:8000 python app.py
```

Or with uvicorn:

```bash
LINUX_MONITOR_API_URL=http://127.0.0.1:8000 uvicorn app:app --host 127.0.0.1 --port 8080
```

Default bind is `127.0.0.1:8080`.

## Configuration

- `LINUX_MONITOR_API_URL`: fixed upstream Linux Monitor server URL (default `http://127.0.0.1:8000`). Set at startup only.
- `LINUX_MONITOR_SESSION_TTL`: session idle expiry in seconds (default `1800`).
- `LINUX_MONITOR_MAX_SESSIONS`: maximum stored sessions (default `1000`).

The web app does not accept a user-controlled upstream target and does not proxy arbitrary requests.

## Authentication

Open the app, choose **Connect**, and paste a reader or admin bearer token. The token is validated once with `GET /api/v1/system`, then kept in server memory in a bounded, expiring per-browser session. The browser receives only an opaque, `HttpOnly`, `SameSite=Strict` cookie (secure when served over HTTPS). Use **Disconnect** to revoke the session.

## Tests

```bash
pytest
```
