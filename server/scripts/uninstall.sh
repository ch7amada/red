#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "uninstall.sh must run as root" >&2
  exit 1
fi

# Cancel any pending power action first.
systemctl stop linux-monitor-power-schedule.timer 2>/dev/null || true
systemctl stop linux-monitor-power-schedule.service 2>/dev/null || true

systemctl disable --now linux-monitor.service 2>/dev/null || true
rm -f /etc/systemd/system/linux-monitor.service
systemctl daemon-reload

rm -f /etc/sudoers.d/linux-monitor
rm -f /usr/local/libexec/linux-monitor-privileged

# Preserve the database and configuration by default.
if [[ "${PURGE:-0}" == "1" ]]; then
  rm -rf /var/lib/linux-monitor /opt/linux-monitor /etc/linux-monitor
  if id -u linux-monitor >/dev/null 2>&1; then
    userdel linux-monitor || true
  fi
  if getent group linux-monitor >/dev/null; then
    groupdel linux-monitor || true
  fi
else
  echo "Preserved /var/lib/linux-monitor, /opt/linux-monitor, and /etc/linux-monitor."
  echo "Set PURGE=1 to remove them and the service account."
fi
