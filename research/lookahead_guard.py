"""Generic guards against lookahead-biased signals."""
from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd


class LookaheadBiasError(RuntimeError):
    """Raised when a signal changes after future rows are hidden."""


SignalFn = Callable[[pd.Series], np.ndarray]


def assert_signal_is_causal(
    prices: pd.Series,
    signal_fn: SignalFn,
    *,
    min_history: int = 20,
    max_checks: int = 64,
    atol: float = 1e-12,
) -> None:
    """Reject signals that depend on rows after the decision point.

    The check is prefix-invariance based. A causal signal should produce the
    same historical outputs whether it receives the full series or only the
    prefix available up to a given date.
    """
    if not isinstance(prices.index, pd.DatetimeIndex):
        raise TypeError("prices index must be a DatetimeIndex")
    if len(prices) <= min_history:
        return

    full = _normalise_signal(signal_fn(prices), len(prices), label="full")
    stop = len(prices) - 1
    starts = np.linspace(min_history, stop, num=min(max_checks, stop - min_history + 1))
    checkpoints = sorted({int(x) for x in starts})

    for pos in checkpoints:
        prefix = prices.iloc[: pos + 1]
        got = _normalise_signal(signal_fn(prefix), len(prefix), label="prefix")
        expected = full[: pos + 1]
        if not np.allclose(got, expected, atol=atol, rtol=0.0, equal_nan=True):
            mismatch = int(np.flatnonzero(~np.isclose(
                got, expected, atol=atol, rtol=0.0, equal_nan=True,
            ))[0])
            raise LookaheadBiasError(
                "signal lookahead detected: output for "
                f"{prices.index[mismatch].date().isoformat()} changes when "
                f"future rows after {prices.index[pos].date().isoformat()} are hidden"
            )


def _normalise_signal(values: np.ndarray, expected_len: int, *, label: str) -> np.ndarray:
    out = np.asarray(values, dtype=float)
    if out.ndim != 1:
        raise ValueError(f"{label} signal must be 1D")
    if len(out) != expected_len:
        raise ValueError(f"{label} signal length {len(out)} != prices length {expected_len}")
    if not np.all(np.isfinite(out)):
        raise ValueError(f"{label} signal contains non-finite values")
    return out


__all__ = ["LookaheadBiasError", "assert_signal_is_causal"]
