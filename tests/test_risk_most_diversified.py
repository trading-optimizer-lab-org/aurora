"""Tests for MostDiversifiedAlloc."""
from __future__ import annotations
import numpy as np
import pytest

from aurora.risk.most_diversified import MostDiversifiedAlloc


def test_md_simplex():
    rng = np.random.default_rng(7)
    R = rng.normal(0.0, 0.01, (800, 5))
    md = MostDiversifiedAlloc()
    w = md.allocate(R)
    assert np.isclose(w.sum(), 1.0, atol=1e-6)
    assert np.all(w >= 0)


def test_md_single_asset():
    R = np.random.default_rng(3).normal(0.0, 0.01, (500, 1))
    md = MostDiversifiedAlloc()
    w = md.allocate(R)
    assert np.isclose(w[0], 1.0)


def test_md_dr_meaningful():
    rng = np.random.default_rng(11)
    R = rng.normal(0.0, 0.01, (600, 4))
    md = MostDiversifiedAlloc()
    Sigma = np.cov(R, rowvar=False, ddof=1)
    w = md.allocate(cov=Sigma)
    dr = md.diversification_ratio(w, Sigma)
    assert dr >= 1.0 - 1e-6


def test_md_iter_validation():
    with pytest.raises(ValueError):
        MostDiversifiedAlloc(max_iter=10)
    with pytest.raises(ValueError):
        MostDiversifiedAlloc(tol=0)


def test_md_validate_inputs():
    md = MostDiversifiedAlloc()
    with pytest.raises(ValueError):
        md.allocate()
    with pytest.raises(ValueError):
        md.allocate(returns_matrix=np.array([1.0, 2.0]))


def test_md_with_cov_only():
    rng = np.random.default_rng(13)
    R = rng.normal(0.0, 0.01, (400, 3))
    Sigma = np.cov(R, rowvar=False, ddof=1)
    md = MostDiversifiedAlloc()
    w = md.allocate(cov=Sigma)
    assert np.isclose(w.sum(), 1.0, atol=1e-6)


def test_md_empty():
    md = MostDiversifiedAlloc()
    out = md.allocate(cov=np.zeros((0, 0)))
    assert out.size == 0


def test_md_higher_vol_lower_weight():
    # Diagonal cov: weights should be inversely related to vol
    Sigma = np.diag([0.0001, 0.0004, 0.0016])
    md = MostDiversifiedAlloc()
    w = md.allocate(cov=Sigma)
    assert w[0] > w[1] > w[2]
