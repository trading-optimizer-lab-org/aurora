"""Tests for the owner-controlled GTBI V7 CODEOWNERS contract."""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

from infra.gtbi_v7_readiness.canonical import (
    canonical_bytes,
    domain_digest,
    raw_sha256,
)
from infra.gtbi_v7_readiness.controller import validate_current_readiness_records
from infra.readiness_state_controller.engine import (
    build_transition_projection,
    write_transition_projection,
)
from infra.readiness_state_controller.policy import validate_transition_manifest
from scripts.generate_gtbi_v7_codeowners_contract import (
    CATALOG_CONTROLLER_PATTERNS,
    CODEOWNERS,
    CONTRACT,
    EXPECTED_PATTERNS,
    MANIFEST,
    OWNER_DECISIONS,
    OWNER_DIRECTIVE,
    RECEIPT,
    build_codeowners,
    build_historical_codeowners,
    build_receipt,
    raw_sha256_bytes,
    build_transition_manifest,
    validate_contract,
)

ROOT = Path(__file__).resolve().parents[1]
READINESS = ROOT / "docs/readiness/gtbi-v7"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_codeowners_contract_and_outputs_are_canonical() -> None:
    contract = validate_contract()
    receipt = build_receipt()
    manifest = build_transition_manifest(receipt)

    assert CONTRACT.read_bytes() == canonical_bytes(contract) + b"\n"
    assert CODEOWNERS.read_bytes() == build_codeowners()
    assert RECEIPT.read_bytes() == canonical_bytes(receipt) + b"\n"
    assert MANIFEST.read_bytes() == canonical_bytes(manifest) + b"\n"
    assert receipt["receipt_digest"] == domain_digest(
        "GTBI_V7_OWNER_CONTROLLED_CODEOWNERS_RECEIPT_V1",
        receipt,
        omit_top_level_fields=("receipt_digest",),
    )
    assert receipt["codeowners_sha256"] == raw_sha256_bytes(
        build_historical_codeowners()
    )
    assert CODEOWNERS.read_bytes().startswith(
        build_historical_codeowners().rstrip(b"\n") + b"\n\n"
    )
    assert receipt["contract_file_sha256"] == raw_sha256(CONTRACT)
    validate_transition_manifest(manifest)


def test_codeowners_has_exact_owner_only_coverage() -> None:
    lines = [
        line
        for line in CODEOWNERS.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]
    assert lines == [
        f"{pattern} @gomez5757"
        for pattern in (*EXPECTED_PATTERNS, *CATALOG_CONTROLLER_PATTERNS)
    ]
    assert len(lines) == len(set(lines))
    assert all(line.endswith(" @gomez5757") for line in lines)
    assert all(line.count("@") == 1 for line in lines)


def test_codeowners_receipt_preserves_owner_boundaries() -> None:
    receipt = build_receipt()
    assert receipt["owner"] == {
        "actor_id": "github-user:271768688",
        "github_login": "gomez5757",
        "repository_permission": "admin",
        "verified_at_utc": "2026-07-31T14:37:36Z",
        "verified_endpoint": (
            "repos/trading-optimizer-lab-org/aurora/"
            "collaborators/gomez5757/permission"
        ),
    }
    assert receipt["blocking_mode"] == "routing_only_until_stage_two"
    assert receipt["incremental_net_spend_usd"] == 0
    assert receipt["github_only_acceptance"] is True
    assert receipt["scientific_work_performed"] is False
    assert receipt["locked_data_accessed"] is False


def test_codeowners_transition_closes_only_task_0203(tmp_path: Path) -> None:
    current_before = validate_current_readiness_records(ROOT)
    if "PREV7-0203" in current_before["terminal_task_ids"]:
        with (READINESS / "task_status.csv").open(
            encoding="utf-8",
            newline="",
        ) as handle:
            tasks = {row["id"]: row for row in csv.DictReader(handle)}
        assert tasks["PREV7-0203"]["status"] == "done"
        assert tasks["PREV7-0203"][
            "alternative_completion_receipt_set_digest"
        ] == build_receipt()["receipt_digest"]
        return

    repository = tmp_path / "repository"
    shutil.copytree(READINESS, repository / "docs/readiness/gtbi-v7")
    (repository / ".github").mkdir(parents=True)
    shutil.copy2(CODEOWNERS, repository / ".github/CODEOWNERS")
    contract_target = repository / CONTRACT.relative_to(ROOT)
    contract_target.parent.mkdir(parents=True)
    shutil.copy2(CONTRACT, contract_target)

    receipt = build_receipt()
    manifest = build_transition_manifest(receipt)
    projection = build_transition_projection(
        repository,
        manifest,
        base_sha="e" * 40,
    )
    assert projection.receipt["locked_data_accessed"] is False
    assert projection.receipt["scientific_work_performed"] is False
    assert projection.receipt["gate_actions_applied"] == []
    write_transition_projection(repository, projection)

    current_after = validate_current_readiness_records(repository)
    assert len(current_after["terminal_task_ids"]) == (
        len(current_before["terminal_task_ids"]) + 1
    )
    assert "PREV7-0203" in current_after["terminal_task_ids"]

    with (repository / "docs/readiness/gtbi-v7/task_status.csv").open(
        encoding="utf-8",
        newline="",
    ) as handle:
        tasks = {row["id"]: row for row in csv.DictReader(handle)}
    with (repository / "docs/readiness/gtbi-v7/gate_status.csv").open(
        encoding="utf-8",
        newline="",
    ) as handle:
        gates = {row["gate_id"]: row for row in csv.DictReader(handle)}
    assert tasks["PREV7-0203"]["status"] == "done"
    assert tasks["PREV7-0203"]["planning_state"] == "complete"
    assert tasks["PREV7-0203"]["alternative_completion_receipt_set_digest"] == (
        receipt["receipt_digest"]
    )
    assert gates["G3B"]["status"] == "red"


def test_codeowners_sources_keep_owner_simplification_authoritative() -> None:
    directive = _read_json(OWNER_DIRECTIVE)
    decisions = _read_json(OWNER_DECISIONS)
    assert directive["precedence"] == (
        "supersedes_conflicting_independence_dual_control_external_custody_"
        "and_external_audit_requirements"
    )
    assert decisions["decisions"]["audits_and_people"] == {
        "distinct_people_required": False,
        "external_audits_required": 0,
        "external_custodians_required": False,
        "owner_controlled_model": "accepted_explicitly",
        "three_signed_audits_required": False,
    }
