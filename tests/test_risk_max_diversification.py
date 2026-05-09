"""Tests for MaxDiversificationPortfolio (Choueifaty MDP)."""
from __future__ import annotations
import numpy as np
import pytest

from aurora.risk.max_diversification import MaxDiversificationPortfolio


def test_mdp_simplex():
    rng = np.random.default_rng(7)
    R = rng.normal(0.0, 0.01, (800, 5))
    mdp = MaxDiversificationPortfolio()
    w = mdp.allocate(R)
    assert np.isclose(w.sum(), 1.0, atol=1e-6)
    assert np.all(w >= 0)


def test_mdp_single_asset():
    R = np.random.default_rng(3).normal(0.0, 0.01, (500, 1))
    mdp = MaxDiversificationPortfolio()
    w = mdp.allocate(R)
    assert np.isclose(w[0], 1.0)


def test_mdp_dr_at_least_1():
    rng = np.random.default_rng(11)
    R = rng.normal(0.0, 0.01, (600, 4))
    mdp = MaxDiversificationPortfolio()
    w = mdp.allocate(R)
    Sigma = np.cov(R, rowvar=False, ddof=1)
    dr = mdp.diversification_ratio(w, Sigma)
    # By construction DR >= 1 for any non-degenerate long portfolio
    assert dr >= 1.0 - 1e-6


def test_mdp_iter_validation():
    with pytest.raises(ValueError):
        MaxDiversificationPortfolio(max_iter=10)
    with pytest.raises(ValueError):
        MaxDiversificationPortfolio(tol=0)
    with pytest.raises(ValueError):
        MaxDiversificationPortfolio(lr=0)


def test_mdp_with_cov_only():
    rng = np.random.default_rng(13)
    R = rng.normal(0.0, 0.01, (400, 3))
    Sigma = np.cov(R, rowvar=False, ddof=1)
    mdp = MaxDiversificationPortfolio()
    w = mdp.allocate(cov=Sigma)
    assert np.isclose(w.sum(), 1.0, atol=1e-6)


def test_mdp_validate_inputs():
    mdp = MaxDiversificationPortfolio()
    with pytest.raises(ValueError):
        mdp.allocate()  # both None
    with pytest.raises(ValueError):
        mdp.allocate(returns_matrix=np.array([1.0, 2.0]))


def test_mdp_long_short():
    rng = np.random.default_rng(17)
    R = rng.normal(0.0, 0.01, (500, 4))
    mdp = MaxDiversificationPortfolio(long_only=False)
    w = mdp.allocate(R)
    assert np.isclose(w.sum(), 1.0, atol=1e-6)


def test_mdp_empty():
    mdp = MaxDiversificationPortfolio()
    out = mdp.allocate(cov=np.zeros((0, 0)))
    assert out.size == 0
