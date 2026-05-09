"""Tests for quantforge.research.hypothesis_framework."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from aurora.research.hypothesis_framework import (
    Hypothesis,
    HypothesisResult,
    HypothesisTester,
)


def _all_long(prices: pd.Series) -> np.ndarray:
    return np.ones(len(prices))


def _all_flat(prices: pd.Series) -> np.ndarray:
    return np.zeros(len(prices))


def test_tester_basic_run(synthetic_prices_daily):
    h = Hypothesis(name="sharpe_pos", description="Sharpe > 0",
                   metric="sharpe", threshold=0.0, alternative="greater")
    t = HypothesisTester(n_bootstrap=50)
    res = t.test(h, synthetic_prices_daily, _all_long)
    assert isinstance(res, HypothesisResult)
    assert 0.0 < res.p_value <= 1.0
    assert res.n_bootstrap == 50


def test_tester_calmar_metric(synthetic_prices_daily):
    h = Hypothesis(name="calmar_pos", description="Calmar > 0",
                   metric="calmar", threshold=0.0)
    t = HypothesisTester(n_bootstrap=30)
    res = t.test(h, synthetic_prices_daily, _all_long)
    assert res.observed is not None
    assert res.hypothesis.metric == "calmar"


def test_tester_battery_returns_one_per_hypo(synthetic_prices_daily):
    hs = [
        Hypothesis(name="s", description="", metric="sharpe", threshold=0.0),
        Hypothesis(name="c", description="", metric="cagr", threshold=0.0),
    ]
    t = HypothesisTester(n_bootstrap=30)
    out = t.test_battery(hs, synthetic_prices_daily, _all_long)
    assert len(out) == 2
    assert out[0].hypothesis.metric == "sharpe"
    assert out[1].hypothesis.metric == "cagr"


def test_tester_invalid_metric_raises(synthetic_prices_daily):
    h = Hypothesis(name="x", description="", metric="alpha_xyz", threshold=0.0)
    t = HypothesisTester(n_bootstrap=20)
    with pytest.raises(ValueError):
        t.test(h, synthetic_prices_daily, _all_long)


def test_tester_two_sided(synthetic_prices_daily):
    h = Hypothesis(name="t", description="two", metric="sharpe",
                   threshold=0.0, alternative="two-sided")
    t = HypothesisTester(n_bootstrap=40)
    res = t.test(h, synthetic_prices_daily, _all_long)
    assert 0.0 < res.p_value <= 1.0


def test_tester_rejection_flag(synthetic_prices_daily):
    h = Hypothesis(name="impossible", description="", metric="sharpe",
                   threshold=999.0, alternative="greater")
    t = HypothesisTester(n_bootstrap=30)
    res = t.test(h, synthetic_prices_daily, _all_long)
    # Threshold 999 -> observed should not exceed it -> not rejected
    assert res.rejected_h0 is False


def test_tester_invalid_constructor():
    with pytest.raises(ValueError):
        HypothesisTester(n_bootstrap=1)
    with pytest.raises(ValueError):
        HypothesisTester(block_len=0)
    with pytest.raises(ValueError):
        HypothesisTester(alpha=1.5)
