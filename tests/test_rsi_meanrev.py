"""Tests for RSIMeanRev strategy.

Covers Wilder vs EMA smoothing, signal shape, anti-lookahead, and back-compat.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from quantforge.strategies.library import RSIMeanRev
from quantforge.strategies.library.rsi_meanrev import _rsi
from quantforge.strategies.base import StrategySpec


@pytest.fixture
def fake_prices():
    rng = np.random.default_rng(42)
    idx = pd.date_range("2010-01-01", periods=500, freq="B")
    rets = rng.normal(0.0005, 0.012, 500)
    p = 100.0 * np.cumprod(1.0 + rets)
    return pd.Series(p, index=idx, name="FAKE")


def test_signals_shape(fake_prices):
    s = RSIMeanRev(period=2, oversold=10, overbought=90)
    sig = s.signals(fake_prices)
    assert isinstance(sig, np.ndarray)
    assert len(sig) == len(fake_prices)
    assert np.all(np.abs(sig) <= 1.0)
    assert not np.any(np.isnan(sig))


def test_default_smoothing_is_wilder():
    s = RSIMeanRev()
    assert s.smoothing == "wilder"


def test_wilder_smoothing_recursion():
    """Verify the recursive form avg = (avg*(n-1) + new) / n.

    For Wilder smoothing, after the seed mean over the first n diffs, the
    next average is exactly avg_seed*(n-1)/n + diff/n.
    """
    n = 5
    rng = np.random.default_rng(0)
    p = 100.0 * np.cumprod(1.0 + rng.normal(0.0, 0.01, 50))
    diffs = np.diff(p)
    g = np.where(diffs > 0, diffs, 0.0)
    l = np.where(diffs < 0, -diffs, 0.0)
    seed_g = g[:n].mean()
    seed_l = l[:n].mean()
    # After one Wilder step the running average uses diff at index n
    expected_g = (seed_g * (n - 1) + g[n]) / n
    expected_l = (seed_l * (n - 1) + l[n]) / n
    if expected_l == 0:
        expected_rsi = 100.0
    else:
        expected_rsi = 100.0 - 100.0 / (1.0 + expected_g / expected_l)
    rsi = _rsi(p, n, smoothing="wilder")
    # rsi[n] should match the seed average; rsi[n+1] should match one step ahead
    assert np.isfinite(rsi[n + 1])
    assert abs(rsi[n + 1] - expected_rsi) < 1e-12


def test_wilder_vs_ema_differs():
    """Wilder (alpha=1/n) and EMA (alpha=2/(n+1)) must produce different RSI."""
    rng = np.random.default_rng(1)
    p = 100.0 * np.cumprod(1.0 + rng.normal(0.0, 0.01, 200))
    rsi_w = _rsi(p, 14, smoothing="wilder")
    rsi_e = _rsi(p, 14, smoothing="ema")
    # both finite over the post-seed range
    mask = np.isfinite(rsi_w) & np.isfinite(rsi_e)
    assert mask.sum() > 50
    # they must not be identical everywhere
    assert not np.allclose(rsi_w[mask], rsi_e[mask])


def test_ema_backward_compat_path():
    """Passing smoothing='ema' must produce a finite, sane RSI series."""
    rng = np.random.default_rng(2)
    p = 100.0 * np.cumprod(1.0 + rng.normal(0.0, 0.01, 100))
    rsi = _rsi(p, 14, smoothing="ema")
    finite = rsi[np.isfinite(rsi)]
    assert finite.size > 0
    assert (finite >= 0).all() and (finite <= 100).all()


def test_invalid_smoothing_raises():
    with pytest.raises(ValueError, match="smoothing"):
        RSIMeanRev(smoothing="garbage")
    with pytest.raises(ValueError, match="smoothing"):
        _rsi(np.array([1.0, 2.0, 3.0, 4.0]), 2, smoothing="garbage")


def test_oversold_triggers_long():
    # Monotone down then up: end of decline -> low RSI -> long
    p = np.linspace(100.0, 80.0, 30)
    series = pd.Series(p, index=pd.date_range("2020-01-01", periods=30, freq="B"))
    s = RSIMeanRev(period=2, oversold=20, overbought=80, allow_short=False)
    sig = s.signals(series)
    # Last bar should be long since prices monotonically dropped
    assert sig[-1] == 1.0


def test_no_short_when_disabled(fake_prices):
    s = RSIMeanRev(period=2, oversold=10, overbought=90, allow_short=False)
    sig = s.signals(fake_prices)
    assert np.all(sig >= 0.0)


def test_no_lookahead(fake_prices):
    """Truncating the series must not change earlier signals."""
    s = RSIMeanRev(period=14, oversold=30, overbought=70)
    sig_full = s.signals(fake_prices)
    k = 200
    sig_trunc = s.signals(fake_prices.iloc[:k])
    assert np.allclose(sig_trunc, sig_full[:k])


def test_spec_has_smoothing():
    spec = RSIMeanRev.spec()
    assert isinstance(spec, StrategySpec)
    assert spec.params["smoothing"] == "wilder"
    assert spec.param_ranges["smoothing"] == ["wilder", "ema"]


def test_rsi_wilder_seed_canonical():
    """Wilder seed at i=n must equal mean of the first n price diffs.

    Verifies no off-by-one: the seed includes g[n-1] (the diff into bar n)
    rather than dropping bar n-1.
    """
    n = 5
    rng = np.random.default_rng(123)
    p = 100.0 * np.cumprod(1.0 + rng.normal(0.0, 0.01, 50))
    diffs = np.diff(p)
    g = np.where(diffs > 0, diffs, 0.0)
    l = np.where(diffs < 0, -diffs, 0.0)
    seed_g = g[:n].mean()  # mean of diffs 0..n-1 (inclusive)
    seed_l = l[:n].mean()
    # Verify g[n-1] (the diff from bar n-1 to bar n) IS in the seed.
    assert abs(seed_g * n - g[:n].sum()) < 1e-12
    assert g[n - 1] in g[:n]  # presence check
    rsi = _rsi(p, n, smoothing="wilder")
    # rsi[n] = formula on (seed_g, seed_l) with no update step.
    if seed_l == 0:
        expected = 100.0
    else:
        expected = 100.0 - 100.0 / (1.0 + seed_g / seed_l)
    assert np.isfinite(rsi[n])
    assert abs(rsi[n] - expected) < 1e-12, (
        f"Wilder seed off by one: rsi[n]={rsi[n]}, expected {expected} "
        f"(seed_g={seed_g}, seed_l={seed_l})"
    )


def test_rsi_meanrev_oversold_overbought_swap():
    """If oversold > overbought is passed, the ctor must swap them rather
    than producing a silently degenerate strategy.
    """
    s = RSIMeanRev(period=2, oversold=80, overbought=20)
    assert s.oversold == 20
    assert s.overbought == 80
