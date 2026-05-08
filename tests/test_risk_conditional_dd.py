"""Tests for ConditionalDrawdownAtRisk."""
from __future__ import annotations
import numpy as np
import pytest

from quantforge.risk.conditional_dd import ConditionalDrawdownAtRisk


def test_cdar_positive_for_random_walk():
    rng = np.random.default_rng(7)
    r = rng.normal(0.0, 0.02, 2000)
    cdar = ConditionalDrawdownAtRisk(alpha=0.95)
    val = cdar.compute(r)
    assert 0.0 < val <= 1.0


def test_cdar_zero_on_no_drawdown():
    # Strictly increasing wealth -> all dd are 0
    r = np.full(100, 0.001)
    cdar = ConditionalDrawdownAtRisk(alpha=0.95)
    assert cdar.compute(r) == 0.0


def test_cdar_zero_on_empty():
    cdar = ConditionalDrawdownAtRisk()
    assert cdar.compute(np.array([])) == 0.0


def test_cdar_alpha_validation():
    with pytest.raises(ValueError):
        ConditionalDrawdownAtRisk(alpha=0.0)
    with pytest.raises(ValueError):
        ConditionalDrawdownAtRisk(alpha=1.0)


def test_cdar_monotone_in_alpha():
    rng = np.random.default_rng(9)
    r = rng.normal(0.0, 0.02, 2000)
    low = ConditionalDrawdownAtRisk(alpha=0.50).compute(r)
    high = ConditionalDrawdownAtRisk(alpha=0.99).compute(r)
    assert high >= low


def test_cdar_allocate_simplex():
    rng = np.random.default_rng(11)
    R = np.column_stack([rng.normal(0.0, s, 1500) for s in (0.005, 0.01, 0.025)])
    cdar = ConditionalDrawdownAtRisk(alpha=0.95)
    w = cdar.allocate(R)
    assert np.isclose(w.sum(), 1.0)
    assert np.all(w >= 0)
    assert w[0] > w[2]


def test_cdar_allocate_2d_check():
    cdar = ConditionalDrawdownAtRisk()
    with pytest.raises(ValueError):
        cdar.allocate(np.array([1.0, 2.0]))


def test_cdar_drops_nans():
    cdar = ConditionalDrawdownAtRisk(alpha=0.9)
    r = np.array([0.01, np.nan, -0.05, np.nan, 0.02, -0.03, 0.01])
    val = cdar.compute(r)
    assert val >= 0.0
