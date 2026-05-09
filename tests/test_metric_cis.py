"""Tests for analytics.metric_cis (R104)."""
from __future__ import annotations

import numpy as np
import pytest

from aurora.analytics.metric_cis import (
    MetricCI,
    MetricCIBundle,
    bootstrap_metric_cis,
)


def _gbm_rets(seed: int, n: int = 1000, drift: float = 0.0005,
              vol: float = 0.01) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(drift, vol, n)


def test_bundle_returns_seven_metrics():
    rets = _gbm_rets(seed=1)
    bundle = bootstrap_metric_cis(rets, n_resamples=100)
    assert isinstance(bundle, MetricCIBundle)
    for name in ("sharpe", "sortino", "calmar", "cagr", "mdd", "win_rate",
                 "profit_factor"):
        ci: MetricCI = getattr(bundle, name)
        assert isinstance(ci, MetricCI)
        assert ci.name == name
        assert ci.n_resamples == 100


def test_sharpe_ci_is_an_interval():
    rets = _gbm_rets(seed=1)
    bundle = bootstrap_metric_cis(rets, n_resamples=200, alpha=0.05)
    sh = bundle.sharpe
    assert np.isfinite(sh.lower)
    assert np.isfinite(sh.upper)
    assert sh.lower <= sh.upper
    assert sh.alpha == 0.05


def test_includes_zero_helper():
    # Zero-mean returns -> Sharpe CI should bracket zero.
    rets = _gbm_rets(seed=2, drift=0.0, vol=0.01)
    bundle = bootstrap_metric_cis(rets, n_resamples=300)
    assert bundle.sharpe.includes_zero


def test_block_bootstrap_runs_without_error():
    rets = _gbm_rets(seed=1)
    bundle = bootstrap_metric_cis(rets, n_resamples=100, block_size=21)
    assert np.isfinite(bundle.sharpe.point)


def test_invalid_alpha_raises():
    rets = _gbm_rets(seed=1)
    with pytest.raises(ValueError):
        bootstrap_metric_cis(rets, alpha=0.0)
    with pytest.raises(ValueError):
        bootstrap_metric_cis(rets, alpha=1.5)


def test_seed_makes_run_reproducible():
    rets = _gbm_rets(seed=1)
    a = bootstrap_metric_cis(rets, n_resamples=100, seed=42)
    b = bootstrap_metric_cis(rets, n_resamples=100, seed=42)
    assert a.sharpe.lower == b.sharpe.lower
    assert a.sharpe.upper == b.sharpe.upper
