"""Exact ConfigSpace adapter for the official DEHB SP500 campaign."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib
import json
from typing import Any, Mapping

from aurora.infra.sp500_megarun.feature_contract import (
    FeatureLaneSpec,
    FrozenFeatureContract,
)


FIDELITIES = (1, 3, 9, 27)
ETA = 3


class DehbConfigSpaceError(RuntimeError):
    """Raised when the official DEHB search space is not exactly reproducible."""


@dataclass(frozen=True)
class LaneConfigSpace:
    """One frozen lane and its official ConfigSpace object."""

    lane_id: str
    seed: int
    dimensions: tuple[str, ...]
    canonical_sha256: str
    configspace: Any


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise DehbConfigSpaceError("NON_JSON_CONFIGSPACE_VALUE") from exc


def _configspace_module(configspace_module: Any | None) -> Any:
    if configspace_module is not None:
        return configspace_module
    try:
        return importlib.import_module("ConfigSpace")
    except ModuleNotFoundError as exc:
        raise DehbConfigSpaceError(
            "CONFIGSPACE_DEPENDENCY_MISSING:use_requirements/dehb-official.lock"
        ) from exc


def _lane_by_id(contract: FrozenFeatureContract, lane_id: str) -> FeatureLaneSpec:
    try:
        lane = next(item for item in contract.lanes if item.lane_id == lane_id)
    except StopIteration as exc:
        raise DehbConfigSpaceError(f"UNKNOWN_LANE:{lane_id}") from exc
    if lane.implementation_status != "executable":
        raise DehbConfigSpaceError(f"LANE_NOT_EXECUTABLE:{lane_id}")
    if not lane.parameter_space:
        raise DehbConfigSpaceError(f"EMPTY_PARAMETER_SPACE:{lane_id}")
    return lane


def build_lane_configspace(
    contract: FrozenFeatureContract,
    lane_id: str,
    *,
    seed: int,
    configspace_module: Any | None = None,
) -> LaneConfigSpace:
    """Build one discrete space without interpolation or implicit crosses."""

    lane = _lane_by_id(contract, lane_id)
    module = _configspace_module(configspace_module)
    try:
        space = module.ConfigurationSpace(seed=seed)
        hyperparameters = [
            module.CategoricalHyperparameter(
                name,
                choices=tuple(choices),
                default_value=choices[0],
            )
            for name, choices in lane.parameter_space.items()
        ]
        space.add(hyperparameters)
    except (AttributeError, TypeError, ValueError) as exc:
        raise DehbConfigSpaceError(f"CONFIGSPACE_BUILD_FAILED:{lane_id}:{exc}") from exc
    return LaneConfigSpace(
        lane_id=lane.lane_id,
        seed=int(seed),
        dimensions=tuple(lane.parameter_space),
        canonical_sha256=lane.canonical_sha256,
        configspace=space,
    )


def build_all_lane_configspaces(
    contract: FrozenFeatureContract,
    *,
    base_seed: int,
    configspace_module: Any | None = None,
) -> tuple[LaneConfigSpace, ...]:
    """Build the 240 independent lane spaces with deterministic seeds."""

    if len(contract.lanes) != 240:
        raise DehbConfigSpaceError(f"EXPECTED_240_LANES:{len(contract.lanes)}")
    return tuple(
        build_lane_configspace(
            contract,
            lane.lane_id,
            seed=base_seed + index,
            configspace_module=configspace_module,
        )
        for index, lane in enumerate(contract.lanes)
    )


def _closed_boundaries(contract: FrozenFeatureContract) -> None:
    if contract.validation_opened:
        raise DehbConfigSpaceError("VALIDATION_MUST_REMAIN_CLOSED")
    if contract.locked_opened:
        raise DehbConfigSpaceError("LOCKED_MUST_REMAIN_CLOSED")
    if contract.search_end.isoformat() != "2010-12-31":
        raise DehbConfigSpaceError(f"INVALID_SEARCH_END:{contract.search_end.isoformat()}")


def build_cross_manifest(contract: FrozenFeatureContract) -> Mapping[str, Any]:
    """Freeze approved cross rules separately from independent lane searches."""

    _closed_boundaries(contract)
    rules = [
        {
            "rule_id": rule.rule_id,
            "left_lanes": list(rule.left_lanes),
            "right_lanes": list(rule.right_lanes),
            "compositions": list(rule.compositions),
            "max_features": rule.max_features,
            "economic_rationale": rule.economic_rationale,
        }
        for rule in contract.cross_rules
    ]
    payload: dict[str, Any] = {
        "feature_contract_sha256": contract.sha256,
        "cross_rule_count": len(rules),
        "implicit_crosses_in_lane_spaces": False,
        "rules": rules,
    }
    payload["cross_manifest_sha256"] = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
    return payload


def build_dehb_space_manifest(
    contract: FrozenFeatureContract,
    *,
    runtime_versions: Mapping[str, str],
) -> Mapping[str, Any]:
    """Return the hashable scientific manifest used by every official DEHB island."""

    _closed_boundaries(contract)
    if len(contract.lanes) != 240:
        raise DehbConfigSpaceError(f"EXPECTED_240_LANES:{len(contract.lanes)}")
    if any(lane.implementation_status != "executable" for lane in contract.lanes):
        raise DehbConfigSpaceError("ALL_LANES_MUST_BE_EXECUTABLE")
    required_versions = {"DEHB", "ConfigSpace", "python"}
    missing_versions = sorted(required_versions - set(runtime_versions))
    if missing_versions:
        raise DehbConfigSpaceError(
            f"RUNTIME_VERSION_MISSING:{','.join(missing_versions)}"
        )
    lanes = [
        {
            "lane_id": lane.lane_id,
            "canonical_sha256": lane.canonical_sha256,
            "parameter_space": {
                name: list(choices) for name, choices in lane.parameter_space.items()
            },
        }
        for lane in contract.lanes
    ]
    payload: dict[str, Any] = {
        "schema_version": 1,
        "engine": "official_dehb",
        "feature_contract_sha256": contract.sha256,
        "search_end": contract.search_end.isoformat(),
        "validation_opened": False,
        "locked_opened": False,
        "fidelities": list(FIDELITIES),
        "eta": ETA,
        "lane_count": len(lanes),
        "runtime_versions": dict(sorted(runtime_versions.items())),
        "cross_manifest_sha256": build_cross_manifest(contract)[
            "cross_manifest_sha256"
        ],
        "lanes": lanes,
    }
    payload["manifest_sha256"] = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
    return payload


__all__ = [
    "DehbConfigSpaceError",
    "ETA",
    "FIDELITIES",
    "LaneConfigSpace",
    "build_all_lane_configspaces",
    "build_cross_manifest",
    "build_dehb_space_manifest",
    "build_lane_configspace",
]
