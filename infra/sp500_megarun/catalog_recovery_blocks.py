"""Content identities carried by the existing sealed checkpoint policy.

The caller must verify the policy's protected provenance. These checks bind
content and assignments; a self-hash alone does not authorize an execution.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from pathlib import Path
from typing import Any

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.github_performance.shard_planner import sha256_file


def _digest(value: object) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        char not in "0123456789abcdef" for char in value
    ):
        raise ValueError("RECOVERY_BLOCK_IDENTITY_INVALID")
    return value


def _strategy_hash(strategy_ids: Sequence[str]) -> str:
    ids = tuple(strategy_ids)
    if not ids or any(not isinstance(item, str) or not item for item in ids):
        raise ValueError("RECOVERY_BLOCK_STRATEGIES_INVALID")
    if ids != tuple(sorted(set(ids))):
        raise ValueError("RECOVERY_BLOCK_STRATEGIES_INVALID")
    return canonical_sha256({"schema_version": "1", "strategy_ids": ids})


def build_recovery_blocks(
    *, science_sha256: str, runtime_identity_sha256: str,
    prepared_input_identity_sha256: str,
    assignments: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    context = {
        "science_sha256": _digest(science_sha256),
        "runtime_identity_sha256": _digest(runtime_identity_sha256),
        "prepared_input_identity_sha256": _digest(prepared_input_identity_sha256),
    }
    blocks = []
    seen_ids: set[str] = set()
    seen_workers: set[int] = set()
    for assignment in assignments:
        worker = assignment["worker_id"]
        count = assignment["checkpoint_slot_count"]
        ids = tuple(assignment["strategy_ids"])
        _strategy_hash(ids)
        if (type(worker) is not int or worker < 0 or worker in seen_workers
                or type(count) is not int or count not in (1, 2, 4, 8)
                or len(ids) < count or seen_ids.intersection(ids)):
            raise ValueError("RECOVERY_BLOCK_ASSIGNMENT_INVALID")
        seen_workers.add(worker)
        seen_ids.update(ids)
        for slot in range(1, count + 1):
            subset = ids[len(ids) * (slot - 1) // count:len(ids) * slot // count]
            strategy_hash = _strategy_hash(subset)
            identity = {"schema_version": "1", **context,
                        "strategy_manifest_sha256": strategy_hash}
            blocks.append({"worker_id": worker, "slot_index": slot,
                           "strategy_count": len(subset),
                           "strategy_manifest_sha256": strategy_hash,
                           "block_id": canonical_sha256(identity)})
    return {"schema_version": "1", **context, "blocks": blocks}


def resolve_recovery_block(
    policy: Mapping[str, Any], *, science_sha256: str,
    worker_id: int, slot_index: int, strategy_ids: Sequence[str],
) -> str:
    """Resolve an exact assignment, never a worker/slot used as an identity."""
    identity = {key: value for key, value in policy.items() if key != "content_sha256"}
    if (policy.get("schema_version") != "1"
            or policy.get("document_type") != "checkpoint_policy"
            or policy.get("science_sha256") != science_sha256
            or canonical_sha256(identity) != policy.get("content_sha256")):
        raise ValueError("RECOVERY_BLOCK_POLICY_INVALID")
    plan = policy.get("recovery_blocks_v1")
    context_fields = {"science_sha256", "runtime_identity_sha256",
                      "prepared_input_identity_sha256"}
    if (not isinstance(plan, dict)
            or set(plan) != context_fields | {"schema_version", "blocks"}
            or plan.get("schema_version") != "1"
            or plan.get("science_sha256") != science_sha256
            or not isinstance(plan.get("blocks"), list)):
        raise ValueError("RECOVERY_BLOCK_PLAN_INVALID")
    context = {key: _digest(plan[key]) for key in context_fields}
    selected = None
    routes: set[tuple[int, int]] = set()
    block_ids: set[str] = set()
    for row in plan["blocks"]:
        if not isinstance(row, dict) or set(row) != {
            "worker_id", "slot_index", "strategy_count", "strategy_manifest_sha256", "block_id"
        }:
            raise ValueError("RECOVERY_BLOCK_PLAN_INVALID")
        worker, slot, count = row["worker_id"], row["slot_index"], row["strategy_count"]
        if (type(worker) is not int or worker < 0 or type(slot) is not int
                or not 1 <= slot <= 8 or type(count) is not int or count < 1):
            raise ValueError("RECOVERY_BLOCK_PLAN_INVALID")
        route = (worker, slot)
        expected_id = canonical_sha256({"schema_version": "1", **context,
            "strategy_manifest_sha256": _digest(row["strategy_manifest_sha256"])})
        if (route in routes or row["block_id"] != expected_id
                or expected_id in block_ids):
            raise ValueError("RECOVERY_BLOCK_PLAN_INVALID")
        routes.add(route)
        block_ids.add(expected_id)
        if route == (worker_id, slot_index):
            selected = row
    if (selected is None or selected["strategy_count"] != len(strategy_ids)
            or selected["strategy_manifest_sha256"] != _strategy_hash(strategy_ids)):
        raise ValueError("RECOVERY_BLOCK_ASSIGNMENT_INVALID")
    return str(selected["block_id"])


def verify_persisted_recovery_block(
    root: Path, *, policy: Mapping[str, Any], science_sha256: str,
    worker_id: int, slot_index: int,
) -> str:
    """Check downloaded bytes before declaring a checkpoint reusable.

    The action verifies artifact provenance and the contiguous prefix separately.
    No evaluation, mutation, transport or retries are performed here.
    """
    import pyarrow.parquet as pq

    paths = {name: root / name for name in (
        "receipt.json", "shard_attempt_manifest.json",
        "checkpoint_chain_manifest.json", "results.parquet",
    )}
    if root.is_symlink() or any(not path.is_file() or path.is_symlink()
                                for path in paths.values()):
        raise ValueError("RECOVERY_BLOCK_RESULT_INVALID")
    documents: dict[str, dict[str, Any]] = {}
    for name in ("receipt.json", "shard_attempt_manifest.json", "checkpoint_chain_manifest.json"):
        path = paths[name]
        if path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("RECOVERY_BLOCK_RESULT_INVALID")
        try:
            document = json.loads(path.read_text("utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError("RECOVERY_BLOCK_RESULT_INVALID") from exc
        if not isinstance(document, dict):
            raise ValueError("RECOVERY_BLOCK_RESULT_INVALID")
        documents[name] = document
    receipt = documents["receipt.json"]
    attempt = documents["shard_attempt_manifest.json"]
    chain = documents["checkpoint_chain_manifest.json"]
    result_sha = sha256_file(paths["results.parquet"])
    receipt_sha = sha256_file(paths["receipt.json"])
    attempt_id = receipt.get("attempt_id")
    chain_identity = {key: value for key, value in chain.items() if key != "chain_sha256"}
    if (not isinstance(attempt_id, str) or not attempt_id.strip()
            or receipt.get("science_identity_sha256") != science_sha256
            or receipt.get("shard_index") != worker_id
            or receipt.get("checkpoint_slot_index") != slot_index
            or attempt.get("worker_id") != worker_id
            or attempt.get("checkpoint_slot_index") != slot_index
            or chain.get("worker_id") != worker_id or chain.get("slot_index") != slot_index
            or attempt.get("attempt_id") != attempt_id or chain.get("attempt_id") != attempt_id
            or receipt.get("result_sha256") != result_sha or attempt.get("result_sha256") != result_sha
            or attempt.get("receipt_sha256") != receipt_sha
            or chain.get("current_receipt_sha256") != receipt_sha
            or canonical_sha256(chain_identity) != chain.get("chain_sha256")
            or any(doc.get("validation_opened") is not False or doc.get("locked_opened") is not False
                   for doc in documents.values())):
        raise ValueError("RECOVERY_BLOCK_RESULT_INVALID")
    try:
        strategy_ids = pq.read_table(paths["results.parquet"], columns=["strategy_id"]).column(
            "strategy_id"
        ).to_pylist()
    except (OSError, ValueError) as exc:
        raise ValueError("RECOVERY_BLOCK_RESULT_INVALID") from exc
    if (receipt.get("strategy_count") != len(strategy_ids)
            or attempt.get("strategy_ids") != strategy_ids
            or chain.get("completed_strategy_ids") != strategy_ids):
        raise ValueError("RECOVERY_BLOCK_RESULT_INVALID")
    block_id = resolve_recovery_block(policy, science_sha256=science_sha256,
        worker_id=worker_id, slot_index=slot_index, strategy_ids=strategy_ids)
    if any(doc.get("recovery_block_id") != block_id for doc in documents.values()):
        raise ValueError("RECOVERY_BLOCK_RESULT_INVALID")
    return block_id


def recovery_metrics_from_checkpoints(
    manifests: Sequence[Mapping[str, Any]], *, authority_id: str,
) -> dict[str, Any] | None:
    """Derive recovery only from verified checkpoint records of this authority."""
    all_ids: set[str] = set()
    recovered: set[str] = set()
    unknown = not manifests
    for row in manifests:
        block = row.get("recovery_block_id")
        if block is None:
            unknown = True
            continue
        block_id = _digest(block)
        worker = row.get("worker_id")
        if not authority_id or type(worker) is not int or worker < 0 or block_id in all_ids:
            raise ValueError("RECOVERY_METRICS_CHECKPOINT_INVALID")
        attempts = tuple(f"{authority_id}:worker:{worker:03d}:attempt:{number}"
                         for number in (1, 2, 3))
        attempt = row.get("attempt_id")
        if attempt not in attempts:
            raise ValueError("RECOVERY_METRICS_ATTEMPT_INVALID")
        all_ids.add(block_id)
        if attempt != attempts[0]:
            recovered.add(block_id)
    if unknown:
        return None
    return {"schema_version": "1", "verified_block_ids": sorted(all_ids),
            "recovered_block_ids": sorted(recovered)}


def aggregate_recovery_metrics(
    receipts: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    """Combine already verified, disjoint producers; missing evidence stays null."""
    verified: set[str] = set()
    recovered: set[str] = set()
    unknown = not receipts
    for receipt in receipts:
        metrics = receipt.get("recovery_metrics")
        if metrics is None:
            unknown = True
            continue
        if (not isinstance(metrics, Mapping) or set(metrics) != {
                "schema_version", "verified_block_ids", "recovered_block_ids"}
                or metrics.get("schema_version") != "1"):
            raise ValueError("RECOVERY_METRICS_INVALID")
        groups = []
        for name in ("verified_block_ids", "recovered_block_ids"):
            ids = metrics[name]
            if not isinstance(ids, (list, tuple)):
                raise ValueError("RECOVERY_METRICS_INVALID")
            checked = [_digest(item) for item in ids]
            if checked != sorted(set(checked)):
                raise ValueError("RECOVERY_METRICS_INVALID")
            groups.append(set(checked))
        source_ids, source_recovered = groups
        if not source_recovered <= source_ids or verified.intersection(source_ids):
            raise ValueError("RECOVERY_METRICS_OVERLAP_INVALID")
        verified.update(source_ids)
        recovered.update(source_recovered)
    if unknown:
        return None
    return {"schema_version": "1", "verified_block_ids": sorted(verified),
            "recovered_block_ids": sorted(recovered)}
