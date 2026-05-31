"""Tests for aurora.ml.causal_inference."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aurora.ml.causal_inference import (
    CausalFactorAnalysis,
    CausalReport,
    RefutationResult,
)


@pytest.fixture
def truly_causal_panel():
    rng = np.random.default_rng(0)
    n = 500
    signal = pd.Series(rng.standard_normal(n), name="s")
    noise = rng.standard_normal(n) * 0.5
    target = pd.Series(0.7 * signal + noise, name="y")
    return signal, target


@pytest.fixture
def random_panel():
    rng = np.random.default_rng(1)
    n = 500
    s = pd.Series(rng.standard_normal(n), name="s")
    y = pd.Series(rng.standard_normal(n), name="y")
    return s, y


def test_estimate_effect_recovers_true_coef(truly_causal_panel):
    s, y = truly_causal_panel
    cfa = CausalFactorAnalysis()
    coef = cfa.estimate_effect(s, y)
    assert abs(coef - 0.7) < 0.1  # OLS should be close


def test_placebo_passes_when_signal_is_truly_causal(truly_causal_panel):
    s, y = truly_causal_panel
    cfa = CausalFactorAnalysis()
    res = cfa.refute_placebo(s, y)
    # placebo (permuted signal) should yield ~0 effect
    assert isinstance(res, RefutationResult)
    assert abs(res.refuted_effect) < abs(res.estimated_effect)
    assert res.passed


def test_subset_refutation_stable(truly_causal_panel):
    s, y = truly_causal_panel
    cfa = CausalFactorAnalysis(subset_tolerance=0.5)
    res = cfa.refute_subset(s, y)
    assert res.passed


def test_random_common_cause_refutation(truly_causal_panel):
    s, y = truly_causal_panel
    cfa = CausalFactorAnalysis(common_cause_tolerance=0.3)
    res = cfa.refute_add_random_common_cause(s, y)
    # Adding pure noise should not perturb the signal coef much
    assert res.passed


def test_run_returns_full_report(truly_causal_panel):
    s, y = truly_causal_panel
    cfa = CausalFactorAnalysis()
    report = cfa.run(s, y)
    assert isinstance(report, CausalReport)
    assert len(report.refutations) == 3
    assert report.all_passed


def test_estimate_validates_input():
    cfa = CausalFactorAnalysis()
    with pytest.raises(TypeError):
        cfa.estimate_effect([1, 2, 3], pd.Series([1, 2, 3]))
    with pytest.raises(TypeError):
        cfa.estimate_effect(pd.Series([1, 2, 3]), [1, 2, 3])
    short = pd.Series([1.0, 2.0, 3.0])
    with pytest.raises(ValueError):
        cfa.estimate_effect(short, short)


def test_estimate_with_controls(truly_causal_panel):
    s, y = truly_causal_panel
    rng = np.random.default_rng(2)
    controls = pd.DataFrame(
        {"c1": rng.standard_normal(len(s)), "c2": rng.standard_normal(len(s))}
    )
    cfa = CausalFactorAnalysis()
    coef = cfa.estimate_effect(s, y, controls=controls)
    assert abs(coef - 0.7) < 0.15
