from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.catalog_recovery_blocks import (
    build_recovery_blocks, resolve_recovery_block,
    recovery_metrics_from_checkpoints, aggregate_recovery_metrics,
)


def _policy(worker: int = 0) -> dict[str, Any]:
    document = {
        "schema_version": "1", "document_type": "checkpoint_policy",
        "science_sha256": "a" * 64,
        "recovery_blocks_v1": build_recovery_blocks(
            science_sha256="a" * 64, runtime_identity_sha256="b" * 64,
            prepared_input_identity_sha256="c" * 64,
            assignments=[{"worker_id": worker, "checkpoint_slot_count": 2,
                          "strategy_ids": ("strategy-0", "strategy-1")}],
        ),
    }
    document["content_sha256"] = canonical_sha256(document)
    return document


def _resolve(policy: dict[str, Any], worker: int = 0, ids: tuple[str, ...] = ("strategy-0",)) -> str:
    return resolve_recovery_block(policy, science_sha256="a" * 64,
        worker_id=worker, slot_index=1, strategy_ids=ids)


def test_block_identity_survives_worker_reassignment_but_not_preparation_change() -> None:
    first = _resolve(_policy())
    assert first == _resolve(_policy(7), worker=7)
    other = _policy()
    other["recovery_blocks_v1"] = build_recovery_blocks(
        science_sha256="a" * 64, runtime_identity_sha256="d" * 64,
        prepared_input_identity_sha256="c" * 64,
        assignments=[{"worker_id": 0, "checkpoint_slot_count": 2,
                      "strategy_ids": ("strategy-0", "strategy-1")}],
    )
    other.pop("content_sha256")
    other["content_sha256"] = canonical_sha256(other)
    assert first != _resolve(other)


@pytest.mark.parametrize("mutation", ["digest", "duplicate", "block_id", "science", "schema"])
def test_block_reader_rejects_invalid_policy(mutation: str) -> None:
    policy = deepcopy(_policy())
    plan = policy["recovery_blocks_v1"]
    if mutation == "duplicate":
        plan["blocks"].append(deepcopy(plan["blocks"][0]))
    elif mutation == "block_id":
        plan["blocks"][0]["block_id"] = "f" * 64
    elif mutation == "science":
        plan["science_sha256"] = "f" * 64
    elif mutation == "schema":
        plan["schema_version"] = "99"
    if mutation != "digest":
        policy.pop("content_sha256")
        policy["content_sha256"] = canonical_sha256(policy)
    else:
        policy["content_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="RECOVERY_BLOCK_"):
        _resolve(policy)


@pytest.mark.parametrize("ids", [("strategy-1",), (), ("strategy-0", "strategy-1")])
def test_block_reader_rejects_wrong_strategy_assignment(ids: tuple[str, ...]) -> None:
    with pytest.raises(ValueError, match="RECOVERY_BLOCK_ASSIGNMENT_INVALID"):
        _resolve(_policy(), ids=ids)


def test_recovery_ids_follow_verified_attempts_through_reduction() -> None:
    group = recovery_metrics_from_checkpoints([
        {"recovery_block_id": "a" * 64, "worker_id": 0, "attempt_id": "authority:worker:000:attempt:1"},
        {"recovery_block_id": "b" * 64, "worker_id": 0, "attempt_id": "authority:worker:000:attempt:2"},
    ], authority_id="authority")
    assert group == {"schema_version": "1", "verified_block_ids": ["a" * 64, "b" * 64],
                     "recovered_block_ids": ["b" * 64]}
    root = aggregate_recovery_metrics([{"recovery_metrics": group}])
    assert root == group
    assert aggregate_recovery_metrics([{"recovery_metrics": root}, {}]) is None
    with pytest.raises(ValueError, match="OVERLAP"):
        aggregate_recovery_metrics([{"recovery_metrics": group}, {"recovery_metrics": group}])


@pytest.mark.parametrize("attempt", ["other:worker:000:attempt:2", "authority:worker:001:attempt:2",
                                      "authority:worker:000:attempt:4", None])
def test_recovery_count_rejects_other_authority_worker_or_exhausted_attempt(attempt: str | None) -> None:
    with pytest.raises(ValueError, match="RECOVERY_METRICS_ATTEMPT_INVALID"):
        recovery_metrics_from_checkpoints([
            {"recovery_block_id": "b" * 64, "worker_id": 0, "attempt_id": attempt},
        ], authority_id="authority")
