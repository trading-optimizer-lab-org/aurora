"""Tests for quantforge.ml.diffusion_scenarios."""
from __future__ import annotations

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from aurora.ml.diffusion_scenarios import (
    DiffusionConfig,
    DiffusionScenarioGenerator,
    TORCH_AVAILABLE,
)


@pytest.fixture
def returns_panel():
    rng = np.random.default_rng(0)
    n = 200
    return rng.normal(0.0005, 0.012, (n, 2)).astype(np.float32)


def test_fit_runs_and_returns_history(returns_panel):
    cfg = DiffusionConfig(horizon=4, n_assets=2, hidden_dim=16, n_steps=8, epochs=5, batch_size=16)
    gen = DiffusionScenarioGenerator(cfg)
    history = gen.fit(returns_panel)
    assert "loss" in history
    assert len(history["loss"]) == 5
    assert all(np.isfinite(history["loss"]))


def test_sample_shape(returns_panel):
    cfg = DiffusionConfig(horizon=4, n_assets=2, hidden_dim=16, n_steps=8, epochs=3, batch_size=16)
    gen = DiffusionScenarioGenerator(cfg)
    gen.fit(returns_panel)
    paths = gen.sample(n_paths=10)
    assert paths.shape == (10, cfg.horizon, cfg.n_assets)
    assert np.isfinite(paths).all()


def test_sample_before_fit_raises():
    cfg = DiffusionConfig(horizon=3, n_assets=1, hidden_dim=8, n_steps=4, epochs=1)
    gen = DiffusionScenarioGenerator(cfg)
    with pytest.raises(RuntimeError):
        gen.sample(5)


def test_input_validation():
    cfg = DiffusionConfig(horizon=3, n_assets=1, hidden_dim=8, n_steps=4, epochs=1)
    gen = DiffusionScenarioGenerator(cfg)
    with pytest.raises(TypeError):
        gen.fit([1.0, 2.0, 3.0])
    with pytest.raises(ValueError):
        gen.fit(np.zeros(2, dtype=np.float32))  # too short

    bad_assets = np.zeros((10, 5), dtype=np.float32)
    with pytest.raises(ValueError):
        gen.fit(bad_assets)


def test_crisis_more_dispersed_than_normal(returns_panel):
    cfg = DiffusionConfig(horizon=4, n_assets=2, hidden_dim=16, n_steps=8, epochs=5, batch_size=16)
    gen = DiffusionScenarioGenerator(cfg)
    gen.fit(returns_panel)
    normal = gen.sample(n_paths=50)
    crisis = gen.sample_crisis(n_paths=50, vol_multiplier=3.0)
    assert crisis.shape == normal.shape
    # Crisis std should be greater
    assert crisis.std() > normal.std()


def test_constructor_validates():
    with pytest.raises(ValueError):
        DiffusionScenarioGenerator(DiffusionConfig(horizon=0))
    with pytest.raises(ValueError):
        DiffusionScenarioGenerator(DiffusionConfig(n_assets=0))


def test_sample_n_paths_validation(returns_panel):
    cfg = DiffusionConfig(horizon=3, n_assets=2, hidden_dim=8, n_steps=4, epochs=2, batch_size=16)
    gen = DiffusionScenarioGenerator(cfg)
    gen.fit(returns_panel)
    with pytest.raises(ValueError):
        gen.sample(n_paths=0)
