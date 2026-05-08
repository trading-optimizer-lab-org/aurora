"""Tests for ExpectedShortfall."""
from __future__ import annotations
import numpy as np
import pytest

from quantforge.risk.expected_shortfall import ExpectedShortfall


def _seed(s: int) -> np.random.Generator:
    return np.random.default_rng(s)


def test_es_positive_for_negative_tail():
    rng = _seed(7)
    r = rng.normal(0.0, 0.01, 5000)
    es = ExpectedShortfall(alphas=(0.95, 0.99))
    out = es.compute(r)
    assert out[0.95] > 0
    assert out[0.99] > out[0.95]


def test_es_zero_on_empty():
    es = ExpectedShortfall()
    out = es.compute(np.array([]))
    assert all(v == 0.0 for v in out.values())


def test_es_drops_nans():
    es = ExpectedShortfall(alphas=(0.95,))
    r = np.array([0.01, np.nan, -0.05, np.nan, -0.02, 0.0])
    out = es.compute(r)
    assert out[0.95] >= 0


def test_es_validates_alpha():
    with pytest.raises(ValueError):
        ExpectedShortfall(alphas=(1.5,))
    with pytest.raises(ValueError):
        ExpectedShortfall(alphas=(0.0,))


def test_es_allocate_simplex():
    rng = _seed(11)
    R = np.column_stack([rng.normal(0.0, s, 1000) for s in (0.005, 0.01, 0.02)])
    es = ExpectedShortfall(alphas=(0.95,))
    w = es.allocate(R)
    assert np.isclose(w.sum(), 1.0)
    assert np.all(w >= 0)
    # Lower-vol asset should get more weight
    assert w[0] > w[2]


def test_es_lower_interpolation():
    es = ExpectedShortfall(alphas=(0.95,), interpolation="lower")
    rng = _seed(3)
    r = rng.normal(0.0, 0.01, 1000)
    out = es.compute(r)
    assert out[0.95] > 0


def test_es_invalid_interp():
    with pytest.raises(ValueError):
        ExpectedShortfall(interpolation="bogus")


def test_es_allocate_2d_check():
    es = ExpectedShortfall()
    with pytest.raises(ValueError):
        es.allocate(np.array([1.0, 2.0]))
