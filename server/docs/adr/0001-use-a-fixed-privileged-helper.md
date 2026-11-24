# ADR 0001: Use a Fixed Privileged Helper

## Status

Accepted

## Context

The API service runs as an unprivileged user but must perform package updates and
schedule power actions. These operations require root privileges. The service is
reachable over the network through Tailscale and authenticates clients with bearer
tokens. We need a privilege boundary that does not expose arbitrary root execution.

## Decision

Run the API as the unprivileged `linux-monitor` account. Grant it passwordless sudo
only for the exact path `/usr/local/libexec/linux-monitor-privileged`. The helper is
root-owned, mode `0755`, and accepts only fixed operations: `apt-check`,
`apt-apply`, `power-schedule`, and `power-cancel`. It validates all arguments and runs
commands with a scrubbed environment and bounded output.

## Alternatives considered

- Root API process: rejected because any application vulnerability would grant full
  root access to a network-facing service.
- Interactive sudo: rejected because the service must be noninteractive and must not
  prompt for passwords or store root credentials.
- Privileged daemon: rejected because it adds another long-running root component and
  a private IPC protocol, increasing attack surface and operational complexity.

## Consequences

Positive:

- The API process has no root privileges and cannot perform arbitrary commands.
- Sudoers grants the minimum necessary capability: one fixed helper path.
- The helper's narrow operation set limits what a compromised service token can do.
- Tailscale ACLs and bearer-token authentication remain the primary network controls.

Negative:

- The helper is a privileged binary that must be installed and updated carefully.
- Sudoers configuration is a security-critical file requiring validation.
- Future privileged features require helper changes and sudoers review.
- Output and execution limits in the helper constrain flexibility.

## Controls

- No `NOPASSWD: ALL`; only the exact helper path.
- Helper validates operation names and arguments; no arbitrary shell or paths.
- Tokens and secrets are scrubbed from process environments and stored output.
- Tailscale restricts which clients can reach port 8000.
- Service sandbox settings that would break helper execution are intentionally not
  used.
