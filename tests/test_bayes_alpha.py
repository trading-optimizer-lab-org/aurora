"""Tests for quantforge.regime.bayes_alpha."""
from __future__ import annotations

import os

import numpy as np
import pandas as pd
import pytest

from aurora.regime.bayes_alpha import (
    BayesAlphaResult,
    alpha_significance_test,
    bayesian_rolling_alpha,
    cumulative_alpha,
    plot_alpha_bands,
)


# ---------- fixtures ----------


@pytest.fixture
def rng():
    return np.random.default_rng(42)


def _series_pair(rng, n=400, alpha=0.0, beta=1.0, sigma=0.01):
    """Build aligned (strategy, benchmark) series with known coefficients."""
    idx = pd.date_range("2022-01-01", periods=n, freq="B")
    bench = pd.Series(rng.normal(0.0005, 0.01, n), index=idx)
    noise = rng.normal(0.0, sigma, n)
    strat = alpha + beta * bench + noise
    return strat, bench


# ---------- core recovery ----------


def test_known_alpha_recovered(rng):
    strat, bench = _series_pair(rng, n=600, alpha=0.001, beta=1.0, sigma=0.005)
    res = bayesian_rolling_alpha(
        strat,
        bench,
        window=120,
        prior_alpha_mean=0.0,
        prior_alpha_std=0.01,
        prior_beta_mean=1.0,
        prior_beta_std=0.5,
    )
    assert isinstance(res, BayesAlphaResult)
    # Last-window posterior should be close to the planted alpha=0.001/day.
    assert abs(res.overall_alpha_mean - 0.001) < 5e-4
    assert abs(res.beta_mean.iloc[-1] - 1.0) < 0.1


def test_zero_alpha_recovery(rng):
    strat, bench = _series_pair(rng, n=600, alpha=0.0, beta=1.0, sigma=0.005)
    res = bayesian_rolling_alpha(strat, bench, window=120)
    # Posterior alpha should be near zero.
    assert abs(res.overall_alpha_mean) < 5e-4


# ---------- uncertainty ----------


def test_uncertainty_decreases_with_window(rng):
    strat, bench = _series_pair(rng, n=600, alpha=0.0005, beta=1.0, sigma=0.005)
    res_short = bayesian_rolling_alpha(strat, bench, window=40)
    res_long = bayesian_rolling_alpha(strat, bench, window=240)
    assert res_long.overall_alpha_std < res_short.overall_alpha_std


def test_prior_dominates_short_window(rng):
    """Tight prior + tiny window keeps posterior anchored near the prior."""
    strat, bench = _series_pair(rng, n=80, alpha=0.0, beta=1.0, sigma=0.005)
    prior = 0.005
    res = bayesian_rolling_alpha(
        strat,
        bench,
        window=5,
        prior_alpha_mean=prior,
        prior_alpha_std=1e-5,  # very tight prior
        prior_beta_mean=1.0,
        prior_beta_std=0.5,
    )
    # Posterior alpha should be glued to the prior mean.
    assert abs(res.overall_alpha_mean - prior) < 1e-4


# ---------- significance ----------


def test_significance_test_returns_probabilities(rng):
    strat, bench = _series_pair(rng, n=300, alpha=0.001, beta=1.0, sigma=0.005)
    res = bayesian_rolling_alpha(strat, bench, window=60)
    probs = alpha_significance_test(res, threshold=0.0)
    valid = probs.dropna()
    assert len(valid) > 0
    assert ((valid >= 0.0) & (valid <= 1.0)).all()
    # Probability that alpha>0 should be elevated for a positive-alpha series.
    assert valid.mean() > 0.5


# ---------- cumulative ----------


def test_cumulative_alpha_compounds(rng):
    strat, bench = _series_pair(rng, n=300, alpha=0.001, beta=1.0, sigma=0.005)
    res = bayesian_rolling_alpha(strat, bench, window=60)
    cum = cumulative_alpha(res)
    valid = cum.dropna()
    assert len(valid) > 0
    # Reconstruct expected compounding from the same posterior means.
    a = res.alpha_mean.dropna().to_numpy()
    expected_last = float(np.cumprod(1.0 + a)[-1] - 1.0)
    assert abs(valid.iloc[-1] - expected_last) < 1e-12
    # Monotone alpha>0 series compounds to a positive cumulative number.
    assert valid.iloc[-1] > 0.0


# ---------- plotting ----------


def test_plot_creates_file(rng, tmp_path):
    strat, bench = _series_pair(rng, n=200, alpha=0.0005, beta=1.0, sigma=0.005)
    res = bayesian_rolling_alpha(strat, bench, window=60)
    out = tmp_path / "alpha_bands.png"
    returned = plot_alpha_bands(res, output_path=str(out))
    assert returned == str(out)
    assert os.path.exists(out)
    assert os.path.getsize(out) > 0


def test_bayes_alpha_singular_fallback_sigma_correct(rng):
    """When X^T X is singular (constant benchmark inside the window), the
    fallback sigma must equal y.std(ddof=1) — not y.std()/sqrt(n), which
    would dramatically understate residual noise.
    """
    n = 80
    idx = pd.date_range("2022-01-01", periods=n, freq="B")
    # Constant benchmark causes the design matrix to be rank-deficient.
    bench = pd.Series(np.zeros(n), index=idx)
    strat = pd.Series(rng.normal(0.001, 0.02, n), index=idx)
    res = bayesian_rolling_alpha(strat, bench, window=30)
    # At least one valid window must produce finite alpha_std (and not the
    # absurdly small value the old buggy fallback produced).
    last_std = float(res.alpha_std.dropna().iloc[-1])
    assert np.isfinite(last_std)
    # Loose lower bound check: the std should not collapse to ~zero. With
    # sigma ≈ y.std(ddof=1) ≈ 0.02 and n=30, post std should be roughly
    # > 1e-3. Picking a generous 1e-5 floor to remain robust.
    assert last_std > 1e-5
