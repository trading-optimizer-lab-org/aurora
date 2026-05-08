"""Tests for quantforge.research.strategy_zoo."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from quantforge.research.strategy_zoo import StrategyZoo, ZooEntry
from quantforge.strategies.base import Strategy


def test_zoo_has_at_least_50_strategies():
    n = StrategyZoo.count()
    assert n >= 50, f"zoo has only {n} entries"


def test_zoo_list_returns_zooentries():
    items = StrategyZoo.list_strategies()
    assert all(isinstance(e, ZooEntry) for e in items)
    assert all(e.name and e.family and e.cls for e in items)


def test_zoo_get_unknown_raises():
    with pytest.raises(KeyError):
        StrategyZoo.get("nonexistent_strategy_zzz")


def test_zoo_instantiate_returns_strategy():
    s = StrategyZoo.instantiate("buy_and_hold")
    assert isinstance(s, Strategy)


def test_zoo_instantiate_signal_runs(synthetic_prices_daily):
    s = StrategyZoo.instantiate("buy_and_hold")
    sig = s.signals(synthetic_prices_daily)
    assert sig.shape == (len(synthetic_prices_daily),)
    assert np.allclose(sig, 1.0)


def test_zoo_families_and_grouping():
    fams = StrategyZoo.families()
    assert "momentum" in fams
    assert "mean_rev" in fams
    mom = StrategyZoo.by_family("momentum")
    assert len(mom) >= 4
    for e in mom:
        assert e.family == "momentum"


def test_zoo_each_strategy_can_run(synthetic_prices_daily):
    """Smoke-test: every zoo entry should produce a finite signal vector."""
    for entry in StrategyZoo.list_strategies():
        s = StrategyZoo.instantiate(entry.name)
        sig = s.signals(synthetic_prices_daily)
        assert sig.shape == (len(synthetic_prices_daily),), entry.name
        assert not np.isnan(sig).any(), entry.name
        assert (sig >= -1.0 - 1e-9).all() and (sig <= 1.0 + 1e-9).all(), entry.name
