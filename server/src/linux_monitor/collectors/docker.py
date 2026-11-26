"""Docker container collection."""

from __future__ import annotations

import json
from typing import Optional

from ..config import Settings
from ..privileged_helper import run_process, scrubbed_env
from ..schemas import DockerContainerInfo

DOCKER_TIMEOUT_SECONDS = 3.0


def collect_docker(settings: Settings) -> tuple[list[DockerContainerInfo], Optional[str]]:
    """Return (containers, error). Empty list with None error means Docker running with no containers."""
    argv = [settings.sudo_path, "-n", settings.privileged_helper_path, "docker-ps"]
    try:
        result = run_process(argv, timeout=DOCKER_TIMEOUT_SECONDS, env=scrubbed_env())
        if (
            getattr(result, "timed_out", False)
            or getattr(result, "returncode", 1) != 0
            or getattr(result, "stdout_truncated", False)
        ):
            return [], "collection failed"
        raw = json.loads(result.stdout)["containers"]
        if not isinstance(raw, list):
            return [], "collection failed"
        containers: list[DockerContainerInfo] = []
        for item in raw:
            containers.append(DockerContainerInfo.model_validate(item))
        return containers, None
    except (OSError, ValueError, KeyError, TypeError):
        return [], "collection failed"