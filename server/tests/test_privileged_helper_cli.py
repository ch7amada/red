import json

import pytest

from linux_monitor import privileged_helper as ph


def test_cli_rejects_unknown_operation(monkeypatch):
    monkeypatch.setattr(ph, "run_process", lambda *a, **k: None)
    code = ph.main(["frobnicate"])
    assert code == 1


def test_cli_rejects_extra_args(monkeypatch):
    monkeypatch.setattr(ph, "run_process", lambda *a, **k: None)
    assert ph.main(["apt-check", "extra"]) == 1
    assert ph.main(["power-cancel", "extra"]) == 1


def test_cli_rejects_bad_power_args(monkeypatch):
    monkeypatch.setattr(ph, "run_process", lambda *a, **k: None)
    assert ph.main(["power-schedule", "reboot"]) == 1
    assert ph.main(["power-schedule", "reboot", "abc"]) == 1
    assert ph.main(["power-schedule", "reboot", "5"]) == 1
    assert ph.main(["power-schedule", "halt", "60"]) == 1


def test_cli_success_prints_json(monkeypatch, capsys):
    calls = {"n": 0}

    def fake_run(argv, *, timeout=None, env=None, cwd=None):
        class R:
            returncode = 0
            stdout = ""
            stderr = ""
        calls["n"] += 1
        r = R()
        if calls["n"] == 2:
            r.stdout = "Inst foo [1.0] (1.1 ...)\n"
        return r
    monkeypatch.setattr(ph, "run_process", fake_run)
    code = ph.main(["apt-check"])
    assert code == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["count"] == 1


def test_cli_failure_nonzero(monkeypatch, capsys):
    def fake_run(argv, *, timeout=None, env=None, cwd=None):
        class R:
            returncode = 1
            stdout = ""
            stderr = "nope"
        return R()
    monkeypatch.setattr(ph, "run_process", fake_run)
    code = ph.main(["apt-check"])
    assert code == 1
    err = capsys.readouterr().err
    assert "error" in err