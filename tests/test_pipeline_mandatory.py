"""Mandatory-gate test for ``validation.pipeline.validate_pipeline``.

Pin the set of gates the pipeline currently invokes so a refactor that drops
or skips one is caught immediately. Each gate function is replaced with a
spy that records the call; we then assert the spy was called.

This test reflects the gates ACTUALLY wired into ``validate_pipeline`` today:
    - walk_forward
    - monte_carlo_bootstrap
    - monte_carlo_trade_reorder
    - spp                          (only when spp_param_ranges + factory given)
    - runtime_lookahead_check
    - deflated_sharpe_check        (always; n_trials=1 collapses to PSR-vs-zero
                                    and emits UserWarning)
    - noise_injection              (only when run_noise_injection=True)
    - gap_sim                      (only when run_gap_sim=True)

Not yet wired into ``validate_pipeline``:
    purged_cv, cscv, structural_breaks (chow/cusum/sadf), scenarios,
    tail_risk, correlation_stress. These exist as standalone modules but are
    invoked outside the pipeline (e.g. via the ``forge`` CLI subcommands).
    If they are ever wired in, extend this test to cover them.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantforge.core.costs import ZERO_costs
from quantforge.strategies.library import MACross
from quantforge.validation import pipeline as pipe_mod
from quantforge.validation.pipeline import validate_pipeline
from quantforge.validation.walk_forward import WFWindow


def _prices(n: int = 1500, seed: int = 17) -> pd.Series:
    """Span enough bars so split_is_oos has >50 on each side."""
    idx = pd.date_range("2008-01-02", periods=n, freq="B")
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0005, 0.012, n)
    return pd.Series(100.0 * np.cumprod(1.0 + rets), index=idx, name="MAND")


def _factory():
    return MACross()


_FAST_WF = [
    WFWindow("WF1", "2008-01-02", "2010-12-31", "2011-01-01", "2011-12-31"),
    WFWindow("WF2", "2008-01-02", "2011-12-31", "2012-01-01", "2012-12-31"),
]


class _Spy:
    """Wrap a callable so we can assert it ran without changing return shape."""

    def __init__(self, real):
        self._real = real
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        return self._real(*args, **kwargs)


@pytest.fixture
def spies(monkeypatch):
    """Replace each gate inside pipeline.py with a Spy and return the dict."""
    targets = {
        "walk_forward": pipe_mod.walk_forward,
        "monte_carlo_bootstrap": pipe_mod.monte_carlo_bootstrap,
        "monte_carlo_trade_reorder": pipe_mod.monte_carlo_trade_reorder,
        "spp": pipe_mod.spp,
        "runtime_lookahead_check": pipe_mod.runtime_lookahead_check,
        "deflated_sharpe_check": pipe_mod.deflated_sharpe_check,
        "noise_injection": pipe_mod.noise_injection,
        "gap_sim": pipe_mod.gap_sim,
    }
    spies = {name: _Spy(fn) for name, fn in targets.items()}
    for name, spy in spies.items():
        monkeypatch.setattr(pipe_mod, name, spy)
    return spies


def test_pipeline_invokes_core_gates(spies):
    """Default pipeline must call WF + both MC paths + lookahead at minimum."""
    rep = validate_pipeline(
        _factory, _prices(), name="mandatory-core",
        costs=ZERO_costs, wf_windows=_FAST_WF, mc_n_paths=20, min_wf_pass=0,
    )

    assert spies["walk_forward"].calls >= 1
    assert spies["monte_carlo_bootstrap"].calls >= 1
    assert spies["monte_carlo_trade_reorder"].calls >= 1
    assert spies["runtime_lookahead_check"].calls >= 1
    # SPP is conditional and was not configured.
    assert spies["spp"].calls == 0
    # DSR now ALWAYS runs (collapses to PSR-vs-zero when n_trials=1).
    assert spies["deflated_sharpe_check"].calls >= 1
    # noise / gap default off.
    assert spies["noise_injection"].calls == 0
    assert spies["gap_sim"].calls == 0
    # report shape:
    assert rep is not None
    assert hasattr(rep, "overall_passed")


def test_pipeline_runs_spp_when_configured(spies):
    """Passing spp_param_ranges + factory must trigger spp()."""

    def factory_with(**kw):
        return MACross(**{**MACross.spec().params, **kw})

    validate_pipeline(
        _factory, _prices(), name="mandatory-spp",
        costs=ZERO_costs, wf_windows=_FAST_WF, mc_n_paths=20, min_wf_pass=0,
        spp_param_ranges=MACross.spec().param_ranges,
        spp_strategy_factory=factory_with,
    )
    assert spies["spp"].calls >= 1


def test_pipeline_runs_dsr_when_n_trials_gt_1(spies):
    """deflated_sharpe_check fires only when n_trials_optimization > 1."""
    validate_pipeline(
        _factory, _prices(), name="mandatory-dsr",
        costs=ZERO_costs, wf_windows=_FAST_WF, mc_n_paths=20, min_wf_pass=0,
        n_trials_optimization=10,
    )
    assert spies["deflated_sharpe_check"].calls >= 1


def test_pipeline_runs_noise_and_gap_when_enabled(spies):
    """run_noise_injection / run_gap_sim must invoke their gates."""
    validate_pipeline(
        _factory, _prices(), name="mandatory-extras",
        costs=ZERO_costs, wf_windows=_FAST_WF, mc_n_paths=20, min_wf_pass=0,
        run_noise_injection=True, noise_n_samples=3, noise_max_drop_pct=99.0,
        run_gap_sim=True, gap_n_samples=3, gap_max_calmar_drop_pct=99.0,
        gap_max_mdd_increase_pct=99.0,
    )
    assert spies["noise_injection"].calls >= 1
    assert spies["gap_sim"].calls >= 1
