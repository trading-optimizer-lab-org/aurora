from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_profile import (
    CHECKPOINT_RECOVERY_CAMPAIGN_KEY,
    CHECKPOINT_RECOVERY_CONFIG_RELATIVE_PATH,
    CheckpointRecoveryProfileV1,
    CHECKPOINT_RECOVERY_SOURCE8_TERMINAL_RECEIPT_SHA256,
    load_checkpoint_recovery_profile,
    load_checkpoint_recovery_profiles,
    validate_exact_checkpoint_profile,
)


CAMPAIGN_KEY = CHECKPOINT_RECOVERY_CAMPAIGN_KEY
CONFIG_RELATIVE_PATH = Path(CHECKPOINT_RECOVERY_CONFIG_RELATIVE_PATH)
INHERITED_PROFILE_SHA256 = (
    "fc3aff1e9ccfc0e4608e510a538f8ce839c371669585b8b680a658e54d7e81b7"
)
GEN9_SOURCE_REQUEST_SHA256 = (
    "f337320f4ebb3c863581b632e18e15eeba364621363310ed31fc120677f84fe0"
)
GEN9_SOURCE_COMMIT_SHA = "9f22f9a1f7c6f2646f888c228a4899d0188f586c"
GEN9_EXECUTION_PLAN_SHA256 = (
    "c56fe177f2c7e24b3fcd42ed6182e52e5fc0e9465c5a45409ea3ebc2eb2c6cca"
)
GEN9_SOURCE_PLAN_RECEIPT_SHA256 = (
    "be0434a61abad0ff0d6eafe1a82d915d552c8e9ba8db96cf622b1afe65d1da0c"
)
GEN9_TERMINAL_RECEIPT_SHA256 = (
    "3e2ec6564b33f71be4bd89b5958ffd436f60ff193d082488e4307b7e8438a348"
)


def _write_config(root: Path, payload: object) -> None:
    path = root / CONFIG_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def _gen9_artifacts() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = [
        {
            "role": "plan",
            "artifact_id": 9000,
            "artifact_name": "catalog-sealed-execution-plan-source8",
            "digest": "sha256:" + "a" * 64,
            "size_bytes": 101,
            "publisher_job_name": "gate",
            "publish_step_name": "Publish the already-materialized sealed plan",
        }
    ]
    for worker_id in range(60):
        for slot_index in range(1, 3):
            ordinal = worker_id * 2 + slot_index
            rows.append(
                {
                    "role": "checkpoint",
                    "artifact_id": 9000 + ordinal,
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


def _gen9_payload(repo_root: Path) -> dict[str, object]:
    inherited = load_checkpoint_recovery_profile(repo_root, CAMPAIGN_KEY, 8)
    assert inherited is not None
    payload = inherited.model_dump(mode="json")
    payload.update(
        {
            "target_generation": 9,
            "source_generation": 8,
            "source_issue_number": 353,
            "source_run_id": 35708742966,
            "source_run_attempt": 1,
            "source_request_sha256": GEN9_SOURCE_REQUEST_SHA256,
            "source_protected_commit_sha": GEN9_SOURCE_COMMIT_SHA,
            "source_plan_receipt_sha256": GEN9_SOURCE_PLAN_RECEIPT_SHA256,
            "worker_ids": list(range(60)),
            "expected_result_count": 37258,
            "expected_total_count": 37258,
            "inherited_profile_sha256": INHERITED_PROFILE_SHA256,
            "artifacts": _gen9_artifacts(),
        }
    )
    payload["source_plan_bindings"] = {
        **payload["source_plan_bindings"],
        "request_sha256": GEN9_SOURCE_REQUEST_SHA256,
        "protected_commit_sha": GEN9_SOURCE_COMMIT_SHA,
        "execution_plan_sha256": GEN9_EXECUTION_PLAN_SHA256,
    }
    return payload


def test_protected_profile8_dump_and_hash_remain_unchanged() -> None:
    repo_root = Path(__file__).parents[1]
    profile = load_checkpoint_recovery_profile(repo_root, CAMPAIGN_KEY, 8)

    assert profile is not None
    assert profile.profile_sha256 == INHERITED_PROFILE_SHA256
    dumped = profile.model_dump(mode="json")
    dumped_json = json.loads(profile.model_dump_json())
    assert dumped_json == dumped
    assert "inherited_profile_sha256" not in dumped
    assert "source_terminal_receipt_sha256" not in dumped

    canonical = json.dumps(
        dumped,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    assert hashlib.sha256(canonical).hexdigest() == INHERITED_PROFILE_SHA256


def test_profile9_is_closed_source8_60_by_2_and_selectable_alongside_profile8(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).parents[1]
    inherited = load_checkpoint_recovery_profile(repo_root, CAMPAIGN_KEY, 8)
    assert inherited is not None
    _write_config(
        tmp_path,
        {
            "schema_version": "1",
            "profiles": [inherited.model_dump(mode="json"), _gen9_payload(repo_root)],
        },
    )

    profile8 = load_checkpoint_recovery_profile(tmp_path, CAMPAIGN_KEY, 8)
    profile9 = load_checkpoint_recovery_profile(tmp_path, CAMPAIGN_KEY, 9)

    assert profile8 is not None
    assert profile9 is not None
    assert profile8.profile_sha256 == INHERITED_PROFILE_SHA256
    assert profile8.total_checkpoint_count == 120
    assert profile9.target_generation == 9
    assert profile9.source_generation == 8
    assert profile9.source_request_sha256 == GEN9_SOURCE_REQUEST_SHA256
    assert profile9.source_issue_number == 353
    assert profile9.source_run_id == 35708742966
    assert profile9.source_run_attempt == 1
    assert profile9.source_protected_commit_sha == GEN9_SOURCE_COMMIT_SHA
    assert profile9.source_plan_receipt_sha256 == GEN9_SOURCE_PLAN_RECEIPT_SHA256
    assert profile9.inherited_profile_sha256 == INHERITED_PROFILE_SHA256
    assert profile9.source_terminal_receipt_sha256 == CHECKPOINT_RECOVERY_SOURCE8_TERMINAL_RECEIPT_SHA256
    assert profile9.worker_count == 60
    assert profile9.slot_count == 2
    assert profile9.checkpoint_result_count == 18628
    assert profile9.total_checkpoint_count == 240
    assert len(profile9.artifacts) == 121
    assert sum(item.role == "checkpoint" for item in profile9.artifacts) == 120
    assert validate_exact_checkpoint_profile(tmp_path, profile8) == profile8
    assert validate_exact_checkpoint_profile(tmp_path, profile9) == profile9


@pytest.mark.parametrize(
    "mutation",
    [
        "request",
        "commit",
        "plan",
        "receipt",
        "inherited",
        "count",
        "worker",
        "slot",
    ],
)
def test_profile9_mutations_fail_closed(tmp_path: Path, mutation: str) -> None:
    repo_root = Path(__file__).parents[1]
    inherited = load_checkpoint_recovery_profile(repo_root, CAMPAIGN_KEY, 8)
    assert inherited is not None
    payload = _gen9_payload(repo_root)
    if mutation == "request":
        payload["source_request_sha256"] = "1" * 64
    elif mutation == "commit":
        payload["source_protected_commit_sha"] = "2" * 40
    elif mutation == "plan":
        bindings = payload["source_plan_bindings"]
        assert isinstance(bindings, dict)
        payload["source_plan_bindings"] = {
            **bindings,
            "execution_plan_sha256": "3" * 64,
        }
    elif mutation == "receipt":
        payload["source_plan_receipt_sha256"] = "4" * 64
    elif mutation == "inherited":
        payload["inherited_profile_sha256"] = "6" * 64
    elif mutation == "count":
        payload["expected_result_count"] = 37257
    elif mutation == "worker":
        payload["worker_ids"] = list(range(1, 61))
    else:
        raw_artifacts = payload["artifacts"]
        assert isinstance(raw_artifacts, list)
        artifacts = list(raw_artifacts)
        artifacts[-1] = {**artifacts[-1], "slot_index": 3}
        payload["artifacts"] = artifacts

    _write_config(
        tmp_path,
        {"schema_version": "1", "profiles": [inherited.model_dump(mode="json"), payload]},
    )
    with pytest.raises(ValueError, match="CATALOG_CHECKPOINT_RECOVERY_CONFIG_INVALID"):
        load_checkpoint_recovery_profiles(tmp_path)


def test_profile9_terminal_receipt_is_derived_and_not_serialized(tmp_path: Path) -> None:
    repo_root = Path(__file__).parents[1]
    payload = _gen9_payload(repo_root)
    _write_config(tmp_path, {"schema_version": "1", "profiles": [payload]})

    profile = load_checkpoint_recovery_profile(tmp_path, CAMPAIGN_KEY, 9)
    assert profile is not None
    assert profile.source_terminal_receipt_sha256 == GEN9_TERMINAL_RECEIPT_SHA256
    assert "source_terminal_receipt_sha256" not in profile.model_dump(mode="json")
