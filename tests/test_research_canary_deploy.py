"""Tests for quantforge.research.canary_deploy."""
from __future__ import annotations
import numpy as np
import pytest

from aurora.research.canary_deploy import CanaryDeployer, CanaryReport


def test_construction_validates():
    with pytest.raises(ValueError):
        CanaryDeployer(name="")
    with pytest.raises(ValueError):
        CanaryDeployer(name="x", initial_alloc=0.0)
    with pytest.raises(ValueError):
        CanaryDeployer(name="x", initial_alloc=0.5, max_alloc=0.4)
    with pytest.raises(ValueError):
        CanaryDeployer(name="x", step_alloc=0)
    with pytest.raises(ValueError):
        CanaryDeployer(name="x", dd_floor=0.1)
    with pytest.raises(ValueError):
        CanaryDeployer(name="x", promotion_window=0)


def test_initial_status_is_canary():
    cd = CanaryDeployer(name="s")
    assert cd.status == "canary"
    assert cd.allocation == 0.01


def test_dd_breach_retires():
    cd = CanaryDeployer(name="s", dd_floor=-0.05, min_observations=5,
                        sharpe_gate=10.0)
    # construct a sharp drawdown
    for r in [0.01, 0.01, -0.20, -0.05, -0.05]:
        rep = cd.update(r)
    assert rep.status == "retired"
    assert cd.allocation == 0.0


def test_scaling_then_promoted():
    cd = CanaryDeployer(name="s", initial_alloc=0.01, step_alloc=0.10,
                        max_alloc=0.30, sharpe_gate=0.0,
                        dd_floor=-0.99, promotion_window=2,
                        min_observations=2)
    rng = np.random.default_rng(42)
    for _ in range(200):
        # positive drift, never breach dd floor
        r = float(rng.normal(0.005, 0.005))
        rep = cd.update(r)
    assert rep.status in ("scaling", "promoted")
    assert rep.allocation > 0.01


def test_retired_state_is_sticky():
    cd = CanaryDeployer(name="s", dd_floor=-0.05, min_observations=2)
    cd.update(0.01)
    cd.update(-0.20)  # produces a drawdown beyond floor
    assert cd.status == "retired"
    rep = cd.update(0.5)
    assert rep.status == "retired"
    assert cd.allocation == 0.0


def test_report_fields():
    cd = CanaryDeployer(name="s")
    rep = cd.update(0.001)
    assert isinstance(rep, CanaryReport)
    assert rep.name == "s"
    assert rep.n_observations == 1
