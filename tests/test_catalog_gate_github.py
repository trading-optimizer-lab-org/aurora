"""Exercise the actual bounded gh entrypoint; replace only subprocess transport."""

import subprocess
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_timeout_never_retries_and_write_remains_uncertain(monkeypatch, capsys, method):
    from scripts import catalog_gate_github as command

    monkeypatch.delenv("CATALOG_GATE_DEADLINE_UNIX", raising=False)
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        assert kwargs["timeout"] == 20
        raise subprocess.TimeoutExpired(args, 20)
    monkeypatch.setattr(command.subprocess, "run", run)
    result = command.main(["--method", method, "repos/trading-optimizer-lab-org/aurora/issues/280"])
    assert result == 124
    assert len(calls) == 1
    assert ("CATALOG_GATE_WRITE_UNCONFIRMED" if method == "POST" else "CATALOG_GATE_READ_TIMEOUT") in capsys.readouterr().err


def test_expired_gate_does_not_start_a_shell_write(monkeypatch):
    from scripts import catalog_gate_github as command

    monkeypatch.setenv("CATALOG_GATE_DEADLINE_UNIX", "1")
    monkeypatch.setattr(command.subprocess, "run", lambda *args, **kwargs: pytest.fail("expired write started"))
    assert command.main(["--method", "POST", "repos/trading-optimizer-lab-org/aurora/issues/280/labels"]) == 2


def test_success_preserves_arguments_and_exit_status(monkeypatch):
    from scripts import catalog_gate_github as command

    monkeypatch.delenv("CATALOG_GATE_DEADLINE_UNIX", raising=False)
    def run(args, **kwargs):
        assert args == ["gh", "api", "repos/trading-optimizer-lab-org/aurora/issues/280"]
        assert kwargs == {"timeout": 20, "check": False}
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(command.subprocess, "run", run)
    assert command.main(["repos/trading-optimizer-lab-org/aurora/issues/280"]) == 0
