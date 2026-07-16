"""Reproducible statistical work units for stock-protocol robustness shards."""

from __future__ import annotations

import hashlib
from itertools import combinations
import math
from statistics import NormalDist

import numpy as np
import pandas as pd


EULER_GAMMA = 0.5772156649015329


def _finite_returns(returns: pd.Series) -> np.ndarray:
    values = pd.to_numeric(returns, errors="coerce").to_numpy(dtype=float)
    if len(values) < 2 or not np.isfinite(values).all() or np.any(values <= -1.0):
        raise ValueError("robustness returns must be finite, > -100%, and non-trivial")
    return values


def block_bootstrap_records(
    returns: pd.Series,
    n_samples: int,
    block_size: int,
    seed: int,
    variant: str,
) -> pd.DataFrame:
    """Run circular fixed-block samples and record each actual sampled path."""

    values = _finite_returns(returns)
    if n_samples < 1 or block_size < 1:
        raise ValueError("n_samples and block_size must be positive")
    if block_size > len(values):
        raise ValueError("block_size cannot exceed observations")
    rng = np.random.default_rng(seed)
    input_hash = hashlib.sha256(values.tobytes()).hexdigest()
    blocks_needed = int(np.ceil(len(values) / block_size))
    rows: list[dict[str, object]] = []
    for sample_id in range(n_samples):
        starts = rng.integers(0, len(values), size=blocks_needed)
        indices = np.concatenate(
            [
                (int(start) + np.arange(block_size, dtype=int)) % len(values)
                for start in starts
            ]
        )[: len(values)]
        sample = values[indices]
        standard_deviation = float(sample.std(ddof=1))
        sharpe = (
            float(sample.mean() / standard_deviation * np.sqrt(252.0))
            if standard_deviation > 0
            else 0.0
        )
        rows.append(
            {
                "sample_id": sample_id,
                "seed": int(seed),
                "method": "circular_block_bootstrap",
                "variant": str(variant),
                "n_observations": int(len(sample)),
                "block_size": int(block_size),
                "mean_return": float(sample.mean()),
                "sharpe": sharpe,
                "input_hash": input_hash,
                "sample_hash": hashlib.sha256(sample.tobytes()).hexdigest(),
            }
        )
    return pd.DataFrame(rows)


def benjamini_hochberg(pvalues: pd.Series) -> pd.Series:
    """Benjamini-Hochberg adjusted p-values in original row order."""

    values = pd.to_numeric(pvalues, errors="coerce")
    if values.isna().any() or not values.between(0.0, 1.0).all():
        raise ValueError("p-values must be finite and within [0, 1]")
    order = np.argsort(values.to_numpy(dtype=float), kind="stable")
    sorted_values = values.to_numpy(dtype=float)[order]
    count = len(sorted_values)
    adjusted_sorted = sorted_values * count / np.arange(1, count + 1)
    adjusted_sorted = np.minimum.accumulate(adjusted_sorted[::-1])[::-1]
    adjusted_sorted = np.clip(adjusted_sorted, 0.0, 1.0)
    adjusted = np.empty(count, dtype=float)
    adjusted[order] = adjusted_sorted
    return pd.Series(adjusted, index=pvalues.index, name="fdr_pvalue")


def leave_one_group_out(
    frame: pd.DataFrame,
    group_column: str,
    return_column: str,
) -> pd.DataFrame:
    """Recompute simple return diagnostics after removing each real group."""

    if group_column not in frame or return_column not in frame:
        raise ValueError("leave-one-group-out columns are missing")
    values = frame.copy()
    values[return_column] = pd.to_numeric(values[return_column], errors="coerce")
    if values[return_column].isna().any() or not np.isfinite(values[return_column]).all():
        raise ValueError("leave-one-group-out returns must be finite")
    rows: list[dict[str, object]] = []
    for group in sorted(values[group_column].dropna().unique().tolist()):
        removed = values.loc[values[group_column] == group]
        remaining = values.loc[values[group_column] != group, return_column]
        standard_deviation = float(remaining.std(ddof=1)) if len(remaining) > 1 else 0.0
        rows.append(
            {
                "left_out_group": group,
                "left_out_observations": int(len(removed)),
                "remaining_observations": int(len(remaining)),
                "remaining_mean_return": float(remaining.mean()),
                "remaining_sharpe": (
                    float(remaining.mean() / standard_deviation * np.sqrt(252.0))
                    if standard_deviation > 0
                    else 0.0
                ),
            }
        )
    return pd.DataFrame(rows)


def deflated_sharpe_ratio(
    returns: pd.Series,
    *,
    n_trials: int,
) -> dict[str, float]:
    """Return a multiple-testing and non-normality adjusted Sharpe probability."""

    values = _finite_returns(returns)
    if len(values) < 30:
        raise ValueError("deflated Sharpe requires at least 30 observations")
    if n_trials < 2:
        raise ValueError("deflated Sharpe requires at least two trials")
    standard_deviation = float(values.std(ddof=1))
    if standard_deviation <= 0:
        raise ValueError("deflated Sharpe requires non-zero volatility")
    daily_sharpe = float(values.mean() / standard_deviation)
    skewness = float(pd.Series(values).skew())
    kurtosis = float(pd.Series(values).kurt() + 3.0)
    variance_term = (
        1.0
        - skewness * daily_sharpe
        + ((kurtosis - 1.0) / 4.0) * daily_sharpe**2
    ) / (len(values) - 1)
    standard_error = math.sqrt(max(variance_term, 1e-15))
    normal = NormalDist()
    first_quantile = normal.inv_cdf(1.0 - 1.0 / n_trials)
    second_quantile = normal.inv_cdf(1.0 - 1.0 / (n_trials * math.e))
    expected_max_daily = standard_error * (
        (1.0 - EULER_GAMMA) * first_quantile
        + EULER_GAMMA * second_quantile
    )
    probability = normal.cdf((daily_sharpe - expected_max_daily) / standard_error)
    result = {
        "observed_sharpe": daily_sharpe * math.sqrt(252.0),
        "expected_max_sharpe": expected_max_daily * math.sqrt(252.0),
        "probability": float(np.clip(probability, 0.0, 1.0)),
        "n_trials": float(n_trials),
        "n_observations": float(len(values)),
        "skewness": skewness,
        "kurtosis": kurtosis,
    }
    if not np.isfinite(np.fromiter(result.values(), dtype=float)).all():
        raise ValueError("deflated Sharpe produced a non-finite result")
    return result


def _strategy_scores(values: np.ndarray) -> np.ndarray:
    mean = values.mean(axis=0)
    deviation = values.std(axis=0, ddof=1)
    return np.divide(mean, deviation, out=np.full_like(mean, -np.inf), where=deviation > 0)


def cscv_probability_of_backtest_overfitting(
    returns_matrix: pd.DataFrame,
    *,
    partitions: int = 8,
) -> dict[str, object]:
    """Compute CSCV/PBO from complementary chronological block combinations."""

    if partitions < 4 or partitions % 2:
        raise ValueError("CSCV partitions must be an even integer of at least four")
    numeric = returns_matrix.apply(pd.to_numeric, errors="coerce")
    values = numeric.to_numpy(dtype=float)
    if values.shape[0] < partitions * 2 or values.shape[1] < 2:
        raise ValueError("CSCV requires enough observations and at least two strategies")
    if not np.isfinite(values).all():
        raise ValueError("CSCV return matrix must be finite")
    blocks = [np.asarray(block, dtype=int) for block in np.array_split(np.arange(len(values)), partitions)]
    logits: list[float] = []
    selected_names: list[str] = []
    half = partitions // 2
    for train_blocks in combinations(range(partitions), half):
        if 0 not in train_blocks:
            continue
        train_set = set(train_blocks)
        test_blocks = [index for index in range(partitions) if index not in train_set]
        train_index = np.concatenate([blocks[index] for index in train_blocks])
        test_index = np.concatenate([blocks[index] for index in test_blocks])
        train_scores = _strategy_scores(values[train_index])
        selected = int(np.argmax(train_scores))
        test_scores = _strategy_scores(values[test_index])
        selected_score = float(test_scores[selected])
        rank_fraction = (
            float(np.sum(test_scores < selected_score)) + 0.5
        ) / len(test_scores)
        rank_fraction = float(np.clip(rank_fraction, 1e-12, 1.0 - 1e-12))
        logits.append(math.log(rank_fraction / (1.0 - rank_fraction)))
        selected_names.append(str(numeric.columns[selected]))
    if not logits:
        raise ValueError("CSCV generated no complementary combinations")
    result: dict[str, object] = {
        "pbo": float(np.mean(np.asarray(logits) <= 0.0)),
        "combinations_evaluated": int(len(logits)),
        "median_logit": float(np.median(logits)),
        "partitions": int(partitions),
        "selected_strategy_counts": {
            name: selected_names.count(name) for name in sorted(set(selected_names))
        },
        "input_hash": hashlib.sha256(values.tobytes()).hexdigest(),
    }
    if not all(
        np.isfinite(float(result[key]))
        for key in ("pbo", "combinations_evaluated", "median_logit", "partitions")
    ):
        raise ValueError("CSCV produced a non-finite result")
    return result
