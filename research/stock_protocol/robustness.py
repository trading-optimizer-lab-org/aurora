"""Reproducible statistical work units for stock-protocol robustness shards."""

from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd


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
