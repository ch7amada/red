import asyncio

from linux_monitor.operations.process_runner import AsyncSubprocessRunner


def test_process_runner_success():
    runner = AsyncSubprocessRunner()
    result = asyncio.get_event_loop().run_until_complete(
        runner.run(["/bin/true"], timeout=5, env={"PATH": "/bin:/usr/bin"})
    )
    assert result.returncode == 0
    assert result.timed_out is False


def test_process_runner_timeout_kills():
    runner = AsyncSubprocessRunner()
    result = asyncio.get_event_loop().run_until_complete(
        runner.run(["/bin/sleep", "10"], timeout=0.2, env={"PATH": "/bin:/usr/bin"})
    )
    assert result.timed_out is True