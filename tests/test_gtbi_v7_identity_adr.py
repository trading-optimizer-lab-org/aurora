from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

from infra.gtbi_v7_readiness.canonical import canonical_bytes
from infra.gtbi_v7_readiness.controller import (
    validate_current_readiness_records,
)
from infra.readiness_state_controller.engine import (
    build_transition_projection,
    write_transition_projection,
)
from infra.readiness_state_controller.policy import (
    validate_transition_manifest,
)
from scripts.generate_gtbi_v7_identity_scope_contract import (
    TASK_ORDER,
    build_manifest,
    build_receipt,
)

ROOT = Path(__file__).resolve().parents[1]
ADR = ROOT / "docs/adr/0003-gtbi-v7-identity.md"


def test_gtbi_v7_identity_adr_freezes_required_identity() -> None:
    text = ADR.read_text(encoding="utf-8")
    required = {
        "product=GTBI V7 Performance Engine",
        "reference_engine=GTBI Fast Strict V6",
        "clean_portfolio_in_scope=false",
        "scientific_change_allowed=false",
        "full_run_authorized=false",
        "train_end=2010-12-31",
        "validation_start=2011-01-01",
        "validation_end=2020-12-31",
        "historical_exclusion_start=2021-01-01",
        "locked_start=2021-01-01",
        "execution_environment=GitHub Actions",
        "identity_approval=accepted_owner_controlled",
        "g1a_state_transition=state_controller_required",
    }
    for value in required:
        assert value in text


def test_gtbi_v7_identity_adr_accepts_scope_without_run_authority() -> None:
    text = ADR.read_text(encoding="utf-8")
    assert "Status: `ACCEPTED_OWNER_CONTROLLED`" in text
    assert "grants no scientific execution" in text
    assert "full_run_authorized=true" not in text


def test_identity_receipt_and_transition_manifest_are_exact() -> None:
    receipt = build_receipt()
    receipt_path = (
        ROOT / "docs/readiness/gtbi-v7/v7_identity_scope_receipt.json"
    )
    assert receipt_path.read_bytes() == canonical_bytes(receipt) + b"\n"
    assert receipt["locked_data_accessed"] is False
    assert receipt["scientific_work_performed"] is False
    assert receipt["full_run_authorized"] is False
    assert receipt["task_acceptance"] == {
        "PREV7-0101": "accepted_owner_controlled",
        "PREV7-0102": "implemented_and_accepted_owner_controlled",
        "PREV7-0103": "accepted_owner_controlled",
    }

    manifest = build_manifest()
    manifest_path = (
        ROOT
        / "docs/readiness/gtbi-v7/transition_manifests/"
        "g1a-identity-close-v1.json"
    )
    assert manifest_path.read_bytes() == canonical_bytes(manifest) + b"\n"
    assert tuple(
        action["task_id"] for action in manifest["task_actions"]
    ) == TASK_ORDER
    assert manifest["gate_actions"][0]["gate_id"] == "G1A"
    validate_transition_manifest(manifest)


def test_g1a_projection_closes_only_identity_tasks_and_gate(
    tmp_path: Path,
) -> None:
    with (
        ROOT / "docs/readiness/gtbi-v7/gate_status.csv"
    ).open(encoding="utf-8", newline="") as handle:
        current_gates = {
            row["gate_id"]: row for row in csv.DictReader(handle)
        }
    if current_gates["G1A"]["status"] == "green":
        with (
            ROOT / "docs/readiness/gtbi-v7/task_status.csv"
        ).open(encoding="utf-8", newline="") as handle:
            current_tasks = {
                row["id"]: row for row in csv.DictReader(handle)
            }
        assert all(
            current_tasks[task_id]["status"] == "done"
            for task_id in TASK_ORDER
        )
        validate_current_readiness_records(ROOT)
        return

    repository = tmp_path / "repository"
    shutil.copytree(
        ROOT / "docs/readiness/gtbi-v7",
        repository / "docs/readiness/gtbi-v7",
    )
    projection = build_transition_projection(
        repository,
        build_manifest(),
        base_sha="c" * 40,
    )
    assert projection.receipt["locked_data_accessed"] is False
    assert projection.receipt["scientific_work_performed"] is False
    write_transition_projection(repository, projection)
    result = validate_current_readiness_records(repository)
    assert set(TASK_ORDER).issubset(result["terminal_task_ids"])

    with (
        repository / "docs/readiness/gtbi-v7/gate_status.csv"
    ).open(encoding="utf-8") as handle:
        text = handle.read()
    assert "G1A,G1A-attempt-0001,2,green" in text
