# Linux Monitor

This runbook starts the API and web dashboard on the same Ubuntu host. It assumes
the checkout is at `~/projects/red` and the host is connected to Tailscale. The API
listens on `127.0.0.1:8002` and the dashboard listens on the host's Tailscale IPv4
address on port `8082`. For direct API access from another device, see the
[Tailscale deployment guide](server/docs/deployment.md).

## 1. Install and start the API with the privileged helper

1. From the checkout, run the installer for a fresh installation or to restore a
   missing helper or sudoers rule. It installs the systemd service, the
   `linux-monitor` service account, and the root-owned helper at
   `/usr/local/libexec/linux-monitor-privileged`. The service account can call that
   helper through passwordless sudo for update and power actions.

   ```bash
   cd ~/projects/red
   sudo env SOURCE_DIR="$PWD/server" HOST=127.0.0.1 PORT=8002 bash server/scripts/install.sh
   ```

   The installer creates and prints both tokens on first install. It preserves
   an existing `/etc/linux-monitor/server.env`. If an existing install uses a
   different address or port, edit it with `sudoedit /etc/linux-monitor/server.env`
   and set `HOST=127.0.0.1` and `PORT=8002` for this setup. If you changed the file, run
   `sudo systemctl restart linux-monitor.service` to load it.

2. Start the API and enable it at boot. Confirm it is active, enabled, and healthy.

   ```bash
   sudo systemctl enable --now linux-monitor.service
   systemctl is-active linux-monitor.service
   systemctl is-enabled linux-monitor.service
   curl -fsS http://127.0.0.1:8002/health/live
   ```

   Expect `active`, `enabled`, and `{"status":"ok"}`.

3. Verify the control setup. Check sudoers and invoke the helper as the service
   account without an operation. The last command should return
   `{"error": "missing_operation"}` with exit status `2`. This proves the account
   can launch the helper without changing packages or the host's power state.

   ```bash
   sudo visudo -cf /etc/sudoers.d/linux-monitor
   systemctl show linux-monitor.service -p User -p NoNewPrivileges -p ProtectSystem
   sudo -u linux-monitor /usr/bin/sudo -n /usr/local/libexec/linux-monitor-privileged
   ```

   The installed unit runs as `User=linux-monitor` with `NoNewPrivileges=no` and
   `ProtectSystem=no`. Keep the packaged unit settings so the helper can gain the
   privileges it needs and modify system files during upgrades.

## 2. Get the reader and admin tokens

1. On the API host, read the generated tokens from the service configuration in
   a private terminal.

   ```bash
   sudo grep -E '^(READER_TOKEN|ADMIN_TOKEN)=' /etc/linux-monitor/server.env
   ```

2. Copy only the value after `=`. Use the **reader token** to view the dashboard
   and the **admin token** for updates, reboot, and shutdown. Store both as secrets.
   See the [token rotation instructions](server/docs/operations.md#token-rotation)
   if you need new values.

## 3. Start the dashboard on Tailscale and enable it at boot

1. As your regular user, install the dashboard dependencies into its virtual
   environment. Reuse the existing `.venv` if you already set it up.

   ```bash
   cd ~/projects/red/webapp
   test -x .venv/bin/python || python3 -m venv .venv
   .venv/bin/python -m pip install -r requirements.txt
   ```

2. Create the user service. `tailscale ip -4` supplies the dashboard's bind
   address. If your checkout is elsewhere, change both paths in the unit.

   ```bash
   dashboard_host=$(tailscale ip -4) &&
     test -n "$dashboard_host" &&
     mkdir -p ~/.config/systemd/user &&
     cat > ~/.config/systemd/user/linux-monitor-web.service <<EOF
   [Unit]
   Description=Linux Monitor web dashboard

   [Service]
   WorkingDirectory=%h/projects/red/webapp
   Environment=LINUX_MONITOR_API_URL=http://127.0.0.1:8002
   ExecStart=%h/projects/red/webapp/.venv/bin/python -m uvicorn app:app --host $dashboard_host --port 8082 --workers 1
   Restart=on-failure
   RestartSec=5

   [Install]
   WantedBy=default.target
   EOF
   ```

3. Enable Tailscale and lingering so the dashboard can start before you log in.
   Restart the dashboard to apply the new bind address. `restart` also starts
   the service on a fresh install.

   ```bash
   sudo systemctl enable --now tailscaled.service
   sudo loginctl enable-linger "$(id -un)"
   systemctl --user daemon-reload
   systemctl --user enable linux-monitor-web.service
   systemctl --user restart linux-monitor-web.service
   systemctl --user is-active linux-monitor-web.service
   systemctl --user is-enabled linux-monitor-web.service
   loginctl show-user "$(id -un)" -p Linger
   curl --retry 5 --retry-connrefused --retry-delay 1 -fsS -o /dev/null \
     "http://$(tailscale ip -4):8082/connect"
   ```

   Expect `active`, `enabled`, and `Linger=yes`. The health check succeeds when
   the dashboard serves the Connect page at its Tailscale address.

4. From a device on your tailnet with access to TCP port `8082`, open
   `http://<tailscale-ip>:8082/` using the address printed by `tailscale ip -4`
   on the host. Paste the admin token on **Connect**. On **Control**, choose
   **Check for updates** and wait for the job to succeed. It refreshes APT
   metadata and simulates an upgrade without installing packages. Power actions
   take effect after the selected delay.

If either service fails or a control job reports an error, check this boot's logs.

```bash
sudo journalctl -b -u linux-monitor.service -n 50 --no-pager
journalctl --user -b -u linux-monitor-web.service -n 50 --no-pager
```
