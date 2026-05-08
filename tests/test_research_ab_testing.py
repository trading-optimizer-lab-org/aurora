"""Tests for quantforge.research.ab_testing."""
from __future__ import annotations
import numpy as np
import pytest

from quantforge.research.ab_testing import ABTestFramework, ABTestResult


def test_welch_t_detects_difference():
    rng = np.random.default_rng(42)
    a = rng.normal(0.005, 0.01, size=500)
    b = rng.normal(0.001, 0.01, size=500)
    fw = ABTestFramework(alpha=0.05)
    res = fw.welch_t(a, b)
    assert isinstance(res, ABTestResult)
    assert res.test == "welch_t"
    assert res.significant is True
    assert res.winner == "A"


def test_welch_t_no_difference():
    rng = np.random.default_rng(7)
    a = rng.normal(0.001, 0.01, size=300)
    b = rng.normal(0.001, 0.01, size=300)
    fw = ABTestFramework(alpha=0.05)
    res = fw.welch_t(a, b)
    # not guaranteed but very likely
    assert res.winner in ("A", "B", "tie")


def test_mann_whitney_detects_difference():
    rng = np.random.default_rng(11)
    a = rng.normal(0.005, 0.01, size=400)
    b = rng.normal(0.001, 0.01, size=400)
    fw = ABTestFramework(alpha=0.05)
    res = fw.mann_whitney(a, b)
    assert res.test == "mann_whitney"
    assert res.significant is True
    assert res.winner == "A"


def test_drop_nans():
    a = np.array([0.01, np.nan, 0.02, 0.03])
    b = np.array([0.0, 0.0, 0.0, 0.0])
    fw = ABTestFramework()
    res = fw.welch_t(a, b)
    assert res.n_a == 3
    assert res.n_b == 4


def test_too_few_observations_welch():
    fw = ABTestFramework()
    with pytest.raises(ValueError):
        fw.welch_t(np.array([1.0]), np.array([2.0, 3.0]))


def test_too_few_observations_mw():
    fw = ABTestFramework()
    with pytest.raises(ValueError):
        fw.mann_whitney(np.array([]), np.array([1.0]))


def test_invalid_alpha():
    with pytest.raises(ValueError):
        ABTestFramework(alpha=0.0)
    with pytest.raises(ValueError):
        ABTestFramework(alpha=1.0)


def test_p_value_in_unit_interval():
    rng = np.random.default_rng(0)
    a = rng.normal(0.0, 1.0, 100)
    b = rng.normal(0.0, 1.0, 100)
    fw = ABTestFramework()
    for r in (fw.welch_t(a, b), fw.mann_whitney(a, b)):
        assert 0.0 <= r.p_value <= 1.0
