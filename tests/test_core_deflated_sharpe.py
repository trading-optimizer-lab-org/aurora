"""Deflated Sharpe in core.metrics: the null benchmark must be in Sharpe units.

Bailey & Lopez de Prado (2014), eq. 8: the expected maximum Sharpe of N
unskilled trials is ``SR0 = sqrt(V[SR]) * E[max of N standard normals]``.
The standard-normal quantile alone (~1.5-3.9) is not a Sharpe; comparing a
per-period Sharpe (~0.05-0.2 for daily data) to it made the DSR ~0 for
every strategy.
"""
from __future__ import annotations

import math

import numpy as np
import pytest
from scipy import stats

from aurora.core.metrics import deflated_sharpe
from aurora.research import multiasset_baselines as mab
from aurora.validation.deflated_sharpe import deflated_sharpe_annualized

PPY = 252
T = 2520  # ten years of daily bars


def _e_max(n: int) -> float:
    g = np.euler_gamma
    return (1 - g) * stats.norm.ppf(1 - 1 / n) + g * stats.norm.ppf(1 - 1 / (n * math.e))


def test_strong_strategy_is_not_deflated_to_zero() -> None:
    # Annualised Sharpe 3 over ten years after 10 trials: clearly significant.
    dsr = deflated_sharpe(3.0 / math.sqrt(PPY), n_trials=10, n_periods=T, kurtosis=3.0)
    assert dsr > 0.99


def test_unskilled_strategy_sits_at_the_null_quantile() -> None:
    # A zero Sharpe is E_max null standard deviations below the benchmark.
    dsr = deflated_sharpe(0.0, n_trials=10, n_periods=T, kurtosis=3.0)
    assert dsr == pytest.approx(stats.norm.cdf(-_e_max(10)), abs=1e-3)


def test_more_trials_deflate_more() -> None:
    sr = 1.0 / math.sqrt(PPY)
    values = [deflated_sharpe(sr, n_trials=n, n_periods=T, kurtosis=3.0) for n in (2, 10, 100, 1000)]
    assert values == sorted(values, reverse=True)
    assert values[0] > values[-1]


def test_cross_trial_dispersion_matches_the_research_implementation() -> None:
    trials_ann = [0.2, 0.5, 0.9, 1.1, 1.4, 0.3, -0.2, 0.8]
    sr_ann, skew, kurt = 1.4, -0.3, 5.0
    expected = mab.deflated_sharpe(sr_ann, trials_ann, n_periods=T, skew=skew, kurtosis=kurt, ppy=PPY)
    got = deflated_sharpe(sr_ann / math.sqrt(PPY), n_trials=len(trials_ann), n_periods=T, skew=skew,
                          kurtosis=kurt, trial_sharpes=[s / math.sqrt(PPY) for s in trials_ann])
    assert got == pytest.approx(expected, abs=1e-4)


def test_annualized_gate_passes_a_strong_strategy() -> None:
    rep = deflated_sharpe_annualized(3.0, n_trials=10, n_periods=T, ppy=PPY, kurtosis=3.0)
    assert rep.dsr > 0.99 and rep.passed


def test_degenerate_inputs_still_return_zero() -> None:
    assert deflated_sharpe(0.1, n_trials=1, n_periods=T) == 0.0
    assert deflated_sharpe(0.1, n_trials=10, n_periods=5) == 0.0
