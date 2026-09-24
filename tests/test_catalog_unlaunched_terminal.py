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


@pytest.mark.parametrize("fault", (None, "digest", "source", "third", "foreign_issue"))
@pytest.mark.parametrize("orphan_number", (370, 375))
def test_exact_orphaned_atlas_receipt_can_be_superseded_without_deleting_it(monkeypatch, fault, orphan_number):
    from scripts import publish_catalog_fast_authority as command

    orphan = {
        370: ("50c97b410f5bd9659e90c3c16c20b6717c70afc919d2a5f057159f406d5c6bb1",
              10808827739, "sha256:2eecc3be434d4d3b0e11d601cf70724f2b822899108ddaa58ee9f37cf10eb938",
              36003599751, "64b31d9867a3140ebc1835e8bca40cd58f89e557"),
        375: ("fac5dcb9359ebeded5b8d2fd06af4f8c332d4aace282dc6667fd446e80ae10d2",
              10817955043, "sha256:8cad1b8c79fef1827c7b506ae772d6a4a493a54c301ea0e3cac0d8dc2c733a3b",
              36022682478, "c3eb87071ca1b944599c9f7636f18046b2f325a5"),
    }[orphan_number]
    request = SimpleNamespace(request_sha256=orphan[0])
    created = NOW - timedelta(minutes=31)
    decision = SimpleNamespace(state="BLOCKED", reason_code="CATALOG_REQUEST_EXPIRED",
        launch_required=False, existing_run_id=None, selected_workers=0,
        decided_at=NOW, expires_at=created + timedelta(minutes=30))
    receipt = SimpleNamespace(state="BLOCKED", reason_code=decision.reason_code,
        engine_run_id=None, run_url=None, observed_recipe_count=0,
        result_science_sha256=None, created_at=NOW)
    issue = {"created_at": created.isoformat(), "state": "open", "labels": []}
    old = {"id": orphan[1], "expired": False, "digest": orphan[2],
        "workflow_run": {"id": orphan[3], "head_sha": orphan[4]}}
    if fault == "digest":
        old["digest"] = "sha256:" + "f" * 64
    elif fault == "source":
        old["workflow_run"]["id"] += 1
    rows = [old, {"id": 88, "expired": False,
                  "workflow_run": {"id": 123, "head_sha": "a" * 40}}]
    if fault == "third":
        rows.append({"id": 89, "expired": False, "workflow_run": {"id": 124}})

    class Client:
        repository = "trading-optimizer-lab-org/aurora"
        def stable_paginated(self, path, *, root):
            assert root == "artifacts"
            return SimpleNamespace(stable=True,
                collection=SimpleNamespace(complete=True, rows=tuple(rows)))

    monkeypatch.setattr(command, "load_fast_gate_owner", lambda **kwargs: None)
    arguments = dict(client=Client(), repository=Client.repository, token="fixture-only",
        commit="a" * 40, number=371 if fault == "foreign_issue" else orphan_number,
        request=request, issue=issue, context={"issue_created_at": issue["created_at"]},
        decision=decision, receipt=receipt, run_id=123, receipt_artifact_id=88)
    if fault is None:
        command._require_unlaunched_terminal(**arguments)
    else:
        with pytest.raises(ValueError, match="CATALOG_FAST_AUTHORITY_UNLAUNCHED_TERMINAL_CONFLICT"):
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
    recovered = next(step for step in workflow["jobs"]["gate"]["steps"]
        if step.get("name") == "Recover the original unlaunched terminal issue")
    assert "recover_unlaunched_terminal == 'true'" in recovered["if"]
    assert "terminal_receipt_sha256 != ''" in recovered["if"]
    assert "publish_catalog_fast_authority" not in recovered["run"]


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


@pytest.mark.parametrize("fault", (None, "actor_changed", "request_changed", "close_unconfirmed"))
def test_recovery_step_revalidates_live_issue_and_confirms_close(tmp_path, monkeypatch, fault):
    import json
    from pathlib import Path
    import subprocess
    from aurora.infra.github_performance.preflight import load_github_yaml
    from tests.test_catalog_cloud_authority import emission
    from tests.test_catalog_run_request import REQUESTER_TEST_PUBLIC_KEY

    workflow = load_github_yaml(Path(__file__).resolve().parents[1] / ".github/workflows/catalog-fast-controller.yml")
    step = next(row for row in workflow["jobs"]["gate"]["steps"]
        if row.get("name") == "Recover the original unlaunched terminal issue")
    code = step["run"].split("python - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    item = emission()
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "requester.pem").write_bytes(REQUESTER_TEST_PUBLIC_KEY)
    (tmp_path / "config/catalog_controller_actors_v1.json").write_text(json.dumps({"requester_public_key_path": "requester.pem"}))
    (tmp_path / "catalog-fast-request-context.json").write_text(json.dumps({
        "request": item.request.model_dump(mode="json"), "issue_number": 401, "actor": "requester",
    }))
    for name, value in {"RUNNER_TEMP": str(tmp_path), "ISSUE_NUMBER": "401",
                        "GITHUB_REPOSITORY": "trading-optimizer-lab-org/aurora"}.items():
        monkeypatch.setenv(name, value)
    issue = {"number": 401, "user": {"login": "other" if fault == "actor_changed" else "requester"},
             "title": item.title, "body": "changed" if fault == "request_changed" else item.body,
             "state": "open", "labels": [{"name": "catalog-run-active-v1"}]}
    calls = []
    monkeypatch.setattr(subprocess, "check_output", lambda *args, **kwargs: json.dumps(issue))
    def mutate(args, **kwargs):
        calls.append(args)
        method = args[3]
        if method == "POST":
            issue["labels"].append({"name": "catalog-run-terminal-v1"})
        elif method == "DELETE":
            issue["labels"] = [row for row in issue["labels"] if row["name"] != "catalog-run-active-v1"]
        elif method == "PATCH" and fault != "close_unconfirmed":
            issue.update(state="closed", state_reason="completed")
    monkeypatch.setattr(subprocess, "run", mutate)
    if fault is None:
        exec(compile(code, "protected-recovery-step", "exec"), {})
        assert len(calls) == 3
        assert issue["state"] == "closed"
    else:
        with pytest.raises(ValueError):
            exec(compile(code, "protected-recovery-step", "exec"), {})
        assert len(calls) == (3 if fault == "close_unconfirmed" else 0)
