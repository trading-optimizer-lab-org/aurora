"""Tests for EqualMarginalVolPortfolio."""
from __future__ import annotations
import numpy as np
import pytest

from aurora.risk.equal_marginal_vol import EqualMarginalVolPortfolio


def test_emv_simplex():
    rng = np.random.default_rng(7)
    R = rng.normal(0.0, 0.01, (800, 5))
    emv = EqualMarginalVolPortfolio()
    w = emv.allocate(R)
    assert np.isclose(w.sum(), 1.0, atol=1e-6)
    assert np.all(w >= 0)


def test_emv_single_asset():
    R = np.random.default_rng(3).normal(0.0, 0.01, (500, 1))
    emv = EqualMarginalVolPortfolio()
    w = emv.allocate(R)
    assert np.isclose(w[0], 1.0)


def test_emv_marginal_contributions_dim():
    rng = np.random.default_rng(13)
    R = rng.normal(0.0, 0.01, (400, 4))
    emv = EqualMarginalVolPortfolio()
    Sigma = np.cov(R, rowvar=False, ddof=1)
    w = emv.allocate(cov=Sigma)
    mc = emv.marginal_contributions(w, Sigma)
    assert mc.size == 4


def test_emv_iter_validation():
    with pytest.raises(ValueError):
        EqualMarginalVolPortfolio(max_iter=10)
    with pytest.raises(ValueError):
        EqualMarginalVolPortfolio(tol=0)


def test_emv_validate_inputs():
    emv = EqualMarginalVolPortfolio()
    with pytest.raises(ValueError):
        emv.allocate()
    with pytest.raises(ValueError):
        emv.allocate(returns_matrix=np.array([1.0, 2.0]))


def test_emv_with_cov_only():
    rng = np.random.default_rng(13)
    R = rng.normal(0.0, 0.01, (400, 3))
    Sigma = np.cov(R, rowvar=False, ddof=1)
    emv = EqualMarginalVolPortfolio()
    w = emv.allocate(cov=Sigma)
    assert np.isclose(w.sum(), 1.0, atol=1e-6)


def test_emv_long_short():
    rng = np.random.default_rng(17)
    R = rng.normal(0.0, 0.01, (500, 4))
    emv = EqualMarginalVolPortfolio(long_only=False)
    w = emv.allocate(R)
    assert np.isclose(w.sum(), 1.0, atol=1e-6)


def test_emv_empty():
    emv = EqualMarginalVolPortfolio()
    out = emv.allocate(cov=np.zeros((0, 0)))
    assert out.size == 0
