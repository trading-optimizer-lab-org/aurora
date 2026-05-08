"""Tests for validation.pipeline polish items.

Specifically: DSR is no longer skipped when n_trials_optimization == 1.
Single-parameter strategies must still pass through the DSR gate (collapses
to PSR-vs-zero) and the pipeline must call ``deflated_sharpe_check``.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from quantforge.core.seed import set_global_seed
from quantforge.core.costs import ZERO_costs
from quantforge.strategies.library import MACross
from quantforge.validation import pipeline as pipe_mod
from quantforge.validation.pipeline import validate_pipeline
from quantforge.validation.walk_forward import WFWindow


def _prices(n: int = 1500, seed: int = 17) -> pd.Series:
    set_global_seed(seed)
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


def test_pipeline_does_not_skip_dsr_n_trials_one(monkeypatch):
    """When n_trials_optimization=1 the DSR gate must still run (collapses to PSR).

    Pipeline contract for n_trials_optimization=1:
      * ``deflated_sharpe_check`` is still invoked (we did not silently
        bypass it).
      * ``rep.dsr`` carries the PSR-vs-zero value and is in [0, 1].
      * ``rep.dsr_passed`` is None — the knife-edge of PSR-vs-zero against a
        0.95 default is intentionally not enforced. Callers wanting a PSR
        gate at n_trials=1 must pass ``min_psr`` to deflated_sharpe_check
        directly.
    """
    calls = {"n": 0}

    real = pipe_mod.deflated_sharpe_check

    def spy(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(pipe_mod, "deflated_sharpe_check", spy)

    rep = validate_pipeline(
        _factory, _prices(), name="dsr-n1",
        costs=ZERO_costs, wf_windows=_FAST_WF, mc_n_paths=20, min_wf_pass=0,
        n_trials_optimization=1,
    )

    assert calls["n"] >= 1, "deflated_sharpe_check must be invoked even with n_trials=1"
    assert rep.dsr is not None, "DSR value must be reported, not silently skipped"
    # n_trials==1 explicitly leaves dsr_passed as None to avoid the PSR-vs-0.95
    # knife-edge. The metric is still reported for visibility.
    assert rep.dsr_passed is None
    # DSR collapses to PSR-vs-zero in [0, 1]
    assert 0.0 <= rep.dsr <= 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
