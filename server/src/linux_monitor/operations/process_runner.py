"""Injectable async subprocess runner with process-group cleanup."""

from __future__ import annotations

import asyncio
import os
import signal
from typing import Any, Optional

from .store import OUTPUT_CAP_BYTES


class ProcessResult:
    def __init__(
        self,
        returncode: int,
        stdout: str = "",
        stderr: str = "",
        timed_out: bool = False,
        stdout_truncated: bool = False,
        stderr_truncated: bool = False,
    ) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.timed_out = timed_out
        self.stdout_truncated = stdout_truncated
        self.stderr_truncated = stderr_truncated


class AsyncSubprocessRunner:
    """Default async runner. Terminates the child process group on timeout."""

    async def run(
        self,
        argv: list[str],
        *,
        timeout: float,
        env: Optional[dict[str, str]] = None,
        cwd: Optional[str] = None,
    ) -> ProcessResult:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
            start_new_session=True,
        )
        cap = OUTPUT_CAP_BYTES
        stdout_buf = bytearray()
        stderr_buf = bytearray()
        stdout_truncated = [False]
        stderr_truncated = [False]

        async def drain(stream, buf, flag):
            try:
                while True:
                    chunk = await stream.read(65536)
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

        drain_stdout = asyncio.create_task(drain(proc.stdout, stdout_buf, stdout_truncated))
        drain_stderr = asyncio.create_task(drain(proc.stderr, stderr_buf, stderr_truncated))
        timed_out = False
        try:
            await asyncio.wait_for(proc.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            timed_out = True
            await self._terminate(proc)
        try:
            await asyncio.wait_for(
                asyncio.gather(drain_stdout, drain_stderr), timeout=5
            )
        except asyncio.TimeoutError:
            drain_stdout.cancel()
            drain_stderr.cancel()
        stdout = stdout_buf.decode("utf-8", errors="replace")
        stderr = stderr_buf.decode("utf-8", errors="replace")
        if timed_out:
            return ProcessResult(
                returncode=-9,
                stdout=stdout,
                stderr=stderr if stderr else "operation timed out",
                timed_out=True,
                stdout_truncated=stdout_truncated[0],
                stderr_truncated=stderr_truncated[0],
            )
        return ProcessResult(
            returncode=proc.returncode if proc.returncode is not None else 0,
            stdout=stdout,
            stderr=stderr,
            timed_out=False,
            stdout_truncated=stdout_truncated[0],
            stderr_truncated=stderr_truncated[0],
        )

    async def _terminate(self, proc: asyncio.subprocess.Process) -> None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
            await proc.wait()


__all__ = ["AsyncSubprocessRunner", "ProcessResult"]
