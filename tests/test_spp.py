"""Tests for validation.spp polish: grid centering and worker seed propagation."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from quantforge.core.seed import set_global_seed
from quantforge.core.costs import ZERO_costs
from quantforge.strategies.library import MACross
from quantforge.validation.spp import spp


@pytest.fixture
def synth_prices():
    set_global_seed(42)
    idx = pd.date_range("2010-01-01", periods=400, freq="B")
    rets = np.random.default_rng(42).normal(0.0005, 0.012, 400)
    p = 100.0 * np.cumprod(1.0 + rets)
    return pd.Series(p, index=idx, name="SYNTH")


def _factory_with(**kw):
    return MACross(**kw)


def test_spp_grid_centers_on_current(synth_prices):
    """When center_on='current', the integer-rounded grid for each parameter
    must straddle the user's current value rather than the (lo+hi)/2 midpoint.
    """
    set_global_seed(42)
    # midpoint of (5, 95) is 50; current value 10 is far from midpoint.
    param_ranges = {"fast": (5, 95)}
    current = {"fast": 10}

    res_current = spp(
        _factory_with, synth_prices, param_ranges,
        perturb=0.20, n_steps=3, costs=ZERO_costs,
        max_combinations=10,
        center_on="current", current_params=current,
        seed_name="spp_current",
    )

    set_global_seed(42)
    res_mid = spp(
        _factory_with, synth_prices, param_ranges,
        perturb=0.20, n_steps=3, costs=ZERO_costs,
        max_combinations=10,
        center_on="midpoint",
        seed_name="spp_mid",
    )

    # Both must produce a valid result.
    assert res_current.n_perturbations >= 1
    assert res_mid.n_perturbations >= 1

    # The current-centered grid should explore values much closer to fast=10
    # than the midpoint-centered grid (which is centered on 50). Compare the
    # perturbed_calmars Series-of-results: equality would mean centering had
    # no effect (it should). We rely on at least one of base_calmar or
    # perturbed_calmars/perturbed_sharpes differing.
    cal_eq = (
        res_current.base_calmar == res_mid.base_calmar
        and len(res_current.perturbed_calmars) == len(res_mid.perturbed_calmars)
        and all(
            a == b for a, b in zip(res_current.perturbed_calmars, res_mid.perturbed_calmars)
        )
    )
    assert not cal_eq, "center_on=current should produce a different grid than midpoint"


def test_spp_workers_seeded_deterministically(synth_prices):
    """Worker child seeds must be derived deterministically from a parent seed
    via numpy ``SeedSequence(parent_seed).spawn(n_workers)``. The previous
    arithmetic recipe ``parent_seed + worker_id * 17`` produced correlated
    streams across adjacent workers (low-order bits shared) and was replaced.

    Two runs with the same parent_seed must produce identical worker_seeds
    regardless of the global seed.
    """
    set_global_seed(42)
    param_ranges = {"fast": (10, 30)}
    res_a = spp(
        _factory_with, synth_prices, param_ranges,
        n_steps=3, costs=ZERO_costs, max_combinations=4,
        n_workers=4, parent_seed=12345, seed_name="spp_w_a",
    )
    set_global_seed(7)  # different global seed should NOT change worker seeds when parent_seed is explicit
    res_b = spp(
        _factory_with, synth_prices, param_ranges,
        n_steps=3, costs=ZERO_costs, max_combinations=4,
        n_workers=4, parent_seed=12345, seed_name="spp_w_b",
    )
    # Reproduce the SeedSequence.spawn output so the test is independent of
    # private implementation details.
    seq = np.random.SeedSequence(12345)
    expected = [int(s.generate_state(1, dtype=np.uint32)[0]) for s in seq.spawn(4)]
    assert res_a.worker_seeds == expected
    assert res_b.worker_seeds == expected
    assert res_a.worker_seeds == res_b.worker_seeds
    # Sanity: independent worker seeds should not be a tight arithmetic
    # progression. Differences between consecutive seeds must vary.
    diffs = [res_a.worker_seeds[i + 1] - res_a.worker_seeds[i] for i in range(3)]
    assert len(set(diffs)) > 1, "SeedSequence outputs must not be uniformly spaced"


def test_spp_invalid_center_on_raises(synth_prices):
    with pytest.raises(ValueError):
        spp(
            _factory_with, synth_prices, {"fast": (10, 30)},
            n_steps=3, costs=ZERO_costs, max_combinations=4,
            center_on="bogus",
        )


def test_spp_center_on_current_requires_current_params(synth_prices):
    with pytest.raises(ValueError):
        spp(
            _factory_with, synth_prices, {"fast": (10, 30)},
            n_steps=3, costs=ZERO_costs, max_combinations=4,
            center_on="current",
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
