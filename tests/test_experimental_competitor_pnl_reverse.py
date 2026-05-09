"""Tests for CompetitorPnLReverseEngineer."""
from __future__ import annotations

import numpy as np
import pytest

from aurora.experimental.competitor_pnl_reverse import CompetitorPnLReverseEngineer


def test_recovers_known_weights_approximately():
    rng = np.random.default_rng(11)
    T, N = 200, 4
    H = rng.standard_normal((T, N))
    R = rng.standard_normal((T, N)) * 0.02
    true_w = np.array([1.0, -0.5, 0.25, 0.0])
    P = (H * R) @ true_w + rng.standard_normal(T) * 1e-4

    eng = CompetitorPnLReverseEngineer(ridge=1e-6)
    res = eng.infer(H, R, P)
    np.testing.assert_allclose(res["weights"], true_w, atol=0.05)
    assert res["r2"] > 0.95


def test_shape_validation():
    eng = CompetitorPnLReverseEngineer()
    H = np.zeros((10, 3))
    R = np.zeros((10, 4))
    P = np.zeros(10)
    with pytest.raises(ValueError):
        eng.infer(H, R, P)


def test_pnl_length_validation():
    eng = CompetitorPnLReverseEngineer()
    H = np.zeros((10, 3))
    R = np.zeros((10, 3))
    P = np.zeros(9)
    with pytest.raises(ValueError):
        eng.infer(H, R, P)


def test_negative_ridge_raises():
    with pytest.raises(ValueError):
        CompetitorPnLReverseEngineer(ridge=-1.0)


def test_dimensions_in_result():
    eng = CompetitorPnLReverseEngineer()
    H = np.zeros((20, 5))
    R = np.zeros((20, 5))
    P = np.zeros(20)
    res = eng.infer(H, R, P)
    assert res["n_assets"] == 5
    assert res["n_periods"] == 20
