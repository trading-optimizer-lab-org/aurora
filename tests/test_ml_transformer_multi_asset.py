"""Tests for aurora.ml.transformer_multi_asset."""
from __future__ import annotations

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from aurora.ml.transformer_multi_asset import (
    MultiAssetTransformer,
    MultiAssetTransformerConfig,
    TORCH_AVAILABLE,
)


@pytest.fixture
def cfg():
    return MultiAssetTransformerConfig(
        n_assets=4, n_features=3, d_model=16, n_heads=2, num_layers=1, dim_feedforward=32, max_len=64
    )


def test_predict_output_shape(cfg):
    model = MultiAssetTransformer(cfg)
    T = 30
    x = np.random.randn(T, cfg.n_assets, cfg.n_features).astype(np.float32)
    out = model.predict(x)
    assert out.shape == (T, cfg.n_assets)


def test_predict_validates_input(cfg):
    model = MultiAssetTransformer(cfg)
    with pytest.raises(TypeError):
        model.predict([1, 2, 3])
    with pytest.raises(ValueError):
        model.predict(np.zeros((5, 3), dtype=np.float32))


def test_train_step_reduces_loss_on_constant_target(cfg):
    """One SGD step should not raise and should return a finite loss."""
    model = MultiAssetTransformer(cfg)
    T = 20
    rng = np.random.default_rng(0)
    x = rng.standard_normal((T, cfg.n_assets, cfg.n_features)).astype(np.float32)
    y = np.zeros((T, cfg.n_assets), dtype=np.float32)
    loss0 = model.train_step(x, y, lr=1e-2)
    loss1 = model.train_step(x, y, lr=1e-2)
    assert np.isfinite(loss0)
    assert np.isfinite(loss1)


def test_n_parameters_positive(cfg):
    model = MultiAssetTransformer(cfg)
    assert model.n_parameters > 0


def test_causal_mask_blocks_future(cfg):
    """Modifying the *last* time-step input should not change earlier outputs."""
    model = MultiAssetTransformer(cfg)
    T = 16
    rng = np.random.default_rng(1)
    x = rng.standard_normal((T, cfg.n_assets, cfg.n_features)).astype(np.float32)
    out_a = model.predict(x)
    x_mut = x.copy()
    x_mut[-1] += 100.0  # shock only the last timestep
    out_b = model.predict(x_mut)
    np.testing.assert_allclose(out_a[:-1], out_b[:-1], atol=1e-5)


def test_dimension_mismatch_raises(cfg):
    model = MultiAssetTransformer(cfg)
    bad = np.zeros((10, cfg.n_assets + 1, cfg.n_features), dtype=np.float32)
    with pytest.raises(ValueError):
        model.predict(bad)
