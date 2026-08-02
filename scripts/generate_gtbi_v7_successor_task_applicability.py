"""Build the complete task-applicability ledger for the canonical GTBI V7 successor."""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from infra.gtbi_v7_readiness.canonical import canonical_bytes, domain_digest, raw_sha256

READINESS = ROOT / "docs/readiness/gtbi-v7"
SUCCESSOR_READINESS = ROOT / "docs/readiness/gtbi-v7-new-reference"
TASK_STATUS = READINESS / "task_status.csv"
OWNER_DIRECTIVE = READINESS / "owner_simplification_directive.json"
SUCCESSOR_AUTHORIZATION = READINESS / "canonical_successor_authorization.json"
FINAL_SUMMARY = SUCCESSOR_READINESS / "final_summary.json"
BENCHMARK = READINESS / "canonical_successor_benchmark_receipt.json"
SMOKE = READINESS / "canonical_successor_smoke_receipt.json"
DESTINATION = READINESS / "successor_task_applicability.json"

RETIRED_HIGH_SEPARATION = {
    "PREV7-0308",
    "PREV7-0610",
    "PREV7-0611",
    "PREV7-0708",
    "PREV7-0710",
    "PREV7-0711",
    "PREV7-0712",
    "PREV7-0713",
    "PREV7-0714",
    "PREV7-0715",
    "PREV7-0807",
    "PREV7-0808",
    "PREV7-0812",
    "PREV7-0815",
    "PREV7-0904",
    "PREV7-0906",
    "PREV7-0907",
}

CONDITIONAL_NOT_SELECTED = {
    "PREV7-0910",
    "PREV7-0911",
    "PREV7-0912",
    "PREV7-0914",
}

REMAINING_APPLICABLE = {
    "PREV7-0209",
    "PREV7-0400",
    "PREV7-0401",
    "PREV7-0402",
    "PREV7-0403",
    "PREV7-0404",
    "PREV7-0405",
    "PREV7-0406",
    "PREV7-0407",
    "PREV7-0501",
    "PREV7-0502",
    "PREV7-0505",
    "PREV7-0507",
    "PREV7-0508",
    "PREV7-0509",
    "PREV7-0601",
    "PREV7-0705",
    "PREV7-0816",
    "PREV7-0913",
    "PREV7-1001",
    "PREV7-1002",
    "PREV7-1003",
}

SUPERSEDED_BY_SUCCESSOR_CONTRACT = {
    "PREV7-0504",
    "PREV7-0606",
    "PREV7-0607",
    "PREV7-0702",
    "PREV7-0800",
    "PREV7-0801",
    "PREV7-0802",
    "PREV7-0803",
    "PREV7-0804",
    "PREV7-0805",
    "PREV7-0809",
    "PREV7-0810",
    "PREV7-0811",
    "PREV7-0813",
    "PREV7-0814",
    "PREV7-0903",
    "PREV7-0905",
}

SUCCESSOR_EVIDENCE_BY_TASK = {
    "PREV7-0310": [
        "docs/readiness/gtbi-v7/canonical_successor_authorization.json",
        "docs/readiness/gtbi-v7-new-reference/preservation_receipt.json",
    ],
    "PREV7-0503": [
        "docs/plans/gtbi-v7-new-reference-campaign.md",
        "docs/readiness/gtbi-v7-new-reference/campaign_authorization.json",
    ],
    "PREV7-0506": [
        "docs/plans/gtbi-v7-new-reference-campaign.md",
        "docs/readiness/gtbi-v7-new-reference/final_summary.json",
    ],
    "PREV7-0602": ["scripts/run_gtbi_v7_new_reference_worker.py"],
    "PREV7-0603": [
        ".github/workflows/gtbi-v7-new-reference.yml",
        ".github/workflows/gtbi-v7-new-reference-merge-recovery.yml",
    ],
    "PREV7-0604": [
        "infra/gtbi_v7_new_reference/runner.py",
        "tests/test_gtbi_v7_new_reference_runtime.py",
    ],
    "PREV7-0605": [
        "docs/readiness/gtbi-v7/canonical_successor_benchmark_receipt.json"
    ],
    "PREV7-0608": [
        ".github/workflows/gtbi-v7-new-reference.yml",
        ".github/workflows/gtbi-v7-new-reference-merge-recovery.yml",
        "docs/readiness/gtbi-v7-new-reference/final_summary.json",
    ],
    "PREV7-0609": [
        "docs/readiness/gtbi-v7/canonical_successor_benchmark_receipt.json",
        "docs/readiness/gtbi-v7-new-reference/final_summary.json",
    ],
    "PREV7-0701": [
        "tests/test_gtbi_v7_new_reference_campaign.py",
        "tests/test_gtbi_v7_new_reference_runtime.py",
        "tests/test_gtbi_v7_new_reference_workflow.py",
    ],
    "PREV7-0703": [
        "docs/readiness/gtbi-v7/canonical_successor_benchmark_receipt.json"
    ],
    "PREV7-0704": [
        ".github/workflows/gtbi-v7-new-reference-merge-recovery.yml",
        "docs/readiness/gtbi-v7-new-reference/final_summary.json",
    ],
    "PREV7-0706": ["docs/readiness/gtbi-v7/canonical_successor_smoke_receipt.json"],
    "PREV7-0707": ["docs/readiness/gtbi-v7-new-reference/final_summary.json"],
    "PREV7-0806": ["docs/readiness/gtbi-v7-new-reference/final_summary.json"],
    "PREV7-0901": [
        "docs/readiness/gtbi-v7-new-reference/final_summary.json",
        "scripts/finalize_gtbi_v7_new_reference_results.py",
    ],
    "PREV7-0902": [
        "docs/readiness/gtbi-v7-new-reference/preservation_receipt.json"
    ],
}


def _json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    if path.read_bytes() != canonical_bytes(payload) + b"\n":
        raise ValueError(f"JSON is not canonical: {path}")
    return payload


def _tasks() -> list[dict[str, str]]:
    with TASK_STATUS.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 110 or len({row["id"] for row in rows}) != 110:
        raise ValueError("the historical task registry must contain 110 unique tasks")
    return rows


def _evidence_entry(relative_path: str) -> dict[str, str]:
    path = ROOT / relative_path
    if not path.is_file():
        raise ValueError(f"missing successor evidence: {relative_path}")
    return {"path": relative_path, "sha256": raw_sha256(path)}


def _classify(row: dict[str, str]) -> tuple[str, str, list[str]]:
    task_id = row["id"]
    if row["status"] in {"done", "cancelled"}:
        return (
            "historical_terminal",
            "historical_registry_terminal_state_preserved",
            ["docs/readiness/gtbi-v7/task_status.csv"],
        )
    if task_id in RETIRED_HIGH_SEPARATION:
        return (
            "retired_high_separation",
            "owner_simplification_directive_supersedes_external_separation",
            ["docs/readiness/gtbi-v7/owner_simplification_directive.json"],
        )
    if task_id in CONDITIONAL_NOT_SELECTED:
        return (
            "conditional_not_selected",
            "completed_successor_path_did_not_select_abandonment_branch",
            ["docs/readiness/gtbi-v7-new-reference/final_summary.json"],
        )
    if task_id in REMAINING_APPLICABLE:
        return "remaining_applicable", "successor_work_still_requires_evidence", []
    if task_id in SUPERSEDED_BY_SUCCESSOR_CONTRACT:
        return (
            "superseded_by_successor_contract",
            "preauthorized_independent_campaign_contract_replaces_legacy_topology",
            [
                "docs/readiness/gtbi-v7/canonical_successor_authorization.json",
                "docs/plans/gtbi-v7-new-reference-campaign.md",
            ],
        )
    if task_id in SUCCESSOR_EVIDENCE_BY_TASK:
        return (
            "satisfied_by_successor_evidence",
            "existing_canonical_successor_evidence_satisfies_effective_requirement",
            SUCCESSOR_EVIDENCE_BY_TASK[task_id],
        )
    raise ValueError(f"unclassified blocked task: {task_id}")


def build_applicability() -> dict[str, Any]:
    directive = _json(OWNER_DIRECTIVE)
    authorization = _json(SUCCESSOR_AUTHORIZATION)
    summary = _json(FINAL_SUMMARY)
    benchmark = _json(BENCHMARK)
    smoke = _json(SMOKE)

    directive_scope = set(directive.get("authorization_scope", []))
    required_directives = {
        "remove_three_independent_audit_requirement",
        "remove_distinct_person_and_external_custodian_requirements",
    }
    if directive.get("accepted") is not True or not required_directives.issubset(
        directive_scope
    ):
        raise ValueError("owner simplification directive is not active")
    if authorization.get("state_transition_policy", {}).get(
        "target_terminal_state"
    ) != "COMPLETED_CLEAN":
        raise ValueError("canonical successor does not target COMPLETED_CLEAN")
    if summary.get("total_terminal_identities") != 72_000:
        raise ValueError("canonical successor is not complete")
    if summary.get("total_jobs_failed") != 0:
        raise ValueError("canonical successor contains failed jobs")
    if summary.get("locked_authorized") is not False:
        raise ValueError("locked was authorized")
    if summary.get("locked_data_accessed") is not False:
        raise ValueError("locked was accessed")
    if benchmark.get("receipt_digest") != summary.get("benchmark_receipt_digest"):
        raise ValueError("benchmark receipt is not bound to the final summary")
    if benchmark.get("equivalent") is not True:
        raise ValueError("one/two/four process benchmark is not equivalent")
    if smoke.get("receipt_digest") != summary.get("smoke_validation_digest"):
        raise ValueError("smoke receipt is not bound to the final summary")
    if smoke.get("valid") is not True or smoke.get("worker_count") != 100:
        raise ValueError("canonical 100-worker smoke is not valid")

    rows: list[dict[str, Any]] = []
    for task in _tasks():
        successor_status, reason, evidence_paths = _classify(task)
        rows.append(
            {
                "task_id": task["id"],
                "gate": task["gate"],
                "title": task["title"],
                "historical_status": task["status"],
                "successor_status": successor_status,
                "reason": reason,
                "evidence": [_evidence_entry(path) for path in evidence_paths],
            }
        )

    rows.sort(key=lambda value: value["task_id"])
    status_counts = dict(sorted(Counter(row["successor_status"] for row in rows).items()))
    gate_rows: list[dict[str, Any]] = []
    for gate in sorted({row["gate"] for row in rows}):
        members = [row for row in rows if row["gate"] == gate]
        remaining = [row["task_id"] for row in members if row["successor_status"] == "remaining_applicable"]
        if remaining:
            state = "remaining"
        elif all(row["successor_status"] == "conditional_not_selected" for row in members):
            state = "not_selected"
        else:
            state = "verified_or_superseded"
        gate_rows.append(
            {
                "gate": gate,
                "successor_state": state,
                "task_count": len(members),
                "remaining_task_ids": remaining,
            }
        )

    payload: dict[str, Any] = {
        "schema_version": "gtbi_v7_successor_task_applicability_v1",
        "repository": "trading-optimizer-lab-org/aurora",
        "successor_generation": "GTBI_V7_CANONICAL_SUCCESSOR_1",
        "campaign_id": "gtbi_v7_new_reference_v1",
        "historical_task_registry": {
            "path": "docs/readiness/gtbi-v7/task_status.csv",
            "sha256": raw_sha256(TASK_STATUS),
            "immutable": True,
            "task_count": len(rows),
        },
        "authority": {
            "owner_simplification_directive": _evidence_entry(
                "docs/readiness/gtbi-v7/owner_simplification_directive.json"
            ),
            "canonical_successor_authorization": _evidence_entry(
                "docs/readiness/gtbi-v7/canonical_successor_authorization.json"
            ),
        },
        "scientific_boundaries": {
            "github_only": True,
            "requires_local_machine": False,
            "train_end": "2010-12-31",
            "validation_start": "2011-01-01",
            "validation_end": "2020-12-31",
            "locked_start": "2021-01-01",
            "locked_authorized": False,
            "locked_data_accessed": False,
            "maximum_incremental_net_spend_usd": 0,
        },
        "classification_policy": {
            "historical_task_status_mutated": False,
            "no_task_may_disappear": True,
            "retired_requirements_do_not_block_successor": True,
            "conditional_unselected_tasks_do_not_block_successor": True,
            "only_remaining_applicable_blocks_completed_clean": True,
        },
        "status_counts": status_counts,
        "remaining_task_ids": sorted(REMAINING_APPLICABLE),
        "gate_projection": gate_rows,
        "tasks": rows,
    }
    payload["receipt_digest"] = domain_digest(
        "GTBI_V7_SUCCESSOR_TASK_APPLICABILITY_V1",
        payload,
        omit_top_level_fields=("receipt_digest",),
    )
    return payload


def main() -> int:
    payload = build_applicability()
    DESTINATION.write_bytes(canonical_bytes(payload) + b"\n")
    digest = hashlib.sha256(DESTINATION.read_bytes()).hexdigest()
    print(
        json.dumps(
            {
                "output": str(DESTINATION.relative_to(ROOT)),
                "sha256": f"sha256:{digest}",
                "status_counts": payload["status_counts"],
                "remaining_task_count": len(payload["remaining_task_ids"]),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
