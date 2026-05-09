"""Tests for the extended AST-based lookahead scanner.

Covers shift(-N), iloc forward slices, lambda forward access, groupby bfill/ffill,
reverse-cumsum, df.index > X heuristic, and backward compatibility of scan_lookahead.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aurora.validation.lookahead_check import (
    StaticLookaheadReport,
    scan_lookahead,
    scan_lookahead_v2,
)


# ---------- shift(-N) ----------

def _shift_neg_strategy(prices: pd.Series) -> np.ndarray:
    sig = prices.shift(-1)
    return sig.fillna(0).to_numpy()


def _shift_pos_strategy(prices: pd.Series) -> np.ndarray:
    sig = prices.shift(1)
    return sig.fillna(0).to_numpy()


def test_shift_neg_detected():
    rep = scan_lookahead_v2(_shift_neg_strategy)
    patterns = {f["pattern"] for f in rep.findings}
    assert "shift_negative" in patterns
    assert rep.severity_counts["high"] >= 1
    assert any("negative shift" in w for w in rep.warnings)


def test_shift_positive_clean():
    rep = scan_lookahead_v2(_shift_pos_strategy)
    patterns = {f["pattern"] for f in rep.findings}
    assert "shift_negative" not in patterns


# ---------- iloc/loc forward ----------

def _iloc_forward_strategy(df: pd.DataFrame) -> np.ndarray:
    # forward slice: take everything after i+1 — clear leak
    out = []
    for i in range(len(df)):
        future = df.iloc[i + 1:]
        out.append(future.mean() if len(future) else 0)
    return np.array(out)


def _iloc_backward_strategy(df: pd.DataFrame) -> np.ndarray:
    # backward window only — clean
    out = []
    for i in range(len(df)):
        past = df.iloc[:i]
        out.append(past.mean() if len(past) else 0)
    return np.array(out)


def test_iloc_forward_detected():
    rep = scan_lookahead_v2(_iloc_forward_strategy)
    patterns = {f["pattern"] for f in rep.findings}
    assert ("iloc_loc_forward" in patterns) or ("subscript_forward_offset" in patterns)
    # for-loop forward access should also trigger
    assert "for_loop_forward_access" in patterns
    assert rep.severity_counts["high"] >= 1


def test_iloc_backward_clean():
    rep = scan_lookahead_v2(_iloc_backward_strategy)
    patterns = {f["pattern"] for f in rep.findings}
    assert "iloc_loc_forward" not in patterns
    assert "subscript_forward_offset" not in patterns
    assert "for_loop_forward_access" not in patterns


# ---------- lambda forward ----------

def _lambda_forward_strategy(df: pd.DataFrame) -> np.ndarray:
    f = lambda i: df.iloc[i + 1]  # noqa: E731
    return np.array([f(i).mean() if i + 1 < len(df) else 0 for i in range(len(df))])


def test_lambda_forward_detected():
    rep = scan_lookahead_v2(_lambda_forward_strategy)
    patterns = {f["pattern"] for f in rep.findings}
    assert "lambda_forward_access" in patterns
    assert rep.severity_counts["medium"] >= 1


# ---------- groupby bfill / ffill ----------

def _groupby_bfill_strategy(df: pd.DataFrame) -> np.ndarray:
    filled = df.groupby("symbol")["price"].bfill()
    return filled.to_numpy()


def _groupby_fillna_bfill_strategy(df: pd.DataFrame) -> np.ndarray:
    filled = df.groupby("symbol")["price"].fillna(method="bfill")
    return filled.to_numpy()


def _groupby_ffill_strategy(df: pd.DataFrame) -> np.ndarray:
    filled = df.groupby("symbol")["price"].ffill()
    return filled.to_numpy()


def test_groupby_bfill_detected():
    rep1 = scan_lookahead_v2(_groupby_bfill_strategy)
    rep2 = scan_lookahead_v2(_groupby_fillna_bfill_strategy)
    patterns1 = {f["pattern"] for f in rep1.findings}
    patterns2 = {f["pattern"] for f in rep2.findings}
    assert "groupby_bfill" in patterns1
    assert "groupby_fillna_bfill" in patterns2
    assert rep1.severity_counts["high"] >= 1
    assert rep2.severity_counts["high"] >= 1


def test_groupby_ffill_clean():
    rep = scan_lookahead_v2(_groupby_ffill_strategy)
    patterns = {f["pattern"] for f in rep.findings}
    assert "groupby_bfill" not in patterns
    assert "groupby_fillna_bfill" not in patterns


# ---------- reverse-cumsum ----------

def _reverse_cumsum_strategy(prices: pd.Series) -> np.ndarray:
    sig = prices[::-1].cumsum()
    return sig.to_numpy()


def test_reverse_cumsum_detected():
    rep = scan_lookahead_v2(_reverse_cumsum_strategy)
    patterns = {f["pattern"] for f in rep.findings}
    assert "reverse_cumulative" in patterns
    assert rep.severity_counts["high"] >= 1


# ---------- df.index > X heuristic ----------

def _index_gt_future_strategy(df: pd.DataFrame, threshold) -> np.ndarray:
    sub = df[df.index > threshold]
    return sub.to_numpy().mean(axis=0) if len(sub) else np.zeros(df.shape[1])


def test_index_gt_future_warned():
    rep = scan_lookahead_v2(_index_gt_future_strategy)
    patterns = {f["pattern"] for f in rep.findings}
    assert "index_gt_future" in patterns
    assert rep.severity_counts["medium"] >= 1


# ---------- clean function ----------

def _clean_signal(prices: pd.Series) -> np.ndarray:
    """Legitimate causal signal: rolling mean over past 20 bars, no future access."""
    rolling = prices.rolling(window=20, min_periods=1).mean()
    diff = prices - rolling
    out = np.where(diff.to_numpy() > 0, 1, -1)
    return out


def test_clean_function_no_warnings():
    rep = scan_lookahead_v2(_clean_signal)
    assert rep.warnings == []
    assert rep.findings == []
    assert rep.severity_counts == {"high": 0, "medium": 0, "low": 0}


# ---------- backward compat ----------

def _legacy_text_pattern_strategy(arr):
    # uses textual `[i+` pattern — exercised only for legacy compatibility
    out = []
    for i in range(len(arr) - 1):
        out.append(arr[i + 1])
    return out


def test_backward_compat_scan_lookahead():
    # old API still works and returns a list[str]
    warnings = scan_lookahead(_legacy_text_pattern_strategy)
    assert isinstance(warnings, list)
    assert all(isinstance(w, str) for w in warnings)
    # legacy should still flag this (text or AST)
    assert len(warnings) >= 1

    # clean function should produce empty warnings via old API too
    clean_warnings = scan_lookahead(_clean_signal)
    assert clean_warnings == []


def test_scan_lookahead_v2_returns_report():
    rep = scan_lookahead_v2(_shift_neg_strategy)
    assert isinstance(rep, StaticLookaheadReport)
    assert isinstance(rep.warnings, list)
    assert isinstance(rep.findings, list)
    assert isinstance(rep.severity_counts, dict)
    for f in rep.findings:
        assert "pattern" in f
        assert "line" in f
        assert "col" in f
        assert "src" in f
        assert "severity" in f


def test_runtime_check_includes_static_v2():
    """runtime_lookahead_check should attach static_v2 by default."""
    from aurora.validation.lookahead_check import runtime_lookahead_check

    prices = pd.Series(np.linspace(100.0, 110.0, 60))
    rep = runtime_lookahead_check(_clean_signal, prices)
    assert rep.static_v2 is not None
    assert isinstance(rep.static_v2, StaticLookaheadReport)


# ---------- intraday/minute-bar runtime check ----------

def _clean_intraday_signal(df: pd.DataFrame) -> np.ndarray:
    """Causal signal on minute bars: rolling mean of close - past 20-bar mean."""
    rolling = df["close"].rolling(window=20, min_periods=1).mean()
    diff = df["close"] - rolling
    return np.where(diff.to_numpy() > 0, 1, -1)


def _leaky_intraday_signal(df: pd.DataFrame) -> np.ndarray:
    """Pulls future close into the current bar: clear leak."""
    future = df["close"].shift(-1).fillna(df["close"]).to_numpy()
    return np.where(future > df["close"].to_numpy(), 1, -1)


def test_runtime_intraday_check_detects_leak():
    """Shuffling rows after k must leave a clean signal unchanged BEFORE k,
    and must reveal a leak when the strategy peeks at future bars.
    """
    from aurora.validation.lookahead_check import runtime_lookahead_check_intraday

    rng = np.random.default_rng(7)
    n = 240
    idx = pd.date_range("2024-01-02 09:30", periods=n, freq="min")
    base = 100.0 + np.cumsum(rng.normal(0, 0.05, n))
    df = pd.DataFrame({
        "open": base,
        "high": base + 0.1,
        "low": base - 0.1,
        "close": base,
        "volume": rng.integers(100, 1000, n).astype(float),
    }, index=idx)

    # Clean signal must pass.
    rep_clean = runtime_lookahead_check_intraday(_clean_intraday_signal, df)
    assert rep_clean.passed is True
    assert rep_clean.runtime_violation is False

    # Leaky signal must fail (signals BEFORE k change when future rows are shuffled).
    rep_leak = runtime_lookahead_check_intraday(_leaky_intraday_signal, df)
    assert rep_leak.passed is False
    assert rep_leak.runtime_violation is True
    assert rep_leak.runtime_metric_delta > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
