# Linux Monitor

This runbook starts the API and web dashboard on the same Ubuntu host. It assumes
the checkout is at `~/projects/red` and the host is connected to Tailscale. The API
listens on `127.0.0.1:8002`. The dashboard is reachable on port `8082` at both the
host's LAN IPv4 address and its Tailscale IPv4 address. For direct API access from
another device, see the
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

## 3. Start the dashboard for LAN and Tailscale access

The old service bound the dashboard to the address from `tailscale ip -4`, so
requests to the host's LAN IP could not reach it. If you already installed the
dashboard, recreate the user service in step 2 and reload and restart it in
step 3.

1. As your regular user, install the dashboard dependencies into its virtual
   environment. Reuse the existing `.venv` if you already set it up.

   ```bash
   cd ~/projects/red/webapp
   test -x .venv/bin/python || python3 -m venv .venv
   .venv/bin/python -m pip install -r requirements.txt
   ```

2. Create the user service. `--host 0.0.0.0` listens on all IPv4 interfaces,
   including LAN and Tailscale. If your checkout is elsewhere, change both paths
   in the unit.

   ```bash
   mkdir -p ~/.config/systemd/user &&
     cat > ~/.config/systemd/user/linux-monitor-web.service <<'EOF'
   [Unit]
   Description=Linux Monitor web dashboard

   [Service]
   WorkingDirectory=%h/projects/red/webapp
   Environment=LINUX_MONITOR_API_URL=http://127.0.0.1:8002
   ExecStart=%h/projects/red/webapp/.venv/bin/python -m uvicorn app:app --host 0.0.0.0 --port 8082 --workers 1
   Restart=on-failure
   RestartSec=5

   [Install]
   WantedBy=default.target
   EOF
   ```

3. Before starting the service, restrict TCP port `8082` to your trusted LAN
   and authorized Tailscale clients. For example, if UFW is active and blocks
   incoming LAN traffic, allow your LAN subnet on its interface. Replace the
   example interface and subnet with yours.

   ```bash
   sudo ufw allow in on enp3s0 from 192.168.1.0/24 to any port 8082 proto tcp
   ```

   If your tailnet uses access rules, allow the intended clients to reach TCP
   `8082` on this host. The direct LAN connection uses plain HTTP. Keep this
   port off public-facing networks and router port forwards.

   Enable Tailscale and lingering for startup at boot. Restart the dashboard to
   apply the new bind address. `restart` also starts it on a fresh install.

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
     http://127.0.0.1:8082/connect
   ```

   Expect `active`, `enabled`, and `Linger=yes`. The health check succeeds when
   the dashboard serves the Connect page locally.

4. Check both addresses from client devices.

   - **LAN** — Run `ip -4 -brief address show scope global` on the host and take
     the IPv4 address of its Ethernet or Wi-Fi interface, omitting the `/` and
     prefix length. Open `http://<lan-ip>:8082/` from a device on that LAN.
   - **Tailscale** — Run `tailscale ip -4` on the host. Open
     `http://<tailscale-ip>:8082/` from a device on your tailnet.

   To verify the dashboard can use the API, paste the admin token on **Connect**.
   On **Control**, choose **Check for updates** and wait for the job to succeed.
   It refreshes APT metadata and simulates an upgrade without installing
   packages. Power actions take effect after the selected delay.

If either service fails or a control job reports an error, check this boot's logs.

```bash
sudo journalctl -b -u linux-monitor.service -n 50 --no-pager
journalctl --user -b -u linux-monitor-web.service -n 50 --no-pager
```
