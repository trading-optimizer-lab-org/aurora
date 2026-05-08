"""Tests for ParameterRankStability."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from quantforge.core.seed import set_global_seed
from quantforge.validation.parameter_rank_stability import ParameterRankStability


@pytest.fixture
def fake_sample():
    set_global_seed(42)
    idx = pd.date_range("2015-01-01", periods=300, freq="B")
    rng = np.random.default_rng(0)
    s = pd.Series(rng.normal(0.0, 0.01, 300), index=idx, name="ret")
    return s


def _fitness_fn(cfg, sample):
    """Simple synthetic fitness: weighted mean of sample."""
    w = float(cfg.get("w", 1.0))
    return float(w * sample.mean() - 0.1 * abs(w))


def test_basic(fake_sample):
    set_global_seed(42)
    configs = [{"w": v} for v in (0.1, 0.5, 1.0, 2.0, 5.0)]
    prs = ParameterRankStability(n_resamples=8).run(configs, _fitness_fn, fake_sample)
    assert prs.n_configs == 5
    assert prs.base_fitnesses.shape == (5,)
    assert prs.resample_taus.shape == (8,)
    assert -1.0 <= prs.mean_tau <= 1.0


def test_invalid_inputs(fake_sample):
    with pytest.raises(TypeError):
        ParameterRankStability().run([{"w": 1}, {"w": 2}, {"w": 3}], _fitness_fn, [1, 2, 3])
    with pytest.raises(ValueError):
        ParameterRankStability().run([{"w": 1}], _fitness_fn, fake_sample)
    with pytest.raises(ValueError):
        ParameterRankStability(n_resamples=0).run(
            [{"w": 1}, {"w": 2}, {"w": 3}], _fitness_fn, fake_sample
        )


def test_stable_ranking_high_tau(fake_sample):
    """Identity-like fitness ordering should give high tau across resamples."""
    set_global_seed(42)
    # Configs with widely-spaced w produce stable rank order (since the
    # mean(sample) sign is random but |w| dominates).
    configs = [{"w": v} for v in (0.01, 0.1, 1.0, 10.0, 100.0)]
    def f(cfg, sample):
        return -abs(float(cfg["w"]))  # rank purely by |w|
    prs = ParameterRankStability(n_resamples=10).run(configs, f, fake_sample)
    # Deterministic fitness => identical rankings => tau ~ 1
    assert prs.mean_tau > 0.99
