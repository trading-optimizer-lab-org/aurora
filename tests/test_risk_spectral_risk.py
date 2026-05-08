"""Tests for SpectralRiskMeasure."""
from __future__ import annotations
import math
import numpy as np
import pytest

from quantforge.risk.spectral_risk import (
    SpectralRiskMeasure,
    exponential_phi,
    power_phi,
)


def test_spectral_positive():
    rng = np.random.default_rng(7)
    r = rng.normal(0.0, 0.01, 4000)
    srm = SpectralRiskMeasure(phi=exponential_phi(k=10.0))
    val = srm.compute(r)
    assert val > 0


def test_spectral_zero_on_empty():
    srm = SpectralRiskMeasure()
    assert srm.compute(np.array([])) == 0.0


def test_phi_validation():
    with pytest.raises(ValueError):
        exponential_phi(k=0.0)
    with pytest.raises(ValueError):
        power_phi(gamma=-1.0)


def test_n_grid_validation():
    with pytest.raises(ValueError):
        SpectralRiskMeasure(n_grid=4)


def test_phi_normalization():
    # Custom phi must integrate to ~1 internally; the class re-normalises
    phi = exponential_phi(k=5.0)
    p = np.linspace(0.001, 0.999, 1000)
    integral = float(np.trapezoid(phi(p), p))
    assert math.isclose(integral, 1.0, rel_tol=0.05)


def test_power_phi_compute():
    rng = np.random.default_rng(13)
    r = rng.normal(0.0, 0.01, 3000)
    srm = SpectralRiskMeasure(phi=power_phi(gamma=2.0))
    val = srm.compute(r)
    assert val > 0


def test_allocate_simplex():
    rng = np.random.default_rng(11)
    R = np.column_stack([rng.normal(0.0, s, 1500) for s in (0.005, 0.01, 0.025)])
    srm = SpectralRiskMeasure()
    w = srm.allocate(R)
    assert np.isclose(w.sum(), 1.0)
    assert np.all(w >= 0)
    assert w[0] > w[2]  # lowest-vol gets the biggest slice


def test_allocate_2d_check():
    srm = SpectralRiskMeasure()
    with pytest.raises(ValueError):
        srm.allocate(np.array([1.0, 2.0]))
