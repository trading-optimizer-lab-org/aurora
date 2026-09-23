from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from infra.github_performance.preflight import load_github_yaml


ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / ".github/workflows/sp500-atlas-run.yml"


def _workflow() -> dict[str, Any]:
    return dict(load_github_yaml(WORKFLOW))


def test_cloud_call_contract_is_string_bound_and_gate_artifact_only() -> None:
    workflow = _workflow()
    trigger = workflow["on"]
    assert isinstance(trigger, dict)
    call = trigger["workflow_call"]
    inputs = call["inputs"]
    expected = {
        "authority_id",
        "campaign_id",
        "decision_sha256",
        "execution_plan_sha256",
        "execution_protocol_sha256",
        "prepared_receipt_sha256",
        "protected_commit_sha",
        "request_sha256",
        "science_sha256",
    }
    assert expected <= set(inputs)
    for name in expected:
        assert inputs[name]["type"] == "string"
        assert inputs[name]["default"] == ""
    assert "prepared_artifact_name" not in inputs
    assert "prepared_artifact_run_id" not in inputs
    assert workflow["permissions"] == {
        "actions": "read",
        "contents": "read",
    }
    assert call["outputs"]["plan_sha256"]["value"] == "${{ jobs.preflight.outputs.plan_sha256 }}"
    assert call["outputs"]["final_results_artifact"]["value"] == "sp500-atlas-final-results"


def test_cloud_gate_verifies_controller_authority_binding_and_five_file_atlas_envelope() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'test "$GITHUB_REPOSITORY" = "trading-optimizer-lab-org/aurora"' in text
    assert 'test "$GITHUB_REF" = "refs/heads/main"' in text
    assert "scripts/verify_catalog_fast_authority.py" not in text
    assert "catalog-sealed-execution-plan-${{ inputs.authority_id }}" in text
    assert '"atlas_prepared_receipt.json"' in text
    assert '"atlas_run_plan.json"' in text
    assert '"atlas_manifest.json"' in text
    assert '"atlas_sealed_envelope.json"' in text
    assert '"atlas_campaign_selection.json"' in text
    assert "ATLAS_CLOUD_GATE_ARTIFACT_LAYOUT_INVALID" in text
    assert "canonical_sha256(envelope_identity)" in text
    assert "ATLAS_CLOUD_SELECTION_PLAN_MISMATCH" in text
    assert 'shutil.copy2(selection_path, cloud_root / "atlas_campaign_selection.json")' in text
    assert 'controller_root / "atlas_campaign_selection.json"' in text
    assert '"outputs/plan/atlas_campaign_selection.json",' in text
    assert 'Path("outputs/plan/atlas_campaign_selection.json").write_text' not in text
    assert 'envelope["prepared_receipt_sha256"] != receipt.receipt_sha256' in text
    assert 'envelope["decision_sha256"] != os.environ["ATLAS_DECISION_SHA256"]' in text
    assert "ATLAS_CLOUD_SIGNED_REQUEST_OR_AUTHORITY_BINDING_INVALID" in text
    assert "verify_sealed_global_reuse_execution_plan" not in text
    assert "atlas-prepared-source" not in text


def test_cloud_uses_future_plan_but_rebuilds_only_frozen_catalog() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'manifest.get("catalog_id") != "sp500-atlas-1"' in text
    assert 'identity.campaign_key != "sp500-atlas-1"' not in text
    assert 'identity.campaign_key != "sp500-atlas-v1"' in text
    assert 'ATLAS_CATALOG_TARGET_END_ISO: "2026-08-20T07:31:00+02:00"' in text
    assert 'catalog_target="$ATLAS_CATALOG_TARGET_END_ISO"' in text
    assert 'receipt.target_end_iso == os.environ["ATLAS_CATALOG_TARGET_END_ISO"]' in text
    assert 'plan["target_end_iso"] != "2026-08-20T07:31:00+02:00"' in text
    assert "receipt.target_end_iso" in text
    assert "ATLAS_CLOUD_PREPARED_PLAN_HASH_MISMATCH" in text
    assert "ATLAS_CLOUD_PREPARED_TARGET_NOT_FUTURE" in text


def test_cloud_full_run_caps_aggregate_matrix_concurrency_at_twenty() -> None:
    workflow = _workflow()
    jobs = workflow["jobs"]
    caps = []
    for job_id, expected in (("evaluate_a", 6), ("evaluate_b", 7), ("evaluate_c", 7)):
        value = jobs[job_id]["strategy"]["max-parallel"]
        match = re.fullmatch(r"\$\{\{ inputs\.prepared_receipt_sha256 != '' && (\d+) \|\| 120 \}\}", value)
        assert match, (job_id, value)
        assert int(match.group(1)) == expected
        caps.append(int(match.group(1)))
    assert sum(caps) == 20
    assert all("needs.preflight.result == 'success'" in jobs[name]["if"] for name in ("evaluate_a", "evaluate_b", "evaluate_c"))


def test_legacy_authorization_branch_remains_distinct_from_cloud() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "AUTHORIZE_SP500_ATLAS_FULL_RUN" in text
    assert "ATLAS_FROZEN_FULL_PLAN_ACCEPTED" in text
    assert "test -z \"$LAUNCH_AUTHORIZATION\"" in text
    assert "inputs.run_mode == 'full'" in text
    assert "sp500-atlas-final-results" in text
