"""Leak-free train-only signal-weight learning."""

from __future__ import annotations

import numpy as np
import pandas as pd


def learn_nonnegative_weights(
    signal_returns: pd.DataFrame,
    *,
    train_end: pd.Timestamp,
) -> dict[str, float]:
    """Fit deterministic non-negative mean/variance weights on past rows only."""

    if "date" not in signal_returns:
        raise ValueError("signal returns require a date column")
    frame = signal_returns.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.normalize()
    cutoff = pd.Timestamp(train_end).normalize()
    train = frame.loc[frame["date"].le(cutoff)].drop(columns="date")
    if len(train) < 2 or train.empty:
        raise ValueError("not enough training rows to learn signal weights")
    train = train.apply(pd.to_numeric, errors="coerce")
    if train.isna().any().any() or not np.isfinite(train.to_numpy(dtype=float)).all():
        raise ValueError("training signal returns must be finite")
    mean = train.mean()
    variance = train.var(ddof=1).clip(lower=1e-12)
    utility = mean.div(variance).clip(lower=0.0)
    if float(utility.sum()) <= 0:
        utility = pd.Series(1.0, index=train.columns)
    weights = utility / utility.sum()
    return {str(column): float(weights[column]) for column in sorted(weights.index)}
