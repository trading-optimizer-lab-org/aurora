"""Immutable planning contracts for a finite, static Atlas campaign.

The complete Atlas space is represented by ordinal ranges.  A run evaluates a
finite prefix of that space, split into contiguous, disjoint shard ranges.
This module contains no market-data loading and is safe to use in preflight.
"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Literal, Sequence

from pydantic import Field

from aurora.infra.github_performance.contracts import FrozenModel, Sha256, canonical_sha256


class AtlasShardPlanV1(FrozenModel):
    """One inclusive/exclusive ordinal interval assigned to one worker."""

    shard_index: int = Field(ge=0)
    start_ordinal: int = Field(ge=0)
    stop_ordinal: int = Field(gt=0)
    expected_recipe_count: int = Field(gt=0)
    shard_sha256: Sha256


class AtlasRunPlanV1(FrozenModel):
    """Hash-bound finite plan used by every worker and by the reducer."""

    schema_version: Literal["1"]
    mode: Literal["atlas_static"]
    catalog_id: str = Field(min_length=1)
    catalog_manifest_sha256: Sha256
    catalog_space_sha256: Sha256
    calibration_receipt_sha256: Sha256
    implementation_commit_sha: str = Field(min_length=7)
    train_end: Literal["2010-12-31"]
    target_end_iso: str = Field(min_length=1)
    target_available_minutes: float = Field(ge=0.0)
    safety_fraction: float = Field(ge=0.5, le=0.9)
    planning_rate_recipes_per_minute: float = Field(ge=0.0)
    requested_recipe_count: int = Field(gt=0)
    canonical_recipe_count: int = Field(gt=0)
    ordinal_start: int = Field(ge=0)
    ordinal_stop: int = Field(gt=0)
    total_shards: int = Field(gt=0)
    shards: tuple[AtlasShardPlanV1, ...]
    validation_opened: Literal[False]
    locked_opened: Literal[False]

    @property
    def plan_sha256(self) -> str:
        return canonical_sha256(self)

    def shard(self, shard_index: int) -> AtlasShardPlanV1:
        for shard in self.shards:
            if shard.shard_index == shard_index:
                return shard
        raise KeyError(f"ATLAS_SHARD_UNKNOWN:{shard_index}")

    def matrix_groups(self, group_count: int = 3) -> tuple[tuple[int, ...], ...]:
        """Return static groups that stay below GitHub's matrix-size limit."""

        if group_count <= 0:
            raise ValueError("ATLAS_MATRIX_GROUP_COUNT_INVALID")
        groups = [[] for _ in range(group_count)]
        for shard in self.shards:
            groups[shard.shard_index % group_count].append(shard.shard_index)
        return tuple(tuple(group) for group in groups)


def _parse_target(value: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("ATLAS_PLAN_TARGET_END_INVALID_ISO") from exc
    if parsed.tzinfo is None:
        raise ValueError("ATLAS_PLAN_TARGET_END_MISSING_TIMEZONE")


def _shard_payload(
    *,
    shard_index: int,
    start_ordinal: int,
    stop_ordinal: int,
    plan_identity: dict[str, object],
) -> dict[str, object]:
    payload = {
        **plan_identity,
        "shard_index": shard_index,
        "start_ordinal": start_ordinal,
        "stop_ordinal": stop_ordinal,
        "expected_recipe_count": stop_ordinal - start_ordinal,
    }
    return payload


def partition_ordinals(
    *,
    recipe_count: int,
    total_shards: int,
) -> tuple[tuple[int, int], ...]:
    """Split [0, recipe_count) into equal contiguous non-empty intervals."""

    if recipe_count <= 0:
        raise ValueError("ATLAS_PLAN_RECIPE_COUNT_INVALID")
    if total_shards <= 0 or total_shards > recipe_count:
        raise ValueError("ATLAS_PLAN_SHARD_COUNT_INVALID")
    base, remainder = divmod(recipe_count, total_shards)
    ranges: list[tuple[int, int]] = []
    cursor = 0
    for index in range(total_shards):
        stop = cursor + base + (1 if index < remainder else 0)
        ranges.append((cursor, stop))
        cursor = stop
    if cursor != recipe_count:
        raise AssertionError("ATLAS_PLAN_PARTITION_INTERNAL_ERROR")
    return tuple(ranges)


def build_run_plan(
    *,
    catalog_manifest: dict[str, object],
    calibration_receipt: dict[str, object],
    target_end_iso: str,
    implementation_commit_sha: str,
    total_shards: int,
    recipe_count: int | None = None,
) -> AtlasRunPlanV1:
    """Build and validate one exact finite plan from immutable evidence."""

    _parse_target(target_end_iso)
    if catalog_manifest.get("validation_opened") is not False or catalog_manifest.get(
        "locked_opened"
    ) is not False:
        raise ValueError("ATLAS_PLAN_CATALOG_BOUNDARY_OPEN")
    if catalog_manifest.get("execution_authorized") is not False:
        raise ValueError("ATLAS_PLAN_CATALOG_ALREADY_AUTHORIZED")
    if calibration_receipt.get("hard_limit_seconds") != 1200.0:
        raise ValueError("ATLAS_PLAN_CALIBRATION_LIMIT_INVALID")
    if calibration_receipt.get("validation_opened") is not False or calibration_receipt.get(
        "locked_opened"
    ) is not False:
        raise ValueError("ATLAS_PLAN_CALIBRATION_BOUNDARY_OPEN")

    canonical_count = int(catalog_manifest["counts"]["canonical_recipe_count"])
    selected_count = int(
        calibration_receipt["target_recipe_count_with_margin"]
        if recipe_count is None
        else recipe_count
    )
    if selected_count <= 0 or selected_count > canonical_count:
        raise ValueError("ATLAS_PLAN_RECIPE_COUNT_OUT_OF_RANGE")
    ranges = partition_ordinals(recipe_count=selected_count, total_shards=total_shards)
    identity = {
        "schema_version": "1",
        "mode": "atlas_static",
        "catalog_id": str(catalog_manifest["catalog_id"]),
        "catalog_manifest_sha256": str(catalog_manifest["manifest_sha256"]),
        "catalog_space_sha256": str(catalog_manifest["artifacts_sha256"]["recipe_space.json"]),
        "calibration_receipt_sha256": str(
            calibration_receipt.get("receipt_sha256")
            or canonical_sha256(
                {
                    key: value
                    for key, value in calibration_receipt.items()
                    if key != "receipt_sha256"
                }
            )
        ),
        "implementation_commit_sha": implementation_commit_sha,
        "train_end": "2010-12-31",
        "target_end_iso": target_end_iso,
        "target_available_minutes": float(
            calibration_receipt["available_minutes_to_target"]
        ),
        "safety_fraction": float(calibration_receipt["safety_fraction"]),
        "planning_rate_recipes_per_minute": float(
            calibration_receipt["recipes_per_minute"]
        ),
        "requested_recipe_count": selected_count,
        "canonical_recipe_count": canonical_count,
        "ordinal_start": 0,
        "ordinal_stop": selected_count,
        "total_shards": total_shards,
        "validation_opened": False,
        "locked_opened": False,
    }
    shards = tuple(
        AtlasShardPlanV1(
            shard_index=index,
            start_ordinal=start,
            stop_ordinal=stop,
            expected_recipe_count=stop - start,
            shard_sha256=canonical_sha256(
                _shard_payload(
                    shard_index=index,
                    start_ordinal=start,
                    stop_ordinal=stop,
                    plan_identity=identity,
                )
            ),
        )
        for index, (start, stop) in enumerate(ranges)
    )
    return AtlasRunPlanV1(shards=shards, **identity)


def plan_payload(plan: AtlasRunPlanV1) -> dict[str, object]:
    identity = plan.model_dump(mode="json")
    return {**identity, "plan_sha256": plan.plan_sha256}


def write_plan(path: Path, plan: AtlasRunPlanV1) -> str:
    payload = plan_payload(plan)
    raw = (json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    Path(path).write_bytes(raw)
    return plan.plan_sha256


def load_plan(path: Path) -> AtlasRunPlanV1:
    payload = json.loads(Path(path).read_text("utf-8"))
    expected = payload.pop("plan_sha256", None)
    plan = AtlasRunPlanV1.model_validate(payload)
    if expected != plan.plan_sha256:
        raise ValueError("ATLAS_PLAN_HASH_INVALID")
    if len(plan.shards) != plan.total_shards:
        raise ValueError("ATLAS_PLAN_SHARD_COUNT_MISMATCH")
    cursor = plan.ordinal_start
    for index, shard in enumerate(plan.shards):
        if shard.shard_index != index or shard.start_ordinal != cursor:
            raise ValueError("ATLAS_PLAN_SHARD_GAP_OR_OVERLAP")
        if shard.stop_ordinal - shard.start_ordinal != shard.expected_recipe_count:
            raise ValueError("ATLAS_PLAN_SHARD_COUNT_INVALID")
        cursor = shard.stop_ordinal
    if cursor != plan.ordinal_stop or plan.ordinal_stop - plan.ordinal_start != plan.requested_recipe_count:
        raise ValueError("ATLAS_PLAN_COVERAGE_INVALID")
    return plan


__all__ = [
    "AtlasRunPlanV1",
    "AtlasShardPlanV1",
    "build_run_plan",
    "load_plan",
    "partition_ordinals",
    "plan_payload",
    "write_plan",
]
