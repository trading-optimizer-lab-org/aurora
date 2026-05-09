"""Tests for quantforge.ml.fracdiff (Task G.4).

Run: uv run pytest quantforge/tests/test_fracdiff.py -v
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aurora.ml.fracdiff import (
    find_min_d,
    frac_diff_ffd,
    fracdiff_correlation,
    get_weights_ffd,
)


# ---------------------------------------------------------------------------
# weight tests
# ---------------------------------------------------------------------------

def test_weights_d0():
    """d = 0 -> identity, only weight 1.0."""
    w = get_weights_ffd(0.0, threshold=1e-5)
    assert w.shape == (1,)
    assert w[0] == pytest.approx(1.0)


def test_weights_d1():
    """d = 1 -> first difference, weights [1, -1]."""
    w = get_weights_ffd(1.0, threshold=1e-5)
    assert w.shape == (2,)
    assert w[0] == pytest.approx(1.0)
    assert w[1] == pytest.approx(-1.0)


def test_weights_decay():
    """d = 0.5 -> weights decay rapidly, truncation respects threshold."""
    w = get_weights_ffd(0.5, threshold=1e-5)
    # First weight is exactly 1.
    assert w[0] == pytest.approx(1.0)
    # Magnitudes must be monotonically decreasing in absolute value.
    abs_w = np.abs(w)
    assert np.all(np.diff(abs_w) <= 1e-12)
    # Last retained weight magnitude is at or above the threshold.
    assert abs_w[-1] >= 1e-5
    # A looser threshold yields a strictly shorter window.
    w_loose = get_weights_ffd(0.5, threshold=1e-2)
    assert len(w_loose) < len(w)


# ---------------------------------------------------------------------------
# frac_diff_ffd tests
# ---------------------------------------------------------------------------

def _sample_series(n: int = 200, seed: int = 7) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2010-01-01", periods=n, freq="B")
    rets = rng.normal(0.0005, 0.012, n)
    p = 100.0 * np.cumprod(1.0 + rets)
    return pd.Series(np.log(p), index=idx, name="log_px")


def test_frac_diff_d0():
    """d = 0 -> output equals original series (no NaN warm-up)."""
    s = _sample_series()
    out = frac_diff_ffd(s, d=0.0, threshold=1e-5)
    assert out.shape == s.shape
    # Width is 0, so nothing is NaN.
    assert not out.isna().any()
    np.testing.assert_allclose(out.to_numpy(), s.to_numpy(), rtol=0, atol=1e-12)


def test_frac_diff_d1():
    """d = 1 -> first differences, first bar NaN."""
    s = _sample_series()
    out = frac_diff_ffd(s, d=1.0, threshold=1e-5)
    assert np.isnan(out.iloc[0])
    expected = s.diff()
    np.testing.assert_allclose(
        out.iloc[1:].to_numpy(), expected.iloc[1:].to_numpy(), rtol=1e-12, atol=1e-12
    )


def test_frac_diff_warmup_nan():
    """Truncation produces a fixed warm-up region of NaNs equal to len(weights) - 1."""
    s = _sample_series(n=300)
    # Threshold low enough to force a long window; verify the warm-up matches.
    w = get_weights_ffd(0.4, threshold=1e-5)
    width = len(w) - 1
    assert width >= 1
    out = frac_diff_ffd(s, d=0.4, threshold=1e-5)
    # Exactly the first ``width`` bars should be NaN; the rest must be finite.
    assert out.iloc[:width].isna().all()
    assert out.iloc[width:].notna().all()


# ---------------------------------------------------------------------------
# find_min_d tests
# ---------------------------------------------------------------------------

def test_find_min_d_random_walk():
    """An I(1) random-walk needs d > 0 to become stationary."""
    rng = np.random.default_rng(123)
    n = 1000
    idx = pd.date_range("2005-01-01", periods=n, freq="B")
    # Cumulative sum of iid normals -> integrated process, non-stationary.
    rw = pd.Series(np.cumsum(rng.normal(0.0, 1.0, n)), index=idx, name="rw")

    min_d, adf_stat, p_val = find_min_d(
        rw, max_d=1.0, step=0.1, threshold=1e-4, adf_pvalue=0.05
    )
    assert min_d is not None, "Expected a stationary d for a random walk"
    assert min_d > 0.0
    assert min_d <= 1.0
    assert p_val is not None and p_val <= 0.05
    assert adf_stat is not None and np.isfinite(adf_stat)


# ---------------------------------------------------------------------------
# fracdiff_correlation tests
# ---------------------------------------------------------------------------

def test_correlation_sweep():
    """Sweep returns the documented column schema and reasonable values."""
    s = _sample_series(n=400)
    df = fracdiff_correlation(s, max_d=1.0, step=0.2, threshold=1e-4)

    assert list(df.columns) == ["d", "adf_stat", "adf_pvalue", "corr_with_original"]
    # Sweep covers d = 0.0 through d = 1.0 inclusive.
    assert df["d"].min() == pytest.approx(0.0)
    assert df["d"].max() == pytest.approx(1.0)
    assert len(df) >= 6  # 0.0, 0.2, 0.4, 0.6, 0.8, 1.0

    # Row d = 0.0 is the original series; correlation must be 1.
    row0 = df.loc[df["d"] == 0.0].iloc[0]
    assert row0["corr_with_original"] == pytest.approx(1.0, abs=1e-9)

    # Correlation should weakly decline as d grows (memory shrinks).
    finite = df.dropna(subset=["corr_with_original"])
    assert finite["corr_with_original"].iloc[0] >= finite["corr_with_original"].iloc[-1] - 1e-6
