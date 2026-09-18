from datetime import timedelta
from types import SimpleNamespace

import pytest

from tests.test_catalog_fast_path import NOW, _request


@pytest.mark.parametrize("fault", (None, "young", "owner", "alias", "receipt", "science", "foreign_issue", "incomplete"))
def test_unlaunched_terminal_requires_expiry_and_no_original_owner(monkeypatch, fault):
    from scripts import publish_catalog_fast_authority as command

    request = _request()
    created = NOW - timedelta(minutes=31)
    decision = SimpleNamespace(state="BLOCKED", reason_code="CATALOG_REQUEST_EXPIRED",
        launch_required=False, existing_run_id=None, selected_workers=0,
        decided_at=NOW, expires_at=created + timedelta(minutes=30))
    receipt = SimpleNamespace(state="BLOCKED", reason_code=decision.reason_code,
        engine_run_id=None, run_url=None, observed_recipe_count=0,
        result_science_sha256=None, created_at=NOW)
    issue = {"created_at": created.isoformat(), "state": "open", "labels": []}
    context = {"issue_created_at": issue["created_at"]}
    if fault == "young":
        issue["created_at"] = NOW.isoformat()
        context["issue_created_at"] = issue["created_at"]
    elif fault == "science":
        receipt.observed_recipe_count = 1
    elif fault == "foreign_issue":
        context["issue_created_at"] = NOW.isoformat()

    class Client:
        repository = "trading-optimizer-lab-org/aurora"
        def stable_paginated(self, path, *, root):
            rows = ({"id": 88, "expired": False,
                     "workflow_run": {"id": 999 if fault == "receipt" else 123, "head_sha": "a" * 40}},)
            return SimpleNamespace(stable=True,
                collection=SimpleNamespace(complete=fault != "incomplete", rows=rows))

    monkeypatch.setattr(command, "load_fast_gate_owner", lambda **kwargs:
        object() if fault in {"owner", "alias"} else None)
    arguments = dict(client=Client(), repository=Client.repository, token="fixture-only",
        commit="a" * 40, number=280, request=request, issue=issue, context=context,
        decision=decision, receipt=receipt, run_id=123, receipt_artifact_id=88)
    if fault is None:
        command._require_unlaunched_terminal(**arguments)
    else:
        with pytest.raises(ValueError, match="CATALOG_FAST_AUTHORITY_UNLAUNCHED"):
            command._require_unlaunched_terminal(**arguments)


def test_unlaunched_terminal_workflow_requires_authority_before_closing():
    from pathlib import Path
    from aurora.infra.github_performance.preflight import load_github_yaml
    workflow = load_github_yaml(Path(__file__).resolve().parents[1] / ".github/workflows/catalog-fast-controller.yml")
    steps = workflow["jobs"]["finalize"]["steps"]
    named = {step.get("id"): step for step in steps if step.get("id")}
    for name in ("write_authority", "publish_authority", "inspect_publication", "verify_authority"):
        assert "needs.gate.outputs.launch_required == 'true'" not in named[name]["if"]
    assert "steps.verify_authority.outcome == 'success'" in named["publish_terminal"]["if"]
    fallback = steps[-1]
    assert "steps.verify_authority.outcome == 'success'" in fallback["if"]


def test_expired_closure_unlocks_only_the_exact_successor():
    from tests.test_catalog_fast_authority import _published_unlaunched_request_state
    from tests.test_catalog_cloud_ticket import select
    state, request = _published_unlaunched_request_state()
    with pytest.raises(ValueError, match="CATALOG_CAMPAIGN_BUSY"):
        select(state)
    terminal = state.close_unlaunched(request=request, issue_number=401,
        run_id=901, terminal_receipt_sha256="d" * 64)
    ticket = select(terminal)
    assert ticket.launch_generation == request.launch_generation + 1
    assert ticket.previous_terminal_request_sha256 == request.request_sha256
    assert terminal.emissions == state.emissions
