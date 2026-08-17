"""Deterministic, train-bound strategy catalog definitions for the SP500 mega-run."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import io
from itertools import product
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Mapping, Sequence

from aurora.infra.sp500_megarun.data_contract import load_and_validate_contract
from aurora.infra.sp500_megarun.dehb_configspace import (
    _forbidden_parameter_pairs,
    _forbidden_parameter_triplets,
)
from aurora.infra.sp500_megarun.feature_contract import (
    CrossRule,
    FeatureLaneSpec,
    FrozenFeatureContract,
    load_and_validate_feature_contract,
)


CATALOG_ID_DOMAIN = b"AURORA-SP500-STRATEGY-CATALOG-V1\0"
CATALOG_RECIPE_DOMAIN = b"AURORA-SP500-STRATEGY-RECIPE-V1\0"
CATALOG_CONFIGURATION_DOMAIN = b"AURORA-SP500-STRATEGY-CONFIGURATION-V1\0"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_LANE_RE = re.compile(r"^F\d{3}$")
_JSON_ATOM_CACHE: dict[tuple[type[object], object], str] = {}
_ARTIFACT_FILENAMES = (
    "catalog.jsonl",
    "catalog.csv",
    "manifest.json",
    "coverage.json",
    "README.md",
)
_HASHED_ARTIFACT_FILENAMES = (
    "catalog.jsonl",
    "catalog.csv",
    "coverage.json",
    "README.md",
)
_CSV_COLUMNS = (
    "strategy_id",
    "scientific_recipe_sha256",
    "strategy_kind",
    "feature_count",
    "initial_fidelity",
    "lane_ids",
    "components_json",
    "composition_json",
    "cross_rule_ids",
    "economic_rationales",
    "coverage_tags",
    "feature_contract_sha256",
    "search_end",
    "validation_opened",
    "locked_opened",
    "performance_status",
)


class CatalogBuildError(ValueError):
    """Raised when a catalog row or artifact violates the frozen contract."""


@dataclass(frozen=True)
class StrategyCatalogBuildV1:
    """Pure in-memory catalog plus its train-only provenance and coverage."""

    entries: tuple[StrategyCatalogEntryV1, ...]
    coverage: Mapping[str, Any]
    data_contract_sha256: str
    feature_contract_sha256: str
    search_end: str
    validation_opened: bool
    locked_opened: bool


def canonical_json_bytes(value: object) -> bytes:
    """Return stable strict JSON bytes for hashes and versioned artifacts."""

    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CatalogBuildError("CATALOG_VALUE_NOT_CANONICAL_JSON") from exc


def _sha256(domain: bytes, value: object) -> str:
    return hashlib.sha256(domain + canonical_json_bytes(value)).hexdigest()


def _require_sha256(value: object, label: str) -> str:
    text = str(value)
    if _SHA256_RE.fullmatch(text) is None:
        raise CatalogBuildError(f"CATALOG_INVALID_SHA256:{label}")
    return text


def configuration_sha256(
    lane_id: str,
    configuration: Mapping[str, object],
) -> str:
    """Bind one canonical lane configuration to its lane identity."""

    if _LANE_RE.fullmatch(str(lane_id)) is None:
        raise CatalogBuildError(f"CATALOG_INVALID_LANE_ID:{lane_id}")
    payload = {"lane_id": str(lane_id), "configuration": dict(configuration)}
    return _sha256(CATALOG_CONFIGURATION_DOMAIN, payload)


@dataclass(frozen=True)
class CatalogComponentV1:
    """One exact lane configuration used by a catalog strategy."""

    lane_id: str
    configuration: Mapping[str, object]
    configuration_sha256: str

    @classmethod
    def create(
        cls,
        lane_id: str,
        configuration: Mapping[str, object],
    ) -> CatalogComponentV1:
        checked_lane = str(lane_id)
        checked_configuration = dict(configuration)
        return cls(
            lane_id=checked_lane,
            configuration=checked_configuration,
            configuration_sha256=configuration_sha256(
                checked_lane,
                checked_configuration,
            ),
        )

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> CatalogComponentV1:
        lane_id = str(payload.get("lane_id", ""))
        raw_configuration = payload.get("configuration")
        if not isinstance(raw_configuration, Mapping):
            raise CatalogBuildError("CATALOG_COMPONENT_CONFIGURATION_INVALID")
        component = cls.create(lane_id, raw_configuration)
        supplied = _require_sha256(
            payload.get("configuration_sha256"),
            "configuration_sha256",
        )
        if supplied != component.configuration_sha256:
            raise CatalogBuildError("CATALOG_COMPONENT_HASH_MISMATCH")
        return component

    def to_payload(self) -> dict[str, object]:
        return {
            "lane_id": self.lane_id,
            "configuration": dict(self.configuration),
            "configuration_sha256": self.configuration_sha256,
        }


def _scientific_recipe_payload(
    *,
    strategy_kind: str,
    components: Sequence[CatalogComponentV1],
    composition: Mapping[str, object],
    feature_contract_sha256: str,
    search_end: str,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "strategy_kind": strategy_kind,
        "components": [component.to_payload() for component in components],
        "composition": dict(composition),
        "feature_contract_sha256": feature_contract_sha256,
        "search_end": search_end,
        "position_contract": {
            "allowed_positions": [-1, 1],
            "zero_action": "carry_previous",
        },
    }


def scientific_recipe_sha256(recipe: Mapping[str, object]) -> str:
    """Hash a fully canonical scientific recipe."""

    return _sha256(CATALOG_RECIPE_DOMAIN, dict(recipe))


def strategy_id_for(recipe: Mapping[str, object]) -> str:
    """Return the stable human-visible ID for one scientific recipe."""

    return "SCV1-" + _sha256(CATALOG_ID_DOMAIN, dict(recipe))


@dataclass(frozen=True)
class StrategyCatalogEntryV1:
    """Validated catalog row with provenance kept outside scientific identity."""

    schema_version: int
    strategy_id: str
    scientific_recipe_sha256: str
    strategy_kind: str
    components: tuple[CatalogComponentV1, ...]
    composition: Mapping[str, object]
    cross_rule_ids: tuple[str, ...]
    economic_rationales: tuple[str, ...]
    feature_count: int
    initial_fidelity: int
    coverage_tags: tuple[str, ...]
    feature_contract_sha256: str
    search_end: str
    validation_opened: bool
    locked_opened: bool
    performance_status: str

    @classmethod
    def create(
        cls,
        *,
        strategy_kind: str,
        components: Sequence[CatalogComponentV1],
        composition: Mapping[str, object],
        cross_rule_ids: Sequence[str],
        economic_rationales: Sequence[str],
        coverage_tags: Sequence[str],
        feature_contract_sha256: str,
        search_end: str = "2010-12-31",
    ) -> StrategyCatalogEntryV1:
        checked_components = tuple(components)
        if strategy_kind not in {"single", "cross"}:
            raise CatalogBuildError("CATALOG_STRATEGY_KIND_INVALID")
        if not 1 <= len(checked_components) <= 5:
            raise CatalogBuildError("CATALOG_FEATURE_COUNT_INVALID")
        lane_ids = [component.lane_id for component in checked_components]
        if len(set(lane_ids)) != len(lane_ids):
            raise CatalogBuildError("CATALOG_COMPONENT_LANE_DUPLICATE")
        if strategy_kind == "single" and len(checked_components) != 1:
            raise CatalogBuildError("CATALOG_SINGLE_FEATURE_COUNT_INVALID")
        if strategy_kind == "cross" and len(checked_components) < 2:
            raise CatalogBuildError("CATALOG_CROSS_FEATURE_COUNT_INVALID")
        feature_hash = _require_sha256(
            feature_contract_sha256,
            "feature_contract_sha256",
        )
        if search_end != "2010-12-31":
            raise CatalogBuildError("CATALOG_SEARCH_END_INVALID")
        recipe = _scientific_recipe_payload(
            strategy_kind=strategy_kind,
            components=checked_components,
            composition=composition,
            feature_contract_sha256=feature_hash,
            search_end=search_end,
        )
        return cls(
            schema_version=1,
            strategy_id=strategy_id_for(recipe),
            scientific_recipe_sha256=scientific_recipe_sha256(recipe),
            strategy_kind=strategy_kind,
            components=checked_components,
            composition=dict(composition),
            cross_rule_ids=tuple(sorted({str(value) for value in cross_rule_ids})),
            economic_rationales=tuple(
                sorted({str(value) for value in economic_rationales})
            ),
            feature_count=len(checked_components),
            initial_fidelity=1,
            coverage_tags=tuple(sorted({str(value) for value in coverage_tags})),
            feature_contract_sha256=feature_hash,
            search_end=search_end,
            validation_opened=False,
            locked_opened=False,
            performance_status="not_evaluated",
        )

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> StrategyCatalogEntryV1:
        if payload.get("validation_opened") is not False or payload.get(
            "locked_opened"
        ) is not False:
            raise CatalogBuildError("CATALOG_BOUNDARY_OPEN")
        if payload.get("schema_version") != 1:
            raise CatalogBuildError("CATALOG_SCHEMA_VERSION_INVALID")
        if payload.get("initial_fidelity") != 1:
            raise CatalogBuildError("CATALOG_INITIAL_FIDELITY_INVALID")
        if payload.get("performance_status") != "not_evaluated":
            raise CatalogBuildError("CATALOG_PERFORMANCE_STATUS_INVALID")
        raw_components = payload.get("components")
        if not isinstance(raw_components, list):
            raise CatalogBuildError("CATALOG_COMPONENTS_INVALID")
        raw_composition = payload.get("composition")
        if not isinstance(raw_composition, Mapping):
            raise CatalogBuildError("CATALOG_COMPOSITION_INVALID")
        raw_rules = payload.get("cross_rule_ids")
        raw_rationales = payload.get("economic_rationales")
        raw_coverage = payload.get("coverage_tags")
        if not all(
            isinstance(value, list)
            for value in (raw_rules, raw_rationales, raw_coverage)
        ):
            raise CatalogBuildError("CATALOG_PROVENANCE_INVALID")
        entry = cls.create(
            strategy_kind=str(payload.get("strategy_kind", "")),
            components=[
                CatalogComponentV1.from_payload(component)
                for component in raw_components
                if isinstance(component, Mapping)
            ],
            composition=raw_composition,
            cross_rule_ids=[str(value) for value in raw_rules],
            economic_rationales=[str(value) for value in raw_rationales],
            coverage_tags=[str(value) for value in raw_coverage],
            feature_contract_sha256=str(payload.get("feature_contract_sha256", "")),
            search_end=str(payload.get("search_end", "")),
        )
        if payload.get("feature_count") != entry.feature_count:
            raise CatalogBuildError("CATALOG_FEATURE_COUNT_MISMATCH")
        if payload.get("strategy_id") != entry.strategy_id:
            raise CatalogBuildError("CATALOG_STRATEGY_ID_MISMATCH")
        if payload.get("scientific_recipe_sha256") != entry.scientific_recipe_sha256:
            raise CatalogBuildError("CATALOG_RECIPE_HASH_MISMATCH")
        return entry

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "strategy_id": self.strategy_id,
            "scientific_recipe_sha256": self.scientific_recipe_sha256,
            "strategy_kind": self.strategy_kind,
            "components": [component.to_payload() for component in self.components],
            "composition": dict(self.composition),
            "cross_rule_ids": list(self.cross_rule_ids),
            "economic_rationales": list(self.economic_rationales),
            "feature_count": self.feature_count,
            "initial_fidelity": self.initial_fidelity,
            "coverage_tags": list(self.coverage_tags),
            "feature_contract_sha256": self.feature_contract_sha256,
            "search_end": self.search_end,
            "validation_opened": self.validation_opened,
            "locked_opened": self.locked_opened,
            "performance_status": self.performance_status,
        }


def _lane_constraints(
    lane: FeatureLaneSpec,
) -> tuple[tuple[tuple[str, object], ...], ...]:
    constraints: list[tuple[tuple[str, object], ...]] = []
    for left_name, left_value, right_name, right_value in (
        _forbidden_parameter_pairs(lane)
    ):
        constraints.append(
            ((left_name, left_value), (right_name, right_value))
        )
    for (
        first_name,
        first_value,
        second_name,
        second_value,
        third_name,
        third_value,
    ) in _forbidden_parameter_triplets(lane):
        constraints.append(
            (
                (first_name, first_value),
                (second_name, second_value),
                (third_name, third_value),
            )
        )
    return tuple(constraints)


def _matches_constraint(
    configuration: Mapping[str, object],
    constraint: tuple[tuple[str, object], ...],
) -> bool:
    return all(configuration[name] == value for name, value in constraint)


def enumerate_valid_configurations(
    lane: FeatureLaneSpec,
) -> tuple[dict[str, object], ...]:
    """Enumerate one lane's exact discrete configurations and reject forbiddens."""

    parameter_names = tuple(lane.parameter_space)
    constraints = _lane_constraints(lane)
    valid: list[dict[str, object]] = []
    for values in product(*(lane.parameter_space[name] for name in parameter_names)):
        configuration = dict(zip(parameter_names, values, strict=True))
        if any(
            _matches_constraint(configuration, constraint)
            for constraint in constraints
        ):
            continue
        valid.append(configuration)
    valid.sort(key=canonical_json_bytes)
    if not valid:
        raise CatalogBuildError(f"CATALOG_LANE_HAS_NO_VALID_CONFIG:{lane.lane_id}")
    return tuple(valid)


def _json_atom(value: object) -> str:
    try:
        key = (type(value), value)
        cached = _JSON_ATOM_CACHE.get(key)
    except TypeError:
        return canonical_json_bytes(value).decode("ascii")
    if cached is None:
        cached = canonical_json_bytes(value).decode("ascii")
        _JSON_ATOM_CACHE[key] = cached
    return cached


def _configuration_requirement_tags(
    configuration: Mapping[str, object],
    parameter_names: Sequence[str],
) -> tuple[str, ...]:
    tags = [
        f"parameter:{name}={_json_atom(configuration[name])}"
        for name in parameter_names
    ]
    for left_index, left_name in enumerate(parameter_names):
        for right_name in parameter_names[left_index + 1 :]:
            tags.append(
                "pair:"
                f"{left_name}={_json_atom(configuration[left_name])}|"
                f"{right_name}={_json_atom(configuration[right_name])}"
            )
    return tuple(tags)


def individual_coverage_requirements(
    lane: FeatureLaneSpec,
    valid_configurations: Sequence[Mapping[str, object]],
) -> tuple[str, ...]:
    """Return every one-way and compatible pairwise requirement for one lane."""

    parameter_names = tuple(lane.parameter_space)
    requirements: set[str] = set()
    for configuration in valid_configurations:
        requirements.update(
            _configuration_requirement_tags(configuration, parameter_names)
        )
    return tuple(sorted(requirements))


def select_covering_configurations(
    lane: FeatureLaneSpec,
    valid_configurations: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    """Choose a deterministic greedy covering set, always including the default."""

    if not valid_configurations:
        raise CatalogBuildError(f"CATALOG_LANE_HAS_NO_VALID_CONFIG:{lane.lane_id}")
    parameter_names = tuple(lane.parameter_space)
    requirements = individual_coverage_requirements(lane, valid_configurations)
    requirement_index = {
        requirement: index for index, requirement in enumerate(requirements)
    }
    candidate_data: list[tuple[bytes, int]] = []
    for configuration in valid_configurations:
        mask = 0
        for tag in _configuration_requirement_tags(configuration, parameter_names):
            mask |= 1 << requirement_index[tag]
        candidate_data.append((canonical_json_bytes(configuration), mask))

    default = {
        name: choices[0] for name, choices in lane.parameter_space.items()
    }
    default_bytes = canonical_json_bytes(default)
    try:
        default_index = next(
            index
            for index, (encoded, _mask) in enumerate(candidate_data)
            if encoded == default_bytes
        )
    except StopIteration as exc:
        raise CatalogBuildError(
            f"CATALOG_DEFAULT_CONFIGURATION_FORBIDDEN:{lane.lane_id}"
        ) from exc

    selected_indices = [default_index]
    selected_set = {default_index}
    uncovered = (1 << len(requirements)) - 1
    uncovered &= ~candidate_data[default_index][1]
    while uncovered:
        best_index = -1
        best_score = 0
        best_bytes = b""
        for index, (encoded, coverage_mask) in enumerate(candidate_data):
            if index in selected_set:
                continue
            score = (coverage_mask & uncovered).bit_count()
            if score > best_score or (
                score == best_score and score > 0 and encoded < best_bytes
            ):
                best_index = index
                best_score = score
                best_bytes = encoded
        if best_index < 0 or best_score == 0:
            raise CatalogBuildError(
                f"CATALOG_INDIVIDUAL_COVERAGE_STALLED:{lane.lane_id}"
            )
        selected_indices.append(best_index)
        selected_set.add(best_index)
        uncovered &= ~candidate_data[best_index][1]

    return tuple(dict(valid_configurations[index]) for index in selected_indices)


def _validate_catalog_contract(contract: FrozenFeatureContract) -> None:
    if len(contract.lanes) != 240:
        raise CatalogBuildError(f"CATALOG_EXPECTED_240_LANES:{len(contract.lanes)}")
    if any(lane.implementation_status != "executable" for lane in contract.lanes):
        raise CatalogBuildError("CATALOG_LANE_NOT_EXECUTABLE")
    if contract.search_end.isoformat() != "2010-12-31":
        raise CatalogBuildError("CATALOG_SEARCH_END_INVALID")
    if contract.validation_opened or contract.locked_opened:
        raise CatalogBuildError("CATALOG_BOUNDARY_OPEN")


def build_individual_entries(
    contract: FrozenFeatureContract,
) -> tuple[tuple[StrategyCatalogEntryV1, ...], dict[str, Any]]:
    """Build the minimum deterministic individual catalog for all 240 lanes."""

    _validate_catalog_contract(contract)
    entries: list[StrategyCatalogEntryV1] = []
    lane_reports: list[dict[str, object]] = []
    raw_cartesian_count = 0
    valid_configuration_count = 0
    requirement_count = 0
    for lane in contract.lanes:
        lane_raw_count = math.prod(
            len(choices) for choices in lane.parameter_space.values()
        )
        raw_cartesian_count += lane_raw_count
        valid = enumerate_valid_configurations(lane)
        selected = select_covering_configurations(lane, valid)
        requirements = tuple(
            sorted(
                {
                    tag
                    for configuration in selected
                    for tag in _configuration_requirement_tags(
                        configuration,
                        tuple(lane.parameter_space),
                    )
                }
            )
        )
        valid_configuration_count += len(valid)
        requirement_count += len(requirements)
        selected_ids: list[str] = []
        for configuration in selected:
            component = CatalogComponentV1.create(lane.lane_id, configuration)
            entry = StrategyCatalogEntryV1.create(
                strategy_kind="single",
                components=(component,),
                composition={"kind": "identity"},
                cross_rule_ids=(),
                economic_rationales=(),
                coverage_tags=(
                    f"lane:{lane.lane_id}",
                    *_configuration_requirement_tags(
                        configuration,
                        tuple(lane.parameter_space),
                    ),
                ),
                feature_contract_sha256=contract.sha256,
            )
            entries.append(entry)
            selected_ids.append(entry.strategy_id)
        lane_reports.append(
            {
                "lane_id": lane.lane_id,
                "raw_cartesian_count": lane_raw_count,
                "valid_configuration_count": len(valid),
                "requirement_count": len(requirements),
                "selected_strategy_count": len(selected),
                "selected_strategy_ids": selected_ids,
                "uncovered_requirements": [],
            }
        )

    if raw_cartesian_count != 682_652:
        raise CatalogBuildError(
            f"CATALOG_RAW_CARTESIAN_COUNT_MISMATCH:{raw_cartesian_count}"
        )
    entries.sort(key=lambda entry: entry.strategy_id)
    report: dict[str, Any] = {
        "lane_count": len(contract.lanes),
        "raw_cartesian_count": raw_cartesian_count,
        "valid_configuration_count": valid_configuration_count,
        "requirement_count": requirement_count,
        "selected_strategy_count": len(entries),
        "uncovered_requirements": [],
        "lanes": lane_reports,
    }
    return tuple(entries), report


_COMMUTATIVE_COMPOSITIONS = {"and", "vote", "weighted_score"}
_WEIGHT_VALUES = (-2.0, -1.0, -0.5, 0.5, 1.0, 2.0)


def _component_sort_key(component: CatalogComponentV1) -> tuple[str, str]:
    return component.lane_id, component.configuration_sha256


def _weight_ratio_key(weights: Sequence[float]) -> tuple[int, ...]:
    doubled = [int(round(float(value) * 2.0)) for value in weights]
    divisor = math.gcd(*[abs(value) for value in doubled])
    ratio = tuple(value // divisor for value in doubled)
    if ratio[0] < 0:
        ratio = tuple(-value for value in ratio)
    return ratio


def _canonical_weight_values(weights: Sequence[float]) -> tuple[float, ...]:
    if not weights or any(float(value) not in _WEIGHT_VALUES for value in weights):
        raise CatalogBuildError("CATALOG_WEIGHT_INVALID")
    ratio = _weight_ratio_key(weights)
    allowed = {Fraction(str(value)) for value in _WEIGHT_VALUES}
    candidates: list[tuple[Fraction, ...]] = []
    for first_value in sorted(value for value in allowed if value > 0):
        scale = first_value / ratio[0]
        candidate = tuple(Fraction(value) * scale for value in ratio)
        if all(value in allowed for value in candidate):
            candidates.append(candidate)
    if not candidates:
        raise CatalogBuildError("CATALOG_WEIGHT_CANONICALIZATION_FAILED")
    winner = min(
        candidates,
        key=lambda values: (sum(abs(value) for value in values), values),
    )
    return tuple(float(value) for value in winner)


def canonicalize_composition(
    kind: str,
    components: Sequence[CatalogComponentV1],
    *,
    vote_mode: str | None = None,
    weights: Sequence[float] | None = None,
) -> tuple[tuple[CatalogComponentV1, ...], dict[str, object]]:
    """Canonicalize component ordering and the exact composition payload."""

    checked_components = tuple(components)
    if not 2 <= len(checked_components) <= 5:
        raise CatalogBuildError("CATALOG_CROSS_FEATURE_COUNT_INVALID")
    if len({component.lane_id for component in checked_components}) != len(
        checked_components
    ):
        raise CatalogBuildError("CATALOG_COMPONENT_LANE_DUPLICATE")
    if kind not in {"and", "gate", "override", "vote", "weighted_score"}:
        raise CatalogBuildError(f"CATALOG_COMPOSITION_INVALID:{kind}")

    if kind == "weighted_score":
        if weights is None or len(weights) != len(checked_components):
            raise CatalogBuildError("CATALOG_WEIGHT_COUNT_INVALID")
        ordered_pairs = sorted(
            zip(checked_components, (float(value) for value in weights), strict=True),
            key=lambda pair: _component_sort_key(pair[0]),
        )
        ordered_components = tuple(pair[0] for pair in ordered_pairs)
        ordered_weights = _canonical_weight_values(
            tuple(pair[1] for pair in ordered_pairs)
        )
        return ordered_components, {
            "kind": "weighted_score",
            "weights": list(ordered_weights),
        }

    if weights is not None:
        raise CatalogBuildError("CATALOG_UNEXPECTED_WEIGHTS")
    if kind in _COMMUTATIVE_COMPOSITIONS:
        checked_components = tuple(sorted(checked_components, key=_component_sort_key))
    if kind == "vote":
        if vote_mode not in {"majority", "unanimity"}:
            raise CatalogBuildError("CATALOG_VOTE_MODE_INVALID")
        return checked_components, {
            "kind": "vote",
            "mode": vote_mode,
        }
    if vote_mode is not None:
        raise CatalogBuildError("CATALOG_UNEXPECTED_VOTE_MODE")
    payload: dict[str, object] = {"kind": kind}
    if kind == "gate":
        payload["base_component_index"] = 0
    elif kind == "override":
        payload["base_component_index"] = 0
        payload["priority_component_index"] = len(checked_components) - 1
    return checked_components, payload


def _weight_patterns(arity: int) -> tuple[tuple[float, ...], ...]:
    canonical_candidates = {
        _canonical_weight_values(values)
        for values in product(_WEIGHT_VALUES, repeat=arity)
        if values[0] > 0
    }
    candidates = tuple(sorted(canonical_candidates))
    parameter_names = tuple(f"weight_{index}" for index in range(arity))
    candidate_maps = tuple(
        dict(zip(parameter_names, values, strict=True)) for values in candidates
    )
    requirements: set[str] = set()
    for candidate in candidate_maps:
        requirements.update(_configuration_requirement_tags(candidate, parameter_names))
    requirement_index = {
        requirement: index for index, requirement in enumerate(sorted(requirements))
    }
    masks: list[int] = []
    for candidate in candidate_maps:
        mask = 0
        for tag in _configuration_requirement_tags(candidate, parameter_names):
            mask |= 1 << requirement_index[tag]
        masks.append(mask)
    uncovered = (1 << len(requirement_index)) - 1
    selected: list[tuple[float, ...]] = []
    selected_indexes: set[int] = set()
    while uncovered:
        best_index = -1
        best_score = 0
        for index, mask in enumerate(masks):
            if index in selected_indexes:
                continue
            score = (mask & uncovered).bit_count()
            if score > best_score:
                best_index = index
                best_score = score
        if best_index < 0:
            raise CatalogBuildError("CATALOG_WEIGHT_COVERAGE_STALLED")
        selected_indexes.add(best_index)
        selected.append(candidates[best_index])
        uncovered &= ~masks[best_index]
    return tuple(selected)


def _higher_arity_lane_ids(
    rule: CrossRule,
    *,
    arity: int,
    row_index: int,
) -> tuple[str, ...]:
    left_lane = rule.left_lanes[row_index % len(rule.left_lanes)]
    right_lane = next(
        lane
        for offset in range(len(rule.right_lanes))
        if (lane := rule.right_lanes[(row_index + offset) % len(rule.right_lanes)])
        != left_lane
    )
    selected = [left_lane, right_lane]
    union = tuple(sorted(set(rule.left_lanes) | set(rule.right_lanes)))
    if len(union) < arity:
        raise CatalogBuildError(f"CATALOG_CROSS_ARITY_UNAVAILABLE:{rule.rule_id}")
    offset = 0
    while len(selected) < arity:
        candidate = union[(row_index + offset) % len(union)]
        offset += 1
        if candidate not in selected:
            selected.append(candidate)
    return tuple(selected)


def merge_duplicate_entries(
    entries: Sequence[StrategyCatalogEntryV1],
) -> tuple[StrategyCatalogEntryV1, ...]:
    """Merge duplicate scientific recipes while retaining all provenance."""

    merged: dict[str, StrategyCatalogEntryV1] = {}
    for entry in entries:
        prior = merged.get(entry.scientific_recipe_sha256)
        if prior is None:
            merged[entry.scientific_recipe_sha256] = entry
            continue
        if (
            prior.strategy_id != entry.strategy_id
            or prior.components != entry.components
            or dict(prior.composition) != dict(entry.composition)
        ):
            raise CatalogBuildError("CATALOG_STRATEGY_ID_COLLISION")
        merged_entry = StrategyCatalogEntryV1.create(
            strategy_kind=prior.strategy_kind,
            components=prior.components,
            composition=prior.composition,
            cross_rule_ids=(*prior.cross_rule_ids, *entry.cross_rule_ids),
            economic_rationales=(
                *prior.economic_rationales,
                *entry.economic_rationales,
            ),
            coverage_tags=(*prior.coverage_tags, *entry.coverage_tags),
            feature_contract_sha256=prior.feature_contract_sha256,
            search_end=prior.search_end,
        )
        if merged_entry.strategy_id != prior.strategy_id:
            raise CatalogBuildError("CATALOG_STRATEGY_ID_COLLISION")
        merged[entry.scientific_recipe_sha256] = merged_entry
    return tuple(sorted(merged.values(), key=lambda entry: entry.strategy_id))


def build_cross_entries(
    contract: FrozenFeatureContract,
    individual_entries: Sequence[StrategyCatalogEntryV1],
) -> tuple[tuple[StrategyCatalogEntryV1, ...], dict[str, Any]]:
    """Expand CR01-CR14 with exact pair and higher-arity coverage."""

    _validate_catalog_contract(contract)
    if len(contract.cross_rules) != 14:
        raise CatalogBuildError(
            f"CATALOG_EXPECTED_14_CROSS_RULES:{len(contract.cross_rules)}"
        )
    by_lane: dict[str, list[CatalogComponentV1]] = {
        lane.lane_id: [] for lane in contract.lanes
    }
    for entry in individual_entries:
        if entry.strategy_kind != "single" or len(entry.components) != 1:
            raise CatalogBuildError("CATALOG_INDIVIDUAL_INPUT_INVALID")
        by_lane[entry.components[0].lane_id].append(entry.components[0])
    if any(not values for values in by_lane.values()):
        raise CatalogBuildError("CATALOG_INDIVIDUAL_LANE_MISSING")
    for values in by_lane.values():
        values.sort(key=_component_sort_key)

    cursors = {lane_id: 0 for lane_id in by_lane}
    used_components: dict[str, set[str]] = {
        lane_id: set() for lane_id in by_lane
    }
    weight_patterns = {arity: _weight_patterns(arity) for arity in range(2, 6)}
    weight_cursors = {arity: 0 for arity in range(2, 6)}
    raw_entries: list[StrategyCatalogEntryV1] = []
    covered_rule_composition_arities: set[str] = set()
    covered_authorized_pairs: set[str] = set()
    raw_pair_composition_count = 0

    def next_component(
        lane_id: str,
        fixed: CatalogComponentV1 | None = None,
    ) -> CatalogComponentV1:
        if fixed is not None:
            component = fixed
        else:
            values = by_lane[lane_id]
            component = values[cursors[lane_id] % len(values)]
            cursors[lane_id] += 1
        used_components[lane_id].add(component.configuration_sha256)
        return component

    def emit(
        rule: CrossRule,
        composition_kind: str,
        lane_ids: Sequence[str],
        *,
        fixed_components: Mapping[str, CatalogComponentV1] | None = None,
        authorized_pair: tuple[str, str] | None = None,
        supplemental: bool = False,
    ) -> None:
        components = tuple(
            next_component(lane_id, (fixed_components or {}).get(lane_id))
            for lane_id in lane_ids
        )
        variants: list[
            tuple[str | None, tuple[float, ...] | None]
        ] = [(None, None)]
        if composition_kind == "vote":
            variants = [("majority", None), ("unanimity", None)]
        elif composition_kind == "weighted_score":
            arity = len(components)
            patterns = weight_patterns[arity]
            pattern = patterns[weight_cursors[arity] % len(patterns)]
            weight_cursors[arity] += 1
            variants = [(None, pattern)]
        for vote_mode, weights in variants:
            ordered_components, composition = canonicalize_composition(
                composition_kind,
                components,
                vote_mode=vote_mode,
                weights=weights,
            )
            arity_tag = (
                f"rule_composition_arity:{rule.rule_id}|"
                f"{composition_kind}|{len(ordered_components)}"
            )
            tags = [
                f"rule:{rule.rule_id}",
                arity_tag,
                *(
                    f"component:{component.lane_id}|"
                    f"{component.configuration_sha256}"
                    for component in ordered_components
                ),
            ]
            if authorized_pair is not None:
                pair_tag = (
                    f"authorized_pair:{rule.rule_id}|{composition_kind}|"
                    f"{authorized_pair[0]}|{authorized_pair[1]}"
                )
                tags.append(pair_tag)
                covered_authorized_pairs.add(pair_tag)
            if supplemental:
                tags.append("supplemental:component_configuration_coverage")
            raw_entries.append(
                StrategyCatalogEntryV1.create(
                    strategy_kind="cross",
                    components=ordered_components,
                    composition=composition,
                    cross_rule_ids=(rule.rule_id,),
                    economic_rationales=(rule.economic_rationale,),
                    coverage_tags=tags,
                    feature_contract_sha256=contract.sha256,
                )
            )
            covered_rule_composition_arities.add(arity_tag)

    required_rule_composition_arities: set[str] = set()
    required_authorized_pairs: set[str] = set()
    participating_lanes: set[str] = set()
    for rule in contract.cross_rules:
        participating_lanes.update(rule.left_lanes)
        participating_lanes.update(rule.right_lanes)
        for composition_kind in rule.compositions:
            for arity in range(2, rule.max_features + 1):
                required_rule_composition_arities.add(
                    f"rule_composition_arity:{rule.rule_id}|"
                    f"{composition_kind}|{arity}"
                )
            for left_lane in rule.left_lanes:
                for right_lane in rule.right_lanes:
                    if left_lane == right_lane:
                        continue
                    raw_pair_composition_count += 1
                    pair_tag = (
                        f"authorized_pair:{rule.rule_id}|{composition_kind}|"
                        f"{left_lane}|{right_lane}"
                    )
                    required_authorized_pairs.add(pair_tag)
                    emit(
                        rule,
                        composition_kind,
                        (left_lane, right_lane),
                        authorized_pair=(left_lane, right_lane),
                    )
            for arity in range(3, rule.max_features + 1):
                row_count = max(len(rule.left_lanes), len(rule.right_lanes))
                for row_index in range(row_count):
                    emit(
                        rule,
                        composition_kind,
                        _higher_arity_lane_ids(
                            rule,
                            arity=arity,
                            row_index=row_index,
                        ),
                    )

    if raw_pair_composition_count != 26_480:
        raise CatalogBuildError(
            "CATALOG_RAW_CROSS_PAIR_COUNT_MISMATCH:"
            f"{raw_pair_composition_count}"
        )

    for lane_id in sorted(participating_lanes):
        required_components = by_lane[lane_id]
        unused = [
            component
            for component in required_components
            if component.configuration_sha256 not in used_components[lane_id]
        ]
        if not unused:
            continue
        eligible_rule = next(
            rule
            for rule in contract.cross_rules
            if lane_id in rule.left_lanes or lane_id in rule.right_lanes
        )
        if lane_id in eligible_rule.left_lanes:
            counterpart = next(
                value for value in eligible_rule.right_lanes if value != lane_id
            )
            supplemental_lanes = (lane_id, counterpart)
        else:
            counterpart = next(
                value for value in eligible_rule.left_lanes if value != lane_id
            )
            supplemental_lanes = (counterpart, lane_id)
        for component in unused:
            emit(
                eligible_rule,
                eligible_rule.compositions[0],
                supplemental_lanes,
                fixed_components={lane_id: component},
                supplemental=True,
            )

    required_component_hashes = {
        lane_id: {
            component.configuration_sha256 for component in by_lane[lane_id]
        }
        for lane_id in sorted(participating_lanes)
    }
    uncovered_parameter_values = [
        f"{lane_id}:{configuration_sha}"
        for lane_id, required_hashes in required_component_hashes.items()
        for configuration_sha in sorted(required_hashes - used_components[lane_id])
    ]
    uncovered_arities = sorted(
        required_rule_composition_arities - covered_rule_composition_arities
    )
    uncovered_pairs = sorted(
        required_authorized_pairs - covered_authorized_pairs
    )
    if uncovered_arities or uncovered_pairs or uncovered_parameter_values:
        raise CatalogBuildError("CATALOG_CROSS_COVERAGE_INCOMPLETE")

    entries = merge_duplicate_entries(raw_entries)
    report: dict[str, Any] = {
        "rule_count": len(contract.cross_rules),
        "participating_lane_count": len(participating_lanes),
        "raw_pair_composition_count": raw_pair_composition_count,
        "raw_strategy_count": len(raw_entries),
        "deduplicated_strategy_count": len(entries),
        "duplicate_strategy_count": len(raw_entries) - len(entries),
        "required_rule_composition_arities": sorted(
            required_rule_composition_arities
        ),
        "uncovered_rule_composition_arities": uncovered_arities,
        "required_authorized_left_right_pair_count": len(
            required_authorized_pairs
        ),
        "uncovered_authorized_left_right_pairs": uncovered_pairs,
        "required_component_configuration_count": sum(
            len(values) for values in required_component_hashes.values()
        ),
        "uncovered_parameter_values": uncovered_parameter_values,
    }
    return entries, report


_BUILD_CACHE: dict[tuple[str, str], StrategyCatalogBuildV1] = {}


def _uncovered_requirement_count(coverage: Mapping[str, Any]) -> int:
    individual = coverage.get("individual")
    cross = coverage.get("cross")
    if not isinstance(individual, Mapping) or not isinstance(cross, Mapping):
        raise CatalogBuildError("CATALOG_COVERAGE_REPORT_INVALID")
    keys = (
        (individual, "uncovered_requirements"),
        (cross, "uncovered_rule_composition_arities"),
        (cross, "uncovered_authorized_left_right_pairs"),
        (cross, "uncovered_parameter_values"),
    )
    count = 0
    for report, key in keys:
        values = report.get(key)
        if not isinstance(values, list):
            raise CatalogBuildError(f"CATALOG_COVERAGE_FIELD_INVALID:{key}")
        count += len(values)
    return count


def build_strategy_catalog(
    data_contract_path: Path,
    feature_contract_path: Path,
) -> StrategyCatalogBuildV1:
    """Build the complete metadata-only catalog without loading market data."""

    data_contract = load_and_validate_contract(Path(data_contract_path))
    feature_contract = load_and_validate_feature_contract(
        Path(feature_contract_path),
        data_contract,
    )
    if data_contract.expected_lane_count != 240 or len(feature_contract.lanes) != 240:
        raise CatalogBuildError("CATALOG_EXPECTED_240_LANES")
    if any(lane.implementation_status != "executable" for lane in feature_contract.lanes):
        raise CatalogBuildError("CATALOG_NON_EXECUTABLE_LANE")
    if (
        data_contract.boundaries.validation_opened
        or data_contract.boundaries.locked_opened
        or feature_contract.validation_opened
        or feature_contract.locked_opened
    ):
        raise CatalogBuildError("CATALOG_BOUNDARY_OPEN")
    if feature_contract.search_end.isoformat() != "2010-12-31":
        raise CatalogBuildError("CATALOG_SEARCH_END_INVALID")

    cache_key = (data_contract.sha256, feature_contract.sha256)
    cached = _BUILD_CACHE.get(cache_key)
    if cached is not None:
        return cached

    individual_entries, individual_report = build_individual_entries(feature_contract)
    cross_entries, cross_report = build_cross_entries(
        feature_contract,
        individual_entries,
    )
    entries = tuple(
        sorted((*individual_entries, *cross_entries), key=lambda entry: entry.strategy_id)
    )
    if len({entry.strategy_id for entry in entries}) != len(entries):
        raise CatalogBuildError("CATALOG_DUPLICATE_STRATEGY_ID")
    if len({entry.scientific_recipe_sha256 for entry in entries}) != len(entries):
        raise CatalogBuildError("CATALOG_DUPLICATE_SCIENTIFIC_RECIPE")
    coverage: dict[str, Any] = {
        "schema_version": 1,
        "individual": individual_report,
        "cross": cross_report,
    }
    if _uncovered_requirement_count(coverage) != 0:
        raise CatalogBuildError("CATALOG_COVERAGE_INCOMPLETE")
    build = StrategyCatalogBuildV1(
        entries=entries,
        coverage=coverage,
        data_contract_sha256=data_contract.sha256,
        feature_contract_sha256=feature_contract.sha256,
        search_end=feature_contract.search_end.isoformat(),
        validation_opened=False,
        locked_opened=False,
    )
    _BUILD_CACHE[cache_key] = build
    return build


def _catalog_jsonl_bytes(entries: Sequence[StrategyCatalogEntryV1]) -> bytes:
    return b"".join(canonical_json_bytes(entry.to_payload()) + b"\n" for entry in entries)


def _catalog_csv_bytes(entries: Sequence[StrategyCatalogEntryV1]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=list(_CSV_COLUMNS),
        lineterminator="\n",
        quoting=csv.QUOTE_MINIMAL,
    )
    writer.writeheader()
    for entry in entries:
        payload = entry.to_payload()
        writer.writerow(
            {
                "strategy_id": entry.strategy_id,
                "scientific_recipe_sha256": entry.scientific_recipe_sha256,
                "strategy_kind": entry.strategy_kind,
                "feature_count": entry.feature_count,
                "initial_fidelity": entry.initial_fidelity,
                "lane_ids": "|".join(
                    component.lane_id for component in entry.components
                ),
                "components_json": canonical_json_bytes(payload["components"]).decode(),
                "composition_json": canonical_json_bytes(payload["composition"]).decode(),
                "cross_rule_ids": "|".join(entry.cross_rule_ids),
                "economic_rationales": canonical_json_bytes(
                    payload["economic_rationales"]
                ).decode(),
                "coverage_tags": canonical_json_bytes(payload["coverage_tags"]).decode(),
                "feature_contract_sha256": entry.feature_contract_sha256,
                "search_end": entry.search_end,
                "validation_opened": "false",
                "locked_opened": "false",
                "performance_status": entry.performance_status,
            }
        )
    return stream.getvalue().encode("utf-8")


def _readme_bytes(build: StrategyCatalogBuildV1) -> bytes:
    individual = build.coverage["individual"]
    cross = build.coverage["cross"]
    text = f"""# SP500 Strategy Catalog V1

Deterministic catalog of predefined SP500 strategy recipes. It is metadata only:
no strategy in this directory has been backtested or ranked.

- Training boundary: through {build.search_end}
- Validation 2011-2020 opened: false
- Locked 2021+ opened: false
- Individual lanes: {individual["lane_count"]}
- Cross rules: {cross["rule_count"]}
- Strategies: {len(build.entries)}
- Initial fidelity recommendation: 1
- Performance status for every row: not_evaluated

`catalog.jsonl` is authoritative. `catalog.csv` is a review-friendly projection.
`coverage.json` records requirement coverage and `manifest.json` binds every file
to its SHA-256 digest. This catalog does not change or launch the active DEHB
campaign and does not decide any future integration with DEHB.
"""
    return text.encode("utf-8")


def _artifact_payloads(build: StrategyCatalogBuildV1) -> dict[str, bytes]:
    payloads = {
        "catalog.jsonl": _catalog_jsonl_bytes(build.entries),
        "catalog.csv": _catalog_csv_bytes(build.entries),
        "coverage.json": canonical_json_bytes(build.coverage) + b"\n",
        "README.md": _readme_bytes(build),
    }
    artifact_hashes = {
        name: hashlib.sha256(payload).hexdigest()
        for name, payload in sorted(payloads.items())
    }
    individual = build.coverage["individual"]
    cross = build.coverage["cross"]
    manifest = {
        "schema_version": 1,
        "catalog_id": "sp500-strategy-catalog-v1",
        "data_contract_sha256": build.data_contract_sha256,
        "feature_contract_sha256": build.feature_contract_sha256,
        "search_end": build.search_end,
        "validation_opened": build.validation_opened,
        "locked_opened": build.locked_opened,
        "performance_status": "not_evaluated",
        "initial_fidelity": 1,
        "lane_count": individual["lane_count"],
        "cross_rule_count": cross["rule_count"],
        "individual_strategy_count": individual["selected_strategy_count"],
        "cross_strategy_count": cross["deduplicated_strategy_count"],
        "strategy_count": len(build.entries),
        "uncovered_requirement_count": _uncovered_requirement_count(build.coverage),
        "artifacts_sha256": artifact_hashes,
    }
    payloads["manifest.json"] = canonical_json_bytes(manifest) + b"\n"
    return payloads


def verify_strategy_catalog_directory(output_dir: Path) -> dict[str, Any]:
    """Reopen and fail closed on any inconsistent catalog artifact."""

    root = Path(output_dir)
    if not root.is_dir():
        raise CatalogBuildError(f"CATALOG_DIRECTORY_NOT_FOUND:{root}")
    actual_names = {path.name for path in root.iterdir() if path.is_file()}
    if actual_names != set(_ARTIFACT_FILENAMES):
        raise CatalogBuildError("CATALOG_ARTIFACT_SET_INVALID")
    try:
        manifest = json.loads((root / "manifest.json").read_bytes())
        coverage = json.loads((root / "coverage.json").read_bytes())
    except (json.JSONDecodeError, OSError) as exc:
        raise CatalogBuildError("CATALOG_ARTIFACT_JSON_INVALID") from exc
    if not isinstance(manifest, Mapping) or not isinstance(coverage, Mapping):
        raise CatalogBuildError("CATALOG_ARTIFACT_ROOT_INVALID")
    expected_hashes = manifest.get("artifacts_sha256")
    if not isinstance(expected_hashes, Mapping):
        raise CatalogBuildError("CATALOG_MANIFEST_HASHES_INVALID")
    for name in _HASHED_ARTIFACT_FILENAMES:
        expected = _require_sha256(expected_hashes.get(name), f"artifact:{name}")
        actual = hashlib.sha256((root / name).read_bytes()).hexdigest()
        if actual != expected:
            raise CatalogBuildError(f"CATALOG_ARTIFACT_HASH_MISMATCH:{name}")

    raw_lines = (root / "catalog.jsonl").read_bytes().splitlines()
    entries: list[StrategyCatalogEntryV1] = []
    for index, raw_line in enumerate(raw_lines, start=1):
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise CatalogBuildError(f"CATALOG_JSONL_INVALID:{index}") from exc
        if not isinstance(payload, Mapping):
            raise CatalogBuildError(f"CATALOG_JSONL_ROW_INVALID:{index}")
        if raw_line != canonical_json_bytes(payload):
            raise CatalogBuildError(f"CATALOG_JSONL_NOT_CANONICAL:{index}")
        entries.append(StrategyCatalogEntryV1.from_payload(payload))
    if not entries:
        raise CatalogBuildError("CATALOG_EMPTY")
    if len({entry.strategy_id for entry in entries}) != len(entries):
        raise CatalogBuildError("CATALOG_DUPLICATE_STRATEGY_ID")
    if [entry.strategy_id for entry in entries] != sorted(
        entry.strategy_id for entry in entries
    ):
        raise CatalogBuildError("CATALOG_ROW_ORDER_INVALID")

    csv_text = (root / "catalog.csv").read_text(encoding="utf-8")
    reader = csv.DictReader(io.StringIO(csv_text, newline=""))
    if tuple(reader.fieldnames or ()) != _CSV_COLUMNS:
        raise CatalogBuildError("CATALOG_CSV_COLUMNS_INVALID")
    csv_rows = list(reader)
    if [row["strategy_id"] for row in csv_rows] != [
        entry.strategy_id for entry in entries
    ]:
        raise CatalogBuildError("CATALOG_CSV_ROWS_MISMATCH")

    uncovered_count = _uncovered_requirement_count(coverage)
    if uncovered_count != 0:
        raise CatalogBuildError("CATALOG_COVERAGE_INCOMPLETE")
    expected_count = int(manifest.get("strategy_count", -1))
    if expected_count != len(entries) or len(csv_rows) != len(entries):
        raise CatalogBuildError("CATALOG_MANIFEST_COUNT_MISMATCH")
    if manifest.get("search_end") != "2010-12-31":
        raise CatalogBuildError("CATALOG_SEARCH_END_INVALID")
    if bool(manifest.get("validation_opened")) or bool(manifest.get("locked_opened")):
        raise CatalogBuildError("CATALOG_BOUNDARY_OPEN")
    if any(
        entry.search_end != "2010-12-31"
        or entry.validation_opened
        or entry.locked_opened
        or entry.performance_status != "not_evaluated"
        for entry in entries
    ):
        raise CatalogBuildError("CATALOG_ROW_BOUNDARY_INVALID")
    return {
        "accepted": True,
        "strategy_count": len(entries),
        "individual_strategy_count": int(
            manifest.get("individual_strategy_count", -1)
        ),
        "cross_strategy_count": int(manifest.get("cross_strategy_count", -1)),
        "uncovered_requirement_count": uncovered_count,
        "search_end": "2010-12-31",
        "validation_opened": False,
        "locked_opened": False,
        "performance_status": "not_evaluated",
    }


def write_strategy_catalog(
    build: StrategyCatalogBuildV1,
    output_dir: Path,
) -> dict[str, Any]:
    """Write five deterministic files after verifying a complete staging copy."""

    root = Path(output_dir)
    root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{root.name}.tmp-", dir=str(root.parent))
    )
    try:
        payloads = _artifact_payloads(build)
        if set(payloads) != set(_ARTIFACT_FILENAMES):
            raise CatalogBuildError("CATALOG_ARTIFACT_SET_INVALID")
        for name in _ARTIFACT_FILENAMES:
            (staging / name).write_bytes(payloads[name])
        verify_strategy_catalog_directory(staging)
        root.mkdir(parents=True, exist_ok=True)
        for name in _ARTIFACT_FILENAMES:
            os.replace(staging / name, root / name)
        return verify_strategy_catalog_directory(root)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def build_and_write_strategy_catalog(
    data_contract_path: Path,
    feature_contract_path: Path,
    *,
    output_dir: Path,
) -> dict[str, Any]:
    """Build and atomically write the train-only strategy catalog."""

    build = build_strategy_catalog(data_contract_path, feature_contract_path)
    return write_strategy_catalog(build, output_dir)


__all__ = [
    "CatalogBuildError",
    "CatalogComponentV1",
    "StrategyCatalogBuildV1",
    "StrategyCatalogEntryV1",
    "build_and_write_strategy_catalog",
    "build_cross_entries",
    "build_individual_entries",
    "build_strategy_catalog",
    "canonical_json_bytes",
    "canonicalize_composition",
    "configuration_sha256",
    "enumerate_valid_configurations",
    "individual_coverage_requirements",
    "merge_duplicate_entries",
    "scientific_recipe_sha256",
    "select_covering_configurations",
    "strategy_id_for",
    "verify_strategy_catalog_directory",
    "write_strategy_catalog",
]
