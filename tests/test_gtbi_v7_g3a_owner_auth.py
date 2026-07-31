"""Tests for the owner-authorized GTBI V7 G3A auth alternative."""

from __future__ import annotations

import copy
import csv
import json
import shutil
from pathlib import Path

import pytest

from infra.gtbi_v7_readiness.canonical import canonical_bytes, domain_digest
from infra.gtbi_v7_readiness.controller import (
    validate_current_readiness_records,
)
from infra.gtbi_v7_readiness.g3a_governance import (
    CANONICAL_SOURCE_ENVIRONMENTS,
)
from infra.gtbi_v7_readiness.g3a_owner_auth import (
    AUTHENTICATION_MODEL,
    G3A_OWNER_AUTH_TASK_IDS,
    G3AOwnerAuthError,
    build_owner_auth_receipt,
)
from infra.readiness_state_controller.engine import (
    build_transition_projection,
    write_transition_projection,
)
from infra.readiness_state_controller.policy import (
    validate_transition_manifest,
)
from scripts.generate_gtbi_v7_g3a_owner_auth_completion import (
    MANIFEST,
    RECEIPT,
    SOURCE_PATHS,
    build_receipt,
    build_transition_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
READINESS = ROOT / "docs/readiness/gtbi-v7"
RECORDED_AT = "2026-07-31T14:00:00Z"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _task_rows() -> list[dict[str, str]]:
    with (READINESS / "task_status.csv").open(
        encoding="utf-8",
        newline="",
    ) as handle:
        return list(csv.DictReader(handle))


def _source_inputs() -> dict:
    return {
        "owner_directive": _read_json(
            SOURCE_PATHS["owner_simplification_directive.json"]
        ),
        "owner_decisions": _read_json(
            SOURCE_PATHS["owner_decisions.json"]
        ),
        "foundation": _read_json(
            SOURCE_PATHS["g0_owner_controlled_foundation_report.json"]
        ),
        "live_baseline": _read_json(
            SOURCE_PATHS["g3a_github_live_receipt.json"]
        ),
        "frozen_data_release": _read_json(
            SOURCE_PATHS["frozen_data_lake_github_release_receipt.json"]
        ),
        "packages_inventory": _read_json(
            SOURCE_PATHS["github_packages_inventory_receipt.json"]
        ),
        "task_rows": _task_rows(),
        "evidence_file_sha256": {
            name: "sha256:" + ("0" * 64) for name in SOURCE_PATHS
        },
        "recorded_at_utc": RECORDED_AT,
    }


def test_owner_auth_receipt_and_manifest_are_canonical() -> None:
    receipt = build_receipt(recorded_at_utc=RECORDED_AT)
    manifest = build_transition_manifest(
        receipt,
        requested_at_utc=RECORDED_AT,
    )
    assert RECEIPT.read_bytes() == canonical_bytes(receipt) + b"\n"
    assert MANIFEST.read_bytes() == canonical_bytes(manifest) + b"\n"
    assert receipt["receipt_digest"] == domain_digest(
        "GTBI_V7_G3A_OWNER_AUTH_COMPLETION_RECEIPT_V1",
        receipt,
        omit_top_level_fields=("receipt_digest",),
    )
    validate_transition_manifest(manifest)


def test_owner_auth_receipt_freezes_exact_security_and_science_boundaries() -> None:
    receipt = build_receipt(recorded_at_utc=RECORDED_AT)
    assert receipt["authentication"] == {
        "model": AUTHENTICATION_MODEL,
        "source_github_apps_required": False,
        "source_github_app_installation_count": 0,
        "external_key_broker_required": False,
        "long_lived_token_in_workflow": False,
        "credential_persistence": "none",
    }
    assert receipt["github_governance"]["environment_names"] == list(
        CANONICAL_SOURCE_ENVIRONMENTS
    )
    assert receipt["github_governance"]["read_packages_scope_present"] is True
    assert receipt["private_data_transport"]["repository_private"] is True
    assert receipt["private_data_transport"]["github_only_verification"] is True
    assert receipt["private_data_transport"]["requires_local_machine"] is False
    assert receipt["scientific_boundaries"] == {
        "train_end": "2010-12-31",
        "validation_start": "2011-01-01",
        "validation_end": "2020-12-31",
        "locked_start": "2021-01-01",
        "locked_data_accessed": False,
        "scientific_processing_performed": False,
        "local_research_run_performed": False,
    }


def test_owner_auth_transition_closes_only_remaining_g3a_tasks_and_gate(
    tmp_path: Path,
) -> None:
    with (READINESS / "gate_status.csv").open(
        encoding="utf-8",
        newline="",
    ) as handle:
        gates = {row["gate_id"]: row for row in csv.DictReader(handle)}
    if gates["G3A"]["status"] == "green":
        with (READINESS / "task_status.csv").open(
            encoding="utf-8",
            newline="",
        ) as handle:
            tasks = {row["id"]: row for row in csv.DictReader(handle)}
        assert all(tasks[task_id]["status"] == "done" for task_id in G3A_OWNER_AUTH_TASK_IDS)
        validate_current_readiness_records(ROOT)
        return

    repository = tmp_path / "repository"
    shutil.copytree(READINESS, repository / "docs/readiness/gtbi-v7")
    receipt = build_receipt(recorded_at_utc=RECORDED_AT)
    projection = build_transition_projection(
        repository,
        build_transition_manifest(receipt, requested_at_utc=RECORDED_AT),
        base_sha="d" * 40,
    )
    assert projection.receipt["locked_data_accessed"] is False
    assert projection.receipt["scientific_work_performed"] is False
    write_transition_projection(repository, projection)
    result = validate_current_readiness_records(repository)
    assert set(G3A_OWNER_AUTH_TASK_IDS).issubset(result["terminal_task_ids"])

    with (repository / "docs/readiness/gtbi-v7/task_status.csv").open(
        encoding="utf-8",
        newline="",
    ) as handle:
        tasks = {row["id"]: row for row in csv.DictReader(handle)}
    with (repository / "docs/readiness/gtbi-v7/gate_status.csv").open(
        encoding="utf-8",
        newline="",
    ) as handle:
        projected_gates = {
            row["gate_id"]: row for row in csv.DictReader(handle)
        }
    with (
        repository
        / "docs/readiness/gtbi-v7/conditional_branch_registry.csv"
    ).open(encoding="utf-8", newline="") as handle:
        branches = {
            (row["branch_id"], row["task_id"]): row
            for row in csv.DictReader(handle)
        }
    assert all(tasks[task_id]["status"] == "done" for task_id in G3A_OWNER_AUTH_TASK_IDS)
    assert all(
        tasks[task_id]["alternative_completion_receipt_set_digest"]
        == receipt["receipt_digest"]
        for task_id in G3A_OWNER_AUTH_TASK_IDS
    )
    assert projected_gates["G3A"]["status"] == "green"
    assert projected_gates["G3A"]["blocking_reason"] == ""
    assert branches[("APP_PRIVATE_KEY_IMPORT", "PREV7-0204")][
        "selected_successor"
    ] == "owner_controlled_ephemeral_github_token"
    assert len(result["terminal_task_ids"]) == 22


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (
            ("foundation", "private_authentication", "external_github_app_required"),
            True,
            "external GitHub App is still required",
        ),
        (
            ("foundation", "private_authentication", "long_lived_token_in_workflow"),
            True,
            "long-lived workflow token is forbidden",
        ),
        (
            ("frozen_data_release", "repository_private"),
            False,
            "frozen data repository is not private",
        ),
        (
            ("frozen_data_release", "requires_local_machine"),
            True,
            "frozen data release depends on the local machine",
        ),
        (
            ("frozen_data_release", "locked_start"),
            "2022-01-01",
            "frozen release locked boundary mismatch",
        ),
        (
            ("packages_inventory", "read_packages_scope_present"),
            False,
            "read:packages scope is not verified",
        ),
        (
            ("live_baseline", "scientific_boundaries", "locked_data_accessed"),
            True,
            "live baseline accessed locked data",
        ),
    ],
)
def test_owner_auth_rejects_weakened_evidence(
    path: tuple[str, ...],
    value: object,
    message: str,
) -> None:
    inputs = copy.deepcopy(_source_inputs())
    target = inputs
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(G3AOwnerAuthError, match=message):
        build_owner_auth_receipt(**inputs)


def test_owner_auth_rejects_incomplete_environment_set() -> None:
    inputs = copy.deepcopy(_source_inputs())
    inputs["live_baseline"]["canonical_source_environments"].pop()
    inputs["live_baseline"]["evaluation"]["environment_count"] -= 1
    with pytest.raises(G3AOwnerAuthError, match="environment count mismatch"):
        build_owner_auth_receipt(**inputs)


def test_owner_auth_rejects_inconsistent_task_state() -> None:
    inputs = copy.deepcopy(_source_inputs())
    statuses = {
        row["id"]: row["status"]
        for row in inputs["task_rows"]
        if row["id"] in G3A_OWNER_AUTH_TASK_IDS
    }
    inconsistent_status = (
        "done" if statuses["PREV7-0210"] == "blocked" else "blocked"
    )
    for row in inputs["task_rows"]:
        if row["id"] == "PREV7-0204":
            row["status"] = inconsistent_status
    with pytest.raises(G3AOwnerAuthError, match="consistently blocked or done"):
        build_owner_auth_receipt(**inputs)
