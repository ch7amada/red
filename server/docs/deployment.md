# Deployment Guide

Target: Ubuntu 22.04 or 24.04, Python 3.10+, systemd, direct HTTP over Tailscale
with optional trusted LAN access.

## Architecture

- `HOST` controls the Uvicorn bind address. The installer uses the Tailscale IPv4
  address when available unless you set `HOST` explicitly.
- Default port is `8000`; change `PORT` in the environment file.
- Tailscale WireGuard supplies transport encryption. There is no HTTPS, Caddy,
  `tailscale serve`, or Tailscale SSH in this design.
- Restrict Tailscale access to authorized clients on the configured API port.
- The API process runs as the unprivileged `linux-monitor` account.
- Privileged APT and power work runs through `/usr/bin/sudo -n
  /usr/local/libexec/linux-monitor-privileged`, which validates a fixed operation set.

## Prerequisites

- Tailscale installed and connected; note the node's `100.x` IPv4 address.
- Root access for installation only.
- Outbound network access for Python package installation.

## Files

- Application: `/opt/linux-monitor` (virtualenv at `/opt/linux-monitor/.venv`)
- Environment: `/etc/linux-monitor/server.env` (`root:linux-monitor`, mode `0640`)
- Database: `/var/lib/linux-monitor/linux-monitor.db`
- Service: `/etc/systemd/system/linux-monitor.service`
- Sudoers: `/etc/sudoers.d/linux-monitor`
- Helper: `/usr/local/libexec/linux-monitor-privileged`

## Environment file

```ini
HOST=100.x.y.z
PORT=8000
DATABASE_PATH=/var/lib/linux-monitor/linux-monitor.db
READER_TOKEN=<at least 32 characters>
ADMIN_TOKEN=<at least 32 characters, distinct from reader>
ENVIRONMENT=production
DOCS_ENABLED=false
```

Generate tokens with `openssl rand -hex 32`. Rotate by editing this file and running
`systemctl restart linux-monitor`.

Optional llama.cpp monitoring uses `LLAMA_CPP_URL`, which defaults to
`http://127.0.0.1:8081`. Set it to an HTTP(S) base URL to point at another
host. `LLAMA_CPP_API_KEY` is an optional bearer token required only when the
upstream llama.cpp server is protected. It is never forwarded across redirects.
Failures degrade safely and do not affect other collectors. The snapshot always
includes a `llama_cpp` status. Context slot sampling is opt-in via
`?include_llama_context=true` (one-shot, resets upstream idle time) and may be
unavailable when the upstream is started with `--no-slots`.

## Repeatable installation

Use `scripts/install.sh` from a checkout of this repository. It is idempotent and does
not execute upgrades or reboot. Review it before running:

```bash
sudo SOURCE_DIR=/path/to/red/server HOST=100.x.y.z bash scripts/install.sh
```

What it does:

1. Installs OS prerequisites (`python3`, `python3-venv`, `python3-pip`, `sudo`). Tailscale is a prerequisite and is not installed by this script.
2. Creates the `linux-monitor` system user and group.
3. Creates `/opt/linux-monitor`, `/var/lib/linux-monitor`, and `/etc/linux-monitor`.
4. Creates a virtualenv and installs this project into `/opt/linux-monitor/.venv`.
5. Installs the root-owned fixed helper at `/usr/local/libexec/linux-monitor-privileged`.
6. Creates `/etc/linux-monitor/server.env` with generated tokens if absent and prints them
   once.
7. Installs and validates `/etc/sudoers.d/linux-monitor` with `visudo -cf`.
8. Installs the systemd unit, runs `daemon-reload`, enables, and starts the service.

If Tailscale is unavailable during install, set `HOST` explicitly. The script defaults
`HOST` to `tailscale ip -4` output and warns if it falls back to `127.0.0.1`.

## Allow direct LAN access

Allow the configured API port only from your trusted LAN and authorized Tailscale
clients. Direct LAN traffic sends bearer tokens over plain HTTP. Keep the port off
public-facing networks and router port forwards.

If UFW is active and blocks incoming LAN traffic, add a rule for your LAN interface
and subnet. Replace the example interface, subnet, and default API port as needed.

```bash
sudo ufw allow in on enp3s0 from 192.168.1.0/24 to any port 8000 proto tcp
```

Allow the same port for the intended tailnet clients in your Tailscale access rules.
For a fresh install, pass `HOST=0.0.0.0` to the installer. On an existing install, run
`sudoedit /etc/linux-monitor/server.env`, set `HOST=0.0.0.0`, and run
`sudo systemctl restart linux-monitor.service`. Keep the existing `PORT` value.

This binds the API to all IPv4 interfaces, including loopback. From each network,
request `/health/live` using the corresponding host IPv4 address and API port.
Expect `{"status":"ok"}`. The dashboard on the API host can continue to use
`127.0.0.1` with that port.

## Systemd unit

```ini
[Unit]
Description=Linux Monitor API server
After=network-online.target tailscaled.service
Wants=network-online.target tailscaled.service

[Service]
Type=simple
User=linux-monitor
Group=linux-monitor
EnvironmentFile=/etc/linux-monitor/server.env
WorkingDirectory=/opt/linux-monitor
ExecStart=/opt/linux-monitor/.venv/bin/uvicorn linux_monitor.asgi:app --host ${HOST} --port ${PORT}
Restart=on-failure
RestartSec=5
TimeoutStopSec=30
StateDirectory=linux-monitor
PrivateTmp=true
ProtectHome=true

[Install]
WantedBy=multi-user.target
```

The service is ordered after `tailscaled.service` and `network-online.target`. It
auto-starts and restarts on failure.

Important: do not add `NoNewPrivileges=yes`, `ProtectSystem=strict` or `full`,
restrictive capability bounding, or equivalent sandbox settings. The service must be able
to invoke the root-owned sudo helper for APT and power actions. Privileged work is
delegated to the fixed helper instead of widening the service's own privileges; see
`docs/adr/0001-use-a-fixed-privileged-helper.md`. `StateDirectory`, `PrivateTmp`, and
`ProtectHome` are retained only where compatible with that model.

## Sudoers

```sudoers
linux-monitor ALL=(root) NOPASSWD: /usr/local/libexec/linux-monitor-privileged
```

Validate with `visudo -cf /etc/sudoers.d/linux-monitor`. There is no `NOPASSWD: ALL`.
The helper accepts only `apt-check`, `apt-apply`, `power-schedule`, `power-cancel`, and `docker-ps`,
and validates all arguments internally. Any sudo or helper failure is noninteractive
because the service uses `sudo -n`.

New installs and updates refresh the fixed helper. Docker monitoring requires the normal rootful Docker socket and binary. Availability is reported as `docker_status`.

## Privileged helper

Installed root-owned and mode `0755` at `/usr/local/libexec/linux-monitor-privileged`.
It runs only:

- `apt-check`: refresh package indexes and simulate an upgrade
- `apt-apply`: install available upgrades without removals
- `power-schedule <reboot|shutdown> <delay>`: create a transient systemd timer
- `power-cancel`: stop the transient power timer
- `docker-ps` lists running Docker containers (fixed `/usr/bin/docker --config /etc/docker --host unix:///var/run/docker.sock ps`)

## SQLite and retention

- Database path: `/var/lib/linux-monitor/linux-monitor.db`
- Jobs, power actions, and audit records older than 90 days are removed at store
  startup.
- Command output is capped at 1 MiB per job.
- No metric history is stored.

## Tailscale ACL example

Tags must be assigned to devices before this policy can apply. Example HuJSON ACL
allowing tagged client devices to reach tagged server devices only on TCP 8000:

```json
{
  "tagOwners": {
    "tag:linux-monitor-client": ["autogroup:admin"],
    "tag:linux-monitor-server": ["autogroup:admin"]
  },
  "acls": [
    {
      "action": "accept",
      "src": ["tag:linux-monitor-client"],
      "dst": ["tag:linux-monitor-server:8000"],
      "proto": "tcp"
    }
  ]
}
```

Assign `tag:linux-monitor-client` to client devices and `tag:linux-monitor-server` to
the server device in Tailscale; otherwise the tags are unused and no traffic is allowed.
Use the configured API port in the ACL if it differs from `8000`. The API requires
reader or admin bearer-token authentication for protected endpoints.

## Uninstall

1. Cancel any pending power action first:
   `systemctl stop linux-monitor-power-schedule.timer || true`
   `systemctl stop linux-monitor-power-schedule.service || true`
2. Stop and disable the service:
   `systemctl disable --now linux-monitor.service`
3. Remove the unit and reload systemd:
   `rm -f /etc/systemd/system/linux-monitor.service`
   `systemctl daemon-reload`
4. Remove sudoers and helper:
   `rm -f /etc/sudoers.d/linux-monitor`
   `rm -f /usr/local/libexec/linux-monitor-privileged`
5. Preserve `/var/lib/linux-monitor` (including the database) by default.
6. Optional explicit purge:
   `rm -rf /var/lib/linux-monitor /opt/linux-monitor /etc/linux-monitor`
   `userdel linux-monitor || true`
   `groupdel linux-monitor || true`

`scripts/uninstall.sh` automates the above and only purges when `PURGE=1` is set.

## Validation performed

- `visudo -cf` for sudoers syntax.
- `systemd-analyze verify` for unit syntax.
- Python syntax/compile checks where applicable.
No real privileged integration or installation was executed for this documentation.
