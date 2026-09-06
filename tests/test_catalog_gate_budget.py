"""The actual network transport must consume the shared admission deadline."""

import pytest


def test_budget_decreases_and_never_restarts_between_calls(monkeypatch):
    from aurora.infra.sp500_megarun import catalog_gate_budget as budget

    monkeypatch.setenv("CATALOG_GATE_DEADLINE_UNIX", "105")
    monkeypatch.setattr(budget.time, "time", lambda: 100.0)
    assert budget.gate_timeout(60) == 5.0
    monkeypatch.setattr(budget.time, "time", lambda: 104.0)
    assert budget.gate_timeout(20) == 1.0
    monkeypatch.setattr(budget.time, "time", lambda: 105.0)
    with pytest.raises(ValueError, match="CATALOG_GATE_DEADLINE_EXCEEDED"):
        budget.gate_timeout(20)


@pytest.mark.parametrize("deadline", ["nan", "inf", "broken", "-1"])
def test_invalid_deadline_cannot_disable_the_budget(monkeypatch, deadline):
    from aurora.infra.sp500_megarun import catalog_gate_budget as budget

    monkeypatch.setenv("CATALOG_GATE_DEADLINE_UNIX", deadline)
    with pytest.raises(ValueError, match="CATALOG_GATE_DEADLINE_INVALID"):
        budget.gate_timeout(20)


def test_expired_budget_prevents_actual_transport_open(monkeypatch):
    from aurora.infra.sp500_megarun.catalog_github_snapshot import UrllibGitHubGetTransport

    monkeypatch.setenv("CATALOG_GATE_DEADLINE_UNIX", "1")
    transport = UrllibGitHubGetTransport()
    monkeypatch.setattr(transport._opener, "open", lambda *args, **kwargs: pytest.fail("Expired gate must not start a GET"))
    with pytest.raises(ValueError, match="CATALOG_GATE_DEADLINE_EXCEEDED"):
        transport.get("https://api.github.com/repos/o/r", {})
