"""Freeze the evidence-backed V6 reproducibility classification."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from infra.gtbi_v7_readiness.canonical import (  # noqa: E402
    canonical_bytes,
    domain_digest,
    raw_sha256,
)

READINESS = ROOT / "docs/readiness/gtbi-v7"
RECOVERY_REPORT = READINESS / "v6_dependency_recovery_report.json"
OWNER_DIRECTIVE = READINESS / "owner_simplification_directive.json"
RECEIPT = READINESS / "g2_reproducibility_classification_receipt.json"
MANIFEST = READINESS / "transition_manifests/g2-reproducibility-classification-v1.json"
RECORDED_AT_UTC = "2026-07-31T17:30:00Z"


def _task_expected_result() -> str:
    with (READINESS / "task_status.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return next(row["expected_result"] for row in rows if row["id"] == "PREV7-0306")


def _load_and_validate_recovery_report() -> dict[str, Any]:
    report = json.loads(RECOVERY_REPORT.read_text(encoding="utf-8"))
    if RECOVERY_REPORT.read_bytes() != canonical_bytes(report) + b"\n":
        raise ValueError("V6 dependency recovery report is not canonical")
    expected = domain_digest(
        "GTBI_V6_DEPENDENCY_RECOVERY_REPORT_V1",
        report,
        omit_top_level_fields=("report_digest",),
    )
    if report["report_digest"] != expected:
        raise ValueError("V6 dependency recovery report digest mismatch")
    if report["reproducibility_classification"] != "result_preserved_inputs_incomplete":
        raise ValueError("unexpected V6 reproducibility classification")
    if report["missing_layers"] != ["D0", "D1", "D2"]:
        raise ValueError("unexpected V6 missing dependency layers")
    if report["full_v6_reproduction_claim_allowed"] is not False:
        raise ValueError("incomplete inputs cannot support a full V6 reproduction claim")
    if report["reuse_recovered_v6_inputs"] is not False:
        raise ValueError("incomplete inputs cannot be reused as the exact V6 baseline")
    if report["locked_data_opened"] or report["scientific_processing_performed"]:
        raise ValueError("classification evidence touched science or locked data")
    return report


def build_receipt() -> dict[str, Any]:
    report = _load_and_validate_recovery_report()
    layers = {row["layer"]: row for row in report["layers"]}
    receipt: dict[str, Any] = {
        "schema_version": "gtbi_v7_reproducibility_classification_receipt_v1",
        "repository": "trading-optimizer-lab-org/aurora",
        "task_id": "PREV7-0306",
        "recorded_at_utc": RECORDED_AT_UTC,
        "classification": "result_preserved_inputs_incomplete",
        "classification_reason": (
            "The V6 result, source, derived D3 data and strategy pack are authenticated, "
            "but original D0, D1 and D2 input lineage is incomplete."
        ),
        "authenticated_layers": [
            layer
            for layer in ("C", "D3", "S", "R")
            if layers[layer]["authenticated"] and layers[layer]["reproducible"]
        ],
        "missing_layers": report["missing_layers"],
        "full_v6_reproduction_claim_allowed": False,
        "reuse_recovered_v6_inputs": False,
        "oracle_b_status": "unavailable_original_inputs_incomplete",
        "v6_historical_reproduction_confirmed": False,
        "v7_baseline_effect": "blocked_pending_separate_authenticated_input_identity",
        "source_report_path": RECOVERY_REPORT.relative_to(ROOT).as_posix(),
        "source_report_sha256": raw_sha256(RECOVERY_REPORT),
        "source_report_digest": report["report_digest"],
        "source_result_archive_sha256": report["source_result_archive_sha256"],
        "source_result_run_id": report["source_result_run_id"],
        "owner_directive_digest": raw_sha256(OWNER_DIRECTIVE),
        "github_only_verification": report["github_only_verification"],
        "requires_local_machine": report["requires_local_machine"],
        "scientific_boundaries": {
            "locked_start": "2021-01-01",
            "locked_data_accessed": False,
            "scientific_processing_performed": False,
            "strategy_evaluation_performed": False,
        },
        "receipt_digest": "",
    }
    receipt["receipt_digest"] = domain_digest(
        "GTBI_V7_REPRODUCIBILITY_CLASSIFICATION_RECEIPT_V1",
        receipt,
        omit_top_level_fields=("receipt_digest",),
    )
    return receipt


def build_transition_manifest(receipt: dict[str, Any]) -> dict[str, Any]:
    evidence_paths = [
        RECEIPT.relative_to(ROOT).as_posix(),
        RECOVERY_REPORT.relative_to(ROOT).as_posix(),
        OWNER_DIRECTIVE.relative_to(ROOT).as_posix(),
    ]
    manifest: dict[str, Any] = {
        "schema_version": "gtbi_v7_readiness_transition_manifest_v1",
        "manifest_id": "g2-reproducibility-classification-v1",
        "transaction_id": "G2_CLOSE-1",
        "requested_at_utc": RECORDED_AT_UTC,
        "actor_id": "github-user:271768688",
        "actor_role": "implementer",
        "expected_base_ref": "refs/heads/main",
        "expected_base_sha_mode": "runtime_default_branch_head",
        "task_actions": [
            {
                "task_id": "PREV7-0306",
                "target_status": "done",
                "evidence_paths": evidence_paths,
                "evidence_sha256": [raw_sha256(ROOT / path) for path in evidence_paths],
                "terminal_reason": "v6_reproducibility_classified_inputs_incomplete",
                "notes": (
                    "V6 is classified without recalculation. The preserved result remains "
                    "historical evidence, but incomplete original input lineage blocks a full "
                    "reproduction claim and reuse as the exact V7 baseline."
                ),
                "files_touched": evidence_paths,
                "expected_result": _task_expected_result(),
                "alternative_completion_receipt_set_digest_or_null": receipt["receipt_digest"],
            }
        ],
        "branch_actions": [],
        "gate_actions": [],
        "owner_directive_digest": raw_sha256(OWNER_DIRECTIVE),
        "manifest_digest": "",
    }
    manifest["manifest_digest"] = domain_digest(
        "GTBI_V7_READINESS_TRANSITION_MANIFEST_V1",
        manifest,
        omit_top_level_fields=("manifest_digest",),
    )
    return manifest


def main() -> int:
    receipt = build_receipt()
    RECEIPT.write_bytes(canonical_bytes(receipt) + b"\n")
    manifest = build_transition_manifest(receipt)
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_bytes(canonical_bytes(manifest) + b"\n")
    print(json.dumps({"classification": receipt["classification"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
