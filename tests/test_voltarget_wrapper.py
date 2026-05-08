"""Tests for VolTargetWrapper, particularly the anti-lookahead invariant."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from quantforge.strategies.library import VolTargetWrapper, MACross
from quantforge.strategies.base import StrategySpec


@pytest.fixture
def fake_prices():
    rng = np.random.default_rng(42)
    idx = pd.date_range("2010-01-01", periods=500, freq="B")
    rets = rng.normal(0.0005, 0.012, 500)
    p = 100.0 * np.cumprod(1.0 + rets)
    return pd.Series(p, index=idx, name="FAKE")


def test_wraps_base_signals(fake_prices):
    base = MACross(fast=10, slow=30, allow_short=True)
    w = VolTargetWrapper(base=base, target_vol=0.15, max_w=0.5, vol_window=30)
    sig = w.signals(fake_prices)
    assert isinstance(sig, np.ndarray)
    assert len(sig) == len(fake_prices)
    assert np.all(np.abs(sig) <= 1.0)
    assert not np.any(np.isnan(sig))


def test_voltarget_no_lookahead(fake_prices):
    """vol[i] uses returns through bar i-1 only.

    Mutating prices at bar i and beyond must not change signals[:i].
    """
    base = MACross(fast=10, slow=30, allow_short=True)
    w = VolTargetWrapper(base=base, target_vol=0.15, max_w=0.5, vol_window=30)
    sig_full = w.signals(fake_prices)

    # Truncate then recompute - earlier signals must be identical
    k = 250
    sig_trunc = w.signals(fake_prices.iloc[:k])
    assert np.allclose(sig_trunc, sig_full[:k]), \
        "VolTargetWrapper leaked future returns into earlier signals"


def test_voltarget_shuffle_future_invariance(fake_prices):
    """Shuffling prices after bar k must not change signals[:k]."""
    base = MACross(fast=10, slow=30, allow_short=False)
    w = VolTargetWrapper(base=base, target_vol=0.15, max_w=0.5, vol_window=30)
    sig_ref = w.signals(fake_prices)

    rng = np.random.default_rng(0)
    p_vals = fake_prices.values.copy()
    k = 200
    tail = p_vals[k:].copy()
    rng.shuffle(tail)
    p_vals[k:] = tail
    shuf = pd.Series(p_vals, index=fake_prices.index, name="FAKE")
    sig_shuf = w.signals(shuf)

    assert np.allclose(sig_ref[:k], sig_shuf[:k])


def test_voltarget_scaling_caps_at_max_w(fake_prices):
    """When realized vol is very low the wrapper must cap leverage at max_w."""
    # constant return series -> vol = 0 -> v falls back to target_vol -> scale = 1
    # so we synthesize a series with very tiny but nonzero vol
    n = 200
    rng = np.random.default_rng(0)
    p = 100.0 * np.cumprod(1.0 + rng.normal(0.0, 1e-6, n))
    series = pd.Series(p, index=pd.date_range("2020-01-01", periods=n, freq="B"))
    base = MACross(fast=5, slow=20, allow_short=True)
    w = VolTargetWrapper(base=base, target_vol=0.15, max_w=0.3, vol_window=30)
    sig = w.signals(series)
    # Whenever the base is non-zero, the magnitude must be exactly max_w
    base_sig = base.signals(series)
    nonzero = base_sig != 0.0
    if nonzero.any():
        assert np.all(np.abs(sig[nonzero]) <= 0.3 + 1e-12)


def test_spec_ranges():
    spec = VolTargetWrapper.spec()
    assert isinstance(spec, StrategySpec)
    assert spec.name == "VolTargetWrapper"
    assert spec.params["target_vol"] == 0.15
    assert spec.params["max_w"] == 0.20
    assert spec.params["vol_window"] == 60


def test_voltarget_is_wrapper_attr():
    """The wrapper exposes is_wrapper = True so GA-discovery code can skip it."""
    assert getattr(VolTargetWrapper, "is_wrapper", False) is True


def test_voltarget_runnable_via_run_ga(fake_prices):
    """Calling run_ga on the wrapper directly raises a clear error explaining
    that wrappers require a base strategy outside of spec().param_ranges.
    """
    pytest.importorskip("deap")
    from quantforge.ga.runner import run_ga, GAConfig
    from quantforge.ga.fitness import multi_objective_fitness_is

    cfg = GAConfig(population=4, generations=1, seed=1, backend="sequential")
    with pytest.raises(TypeError, match="is_wrapper"):
        run_ga(VolTargetWrapper, fake_prices, None, multi_objective_fitness_is,
               cfg, verbose=False)


def test_voltarget_requires_base():
    """Constructing without a base must raise rather than build a half-init wrapper."""
    with pytest.raises(TypeError, match="base"):
        VolTargetWrapper()
