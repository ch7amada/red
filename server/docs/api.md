# API Reference

Base URL: `http://<tailscale-ip>:8000`. All endpoints use direct HTTP; transport
encryption is provided by Tailscale.

## Authentication

- `GET /health/live` is public.
- All other endpoints require `Authorization: Bearer <token>`.
- Reader token: read-only access.
- Admin token: all reader capabilities plus mutation endpoints.
- Admin includes reader capability; the two tokens must be distinct and at least 32
  characters.
- Failed authentication is throttled per client address.

## Error envelope

All errors use this JSON shape:

```json
{
  "error": {
    "code": "unauthorized",
    "message": "Missing or invalid bearer token",
    "request_id": "..."
  }
}
```

Common codes: `bad_request`, `unauthorized`, `forbidden`, `not_found`,
`method_not_allowed`, `validation_error`, `too_many_requests`, `conflict`,
`invalid_input`, `execution_failed`, `timeout`, `interrupted`, `internal_error`.

Status mapping: invalid input `422`, not found `404`, conflict `409`, timeout `504`,
execution failure `503`, interrupted/internal `500`.
Responses include an `X-Request-ID` header.

## llama.cpp monitoring

The system snapshot always includes a `llama_cpp` object. The default upstream URL
is `http://127.0.0.1:8081`. Override it with `LLAMA_CPP_URL` (HTTP or HTTPS base
URL). `LLAMA_CPP_API_KEY` is an optional bearer token and is required only when
the upstream llama.cpp server is protected. The key is sent only to the
configured upstream host. Redirects and ambient proxies are not followed.

The server polls the configured instance's `/health`, `/models`, and `/props`
endpoints. Failures degrade safely and never affect other collectors. Each model
entry reports `id`, `status`, `context_tokens` (context per slot, when loaded),
`training_context_tokens` (training context), and `total_slots` (slot count). The
top-level `llama_cpp.status` is always present.

Per-model `slots` are sampled only on an explicit opt-in request
(`GET /api/v1/system?include_llama_context=true`), because calling upstream
`/slots` resets llama.cpp idle time. Each slot reports `id`, `context_tokens`,
`used_tokens`, `remaining_tokens`, and `is_processing`. `slots` is `null` when
not sampled or unavailable, and `[]` when the upstream reported no slots. The
upstream `/slots` endpoint may be unavailable when llama.cpp is started with
`--no-slots`. In that case sampling is skipped and `slots` remains `null`.

## Endpoints

### `GET /health/live`

Public minimal liveness check.

Response `200`:

```json
{"status": "ok"}
```

### `GET /api/v1/system`

Reader or admin. Returns the monitoring snapshot. Optional query parameter
`include_llama_context` (boolean, default `false`) enables one-shot llama.cpp
context slot sampling.

Response `200`: `SystemInfo` object with `schema_version`, `collected_at`, `hostname`,
`os`, `uptime_seconds`, `uptime_status`, `llama_cpp`, `cpu`, `memory`, `swap`,
`filesystems`, `network`, `gpus`, and Docker containers (`docker_containers` with `docker_status`).

### `POST /api/v1/updates/check`

Admin only. Starts an update check job. Returns `202 Accepted`.

### `POST /api/v1/updates/apply`

Admin only. Starts an update apply job. Returns `202 Accepted`.

### `GET /api/v1/jobs/{id}`

Admin only. Returns `JobResponse` with `id`, `kind`, `status`,
`created_at`, `started_at`, `finished_at`, `result`, `output`,
`output_truncated`, `error_code`, `error_message`, and `poll_url`.

Job statuses include `queued`, `running`, `succeeded`, `failed`, and `interrupted`.
Interrupted jobs are marked failed after a service restart.

### `POST /api/v1/power-actions`

Admin only. Body:

```json
{
  "action": "reboot",
  "delay_seconds": 60,
  "confirmation": "reboot"
}
```

- `action`: `reboot` or `shutdown`
- `delay_seconds`: integer from 10 to 3600 (default 60)
- `confirmation`: must exactly equal `action`

Returns `202 Accepted` with `PowerActionResponse`: `id`, `action`, `status`,
`created_at`, `scheduled_for`, and `cancellable`. Only one power action may be
pending at a time. Power actions conflict with active APT operations.

### `GET /api/v1/power-actions/{id}`

Admin only. Returns a power action, including `pending`, `cancelled`, `failed`,
`unknown`, or completed status.

### `DELETE /api/v1/power-actions/{id}`

Admin only. Cancels a pending power action. Returns `200 OK` with the updated
`PowerActionResponse`. Cancellation is only possible before `scheduled_for`; after that
the action may be reported as already executed or unknown.

## Job and power action polling

Job and power-action creation returns `202` with the created resource. Poll the
corresponding `GET` endpoint until the status is terminal. There is no streaming or
callback interface.

## APT semantics

- Update check runs `apt-get update` then a simulated `apt-get upgrade`.
- Update apply runs `apt-get upgrade` with `--with-new-pkgs`.
- No package removals, `autoremove`, `dist-upgrade`, or `full-upgrade` are performed.
- No automatic reboot occurs; `reboot_required` is reported when `/var/run/reboot-required`
  exists.
- Check timeout: 15 minutes. Apply timeout: 2 hours.
- Conflicts: another APT job active, or a pending power action.

## Power semantics

- Delay range: 10 to 3600 seconds.
- One pending power action at a time.
- Uses a transient systemd timer (`linux-monitor-power-schedule`).
- Cancellation stops the timer if still within the cancellation window.
- If the service restarts after the scheduled time, the action is marked `unknown`
  because execution cannot be confirmed.


## Docker monitoring

- `GET /api/v1/system` includes running containers only (`docker ps` semantics).
- Container rows include `id`, `name`, `image`, and `status`.
- Docker availability is reported via `docker_status` (`ok` when Docker ran, even with zero containers).
- Failures (missing binary/daemon/permission/timeout) degrade to an empty list with `status: error` and a generic error. Other collectors are unaffected.
- The privileged helper runs fixed `docker ps` semantics against `/var/run/docker.sock`.

## Output limits

Command output is capped at 1 MiB per job and may be truncated with a marker. Bearer
tokens are redacted from stored output.
