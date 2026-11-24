# Operations Guide

## Service management

```bash
systemctl status linux-monitor
systemctl restart linux-monitor
journalctl -u linux-monitor -f
```

The service starts automatically on boot and restarts on failure.

## Token rotation

1. Edit `/etc/linux-monitor/server.env`.
2. Set new `READER_TOKEN` and/or `ADMIN_TOKEN` values (at least 32 characters,
   distinct).
3. Run `systemctl restart linux-monitor`.
4. Distribute new tokens to clients.

There is no token management API.

## Logs

Use `journalctl -u linux-monitor`. The application returns request IDs in the
`X-Request-ID` header and error body; correlate these with logs.

## Database backup and restore

The SQLite database is `/var/lib/linux-monitor/linux-monitor.db` (WAL mode). To back up:

```bash
systemctl stop linux-monitor
cp /var/lib/linux-monitor/linux-monitor.db /backup/linux-monitor.db
# also copy -wal and -shm if present
systemctl start linux-monitor
```

Restore by stopping the service, replacing the database files, and starting again.

## Service restart behavior

- On startup, jobs left `queued` or `running` are marked `failed` with error code
  `interrupted`.
- Pending power actions whose scheduled time has passed are marked `unknown`.
- Jobs, power actions, and audit records older than 90 days are removed on startup.
- APT operations do not resume automatically.

## Recovery

### APT operation interrupted

If an update check or apply is interrupted by a restart or crash:

1. Inspect `/var/lib/dpkg` locks and APT state:
   `ls -l /var/lib/dpkg/lock* /var/lib/apt/lists/lock 2>/dev/null`
2. Check whether dpkg/apt is running:
   `ps aux | grep -E 'apt|dpkg'`
3. Review logs:
   `journalctl -u linux-monitor`, `/var/log/apt/history.log`,
   `/var/log/dpkg.log`, `/var/log/apt/term.log`
4. Do not blindly rerun the update. Determine whether dpkg is mid-configuration or a
   lock is stale before taking action.
5. If dpkg was interrupted mid-configuration, follow Debian recovery guidance
   (`dpkg --configure -a`) only after understanding the failure.

### Power action unknown state

If the service was down when a scheduled reboot/shutdown time passed:

1. The power action is marked `unknown`.
2. Check whether the system actually rebooted or shut down.
3. Inspect `systemctl list-timers linux-monitor-power-schedule.timer` and journal logs.
4. If a shutdown is still pending, cancel with the helper or stop the timer as root.
5. Reconcile client state by polling the power action endpoint.

### Helper or sudo failure

- Verify sudoers syntax: `visudo -cf /etc/sudoers.d/linux-monitor`
- Test the helper manually as the service account:
  `sudo -u linux-monitor sudo -n /usr/local/libexec/linux-monitor-privileged apt-check`
- Warning: `apt-check` performs a real privileged `apt-get update` and refreshes
  package metadata on the host. It is not a dry-run connectivity test. Do not use
  `apt-apply`, `power-schedule`, or `power-cancel` as connectivity tests.
- Any failure is safe and noninteractive; the API returns `execution_failed` or
  `helper_failed`.

### Database corruption

Restore from backup. If no backup exists, move the corrupt file aside and restart; a
new empty database will be created. Historical jobs and audit records will be lost.
