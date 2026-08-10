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
    if lane.lane_id == "F121":
        pairs.extend(
            ("statistic", statistic, parameter, choice)
            for statistic in ("high_distance", "low_distance", "range_position")
            for parameter in ("buffer_fraction", "confirmation")
            for choice in space[parameter][1:]
        )
    if lane.lane_id == "F123":
        pairs.extend(
            ("statistic", "trix", "slow", slow)
            for slow in space["slow"][1:]
        )
        pairs.extend(
            ("statistic", statistic, "signal", signal)
            for statistic in ("trix", "tsi")
            for signal in space["signal"][1:]
        )
    if lane.lane_id == "F124":
        pairs.extend(
            ("base_window", base, "span_b_window", span)
            for base in space["base_window"]
            for span in space["span_b_window"]
            if int(base) >= int(span)
        )
        pairs.extend(
            ("statistic", "cloud_breakout", "atr_window", window)
            for window in space["atr_window"][1:]
        )
    if lane.lane_id == "F125":
        pairs.extend(
            ("statistic", "parabolic_sar", parameter, choice)
            for parameter in ("window", "atr_multiplier")
            for choice in space[parameter][1:]
        )
        pairs.extend(
            ("statistic", "supertrend", parameter, choice)
            for parameter in (
                "window",
                "acceleration_step",
                "acceleration_max",
            )
            for choice in space[parameter][1:]
        )
        pairs.extend(
            ("statistic", "chandelier", parameter, choice)
            for parameter in ("acceleration_step", "acceleration_max")
            for choice in space[parameter][1:]
        )
    if lane.lane_id == "F127":
        pairs.extend(
            ("statistic", "heikin_ashi", parameter, choice)
            for parameter in ("window", "box_atr", "reversal_boxes")
            for choice in space[parameter][1:]
        )
        pairs.extend(
            ("statistic", "renko", "reversal_boxes", choice)
            for choice in space["reversal_boxes"][1:]
        )
    if lane.lane_id == "F128":
        pairs.extend(
            ("statistic", statistic, parameter, choice)
            for statistic in ("triangle", "wedge")
            for parameter in ("tolerance", "head_margin", "breakout_buffer")
            for choice in space[parameter][1:]
        )
        pairs.extend(
            ("statistic", "double_extreme", "head_margin", choice)
            for choice in space["head_margin"][1:]
        )
        pairs.extend(
            ("statistic", "shoulders", "breakout_buffer", choice)
            for choice in space["breakout_buffer"][1:]
        )
    if lane.lane_id == "F130":
        pairs.extend(
            ("statistic", statistic, parameter, choice)
            for statistic in (
                "chaikin_money_flow",
                "money_flow_index",
                "force_index",
                "ease_of_movement",
            )
            for parameter in ("klinger_fast", "klinger_slow", "klinger_signal")
            for choice in space[parameter][1:]
        )
        pairs.extend(
            ("statistic", "klinger_oscillator", "window", window)
            for window in space["window"][1:]
        )
    if lane.lane_id == "F132":
        pairs.extend(
            ("kind", "emd", parameter, choice)
            for parameter in ("ensembles", "noise_scale")
            for choice in space[parameter][1:]
        )
        pairs.extend(
            ("statistic", statistic, "components", choice)
            for statistic in ("imf1", "imf2")
            for choice in space["components"][1:]
        )
    if lane.lane_id == "F133":
        pairs.append(("window", 63, "embedding", 63))
        pairs.extend(
            ("statistic", statistic, "components", choice)
            for statistic in ("trend_component", "singular_concentration")
            for choice in space["components"][1:]
        )
        pairs.append(("statistic", "oscillatory_component", "components", 1))
    if lane.lane_id == "F134":
        pairs.extend(
            ("statistic", "trend", "min_occurrences", choice)
            for choice in space["min_occurrences"][1:]
        )
    if lane.lane_id == "F135":
        pairs.extend(
            ("statistic", "discord_score", parameter, choice)
            for parameter in ("neighbors", "radius")
            for choice in space[parameter][1:]
        )
        pairs.extend(
            ("statistic", "motif_density", "neighbors", choice)
            for choice in space["neighbors"][1:]
        )
        pairs.extend(
            ("statistic", statistic, "radius", choice)
            for statistic in ("motif_follow_through", "neighbor_dispersion")
            for choice in space["radius"][1:]
        )
        pairs.append(("statistic", "neighbor_dispersion", "neighbors", 1))
    if lane.lane_id == "F136":
        pairs.extend(
            ("statistic", "recurrence_rate", "minimum_line", choice)
            for choice in space["minimum_line"][1:]
        )
    if lane.lane_id == "F137":
        pairs.extend(
            ("statistic", statistic, parameter, choice)
            for statistic in ("hurst", "roughness", "fractal_dimension")
            for parameter in ("q_low", "q_high")
            for choice in space[parameter][1:]
        )
    if lane.lane_id == "F139":
        pairs.extend(
            ("kind", kind, "asymmetry", choice)
            for kind in ("ewma", "garch_proxy")
            for choice in space["asymmetry"][1:]
        )
        pairs.extend(
            ("statistic", "asymmetry_ratio", "asymmetry", choice)
            for choice in space["asymmetry"][1:]
        )
        pairs.extend(
            ("statistic", "asymmetry_ratio", "kind", kind)
            for kind in space["kind"][1:]
        )
        pairs.append(("kind", "asymmetric_ewma", "asymmetry", 0.0))
    if lane.lane_id == "F140":
        pairs.extend(
            ("kind", kind, "transition_speed", choice)
            for kind in ("setar", "observable_threshold")
            for choice in space["transition_speed"][1:]
        )
        pairs.extend(
            ("statistic", statistic, "kind", kind)
            for statistic in ("regime_state", "regime_spread")
            for kind in space["kind"][1:]
        )
        pairs.append(
            (
                "statistic",
                "transition_probability",
                "kind",
                "observable_threshold",
            )
        )
        pairs.append(("regimes", 3, "threshold_quantile", 0.5))
    if lane.lane_id == "F141":
        pairs.extend(
            ("kind", kind, "ma_order", choice)
            for kind in ("ar", "distributed_regression")
            for choice in space["ma_order"][1:]
        )
        pairs.extend(
            ("kind", kind, "volume_lags", choice)
            for kind in ("ar", "arma")
            for choice in space["volume_lags"][1:]
        )
        pairs.append(("kind", "arma", "ma_order", 0))
        pairs.extend(
            ("statistic", "innovation", "kind", kind)
            for kind in ("ar", "distributed_regression")
        )
    if lane.lane_id == "F142":
        pairs.append(("statistic", "error_correction", "kind", "var"))
        pairs.append(("statistic", "common_state", "kind", "vecm"))
        pairs.extend(
            ("statistic", "error_correction", "lags", choice)
            for choice in space["lags"][1:]
        )
        pairs.extend(
            ("statistic", statistic, "ridge", choice)
            for statistic in ("common_state", "error_correction")
            for choice in space["ridge"][1:]
        )
    if lane.lane_id == "F143":
        pairs.extend(
            ("statistic", statistic, "sign_rule", "trend_anchor")
            for statistic in (
                "explained_share",
                "common_direction",
                "idiosyncratic_dispersion",
            )
        )
    if lane.lane_id == "F144":
        pairs.extend(
            ("statistic", statistic, "forecast_quantile", choice)
            for statistic in (
                "tail_probability",
                "interquantile_range",
                "median_skew",
            )
            for choice in space["forecast_quantile"][1:]
        )
        pairs.extend(
            ("statistic", "quantile_forecast", "tail_quantile", choice)
            for choice in space["tail_quantile"][1:]
        )
    if lane.lane_id == "F145":
        pairs.extend(
            ("kind", "linear", parameter, choice)
            for parameter in ("gamma", "degree")
            for choice in space[parameter][1:]
        )
        pairs.extend(
            ("kind", "rbf", "degree", choice)
            for choice in space["degree"][1:]
        )
    if lane.lane_id == "F149":
        pairs.extend(
            ("statistic", statistic, "ridge", choice)
            for statistic in ("state_energy", "memory_alignment")
            for choice in space["ridge"][1:]
        )
    if lane.lane_id == "F150":
        pairs.extend(
            ("kind", "attention", parameter, choice)
            for parameter in ("experts", "gate")
            for choice in space[parameter][1:]
        )
        pairs.extend(
            ("kind", "moe", "temperature", choice)
            for choice in space["temperature"][1:]
        )
        pairs.append(("statistic", "attention_entropy", "kind", "moe"))
        pairs.append(("statistic", "expert_disagreement", "kind", "attention"))
        pairs.extend(
            ("statistic", "attention_entropy", "ridge", choice)
            for choice in space["ridge"][1:]
        )
    if lane.lane_id in {"F161", "F170"}:
        pairs.extend(
            ("mode", mode, "threshold", choice)
            for mode in ("change", "divergence")
            for choice in space["threshold"][1:]
        )
        pairs.extend(
            ("mode", mode, "change_lag", choice)
            for mode in ("level", "divergence")
            for choice in space["change_lag"][1:]
        )
    if lane.lane_id in {"F162", "F169"}:
        pairs.extend(
            ("aggregation", aggregation, "selection_fraction", choice)
            for aggregation in ("breadth", "rank")
            for choice in space["selection_fraction"][1:]
        )
    if lane.lane_id == "F165":
        pairs.extend(
            ("window", window, "short_window", short)
            for window in space["window"]
            for short in space["short_window"]
            if int(short) >= int(window)
        )
        pairs.extend(
            ("statistic", statistic, "short_window", choice)
            for statistic in (
                "dispersion",
                "sign_disagreement",
                "mean_correlation",
            )
            for choice in space["short_window"][1:]
        )
    if lane.lane_id == "F171":
        pairs.extend(
            ("statistic", statistic, "threshold", threshold)
            for statistic in (
                "official_broad",
                "cross_mean",
                "divergence",
                "dispersion",
            )
            for threshold in space["threshold"][1:]
        )
    if lane.lane_id == "F172":
        pairs.extend(
            ("statistic", statistic, "window", window)
            for statistic in ("cash_level", "offshore_basis", "carry_pressure")
            for window in space["window"][1:]
        )
    if lane.lane_id == "F173":
        pairs.extend(
            ("aggregation", aggregation, "selection_fraction", fraction)
            for aggregation in ("breadth", "rank")
            for fraction in space["selection_fraction"][1:]
        )
    if lane.lane_id in {"F174", "F176"}:
        pairs.extend(
            ("statistic", "level", "window", window)
            for window in space["window"][1:]
        )
        pairs.extend(
            ("statistic", statistic, "normalization_window", window)
            for statistic in ("momentum", "breadth")
            for window in space["normalization_window"][1:]
        )
        pairs.extend(
            ("statistic", statistic, "threshold", threshold)
            for statistic in ("level", "momentum")
            for threshold in space["threshold"][1:]
        )
    if lane.lane_id == "F177":
        pairs.extend(
            ("statistic", statistic, "threshold", threshold)
            for statistic in ("dispersion", "inflation_pressure", "concentration")
            for threshold in space["threshold"][1:]
        )
    if lane.lane_id == "F178":
        pairs.extend(
            ("statistic", "sign_breadth", "normalization_window", window)
            for window in space["normalization_window"][1:]
        )
    if lane.lane_id == "F179":
        pairs.extend(
            ("normalization", "raw", "z_window", window)
            for window in space["z_window"][1:]
        )
    if lane.lane_id == "F180":
        pairs.extend(
            ("statistic", statistic, "long_window", window)
            for statistic in ("correlation", "beta")
            for window in space["long_window"][1:]
        )
    if lane.lane_id == "F181":
        pairs.extend(
            ("normalization", normalization, "window", window)
            for normalization in ("raw", "change")
            for window in space["window"][1:]
        )
        pairs.extend(
            ("normalization", normalization, "change_lag", lag)
            for normalization in ("raw", "rolling_zscore")
            for lag in space["change_lag"][1:]
        )
    if lane.lane_id == "F182":
        pairs.extend(
            ("normalization", normalization, "window", window)
            for normalization in ("raw", "change")
            for window in space["window"][1:]
        )
        pairs.extend(
            ("normalization", normalization, "change_lag", lag)
            for normalization in ("raw", "rolling_zscore")
            for lag in space["change_lag"][1:]
        )
        pairs.extend(
            ("statistic", statistic, "shock_lag", lag)
            for statistic in (
                "forward_2y5y",
                "forward_5y10y",
                "forward_slope",
                "butterfly",
            )
            for lag in space["shock_lag"][1:]
        )
    if lane.lane_id == "F183":
        pairs.extend(
            ("statistic", statistic, "window", window)
            for statistic in ("level", "dispersion")
            for window in space["window"][1:]
        )
        pairs.extend(
            ("statistic", "dispersion", "inflation_basis", basis)
            for basis in space["inflation_basis"][1:]
        )
    if lane.lane_id == "F184":
        pairs.extend(
            ("normalization", normalization, "change_lag", lag)
            for normalization in ("raw", "rolling_zscore")
            for lag in space["change_lag"][1:]
        )
    if lane.lane_id == "F185":
        pairs.extend(
            ("statistic", statistic, "lag", lag)
            for statistic in (
                "quality_spread",
                "financial_spread",
                "issuance_intensity",
            )
            for lag in space["lag"][1:]
        )
        pairs.extend(
            ("normalization", normalization, "change_lag", lag)
            for normalization in ("raw", "rolling_zscore")
            for lag in space["change_lag"][1:]
        )
    if lane.lane_id == "F186":
        pairs.extend(
            ("statistic", "loan_share", "lag", lag)
            for lag in space["lag"][1:]
        )
        pairs.extend(
            ("normalization", normalization, "window", window)
            for normalization in ("raw", "change")
            for window in space["window"][1:]
        )
        pairs.extend(
            ("normalization", normalization, "change_lag", lag)
            for normalization in ("raw", "rolling_zscore")
            for lag in space["change_lag"][1:]
        )
    if lane.lane_id == "F187":
        pairs.extend(
            ("statistic", statistic, "lag", lag)
            for statistic in (
                "liquid_share",
                "borrowing_pressure",
                "credit_money_ratio",
            )
            for lag in space["lag"][1:]
        )
        pairs.extend(
            ("normalization", normalization, "window", window)
            for normalization in ("raw", "change")
            for window in space["window"][1:]
        )
        pairs.extend(
            ("normalization", normalization, "change_lag", lag)
            for normalization in ("raw", "rolling_zscore")
            for lag in space["change_lag"][1:]
        )
    if lane.lane_id == "F188":
        pairs.extend(
            ("statistic", "revolving_share", "lag", lag)
            for lag in space["lag"][1:]
        )
        pairs.extend(
            ("normalization", normalization, "change_lag", lag)
            for normalization in ("raw", "rolling_zscore")
            for lag in space["change_lag"][1:]
        )
    if lane.lane_id == "F190":
        pairs.extend(
            ("statistic", statistic, "threshold", threshold)
            for statistic in ("joint_mean", "joint_max", "triple_interaction")
            for threshold in space["threshold"][1:]
        )
    if lane.lane_id in {"F191", "F192", "F194", "F200"}:
        pairs.extend(
            ("normalization", normalization, "window", window)
            for normalization in ("raw", "change")
            for window in space["window"][1:]
        )
    if lane.lane_id in {
        "F191",
        "F192",
        "F193",
        "F194",
        "F195",
        "F196",
        "F197",
        "F198",
        "F199",
        "F200",
    }:
        pairs.extend(
            ("normalization", normalization, "change_lag", lag)
            for normalization in ("raw", "rolling_zscore")
            for lag in space["change_lag"][1:]
        )
    if lane.lane_id == "F193":
        pairs.extend(
            ("statistic", statistic, "lag", lag)
            for statistic in (
                "nonresidential_investment",
                "residential_investment",
                "housing_starts",
                "revision_composite",
            )
            for lag in space["lag"][1:]
        )
    if lane.lane_id == "F196":
        pairs.extend(
            ("statistic", statistic, "lag", lag)
            for statistic in (
                "industrial_production",
                "manufacturing_production",
                "capacity_utilization",
                "manufacturing_capacity",
                "utilization_spread",
                "revision_composite",
            )
            for lag in space["lag"][1:]
        )
    if lane.lane_id in {"F205", "F206", "F207"}:
        pairs.extend(
            ("normalization", normalization, "window", window)
            for normalization in ("raw", "change")
            for window in space["window"][1:]
        )
    if lane.lane_id in {
        "F202",
        "F203",
        "F205",
        "F206",
        "F207",
        "F208",
        "F209",
        "F210",
    }:
        pairs.extend(
            ("normalization", normalization, "change_lag", lag)
            for normalization in ("raw", "rolling_zscore")
            for lag in space["change_lag"][1:]
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
    if lane.lane_id == "F101":
        pairs.extend(
            ("statistic", statistic, "window", window)
            for statistic in ("earnings_news", "dividend_news")
            for window in space["window"][1:]
        )
    if lane.lane_id == "F102":
        pairs.extend(
            ("statistic", statistic, "window", window)
            for statistic in (
                "earnings_momentum",
                "earnings_yield_change",
                "acceleration",
            )
            for window in space["window"][1:]
        )
    if lane.lane_id == "F103":
        pairs.extend(
            ("statistic", statistic, "window", window)
            for statistic in ("earnings_growth", "dividend_growth", "payout_change")
            for window in space["window"][1:]
        )
    if lane.lane_id == "F104":
        pairs.extend(
            ("statistic", "market_issuance", "change_lag", lag)
            for lag in space["change_lag"][1:]
        )
    if lane.lane_id == "F105":
        pairs.extend(
            ("statistic", "funding_stress", "growth_lag", lag)
            for lag in space["growth_lag"][1:]
        )
    if lane.lane_id == "F106":
        pairs.extend(
            ("statistic", statistic, "persistence_window", window)
            for statistic in (
                "uncertainty_level",
                "stress_composite",
                "disagreement",
            )
            for window in space["persistence_window"][1:]
        )
    if lane.lane_id == "F108":
        pairs.extend(
            ("statistic", "activity_state", "trend_window", window)
            for window in space["trend_window"][1:]
        )
    if lane.lane_id == "F110":
        pairs.extend(
            ("statistic", "oil_gold_ratio", parameter, choice)
            for parameter in ("window", "momentum_lag")
            for choice in space[parameter][1:]
        )
        pairs.extend(
            ("statistic", "relative_momentum", "window", window)
            for window in space["window"][1:]
        )
    if lane.lane_id == "F113":
        pairs.extend(
            ("statistic", statistic, "momentum_lag", lag)
            for statistic in ("stock_bond_correlation", "joint_shock")
            for lag in space["momentum_lag"][1:]
        )
        pairs.extend(
            ("statistic", statistic, "window", window)
            for statistic in ("curve_momentum", "duration_momentum")
            for window in space["window"][1:]
        )
    if lane.lane_id == "F115":
        pairs.extend(
            ("statistic", "dispersion", "window", window)
            for window in space["window"][1:]
        )
    if lane.lane_id == "F116":
        pairs.extend(
            ("statistic", "common_mode", "window", window)
            for window in space["window"][1:]
        )
    if lane.lane_id == "F117":
        pairs.extend(
            ("statistic", statistic, "change_lag", lag)
            for statistic in ("breadth", "divergence")
            for lag in space["change_lag"][1:]
        )
    if lane.lane_id == "F118":
        pairs.extend(
            ("statistic", "industry_state", "growth_lag", lag)
            for lag in space["growth_lag"][1:]
        )
    return tuple(pairs)


def _forbidden_parameter_triplets(
    lane: FeatureLaneSpec,
) -> tuple[tuple[str, Any, str, Any, str, Any], ...]:
    triplets: list[tuple[str, Any, str, Any, str, Any]] = []
    space = lane.parameter_space
    if lane.lane_id == "F148":
        triplets.extend(
            ("sequence", sequence, "kernel", kernel, "dilation", dilation)
            for sequence in space["sequence"]
            for kernel in space["kernel"]
            for dilation in space["dilation"]
            if (int(kernel) - 1) * int(dilation) >= int(sequence)
        )
    if lane.lane_id == "F169":
        universe_sizes = {
            "regions_only": 3,
            "developed_ex_us_plus_regions": 4,
            "all_available": 5,
        }
        for aggregation in ("mean", "median"):
            for universe, count in universe_sizes.items():
                effective_counts: set[int] = set()
                for fraction in space["selection_fraction"]:
                    effective = math.ceil(count * float(fraction))
                    if effective in effective_counts:
                        triplets.append(
                            (
                                "aggregation",
                                aggregation,
                                "universe",
                                universe,
                                "selection_fraction",
                                fraction,
                            )
                        )
                    else:
                        effective_counts.add(effective)
    if lane.lane_id == "F180":
        triplets.extend(
            (
                "statistic",
                statistic,
                "window",
                window,
                "long_window",
                long_window,
            )
            for statistic in ("decoupling", "sign_change")
            for window in space["window"]
            for long_window in space["long_window"]
            if int(long_window) <= int(window)
        )
    if lane.lane_id in {"F184", "F185", "F188"}:
        simple_statistics = {
            "F184": ("baa_aaa", "aaa_treasury", "baa_treasury"),
            "F185": (
                "quality_spread",
                "financial_spread",
                "outstanding_contraction",
                "issuance_intensity",
            ),
            "F188": (
                "total_growth",
                "revolving_growth",
                "revolving_share",
                "revolving_relative_growth",
            ),
        }
        triplets.extend(
            (
                "statistic",
                statistic,
                "normalization",
                normalization,
                "window",
                window,
            )
            for statistic in simple_statistics[lane.lane_id]
            for normalization in ("raw", "change")
            for window in space["window"][1:]
        )
    if lane.lane_id in {"F193", "F195", "F196", "F197", "F198", "F199"}:
        simple_statistics = {
            "F193": (
                "nonresidential_investment",
                "residential_investment",
                "housing_starts",
                "housing_starts_change",
                "investment_breadth",
            ),
            "F195": (
                "payroll_first",
                "payroll_revision",
                "unemployment_level",
                "unemployment_change",
                "labor_breadth",
            ),
            "F196": (
                "industrial_production",
                "manufacturing_production",
                "capacity_utilization",
                "manufacturing_capacity",
                "utilization_spread",
                "production_breadth",
            ),
            "F197": (
                "output_nowcast",
                "output_next_forecast",
                "unemployment_nowcast",
                "cpi_nowcast",
                "housing_nowcast",
                "tbill_nowcast",
            ),
            "F198": (
                "ngdp_iqr",
                "unemployment_iqr",
                "cpi_iqr",
                "housing_iqr",
                "tbill_iqr",
            ),
            "F199": (
                "forecast_revision",
                "nowcast_signed_error",
                "nowcast_absolute_error",
                "prior_signed_error",
                "prior_absolute_error",
            ),
        }
        triplets.extend(
            (
                "statistic",
                statistic,
                "normalization",
                normalization,
                "window",
                window,
            )
            for statistic in simple_statistics[lane.lane_id]
            for normalization in ("raw", "change")
            for window in space["window"][1:]
        )
    if lane.lane_id in {"F201", "F202", "F203", "F204", "F208", "F209", "F210"}:
        simple_statistics = {
            "F201": (
                "household_equity_share",
                "household_liquid_share",
                "equity_liquidity_ratio",
                "equity_share_change",
            ),
            "F202": (
                "household_leverage",
                "liquid_assets_to_liabilities",
                "liabilities_growth",
                "liquidity_growth",
            ),
            "F203": (
                "corporate_leverage",
                "corporate_liquid_share",
                "corporate_debt_share",
                "corporate_liquidity_change",
            ),
            "F204": (
                "corporate_net_issuance",
                "issuance_to_assets",
                "issuance_change",
            ),
            "F208": (
                "broker_leverage",
                "repo_funding_share",
                "repo_asset_share",
                "broker_assets_growth",
            ),
            "F209": (
                "tic_treasury_flow",
                "tic_equity_flow",
                "tic_total_flow",
                "z1_foreign_flow",
                "equity_treasury_divergence",
            ),
            "F210": (
                "household_to_fund",
                "fund_to_broker",
                "broker_to_business",
            ),
        }
        triplets.extend(
            (
                "statistic",
                statistic,
                "normalization",
                normalization,
                "window",
                window,
            )
            for statistic in simple_statistics[lane.lane_id]
            for normalization in ("raw", "change")
            for window in space["window"][1:]
        )
    if lane.lane_id in {"F201", "F204"}:
        simple_statistics = {
            "F201": (
                "household_equity_share",
                "household_liquid_share",
                "equity_liquidity_ratio",
                "risk_appetite",
            ),
            "F204": (
                "corporate_net_issuance",
                "issuance_to_assets",
                "issuance_pressure",
            ),
        }
        triplets.extend(
            (
                "statistic",
                statistic,
                "normalization",
                normalization,
                "change_lag",
                lag,
            )
            for statistic in simple_statistics[lane.lane_id]
            for normalization in ("raw", "rolling_zscore")
            for lag in space["change_lag"][1:]
        )
    return tuple(triplets)


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
        forbidden_triplets = _forbidden_parameter_triplets(lane)
        forbidden_clauses = [
            module.ForbiddenAndConjunction(
                module.ForbiddenEqualsClause(space[left_name], left_value),
                module.ForbiddenEqualsClause(space[right_name], right_value),
            )
            for left_name, left_value, right_name, right_value in forbidden_pairs
        ]
        forbidden_clauses.extend(
            module.ForbiddenAndConjunction(
                module.ForbiddenEqualsClause(space[first_name], first_value),
                module.ForbiddenEqualsClause(space[second_name], second_value),
                module.ForbiddenEqualsClause(space[third_name], third_value),
            )
            for (
                first_name,
                first_value,
                second_name,
                second_value,
                third_name,
                third_value,
            ) in forbidden_triplets
        )
        if forbidden_clauses:
            space.add(forbidden_clauses)
    except (AttributeError, TypeError, ValueError) as exc:
        raise DehbConfigSpaceError(f"CONFIGSPACE_BUILD_FAILED:{lane_id}:{exc}") from exc
    return LaneConfigSpace(
        lane_id=lane.lane_id,
        seed=int(seed),
        dimensions=tuple(lane.parameter_space),
        canonical_sha256=lane.canonical_sha256,
        forbidden_configuration_count=len(forbidden_pairs) + len(forbidden_triplets),
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
            "forbidden_parameter_triplets": [
                [
                    first_name,
                    first_value,
                    second_name,
                    second_value,
                    third_name,
                    third_value,
                ]
                for (
                    first_name,
                    first_value,
                    second_name,
                    second_value,
                    third_name,
                    third_value,
                ) in _forbidden_parameter_triplets(lane)
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
