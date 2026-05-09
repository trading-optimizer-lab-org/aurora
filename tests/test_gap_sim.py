"""Tests for quantforge.validation.gap_sim."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from aurora.core.seed import set_global_seed
from aurora.core.costs import ZERO_costs
from aurora.strategies.library.ma_cross import MACross
from aurora.validation.gap_sim import gap_sim, GapSimResult


@pytest.fixture
def fake_prices():
    set_global_seed(42)
    idx = pd.date_range("2010-01-01", periods=2000, freq="B")
    rets = np.random.default_rng(42).normal(0.0005, 0.012, 2000)
    p = 100 * np.cumprod(1.0 + rets)
    return pd.Series(p, index=idx, name="FAKE")


def _factory():
    return lambda: MACross(fast=10, slow=50)


def test_basic(fake_prices):
    """Returns a GapSimResult dataclass with expected shapes."""
    set_global_seed(42)
    res = gap_sim(_factory(), fake_prices, costs=ZERO_costs,
                  n_samples=10, n_gaps_per_path=3, gap_size_pct_max=0.03)
    assert isinstance(res, GapSimResult)
    assert res.n_samples == 10
    assert res.n_gaps_per_path == 3
    assert res.gap_size_pct_max == 0.03
    assert res.perturbed_calmars.shape == (10,)
    assert res.perturbed_mdds.shape == (10,)
    assert isinstance(res.base_calmar, float)
    assert isinstance(res.base_mdd, float)


def test_no_gaps_zero_perturb(fake_prices):
    """With n_gaps=0, perturbed paths are identical to base."""
    set_global_seed(42)
    res = gap_sim(_factory(), fake_prices, costs=ZERO_costs,
                  n_samples=5, n_gaps_per_path=0, gap_size_pct_max=0.05)
    assert np.allclose(res.perturbed_calmars, res.base_calmar)
    assert np.allclose(res.perturbed_mdds, res.base_mdd)


def test_large_gaps_hurt_mdd(fake_prices):
    """Very large gaps (~20%) produce many MDDs worse than base."""
    set_global_seed(42)
    res = gap_sim(_factory(), fake_prices, costs=ZERO_costs,
                  n_samples=30, n_gaps_per_path=8, gap_size_pct_max=0.20)
    # mdd is negative pct; "worse" = more negative
    n_worse = int(np.sum(res.perturbed_mdds < res.base_mdd))
    # at least some perturbed paths should be worse than base
    assert n_worse >= 5, f"expected >= 5 paths with worse MDD, got {n_worse}"


def test_reproducibility(fake_prices):
    """Same seed_name + global seed => identical result."""
    set_global_seed(42)
    res1 = gap_sim(_factory(), fake_prices, costs=ZERO_costs,
                   n_samples=10, n_gaps_per_path=4, gap_size_pct_max=0.05,
                   seed_name="repro_test")
    set_global_seed(42)
    res2 = gap_sim(_factory(), fake_prices, costs=ZERO_costs,
                   n_samples=10, n_gaps_per_path=4, gap_size_pct_max=0.05,
                   seed_name="repro_test")
    assert np.allclose(res1.perturbed_calmars, res2.perturbed_calmars)
    assert np.allclose(res1.perturbed_mdds, res2.perturbed_mdds)


def test_passes_threshold(fake_prices):
    """Small gaps + a robust trend strategy => passes() True under loose thresholds."""
    set_global_seed(42)
    res = gap_sim(_factory(), fake_prices, costs=ZERO_costs,
                  n_samples=20, n_gaps_per_path=2, gap_size_pct_max=0.005)
    # Loose thresholds: small gaps shouldn't crater anything
    assert res.passes(max_calmar_drop_pct=80.0, max_mdd_increase_pct=200.0)
