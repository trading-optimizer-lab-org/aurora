"""Tests for noise injection robustness validation."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from aurora.core.seed import set_global_seed
from aurora.core.costs import ZERO_costs
from aurora.strategies.library import MACross
from aurora.validation.noise_injection import (
    noise_injection,
    NoiseInjectionResult,
)


@pytest.fixture
def synth_prices():
    set_global_seed(42)
    idx = pd.date_range("2010-01-01", periods=1500, freq="B")
    rets = np.random.default_rng(42).normal(0.0005, 0.012, 1500)
    p = 100.0 * np.cumprod(1.0 + rets)
    return pd.Series(p, index=idx, name="SYNTH")


def _factory(fast: int = 10, slow: int = 50, allow_short: bool = True):
    def make():
        return MACross(fast=fast, slow=slow, allow_short=allow_short)
    return make


def test_basic(synth_prices):
    set_global_seed(42)
    res = noise_injection(
        _factory(), synth_prices, costs=ZERO_costs,
        n_samples=20, noise_sigma_bps=10.0,
    )
    assert isinstance(res, NoiseInjectionResult)
    assert res.n_samples == 20
    assert res.noise_sigma_bps == 10.0
    assert res.perturbed_calmars.shape == (20,)
    assert res.perturbed_sharpes.shape == (20,)
    assert res.calmar_p5 <= res.calmar_p50 <= res.calmar_p95
    assert isinstance(res.base_calmar, float)
    assert isinstance(res.base_sharpe, float)
    assert isinstance(res.calmar_drop_pct, float)


def test_low_noise_minimal_impact(synth_prices):
    set_global_seed(42)
    res = noise_injection(
        _factory(), synth_prices, costs=ZERO_costs,
        n_samples=30, noise_sigma_bps=1.0,  # 1 bp = 0.01% per bar
    )
    # With 1 bp noise, median Calmar should hardly move
    assert abs(res.calmar_drop_pct) < 5.0, (
        f"low noise should leave Calmar within 5% (got {res.calmar_drop_pct:.2f}%)"
    )


def test_high_noise_large_impact(synth_prices):
    set_global_seed(42)
    res_low = noise_injection(
        _factory(), synth_prices, costs=ZERO_costs,
        n_samples=30, noise_sigma_bps=1.0,
        seed_name="ni_low",
    )
    set_global_seed(42)
    res_high = noise_injection(
        _factory(), synth_prices, costs=ZERO_costs,
        n_samples=30, noise_sigma_bps=100.0,  # 1% per bar -> heavy distortion
        seed_name="ni_high",
    )
    # High noise should cause a strictly larger spread than low noise
    spread_low = res_low.calmar_p95 - res_low.calmar_p5
    spread_high = res_high.calmar_p95 - res_high.calmar_p5
    assert spread_high > spread_low, (
        f"high noise spread ({spread_high:.4f}) should exceed "
        f"low noise spread ({spread_low:.4f})"
    )
    # And the magnitude of Calmar drift should be larger
    assert abs(res_high.calmar_drop_pct) > abs(res_low.calmar_drop_pct)


def test_passes_threshold(synth_prices):
    set_global_seed(42)
    res = noise_injection(
        _factory(), synth_prices, costs=ZERO_costs,
        n_samples=30, noise_sigma_bps=1.0,
    )
    # Robust strategy under tiny noise should pass the 30% drop gate
    assert res.passes(max_drop_pct=30.0)


def test_reproducibility(synth_prices):
    set_global_seed(42)
    a = noise_injection(
        _factory(), synth_prices, costs=ZERO_costs,
        n_samples=15, noise_sigma_bps=10.0,
    )
    set_global_seed(42)
    b = noise_injection(
        _factory(), synth_prices, costs=ZERO_costs,
        n_samples=15, noise_sigma_bps=10.0,
    )
    assert np.allclose(a.perturbed_calmars, b.perturbed_calmars)
    assert np.allclose(a.perturbed_sharpes, b.perturbed_sharpes)
    assert a.calmar_p50 == b.calmar_p50
    assert a.calmar_drop_pct == b.calmar_drop_pct


def test_noise_injection_rejects_extreme(synth_prices):
    """noise_pct outside [-0.5, 0.5] must raise ValueError before any backtest."""
    set_global_seed(42)
    # noise_pct = -1.0 i.e. -100% (bps=-1e4). Negative bps already rejected,
    # but anything > 5000 bps must also be rejected (noise_pct > 0.5).
    with pytest.raises(ValueError):
        noise_injection(
            _factory(), synth_prices, costs=ZERO_costs,
            n_samples=2, noise_sigma_bps=10000.0,  # noise_pct = 1.0 -> > 0.5
        )

    # Negative magnitudes already caught by sigma >= 0 check.
    with pytest.raises(ValueError):
        noise_injection(
            _factory(), synth_prices, costs=ZERO_costs,
            n_samples=2, noise_sigma_bps=-100.0,
        )


def test_noise_injection_warns_on_clip(synth_prices):
    """When clipping actually occurs (price would go non-positive) a UserWarning fires."""
    import warnings

    set_global_seed(42)
    # Construct a price series with a few near-zero values so even modest noise
    # can push them non-positive on at least one path.
    idx = synth_prices.index[:200]
    base = synth_prices.values[:200].copy()
    base[100] = 1e-6  # near zero -> any negative noise pushes it below 0
    base[120] = 1e-6
    fragile = pd.Series(base, index=idx, name="FRAGILE")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        noise_injection(
            _factory(), fragile, costs=ZERO_costs,
            n_samples=5, noise_sigma_bps=4000.0,  # noise_pct=0.4: within [-0.5, 0.5]
        )

    # At least one UserWarning mentioning clipping should be emitted.
    clipping = [
        w for w in caught
        if issubclass(w.category, UserWarning)
        and "clipped" in str(w.message)
    ]
    assert clipping, "expected UserWarning when noise pushed prices non-positive"
