"""Deterministic production-shard pilot selection and verification."""

from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Any

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.atlas_execution_contract import AtlasRunPlanV1


def build_pilot_manifest(
    plan: AtlasRunPlanV1,
    *,
    shard_count: int = 60,
    seed: int = 20260818,
) -> dict[str, Any]:
    """Select evenly spread real production shards without looking at results."""

    if shard_count <= 0 or shard_count > plan.total_shards:
        raise ValueError("ATLAS_PILOT_COUNT_INVALID")
    if shard_count == 1:
        indices = [0]
    else:
        indices = sorted(
            {round(index * (plan.total_shards - 1) / (shard_count - 1)) for index in range(shard_count)}
        )
    if len(indices) != shard_count:
        raise ValueError("ATLAS_PILOT_SELECTION_COLLISION")
    identity: dict[str, Any] = {
        "schema_version": 1,
        "manifest_kind": "sp500_atlas_pilot",
        "plan_sha256": plan.plan_sha256,
        "selection_sha256": plan.selection_sha256,
        "seed": int(seed),
        "shard_indices": indices,
        "expected_recipe_count": sum(plan.shard(index).expected_recipe_count for index in indices),
        "validation_opened": False,
        "locked_opened": False,
    }
    return {**identity, "manifest_sha256": canonical_sha256(identity)}


def load_pilot_manifest(
    value: Mapping[str, Any] | str | bytes,
    *,
    plan: AtlasRunPlanV1 | None = None,
) -> dict[str, Any]:
    if isinstance(value, (str, bytes)):
        parsed = json.loads(value)
    else:
        parsed = dict(value)
    if not isinstance(parsed, dict) or parsed.get("manifest_kind") != "sp500_atlas_pilot":
        raise ValueError("ATLAS_PILOT_MANIFEST_INVALID")
    if parsed.get("validation_opened") is not False or parsed.get("locked_opened") is not False:
        raise ValueError("ATLAS_PILOT_BOUNDARY_OPEN")
    indices = parsed.get("shard_indices")
    if not isinstance(indices, list) or indices != sorted(set(int(value) for value in indices)):
        raise ValueError("ATLAS_PILOT_SELECTION_INVALID")
    if plan is not None:
        if parsed.get("plan_sha256") != plan.plan_sha256:
            raise ValueError("ATLAS_PILOT_PLAN_HASH_INVALID")
        if parsed.get("selection_sha256") != plan.selection_sha256:
            raise ValueError("ATLAS_PILOT_SELECTION_HASH_INVALID")
        if any(index < 0 or index >= plan.total_shards for index in indices):
            raise ValueError("ATLAS_PILOT_SELECTION_INVALID")
        expected = sum(plan.shard(index).expected_recipe_count for index in indices)
        if int(parsed.get("expected_recipe_count", -1)) != expected:
            raise ValueError("ATLAS_PILOT_RECIPE_COUNT_INVALID")
    supplied = parsed.get("manifest_sha256")
    identity = {key: value for key, value in parsed.items() if key != "manifest_sha256"}
    if supplied != canonical_sha256(identity):
        raise ValueError("ATLAS_PILOT_MANIFEST_HASH_INVALID")
    return parsed


__all__ = ["build_pilot_manifest", "load_pilot_manifest"]
