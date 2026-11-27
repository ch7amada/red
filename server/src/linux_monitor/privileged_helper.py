"""Privileged helper CLI with a narrow, fixed operation set."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
from typing import Any, Callable, Optional

APT_GET = "/usr/bin/apt-get"
SYSTEMD_RUN = "/usr/bin/systemd-run"
SYSTEMCTL = "/usr/bin/systemctl"
DOCKER = "/usr/bin/docker"
DOCKER_CONFIG = "/etc/docker"
DOCKER_HOST = "unix:///var/run/docker.sock"
DOCKER_PS_FORMAT = '{"id":{{json .ID}},"name":{{json .Names}},"image":{{json .Image}},"status":{{json .Status}}}'
POWER_UNIT = "linux-monitor-power-schedule"

OUTPUT_CAP_BYTES = 1 * 1024 * 1024
HELPER_OUTPUT_CAP_BYTES = 256 * 1024
TRUNCATION_MARKER = "\n...[truncated]"


def truncate_output(text: Optional[str], cap: int = OUTPUT_CAP_BYTES, truncated: bool = False) -> tuple[Optional[str], bool]:
    if text is None:
        return None, False
    if not truncated and len(text) <= cap:
        return text, False
    marker = TRUNCATION_MARKER
    if cap <= len(marker):
        return text[:cap], True
    return text[: cap - len(marker)] + marker, True


class HelperError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def scrubbed_env() -> dict[str, str]:
    return {
        "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
        "DEBIAN_FRONTEND": "noninteractive",
        "LC_ALL": "C",
        "LANG": "C",
    }


import threading


def run_process(
    argv: list[str],
    *,
    timeout: Optional[float] = None,
    env: Optional[dict[str, str]] = None,
    cwd: Optional[str] = None,
) -> subprocess.CompletedProcess:
    """Bounded synchronous process runner (shell=False)."""
    proc = subprocess.Popen(
        list(argv),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=cwd,
        shell=False,
        start_new_session=True,
    )
    cap = OUTPUT_CAP_BYTES
    stdout_buf = bytearray()
    stderr_buf = bytearray()
    stdout_truncated = [False]
    stderr_truncated = [False]

    def drain(pipe, buf, flag):
        try:
            while True:
                chunk = pipe.read(65536)
                if not chunk:
                    break
                if len(buf) < cap:
                    space = cap - len(buf)
                    if space:
                        buf.extend(chunk[:space])
                    if len(chunk) > space:
                        flag[0] = True
                else:
                    flag[0] = True
        except (OSError, ValueError):
            pass
        finally:
            try:
                pipe.close()
            except (OSError, ValueError):
                pass

    t_out = threading.Thread(
        target=drain, args=(proc.stdout, stdout_buf, stdout_truncated), daemon=True
    )
    t_err = threading.Thread(
        target=drain, args=(proc.stderr, stderr_buf, stderr_truncated), daemon=True
    )
    t_out.start()
    t_err.start()

    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
            proc.wait()

    t_out.join(timeout=5)
    t_err.join(timeout=5)

    returncode = -9 if timed_out else (proc.returncode if proc.returncode is not None else 0)
    result = subprocess.CompletedProcess(
        list(argv),
        returncode,
        stdout_buf.decode("utf-8", errors="replace"),
        stderr_buf.decode("utf-8", errors="replace"),
    )
    result.stdout_truncated = stdout_truncated[0]
    result.stderr_truncated = stderr_truncated[0]
    result.timed_out = timed_out
    return result


def _bounded_message(proc: subprocess.CompletedProcess) -> str:
    text = (proc.stderr or "").strip() or (proc.stdout or "").strip()
    truncated = bool(getattr(proc, "stderr_truncated", False) or getattr(proc, "stdout_truncated", False))
    text, _ = truncate_output(text, truncated=truncated)
    return text or "command failed"


def _parse_check_output(stdout: str) -> list[dict[str, Any]]:
    packages: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("Inst "):
            continue
        # Inst <name> [<current>] (<candidate> ...)
        rest = line[len("Inst ") :].strip()
        name = rest.split()[0] if rest.split() else ""
        if not name:
            continue
        current = None
        candidate = None
        if "[" in rest and "]" in rest:
            start = rest.index("[")
            end = rest.index("]", start)
            current = rest[start + 1 : end].strip() or None
        if "(" in rest and ")" in rest:
            start = rest.index("(")
            end = rest.index(")", start)
            inner = rest[start + 1 : end].strip()
            candidate = inner.split()[0] if inner.split() else None
        packages.append({"name": name, "current": current, "candidate": candidate})
    return packages


def apt_check(
    runner: Callable[..., subprocess.CompletedProcess] = run_process,
    *,
    apt_get: str = APT_GET,
) -> dict[str, Any]:
    env = scrubbed_env()
    update = runner([apt_get, "update"], timeout=300, env=env)
    if update.returncode != 0:
        raise HelperError("apt_update_failed", _bounded_message(update))
    sim = runner([apt_get, "upgrade", "-s", "-y", "--with-new-pkgs"], timeout=600, env=env)
    if sim.returncode != 0:
        raise HelperError("apt_check_failed", _bounded_message(sim))
    packages = _parse_check_output(sim.stdout or "")
    return {"packages": packages, "count": len(packages)}


def apt_apply(
    runner: Callable[..., subprocess.CompletedProcess] = run_process,
    *,
    apt_get: str = APT_GET,
) -> dict[str, Any]:
    env = scrubbed_env()
    argv = [
        apt_get,
        "-y",
        "--with-new-pkgs",
        "-o",
        "Dpkg::Options::=--force-confdef",
        "-o",
        "Dpkg::Options::=--force-confold",
        "upgrade",
    ]
    result = runner(argv, timeout=7000, env=env)
    if result.returncode != 0:
        raise HelperError("apt_apply_failed", _bounded_message(result))
    reboot_required = os.path.exists("/var/run/reboot-required")
    output, truncated = truncate_output(result.stdout or "", cap=HELPER_OUTPUT_CAP_BYTES)
    return {
        "reboot_required": reboot_required,
        "output": output,
        "output_truncated": truncated,
        "returncode": result.returncode,
    }


def power_schedule(
    runner: Callable[..., subprocess.CompletedProcess] = run_process,
    action_type: str = "reboot",
    delay_seconds: int = 60,
    *,
    systemd_run: str = SYSTEMD_RUN,
    systemctl: str = SYSTEMCTL,
) -> dict[str, Any]:
    if action_type not in {"reboot", "shutdown"}:
        raise HelperError("invalid_power_action", "unsupported power action")
    if not isinstance(delay_seconds, int) or isinstance(delay_seconds, bool):
        raise HelperError("invalid_delay", "delay must be an integer")
    if delay_seconds < 10 or delay_seconds > 3600:
        raise HelperError("invalid_delay", "delay must be between 10 and 3600 seconds")
    verb = "reboot" if action_type == "reboot" else "poweroff"
    argv = [
        systemd_run,
        f"--unit={POWER_UNIT}",
        f"--on-active={delay_seconds}s",
        systemctl,
        verb,
    ]
    result = runner(argv, timeout=60, env=scrubbed_env())
    if result.returncode != 0:
        raise HelperError("power_schedule_failed", _bounded_message(result))
    return {
        "action_type": action_type,
        "delay_seconds": delay_seconds,
        "scheduled": True,
    }


def power_cancel(
    runner: Callable[..., subprocess.CompletedProcess] = run_process,
    *,
    systemctl: str = SYSTEMCTL,
) -> dict[str, Any]:
    result = runner([systemctl, "stop", f"{POWER_UNIT}.timer"], timeout=60, env=scrubbed_env())
    if result.returncode != 0:
        raise HelperError("power_cancel_failed", _bounded_message(result))
    return {"cancelled": True}


def docker_ps(
    runner: Optional[Callable[..., subprocess.CompletedProcess]] = None,
    *,
    docker: str = DOCKER,
) -> dict[str, Any]:
    """Fixed read-only Docker container listing (running containers only)."""
    if runner is None:
        runner = run_process
    argv = [
        docker,
        "--config",
        DOCKER_CONFIG,
        "--host",
        DOCKER_HOST,
        "ps",
        "--format",
        DOCKER_PS_FORMAT,
    ]
    result = runner(argv, timeout=2.0, env=scrubbed_env(), cwd="/")
    if (
        getattr(result, "timed_out", False)
        or getattr(result, "returncode", 1) != 0
        or getattr(result, "stdout_truncated", False)
    ):
        raise HelperError("docker_ps_failed", "docker ps failed")
    stdout = getattr(result, "stdout", "") or ""
    containers = [json.loads(line) for line in stdout.splitlines()]
    return {"containers": containers}


def _validate_power_args(args: list[str]) -> tuple[str, str, int]:
    if len(args) != 2:
        raise HelperError("invalid_arguments", "power-schedule requires <reboot|shutdown> <delay>")
    action_type = args[0]
    delay_str = args[1]
    if action_type not in {"reboot", "shutdown"}:
        raise HelperError("invalid_power_action", "unsupported power action")
    if not delay_str.isdigit():
        raise HelperError("invalid_delay", "delay must be a positive integer")
    delay = int(delay_str)
    if delay < 10 or delay > 3600:
        raise HelperError("invalid_delay", "delay must be between 10 and 3600 seconds")
    return action_type, delay_str, delay


def main(argv: Optional[list[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(json.dumps({"error": "missing_operation"}), file=sys.stderr)
        return 2
    operation = args[0].replace("_", "-")
    rest = args[1:]
    runner = run_process
    try:
        if operation == "apt-check":
            if rest:
                raise HelperError("invalid_arguments", "apt-check takes no arguments")
            result = apt_check(runner)
        elif operation == "apt-apply":
            if rest:
                raise HelperError("invalid_arguments", "apt-apply takes no arguments")
            result = apt_apply(runner)
        elif operation == "power-schedule":
            action_type, _delay_str, delay = _validate_power_args(rest)
            result = power_schedule(runner, action_type, delay)
        elif operation == "power-cancel":
            if rest:
                raise HelperError("invalid_arguments", "power-cancel takes no arguments")
            result = power_cancel(runner)
        elif operation == "docker-ps":
            if rest:
                raise HelperError("invalid_arguments", "docker-ps takes no arguments")
            result = docker_ps(runner)
        else:
            raise HelperError("invalid_operation", f"unknown operation: {operation}")
    except HelperError as exc:
        print(json.dumps({"error": exc.code, "message": exc.message}), file=sys.stderr)
        return 1
    except Exception:  # pragma: no cover - defensive
        print(json.dumps({"error": "unexpected_error", "message": "internal error"}), file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
