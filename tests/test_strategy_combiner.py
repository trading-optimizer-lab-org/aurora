"""Tests for aurora.research.strategy_combiner."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from aurora.research.strategy_combiner import (
    CombinerEntry,
    CombinerReport,
    StrategyCombiner,
)


def _all_long(prices: pd.Series) -> np.ndarray:
    return np.ones(len(prices))


def _all_flat(prices: pd.Series) -> np.ndarray:
    return np.zeros(len(prices))


def _half_long(prices: pd.Series) -> np.ndarray:
    return np.full(len(prices), 0.5)


def test_combiner_basic_search(synthetic_prices_daily):
    entries = [
        CombinerEntry("long", _all_long),
        CombinerEntry("flat", _all_flat),
    ]
    c = StrategyCombiner(n_candidates=20, metric="sharpe")
    rep = c.search(synthetic_prices_daily, entries, is_end=300)
    assert isinstance(rep, CombinerReport)
    assert "long" in rep.best_weights
    assert "flat" in rep.best_weights
    assert abs(sum(rep.best_weights.values()) - 1.0) < 1e-6


def test_combiner_oos_metric_present(synthetic_prices_daily):
    entries = [CombinerEntry("a", _all_long), CombinerEntry("b", _half_long)]
    c = StrategyCombiner(n_candidates=10, metric="calmar")
    rep = c.search(synthetic_prices_daily, entries, is_end=400)
    assert rep.metric_name == "calmar"
    # both is and oos metrics should be finite numbers
    assert isinstance(rep.is_metric, float)
    assert isinstance(rep.oos_metric, float)


def test_combiner_equal_weight_baseline(synthetic_prices_daily):
    entries = [CombinerEntry("a", _all_long), CombinerEntry("b", _all_flat)]
    c = StrategyCombiner(n_candidates=5, metric="sharpe")
    rep = c.search(synthetic_prices_daily, entries, is_end=300)
    assert isinstance(rep.equal_weight_is, float)
    assert isinstance(rep.equal_weight_oos, float)


def test_combiner_invalid_metric():
    with pytest.raises(ValueError):
        StrategyCombiner(metric="alpha")


def test_combiner_zero_candidates():
    with pytest.raises(ValueError):
        StrategyCombiner(n_candidates=0)


def test_combiner_empty_entries(synthetic_prices_daily):
    c = StrategyCombiner(n_candidates=10)
    with pytest.raises(ValueError):
        c.search(synthetic_prices_daily, [], is_end=200)


def test_combiner_invalid_is_end(synthetic_prices_daily):
    c = StrategyCombiner(n_candidates=5)
    entries = [CombinerEntry("a", _all_long)]
    with pytest.raises(ValueError):
        c.search(synthetic_prices_daily, entries, is_end=0)
    with pytest.raises(ValueError):
        c.search(synthetic_prices_daily, entries,
                 is_end=len(synthetic_prices_daily))


def test_combiner_requires_pd_series():
    c = StrategyCombiner(n_candidates=5)
    with pytest.raises(TypeError):
        c.search(np.zeros(100), [CombinerEntry("a", _all_long)], is_end=50)


def test_combiner_best_metric_at_least_equal(synthetic_prices_daily):
    """Search must never return a metric worse than the equal-weight baseline."""
    entries = [CombinerEntry("a", _all_long), CombinerEntry("b", _half_long),
               CombinerEntry("c", _all_flat)]
    c = StrategyCombiner(n_candidates=30, metric="sharpe")
    rep = c.search(synthetic_prices_daily, entries, is_end=300)
    assert rep.is_metric >= rep.equal_weight_is - 1e-9
