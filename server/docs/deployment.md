# Deployment Guide

Target: Ubuntu 22.04 or 24.04, Python 3.10+, systemd, direct HTTP over Tailscale.

## Architecture

- Uvicorn binds to the configured Tailscale IPv4 address only, never `0.0.0.0`.
- Default port is `8000`; change `PORT` in the environment file.
- Tailscale WireGuard supplies transport encryption. There is no HTTPS, Caddy,
  `tailscale serve`, or Tailscale SSH in this design.
- Tailscale ACLs must restrict clients to the server on port 8000.
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
The helper accepts only `apt-check`, `apt-apply`, `power-schedule`, and `power-cancel`,
and validates all arguments internally. Any sudo or helper failure is noninteractive
because the service uses `sudo -n`.

## Privileged helper

Installed root-owned and mode `0755` at `/usr/local/libexec/linux-monitor-privileged`.
It runs only:

- `apt-check`: refresh package indexes and simulate an upgrade
- `apt-apply`: install available upgrades without removals
- `power-schedule <reboot|shutdown> <delay>`: create a transient systemd timer
- `power-cancel`: stop the transient power timer

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
Deny all other ingress to the host. Do not publish port 8000 through a router or
firewall. These ACLs are a network-layer restriction only; they do not replace the
API's reader and admin bearer-token authentication.

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
