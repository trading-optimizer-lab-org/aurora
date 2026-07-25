from __future__ import annotations

import importlib.resources
import json
import re
from pathlib import Path
from typing import Any, Mapping

import jsonschema
import pytest
import yaml
from pydantic import ValidationError

from aurora.infra.github_performance.contracts import (
    AttemptManifest,
    RunSpec,
    canonical_sha256,
)
from github_performance_helpers import minimal_valid_spec


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "config" / "schemas" / "github_run_spec_v3.schema.json"
TEMPLATE_PATH = ROOT / "config" / "templates" / "github_run_v3.yaml"
CAPACITY_PATH = ROOT / "config" / "github_capacity_profile.json"
ACTION_LOCK_PATH = ROOT / "config" / "official_actions_lock.json"


def load_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def load_template() -> dict[str, Any]:
    payload = yaml.safe_load(TEMPLATE_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def template_mapping_paths(
    value: Mapping[str, Any],
    prefix: tuple[str, ...] = (),
) -> set[tuple[str, ...]]:
    paths: set[tuple[str, ...]] = set()
    for key, child in value.items():
        path = prefix + (key,)
        paths.add(path)
        if isinstance(child, Mapping):
            paths.update(template_mapping_paths(child, path))
    return paths


def schema_mapping_paths(
    schema: Mapping[str, Any],
    prefix: tuple[str, ...] = (),
) -> set[tuple[str, ...]]:
    paths: set[tuple[str, ...]] = set()
    for key, child in schema.get("properties", {}).items():
        path = prefix + (key,)
        paths.add(path)
        if child.get("type") == "object":
            paths.update(schema_mapping_paths(child, path))
    return paths


def test_master_template_validates_against_v3_schema() -> None:
    jsonschema.Draft202012Validator(load_schema()).validate(load_template())


def test_capacity_profile_matches_support_confirmation() -> None:
    profile = json.loads(CAPACITY_PATH.read_text(encoding="utf-8"))
    assert profile["standard_concurrency_ceiling"] == 360
    assert profile["matrix_job_ceiling"] == 256
    assert profile["runner_label"] == "ubuntu-24.04"
    assert profile["larger_runners_allowed"] is False


def test_schema_covers_every_master_template_key() -> None:
    assert schema_mapping_paths(load_schema()) == template_mapping_paths(load_template())


def test_all_fixed_objects_are_closed_and_require_every_property() -> None:
    def visit(node: Mapping[str, Any], path: tuple[str, ...] = ()) -> None:
        if node.get("type") == "object":
            properties = node.get("properties", {})
            assert node.get("additionalProperties") is False, path
            assert set(node.get("required", [])) == set(properties), path
            for key, child in properties.items():
                visit(child, path + (key,))

    visit(load_schema())


def test_official_actions_are_locked_to_full_commit_shas() -> None:
    lock = json.loads(ACTION_LOCK_PATH.read_text(encoding="utf-8"))
    assert set(lock) == {
        "actions/checkout",
        "actions/setup-python",
        "actions/cache",
        "actions/upload-artifact",
        "actions/download-artifact",
    }
    assert all(re.fullmatch(r"[0-9a-f]{40}", sha) for sha in lock.values())


def test_nested_contract_files_ship_inside_the_aurora_package() -> None:
    root = importlib.resources.files("aurora")
    schema = root.joinpath("config/schemas/github_run_spec_v3.schema.json")
    template = root.joinpath("config/templates/github_run_v3.yaml")
    assert schema.is_file()
    assert template.is_file()


def _manifest_payload(
    shard_id: str,
    attempt_id: str,
    state: str = "completed",
) -> dict[str, object]:
    return {
        "shard_id": shard_id,
        "attempt_id": attempt_id,
        "state": state,
        "spec_hash": "1" * 64,
        "policy_hash": "2" * 64,
        "snapshot_hash": "3" * 64,
        "code_sha": "4" * 40,
        "dependency_lock_sha256": "5" * 64,
        "capacity_profile_sha256": "6" * 64,
        "output_sha256": "7" * 64,
        "reason_code": None,
        "artifact_name": f"run-shard-g00-{shard_id}-{attempt_id}",
        "unit_attempts_path": "unit_attempts.parquet",
        "unit_attempts_sha256": "8" * 64,
        "checkpoint_artifact": None,
        "completed_unit_count": 1,
        "output_rows": 1,
        "output_bytes": 128,
    }


def test_contract_hash_ignores_mapping_order() -> None:
    assert canonical_sha256({"a": 1, "b": 2}) == canonical_sha256(
        {"b": 2, "a": 1}
    )


def test_run_spec_is_deeply_immutable() -> None:
    spec = RunSpec.model_validate(minimal_valid_spec())
    with pytest.raises(TypeError):
        spec.policy["locked_opened"] = True


def test_attempt_identity_is_physical_not_logical() -> None:
    first = AttemptManifest.model_validate(_manifest_payload("s1", "a1"))
    second = AttemptManifest.model_validate(_manifest_payload("s1", "a2"))
    assert first.shard_id == second.shard_id
    assert first.attempt_id != second.attempt_id


def test_terminal_state_is_closed_enum() -> None:
    with pytest.raises(ValidationError):
        AttemptManifest.model_validate(
            _manifest_payload("u", "a", state="skipped")
        )


def test_non_completed_attempt_requires_reason_code() -> None:
    payload = _manifest_payload("s1", "a1", state="failed_technical")
    payload["output_sha256"] = None
    payload["unit_attempts_path"] = None
    payload["unit_attempts_sha256"] = None
    with pytest.raises(ValidationError, match="reason_code"):
        AttemptManifest.model_validate(payload)
