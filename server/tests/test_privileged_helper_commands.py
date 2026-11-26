import json
import subprocess

import pytest

from linux_monitor import privileged_helper as ph


class FakeResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class FakeRunner:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def __call__(self, argv, *, timeout=None, env=None, cwd=None):
        self.calls.append((list(argv), timeout, env))
        if self.results:
            return self.results.pop(0)
        return FakeResult(0, "", "")


def test_apt_check_refreshes_and_parses():
    runner = FakeRunner([
        FakeResult(0, "", ""),  # apt-get update
        FakeResult(0, "Inst foo [1.0] (1.1 Ubuntu:...)\nInst bar [2.0] (2.1 ...)\n", ""),
    ])
    result = ph.apt_check(runner)
    assert result["count"] == 2
    assert result["packages"][0]["name"] == "foo"
    assert result["packages"][0]["current"] == "1.0"
    assert result["packages"][0]["candidate"] == "1.1"
    # ensure update called first
    assert runner.calls[0][0] == [ph.APT_GET, "update"]
    assert runner.calls[1][0] == [ph.APT_GET, "upgrade", "-s", "-y", "--with-new-pkgs"]


def test_apt_check_update_failure():
    runner = FakeRunner([FakeResult(1, "", "update failed")])
    with pytest.raises(ph.HelperError) as exc:
        ph.apt_check(runner)
    assert exc.value.code == "apt_update_failed"


def test_apt_check_sim_failure():
    runner = FakeRunner([FakeResult(0, "", ""), FakeResult(2, "", "sim failed")])
    with pytest.raises(ph.HelperError) as exc:
        ph.apt_check(runner)
    assert exc.value.code == "apt_check_failed"


def test_apt_apply_command_shape():
    runner = FakeRunner([FakeResult(0, "done", "")])
    # fake reboot-required existence by monkeypatch
    orig_exists = __import__("os").path.exists
    __import__("os").path.exists = lambda p: p == "/var/run/reboot-required"
    try:
        result = ph.apt_apply(runner)
    finally:
        __import__("os").path.exists = orig_exists
    assert result["reboot_required"] is True
    argv = runner.calls[0][0]
    assert argv[0] == ph.APT_GET
    assert "--with-new-pkgs" in argv
    assert "upgrade" in argv
    assert "--force-confold" not in argv  # option value form
    assert any("force-confold" in a for a in argv)
    assert "autoremove" not in argv
    assert "dist-upgrade" not in argv
    assert "full-upgrade" not in argv


def test_apt_apply_failure():
    runner = FakeRunner([FakeResult(1, "", "apply failed")])
    with pytest.raises(ph.HelperError) as exc:
        ph.apt_apply(runner)
    assert exc.value.code == "apt_apply_failed"


def test_power_schedule_command_shape():
    runner = FakeRunner([FakeResult(0, "", "")])
    result = ph.power_schedule(runner, "reboot", 60)
    assert result["scheduled"] is True
    assert runner.calls[0][0] == [ph.SYSTEMD_RUN, "--unit=linux-monitor-power-schedule", "--on-active=60s", ph.SHUTDOWN, "-r", "now"]


def test_power_schedule_shutdown():
    runner = FakeRunner([FakeResult(0, "", "")])
    ph.power_schedule(runner, "shutdown", 120)
    assert runner.calls[0][0] == [ph.SYSTEMD_RUN, "--unit=linux-monitor-power-schedule", "--on-active=120s", ph.SHUTDOWN, "-h", "now"]


def test_power_schedule_validation():
    runner = FakeRunner([FakeResult(0, "", "")])
    with pytest.raises(ph.HelperError):
        ph.power_schedule(runner, "reboot", 5)
    with pytest.raises(ph.HelperError):
        ph.power_schedule(runner, "foo", 60)
    assert runner.calls == []  # validation before run


def test_power_cancel_command_shape():
    runner = FakeRunner([FakeResult(0, "", "")])
    result = ph.power_cancel(runner)
    assert result["cancelled"] is True
    assert runner.calls[0][0] == [ph.SYSTEMCTL, "stop", "linux-monitor-power-schedule.timer"]


def test_power_cancel_failure():
    runner = FakeRunner([FakeResult(1, "", "no shutdown")])
    with pytest.raises(ph.HelperError) as exc:
        ph.power_cancel(runner)
    assert exc.value.code == "power_cancel_failed"


def test_scrubbed_env_no_token():
    env = ph.scrubbed_env()
    assert "DEBIAN_FRONTEND" in env
    # no bearer/token
    for k, v in env.items():
        assert "token" not in k.lower()
        assert "bearer" not in str(v).lower()


def test_parse_malformed_inst_line():
    # malformed output should not crash
    runner = FakeRunner([
        FakeResult(0, "", ""),
        FakeResult(0, "garbage line\nInst onlyname\n", ""),
    ])
    result = ph.apt_check(runner)
    assert result["count"] >= 0


def test_truncate_output_helper():
    text = "a" * (ph.OUTPUT_CAP_BYTES + 5)
    out, trunc = ph.truncate_output(text)
    assert trunc is True
    assert len(out) <= ph.OUTPUT_CAP_BYTES


def test_docker_ps_fixed_argv_env_and_cwd():
    class R:
        returncode = 0
        stdout = ""
        stderr = ""
        timed_out = False
        stdout_truncated = False

    calls = []

    def runner(argv, *, timeout=None, env=None, cwd=None):
        calls.append((list(argv), timeout, env, cwd))
        return R()

    result = ph.docker_ps(runner)
    assert result == {"containers": []}
    argv, timeout, env, cwd = calls[0]
    assert argv == [
        "/usr/bin/docker",
        "--config",
        "/etc/docker",
        "--host",
        "unix:///var/run/docker.sock",
        "ps",
        "--format",
        '{"id":{{json .ID}},"name":{{json .Names}},"image":{{json .Image}},"status":{{json .Status}}}',
    ]
    assert timeout == 2.0
    assert env == ph.scrubbed_env()
    assert cwd == "/"