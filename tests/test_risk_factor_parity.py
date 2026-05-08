"""Tests for FactorRiskParity."""
from __future__ import annotations
import numpy as np
import pytest

from quantforge.risk.risk_parity_factor import FactorRiskParity


def test_factor_parity_simplex():
    rng = np.random.default_rng(7)
    R = rng.normal(0.0, 0.01, (500, 5))
    frp = FactorRiskParity()
    w = frp.allocate(R)
    assert w.size == 5
    assert np.isclose(w.sum(), 1.0, atol=1e-6)
    assert np.all(w >= 0)


def test_factor_parity_n_factors_argument():
    rng = np.random.default_rng(11)
    R = rng.normal(0.0, 0.01, (500, 5))
    frp = FactorRiskParity(n_factors=2)
    w = frp.allocate(R)
    assert np.isclose(w.sum(), 1.0, atol=1e-6)


def test_factor_parity_single_asset():
    rng = np.random.default_rng(3)
    R = rng.normal(0.0, 0.01, (500, 1))
    frp = FactorRiskParity()
    w = frp.allocate(R)
    assert w.size == 1
    assert np.isclose(w[0], 1.0)


def test_factor_parity_validates_2d():
    frp = FactorRiskParity()
    with pytest.raises(ValueError):
        frp.allocate(np.array([1.0, 2.0]))


def test_factor_parity_iter_validation():
    with pytest.raises(ValueError):
        FactorRiskParity(max_iter=0)
    with pytest.raises(ValueError):
        FactorRiskParity(tol=-1)


def test_factor_contributions_match_dim():
    rng = np.random.default_rng(13)
    R = rng.normal(0.0, 0.01, (400, 4))
    frp = FactorRiskParity(n_factors=3)
    w = frp.allocate(R)
    contribs = frp.factor_contributions(w, R)
    assert contribs.size == 3
    assert np.all(contribs >= 0)


def test_factor_parity_long_short():
    rng = np.random.default_rng(17)
    R = rng.normal(0.0, 0.01, (500, 4))
    frp = FactorRiskParity(long_only=False)
    w = frp.allocate(R)
    assert np.isclose(w.sum(), 1.0, atol=1e-6)


def test_factor_parity_empty():
    frp = FactorRiskParity()
    out = frp.allocate(np.zeros((10, 0)))
    assert out.size == 0
