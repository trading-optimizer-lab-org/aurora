"""Multiplicity and superior-set gates for the complete DEHB search ledger."""

from __future__ import annotations

import itertools
import math
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from aurora.infra.sp500_long_short_daily.statistics import (
    _stationary_bootstrap_indices,
    reality_check_and_spa,
)


class GlobalRobustnessError(ValueError):
    """Raised when global inference omits trials or uses incompatible returns."""


def holm_adjust(pvalues: Mapping[str, float]) -> dict[str, float]:
    """Return monotone Holm family-wise adjusted p-values."""

    ordered = sorted(
        ((str(key), float(value)) for key, value in pvalues.items()),
        key=lambda item: (item[1], item[0]),
    )
    count = len(ordered)
    adjusted: dict[str, float] = {}
    running = 0.0
    for index, (key, value) in enumerate(ordered):
        running = max(running, (count - index) * value)
        adjusted[key] = min(max(running, 0.0), 1.0)
    return adjusted


def geometric_cscv_pbo(
    strategy_returns: pd.DataFrame,
    *,
    partitions: int = 16,
    max_combinations: int = 12_870,
    seed: int,
) -> Mapping[str, Any]:
    """Estimate PBO using geometric return, never Sharpe, on symmetric folds."""

    frame = strategy_returns.replace([np.inf, -np.inf], np.nan).dropna(axis=0)
    if partitions < 2 or partitions % 2:
        raise GlobalRobustnessError("PBO_PARTITIONS_MUST_BE_POSITIVE_EVEN")
    if frame.shape[1] < 2 or len(frame) < partitions:
        return {"pbo": None, "combinations": 0, "reason": "INSUFFICIENT_MATRIX"}
    if (frame <= -1.0).any(axis=None):
        raise GlobalRobustnessError("PBO_RETURN_AT_OR_BELOW_MINUS_ONE")
    blocks = [np.asarray(block, dtype=int) for block in np.array_split(np.arange(len(frame)), partitions)]
    all_combinations = list(itertools.combinations(range(partitions), partitions // 2))
    if len(all_combinations) > max_combinations:
        rng = np.random.default_rng(seed)
        chosen = np.sort(
            rng.choice(len(all_combinations), size=max_combinations, replace=False)
        )
        combinations = [all_combinations[int(index)] for index in chosen]
    else:
        combinations = all_combinations
    logs = np.log1p(frame.to_numpy(dtype=float))
    block_sums = np.vstack([logs[block].sum(axis=0) for block in blocks])
    block_counts = np.asarray([len(block) for block in blocks], dtype=float)
    total_sums = block_sums.sum(axis=0)
    total_count = float(block_counts.sum())
    logits: list[float] = []
    rank_correlations: list[float] = []
    correlation_stride = max(1, len(combinations) // 256)
    for combination_index, selected in enumerate(combinations):
        selected_array = np.asarray(selected, dtype=int)
        train_sum = block_sums[selected_array].sum(axis=0)
        train_count = float(block_counts[selected_array].sum())
        train_scores = train_sum / train_count
        test_scores = (total_sums - train_sum) / (total_count - train_count)
        winner = int(np.argmax(train_scores))
        winner_test = test_scores[winner]
        less = int(np.count_nonzero(test_scores < winner_test))
        equal = int(np.count_nonzero(test_scores == winner_test))
        average_rank = less + (equal + 1.0) / 2.0
        percentile = float(average_rank / (len(test_scores) + 1.0))
        bounded = min(max(percentile, 1e-9), 1.0 - 1e-9)
        logits.append(math.log(bounded / (1.0 - bounded)))
        if (
            combination_index % correlation_stride == 0
            and np.std(train_scores) > 0.0
            and np.std(test_scores) > 0.0
        ):
            rank_correlations.append(
                float(pd.Series(train_scores).corr(pd.Series(test_scores), method="spearman"))
            )
        elif combination_index % correlation_stride == 0:
            rank_correlations.append(0.0)
    return {
        "pbo": float(np.mean(np.asarray(logits) <= 0.0)),
        "combinations": len(logits),
        "median_logit": float(np.median(logits)),
        "median_rank_correlation": float(np.median(rank_correlations)),
        "selection_metric": "mean_log_strategy_return",
        "uses_sharpe": False,
        "reason": None,
    }


def model_confidence_set(
    strategy_returns: pd.DataFrame,
    *,
    alpha: float,
    bootstrap_samples: int,
    block_length: int,
    seed: int,
) -> Mapping[str, Any]:
    """Bootstrap range-statistic MCS over geometric-return losses."""

    frame = strategy_returns.replace([np.inf, -np.inf], np.nan).dropna(axis=0)
    if not 0.0 < alpha < 1.0 or bootstrap_samples <= 0 or block_length <= 0:
        raise GlobalRobustnessError("MCS_PARAMETER_INVALID")
    if frame.shape[1] < 2 or len(frame) < 20:
        return {
            "superior_set": list(frame.columns),
            "eliminated": [],
            "reason": "INSUFFICIENT_MATRIX",
        }
    if (frame <= -1.0).any(axis=None):
        raise GlobalRobustnessError("MCS_RETURN_AT_OR_BELOW_MINUS_ONE")
    losses = -np.log1p(frame.to_numpy(dtype=float))
    names = [str(column) for column in frame.columns]
    active = list(range(len(names)))
    eliminated: list[dict[str, Any]] = []
    rng = np.random.default_rng(seed)
    bootstrap_indices = [
        _stationary_bootstrap_indices(rng, len(frame), block_length)
        for _ in range(bootstrap_samples)
    ]
    while len(active) > 1:
        current = losses[:, active]
        means = current.mean(axis=0)
        observed_range = float(means.max() - means.min())
        centered = current - means
        bootstrap_ranges = np.asarray(
            [
                float(np.ptp(centered[indices].mean(axis=0)))
                for indices in bootstrap_indices
            ]
        )
        pvalue = float(
            (1 + np.count_nonzero(bootstrap_ranges >= observed_range))
            / (bootstrap_samples + 1)
        )
        if pvalue > alpha:
            break
        worst_local = int(np.argmax(means))
        worst = active.pop(worst_local)
        eliminated.append(
            {
                "candidate_id": names[worst],
                "pvalue_at_elimination": pvalue,
                "mean_log_loss": float(means[worst_local]),
            }
        )
    return {
        "superior_set": [names[index] for index in active],
        "eliminated": eliminated,
        "alpha": alpha,
        "bootstrap_samples": bootstrap_samples,
        "block_length": block_length,
        "loss": "negative_log_strategy_return",
        "uses_sharpe": False,
        "reason": None,
    }


def evaluate_global_robustness(
    strategy_returns: pd.DataFrame,
    spy_returns: pd.Series,
    *,
    finalist_ids: Sequence[str],
    raw_trial_count: int,
    strategy_fingerprints: Mapping[str, str],
    seed: int,
    bootstrap_samples: int = 2048,
    alpha: float = 0.05,
    maximum_pbo: float = 0.20,
) -> Mapping[str, Any]:
    """Evaluate gates 43-48 against every unique full-fidelity strategy."""

    frame = strategy_returns.sort_index().replace([np.inf, -np.inf], np.nan)
    benchmark = spy_returns.reindex(frame.index)
    common = pd.concat([frame, benchmark.rename("__spy__")], axis=1).dropna(axis=0)
    frame = common.drop(columns="__spy__")
    benchmark = common["__spy__"]
    if raw_trial_count < frame.shape[1]:
        raise GlobalRobustnessError("RAW_TRIAL_COUNT_BELOW_UNIQUE_STRATEGIES")
    if set(frame.columns) != set(strategy_fingerprints):
        raise GlobalRobustnessError("FINGERPRINT_CANDIDATE_SET_MISMATCH")
    if not set(finalist_ids) <= set(frame.columns):
        raise GlobalRobustnessError("FINALIST_OUTSIDE_GLOBAL_MATRIX")
    differentials = frame.sub(benchmark, axis=0)
    inference = reality_check_and_spa(
        differentials,
        seed=seed,
        samples=bootstrap_samples,
        block_lengths=(5, 10, 20, 40, 63),
    )
    pbo = geometric_cscv_pbo(frame, seed=seed)
    mcs = model_confidence_set(
        frame.loc[:, list(dict.fromkeys(finalist_ids))],
        alpha=alpha,
        bootstrap_samples=bootstrap_samples,
        block_length=max(2, int(round(len(frame) ** (1.0 / 3.0)))),
        seed=seed + 1,
    )
    raw_pvalues = {
        str(key): float(value)
        for key, value in inference.get("candidate_raw_pvalues", {}).items()
    }
    holm = holm_adjust(raw_pvalues)
    fdr = {
        str(key): float(value)
        for key, value in inference.get("candidate_fdr_qvalues", {}).items()
    }
    spa_candidates = {
        str(key): float(value)
        for key, value in inference.get("candidate_spa_pvalues", {}).items()
    }
    bootstrap_se = {
        str(key): float(value)
        for key, value in inference.get(
            "candidate_mean_differential_bootstrap_se", {}
        ).items()
    }
    fingerprint_groups: dict[str, list[str]] = {}
    for candidate_id, fingerprint in strategy_fingerprints.items():
        fingerprint_groups.setdefault(str(fingerprint), []).append(str(candidate_id))
    global_process_pass = (
        inference.get("white_reality_check_pvalue") is not None
        and inference.get("hansen_spa_pvalue") is not None
        and float(inference["white_reality_check_pvalue"]) <= alpha
        and float(inference["hansen_spa_pvalue"]) <= alpha
        and pbo.get("pbo") is not None
        and float(pbo["pbo"]) <= maximum_pbo
    )
    finalist_rows = {}
    superior = set(mcs["superior_set"])
    for candidate_id in finalist_ids:
        candidate_mean = float(differentials[candidate_id].mean())
        candidate_bootstrap_se = bootstrap_se.get(candidate_id, float("inf"))
        trial_count_t = (
            candidate_mean / candidate_bootstrap_se
            if candidate_bootstrap_se > 0.0
            and math.isfinite(candidate_bootstrap_se)
            else float("inf")
            if candidate_mean > 0.0
            else 0.0
        )
        trial_count_threshold = math.sqrt(
            2.0 * math.log(max(2.0, float(raw_trial_count) / alpha))
        )
        gate_43 = trial_count_t >= trial_count_threshold
        gate_44 = global_process_pass and spa_candidates.get(candidate_id, 1.0) <= alpha
        gate_45 = holm.get(candidate_id, 1.0) <= alpha and fdr.get(candidate_id, 1.0) <= alpha
        gate_46 = pbo.get("pbo") is not None and float(pbo["pbo"]) <= maximum_pbo
        gate_47 = candidate_id in superior
        gate_48 = len(fingerprint_groups[strategy_fingerprints[candidate_id]]) >= 1
        finalist_rows[candidate_id] = {
            "passed": bool(
                gate_43 and gate_44 and gate_45 and gate_46 and gate_47 and gate_48
            ),
            "gates": {
                "43": bool(gate_43),
                "44": bool(gate_44),
                "45": bool(gate_45),
                "46": bool(gate_46),
                "47": bool(gate_47),
                "48": bool(gate_48),
            },
            "holm_adjusted_pvalue": holm.get(candidate_id),
            "fdr_qvalue": fdr.get(candidate_id),
            "spa_familywise_pvalue": spa_candidates.get(candidate_id),
            "trial_count_adjusted_t": trial_count_t,
            "trial_count_threshold": trial_count_threshold,
            "trial_count_penalty_uses_raw_trials": int(raw_trial_count),
        }
    return {
        "schema_version": 1,
        "raw_trial_count": int(raw_trial_count),
        "unique_candidate_count": int(frame.shape[1]),
        "unique_fingerprint_count": len(fingerprint_groups),
        "clone_count": int(frame.shape[1] - len(fingerprint_groups)),
        "white_spa_fdr": inference,
        "holm_adjusted_pvalues": holm,
        "pbo": pbo,
        "model_confidence_set": mcs,
        "alpha": alpha,
        "maximum_pbo": maximum_pbo,
        "finalists": finalist_rows,
        "uses_sharpe": False,
        "validation_opened": False,
        "locked_opened": False,
    }


__all__ = [
    "GlobalRobustnessError",
    "evaluate_global_robustness",
    "geometric_cscv_pbo",
    "holm_adjust",
    "model_confidence_set",
]
