"""Hash-bound, disjoint segment manifests for the finite Atlas campaign."""

from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Any

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.atlas_execution_contract import AtlasRunPlanV1


def _identity(manifest: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in manifest.items() if key != "manifest_sha256"}


def _validate_coverage(manifest: Mapping[str, Any]) -> None:
    total_shards = int(manifest.get("total_shards", 0))
    segments = manifest.get("segments")
    if total_shards <= 0 or not isinstance(segments, list) or not segments:
        raise ValueError("ATLAS_SEGMENT_COVERAGE_INVALID")
    seen: list[int] = []
    for expected_index, segment in enumerate(segments):
        if not isinstance(segment, Mapping):
            raise ValueError("ATLAS_SEGMENT_OBJECT_INVALID")
        if int(segment.get("segment_index", -1)) != expected_index:
            raise ValueError("ATLAS_SEGMENT_INDEX_INVALID")
        shard_indices = segment.get("shard_indices")
        if not isinstance(shard_indices, list) or not shard_indices:
            raise ValueError("ATLAS_SEGMENT_COVERAGE_INVALID")
        if shard_indices != sorted(set(int(value) for value in shard_indices)):
            raise ValueError("ATLAS_SEGMENT_COVERAGE_INVALID")
        seen.extend(int(value) for value in shard_indices)
    if sorted(seen) != list(range(total_shards)):
        raise ValueError("ATLAS_SEGMENT_COVERAGE_INVALID")


def build_segment_manifest(
    plan: AtlasRunPlanV1,
    *,
    max_shards_per_segment: int = 120,
) -> dict[str, Any]:
    """Split the immutable plan into ordered, disjoint, retryable segments."""

    if max_shards_per_segment <= 0:
        raise ValueError("ATLAS_SEGMENT_SIZE_INVALID")
    shard_indices = [shard.shard_index for shard in plan.shards]
    segments: list[dict[str, Any]] = []
    for segment_index, start in enumerate(range(0, len(shard_indices), max_shards_per_segment)):
        selected = shard_indices[start : start + max_shards_per_segment]
        selected_shards = [plan.shard(index) for index in selected]
        segments.append(
            {
                "segment_id": f"atlas-segment-{segment_index:04d}",
                "segment_index": segment_index,
                "shard_indices": selected,
                "start_ordinal": min(shard.start_ordinal for shard in selected_shards),
                "stop_ordinal": max(shard.stop_ordinal for shard in selected_shards),
                "expected_recipe_count": sum(
                    shard.expected_recipe_count for shard in selected_shards
                ),
                "validation_opened": False,
                "locked_opened": False,
            }
        )
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "manifest_kind": "sp500_atlas_segments",
        "plan_sha256": plan.plan_sha256,
        "selection_sha256": plan.selection_sha256,
        "total_shards": plan.total_shards,
        "requested_recipe_count": plan.requested_recipe_count,
        "max_shards_per_segment": max_shards_per_segment,
        "segments": segments,
        "validation_opened": False,
        "locked_opened": False,
    }
    manifest["manifest_sha256"] = canonical_sha256(manifest)
    load_segment_manifest(manifest, plan=plan)
    return manifest


def load_segment_manifest(
    value: Mapping[str, Any] | str | bytes,
    *,
    plan: AtlasRunPlanV1 | None = None,
) -> dict[str, Any]:
    """Validate a segment manifest and return a detached JSON-compatible copy."""

    if isinstance(value, (str, bytes)):
        parsed = json.loads(value)
    else:
        parsed = dict(value)
    if not isinstance(parsed, dict):
        raise ValueError("ATLAS_SEGMENT_MANIFEST_OBJECT_REQUIRED")
    if parsed.get("schema_version") != 1 or parsed.get("manifest_kind") != "sp500_atlas_segments":
        raise ValueError("ATLAS_SEGMENT_MANIFEST_SCHEMA_INVALID")
    if parsed.get("validation_opened") is not False or parsed.get("locked_opened") is not False:
        raise ValueError("ATLAS_SEGMENT_BOUNDARY_OPEN")
    if plan is not None:
        if parsed.get("plan_sha256") != plan.plan_sha256:
            raise ValueError("ATLAS_SEGMENT_PLAN_HASH_INVALID")
        if parsed.get("selection_sha256") != plan.selection_sha256:
            raise ValueError("ATLAS_SEGMENT_SELECTION_HASH_INVALID")
        if int(parsed.get("total_shards", -1)) != plan.total_shards:
            raise ValueError("ATLAS_SEGMENT_TOTAL_SHARDS_INVALID")
        if int(parsed.get("requested_recipe_count", -1)) != plan.requested_recipe_count:
            raise ValueError("ATLAS_SEGMENT_RECIPE_COUNT_INVALID")
    _validate_coverage(parsed)
    supplied = parsed.get("manifest_sha256")
    if supplied != canonical_sha256(_identity(parsed)):
        raise ValueError("ATLAS_SEGMENT_MANIFEST_HASH_INVALID")
    return parsed


__all__ = ["build_segment_manifest", "load_segment_manifest"]
