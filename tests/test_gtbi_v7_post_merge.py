from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import pytest

from infra.gtbi_v7_readiness.canonical import canonical_bytes
from infra.gtbi_v7_readiness.post_merge import (
    PostMergeValidationError,
    validate_pr1_merge_receipt,
)

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = (
    ROOT
    / "docs/readiness/gtbi-v7/pr1_merge_reconciliation_receipt.json"
)


def test_checked_in_pr1_merge_receipt_is_complete() -> None:
    receipt = validate_pr1_merge_receipt(ROOT)
    assert receipt["base_sha"] == (
        "56251bbdd76a994b5032b912e9266253af3f4091"
    )
    assert receipt["head_sha"] == (
        "a559dbb1fa5de30b3250083d38be2672c702fb48"
    )
    assert receipt["merge_sha"] == (
        "177b9d3f4ed4f784c8b682e50d7ccca5bf79ba16"
    )
    assert receipt["all_checks_success"] is True
    assert receipt["check_count"] == 25
    assert receipt["maximum_incremental_net_spend_usd"] == 0


def test_receipt_rejects_a_non_success_ci_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    receipt["ci_runs"][0]["conclusion"] = "failure"
    fake = tmp_path / "receipt.json"
    fake.write_bytes(canonical_bytes(receipt) + b"\n")
    monkeypatch.setattr(
        "infra.gtbi_v7_readiness.post_merge.RECEIPT_FILENAME",
        "receipt.json",
    )
    monkeypatch.setattr(
        "infra.gtbi_v7_readiness.post_merge.canonical_bytes",
        lambda value: canonical_bytes(value),
    )
    destination = tmp_path / "docs/readiness/gtbi-v7"
    destination.mkdir(parents=True)
    (destination / "receipt.json").write_bytes(fake.read_bytes())
    for relative in receipt["initial_record_digests"]:
        source = ROOT / relative
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    plan = tmp_path / "docs/plans/gtbi-v7-master-plan.md"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_bytes(
        (ROOT / "docs/plans/gtbi-v7-master-plan.md").read_bytes()
    )
    for relative in (
        "docs/readiness/gtbi-v7/owner_simplification_directive.json",
        "docs/readiness/gtbi-v7/initial_inventory_binding.json",
        "docs/readiness/gtbi-v7/canonical_successor_authorization.json",
        (
            "config/gtbi/fixtures/v7/governance/"
            "role_registry_v1.owner_controlled.json"
        ),
    ):
        source = ROOT / relative
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

    with pytest.raises(
        PostMergeValidationError,
        match="non-success",
    ):
        validate_pr1_merge_receipt(tmp_path)


def test_successor_amendment_preserves_historical_pr1_receipt() -> None:
    receipt = validate_pr1_merge_receipt(ROOT)
    authorization = json.loads(
        (
            ROOT
            / "docs/readiness/gtbi-v7/canonical_successor_authorization.json"
        ).read_text(encoding="utf-8")
    )
    assert authorization["historical_pr1_bootstrap"] == {
        "immutable_historical_record": True,
        "master_plan_git_blob_id": receipt["master_plan_git_blob_id"],
        "master_plan_sha256": receipt["master_plan_sha256"],
        "pr1_merge_receipt_digest": receipt["receipt_digest"],
    }
    with (
        ROOT / "docs/readiness/gtbi-v7/task_planning_inputs.csv"
    ).open(encoding="utf-8", newline="") as handle:
        foundation = next(
            row for row in csv.DictReader(handle) if row["task_id"] == "PREV7-0000"
        )
    assert foundation["estimate_basis_digest"] == receipt["master_plan_sha256"]


def test_successor_amendment_rejects_current_plan_drift(tmp_path: Path) -> None:
    shutil.copytree(ROOT / "docs", tmp_path / "docs")
    shutil.copytree(ROOT / "config", tmp_path / "config")
    plan = tmp_path / "docs/plans/gtbi-v7-master-plan.md"
    plan.write_text(plan.read_text(encoding="utf-8") + "\nDRIFT\n", encoding="utf-8")

    with pytest.raises(
        PostMergeValidationError,
        match="canonical-successor master-plan SHA-256 mismatch",
    ):
        validate_pr1_merge_receipt(tmp_path)
