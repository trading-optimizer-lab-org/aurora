from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from infra.gtbi_v7_readiness import successor_completion as completion


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def preterminal_result() -> completion.ReconciliationResult:
    return completion.reconcile(ROOT, preterminal=True)


def test_current_successor_is_ready_for_terminal_reconciliation(
    preterminal_result: completion.ReconciliationResult,
) -> None:
    assert preterminal_result.passed is True
    assert preterminal_result.blockers == ()
    assert len(preterminal_result.completed_task_ids) == 21
    assert "PREV7-1003" not in preterminal_result.completed_task_ids


def test_security_bound_file_drift_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    real_sha256 = completion._sha256

    def drifted_sha256(path: Path) -> str:
        if path.name == "execution_policy.py":
            return "sha256:" + "0" * 64
        return real_sha256(path)

    monkeypatch.setattr(completion, "_sha256", drifted_sha256)
    monkeypatch.setattr(completion, "_evidence_digest", lambda *_: "sha256:test")
    result = completion.reconcile(ROOT, preterminal=True)
    assert result.passed is False
    assert any("security-bound file drifted" in blocker for blocker in result.blockers)


def test_consumer_remediation_chain_is_closed() -> None:
    path = ROOT / "docs/readiness/gtbi-v7-successor/output_consumer_remediation_registry.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    row = rows[0]
    claimed = row.pop("event_digest")
    assert claimed == completion._canonical_digest(row)
    assert row["open_child_count"] == 0


def test_completed_clean_contains_all_tasks_and_preserves_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    passed = completion.ReconciliationResult(
        passed=True,
        completed_task_ids=tuple(sorted(set(completion.TASK_EVIDENCE) - {"PREV7-1003"})),
        blockers=(),
        evidence_bundle_digest="sha256:test",
        evidence_files=(),
    )
    monkeypatch.setattr(completion, "reconcile", lambda *_args, **_kwargs: passed)
    receipt = completion.build_completed_clean(ROOT, reviewed_commit="a" * 40)
    assert receipt["terminal_output"] == "COMPLETED_CLEAN"
    assert receipt["completed_task_count"] == 22
    assert set(receipt["completed_task_ids"]) == set(completion.TASK_EVIDENCE)
    assert receipt["locked_authorized"] is False
    assert receipt["locked_data_accessed"] is False
    assert receipt["incremental_net_spend_usd"] == 0.0


def test_inventory_registry_has_no_unknown_decisions() -> None:
    path = ROOT / "docs/project_inventory/workflow_branch_registry.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows
    assert all(row["decision"] != "unknown" for row in rows)


def test_completion_workflow_is_github_only_and_locked_closed() -> None:
    path = ROOT / ".github/workflows/gtbi-v7-successor-close.yml"
    text = path.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    assert "runs-on: ubuntu-latest" in text
    assert "self-hosted" not in text
    assert "C:\\" not in text
    assert 'locked_start: "2021-01-01"' in text
    assert "--finalize" in text
    assert "scripts/global_technical_buy_indicator.py" not in text
    assert "run_gtbi_v7_new_reference_worker" not in text
