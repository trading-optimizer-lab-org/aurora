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
    write_formal_genesis_records,
)
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
