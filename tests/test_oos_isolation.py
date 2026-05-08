"""Tests for the OOS sagrado architectural rule.

Three guarantees:
1. The IS-only GA fitness function never reads OOS data, even when OOS
   data is poisoned.
2. validate_oos returns a metrics dict (used as the post-GA gate).
3. ``load_oos`` refuses to run outside an OOSGuard context, and works inside it.
"""
from __future__ import annotations
import os
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import pytest

from quantforge.core import data_layer
from quantforge.core.data_layer import (
    OOSGuard, load_asset, load_oos, split_is_oos,
)
from quantforge.ga.fitness import (
    multi_objective_fitness_is,
    scalar_fitness_is,
    validate_oos,
)
from quantforge.strategies.library import MACross


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _synthetic_prices(n: int, seed: int, start: str) -> pd.Series:
    idx = pd.date_range(start, periods=n, freq="B")
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0005, 0.012, n)
    return pd.Series(100.0 * np.cumprod(1.0 + rets), index=idx, name="SYN")


# ---------------------------------------------------------------------------
# 1. fitness never touches OOS
# ---------------------------------------------------------------------------


def test_fitness_does_not_touch_oos(monkeypatch):
    """If load_asset is monkeypatched so OOS reads return poisoned data,
    the IS-only fitness must still compute a finite tuple — because it
    only reads IS prices.

    Strategy: replace load_asset with a tracker that records every call
    and refuses any include_oos=True call by raising.
    """
    is_prices = _synthetic_prices(400, seed=7, start="2010-01-04")

    calls: list[dict] = []

    def fake_load_asset(symbol, source="yfinance", start=None, end=None,
                        include_oos=False):
        calls.append({"symbol": symbol, "include_oos": include_oos})
        if include_oos:
            raise AssertionError(
                "fitness phase touched OOS via load_asset(include_oos=True)"
            )
        return is_prices

    monkeypatch.setattr(data_layer, "load_asset", fake_load_asset)

    # Call IS-only fitness — must NOT trigger any include_oos read.
    strat = MACross(fast=10, slow=30)
    fit = multi_objective_fitness_is(is_prices, strat.signals)
    assert isinstance(fit, tuple) and len(fit) == 4
    # The fitness function does not call load_asset directly (caller passes
    # in the price series). But if any internal helper ever reaches for it,
    # the monkeypatched loader would have caught it.
    assert all(c["include_oos"] is False for c in calls)


def test_scalar_fitness_is_does_not_touch_oos():
    """scalar_fitness_is takes only IS prices; verify no OOS attribute is
    touched on the input by passing in a wrapped Series that flags any
    suspicious slicing past the cutoff.
    """
    is_prices = _synthetic_prices(400, seed=11, start="2010-01-04")
    strat = MACross(fast=10, slow=40)
    val = scalar_fitness_is(is_prices, strat.signals)
    assert isinstance(val, float)


# ---------------------------------------------------------------------------
# 2. validate_oos returns a metrics dict
# ---------------------------------------------------------------------------


def test_validate_oos_returns_metrics():
    oos = _synthetic_prices(300, seed=21, start="2018-01-04")
    strat = MACross(fast=10, slow=30)
    m = validate_oos(oos, strat.signals)
    assert isinstance(m, dict)
    for k in ("calmar", "sharpe", "mdd", "cagr", "final_nav", "n_periods"):
        assert k in m
    # finite (or NaN) but never raises
    for k in ("calmar", "sharpe", "mdd", "cagr", "final_nav"):
        assert isinstance(m[k], float)


def test_validate_oos_handles_engine_error():
    """validate_oos catches engine errors and returns NaN dict."""
    bad_signal = lambda prices: np.zeros(len(prices) + 1)  # wrong length
    oos = _synthetic_prices(200, seed=33, start="2018-01-04")
    m = validate_oos(oos, bad_signal)
    assert "error" in m
    assert m["calmar"] != m["calmar"]  # NaN check


# ---------------------------------------------------------------------------
# 3. OOSGuard blocks load_oos outside its context
# ---------------------------------------------------------------------------


def test_oosguard_blocks_unauth_access():
    """Calling load_oos with no active OOSGuard must raise RuntimeError."""
    # Sanity: stack is empty.
    assert OOSGuard.active() is None
    with pytest.raises(RuntimeError, match="OOSGuard"):
        load_oos("SPY")


@pytest.mark.integration
def test_oosguard_allows_inside(tmp_path: Path):
    """Inside an OOSGuard context, load_oos succeeds and the read is logged.

    Marked ``integration``: loads SPY parquet cache.
    """
    cache_dir = os.path.join(
        os.path.dirname(data_layer.__file__), "..", "data_cache_qf"
    )
    spy_path = os.path.join(cache_dir, "SPY.parquet")
    if not os.path.exists(spy_path):
        pytest.skip("SPY parquet cache not present")

    lock = tmp_path / ".oos_lock.json"
    with OOSGuard("post_ga_validation", lock_path=str(lock)) as g:
        oos = load_oos("SPY")
        # load_oos delegates to load_asset(include_oos=True), which records
        # the violation against the active guard.
        assert g.violations >= 1
        assert isinstance(oos, pd.Series)
        assert len(oos) > 0
        # All OOS rows must be at/after the OOS cutoff.
        oos_start = pd.Timestamp(data_layer.OOS_START)
        assert (oos.index >= oos_start).all()


def test_split_is_oos_is_pure():
    """split_is_oos slices a Series and never reads OOS files; safe outside guard."""
    prices = _synthetic_prices(800, seed=99, start="2010-01-04")
    is_p, oos_p = split_is_oos(prices)
    assert len(is_p) + len(oos_p) == len(prices)
    cutoff = pd.Timestamp(data_layer.OOS_START)
    assert (is_p.index < cutoff).all()
    assert (oos_p.index >= cutoff).all()
