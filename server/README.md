# Linux Monitor Server

FastAPI service that exposes a point-in-time system monitoring snapshot and controlled
update/power operations for a single Ubuntu host. It runs unprivileged behind Tailscale;
privileged work is delegated to a fixed root-owned helper.

## Features

- Public liveness probe: `GET /health/live`
- Authenticated monitoring snapshot: `GET /api/v1/system`
- Administrator-only update checks and applies as tracked jobs
- Administrator-only scheduled reboot/shutdown with a cancellation window
- Persistent SQLite job, power-action, and audit state
- Standard JSON error envelope with request IDs

## Development

Requires Python 3.10+.

```bash
cd red/server
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
```

Run the server locally (docs are opt-in):

```bash
READER_TOKEN="$(openssl rand -hex 32)" \
ADMIN_TOKEN="$(openssl rand -hex 32)" \
HOST=127.0.0.1 PORT=8000 DOCS_ENABLED=true \
DATABASE_PATH=./linux-monitor.db \
  .venv/bin/uvicorn linux_monitor.asgi:app --reload
```

`DATABASE_PATH` points at a local development database (`./linux-monitor.db`); keep it
local and do not commit it. Control endpoints (updates and power actions) require the
privileged helper and sudoers from the deployment guide; without that deployment they
fail safely. Never run the API as root.

Without installation, tests can run with `PYTHONPATH=src pytest -q`.

## Production

- Deployment guide: `docs/deployment.md`
- Operations and recovery: `docs/operations.md`
- API reference: `docs/api.md`
- Privileged helper decision: `docs/adr/0001-use-a-fixed-privileged-helper.md`

## Security warning

This service uses direct HTTP. Transport encryption is provided by Tailscale WireGuard,
not by the application. Do not expose port 8000 to the public internet or to untrusted
networks. Restrict clients with Tailscale ACLs to the server's port 8000. Reader and
admin bearer tokens are long-lived secrets; store them only in the root-owned
`/etc/linux-monitor/server.env`, rotate them by editing that file and restarting the
service, and never commit them. The service account has no sudo rights except the exact
fixed helper path `/usr/local/libexec/linux-monitor-privileged`. Future Android clients
will need a cleartext HTTP exception for the Tailscale address, but the Android app is
otherwise unchanged.
