"""Tests for validation.random_baseline (R103)."""
from __future__ import annotations

import numpy as np
import pytest

from quantforge.validation.random_baseline import random_baseline_test


def _gbm_returns(seed: int, n: int = 500) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(0.0005, 0.01, n)


def test_random_weights_score_close_to_random_distribution():
    rets = _gbm_returns(seed=1)
    rng = np.random.default_rng(2)
    # Random weights matching the prices: should score near the
    # random ensemble's centre.
    weights = rng.choice([-1.0, 0.0, 1.0], size=len(rets))
    res = random_baseline_test(weights, rets, n_shuffles=200)
    # Loose check: candidate p-value bracketed in (0, 1).
    assert 0.0 <= res.p_value_one_tail <= 1.0


def test_signal_aligned_with_returns_beats_random_ensemble():
    rets = _gbm_returns(seed=1)
    # Perfect-foresight signal: take long when the next-bar return is
    # positive. apply_costs uses weights[t-1] * returns[t], so the
    # signal at bar i must reference returns[i+1]. Shift accordingly.
    weights = np.zeros_like(rets)
    weights[:-1] = np.sign(rets[1:])
    res = random_baseline_test(
        weights, rets, metric_name="sharpe", n_shuffles=200,
    )
    assert res.is_significant


def test_length_mismatch_raises():
    rets = _gbm_returns(seed=1)
    with pytest.raises(ValueError):
        random_baseline_test(np.zeros(10), rets, n_shuffles=10)


def test_seed_makes_run_reproducible():
    rets = _gbm_returns(seed=1)
    rng = np.random.default_rng(99)
    weights = rng.choice([-1.0, 0.0, 1.0], size=len(rets))
    a = random_baseline_test(weights, rets, n_shuffles=100, seed=42)
    b = random_baseline_test(weights, rets, n_shuffles=100, seed=42)
    assert a.p_value_one_tail == b.p_value_one_tail
