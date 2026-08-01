from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import pytest

from infra.gtbi_v7_readiness.canonical import canonical_bytes, domain_digest
from infra.readiness_state_controller.no_go import (
    NoGoClosureError,
    build_no_go_receipt,
    validate_no_go_prerequisites,
)

ROOT = Path(__file__).resolve().parents[1]
READINESS = Path("docs/readiness/gtbi-v7")
BASE_SHA = "a" * 40
RUN_ID = 123456789
RUN_URL = (
    "https://github.com/trading-optimizer-lab-org/aurora/actions/runs/123456789"
)


def _repository_fixture(tmp_path: Path) -> Path:
    destination = tmp_path / "repository"
    shutil.copytree(ROOT / "docs/readiness/gtbi-v7", destination / READINESS)
    trigger = destination / READINESS / "g2_v6_input_identity_decision_receipt.json"
    if not trigger.exists():
        payload = {
            "decision": "no_authenticated_v6_input_identity",
            "no_go_close_required": True,
            "current_v7_baseline_authorized": False,
            "receipt_digest": "sha256:" + ("1" * 64),
            "scientific_boundaries": {
                "locked_start": "2021-01-01",
                "locked_data_accessed": False,
                "provider_download_performed": False,
                "scientific_processing_performed": False,
                "strategy_evaluation_performed": False,
            },
        }
        trigger.write_bytes(canonical_bytes(payload) + b"\n")
    return destination


def _rewrite_csv(path: Path, field: str, identity: str, value: str) -> None:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fields = list(rows[0])
    identity_field = "id" if "id" in rows[0] else "gate_id"
    for row in rows:
        if row[identity_field] == identity:
            row[field] = value
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def test_current_repository_satisfies_terminal_no_go_prerequisites() -> None:
    validation = validate_no_go_prerequisites(ROOT, BASE_SHA)
    assert validation["scientific_attempt_count"] == 0
    assert validation["trigger"]["no_go_close_required"] is True


def test_exact_receipt_is_complete_and_self_consistent() -> None:
    receipt = build_no_go_receipt(
        ROOT,
        base_sha=BASE_SHA,
        close_id="NO_GO_CLOSE-1",
        closed_at_utc="2026-08-01T12:00:00Z",
        run_id=RUN_ID,
        run_url=RUN_URL,
    )
    assert receipt["terminal_state"] == "NO_GO_CLOSED"
    assert receipt["run"] == {
        "id": RUN_ID,
        "url": RUN_URL,
        "github_only": True,
        "requires_local_machine": False,
    }
    assert receipt["scientific_boundaries"] == {
        "locked_start": "2021-01-01",
        "locked_data_accessed": False,
        "train_end": "2010-12-31",
        "validation_start": "2011-01-01",
        "validation_end": "2020-12-31",
        "scientific_processing_performed": False,
        "strategy_evaluation_performed": False,
        "provider_download_performed": False,
    }
    assert [event["state"] for event in receipt["events"]] == [
        "created",
        "inventory_frozen",
        "cleanup_running",
        "reconciliation",
        "NO_GO_CLOSED",
    ]
    assert receipt["event_chain_head_digest"] == receipt["events"][-1]["event_digest"]
    assert receipt["receipt_digest"] == domain_digest(
        "GTBI_V7_NO_GO_CLOSE_CONTROLLER_RECEIPT_V1",
        receipt,
        omit_top_level_fields=("receipt_digest",),
    )


def test_closure_fails_when_g0_is_not_green(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _repository_fixture(tmp_path)
    monkeypatch.setattr(
        "infra.readiness_state_controller.no_go.validate_current_readiness_records",
        lambda _root: {},
    )
    _rewrite_csv(repository / READINESS / "gate_status.csv", "status", "G0", "red")
    with pytest.raises(NoGoClosureError, match="G0 is not green"):
        validate_no_go_prerequisites(repository, BASE_SHA)


def test_closure_fails_when_no_baseline_task_is_not_done(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _repository_fixture(tmp_path)
    monkeypatch.setattr(
        "infra.readiness_state_controller.no_go.validate_current_readiness_records",
        lambda _root: {},
    )
    _rewrite_csv(
        repository / READINESS / "task_status.csv",
        "status",
        "PREV7-0307",
        "blocked",
    )
    with pytest.raises(NoGoClosureError, match="PREV7-0307 is not done"):
        validate_no_go_prerequisites(repository, BASE_SHA)


def test_closure_fails_when_scientific_attempt_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _repository_fixture(tmp_path)
    monkeypatch.setattr(
        "infra.readiness_state_controller.no_go.validate_current_readiness_records",
        lambda _root: {},
    )
    _rewrite_csv(
        repository / READINESS / "task_status.csv",
        "status",
        "PREV7-0307",
        "done",
    )
    attempts = repository / READINESS / "task_attempts.jsonl"
    existing = attempts.read_text(encoding="utf-8").splitlines()
    row = json.loads(existing[-1])
    row["task_id"] = "PREV7-0701"
    attempts.write_text("\n".join(existing + [json.dumps(row)]) + "\n", encoding="utf-8")
    with pytest.raises(NoGoClosureError, match="scientific attempt exists"):
        validate_no_go_prerequisites(repository, BASE_SHA)


def test_workflow_is_github_only_read_only_and_locked_closed() -> None:
    workflow = (ROOT / ".github/workflows/gtbi-v7-no-go-close.yml").read_text(
        encoding="utf-8"
    )
    assert "runs-on: ubuntu-24.04" in workflow
    assert "contents: read" in workflow
    assert "persist-credentials: false" in workflow
    assert "self-hosted" not in workflow
    assert "C:\\" not in workflow
    assert "2021-01-01" not in workflow
    assert "workflow_dispatch:" in workflow
