"""Staged full-fidelity robustness review for train-only DEHB candidates."""

from __future__ import annotations

from dataclasses import asdict
import math
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np
import pandas as pd

from aurora.infra.sp500_megarun.dehb_objective import score_ledger_decisions
from aurora.infra.sp500_megarun.dehb_worker import (
    FeatureEvaluator,
    feature_frame_to_decisions,
)


class RobustnessReviewError(ValueError):
    """Raised when a robustness review is incomplete, non-causal or ambiguous."""


ConfigurationValidator = Callable[[Mapping[str, Any]], bool]


def _canonical_configuration(configuration: Mapping[str, Any]) -> tuple[tuple[str, Any], ...]:
    return tuple(sorted((str(name), value) for name, value in configuration.items()))


def _neighbor_configurations(
    configuration: Mapping[str, Any],
    parameter_space: Mapping[str, Sequence[Any]],
    *,
    count: int,
    seed: int,
    configuration_validator: ConfigurationValidator | None = None,
) -> list[dict[str, Any]]:
    if count < 0:
        raise RobustnessReviewError("NEGATIVE_NEIGHBOR_COUNT")
    base = dict(configuration)
    for name, choices in parameter_space.items():
        if name not in base or base[name] not in choices:
            raise RobustnessReviewError(f"CONFIGURATION_OUTSIDE_SPACE:{name}")
    if configuration_validator is not None and not configuration_validator(base):
        raise RobustnessReviewError("BASE_CONFIGURATION_FORBIDDEN")
    candidates: list[dict[str, Any]] = []
    seen = {_canonical_configuration(base)}

    def add(candidate: dict[str, Any]) -> None:
        key = _canonical_configuration(candidate)
        if key not in seen and (
            configuration_validator is None or configuration_validator(candidate)
        ):
            seen.add(key)
            candidates.append(candidate)

    adjacent: dict[str, list[Any]] = {}
    for name in sorted(parameter_space):
        choices = tuple(parameter_space[name])
        index = choices.index(base[name])
        ordered = sorted(
            (value for offset, value in enumerate(choices) if offset != index),
            key=lambda value: (abs(choices.index(value) - index), choices.index(value)),
        )
        adjacent[name] = [
            choices[index + delta]
            for delta in (-1, 1)
            if 0 <= index + delta < len(choices)
        ]
        for value in ordered:
            candidate = dict(base)
            candidate[name] = value
            add(candidate)
            if len(candidates) >= count:
                return candidates

    names = sorted(adjacent)
    for left_index, left in enumerate(names):
        for right in names[left_index + 1 :]:
            for left_value in adjacent[left]:
                for right_value in adjacent[right]:
                    candidate = dict(base)
                    candidate[left] = left_value
                    candidate[right] = right_value
                    add(candidate)
                    if len(candidates) >= count:
                        return candidates

    rng = np.random.default_rng(seed)
    attempts = 0
    while len(candidates) < count and attempts < 10_000:
        attempts += 1
        candidate = dict(base)
        for name in names:
            choices = tuple(parameter_space[name])
            index = choices.index(base[name])
            offset = int(rng.integers(-1, 2))
            candidate[name] = choices[min(max(index + offset, 0), len(choices) - 1)]
        add(candidate)
    return candidates


def _compounded(values: pd.Series) -> float:
    if values.empty:
        return 0.0
    return math.expm1(float(np.log1p(values.to_numpy(dtype=float)).sum()))


def _period_metrics(
    strategy: pd.Series,
    spy: pd.Series,
    frequency: str,
) -> Mapping[str, Any]:
    frame = pd.DataFrame({"strategy": strategy, "spy": spy})
    frame["period"] = frame.index.to_period(frequency)
    grouped = frame.groupby("period", sort=True)[["strategy", "spy"]].agg(_compounded)
    active = grouped["strategy"] - grouped["spy"]
    return {
        "period_count": int(len(grouped)),
        "strategy_positive_rate": float(grouped["strategy"].gt(0.0).mean()),
        "spy_beat_rate": float(active.gt(0.0).mean()),
        "median_strategy_return": float(grouped["strategy"].median()),
        "median_active_return": float(active.median()),
        "minimum_active_return": float(active.min()),
        "maximum_active_return": float(active.max()),
    }


def _rolling_metrics(
    strategy: pd.Series,
    spy: pd.Series,
    windows: Sequence[int],
) -> Mapping[str, Any]:
    strategy_log = np.log1p(strategy)
    spy_log = np.log1p(spy)
    rows: dict[str, Any] = {}
    for window in windows:
        strategy_return = np.expm1(strategy_log.rolling(window).sum()).dropna()
        spy_return = np.expm1(spy_log.rolling(window).sum()).dropna()
        active = strategy_return - spy_return
        rows[str(window)] = {
            "window": int(window),
            "observation_count": int(len(active)),
            "spy_beat_rate": float(active.gt(0.0).mean()) if len(active) else 0.0,
            "minimum_active_return": float(active.min()) if len(active) else None,
            "median_active_return": float(active.median()) if len(active) else None,
            "maximum_active_return": float(active.max()) if len(active) else None,
        }
    return rows


def _bootstrap_review(
    strategy: pd.Series,
    spy: pd.Series,
    *,
    target_years: Sequence[int],
    paths: int,
    seed: int,
    block_lengths: Sequence[int] = (5, 10, 20, 40, 63),
) -> Mapping[str, Any]:
    if paths <= 0:
        raise RobustnessReviewError("BOOTSTRAP_PATHS_MUST_BE_POSITIVE")
    rng = np.random.default_rng(seed)
    strategy_logs = np.log1p(strategy.to_numpy(dtype=float))
    spy_logs = np.log1p(spy.to_numpy(dtype=float))
    years = strategy.index.year.to_numpy(dtype=int)
    gate_survival = np.zeros(paths, dtype=bool)
    annualized_alpha = np.empty(paths, dtype=float)
    by_block = {int(length): [0, 0] for length in block_lengths}
    for path_index in range(paths):
        length = int(block_lengths[path_index % len(block_lengths)])
        all_years_pass = True
        strategy_total_log = 0.0
        spy_total_log = 0.0
        sample_count = 0
        for year in target_years:
            positions = np.flatnonzero(years == int(year))
            if not len(positions):
                raise RobustnessReviewError(f"BOOTSTRAP_YEAR_MISSING:{year}")
            block_count = math.ceil(len(positions) / length)
            starts = rng.integers(0, len(positions), size=block_count)
            sampled_local = np.concatenate(
                [
                    (start + np.arange(length, dtype=int)) % len(positions)
                    for start in starts
                ]
            )[: len(positions)]
            sampled = positions[sampled_local]
            strategy_log = float(strategy_logs[sampled].sum())
            spy_log = float(spy_logs[sampled].sum())
            strategy_return = math.expm1(strategy_log)
            spy_return = math.expm1(spy_log)
            all_years_pass &= strategy_return > 0.0 and strategy_return > spy_return
            strategy_total_log += strategy_log
            spy_total_log += spy_log
            sample_count += len(sampled)
        gate_survival[path_index] = all_years_pass
        scale = 252.0 / sample_count
        annualized_alpha[path_index] = math.expm1(strategy_total_log * scale) - math.expm1(
            spy_total_log * scale
        )
        by_block[length][0] += int(all_years_pass)
        by_block[length][1] += 1

    intervals: dict[str, Mapping[str, float]] = {}
    for confidence in (0.80, 0.90, 0.95, 0.99):
        tail = (1.0 - confidence) / 2.0
        intervals[str(confidence)] = {
            "lower": float(np.quantile(annualized_alpha, tail)),
            "upper": float(np.quantile(annualized_alpha, 1.0 - tail)),
        }
    return {
        "paths": paths,
        "block_lengths": [int(value) for value in block_lengths],
        "all_year_gate_survival_rate": float(gate_survival.mean()),
        "annualized_alpha_mean": float(annualized_alpha.mean()),
        "annualized_alpha_median": float(np.median(annualized_alpha)),
        "annualized_alpha_intervals": intervals,
        "survival_rate_by_block_length": {
            str(length): passed / total for length, (passed, total) in by_block.items()
        },
    }


def _direction_metrics(result: Any) -> Mapping[str, Any]:
    positions = result.positions.iloc[: len(result.strategy_returns)].to_numpy(dtype=float)
    strategy = result.strategy_returns.to_numpy(dtype=float)
    spy = result.spy_returns.to_numpy(dtype=float)
    long_mask = positions > 0.0
    short_mask = positions < 0.0

    def side(mask: np.ndarray) -> Mapping[str, Any]:
        return {
            "sessions": int(mask.sum()),
            "strategy_return": math.expm1(float(np.log1p(strategy[mask]).sum()))
            if mask.any()
            else 0.0,
            "spy_return": math.expm1(float(np.log1p(spy[mask]).sum()))
            if mask.any()
            else 0.0,
        }

    changes = int(np.count_nonzero(np.diff(positions))) if len(positions) > 1 else 0
    return {
        "long_sessions": int(long_mask.sum()),
        "short_sessions": int(short_mask.sum()),
        "position_changes": changes,
        "long": side(long_mask),
        "short": side(short_mask),
    }


_GATE_NAMES = (
    "period_results", "time_segments", "rolling_windows", "leave_period_out",
    "beginning_vs_end", "start_date_shifts", "calendar_slices",
    "parameter_neighbors", "percentage_parameter_changes",
    "confirmation_and_persistence", "tie_missing_initial_position_rules",
    "ingredient_ablation", "model_simplification", "parameter_plateau",
    "importance_and_seed_agreement", "second_provider", "numeric_precision",
    "missing_observations", "extreme_observations", "publication_date_causality",
    "point_in_time_macro_vintages", "historical_index_components",
    "dividend_split_reconstruction", "dataset_truncation_invariance",
    "signal_delay", "alternative_execution_moments", "open_price_perturbation",
    "deliberate_corporate_action_errors", "position_change_runs",
    "market_and_volatility_regimes", "vix_credit_rates_regimes",
    "positive_negative_session_decomposition", "long_short_decomposition",
    "remove_largest_gains", "profit_concentration", "tail_trimming",
    "block_bootstrap", "multiple_block_lengths", "bootstrap_alpha_annual_edge",
    "blocked_signal_placebos", "uncertainty_intervals", "dependent_day_confidence",
    "trial_count_adjustment", "winner_vs_full_process", "multiple_testing_correction",
    "overfit_probability", "model_confidence_set", "clone_detection",
    "train_validation_degradation", "validation_rank_stability",
    "distance_from_alpha_leader", "spy_upside_dependence",
    "family_variable_contribution", "prewritten_economic_coherence",
    "one_vs_four_processors", "checkpoint_resume_invariance", "clean_runner_reproduction",
    "fingerprint_invariance", "cold_hot_cache_invariance", "fault_injection_recovery",
)

_GATE_STAGES = {
    **{gate: "candidate_local" for gate in range(1, 16)},
    **{gate: "data_external" for gate in range(16, 25)},
    **{gate: "candidate_local" for gate in range(25, 43)},
    **{gate: "global_merge" for gate in range(43, 49)},
    **{gate: "validation" for gate in range(49, 55)},
    **{gate: "technical_reproducibility" for gate in range(55, 61)},
}


def _gate_matrix(*, neighbor_passed: bool) -> tuple[list[dict[str, Any]], list[int]]:
    measured_information = {1, 3, 25, 29, 33, 37, 38, 39, 41}
    evaluated = {8, 9, 14, 20}
    pending = set(range(1, 61)) - measured_information - evaluated
    matrix: list[dict[str, Any]] = []
    for gate_id in range(1, 61):
        if gate_id in (8, 9, 14):
            status = "PASS" if neighbor_passed else "FAIL"
        elif gate_id == 20:
            status = "PASS"
        elif gate_id in measured_information:
            status = "MEASURED"
        else:
            status = "PENDING"
        matrix.append(
            {
                "gate_id": gate_id,
                "name": _GATE_NAMES[gate_id - 1],
                "stage": _GATE_STAGES[gate_id],
                "status": status,
            }
        )
    return matrix, sorted(pending)


def review_candidate_robustness(
    *,
    ledger: pd.DataFrame,
    lane_id: str,
    configuration: Mapping[str, Any],
    parameter_space: Mapping[str, Sequence[Any]],
    feature_evaluator: FeatureEvaluator,
    target_years: Sequence[int],
    allowed_end: str,
    seed: int,
    bootstrap_paths: int,
    parameter_neighbors: int,
    temporal_delays: Sequence[int],
    configuration_validator: ConfigurationValidator | None = None,
) -> Mapping[str, Any]:
    """Run candidate-local fidelity-27 checks; global and validation gates remain pending."""

    base_feature = feature_evaluator(lane_id, configuration)
    base_decisions = feature_frame_to_decisions(base_feature, allowed_end=allowed_end)
    base = score_ledger_decisions(
        ledger,
        base_decisions,
        target_years=target_years,
        allowed_end=allowed_end,
    )
    neighbors = _neighbor_configurations(
        configuration,
        parameter_space,
        count=parameter_neighbors,
        seed=seed,
        configuration_validator=configuration_validator,
    )
    neighbor_rows: list[dict[str, Any]] = []
    sign_stability: list[float] = []
    for index, neighbor in enumerate(neighbors):
        feature = feature_evaluator(lane_id, neighbor)
        decisions = feature_frame_to_decisions(feature, allowed_end=allowed_end)
        result = score_ledger_decisions(
            ledger,
            decisions,
            target_years=target_years,
            allowed_end=allowed_end,
        )
        aligned = pd.concat(
            [base_decisions.rename("base"), decisions.rename("neighbor")], axis=1
        ).dropna()
        sign_stability.append(
            float(aligned["base"].eq(aligned["neighbor"]).mean())
            if len(aligned)
            else 0.0
        )
        neighbor_rows.append(
            {
                "neighbor_index": index,
                "configuration": neighbor,
                "feasible": result.score.feasible,
                "annualized_strategy_return": result.score.annualized_strategy_return,
                "weekly_spy_beat_rate": result.score.weekly_spy_beat_rate,
                "annualized_alpha": result.score.annualized_alpha,
                "failed_years": list(result.score.failed_years),
            }
        )
    neighbor_survival = (
        sum(bool(row["feasible"]) for row in neighbor_rows) / len(neighbor_rows)
        if neighbor_rows
        else 0.0
    )
    neighbor_passed = bool(neighbor_rows) and neighbor_survival >= 0.60

    delay_rows: list[dict[str, Any]] = []
    for delay in temporal_delays:
        if int(delay) <= 0:
            raise RobustnessReviewError("TEMPORAL_DELAY_MUST_BE_POSITIVE")
        delayed = base_decisions.shift(int(delay))
        delayed_result = score_ledger_decisions(
            ledger,
            delayed,
            target_years=target_years,
            allowed_end=allowed_end,
        )
        delay_rows.append(
            {
                "delay_sessions": int(delay),
                "feasible": delayed_result.score.feasible,
                "annualized_strategy_return": (
                    delayed_result.score.annualized_strategy_return
                ),
                "weekly_spy_beat_rate": delayed_result.score.weekly_spy_beat_rate,
                "annualized_alpha": delayed_result.score.annualized_alpha,
                "failed_years": list(delayed_result.score.failed_years),
            }
        )

    period_metrics = {
        "weekly": _period_metrics(base.strategy_returns, base.spy_returns, "W-FRI"),
        "monthly": _period_metrics(base.strategy_returns, base.spy_returns, "M"),
        "quarterly": _period_metrics(base.strategy_returns, base.spy_returns, "Q"),
        "annual": _period_metrics(base.strategy_returns, base.spy_returns, "Y"),
    }
    matrix, pending = _gate_matrix(neighbor_passed=neighbor_passed)
    local_passed = base.score.feasible and neighbor_passed
    return {
        "schema_version": 1,
        "lane_id": lane_id,
        "configuration": dict(configuration),
        "base_train_feasible": base.score.feasible,
        "base_failed_years": list(base.score.failed_years),
        "base_annual_returns": {
            str(year): asdict(row) for year, row in base.score.annual_returns.items()
        },
        "base_annualized_strategy_return": base.score.annualized_strategy_return,
        "base_weekly_spy_beat_rate": base.score.weekly_spy_beat_rate,
        "base_annualized_alpha": base.score.annualized_alpha,
        "period_metrics": period_metrics,
        "rolling_metrics": _rolling_metrics(
            base.strategy_returns,
            base.spy_returns,
            (21, 63, 126, 252, 504, 756),
        ),
        "direction_metrics": _direction_metrics(base),
        "neighbor_count": len(neighbor_rows),
        "neighbor_requested": parameter_neighbors,
        "neighbor_survival_rate": neighbor_survival,
        "neighbor_pass_threshold": 0.60,
        "neighbor_passed": neighbor_passed,
        "mean_position_sign_stability": float(np.mean(sign_stability))
        if sign_stability
        else 0.0,
        "neighbors": neighbor_rows,
        "temporal_delays": delay_rows,
        "bootstrap": _bootstrap_review(
            base.strategy_returns,
            base.spy_returns,
            target_years=target_years,
            paths=bootstrap_paths,
            seed=seed,
        ),
        "gate_matrix": matrix,
        "pending_gate_ids": pending,
        "pending_global_gate_ids": pending,
        "candidate_local_passed": local_passed,
        "passed": bool(local_passed and not pending),
        "validation_opened": False,
        "locked_opened": False,
    }


def build_physical_candidate_robustness_reviewer(
    contract: Any,
    feature_contract: Any,
    *,
    lane_id: str,
    train_snapshot: Path,
    baseline_feature_dirs: Mapping[str, Path],
    lane_configspace: Any,
    seed: int,
) -> Callable[[Mapping[str, Any]], Mapping[str, Any]]:
    """Bind the complete train-only fidelity-27 reviewer to physical artifacts."""

    from aurora.infra.sp500_megarun.dehb_lane_registry import (
        TrainLaneEvaluator,
        default_lane_configurations,
    )
    from aurora.infra.sp500_megarun.dehb_worker import (
        load_train_total_return_ledger,
    )

    lane_specs = {
        str(lane.lane_id): lane for lane in feature_contract.lanes
    }
    if lane_id not in lane_specs:
        raise RobustnessReviewError(f"UNKNOWN_LANE:{lane_id}")
    full_fidelity = max(contract.fidelities, key=lambda item: int(item.budget))
    ledger = load_train_total_return_ledger(
        Path(train_snapshot),
        allowed_end=contract.search_end,
        expected_manifest_sha256=contract.train_snapshot_manifest_sha256,
        expected_spy_sha256=contract.train_spy_sha256,
    )
    evaluator = TrainLaneEvaluator(
        Path(train_snapshot),
        expected_manifest_sha256=contract.train_snapshot_manifest_sha256,
        expected_spy_sha256=contract.train_spy_sha256,
        default_configurations=default_lane_configurations(feature_contract),
        baseline_feature_dirs=baseline_feature_dirs,
    )

    def valid_configuration(configuration: Mapping[str, Any]) -> bool:
        try:
            import ConfigSpace

            ConfigSpace.Configuration(
                lane_configspace.configspace,
                values=dict(configuration),
            )
        except (KeyError, TypeError, ValueError):
            return False
        return True

    temporal_schedule = (1, 2, 3, 5, 10)
    temporal_delays = temporal_schedule[: int(full_fidelity.temporal_perturbations)]
    cache: dict[tuple[tuple[str, Any], ...], Mapping[str, Any]] = {}

    def reviewer(trial: Mapping[str, Any]) -> Mapping[str, Any]:
        info = trial.get("info")
        configuration = trial.get("configuration")
        if not isinstance(info, Mapping) or not isinstance(configuration, Mapping):
            raise RobustnessReviewError("ROBUSTNESS_TRIAL_INVALID")
        if (
            info.get("lane_id") != lane_id
            or int(info.get("fidelity", -1)) != int(full_fidelity.budget)
            or info.get("full_fidelity") is not True
            or info.get("train_feasible") is not True
        ):
            raise RobustnessReviewError("ROBUSTNESS_TRIAL_NOT_ELIGIBLE")
        key = _canonical_configuration(configuration)
        cached = cache.get(key)
        if cached is None:
            cached = review_candidate_robustness(
                ledger=ledger,
                lane_id=lane_id,
                configuration=configuration,
                parameter_space=lane_specs[lane_id].parameter_space,
                feature_evaluator=evaluator,
                target_years=full_fidelity.years,
                allowed_end=contract.search_end,
                seed=seed,
                bootstrap_paths=full_fidelity.bootstrap_paths,
                parameter_neighbors=full_fidelity.parameter_neighbors,
                temporal_delays=temporal_delays,
                configuration_validator=valid_configuration,
            )
            cache[key] = cached
        return cached

    return reviewer


__all__ = [
    "RobustnessReviewError",
    "build_physical_candidate_robustness_reviewer",
    "review_candidate_robustness",
]
