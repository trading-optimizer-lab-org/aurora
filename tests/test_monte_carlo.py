"""Tests for quantforge.validation.monte_carlo (block bootstrap)."""
from __future__ import annotations
import numpy as np
import pytest

from aurora.core.seed import set_global_seed, child_rng
from aurora.validation.monte_carlo import (
    MCResult,
    circular_block_bootstrap,
    monte_carlo_bootstrap,
    monte_carlo_trade_reorder,
)


@pytest.fixture(autouse=True)
def _seed():
    set_global_seed(2026)


def _stationary_returns(n: int = 800, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(0.0005, 0.012, n)


# --------------------------------------------------------------------------- #
# circular_block_bootstrap                                                    #
# --------------------------------------------------------------------------- #
def test_circular_bootstrap_preserves_length():
    """Output length is exactly the requested length, regardless of T."""
    r = _stationary_returns(500)
    rng = child_rng("cb_len")
    for L in (50, 500, 1234):
        sample = circular_block_bootstrap(r, length=L, avg_block_len=10.0, rng=rng)
        assert sample.shape == (L,)


def test_circular_bootstrap_uses_wraparound():
    """A bootstrap with avg_block_len equal to ~T can wrap past index T-1
    when starting near the end. Force a deterministic wraparound by using a
    distinctive sentinel array and a manipulated starting index — verified
    here via a probabilistic check across many draws.
    """
    # Very short series with distinct values so we can detect wrap.
    r = np.arange(1, 11, dtype=float)  # 1..10
    rng = child_rng("cb_wrap")
    found_wrap = False
    # Many draws with avg_block_len > T to force wrap with high probability.
    for _ in range(200):
        sample = circular_block_bootstrap(
            r, length=20, avg_block_len=15.0, rng=rng
        )
        # Find a contiguous descent from 10 back to 1 — only possible by wrap.
        for k in range(len(sample) - 1):
            if sample[k] == 10.0 and sample[k + 1] == 1.0:
                found_wrap = True
                break
        if found_wrap:
            break
    assert found_wrap, "wraparound never observed in circular bootstrap"


def test_circular_bootstrap_seed_reproducibility():
    """Same global seed + same seed_name -> identical sample."""
    r = _stationary_returns(300)
    set_global_seed(42)
    a = circular_block_bootstrap(r, length=300, avg_block_len=12.0,
                                 rng=child_rng("repro"))
    set_global_seed(42)
    b = circular_block_bootstrap(r, length=300, avg_block_len=12.0,
                                 rng=child_rng("repro"))
    np.testing.assert_array_equal(a, b)


def test_circular_bootstrap_validates_args():
    rng = child_rng("cb_validate")
    with pytest.raises(ValueError):
        circular_block_bootstrap(np.array([]), length=10, avg_block_len=5.0, rng=rng)
    with pytest.raises(ValueError):
        circular_block_bootstrap(_stationary_returns(50), length=0,
                                 avg_block_len=5.0, rng=rng)
    with pytest.raises(ValueError):
        circular_block_bootstrap(_stationary_returns(50), length=10,
                                 avg_block_len=0.0, rng=rng)


# --------------------------------------------------------------------------- #
# monte_carlo_bootstrap                                                       #
# --------------------------------------------------------------------------- #
def test_monte_carlo_bootstrap_circular_default():
    r = _stationary_returns(600)
    res = monte_carlo_bootstrap(r, n_paths=120, block_size=15, ppy=252,
                                 seed_name="mc_circ")
    assert isinstance(res, MCResult)
    assert res.n_paths == 120
    assert np.isfinite(res.real_mdd)
    assert np.isfinite(res.p5_mdd)
    assert np.isfinite(res.p95_mdd)
    # Percentiles must be ordered: p5 <= p50 <= p95 (MDD is negative so smaller=worse)
    assert res.p5_mdd <= res.p50_mdd <= res.p95_mdd


def test_monte_carlo_bootstrap_fixed_method_still_works():
    """Backwards compat: method='fixed' takes the legacy non-circular path."""
    r = _stationary_returns(600)
    res = monte_carlo_bootstrap(r, n_paths=80, block_size=20, ppy=252,
                                 seed_name="mc_fixed", method="fixed")
    assert res.n_paths == 80
    assert np.isfinite(res.real_mdd)


def test_monte_carlo_bootstrap_method_validation():
    r = _stationary_returns(400)
    with pytest.raises(ValueError):
        monte_carlo_bootstrap(r, n_paths=10, block_size=10, method="bogus")


# --------------------------------------------------------------------------- #
# trade reorder smoke                                                         #
# --------------------------------------------------------------------------- #
def test_trade_reorder_smoke():
    """Simple alternating-weight series: produces enough trades."""
    n = 400
    rng = np.random.default_rng(11)
    rets = rng.normal(0.0004, 0.01, n)
    # 20-bar on/off pattern -> 20 segments
    weights = np.zeros(n)
    on = True
    for i in range(0, n, 20):
        if on:
            weights[i:i + 20] = 1.0
        on = not on

    res = monte_carlo_trade_reorder(weights, rets, n_paths=50, ppy=252,
                                     seed_name="mc_reorder_smoke")
    assert isinstance(res, MCResult)
    assert res.n_paths == 50
    assert np.isfinite(res.real_mdd_percentile)
