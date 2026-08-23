from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from aurora.infra.sp500_megarun.catalog_controller import (
    CatalogCapacityAdmissionEvidenceV1,
)
from scripts.prepare_catalog_admission_decision import build_operational_plan


ROOT = Path(__file__).resolve().parents[1]


def _capacity(workers: int) -> CatalogCapacityAdmissionEvidenceV1:
    return CatalogCapacityAdmissionEvidenceV1(
        status="ready",
        observed_at="2026-08-21T12:00:00Z",
        source_sha256="1" * 64,
        content_sha256="2" * 64,
        receipt_sha256="3" * 64,
        capacity_known=True,
        temporarily_unavailable=False,
        compatible_qualified_ceiling=360,
        current_safe_free_capacity=workers,
        selected_workers=workers,
        standard_runner_only=True,
        paid_runner_minutes=0,
        estimated_paid_actions_cost=0,
        artifact_storage_headroom_proven=True,
        cache_storage_headroom_proven=True,
        resource_margin_verified=True,
        compatible_safe_floor_used=True,
        retry_not_before=None,
        capacity_receipt_sha256="4" * 64,
    )


def test_operational_plan_binds_every_candidate_and_capacity_identity() -> None:
    plan = build_operational_plan(
        capacity=_capacity(120),
        candidate_manifest_sha256="5" * 64,
        execution_protocol_sha256="6" * 64,
        contract_sha256="7" * 64,
        runtime_identity_sha256="8" * 64,
        source_artifact_plan_sha256="9" * 64,
        store_metadata_sha256="a" * 64,
        recipe_dag_manifest_sha256="b" * 64,
        operational_qualification_sha256="c" * 64,
        logical_recipe_count=209_906,
        unique_component_count=84_499,
        component_workers=120,
    )

    assert plan["workers"] == 120
    assert plan["component_workers"] == 120
    assert plan["logical_recipe_count"] == 209_906
    assert plan["candidate_manifest_sha256"] == "5" * 64
    assert plan["capacity_receipt_sha256"] == "4" * 64


def test_admission_decision_cli_has_no_arbitrary_discovery_or_execution_options() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/prepare_catalog_admission_decision.py"),
            "--help",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    for forbidden in (
        "--repository",
        "--url",
        "--token",
        "--command",
        "--workflow",
        "--campaign",
        "--catalog-dir",
        "--policy",
        "--workers",
    ):
        assert forbidden not in result.stdout
