from dataclasses import asdict
from datetime import timedelta

import pytest

from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_owner import (
    verify_checkpoint_failure_owner,
)
from aurora.infra.sp500_megarun.catalog_fast_path import CatalogTerminalReceiptV1

from tests.test_catalog_checkpoint_recovery_owner import _case


def _terminal_case():
    profile, owner = _case()
    profile.target_generation = 9
    profile.source_generation = 8
    profile.expected_total_count = 37258
    terminal = CatalogTerminalReceiptV1.create(
        state="BLOCKED", reason_code="CATALOG_REDUCTION_FAILED",
        request_sha256=owner.decision.request_sha256,
        submission_key_sha256=owner.decision.submission_key_sha256,
        campaign_key=owner.decision.campaign_key,
        prepared_receipt_sha256=owner.decision.prepared_receipt_sha256,
        engine_run_id=owner.run_id,
        run_url=f"https://github.com/trading-optimizer-lab-org/aurora/actions/runs/{owner.run_id}",
        expected_recipe_count=37258, observed_recipe_count=0,
        queue_seconds=0.0, preparation_seconds=0.0, computation_seconds=0.0,
        recovery_seconds=0.0, reduction_seconds=0.0, recovered_block_count=0,
        failure_class="infrastructure", result_science_sha256=None,
        created_at=owner.decision.decided_at + timedelta(minutes=10),
    )
    profile.source_terminal_receipt_sha256 = terminal.receipt_sha256
    owner.jobs[0]["conclusion"] = "success"
    for step in owner.jobs[0]["steps"]:
        step["conclusion"] = "success"
    return profile, owner, terminal


def test_checkpoint_terminal_owner_preserves_terminal_and_has_distinct_proof():
    profile, owner, terminal = _terminal_case()
    proof = verify_checkpoint_failure_owner(profile=profile, owner=owner, terminal=terminal)
    assert proof.evidence_kind == "failed_owner_with_terminal"
    assert proof.source_finalizer_job_id == owner.jobs[0]["id"]
    assert proof.source_request_sha256 == terminal.request_sha256
    assert "terminal_receipt_sha256" not in asdict(proof)


@pytest.mark.parametrize("defect", [
    "missing", "receipt", "request", "campaign", "reason", "observed",
    "total", "science", "engine", "finalizer", "publish", "wrong_generation",
])
def test_checkpoint_terminal_owner_rejects_nonexact_terminal(defect):
    profile, owner, terminal = _terminal_case()
    if defect == "missing":
        terminal = None
    elif defect == "receipt":
        profile.source_terminal_receipt_sha256 = "f" * 64
    elif defect == "finalizer":
        owner.jobs[0]["conclusion"] = "failure"
    elif defect == "publish":
        owner.jobs[0]["steps"][2]["conclusion"] = "skipped"
    elif defect == "wrong_generation":
        profile.target_generation = 8
    else:
        changes = {
            "request": {"request_sha256": "f" * 64},
            "campaign": {"campaign_key": "catalog-fast-canary-v1"},
            "reason": {"reason_code": "CATALOG_ENGINE_STAGE_FAILED"},
            "observed": {"observed_recipe_count": 1},
            "total": {"expected_recipe_count": 37257},
            "science": {"result_science_sha256": "f" * 64},
            "engine": {"engine_run_id": owner.run_id + 1},
        }[defect]
        terminal = CatalogTerminalReceiptV1.create(
            **{**terminal.model_dump(exclude={"receipt_sha256"}), **changes}
        )
        profile.source_terminal_receipt_sha256 = terminal.receipt_sha256
    with pytest.raises(ValueError, match="CATALOG_CHECKPOINT_RECOVERY_OWNER_INVALID"):
        verify_checkpoint_failure_owner(profile=profile, owner=owner, terminal=terminal)
