"""Compact, deterministic representation of the complete SP500 Atlas-1.

The exhaustive Atlas-1 space is too large to materialise as one JSONL file.
This module stores every lane configuration once and describes every recipe as
an immutable ordinal range.  The ranges are disjoint after formal
canonicalisation, so a future static worker can enumerate them without
creating artificial duplicates or relying on a shared queue.

This module only prepares metadata.  It never loads market data and never
evaluates a strategy.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from itertools import product
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.feature_contract import (
    CrossRule,
    FrozenFeatureContract,
)
from aurora.infra.sp500_megarun.strategy_catalog import (
    CatalogComponentV1,
    _canonical_weight_values,
    enumerate_valid_configurations,
)


_SPACE_DOMAIN = "AURORA-SP500-ATLAS-SPACE-V1"
_RECIPE_DOMAIN = "AURORA-SP500-ATLAS-RECIPE-V1"
_COMMUTATIVE = frozenset({"and", "vote", "weighted_score"})
_WEIGHTS = (-2.0, -1.0, -0.5, 0.5, 1.0, 2.0)


def _hash_payload(domain: str, payload: object) -> str:
    return hashlib.sha256(
        domain.encode("ascii")
        + b"\0"
        + json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _weight_variants() -> tuple[dict[str, object], ...]:
    """Return every distinct allowed two-signal weight ratio."""

    values = {
        tuple(_canonical_weight_values(candidate))
        for candidate in product(_WEIGHTS, repeat=2)
        if candidate[0] > 0
    }
    return tuple(
        {"kind": "weighted_score", "weights": list(values_)}
        for values_ in sorted(values)
    )


def composition_variants(kind: str) -> tuple[dict[str, object], ...]:
    """Return all formal two-component variants for one authorised kind."""

    if kind == "and":
        return ({"kind": "and"},)
    if kind == "gate":
        return ({"kind": "gate", "base_component_index": 0},)
    if kind == "override":
        return (
            {
                "kind": "override",
                "base_component_index": 0,
                "priority_component_index": 1,
            },
        )
    if kind == "vote":
        return (
            {"kind": "vote", "mode": "majority"},
            {"kind": "vote", "mode": "unanimity"},
        )
    if kind == "weighted_score":
        return _weight_variants()
    raise ValueError(f"ATLAS_UNKNOWN_COMPOSITION:{kind}")


@dataclass(frozen=True)
class AtlasRangeV1:
    """One disjoint ordinal interval in the complete recipe space."""

    range_id: str
    start_ordinal: int
    stop_ordinal: int
    strategy_kind: str
    direction: int
    lane_ids: tuple[str, ...]
    component_counts: tuple[int, ...]
    composition_kind: str
    composition_variants: tuple[dict[str, object], ...]
    rule_ids: tuple[str, ...]
    formal_source_variant_count: int = 1

    @property
    def recipe_count(self) -> int:
        return self.stop_ordinal - self.start_ordinal

    def to_payload(self) -> dict[str, object]:
        return {
            "range_id": self.range_id,
            "start_ordinal": self.start_ordinal,
            "stop_ordinal": self.stop_ordinal,
            "recipe_count": self.recipe_count,
            "strategy_kind": self.strategy_kind,
            "direction": self.direction,
            "lane_ids": list(self.lane_ids),
            "component_counts": list(self.component_counts),
            "composition_kind": self.composition_kind,
            "composition_variants": [dict(x) for x in self.composition_variants],
            "rule_ids": list(self.rule_ids),
            "formal_source_variant_count": self.formal_source_variant_count,
        }


@dataclass(frozen=True)
class AtlasSpaceV1:
    """Complete compact Atlas-1 manifest data."""

    catalog_id: str
    feature_contract_sha256: str
    train_end: str
    lane_component_counts: Mapping[str, int]
    lane_component_offsets: Mapping[str, int]
    ranges: tuple[AtlasRangeV1, ...]
    raw_requested_recipe_count: int
    canonical_recipe_count: int
    formal_duplicate_count: int
    validation_opened: bool = False
    locked_opened: bool = False

    def to_payload(self) -> dict[str, object]:
        identity = {
            "schema_version": 1,
            "space_version": "1",
            "catalog_id": self.catalog_id,
            "feature_contract_sha256": self.feature_contract_sha256,
            "train_end": self.train_end,
            "lane_component_counts": dict(sorted(self.lane_component_counts.items())),
            "lane_component_offsets": dict(sorted(self.lane_component_offsets.items())),
            "ranges": [item.to_payload() for item in self.ranges],
            "raw_requested_recipe_count": self.raw_requested_recipe_count,
            "canonical_recipe_count": self.canonical_recipe_count,
            "formal_duplicate_count": self.formal_duplicate_count,
            "materialization": "compact_ordinal_ranges",
            "validation_opened": self.validation_opened,
            "locked_opened": self.locked_opened,
        }
        return {**identity, "space_sha256": canonical_sha256(identity)}


def _pair_key(kind: str, left: str, right: str) -> tuple[str, str, str]:
    if kind in _COMMUTATIVE:
        left, right = sorted((left, right))
    return kind, left, right


def _apply_composition(
    kind: str,
    values: Sequence[int],
    composition: Mapping[str, object],
) -> int:
    """Evaluate a two-input composition on {-1, 0, +1} only."""

    if kind == "and":
        return values[0] if values[0] != 0 and values[0] == values[1] else 0
    if kind == "gate":
        base = values[int(composition.get("base_component_index", 0))]
        return base if base != 0 and values[0] == base and values[1] == base else 0
    if kind == "override":
        base = values[int(composition.get("base_component_index", 0))]
        priority = values[int(composition.get("priority_component_index", 1))]
        return priority if priority != 0 else base
    if kind == "vote":
        positive = sum(value == 1 for value in values)
        negative = sum(value == -1 for value in values)
        needed = 2 if composition.get("mode") == "unanimity" else 2
        return 1 if positive >= needed else (-1 if negative >= needed else 0)
    if kind == "weighted_score":
        weights = tuple(float(value) for value in composition["weights"])
        score = sum(value * weight for value, weight in zip(values, weights, strict=True))
        return 1 if score > 0 else (-1 if score < 0 else 0)
    raise ValueError(f"ATLAS_UNKNOWN_COMPOSITION:{kind}")


def _canonical_pair_variant(
    raw_lane_ids: tuple[str, str],
    kind: str,
    composition: Mapping[str, object],
    direction: int,
) -> tuple[tuple[str, str], tuple[int, ...], dict[str, object]]:
    """Return sorted component order, truth table and normalized semantics."""

    sorted_lane_ids = tuple(sorted(raw_lane_ids))
    raw_to_sorted = tuple(sorted_lane_ids.index(item) for item in raw_lane_ids)
    normalized = dict(composition)
    if kind in {"gate", "override"}:
        for key in ("base_component_index", "priority_component_index"):
            if key in normalized:
                normalized[key] = raw_to_sorted[int(normalized[key])]
    elif kind == "weighted_score":
        raw_weights = tuple(float(value) for value in normalized["weights"])
        sorted_weights = [0.0, 0.0]
        for raw_index, sorted_index in enumerate(raw_to_sorted):
            sorted_weights[sorted_index] = raw_weights[raw_index]
        normalized["weights"] = list(_canonical_weight_values(sorted_weights))
    normalized["direction"] = int(direction)
    table: list[int] = []
    for sorted_values in product((-1, 0, 1), repeat=2):
        raw_values = tuple(sorted_values[index] for index in raw_to_sorted)
        value = _apply_composition(kind, raw_values, composition)
        table.append(int(value) * int(direction))
    return sorted_lane_ids, tuple(table), normalized


def _formal_pair_variants(
    contract: FrozenFeatureContract,
) -> tuple[dict[tuple[str, str], dict[tuple[int, ...], dict[str, object]]], int]:
    """Group all authorised pair variants by their exact truth table."""

    groups: dict[tuple[str, str], dict[tuple[int, ...], dict[str, object]]] = defaultdict(dict)
    raw_count = 0
    for rule in contract.cross_rules:
        for kind in rule.compositions:
            variants = composition_variants(kind)
            for left in rule.left_lanes:
                for right in rule.right_lanes:
                    if left == right:
                        continue
                    for direction in (1, -1):
                        for variant in variants:
                            raw_count += 1
                            lane_ids, table, normalized = _canonical_pair_variant(
                                (left, right), kind, variant, direction
                            )
                            key = (lane_ids[0], lane_ids[1])
                            prior = groups[key].get(table)
                            if prior is None:
                                groups[key][table] = {
                                    "kind": kind,
                                    "composition": normalized,
                                    "direction": direction,
                                    "rule_ids": {rule.rule_id},
                                    "source_variant_count": 1,
                                }
                            else:
                                prior["rule_ids"].add(rule.rule_id)
                                prior["source_variant_count"] += 1
    return groups, raw_count


def build_atlas_components(
    contract: FrozenFeatureContract,
) -> tuple[dict[str, tuple[CatalogComponentV1, ...]], dict[str, int]]:
    """Enumerate every valid component configuration without market data."""

    components: dict[str, tuple[CatalogComponentV1, ...]] = {}
    offsets: dict[str, int] = {}
    offset = 0
    for lane in sorted(contract.lanes, key=lambda item: item.lane_id):
        rows = tuple(
            sorted(
                (
                    CatalogComponentV1.create(lane.lane_id, configuration)
                    for configuration in enumerate_valid_configurations(lane)
                ),
                key=lambda item: item.configuration_sha256,
            )
        )
        if not rows:
            raise ValueError(f"ATLAS_EMPTY_LANE:{lane.lane_id}")
        components[lane.lane_id] = rows
        offsets[lane.lane_id] = offset
        offset += len(rows)
    return components, offsets


def build_atlas_space(
    contract: FrozenFeatureContract,
    *,
    catalog_id: str = "sp500-atlas-1",
    include_inverses: bool = True,
) -> tuple[AtlasSpaceV1, dict[str, tuple[CatalogComponentV1, ...]]]:
    """Build the complete pairwise Atlas-1 ordinal space."""

    if not include_inverses:
        raise ValueError("ATLAS1_REQUIRES_INVERSES")
    if contract.search_end.isoformat() != "2010-12-31":
        raise ValueError("ATLAS_SEARCH_END_INVALID")
    if contract.validation_opened or contract.locked_opened:
        raise ValueError("ATLAS_PROTECTED_BOUNDARY_OPEN")
    components, offsets = build_atlas_components(contract)
    counts = {lane: len(values) for lane, values in components.items()}
    directions = (1, -1) if include_inverses else (1,)

    ranges: list[AtlasRangeV1] = []
    ordinal = 0
    raw_requested = sum(counts.values())
    for direction in directions:
        for lane_id in sorted(components):
            count = counts[lane_id]
            payload = {
                "kind": "single",
                "direction": direction,
                "lane_ids": [lane_id],
                "composition_kind": "identity",
            }
            item = AtlasRangeV1(
                range_id=_hash_payload(_SPACE_DOMAIN, payload),
                start_ordinal=ordinal,
                stop_ordinal=ordinal + count,
                strategy_kind="single",
                direction=direction,
                lane_ids=(lane_id,),
                component_counts=(count,),
                composition_kind="identity",
                composition_variants=({"kind": "identity"},),
                rule_ids=(),
            )
            ranges.append(item)
            ordinal += count

    del directions  # Directions are already included in formal truth-table groups.
    pair_groups, raw_cross_one_direction = _formal_pair_variants(contract)
    for (left, right), tables in sorted(pair_groups.items()):
        lanes = (left, right)
        for table, representative in sorted(tables.items(), key=lambda item: item[0]):
            variants = (dict(representative["composition"]),)
            count = counts[left] * counts[right]
            payload = {
                "kind": "cross",
                "direction": representative["direction"],
                "lane_ids": list(lanes),
                "composition_kind": representative["kind"],
                "rule_ids": sorted(representative["rule_ids"]),
                "truth_table": list(table),
            }
            item = AtlasRangeV1(
                range_id=_hash_payload(_SPACE_DOMAIN, payload),
                start_ordinal=ordinal,
                stop_ordinal=ordinal + count,
                strategy_kind="cross",
                direction=int(representative["direction"]),
                lane_ids=lanes,
                component_counts=(counts[left], counts[right]),
                composition_kind=str(representative["kind"]),
                composition_variants=variants,
                rule_ids=tuple(sorted(representative["rule_ids"])),
                formal_source_variant_count=int(representative["source_variant_count"]),
            )
            ranges.append(item)
            ordinal += count

    canonical = ordinal
    raw_cross = 0
    for rule in contract.cross_rules:
        for kind in rule.compositions:
            variant_count = len(composition_variants(kind))
            for left in rule.left_lanes:
                for right in rule.right_lanes:
                    if left != right:
                        raw_cross += counts[left] * counts[right] * variant_count * 2
    if raw_cross_one_direction <= 0 or raw_cross_one_direction != sum(
        len(composition_variants(kind)) * 2
        for rule in contract.cross_rules
        for kind in rule.compositions
        for left in rule.left_lanes
        for right in rule.right_lanes
        if left != right
    ):
        raise ValueError("ATLAS_RAW_PAIR_VARIANT_COUNT_INVALID")
    raw_requested = sum(counts.values()) * 2 + raw_cross
    return (
        AtlasSpaceV1(
            catalog_id=catalog_id,
            feature_contract_sha256=contract.sha256,
            train_end=contract.search_end.isoformat(),
            lane_component_counts=counts,
            lane_component_offsets=offsets,
            ranges=tuple(ranges),
            raw_requested_recipe_count=raw_requested,
            canonical_recipe_count=canonical,
            formal_duplicate_count=raw_requested - canonical,
        ),
        components,
    )


def _find_range(space: AtlasSpaceV1, ordinal: int) -> AtlasRangeV1:
    if ordinal < 0 or ordinal >= space.canonical_recipe_count:
        raise IndexError("ATLAS_ORDINAL_OUT_OF_RANGE")
    starts = [item.start_ordinal for item in space.ranges]
    item = space.ranges[bisect_right(starts, ordinal) - 1]
    if ordinal >= item.stop_ordinal:
        raise IndexError("ATLAS_RANGE_GAP")
    return item


def recipe_for_ordinal(
    space: AtlasSpaceV1,
    components: Mapping[str, Sequence[CatalogComponentV1]],
    ordinal: int,
) -> dict[str, object]:
    """Return one canonical recipe from the compact space."""

    item = _find_range(space, ordinal)
    local = ordinal - item.start_ordinal
    variant_index = local % len(item.composition_variants)
    combination = local // len(item.composition_variants)
    selected: list[CatalogComponentV1] = []
    for lane_id, count in zip(item.lane_ids, item.component_counts, strict=True):
        index = combination % count
        combination //= count
        selected.append(components[lane_id][index])
    selected_ids = [item.configuration_sha256 for item in selected]
    composition = dict(item.composition_variants[variant_index])
    composition["direction"] = item.direction
    payload = {
        "schema_version": 1,
        "strategy_kind": item.strategy_kind,
        "components": selected_ids,
        "composition": composition,
        "feature_contract_sha256": space.feature_contract_sha256,
        "search_end": space.train_end,
        "position_contract": {
            "allowed_positions": [-1, 1],
            "zero_action": "carry_previous",
        },
    }
    return {
        "strategy_id": "ATLAS1-" + _hash_payload(_RECIPE_DOMAIN, payload),
        "scientific_recipe_sha256": _hash_payload(_RECIPE_DOMAIN, payload),
        "strategy_kind": item.strategy_kind,
        "components": selected_ids,
        "composition": composition,
        "cross_rule_ids": list(item.rule_ids),
        "ordinal": ordinal,
        "search_end": space.train_end,
        "validation_opened": False,
        "locked_opened": False,
        "performance_status": "not_evaluated",
    }


def write_component_index(
    path: Path,
    components: Mapping[str, Sequence[CatalogComponentV1]],
) -> str:
    """Write a compact lane-to-component index and return its SHA-256."""

    payload = {
        "schema_version": 1,
        "lanes": {
            lane: [item.configuration_sha256 for item in values]
            for lane, values in sorted(components.items())
        },
        "validation_opened": False,
        "locked_opened": False,
    }
    data = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    raw = (data + "\n").encode("utf-8")
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


__all__ = [
    "AtlasRangeV1",
    "AtlasSpaceV1",
    "build_atlas_components",
    "build_atlas_space",
    "composition_variants",
    "recipe_for_ordinal",
    "write_component_index",
]
