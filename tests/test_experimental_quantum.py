"""Tests for QuantumPortfolioOptimizer (classical fallback only)."""
from __future__ import annotations

import numpy as np
import pytest

from quantforge.experimental.quantum_placeholder import (
    QISKIT_AVAILABLE,
    QuantumPortfolioOptimizer,
)


def test_optimizer_returns_simplex_weights():
    rng = np.random.default_rng(0)
    n = 5
    mu = rng.normal(0.001, 0.0005, n)
    raw = rng.normal(0.0, 0.01, (n, n))
    sigma = raw @ raw.T  # PSD covariance
    opt = QuantumPortfolioOptimizer(risk_aversion=2.0)
    w = opt.optimize(mu, sigma)
    assert w.shape == (n,)
    assert np.all(w >= 0)
    assert pytest.approx(1.0, abs=1e-9) == w.sum()


def test_backend_reports_classical_when_qiskit_missing():
    opt = QuantumPortfolioOptimizer()
    expected = "qiskit" if QISKIT_AVAILABLE else "classical"
    assert opt.backend == expected


def test_optimizer_rejects_wrong_sigma_shape():
    opt = QuantumPortfolioOptimizer()
    with pytest.raises(ValueError):
        opt.optimize(np.ones(3), np.eye(2))


def test_optimizer_handles_singular_sigma():
    opt = QuantumPortfolioOptimizer()
    mu = np.array([0.01, 0.01, 0.01])
    sigma = np.zeros((3, 3))  # singular -> falls back to pinv + simplex
    w = opt.optimize(mu, sigma)
    assert w.shape == (3,)
    assert pytest.approx(1.0, abs=1e-9) == w.sum()
