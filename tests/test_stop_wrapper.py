"""Tests for StopWrapper strategy."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from quantforge.strategies.base import Strategy, StrategySpec
from quantforge.strategies.library import StopWrapper, MACross, BollingerMR
from quantforge.validation.lookahead_check import runtime_lookahead_check


class _AlwaysLong(Strategy):
    """Dummy: signals = +1 forever."""

    def signals(self, prices: pd.Series) -> np.ndarray:
        return np.ones(len(prices))


class _AlwaysShort(Strategy):
    """Dummy: signals = -1 forever."""

    def signals(self, prices: pd.Series) -> np.ndarray:
        return -np.ones(len(prices))


@pytest.fixture
def fake_prices():
    rng = np.random.default_rng(42)
    idx = pd.date_range("2010-01-01", periods=500, freq="B")
    rets = rng.normal(0.0005, 0.012, 500)
    p = 100 * np.cumprod(1.0 + rets)
    return pd.Series(p, index=idx, name="FAKE")


def test_passthrough_no_trigger():
    """Base always +1, prices flat: stop never hits, signals == base."""
    n = 60
    p = np.full(n, 100.0)
    series = pd.Series(p, index=pd.date_range("2020-01-01", periods=n, freq="B"))
    base = _AlwaysLong()
    w = StopWrapper(base, stop_pct=0.05, take_pct=0.20, lockout=5)
    sig = w.signals(series)
    base_sig = base.signals(series)
    assert np.allclose(sig, base_sig)


def test_stop_loss_triggers():
    """Synthetic price drops -10% from entry, stop=5% -> exit on the drop bar."""
    n = 30
    p = np.full(n, 100.0)
    p[20] = 90.0  # -10% drop on bar 20
    series = pd.Series(p, index=pd.date_range("2020-01-01", periods=n, freq="B"))
    base = _AlwaysLong()
    w = StopWrapper(base, stop_pct=0.05, take_pct=0.50, lockout=5)
    sig = w.signals(series)
    # entry on bar 0, stop fires on bar 20
    assert sig[0] == 1.0
    assert sig[19] == 1.0  # still in before drop bar
    assert sig[20] == 0.0  # stop fires here


def test_take_profit_triggers():
    """Synthetic price up +25% from entry, take=20% -> exit."""
    n = 30
    p = np.full(n, 100.0)
    p[15] = 125.0  # +25% on bar 15
    series = pd.Series(p, index=pd.date_range("2020-01-01", periods=n, freq="B"))
    base = _AlwaysLong()
    w = StopWrapper(base, stop_pct=0.10, take_pct=0.20, lockout=5)
    sig = w.signals(series)
    assert sig[0] == 1.0
    assert sig[14] == 1.0
    assert sig[15] == 0.0  # take-profit fires


def test_lockout_blocks_reentry():
    """Stop hits at i=10, lockout=5 -> no entry until i>=16."""
    n = 30
    p = np.full(n, 100.0)
    p[10] = 90.0  # -10% drop on bar 10 -> stop fires
    # after that, prices stay flat at 90 -> base says +1, but lockout blocks
    p[11:] = 90.0
    series = pd.Series(p, index=pd.date_range("2020-01-01", periods=n, freq="B"))
    base = _AlwaysLong()
    w = StopWrapper(base, stop_pct=0.05, take_pct=0.50, lockout=5)
    sig = w.signals(series)
    # stop fires on bar 10
    assert sig[10] == 0.0
    # lockout active for bars 11..15 (lockout=5 -> until_idx = 10+1+5 = 16)
    for i in range(11, 16):
        assert sig[i] == 0.0, f"expected lockout at bar {i}, got {sig[i]}"
    # bar 16 onwards: re-entry allowed
    assert sig[16] == 1.0


def test_short_stop():
    """Short position, price rises +5%, stop=5% -> exit."""
    n = 30
    p = np.full(n, 100.0)
    p[10] = 105.0  # +5% rise -> for short, ret = -5% -> stop fires at exactly stop_pct
    series = pd.Series(p, index=pd.date_range("2020-01-01", periods=n, freq="B"))
    base = _AlwaysShort()
    w = StopWrapper(base, stop_pct=0.05, take_pct=0.50, lockout=5)
    sig = w.signals(series)
    assert sig[0] == -1.0
    assert sig[9] == -1.0
    assert sig[10] == 0.0  # stop fires at 5% adverse


def test_no_lookahead(fake_prices):
    base = MACross(fast=10, slow=30)
    w = StopWrapper(base, stop_pct=0.05, take_pct=0.20, lockout=5)
    rep = runtime_lookahead_check(w.signals, fake_prices)
    assert rep.runtime_violation == False


def test_spec_ranges():
    spec = StopWrapper.spec()
    assert isinstance(spec, StrategySpec)
    assert spec.name == "StopWrapper"
    assert spec.param_ranges["stop_pct"] == (0.01, 0.10)
    assert spec.param_ranges["take_pct"] == (0.05, 0.50)
    assert spec.param_ranges["lockout"] == (0, 20)
    assert spec.params["stop_pct"] == 0.05
    assert spec.params["take_pct"] == 0.20
    assert spec.params["lockout"] == 5


def test_with_bollinger_base(fake_prices):
    """Smoke test: wrap BollingerMR, output is valid."""
    base = BollingerMR(period=20, num_std=2.0)
    w = StopWrapper(base, stop_pct=0.05, take_pct=0.20, lockout=5)
    sig = w.signals(fake_prices)
    assert len(sig) == len(fake_prices)
    assert np.all(np.abs(sig) <= 1.0)
    assert not np.any(np.isnan(sig))


def test_stop_is_wrapper_attr():
    """The wrapper exposes is_wrapper = True so GA-discovery code can skip it."""
    assert getattr(StopWrapper, "is_wrapper", False) is True


def test_stop_runnable_via_run_ga(fake_prices):
    """Calling run_ga on the wrapper raises a clear error rather than failing
    deep inside DEAP with a TypeError about a missing `base` positional arg.
    """
    pytest.importorskip("deap")
    from quantforge.ga.runner import run_ga, GAConfig
    from quantforge.ga.fitness import multi_objective_fitness_is

    cfg = GAConfig(population=4, generations=1, seed=1, backend="sequential")
    with pytest.raises(TypeError, match="is_wrapper"):
        run_ga(StopWrapper, fake_prices, None, multi_objective_fitness_is,
               cfg, verbose=False)


def test_stop_requires_base():
    """Constructing without a base must raise."""
    with pytest.raises(TypeError, match="base"):
        StopWrapper()


@pytest.mark.parametrize("lockout", [1, 3, 5, 10])
def test_stop_lockout_duration_correct(lockout):
    """Lockout must block re-entry for exactly `lockout` bars after stop."""
    n = 50
    p = np.full(n, 100.0)
    stop_bar = 10
    p[stop_bar] = 90.0  # -10% drop -> stop fires at stop_bar
    p[stop_bar + 1:] = 90.0  # flat after, base=+1, but lockout blocks
    series = pd.Series(p, index=pd.date_range("2020-01-01", periods=n, freq="B"))
    base = _AlwaysLong()
    w = StopWrapper(base, stop_pct=0.05, take_pct=0.50, lockout=lockout)
    sig = w.signals(series)
    # Stop fires at stop_bar
    assert sig[stop_bar] == 0.0, f"stop must fire at bar {stop_bar}"
    # Bars [stop_bar+1, stop_bar+lockout] must be locked (zero)
    for i in range(stop_bar + 1, stop_bar + lockout + 1):
        assert sig[i] == 0.0, \
            f"lockout={lockout}: expected zero at bar {i}, got {sig[i]}"
    # Bar stop_bar+lockout+1 must allow re-entry
    if stop_bar + lockout + 1 < n:
        assert sig[stop_bar + lockout + 1] == 1.0, \
            f"lockout={lockout}: expected re-entry at bar {stop_bar + lockout + 1}"
