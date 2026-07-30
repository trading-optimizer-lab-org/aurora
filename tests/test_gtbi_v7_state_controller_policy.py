from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest
import jsonschema

from infra.gtbi_v7_readiness.canonical import (
    canonical_bytes,
    domain_digest,
    raw_sha256,
)
from infra.gtbi_v7_readiness.controller import (
    ReadinessValidationError,
    validate_current_readiness_records,
)
from infra.gtbi_v7_readiness.formal_genesis import (
    validate_formal_genesis_records,
    write_formal_genesis_records,
)
from infra.gtbi_v7_readiness.genesis import write_initial_records
from infra.readiness_state_controller.engine import (
    MUTABLE_FILENAMES,
    build_transition_projection,
    write_transition_projection,
)
from infra.readiness_state_controller.policy import (
    StateControllerError,
    load_transition_manifest,
    validate_transition_manifest,
)
from infra.readiness_state_controller.schemas import schema_documents
from scripts.generate_gtbi_v7_state_controller_smoke_manifest import (
    build_manifest as build_smoke_manifest,
)
from scripts.generate_gtbi_v7_state_controller_contract import (
    build_manifest as build_controller_contract,
)
from scripts.generate_gtbi_v7_state_controller_recovery_receipt import (
    build_receipt as build_recovery_receipt,
)
from scripts.generate_gtbi_v7_g0_apply_reconciliation_receipt import (
    SOURCE as G0_APPLY_SOURCE,
    build_receipt as build_g0_apply_receipt,
    validate_application as validate_g0_application,
)
from scripts.generate_gtbi_v7_g1a_apply_reconciliation_receipt import (
    SOURCE as G1A_APPLY_SOURCE,
    build_receipt as build_g1a_apply_receipt,
    validate_application as validate_g1a_application,
)
from scripts.generate_gtbi_v7_g1b_role_contract import (
    build_manifest as build_g1b_manifest,
)
from scripts.generate_gtbi_v7_g0_transition_manifest import (
    TASK_ORDER as G0_TASK_ORDER,
    build_manifest as build_g0_manifest,
)


def _manifest() -> dict:
    payload = {
        "schema_version": "gtbi_v7_readiness_transition_manifest_v1",
        "manifest_id": "g0-close-1",
        "transaction_id": "G0_CLOSE-1",
        "requested_at_utc": "2026-07-30T12:00:00Z",
        "actor_id": "github-user:271768688",
        "actor_role": "repository_owner",
        "expected_base_ref": "refs/heads/main",
        "expected_base_sha_mode": "runtime_default_branch_head",
        "task_actions": [
            {
                "task_id": "PREV7-0001",
                "target_status": "done",
                "evidence_paths": [
                    "docs/readiness/gtbi-v7/owner_decisions.json"
                ],
                "evidence_sha256": ["sha256:" + ("1" * 64)],
                "terminal_reason": "owner_decision_recorded",
                "notes": "Owner-controlled task.",
                "files_touched": [
                    "docs/readiness/gtbi-v7/owner_decisions.json"
                ],
                "expected_result": "owner_decision_complete",
                "alternative_completion_receipt_set_digest_or_null": None,
            }
        ],
        "branch_actions": [],
        "gate_actions": [],
        "owner_directive_digest": "sha256:" + ("2" * 64),
        "manifest_digest": "",
    }
    payload["manifest_digest"] = domain_digest(
        "GTBI_V7_READINESS_TRANSITION_MANIFEST_V1",
        payload,
        omit_top_level_fields=("manifest_digest",),
    )
    return payload


def _redigest(payload: dict) -> dict:
    payload["manifest_digest"] = domain_digest(
        "GTBI_V7_READINESS_TRANSITION_MANIFEST_V1",
        payload,
        omit_top_level_fields=("manifest_digest",),
    )
    return payload


def test_transition_manifest_accepts_exact_owner_controlled_contract() -> None:
    validate_transition_manifest(_manifest())


def test_transition_manifest_rejects_digest_mismatch() -> None:
    payload = _manifest()
    payload["task_actions"][0]["notes"] = "mutated"
    with pytest.raises(StateControllerError, match="digest mismatch"):
        validate_transition_manifest(payload)


@pytest.mark.parametrize(
    "manifest_id",
    ("../g0-close-1", r"..\g0-close-1", "/g0-close-1", "G0-close-1"),
)
def test_loader_rejects_non_closed_manifest_identifiers(
    tmp_path: Path,
    manifest_id: str,
) -> None:
    with pytest.raises(StateControllerError, match="invalid manifest id"):
        load_transition_manifest(tmp_path, manifest_id)


@pytest.mark.parametrize(
    "path",
    (
        "../outside.json",
        r"docs\readiness\gtbi-v7\evidence.json",
        "/docs/readiness/gtbi-v7/evidence.json",
        "docs/readiness/other/evidence.json",
    ),
)
def test_transition_manifest_rejects_arbitrary_evidence_paths(path: str) -> None:
    payload = copy.deepcopy(_manifest())
    payload["task_actions"][0]["evidence_paths"] = [path]
    _redigest(payload)
    with pytest.raises(StateControllerError, match="evidence path"):
        validate_transition_manifest(payload)


def test_transition_manifest_rejects_non_owner_actor_role() -> None:
    payload = _manifest()
    payload["actor_role"] = "reviewer"
    _redigest(payload)
    with pytest.raises(StateControllerError, match="owner-controlled"):
        validate_transition_manifest(payload)


def test_transition_manifest_rejects_unexpected_fields() -> None:
    payload = _manifest()
    payload["command"] = "arbitrary shell"
    _redigest(payload)
    with pytest.raises(StateControllerError, match="field set mismatch"):
        validate_transition_manifest(payload)


def test_loader_accepts_only_canonical_reviewed_file(tmp_path: Path) -> None:
    payload = _manifest()
    manifest_dir = (
        tmp_path / "docs/readiness/gtbi-v7/transition_manifests"
    )
    manifest_dir.mkdir(parents=True)
    path = manifest_dir / "g0-close-1.json"
    path.write_bytes(canonical_bytes(payload) + b"\n")
    assert load_transition_manifest(tmp_path, "g0-close-1") == payload

    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with pytest.raises(StateControllerError, match="not canonical"):
        load_transition_manifest(tmp_path, "g0-close-1")


def _repository_fixture(tmp_path: Path) -> Path:
    source = Path(__file__).resolve().parents[1]
    destination = tmp_path / "repository"
    shutil.copytree(
        source / "docs/plans",
        destination / "docs/plans",
    )
    shutil.copytree(
        source / "docs/readiness/gtbi-v7",
        destination / "docs/readiness/gtbi-v7",
    )
    role_registry = (
        "config/gtbi/fixtures/v7/governance/"
        "role_registry_v1.owner_controlled.json"
    )
    (destination / role_registry).parent.mkdir(parents=True)
    shutil.copyfile(source / role_registry, destination / role_registry)
    write_initial_records(destination)
    write_formal_genesis_records(destination)
    return destination


def _current_repository_fixture(tmp_path: Path) -> Path:
    source = Path(__file__).resolve().parents[1]
    destination = tmp_path / "repository"
    shutil.copytree(
        source / "docs/plans",
        destination / "docs/plans",
    )
    shutil.copytree(
        source / "docs/readiness/gtbi-v7",
        destination / "docs/readiness/gtbi-v7",
    )
    return destination


def test_projection_closes_task_and_preserves_closed_write_scope(
    tmp_path: Path,
) -> None:
    repository = _repository_fixture(tmp_path)
    evidence = (
        repository
        / "docs/readiness/gtbi-v7/inventory_github_actions_attempt_receipt.json"
    )
    payload = _manifest()
    payload["task_actions"][0].update(
        {
            "evidence_paths": [
                "docs/readiness/gtbi-v7/"
                "inventory_github_actions_attempt_receipt.json"
            ],
            "evidence_sha256": [raw_sha256(evidence)],
        }
    )
    _redigest(payload)

    projection = build_transition_projection(
        repository,
        payload,
        base_sha="a" * 40,
    )
    task = next(
        row
        for row in projection.records["task_status.csv"]
        if row["id"] == "PREV7-0001"
    )
    assert task["status"] == "done"
    assert task["planning_state"] == "complete"
    assert projection.receipt["scientific_work_performed"] is False
    assert projection.receipt["locked_data_accessed"] is False

    written = write_transition_projection(repository, projection)
    assert {path.name for path in written} == set(MUTABLE_FILENAMES)
    for relative, expected in projection.receipt["output_sha256"].items():
        assert raw_sha256(repository / relative) == expected
    assert "PREV7-0001" in validate_current_readiness_records(
        repository
    )["terminal_task_ids"]

    before = {
        path.name: path.read_bytes()
        for path in written
    }
    write_formal_genesis_records(repository)
    assert {
        path.name: path.read_bytes()
        for path in written
    } == before


def test_projection_rejects_task_with_open_dependency(tmp_path: Path) -> None:
    repository = _repository_fixture(tmp_path)
    evidence = (
        repository
        / "docs/readiness/gtbi-v7/inventory_github_actions_attempt_receipt.json"
    )
    payload = _manifest()
    payload["task_actions"][0].update(
        {
            "task_id": "PREV7-0002",
            "evidence_paths": [
                "docs/readiness/gtbi-v7/"
                "inventory_github_actions_attempt_receipt.json"
            ],
            "evidence_sha256": [raw_sha256(evidence)],
        }
    )
    _redigest(payload)
    with pytest.raises(StateControllerError, match="dependencies"):
        build_transition_projection(
            repository,
            payload,
            base_sha="a" * 40,
        )


def test_current_projection_validator_rejects_status_drift(
    tmp_path: Path,
) -> None:
    repository = _repository_fixture(tmp_path)
    status_path = repository / "docs/readiness/gtbi-v7/task_status.csv"
    text = status_path.read_text(encoding="utf-8")
    status_path.write_text(
        text.replace("PREV7-0001,,1,1,", "PREV7-0001,,1,2,", 1),
        encoding="utf-8",
        newline="",
    )
    with pytest.raises(
        ReadinessValidationError,
        match="task version projection mismatch",
    ):
        validate_current_readiness_records(repository)


def test_checked_in_smoke_manifest_is_exact_and_dry_run_safe() -> None:
    root = Path(__file__).resolve().parents[1]
    expected = build_smoke_manifest()
    path = (
        root
        / "docs/readiness/gtbi-v7/transition_manifests/"
        "state-controller-smoke-v1.json"
    )
    assert path.read_bytes() == canonical_bytes(expected) + b"\n"
    assert expected["gate_actions"] == []
    assert expected["branch_actions"] == []
    validate_transition_manifest(expected)


def test_state_controller_workflow_has_closed_github_only_scope() -> None:
    root = Path(__file__).resolve().parents[1]
    text = (
        root
        / ".github/workflows/gtbi-v7-readiness-state-controller.yml"
    ).read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    assert "runs-on: ubuntu-24.04" in text
    assert "self-hosted" not in text
    assert "C:\\" not in text
    assert "scripts/global_technical_buy_indicator.py" not in text
    assert "locked_start" not in text.lower()
    assert "qf_oos" not in text.lower()
    assert "open_locked" not in text.lower()
    assert "permissions:\n  contents: write" in text
    assert "${{ github.sha }}" not in text
    assert "git rev-parse HEAD" in text


def test_state_controller_schemas_are_canonical_and_validate_outputs(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[1]
    schemas = schema_documents()
    for filename, schema in schemas.items():
        path = root / "config/gtbi/schemas/readiness" / filename
        assert path.read_bytes() == canonical_bytes(schema) + b"\n"
        jsonschema.Draft202012Validator.check_schema(schema)

    repository = _repository_fixture(tmp_path)
    manifest = build_smoke_manifest()
    projection = build_transition_projection(
        repository,
        manifest,
        base_sha="a" * 40,
    )
    jsonschema.validate(
        manifest,
        schemas[
            "gtbi_v7_readiness_transition_manifest_v1.schema.json"
        ],
    )
    jsonschema.validate(
        projection.receipt,
        schemas["gtbi_v7_state_controller_receipt_v1.schema.json"],
    )


def test_state_controller_public_contract_is_exact() -> None:
    root = Path(__file__).resolve().parents[1]
    expected = build_controller_contract()
    path = (
        root
        / "docs/readiness/gtbi-v7/state_controller_manifest.json"
    )
    assert path.read_bytes() == canonical_bytes(expected) + b"\n"
    assert expected["security_properties"] == {
        "arbitrary_command_execution_supported": False,
        "arbitrary_evidence_paths_supported": False,
        "external_auditor_required": False,
        "external_custodian_required": False,
        "locked_data_accessed": False,
        "owner_controlled": True,
        "scientific_work_performed": False,
        "self_hosted_runner_used": False,
        "windows_local_path_used": False,
    }


def test_state_controller_github_smoke_receipt_is_exact() -> None:
    root = Path(__file__).resolve().parents[1]
    expected = build_recovery_receipt()
    path = (
        root
        / "docs/readiness/gtbi-v7/state_controller_recovery_receipt.json"
    )
    assert path.read_bytes() == canonical_bytes(expected) + b"\n"
    assert expected["run_conclusion"] == "success"
    assert expected["run_id"] == 30556296057
    assert expected["verified_properties"] == {
        "arbitrary_command_execution_supported": False,
        "base_sha_matches_default_branch": True,
        "locked_data_accessed": False,
        "repository_state_mutated": False,
        "scientific_work_performed": False,
    }


def test_g0_apply_receipt_is_canonical_and_reconciled() -> None:
    root = Path(__file__).resolve().parents[1]
    source = json.loads(G0_APPLY_SOURCE.read_text(encoding="utf-8"))
    assert G0_APPLY_SOURCE.read_bytes() == canonical_bytes(source) + b"\n"
    assert source["receipt_digest"] == domain_digest(
        "GTBI_V7_STATE_CONTROLLER_RECEIPT_V1",
        source,
        omit_top_level_fields=("receipt_digest",),
    )

    validation = validate_g0_application()
    assert validation["append_only_g0_history_preserved"] is True
    assert isinstance(validation["exact_g0_projection"], bool)

    expected = build_g0_apply_receipt()
    destination = (
        root
        / "docs/readiness/gtbi-v7/"
        "g0_state_transition_reconciliation_receipt.json"
    )
    assert destination.read_bytes() == canonical_bytes(expected) + b"\n"
    assert expected["post_apply_state"]["counts"] == {
        "attempt_event_count": 50,
        "gate_count": 15,
        "gate_event_count": 16,
        "task_count": 110,
        "task_event_count": 159,
    }
    assert expected["post_apply_state"]["task_status_counts"] == {
        "blocked": 97,
        "cancelled": 1,
        "done": 12,
    }
    assert expected["verified_properties"] == {
        "append_only_g0_history_preserved": True,
        "arbitrary_command_execution_supported": False,
        "locked_data_accessed": False,
        "owner_controlled": True,
        "scientific_work_performed": False,
        "state_merged": True,
    }


def test_g1a_apply_receipt_is_canonical_and_reconciled() -> None:
    root = Path(__file__).resolve().parents[1]
    source = json.loads(G1A_APPLY_SOURCE.read_text(encoding="utf-8"))
    assert G1A_APPLY_SOURCE.read_bytes() == canonical_bytes(source) + b"\n"
    assert source["receipt_digest"] == domain_digest(
        "GTBI_V7_STATE_CONTROLLER_RECEIPT_V1",
        source,
        omit_top_level_fields=("receipt_digest",),
    )

    validation = validate_g1a_application()
    assert validation["append_only_g1a_history_preserved"] is True
    assert isinstance(validation["exact_g1a_projection"], bool)

    expected = build_g1a_apply_receipt()
    destination = (
        root
        / "docs/readiness/gtbi-v7/"
        "g1a_state_transition_reconciliation_receipt.json"
    )
    assert destination.read_bytes() == canonical_bytes(expected) + b"\n"
    assert expected["post_apply_state"]["counts"] == {
        "attempt_event_count": 62,
        "gate_count": 15,
        "gate_event_count": 17,
        "task_count": 110,
        "task_event_count": 171,
    }
    assert expected["post_apply_state"]["task_status_counts"] == {
        "blocked": 94,
        "cancelled": 1,
        "done": 15,
    }
    assert expected["verified_properties"] == {
        "append_only_g1a_history_preserved": True,
        "arbitrary_command_execution_supported": False,
        "locked_data_accessed": False,
        "owner_controlled": True,
        "scientific_work_performed": False,
        "state_merged": True,
    }


def test_g1b_transition_projects_only_role_task_and_gate(
    tmp_path: Path,
) -> None:
    repository = _current_repository_fixture(tmp_path)
    projection = build_transition_projection(
        repository,
        build_g1b_manifest(),
        base_sha="c" * 40,
    )
    statuses = {
        row["id"]: row["status"]
        for row in projection.records["task_status.csv"]
    }
    assert statuses["PREV7-0201"] == "done"
    assert statuses["PREV7-0202"] == "blocked"
    gate = next(
        row
        for row in projection.records["gate_status.csv"]
        if row["gate_id"] == "G1B"
    )
    assert gate["status"] == "green"
    write_transition_projection(repository, projection)
    validated = validate_current_readiness_records(repository)
    assert "PREV7-0201" in validated["terminal_task_ids"]
    assert "PREV7-0202" not in validated["terminal_task_ids"]


def test_g0_transition_manifest_is_exact_and_dependency_ordered() -> None:
    root = Path(__file__).resolve().parents[1]
    expected = build_g0_manifest()
    path = (
        root
        / "docs/readiness/gtbi-v7/transition_manifests/"
        "g0-owner-close-v1.json"
    )
    assert path.read_bytes() == canonical_bytes(expected) + b"\n"
    assert tuple(
        action["task_id"] for action in expected["task_actions"]
    ) == G0_TASK_ORDER
    assert expected["task_actions"][-1]["task_id"] == "PREV7-0011"
    assert expected["task_actions"][-1]["target_status"] == "cancelled"
    assert expected["task_actions"][-1][
        "alternative_completion_receipt_set_digest_or_null"
    ].startswith("sha256:")
    assert expected["gate_actions"] == [
        {
            "gate_id": "G0",
            "target_status": "green",
            "selected_branch_id_or_null": "G0_BOOTSTRAP_DISPOSITION",
            "inventory_snapshot_digest": (
                "sha256:"
                "3a93d655520be90818b81df0179cdbde35ca82aea4229292806619758ed300be"
            ),
            "evidence_bundle_digest": expected["gate_actions"][0][
                "evidence_bundle_digest"
            ],
        }
    ]
    validate_transition_manifest(expected)


def test_g0_transition_projects_all_tasks_branches_and_gate(
    tmp_path: Path,
) -> None:
    repository = _repository_fixture(tmp_path)
    projection = build_transition_projection(
        repository,
        build_g0_manifest(),
        base_sha="b" * 40,
    )
    statuses = {
        row["id"]: row["status"]
        for row in projection.records["task_status.csv"]
    }
    assert all(
        statuses[task_id] == (
            "cancelled" if task_id == "PREV7-0011" else "done"
        )
        for task_id in G0_TASK_ORDER
    )
    gate = next(
        row
        for row in projection.records["gate_status.csv"]
        if row["gate_id"] == "G0"
    )
    assert gate["status"] == "green"
    branches = {
        row["branch_id"]: row["selected_successor"]
        for row in projection.records["conditional_branch_registry.csv"]
        if row["branch_id"]
        in {
            "V6_FINAL_SOURCE",
            "EMERGENCY_ESCROW",
            "G0_BOOTSTRAP_DISPOSITION",
        }
    }
    assert branches == {
        "V6_FINAL_SOURCE": "remote_original_preserved",
        "EMERGENCY_ESCROW": "normal_preservation_complete",
        "G0_BOOTSTRAP_DISPOSITION": (
            "g0_ready_alternative_completion"
        ),
    }
    write_transition_projection(repository, projection)
    validated = validate_current_readiness_records(repository)
    assert set(G0_TASK_ORDER).issubset(validated["terminal_task_ids"])
    formal = validate_formal_genesis_records(repository)
    assert formal["completed_task_ids"] == ["PREV7-0000"]
