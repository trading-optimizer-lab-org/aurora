"""Frozen train-only ranking and multiple-testing diagnostics."""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import norm


def deflated_sharpe_probability(
    returns: np.ndarray,
    *,
    trials: int,
    periods_per_year: int = 252,
) -> float:
    raw = np.asarray(returns, dtype=float)
    raw = raw[np.isfinite(raw)]
    if len(raw) < 3 or np.std(raw, ddof=1) <= 1e-15:
        return 0.0
    daily_sharpe = float(np.mean(raw) / np.std(raw, ddof=1))
    annual_sharpe = daily_sharpe * math.sqrt(periods_per_year)
    skew = float(pd.Series(raw).skew())
    kurtosis = float(pd.Series(raw).kurtosis() + 3.0)
    expected_max = norm.ppf((trials - 0.375) / (trials + 0.25))
    benchmark = expected_max / math.sqrt(max(len(raw) - 1, 1)) * math.sqrt(periods_per_year)
    denominator = math.sqrt(
        max(
            (1.0 - skew * daily_sharpe + ((kurtosis - 1.0) / 4.0) * daily_sharpe**2)
            / max(len(raw) - 1, 1),
            1e-15,
        )
    ) * math.sqrt(periods_per_year)
    return float(norm.cdf((annual_sharpe - benchmark) / denominator))


def _moving_block_indices(
    rng: np.random.Generator,
    length: int,
    block_length: int,
) -> np.ndarray:
    blocks = math.ceil(length / block_length)
    starts = rng.integers(0, length, size=blocks)
    offsets = np.arange(block_length)
    return ((starts[:, None] + offsets[None, :]) % length).reshape(-1)[:length]


def reality_check_and_spa(
    differentials: pd.DataFrame,
    *,
    seed: int,
    samples: int = 1000,
    block_lengths: Sequence[int] = (5, 10, 20, 60),
) -> Mapping[str, Any]:
    frame = differentials.dropna(axis=1, how="all").dropna(axis=0, how="any")
    if frame.empty or frame.shape[1] == 0 or len(frame) < 100:
        return {
            "white_reality_check_pvalue": None,
            "hansen_spa_pvalue": None,
            "candidate_spa_pvalues": {},
            "block_sensitivity": {},
            "reason": "INSUFFICIENT_COMMON_OBSERVATIONS",
        }
    matrix = frame.to_numpy(dtype=float)
    means = matrix.mean(axis=0)
    standard_errors = matrix.std(axis=0, ddof=1) / math.sqrt(len(matrix))
    observed_white = float(np.max(means))
    observed_t = np.divide(means, standard_errors, out=np.zeros_like(means), where=standard_errors > 0)
    observed_spa = float(np.max(observed_t))
    centered = matrix - means
    automatic = max(2, int(round(len(frame) ** (1.0 / 3.0))))
    lengths = (automatic, *tuple(int(value) for value in block_lengths))
    sensitivity = {}
    selected_bootstrap_t: np.ndarray | None = None
    for block_length in lengths:
        rng = np.random.default_rng(seed + block_length)
        boot_white = np.empty(samples, dtype=float)
        boot_spa = np.empty(samples, dtype=float)
        boot_t = np.empty((samples, matrix.shape[1]), dtype=float)
        for sample in range(samples):
            indices = _moving_block_indices(rng, len(frame), block_length)
            sampled = centered[indices]
            sample_means = sampled.mean(axis=0)
            sample_se = sampled.std(axis=0, ddof=1) / math.sqrt(len(sampled))
            studentized = np.divide(
                sample_means,
                sample_se,
                out=np.zeros_like(sample_means),
                where=sample_se > 0,
            )
            boot_t[sample] = studentized
            boot_white[sample] = float(np.max(sample_means))
            boot_spa[sample] = float(np.max(studentized))
        white_p = float((1 + np.count_nonzero(boot_white >= observed_white)) / (samples + 1))
        spa_p = float((1 + np.count_nonzero(boot_spa >= observed_spa)) / (samples + 1))
        sensitivity[str(block_length)] = {
            "white_reality_check_pvalue": white_p,
            "hansen_spa_pvalue": spa_p,
        }
        if block_length == automatic:
            selected_bootstrap_t = boot_t
    assert selected_bootstrap_t is not None
    maxima = np.max(selected_bootstrap_t, axis=1)
    candidate_pvalues = {
        column: float((1 + np.count_nonzero(maxima >= observed_t[index])) / (samples + 1))
        for index, column in enumerate(frame.columns)
    }
    selected = sensitivity[str(automatic)]
    return {
        **selected,
        "candidate_spa_pvalues": candidate_pvalues,
        "automatic_block_length": automatic,
        "bootstrap_samples": samples,
        "block_sensitivity": sensitivity,
        "reason": None,
    }


def cscv_pbo(returns: pd.DataFrame, *, partitions: int = 10) -> Mapping[str, Any]:
    frame = returns.dropna(axis=0, how="any")
    if frame.shape[1] < 2 or len(frame) < partitions * 20:
        return {"pbo": None, "combinations": 0, "reason": "INSUFFICIENT_COMMON_OBSERVATIONS"}
    blocks = np.array_split(np.arange(len(frame)), partitions)
    logits = []
    half = partitions // 2
    for selected in itertools.combinations(range(partitions), half):
        train_indices = np.concatenate([blocks[index] for index in selected])
        test_indices = np.concatenate([blocks[index] for index in range(partitions) if index not in selected])
        train = frame.iloc[train_indices]
        test = frame.iloc[test_indices]
        train_std = train.std(axis=0, ddof=0).replace(0.0, np.nan)
        train_sharpe = train.mean(axis=0) / train_std
        winner = str(train_sharpe.fillna(-np.inf).idxmax())
        test_std = test.std(axis=0, ddof=0).replace(0.0, np.nan)
        test_sharpe = (test.mean(axis=0) / test_std).rank(pct=True).fillna(0.0)
        percentile = float(test_sharpe[winner])
        bounded = min(max(percentile, 1e-9), 1.0 - 1e-9)
        logits.append(math.log(bounded / (1.0 - bounded)))
    return {
        "pbo": float(np.mean(np.asarray(logits) <= 0.0)),
        "combinations": len(logits),
        "median_logit": float(np.median(logits)),
        "reason": None,
    }


def _percentile_rank(series: pd.Series, *, higher_is_better: bool = True) -> pd.Series:
    clipped = series.clip(series.quantile(0.025), series.quantile(0.975))
    return clipped.rank(pct=True, ascending=higher_is_better)


def effective_independent_trials(returns: pd.DataFrame) -> float:
    """Estimate independent trials by correlation-matrix participation ratio."""

    correlation = returns.corr().fillna(0.0).copy()
    if correlation.empty:
        return 1.0
    matrix = correlation.to_numpy(dtype=float, copy=True)
    np.fill_diagonal(matrix, 1.0)
    eigenvalues = np.linalg.eigvalsh(matrix)
    eigenvalues = np.clip(eigenvalues, 0.0, None)
    denominator = float(np.square(eigenvalues).sum())
    if denominator <= 1e-15:
        return 1.0
    effective = float(eigenvalues.sum() ** 2 / denominator)
    return min(max(effective, 1.0), float(correlation.shape[0]))


def frozen_train_ranking(
    candidate_metrics: pd.DataFrame,
    annual_metrics: pd.DataFrame,
    daily_returns: pd.DataFrame,
    benchmark_daily_returns: pd.DataFrame,
    *,
    proxy_families: set[str],
    seed: int,
) -> tuple[pd.DataFrame, Mapping[str, Any]]:
    metrics = candidate_metrics.loc[candidate_metrics["status"] == "evaluated"].copy()
    if metrics.empty:
        return metrics, {
            "white_reality_check_pvalue": None,
            "hansen_spa_pvalue": None,
            "pbo": None,
            "reason": "NO_EVALUATED_CANDIDATES",
        }
    candidate_wide = daily_returns.pivot(index="date", columns="unit_key", values="return")
    benchmark_wide = benchmark_daily_returns.pivot(index="date", columns="unit_key", values="return")
    strongest_benchmark = max(
        benchmark_wide.columns,
        key=lambda column: float(benchmark_wide[column].mean() / max(benchmark_wide[column].std(ddof=0), 1e-15)),
    )
    benchmark = benchmark_wide[strongest_benchmark]
    differential = candidate_wide.subtract(benchmark, axis=0)
    multiple = dict(reality_check_and_spa(differential, seed=seed))
    pbo = cscv_pbo(candidate_wide)
    multiple["cscv"] = pbo
    multiple["pbo"] = pbo["pbo"]
    multiple["strongest_benchmark"] = strongest_benchmark
    candidate_spa = multiple.get("candidate_spa_pvalues", {})

    effective_trials = effective_independent_trials(candidate_wide)
    multiple["effective_independent_trials"] = effective_trials
    dsr_trials = max(1, int(math.ceil(effective_trials)))
    metrics["deflated_sharpe_probability"] = metrics["unit_key"].map(
        lambda key: deflated_sharpe_probability(
            candidate_wide[key].dropna().to_numpy(),
            trials=dsr_trials,
        )
    )
    metrics["spa_pvalue"] = metrics["unit_key"].map(candidate_spa)
    metrics["pbo"] = pbo["pbo"]
    annual_candidates = annual_metrics.loc[annual_metrics["unit_key"].isin(metrics["unit_key"])]
    annual_benchmark = annual_metrics.loc[annual_metrics["unit_key"] == strongest_benchmark].set_index("year")
    benchmark_win = {}
    for key, group in annual_candidates.groupby("unit_key"):
        merged = group.set_index("year").join(annual_benchmark[["return_pct"]], rsuffix="_benchmark")
        benchmark_win[str(key)] = float((merged["return_pct"] > merged["return_pct_benchmark"]).mean())
    metrics["benchmark_win_fraction"] = metrics["unit_key"].map(benchmark_win).fillna(0.0)

    sensitivity = {}
    for _, group in metrics.groupby("family", sort=True):
        ordered = group.sort_values("strategy_id", kind="mergesort").reset_index(drop=True)
        passing = (ordered["train_cagr_pct"] > 0) & (ordered["train_sharpe"] > 0)
        for index, key in enumerate(ordered["unit_key"]):
            neighbour_indices = [
                value
                for value in (index - 1, index + 1)
                if 0 <= value < len(ordered)
            ]
            sensitivity[str(key)] = (
                float(passing.iloc[neighbour_indices].mean())
                if neighbour_indices
                else 0.0
            )
    metrics["neighbour_positive_fraction"] = metrics["unit_key"].map(sensitivity)

    checks = {
        "cagr_positive": metrics["train_cagr_pct"] > 0,
        "sharpe_gt_0_30": metrics["train_sharpe"] > 0.30,
        "calmar_gt_0_25": metrics["train_calmar"] > 0.25,
        "max_drawdown_gt_minus_55": metrics["train_max_drawdown_pct"] > -55.0,
        "positive_years_ge_60pct": metrics["train_positive_year_fraction"] >= 0.60,
        "rolling_3y_cagr_positive": metrics["train_median_rolling_3y_cagr_pct"] > 0,
        "worst_fold_gt_minus_30": metrics["train_min_outer_fold_cagr_pct"] > -30.0,
        "gain_concentration_le_60pct": metrics["train_gain_concentration"] <= 0.60,
        "neighbour_sensitivity": metrics["neighbour_positive_fraction"] >= 0.50,
        "deflated_sharpe_gt_0_80": metrics["deflated_sharpe_probability"] > 0.80,
        "pbo_lt_0_50": metrics["pbo"].notna() & (metrics["pbo"] < 0.50),
    }
    for name, values in checks.items():
        metrics[f"gate_{name}"] = values
    metrics["diagnostic_family_representative"] = False
    metrics["hard_train_eligible"] = pd.DataFrame(checks).all(axis=1)
    metrics["spa_pass"] = metrics["spa_pvalue"].notna() & (metrics["spa_pvalue"] <= 0.10)

    rank_inputs = {
        "cagr": _percentile_rank(metrics["train_cagr_pct"]),
        "calmar": _percentile_rank(metrics["train_calmar"]),
        "sharpe": _percentile_rank(metrics["train_sharpe"]),
        "sortino": _percentile_rank(metrics["train_sortino"]),
        "positive": _percentile_rank(metrics["train_positive_year_fraction"]),
        "rolling": _percentile_rank(metrics["train_median_rolling_3y_cagr_pct"]),
        "worst": _percentile_rank(metrics["train_worst_year_return_pct"]),
        "fold": _percentile_rank(metrics["train_min_outer_fold_cagr_pct"]),
        "benchmark": _percentile_rank(metrics["benchmark_win_fraction"]),
        "turnover": _percentile_rank(1.0 - metrics["train_turnover_instability"].clip(0, 1)),
    }
    metrics["base_score"] = (
        0.20 * rank_inputs["cagr"]
        + 0.15 * rank_inputs["calmar"]
        + 0.10 * rank_inputs["sharpe"]
        + 0.08 * rank_inputs["sortino"]
        + 0.10 * rank_inputs["positive"]
        + 0.10 * rank_inputs["rolling"]
        + 0.10 * rank_inputs["worst"]
        + 0.07 * rank_inputs["fold"]
        + 0.05 * rank_inputs["benchmark"]
        + 0.05 * rank_inputs["turnover"]
    )
    metrics["penalty"] = (
        0.05 * (metrics["complexity_score"] / max(float(metrics["complexity_score"].max()), 1.0))
        + 0.07 * (1.0 - metrics["neighbour_positive_fraction"])
        + 0.06 * metrics["train_gain_concentration"].clip(0, 1)
        + 0.05 * metrics["missing_fraction"].fillna(1.0).clip(0, 1)
        + 0.04 * (metrics["evidence_track"] == "post_2010_research").astype(float)
        + 0.03 * metrics["family"].isin(proxy_families).astype(float)
    )
    metrics["train_selection_score"] = metrics["base_score"] - metrics["penalty"]
    metrics["eligible_for_freeze"] = metrics["hard_train_eligible"] & metrics["spa_pass"]
    metrics = metrics.sort_values(
        ["eligible_for_freeze", "train_selection_score", "unit_key"],
        ascending=[False, False, True],
        kind="mergesort",
    ).reset_index(drop=True)
    metrics["train_rank"] = np.arange(1, len(metrics) + 1)
    return metrics, multiple
