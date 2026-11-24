#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="${SOURCE_DIR:-$(pwd)}"
INSTALL_ROOT=/opt/linux-monitor
VENV="$INSTALL_ROOT/.venv"
SERVICE_USER=linux-monitor
HELPER=/usr/local/libexec/linux-monitor-privileged
ENV_DIR=/etc/linux-monitor
ENV_FILE="$ENV_DIR/server.env"
UNIT=/etc/systemd/system/linux-monitor.service
SUDOERS=/etc/sudoers.d/linux-monitor

if [[ "${EUID}" -ne 0 ]]; then
  echo "install.sh must run as root" >&2
  exit 1
fi

if [[ ! -f "$SOURCE_DIR/pyproject.toml" ]]; then
  echo "SOURCE_DIR must point to the red/server checkout" >&2
  exit 1
fi

apt-get update
apt-get install -y --no-install-recommends python3 python3-venv python3-pip sudo

if ! getent group "$SERVICE_USER" >/dev/null; then
  groupadd --system "$SERVICE_USER"
fi
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --gid "$SERVICE_USER" \
    --home-dir /var/lib/linux-monitor --create-home \
    --shell /usr/sbin/nologin "$SERVICE_USER"
fi

install -d -o root -g root -m 0755 "$INSTALL_ROOT"
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0750 /var/lib/linux-monitor
install -d -o root -g "$SERVICE_USER" -m 0750 "$ENV_DIR"

if [[ ! -x "$VENV/bin/python" ]]; then
  python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install --upgrade pip
"$VENV/bin/pip" install --no-cache-dir "$SOURCE_DIR"

install -d -o root -g root -m 0755 /usr/local/libexec
{
  printf '#!%s\n' "$VENV/bin/python"
  cat "$SOURCE_DIR/src/linux_monitor/privileged_helper.py"
} > "$HELPER"
chown root:root "$HELPER"
chmod 0755 "$HELPER"

if [[ ! -f "$ENV_FILE" ]]; then
  HOST_VALUE="${HOST:-}"
  if [[ -z "$HOST_VALUE" ]]; then
    if command -v tailscale >/dev/null 2>&1; then
      HOST_VALUE="$(tailscale ip -4 2>/dev/null | head -n 1 || true)"
    fi
  fi
  if [[ -z "$HOST_VALUE" ]]; then
    HOST_VALUE="127.0.0.1"
    echo "WARNING: could not detect Tailscale IPv4; set HOST in $ENV_FILE" >&2
  fi
  PORT_VALUE="${PORT:-8000}"
  READER_TOKEN_VALUE="$(openssl rand -hex 32)"
  ADMIN_TOKEN_VALUE="$(openssl rand -hex 32)"
  cat > "$ENV_FILE" <<EOF
HOST=$HOST_VALUE
PORT=$PORT_VALUE
DATABASE_PATH=/var/lib/linux-monitor/linux-monitor.db
READER_TOKEN=$READER_TOKEN_VALUE
ADMIN_TOKEN=$ADMIN_TOKEN_VALUE
ENVIRONMENT=production
DOCS_ENABLED=false
EOF
  echo "Generated $ENV_FILE. Save these tokens securely:"
  echo "READER_TOKEN=$READER_TOKEN_VALUE"
  echo "ADMIN_TOKEN=$ADMIN_TOKEN_VALUE"
fi
chown root:"$SERVICE_USER" "$ENV_FILE"
chmod 0640 "$ENV_FILE"

cat > "$SUDOERS" <<'EOF'
linux-monitor ALL=(root) NOPASSWD: /usr/local/libexec/linux-monitor-privileged
EOF
chown root:root "$SUDOERS"
chmod 0440 "$SUDOERS"
visudo -cf "$SUDOERS"

cat > "$UNIT" <<'EOF'
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
EOF

systemctl daemon-reload
systemctl enable linux-monitor.service
systemctl restart linux-monitor.service || systemctl start linux-monitor.service
