from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

from infra.gtbi_v7_readiness.controller import (
    validate_gate_event_chain,
    validate_task_event_chain,
)
from infra.gtbi_v7_readiness.canonical import canonical_bytes
from infra.gtbi_v7_readiness.genesis import (
    BRANCH_TASKS,
    FULL_DISPOSITION_SUCCESSORS,
    build_initial_records,
    validate_initial_records,
    write_initial_records,
)
from infra.gtbi_v7_readiness.records import RECORD_SCHEMAS

ROOT = Path(__file__).resolve().parents[1]
READINESS = ROOT / "docs/readiness/gtbi-v7"


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _jsonl_rows(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def test_initial_records_have_exact_coverage_and_no_claimed_completion() -> None:
    built = build_initial_records(ROOT)
    tasks = built["task_status.csv"]
    gates = built["gate_status.csv"]
    assert len(tasks) == 110
    assert len(gates) == 15
    assert {row["status"] for row in tasks} == {"blocked"}
    assert {row["status"] for row in gates} == {"red"}
    assert not any(row["completed_at"] for row in tasks)
    assert not any(row["approved_at"] for row in tasks)
    assert built["task_attempts.jsonl"] == []


def test_initial_projection_uses_immutable_inventory_binding() -> None:
    path = READINESS / "initial_inventory_binding.json"
    binding = json.loads(path.read_text(encoding="utf-8"))
    current_inventory = json.loads(
        (ROOT / "docs/project_inventory/audit_metadata.json").read_text(
            encoding="utf-8"
        )
    )

    assert path.read_bytes() == canonical_bytes(binding) + b"\n"
    assert binding["default_branch_sha"] == (
        "56251bbdd76a994b5032b912e9266253af3f4091"
    )
    assert binding["role_registry_text_digest"] == (
        "sha256:14b5266364b2c255d4f5e7796970d192d20d1c1066cd9cbf1f72b02048cfb72e"
    )
    assert binding["snapshot_digest"] != current_inventory["snapshot_digest"]
    built = build_initial_records(ROOT)
    assert {
        row["base_sha"] for row in built["task_status.csv"]
    } == {binding["default_branch_sha"]}
    assert {
        row["participant_availability_manifest_digest"]
        for row in built["task_status.csv"]
    } == {binding["role_registry_text_digest"]}


def test_initial_events_cover_every_projection_and_validate() -> None:
    built = build_initial_records(ROOT)
    task_events = built["task_events.jsonl"]
    gate_events = built["gate_events.jsonl"]
    assert len(task_events) == 110
    assert len(gate_events) == 15
    validate_task_event_chain(task_events)
    validate_gate_event_chain(gate_events)


def test_branch_registry_covers_all_declared_initial_branch_tasks() -> None:
    rows = _csv_rows(READINESS / "conditional_branch_registry.csv")
    keys = {(row["branch_id"], row["task_id"]) for row in rows}
    expected = {
        (branch_id, task_id)
        for branch_id, task_ids in BRANCH_TASKS.items()
        for task_id in task_ids
    }
    expected.update(
        ("FULL_DISPOSITION", task_id)
        for task_id in FULL_DISPOSITION_SUCCESSORS
    )
    assert keys == expected
    assert all(not row["selected_successor"] for row in rows)
    assert all(not row["decision_receipt_digest"] for row in rows)


def test_generator_is_byte_deterministic(tmp_path: Path) -> None:
    for relative in (
        "docs/plans/gtbi-v7-master-plan.md",
        "docs/readiness/gtbi-v7/owner_simplification_directive.json",
        "docs/readiness/gtbi-v7/initial_inventory_binding.json",
        (
            "config/gtbi/fixtures/v7/governance/"
            "role_registry_v1.owner_controlled.json"
        ),
    ):
        source = ROOT / relative
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    first = write_initial_records(tmp_path)
    first_bytes = {path.name: path.read_bytes() for path in first}
    second = write_initial_records(tmp_path)
    assert {path.name: path.read_bytes() for path in second} == first_bytes
    validate_initial_records(tmp_path)


def test_generator_is_independent_of_checkout_line_endings(
    tmp_path: Path,
) -> None:
    for relative in (
        "docs/plans/gtbi-v7-master-plan.md",
        "docs/readiness/gtbi-v7/owner_simplification_directive.json",
        "docs/readiness/gtbi-v7/initial_inventory_binding.json",
        (
            "config/gtbi/fixtures/v7/governance/"
            "role_registry_v1.owner_controlled.json"
        ),
    ):
        source = ROOT / relative
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        lf_bytes = source.read_bytes().replace(b"\r\n", b"\n").replace(
            b"\r", b"\n"
        )
        destination.write_bytes(lf_bytes)

    assert build_initial_records(tmp_path) == build_initial_records(ROOT)


def test_every_record_matches_declared_schema_filename() -> None:
    built = build_initial_records(ROOT)
    assert set(built) == {schema.filename for schema in RECORD_SCHEMAS}
