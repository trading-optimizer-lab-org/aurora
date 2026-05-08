"""Tests for Task 3.5: validate_pipeline extended with noise_injection + gap_sim gates."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from quantforge.core.seed import set_global_seed
from quantforge.core.costs import ZERO_costs
from quantforge.strategies.library import MACross
from quantforge.validation.pipeline import validate_pipeline, ValidationReport
from quantforge.validation.noise_injection import NoiseInjectionResult
from quantforge.validation.gap_sim import GapSimResult
from quantforge.validation.walk_forward import WFWindow


def _synth_prices(n: int = 6000, seed: int = 42) -> pd.Series:
    """Build a synthetic series spanning IS (pre-2013) and OOS (2013+)."""
    set_global_seed(seed)
    idx = pd.date_range("2000-01-03", periods=n, freq="B")
    rets = np.random.default_rng(seed).normal(0.0005, 0.012, n)
    p = 100.0 * np.cumprod(1.0 + rets)
    return pd.Series(p, index=idx, name="SYNTH")


def _factory(fast: int = 10, slow: int = 50, allow_short: bool = True):
    def make():
        return MACross(fast=fast, slow=slow, allow_short=allow_short)
    return make


# Smaller WF windows so test runs are fast but still cover the pipeline
_FAST_WF = [
    WFWindow("WF1", "2000-01-03", "2005-12-31", "2006-01-01", "2008-12-31"),
    WFWindow("WF2", "2000-01-03", "2007-12-31", "2008-01-01", "2010-12-31"),
    WFWindow("WF3", "2000-01-03", "2009-12-31", "2010-01-01", "2012-12-31"),
]


def test_pipeline_default_no_extras():
    """When run_noise_injection / run_gap_sim are False, fields are None."""
    prices = _synth_prices()
    rep = validate_pipeline(
        _factory(), prices, "default-no-extras",
        costs=ZERO_costs, wf_windows=_FAST_WF,
        mc_n_paths=20, min_wf_pass=0,
    )
    assert isinstance(rep, ValidationReport)
    assert rep.noise_result is None
    assert rep.gap_result is None


def test_pipeline_with_noise_only():
    """run_noise_injection=True populates noise_result; gap_result stays None."""
    prices = _synth_prices()
    rep = validate_pipeline(
        _factory(), prices, "noise-only",
        costs=ZERO_costs, wf_windows=_FAST_WF,
        mc_n_paths=20, min_wf_pass=0,
        run_noise_injection=True, noise_n_samples=5,
        noise_sigma_bps=5.0, noise_max_drop_pct=99.0,
    )
    assert isinstance(rep.noise_result, NoiseInjectionResult)
    assert rep.noise_result.n_samples == 5
    assert rep.gap_result is None
    # Report renders cleanly with the noise summary line
    assert "Noise injection" in rep.report()


def test_pipeline_with_gap_only():
    """run_gap_sim=True populates gap_result; noise_result stays None."""
    prices = _synth_prices()
    rep = validate_pipeline(
        _factory(), prices, "gap-only",
        costs=ZERO_costs, wf_windows=_FAST_WF,
        mc_n_paths=20, min_wf_pass=0,
        run_gap_sim=True, gap_n_samples=5,
        gap_n_per_path=3, gap_size_max=0.02,
        gap_max_calmar_drop_pct=99.0, gap_max_mdd_increase_pct=999.0,
    )
    assert rep.noise_result is None
    assert isinstance(rep.gap_result, GapSimResult)
    assert rep.gap_result.n_samples == 5
    assert rep.gap_result.n_gaps_per_path == 3
    assert "Gap sim" in rep.report()


def test_pipeline_with_both():
    """Both flags True populates both result fields."""
    prices = _synth_prices()
    rep = validate_pipeline(
        _factory(), prices, "noise+gap",
        costs=ZERO_costs, wf_windows=_FAST_WF,
        mc_n_paths=20, min_wf_pass=0,
        run_noise_injection=True, noise_n_samples=5,
        noise_sigma_bps=5.0, noise_max_drop_pct=99.0,
        run_gap_sim=True, gap_n_samples=5,
        gap_n_per_path=3, gap_size_max=0.02,
        gap_max_calmar_drop_pct=99.0, gap_max_mdd_increase_pct=999.0,
    )
    assert isinstance(rep.noise_result, NoiseInjectionResult)
    assert isinstance(rep.gap_result, GapSimResult)
    out = rep.report()
    assert "Noise injection" in out
    assert "Gap sim" in out


def test_pipeline_failures_aggregate():
    """Tight noise threshold + heavy noise should fail; failure listed; overall=False."""
    prices = _synth_prices()
    rep = validate_pipeline(
        _factory(), prices, "noise-fail",
        costs=ZERO_costs, wf_windows=_FAST_WF,
        mc_n_paths=20, min_wf_pass=0,
        run_noise_injection=True, noise_n_samples=10,
        noise_sigma_bps=500.0,           # 5% per-bar noise: aggressive
        noise_max_drop_pct=0.0001,       # essentially zero tolerance: must fail
    )
    assert rep.overall_passed is False
    assert any("Noise injection" in f for f in rep.failures)
