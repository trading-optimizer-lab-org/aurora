"""Tests for microstructure features.

Run: uv run pytest aurora/tests/test_microstructure.py -v
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from aurora.ml.microstructure import (
    corwin_schultz_spread,
    roll_spread_estimator,
    signed_volume,
    order_flow_imbalance,
    vpin,
    kyle_lambda,
    amihud_illiquidity,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def idx():
    return pd.date_range("2021-01-01", periods=300, freq="B")


@pytest.fixture
def random_ohlc(idx):
    rng = np.random.default_rng(7)
    rets = rng.normal(0.0003, 0.01, len(idx))
    close = pd.Series(100.0 * np.cumprod(1.0 + rets), index=idx, name="close")
    # Build plausible high/low around close.
    span = pd.Series(rng.uniform(0.002, 0.01, len(idx)), index=idx)
    high = close * (1.0 + span)
    low = close * (1.0 - span)
    volume = pd.Series(rng.integers(1_000, 10_000, len(idx)).astype(float),
                       index=idx, name="volume")
    return close, high, low, volume


# ---------------------------------------------------------------------------
# Corwin-Schultz spread
# ---------------------------------------------------------------------------

def test_corwin_schultz_basic(random_ohlc):
    _, high, low, _ = random_ohlc
    s = corwin_schultz_spread(high, low, window=2)
    assert isinstance(s, pd.Series)
    assert len(s) == len(high)
    finite = s.dropna()
    assert len(finite) > 0
    # Spread is in fractional units (not bps), should be small and finite.
    assert np.all(np.isfinite(finite.values))
    assert (finite >= 0).all()
    assert finite.max() < 1.0  # sanity: less than 100% of price


def test_corwin_schultz_warmup(random_ohlc):
    _, high, low, _ = random_ohlc
    window = 5
    s = corwin_schultz_spread(high, low, window=window)
    # First window-1 bars must be NaN.
    assert s.iloc[: window - 1].isna().all()
    # And the bar at index window-1 should be finite (we have enough data).
    assert np.isfinite(s.iloc[window - 1])


def test_corwin_schultz_validation():
    h = pd.Series([1.0, 1.1, 1.2])
    l = pd.Series([0.9, 1.0])
    with pytest.raises(ValueError):
        corwin_schultz_spread(h, l)
    with pytest.raises(TypeError):
        corwin_schultz_spread([1.0, 2.0], pd.Series([0.5, 1.5]))
    with pytest.raises(ValueError):
        corwin_schultz_spread(pd.Series([1.0, 2.0]), pd.Series([0.5, 1.5]),
                              window=1)


# ---------------------------------------------------------------------------
# Roll spread estimator
# ---------------------------------------------------------------------------

def test_roll_spread():
    """Construct a synthetic bid-ask bouncing series with known spread.

    Take a constant midprice and add a +/- (s/2) bounce on alternate ticks.
    Then dP_t alternates +/- s, so cov(dP_t, dP_{t-1}) = -s^2 and Roll's
    estimator returns spread = 2 * sqrt(s^2) = 2 * s. With s = 0.10 (i.e.
    half = 0.05) the expected output is exactly 0.20.
    """
    n = 200
    half = 0.05  # half-spread per side
    s = 2.0 * half  # full spread
    bounce = np.array([(-1) ** i for i in range(n)], dtype=float) * half
    mid = 100.0
    px = pd.Series(mid + bounce, index=pd.RangeIndex(n))
    out = roll_spread_estimator(px, window=50)
    finite = out.dropna()
    assert len(finite) > 0
    assert np.isclose(finite.mean(), 2.0 * s, atol=1e-6)
    # First window-1 bars must be NaN.
    assert out.iloc[:49].isna().all()


def test_roll_spread_validation():
    with pytest.raises(TypeError):
        roll_spread_estimator([1.0, 2.0])
    with pytest.raises(ValueError):
        roll_spread_estimator(pd.Series([1.0, 2.0, 3.0]), window=2)


# ---------------------------------------------------------------------------
# Signed volume (Lee-Ready tick rule)
# ---------------------------------------------------------------------------

def test_signed_volume_uptick():
    """Strictly increasing prices => all volumes positive (after the first)."""
    px = pd.Series(np.arange(1.0, 11.0))
    vol = pd.Series(np.full(10, 100.0))
    sv = signed_volume(px, vol)
    # First bar has no previous tick: sign = 0 => signed = 0.
    assert sv.iloc[0] == 0.0
    assert (sv.iloc[1:] == 100.0).all()


def test_signed_volume_downtick():
    """Strictly decreasing prices => all volumes negative (after the first)."""
    px = pd.Series(np.arange(10.0, 0.0, -1.0))
    vol = pd.Series(np.full(10, 100.0))
    sv = signed_volume(px, vol)
    assert sv.iloc[0] == 0.0
    assert (sv.iloc[1:] == -100.0).all()


def test_signed_volume_flat():
    """Flat price after an initial tick carries the previous sign."""
    # up tick at i=1, then flat for the remainder
    px = pd.Series([100.0, 101.0, 101.0, 101.0, 101.0])
    vol = pd.Series([10.0, 20.0, 30.0, 40.0, 50.0])
    sv = signed_volume(px, vol)
    assert sv.iloc[0] == 0.0
    assert sv.iloc[1] == 20.0   # uptick
    assert sv.iloc[2] == 30.0   # flat -> carry +
    assert sv.iloc[3] == 40.0
    assert sv.iloc[4] == 50.0

    # now downtick scenario
    px2 = pd.Series([100.0, 99.0, 99.0, 99.0])
    vol2 = pd.Series([10.0, 20.0, 30.0, 40.0])
    sv2 = signed_volume(px2, vol2)
    assert sv2.iloc[0] == 0.0
    assert sv2.iloc[1] == -20.0
    assert sv2.iloc[2] == -30.0
    assert sv2.iloc[3] == -40.0


def test_signed_volume_no_lookahead():
    """signed_volume[:i] must depend only on close[:i+1] and volume[:i+1].

    Regression guard: mutate close[i+1:] and volume[i+1:]; the prefix of
    signed_volume up to and including bar i must be byte-identical.
    """
    rng = np.random.default_rng(123)
    n = 200
    rets = rng.normal(0.0, 0.01, n)
    close = pd.Series(100.0 * np.cumprod(1.0 + rets))
    volume = pd.Series(rng.integers(1_000, 10_000, n).astype(float))

    sv_orig = signed_volume(close, volume)

    # Probe at multiple bars to ensure no leakage anywhere.
    for i in (10, 50, 100, 150, 198):
        close_pert = close.copy()
        vol_pert = volume.copy()
        # Aggressively perturb everything strictly after i.
        close_pert.iloc[i + 1:] = (
            close_pert.iloc[i + 1:] * rng.uniform(0.5, 1.5, n - (i + 1))
        )
        vol_pert.iloc[i + 1:] = (
            vol_pert.iloc[i + 1:] * rng.uniform(0.1, 10.0, n - (i + 1))
        )
        sv_pert = signed_volume(close_pert, vol_pert)
        # Bar 0..i must be byte-identical.
        np.testing.assert_array_equal(
            sv_orig.iloc[: i + 1].to_numpy(),
            sv_pert.iloc[: i + 1].to_numpy(),
        )


# ---------------------------------------------------------------------------
# Order-flow imbalance
# ---------------------------------------------------------------------------

def test_ofi_rolling_sum():
    """OFI with window=10 should equal rolling sum of signed_vol over 10 bars."""
    rng = np.random.default_rng(123)
    sv = pd.Series(rng.normal(0.0, 100.0, 50))
    ofi = order_flow_imbalance(sv, window=10)
    # Compare against pandas reference.
    expected = sv.rolling(window=10, min_periods=10).sum()
    pd.testing.assert_series_equal(
        ofi.rename(None), expected.rename(None), check_names=False,
    )
    # Warm-up: first 9 rows are NaN.
    assert ofi.iloc[:9].isna().all()
    assert np.isfinite(ofi.iloc[9])


# ---------------------------------------------------------------------------
# VPIN
# ---------------------------------------------------------------------------

def test_vpin_range(random_ohlc):
    close, _, _, volume = random_ohlc
    out = vpin(close, volume, n_buckets=20, window=5)
    assert isinstance(out, pd.Series)
    assert len(out) == len(close)
    finite = out.dropna()
    # VPIN is |buy - sell| / bucket_vol averaged in [0, 1].
    assert (finite >= 0.0).all()
    assert (finite <= 1.0 + 1e-9).all()
    # We should produce at least some non-NaN VPIN values.
    assert len(finite) > 0


# ---------------------------------------------------------------------------
# Kyle's lambda
# ---------------------------------------------------------------------------

def test_kyle_lambda_finite(random_ohlc):
    close, _, _, volume = random_ohlc
    lam = kyle_lambda(close, volume, window=30)
    assert isinstance(lam, pd.Series)
    assert len(lam) == len(close)
    finite = lam.dropna()
    assert len(finite) > 0
    assert np.all(np.isfinite(finite.values))
    # First window-1 rows must be NaN.
    assert lam.iloc[:29].isna().all()


# ---------------------------------------------------------------------------
# Amihud illiquidity
# ---------------------------------------------------------------------------

def test_amihud_illiquidity():
    """Periods with low dollar volume should give higher illiquidity."""
    n = 100
    rng = np.random.default_rng(0)
    rets = pd.Series(rng.normal(0.0, 0.01, n))
    # Low volume in the first half, high volume in the second half.
    dv = pd.Series(np.r_[np.full(n // 2, 1e3), np.full(n - n // 2, 1e6)])
    illiq = amihud_illiquidity(rets, dv, window=10)
    finite = illiq.dropna()
    assert len(finite) > 0
    # Compare averages of the two regimes (skip the boundary 10 bars where
    # the rolling window straddles both regimes).
    low_vol_segment = illiq.iloc[10: n // 2].dropna()
    high_vol_segment = illiq.iloc[n // 2 + 10:].dropna()
    assert low_vol_segment.mean() > high_vol_segment.mean()
    # First window-1 rows must be NaN.
    assert illiq.iloc[:9].isna().all()


def test_amihud_illiquidity_validation():
    with pytest.raises(TypeError):
        amihud_illiquidity([0.01, -0.02], pd.Series([1.0, 2.0]))
    with pytest.raises(ValueError):
        amihud_illiquidity(pd.Series([0.01]), pd.Series([1.0, 2.0]))
    with pytest.raises(ValueError):
        amihud_illiquidity(pd.Series([0.01, 0.0]), pd.Series([1.0, 2.0]),
                           window=0)


# ---------------------------------------------------------------------------
# Audit fix: VPIN alignment must place the rolling mean at the bar that
# closed the RIGHT edge of the window of buckets (issue #4).
# ---------------------------------------------------------------------------


def test_signed_volume_nan_propagates_at_bad_diff():
    """Audit fix: a non-finite price diff (NaN/inf) must surface as a NaN
    sign at that bar instead of silently inheriting the previous sign.
    """
    close = pd.Series([100.0, 101.0, np.nan, 103.0, 104.0])
    volume = pd.Series([1.0, 1.0, 1.0, 1.0, 1.0])
    sv = signed_volume(close, volume)
    assert pd.isna(sv.iloc[2]), "non-finite price diff should yield NaN sign"
    # Bar 3 sees diff = NaN - actual = NaN, also non-finite -> NaN.
    assert pd.isna(sv.iloc[3])


def test_vpin_ffill_is_bounded_by_window():
    """Audit fix: VPIN ffill must stop after ``window`` bars so a long tail
    without any new bucket close cannot propagate a stale value forever.
    """
    n = 60
    close = pd.Series(100.0 + np.arange(n) * 0.1)
    volume = pd.Series(np.ones(n))
    # After a brief streak of full bars at the start, the rest of the series
    # has zero volume (no new buckets close), so a stale VPIN value would
    # otherwise propagate without bound.
    volume.iloc[20:] = 0.0
    W = 4
    out = vpin(close, volume, n_buckets=20, window=W)
    # Pick the last bar carrying a finite VPIN and confirm forward-fill stops
    # at most ``window`` bars later.
    finite = out[out.notna()]
    if len(finite) == 0:
        pytest.skip("no finite VPIN produced under this configuration")
    last_finite_pos = finite.index[-1]
    # Bars beyond last_finite_pos + W must remain NaN.
    far_pos = last_finite_pos + W + 1
    if far_pos < len(out):
        assert out.iloc[far_pos:].isna().all(), (
            "VPIN ffill exceeded the configured window bound"
        )


def test_vpin_aligned_at_window_right_edge():
    """Construct a deterministic series where every bucket spans exactly one
    bar. With window=W, the first finite VPIN must appear at bar (W-1), and
    its value must equal the mean of the first W per-bucket imbalances.
    """
    # Equal volume per bar so each bar = one bucket.
    n = 50
    close = pd.Series(100.0 + np.arange(n) * 0.1)  # all uptick => sign = +1
    volume = pd.Series(np.ones(n))
    n_buckets = n  # bucket_size = 1.0 => each bar closes exactly one bucket

    W = 5
    out = vpin(close, volume, n_buckets=n_buckets, window=W)
    # Per-bucket imbalance for an all-uptick series after the first bar
    # is |buy - sell| / bucket_size = 1.0 (the first bar carries sign 0
    # because tick_rule has no prior, contributing 0/1 = 0).
    # So per-bucket imbalances are [0, 1, 1, 1, ..., 1].
    # Rolling mean over the first W=5 buckets = (0 + 1 + 1 + 1 + 1) / 5 = 0.8.
    # That value must land at bar index W-1 = 4 (the right-edge bucket close).
    assert out.iloc[W - 1] == pytest.approx(0.8, abs=1e-9)
    # Bars before W-1 must remain NaN (no completed window yet).
    assert out.iloc[: W - 1].isna().all()
    # After the warmup, all subsequent bars must be 1.0 (rolling over 1's).
    after = out.iloc[W:].dropna()
    np.testing.assert_allclose(after.values, 1.0, atol=1e-9)
