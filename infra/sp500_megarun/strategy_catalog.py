"""Deterministic, train-bound strategy catalog definitions for the SP500 mega-run."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from itertools import product
import json
import math
import re
from typing import Any, Mapping, Sequence

from aurora.infra.sp500_megarun.dehb_configspace import (
    _forbidden_parameter_pairs,
    _forbidden_parameter_triplets,
)
from aurora.infra.sp500_megarun.feature_contract import (
    FeatureLaneSpec,
    FrozenFeatureContract,
)


CATALOG_ID_DOMAIN = b"AURORA-SP500-STRATEGY-CATALOG-V1\0"
CATALOG_RECIPE_DOMAIN = b"AURORA-SP500-STRATEGY-RECIPE-V1\0"
CATALOG_CONFIGURATION_DOMAIN = b"AURORA-SP500-STRATEGY-CONFIGURATION-V1\0"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_LANE_RE = re.compile(r"^F\d{3}$")
_JSON_ATOM_CACHE: dict[tuple[type[object], object], str] = {}


class CatalogBuildError(ValueError):
    """Raised when a catalog row or artifact violates the frozen contract."""


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


__all__ = [
    "CatalogBuildError",
    "CatalogComponentV1",
    "StrategyCatalogEntryV1",
    "build_individual_entries",
    "canonical_json_bytes",
    "configuration_sha256",
    "enumerate_valid_configurations",
    "individual_coverage_requirements",
    "scientific_recipe_sha256",
    "select_covering_configurations",
    "strategy_id_for",
]
