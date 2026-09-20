from __future__ import annotations

import hashlib
import inspect
import json
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_profile import (
    CHECKPOINT_RECOVERY_CONFIG_RELATIVE_PATH,
    CheckpointRecoveryProfileV1,
    canonical_cached_strategy_ids_sha256,
    load_checkpoint_recovery_profile,
    validate_exact_checkpoint_profile,
)


CAMPAIGN_KEY = "sp500-optimized-catalog-v1"
CONFIG_RELATIVE_PATH = Path(CHECKPOINT_RECOVERY_CONFIG_RELATIVE_PATH)
SOURCE_REQUEST_SHA256 = (
    "db7838f228058a301bb369a02e7133096cc48846cf0be8d6dac79372152ba2e1"
)
SOURCE_PROTECTED_COMMIT_SHA = "d12a374ab84bfb4e79bd5039343ffd5bd963c115"
SCIENCE_SHA256 = "f0e8c6db17a915f7c5f1dfec7d49ce5a69375c7252c23b49d82283120266419f"
EXECUTION_PLAN_SHA256 = "d2bce38b7382cc9dbcb3327337b68ef037813bb2310fe3157016b443070da9b9"
SOURCE_PLAN_RECEIPT_SHA256 = (
    "6f7707ae33b710a0114d67c9b5bb12f204a08003c273332415341c978d08e889"
)


def _bindings() -> dict[str, str]:
    return {
        "request_sha256": SOURCE_REQUEST_SHA256,
        "decision_sha256": "1" * 64,
        "protected_commit_sha": SOURCE_PROTECTED_COMMIT_SHA,
        "authority_id": "00000000-0000-4000-8000-000000000007",
        "campaign_id": "2" * 64,
        "science_sha256": SCIENCE_SHA256,
        "execution_plan_sha256": EXECUTION_PLAN_SHA256,
        "execution_protocol_sha256": "3" * 64,
    }


def _artifacts() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = [
        {
            "role": "plan",
            "artifact_id": 1,
            "artifact_name": "catalog-sealed-execution-plan-source7",
            "digest": "sha256:" + "a" * 64,
            "size_bytes": 101,
            "publisher_job_name": "gate",
            "publish_step_name": "Publish the already-materialized sealed plan",
        }
    ]
    for worker_id in range(30):
        for slot_index in range(1, 5):
            ordinal = worker_id * 4 + slot_index
            rows.append(
                {
                    "role": "checkpoint",
                    "artifact_id": ordinal + 1,
                    "artifact_name": f"catalog-checkpoint-worker-{worker_id:03d}-slot-{slot_index:02d}",
                    "digest": "sha256:" + f"{ordinal:064x}",
                    "size_bytes": 102 + ordinal,
                    "publisher_job_name": f"worker-{worker_id:03d}",
                    "publish_step_name": f"Publish checkpoint slot {slot_index}",
                    "worker_id": worker_id,
                    "slot_index": slot_index,
                }
            )
    assert len(rows) == 121
    return rows


def _payload() -> dict[str, object]:
    cached_ids = ("SCV1-alpha", "SCV1-beta", "SCV1-gamma")
    return {
        "schema_version": "1",
        "campaign_key": CAMPAIGN_KEY,
        "target_generation": 8,
        "source_generation": 7,
        "source_request_sha256": SOURCE_REQUEST_SHA256,
        "source_issue_number": 339,
        "source_run_id": 35504391586,
        "source_run_attempt": 1,
        "source_protected_commit_sha": SOURCE_PROTECTED_COMMIT_SHA,
        "source_plan_bindings": _bindings(),
        "source_plan_receipt_sha256": SOURCE_PLAN_RECEIPT_SHA256,
        "science_sha256": SCIENCE_SHA256,
        "catalog_manifest_sha256": "4" * 64,
        "worker_ids": list(range(30)),
        "expected_result_count": 18630,
        "expected_total_count": 37258,
        "cached_strategy_ids_sha256": canonical_cached_strategy_ids_sha256(cached_ids),
        "artifacts": _artifacts(),
    }


def _write_config(root: Path, payload: object | str) -> Path:
    path = root / CONFIG_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
    return path


def _root_with_profile(tmp_path: Path) -> Path:
    _write_config(tmp_path, {"schema_version": "1", "profiles": [_payload()]})
    return tmp_path


def test_valid_profile_is_closed_frozen_and_serializes_stably(tmp_path: Path) -> None:
    root = _root_with_profile(tmp_path)

    profile = load_checkpoint_recovery_profile(root, CAMPAIGN_KEY, 8)

    assert isinstance(profile, CheckpointRecoveryProfileV1)
    assert profile.source_generation == 7
    assert profile.source_issue_number == 339
    assert profile.source_run_id == 35504391586
    assert profile.source_run_attempt == 1
    assert profile.source_request_sha256 == SOURCE_REQUEST_SHA256
    assert profile.source_protected_commit_sha == SOURCE_PROTECTED_COMMIT_SHA
    assert len(profile.artifacts) == 121
    assert len(profile.worker_ids) == 30
    assert sum(item.role == "checkpoint" for item in profile.artifacts) == 120

    canonical = json.dumps(
        profile.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    assert profile.profile_sha256 == hashlib.sha256(canonical).hexdigest()
    assert profile.profile_sha256 == profile.profile_sha256
    with pytest.raises((TypeError, ValidationError)):
        profile.target_generation = 9


@pytest.mark.parametrize(
    ("campaign_key", "target_generation"),
    [("catalog-fast-canary-v1", 8), (CAMPAIGN_KEY, 7), (CAMPAIGN_KEY, 9)],
)
def test_non_target_campaigns_and_generations_return_none(
    tmp_path: Path, campaign_key: str, target_generation: int
) -> None:
    assert load_checkpoint_recovery_profile(tmp_path, campaign_key, target_generation) is None


@pytest.mark.parametrize(
    "mutation",
    ["source", "bindings", "commit", "science", "plan", "receipt", "worker", "slot"],
)
def test_incompatible_source_bindings_and_metadata_fail_closed(
    tmp_path: Path, mutation: str
) -> None:
    payload = _payload()
    if mutation == "source":
        payload["source_request_sha256"] = "5" * 64
    elif mutation == "bindings":
        payload["source_plan_bindings"] = {
            key: value for key, value in _bindings().items() if key != "execution_protocol_sha256"
        }
    elif mutation == "commit":
        payload["source_protected_commit_sha"] = "7" * 40
    elif mutation == "science":
        payload["science_sha256"] = "8" * 64
    elif mutation == "plan":
        payload["source_plan_bindings"] = {
            **_bindings(),
            "execution_plan_sha256": "9" * 64,
        }
    elif mutation == "receipt":
        payload["source_plan_receipt_sha256"] = "a" * 64
    elif mutation == "worker":
        payload["worker_ids"] = list(range(1, 31))
    else:
        payload["artifacts"] = _artifacts()[:-1]

    _write_config(tmp_path, {"schema_version": "1", "profiles": [payload]})
    with pytest.raises(ValueError, match="CATALOG_CHECKPOINT_RECOVERY_CONFIG_INVALID"):
        load_checkpoint_recovery_profile(tmp_path, CAMPAIGN_KEY, 8)


def test_duplicate_artifact_and_incomplete_worker_slot_sets_are_rejected(tmp_path: Path) -> None:
    payload = _payload()
    artifacts = _artifacts()
    artifacts[-1]["artifact_id"] = artifacts[-2]["artifact_id"]
    payload["artifacts"] = artifacts
    _write_config(tmp_path, {"schema_version": "1", "profiles": [payload]})
    with pytest.raises(ValueError, match="CATALOG_CHECKPOINT_RECOVERY_CONFIG_INVALID"):
        load_checkpoint_recovery_profile(tmp_path, CAMPAIGN_KEY, 8)

    payload = _payload()
    artifacts = _artifacts()
    artifacts[-1]["worker_id"] = 29
    artifacts[-1]["slot_index"] = 3
    payload["artifacts"] = artifacts
    _write_config(tmp_path, {"schema_version": "1", "profiles": [payload]})
    with pytest.raises(ValueError, match="CATALOG_CHECKPOINT_RECOVERY_CONFIG_INVALID"):
        load_checkpoint_recovery_profile(tmp_path, CAMPAIGN_KEY, 8)


def test_loader_rejects_duplicate_keys_nonfinite_and_wrong_root(tmp_path: Path) -> None:
    duplicate = '{"schema_version":"1","profiles":[],"profiles":[]}'
    _write_config(tmp_path, duplicate)
    with pytest.raises(ValueError, match="CATALOG_CHECKPOINT_RECOVERY_CONFIG_INVALID"):
        load_checkpoint_recovery_profile(tmp_path, CAMPAIGN_KEY, 8)

    _write_config(tmp_path, '{"schema_version":"1","profiles":[NaN]}')
    with pytest.raises(ValueError, match="CATALOG_CHECKPOINT_RECOVERY_CONFIG_INVALID"):
        load_checkpoint_recovery_profile(tmp_path, CAMPAIGN_KEY, 8)

    _write_config(tmp_path, {"schema_version": "1", "profiles": []})
    with pytest.raises(ValueError, match="CATALOG_CHECKPOINT_RECOVERY_CONFIG_INVALID"):
        load_checkpoint_recovery_profile(tmp_path, CAMPAIGN_KEY, 8)


def test_loader_rejects_symlinked_and_oversized_config(tmp_path: Path) -> None:
    target = tmp_path / "outside.json"
    target.write_text(
        json.dumps({"schema_version": "1", "profiles": [_payload()]}),
        encoding="utf-8",
    )
    config = tmp_path / CONFIG_RELATIVE_PATH
    config.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(target, config)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink unavailable: {exc}")
    with pytest.raises(ValueError, match="CATALOG_CHECKPOINT_RECOVERY_CONFIG_INVALID"):
        load_checkpoint_recovery_profile(tmp_path, CAMPAIGN_KEY, 8)

    oversized_root = tmp_path / "oversized"
    oversized = _payload()
    oversized["catalog_manifest_sha256"] = "b" * 64
    _write_config(
        oversized_root,
        '{"schema_version":"1","profiles":['
        + json.dumps(oversized)
        + ","
        + "null" * 0
        + "],"
        + '"padding":"'
        + "x" * (256 * 1024)
        + '"}',
    )
    with pytest.raises(ValueError, match="CATALOG_CHECKPOINT_RECOVERY_CONFIG_INVALID"):
        load_checkpoint_recovery_profile(oversized_root, CAMPAIGN_KEY, 8)


def test_exact_validation_requires_equality_with_protected_profile(tmp_path: Path) -> None:
    root = _root_with_profile(tmp_path)
    profile = load_checkpoint_recovery_profile(root, CAMPAIGN_KEY, 8)
    assert profile is not None
    assert validate_exact_checkpoint_profile(root, profile.model_dump(mode="json")) == profile

    changed = profile.model_dump(mode="json")
    changed["expected_total_count"] = 37257
    with pytest.raises(ValueError, match="CATALOG_CHECKPOINT_RECOVERY_PROFILE_MISMATCH"):
        validate_exact_checkpoint_profile(root, changed)


def test_model_module_is_controller_light_and_has_no_pyarrow_import() -> None:
    from aurora.infra.sp500_megarun import catalog_checkpoint_recovery_profile as module

    assert "pyarrow" not in inspect.getsource(module).lower()
