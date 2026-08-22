from __future__ import annotations

import ast
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path

import pytest

from aurora.infra.github_performance.contracts import CapacityProfile, canonical_sha256
from aurora.infra.github_performance.merge_planner import MergeResourceProjectionV1
from aurora.infra.sp500_megarun.catalog_admission_adapter import (
    CatalogOperationalQualificationV1,
    github_controls_evidence_from_auditor_receipt,
    load_catalog_operational_qualification,
    select_catalog_capacity_evidence,
    verify_admission_candidate_bundle,
)
from aurora.infra.sp500_megarun.catalog_capacity_qualification import (
    BundleLayoutQualificationV1,
)
from aurora.infra.sp500_megarun.catalog_github_controls import (
    AuditorCatalogGithubControlsReceiptV1,
)
ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def _auditor_receipt(**updates: object) -> AuditorCatalogGithubControlsReceiptV1:
    payload: dict[str, object] = {
        "schema_version": "1",
        "status": "ready",
        "repository": "trading-optimizer-lab-org/aurora",
        "observed_default_branch_sha": "a" * 40,
        "observed_repository_visibility": "public",
        "checked_controls": ("A", "B"),
        "failed_controls": (),
        "heavy_workflow_inventory": (),
        "active_heavy_run_inventory": (),
        "unmanaged_active_heavy_run_ids": (),
        "request_actor_permissions": {
            "kind": "GitHubApp",
            "repository_administration": "none",
            "repository_actions": "none",
            "repository_contents": "none",
            "repository_issues": "write",
        },
        "actions_zero_spend_budgets": (
            {"budget_product_sku": "actions", "budget_amount": 0},
            {"budget_product_sku": "actions_storage", "budget_amount": 0},
            {"budget_product_sku": "actions_cache_storage", "budget_amount": 0},
        ),
        "actions_billing_usage_snapshot": {
            "paid_runner_minutes": 0,
            "estimated_paid_actions_cost": 0,
        },
        "free_artifact_storage_headroom": 8_000_000_000,
        "free_cache_storage_headroom": 4_000_000_000,
        "repository_cache_storage_limit_gb": 10,
        "repository_cache_retention_days": 90,
        "projected_campaign_artifact_bytes": 2_000_000_000,
        "projected_campaign_cache_bytes": 500_000_000,
        "local_agent_actor": None,
        "local_agent_has_admin": None,
        "auditor_installation_proof": {
            "token_minted_in_process": True,
            "fixed_get_endpoints_only": True,
        },
        "observer_context": "github_auditor",
        "audit_use_context": "controller_admission",
        "audit_context_sha256": "b" * 64,
        "protected_commit_sha": "a" * 40,
        "caller_workflow": ".github/workflows/catalog-run-controller.yml",
        "caller_job": "live_controls_audit_before_reserve",
        "observed_at": NOW,
        "github_api_observed_at": NOW,
        "source_snapshot_sha256": "c" * 64,
    }
    payload.update(updates)
    hash_payload = {
        key: (
            value.isoformat().replace("+00:00", "Z")
            if isinstance(value, datetime)
            else value
        )
        for key, value in payload.items()
    }
    payload["receipt_sha256"] = hashlib.sha256(
        json.dumps(
            hash_payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()
    return AuditorCatalogGithubControlsReceiptV1.model_validate(payload)


def _write_candidate_bundle(root: Path) -> str:
    root.mkdir()
    (root / "candidate-context.json").write_bytes(b"{}\n")
    content = ({
        "path": "candidate-context.json",
        "sha256": hashlib.sha256(b"{}\n").hexdigest(),
        "size_bytes": 3,
    },)
    identity = {
        "schema_version": "1",
        "document_type": "catalog_admission_candidate_manifest_v1",
        "request_sha256": "1" * 64,
        "campaign_id": "2" * 64,
        "applicable_commit_sha": "a" * 40,
        "execution_protocol_sha256": "3" * 64,
        "content_manifest": content,
    }
    manifest = {
        **identity,
        "candidate_manifest_sha256": canonical_sha256(identity),
    }
    (root / "candidate-manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return str(manifest["candidate_manifest_sha256"])


def _qualification(**updates: object) -> CatalogOperationalQualificationV1:
    layouts = tuple(
        BundleLayoutQualificationV1(
            bundle_count=count,
            equivalent=True,
            sample_count=3,
            memory_safe=True,
            disk_safe=True,
            runner_timeout_safe=True,
            projected_end_to_end_p50_seconds=1000.0 + count,
            projected_end_to_end_p95_seconds=1100.0 + count,
            projected_component_download_bytes=500_000_000,
            projected_cache_uploads_per_minute=10,
            projected_cache_downloads_per_minute=100,
            checkpoint_upload_seconds_p95=1.0,
        )
        for count in (8, 16, 32, 64, 96, 128)
    )
    projection = MergeResourceProjectionV1(
        timeout_fraction_p99=0.6,
        memory_fraction_p99=0.6,
        disk_fraction_p99=0.6,
        artifact_fraction_p99=0.6,
        download_fraction_p99=0.6,
        input_count_fraction_p99=0.6,
    )
    values: dict[str, object] = {
        "schema_version": "1",
        "status": "ready",
        "reason_codes": (),
        "qualified_at": NOW,
        "qualification_receipt_sha256": "4" * 64,
        "qualification_run_ids": ("100", "101", "102"),
        "bundle_layout_qualifications": layouts,
        "reduction_projection": projection,
        "hierarchical_reduction_projection": projection,
        "topology_sample_count": 3,
        "memory_fraction_p50": 0.4,
        "memory_fraction_p95": 0.5,
        "memory_fraction_p99": 0.6,
        "disk_fraction_p50": 0.3,
        "disk_fraction_p95": 0.4,
        "disk_fraction_p99": 0.5,
        "runner_start_seconds_p50": 8.0,
        "runner_start_seconds_p95": 12.0,
        "runner_start_seconds_p99": 20.0,
        "unit_seconds_p50": 1.0,
        "unit_seconds_p95": 1.5,
        "unit_seconds_p99": 2.0,
        "projected_artifact_storage_bytes": 2_000_000_000,
        "projected_cache_storage_bytes": 500_000_000,
        "planned_new_cache_entry_count": 128,
        "selected_component_bundle_count": 64,
        "planned_cache_upload_requests_per_minute_peak": 100,
        "planned_cache_download_requests_per_minute_peak": 800,
        "artifact_transport_retention_days": 1,
    }
    values.update(updates)
    return CatalogOperationalQualificationV1.model_validate(values)


def _enabled_profile() -> CapacityProfile:
    payload = json.loads((ROOT / "config/github_capacity_profile.json").read_text())
    payload.update(
        {
            "production_admission_enabled": True,
            "proven_uncontended_floor": 120,
            "qualification_receipt_sha256": "4" * 64,
            "qualification_run_ids": ["100", "101", "102"],
        }
    )
    return CapacityProfile.model_validate(payload)


def test_candidate_bundle_requires_exact_complete_content_manifest(tmp_path: Path) -> None:
    bundle = tmp_path / "candidate"
    expected = _write_candidate_bundle(bundle)

    manifest = verify_admission_candidate_bundle(bundle, expected_sha256=expected)

    assert manifest["candidate_manifest_sha256"] == expected
    (bundle / "unexpected.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="CATALOG_CANDIDATE_MANIFEST_COVERAGE_INVALID"):
        verify_admission_candidate_bundle(bundle, expected_sha256=expected)


def test_auditor_receipt_is_bound_to_exact_candidate_context_and_commit() -> None:
    evidence = github_controls_evidence_from_auditor_receipt(
        _auditor_receipt(),
        expected_audit_context_sha256="b" * 64,
        expected_protected_commit_sha="a" * 40,
    )

    assert evidence.status == "ready"
    assert evidence.controls_verified is True
    assert evidence.production_environment_verified is True
    assert evidence.paid_runner_minutes == 0
    assert evidence.zero_actions_spend_budget_verified is True
    with pytest.raises(ValueError, match="CATALOG_AUDIT_CONTEXT_MISMATCH"):
        github_controls_evidence_from_auditor_receipt(
            _auditor_receipt(),
            expected_audit_context_sha256="0" * 64,
            expected_protected_commit_sha="a" * 40,
        )


def test_unqualified_checked_profile_blocks_without_selecting_workers() -> None:
    profile = CapacityProfile.model_validate_json(
        (ROOT / "config/github_capacity_profile.json").read_text()
    )
    qualification = load_catalog_operational_qualification(
        ROOT / "config/catalog_operational_qualification_v1.json"
    )

    evidence = select_catalog_capacity_evidence(
        profile=profile,
        qualification=qualification,
        controls_receipt=_auditor_receipt(),
        registered_maximum_workers=360,
        observed_at=NOW,
    )

    assert evidence.status == "blocked"
    assert evidence.capacity_known is False
    assert evidence.selected_workers == 0
    assert evidence.temporarily_unavailable is False
    assert evidence.reason_codes == ("CATALOG_CAPACITY_UNPROVEN",)


def test_enabled_profile_uses_only_the_proven_safe_floor() -> None:
    evidence = select_catalog_capacity_evidence(
        profile=_enabled_profile(),
        qualification=_qualification(),
        controls_receipt=_auditor_receipt(),
        registered_maximum_workers=360,
        observed_at=NOW,
    )

    assert evidence.status == "ready"
    assert evidence.capacity_known is True
    assert evidence.compatible_qualified_ceiling == 360
    assert evidence.current_safe_free_capacity == 120
    assert evidence.selected_workers == 120
    assert evidence.compatible_safe_floor_used is True


def test_admission_domain_module_never_imports_an_executable_script() -> None:
    path = ROOT / "infra/sp500_megarun/catalog_admission_adapter.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert not {module for module in modules if module == "scripts" or module.startswith("scripts.")}
