"""Exact ConfigSpace adapter for the official DEHB SP500 campaign."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib
import json
import math
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
    forbidden_configuration_count: int
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


def _forbidden_parameter_pairs(
    lane: FeatureLaneSpec,
) -> tuple[tuple[str, Any, str, Any], ...]:
    space = lane.parameter_space
    pairs: list[tuple[str, Any, str, Any]] = []
    if lane.lane_id == "F002":
        pairs.extend(
            ("fast", fast, "slow", slow)
            for fast in space["fast"]
            for slow in space["slow"]
            if int(fast) >= int(slow)
        )
    if lane.lane_id == "F120":
        pairs.extend(
            ("embargo", embargo, "horizon", horizon)
            for embargo in space["embargo"]
            for horizon in space["horizon"]
            if int(embargo) < int(horizon)
        )
    if lane.lane_id in {"F172", "F180"}:
        pairs.extend(
            ("window", window, "long_window", long_window)
            for window in space["window"]
            for long_window in space["long_window"]
            if int(long_window) <= int(window)
        )
    if lane.lane_id in {"F023", "F026", "F030", "F031"}:
        pairs.extend(
            ("window", 1, "normalization", normalization)
            for normalization in space["normalization"]
            if normalization != "none"
        )
    if lane.lane_id == "F026":
        pairs.extend(
            ("window", 1, "form", form)
            for form in ("correlation", "divergence")
        )
    if lane.lane_id == "F022":
        for window in space["window"]:
            seen_effective_tails: set[int] = set()
            for tail in space["tail"]:
                effective_tail_count = math.ceil(float(tail) * int(window))
                if effective_tail_count in seen_effective_tails:
                    pairs.append(("window", window, "tail", tail))
                else:
                    seen_effective_tails.add(effective_tail_count)
    if lane.lane_id == "F051":
        pairs.extend(
            ("aggregation", aggregation, "normalization_window", window)
            for aggregation in ("majority", "unanimity")
            for window in space["normalization_window"][1:]
        )
    if lane.lane_id == "F055":
        pairs.append(("kind", "causal_pelt", "reset", True))
    if lane.lane_id == "F057":
        pairs.extend(
            ("model", "gam", "components", components)
            for components in space["components"][1:]
        )
        pairs.extend(
            ("model", "pls", parameter, choice)
            for parameter in ("knots", "ridge")
            for choice in space[parameter][1:]
        )
    if lane.lane_id == "F058":
        pairs.extend(
            ("model", "tree", parameter, choice)
            for parameter in ("estimators", "learning_rate")
            for choice in space[parameter][1:]
        )
        pairs.extend(
            ("model", "boosted_stumps", "depth", depth)
            for depth in space["depth"][1:]
        )
    if lane.lane_id == "F059":
        pairs.extend(
            (
                ("logic", "identity", "depth", 3),
                ("logic", "majority", "depth", 2),
            )
        )
    if lane.lane_id == "F060":
        pairs.extend(
            ("rule", rule, "seed", seed)
            for rule in space["rule"]
            if rule != "block_placebo"
            for seed in space["seed"][1:]
        )
        pairs.extend(
            ("rule", rule, "hold", hold)
            for rule in ("always_long", "always_short")
            for hold in space["hold"][1:]
        )
    if lane.lane_id == "F069":
        pairs.extend(
            ("distribution", "normal", "student_df", student_df)
            for student_df in space["student_df"][1:]
        )
    if lane.lane_id == "F074":
        pairs.extend(
            ("statistic", "breakout_pressure", parameter, choice)
            for parameter in ("pivot_span", "tolerance")
            for choice in space[parameter][1:]
        )
    if lane.lane_id == "F079":
        pairs.extend(
            ("statistic", statistic, "zero_tolerance_bps", tolerance)
            for statistic in ("volume_drought", "volume_shock")
            for tolerance in space["zero_tolerance_bps"][1:]
        )
    if lane.lane_id == "F082":
        pairs.extend(
            ("statistic", statistic, "lag", lag)
            for statistic in ("level", "percentile")
            for lag in space["lag"][1:]
        )
    if lane.lane_id == "F083":
        pairs.extend(
            ("statistic", statistic, "lag", lag)
            for statistic in ("noncommercial_short", "reportable_short")
            for lag in space["lag"][1:]
        )
    if lane.lane_id == "F084":
        pairs.extend(
            ("statistic", "financing_pressure", "balance_window", window)
            for window in space["balance_window"][1:]
        )
        pairs.extend(
            ("statistic", "allocation_pressure", "margin_window", window)
            for window in space["margin_window"][1:]
        )
    if lane.lane_id == "F085":
        pairs.extend(
            ("statistic", "close_location", "window", window)
            for window in space["window"][1:]
        )
    if lane.lane_id == "F086":
        pairs.extend(
            ("statistic", "participation_gap", parameter, choice)
            for parameter in ("window", "lag")
            for choice in space[parameter][1:]
        )
    if lane.lane_id == "F087":
        pairs.extend(
            ("statistic", statistic, parameter, choice)
            for statistic in (
                "noncommercial_gap",
                "commercial_gap",
                "open_interest_share",
            )
            for parameter in ("window", "lag")
            for choice in space[parameter][1:]
        )
    if lane.lane_id == "F088":
        pairs.extend(
            ("statistic", statistic, "lag", lag)
            for statistic in (
                "top4_level",
                "top8_level",
                "top4_top8_share",
                "combined_gap",
            )
            for lag in space["lag"][1:]
        )
        pairs.extend(
            ("statistic", "top4_top8_share", "window", window)
            for window in space["window"][1:]
        )
    if lane.lane_id == "F089":
        pairs.extend(
            ("statistic", "realized_asymmetry", "change_lag", lag)
            for lag in space["change_lag"][1:]
        )
    if lane.lane_id == "F091":
        pairs.extend(
            ("statistic", statistic, "tail_quantile", quantile)
            for statistic in ("vol_of_vol", "methodology_disagreement")
            for quantile in space["tail_quantile"][1:]
        )
        pairs.extend(
            ("statistic", "methodology_disagreement", "window", window)
            for window in space["window"][1:]
        )
    if lane.lane_id == "F093":
        pairs.extend(
            ("statistic", statistic, "positioning_window", window)
            for statistic in ("implied_downside_gap", "tail_realization")
            for window in space["positioning_window"][1:]
        )
        pairs.extend(
            ("statistic", "positioning_pressure", parameter, choice)
            for parameter in ("window", "tail_quantile")
            for choice in space[parameter][1:]
        )
    if lane.lane_id == "F095":
        pairs.extend(
            ("statistic", statistic, "change_lag", lag)
            for statistic in ("rate_volatility", "volatility_ratio", "divergence")
            for lag in space["change_lag"][1:]
        )
    if lane.lane_id == "F097":
        pairs.extend(
            ("statistic", "growth_breadth", "window", window)
            for window in space["window"][1:]
        )
    if lane.lane_id == "F098":
        pairs.extend(
            ("statistic", "surprise_breadth", "scale_window", window)
            for window in space["scale_window"][1:]
        )
    if lane.lane_id == "F099":
        pairs.extend(
            ("statistic", "inflation_level", parameter, choice)
            for parameter in ("forecast_window", "scale_window")
            for choice in space[parameter][1:]
        )
        pairs.extend(
            ("statistic", statistic, "scale_window", window)
            for statistic in ("inflation_trend", "inflation_acceleration")
            for window in space["scale_window"][1:]
        )
    if lane.lane_id == "F100":
        pairs.extend(
            ("statistic", statistic, "normalization_window", window)
            for statistic in ("policy_change", "real_rate", "rule_gap")
            for window in space["normalization_window"][1:]
        )
    return tuple(pairs)


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
        forbidden_pairs = _forbidden_parameter_pairs(lane)
        forbidden_clauses = [
            module.ForbiddenAndConjunction(
                module.ForbiddenEqualsClause(space[left_name], left_value),
                module.ForbiddenEqualsClause(space[right_name], right_value),
            )
            for left_name, left_value, right_name, right_value in forbidden_pairs
        ]
        if forbidden_clauses:
            space.add(forbidden_clauses)
    except (AttributeError, TypeError, ValueError) as exc:
        raise DehbConfigSpaceError(f"CONFIGSPACE_BUILD_FAILED:{lane_id}:{exc}") from exc
    return LaneConfigSpace(
        lane_id=lane.lane_id,
        seed=int(seed),
        dimensions=tuple(lane.parameter_space),
        canonical_sha256=lane.canonical_sha256,
        forbidden_configuration_count=len(forbidden_pairs),
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
            "forbidden_parameter_pairs": [
                [left_name, left_value, right_name, right_value]
                for left_name, left_value, right_name, right_value in (
                    _forbidden_parameter_pairs(lane)
                )
            ],
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
