"""Tests for HierarchicalEqualRiskContribution (HERC)."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from quantforge.risk.herc import HierarchicalEqualRiskContribution


def _seed(s: int) -> np.random.Generator:
    return np.random.default_rng(s)


def test_herc_basic_simplex():
    rng = _seed(7)
    df = pd.DataFrame(rng.normal(0.0, 0.01, (500, 5)),
                      columns=list("ABCDE"))
    herc = HierarchicalEqualRiskContribution()
    w = herc.allocate(df)
    assert isinstance(w, pd.Series)
    assert np.isclose(w.sum(), 1.0, atol=1e-6)
    assert (w >= 0).all()
    assert list(w.index) == list("ABCDE")


def test_herc_single_asset():
    df = pd.DataFrame(np.array([[0.01], [0.0], [-0.005]]), columns=["A"])
    herc = HierarchicalEqualRiskContribution()
    w = herc.allocate(df)
    assert np.isclose(w["A"], 1.0)


def test_herc_invalid_linkage():
    with pytest.raises(ValueError):
        HierarchicalEqualRiskContribution(linkage_method="bogus")


def test_herc_invalid_risk_measure():
    with pytest.raises(ValueError):
        HierarchicalEqualRiskContribution(risk_measure="weird")


def test_herc_works_with_ndarray():
    rng = _seed(11)
    R = rng.normal(0.0, 0.01, (400, 4))
    herc = HierarchicalEqualRiskContribution(linkage_method="single")
    w = herc.allocate(R)
    assert np.isclose(w.sum(), 1.0, atol=1e-6)
    assert (w >= 0).all()


def test_herc_n_clusters_argument():
    rng = _seed(13)
    R = rng.normal(0.0, 0.01, (500, 6))
    herc = HierarchicalEqualRiskContribution(n_clusters=3)
    w = herc.allocate(R)
    assert np.isclose(w.sum(), 1.0, atol=1e-6)


def test_herc_std_risk_measure():
    rng = _seed(17)
    R = rng.normal(0.0, 0.01, (400, 4))
    herc = HierarchicalEqualRiskContribution(risk_measure="std")
    w = herc.allocate(R)
    assert np.isclose(w.sum(), 1.0, atol=1e-6)


def test_herc_2d_required():
    herc = HierarchicalEqualRiskContribution()
    with pytest.raises(ValueError):
        herc.allocate(np.array([1.0, 2.0]))
