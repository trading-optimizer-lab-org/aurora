"""Tests for quantforge.execution.implementation_shortfall."""
from __future__ import annotations

import pytest

from aurora.execution.implementation_shortfall import (
    ImplementationShortfallOptimizer,
    ISConfig,
)


def test_is_config_defaults():
    cfg = ISConfig()
    assert cfg.eta >= 0
    assert cfg.gamma >= 0
    assert cfg.sigma >= 0


def test_is_config_negative_rejected():
    with pytest.raises(ValueError):
        ISConfig(eta=-1)
    with pytest.raises(ValueError):
        ISConfig(gamma=-0.1)
    with pytest.raises(ValueError):
        ISConfig(sigma=-0.01)


def test_is_config_n_bounds_rejected():
    with pytest.raises(ValueError):
        ISConfig(n_min=0)
    with pytest.raises(ValueError):
        ISConfig(n_min=10, n_max=5)


def test_is_expected_cost_positive():
    opt = ImplementationShortfallOptimizer()
    c = opt.expected_cost(parent_qty=10_000, n=10)
    assert c > 0


def test_is_invalid_qty_or_n():
    opt = ImplementationShortfallOptimizer()
    with pytest.raises(ValueError):
        opt.expected_cost(0, 5)
    with pytest.raises(ValueError):
        opt.expected_cost(100, 0)


def test_is_optimize_returns_within_bounds():
    cfg = ISConfig(n_min=1, n_max=50)
    opt = ImplementationShortfallOptimizer(cfg)
    res = opt.optimize(10_000)
    assert cfg.n_min <= res.optimal_n <= cfg.n_max
    assert res.expected_cost >= 0


def test_is_optimize_decomposition_keys():
    opt = ImplementationShortfallOptimizer()
    res = opt.optimize(5_000)
    assert "delay" in res.decomposition
    assert "trading" in res.decomposition
    assert "opportunity" in res.decomposition


def test_is_optimize_invalid_qty():
    opt = ImplementationShortfallOptimizer()
    with pytest.raises(ValueError):
        opt.optimize(0)


def test_is_realized_shortfall_buy_costs_positive_when_paying_more():
    opt = ImplementationShortfallOptimizer()
    out = opt.realized_shortfall(
        decision_price=100.0,
        arrival_price=100.5,
        avg_exec_price=101.0,
        end_price=102.0,
        parent_qty=1000,
        executed_qty=800,
        side="buy",
    )
    # buy and prices rose: every component should be positive cost
    assert out["delay"] > 0
    assert out["trading"] > 0
    assert out["opportunity"] > 0
    assert out["total"] == pytest.approx(out["delay"] + out["trading"] + out["opportunity"])


def test_is_realized_shortfall_sell_flipped_sign():
    opt = ImplementationShortfallOptimizer()
    out = opt.realized_shortfall(
        decision_price=100.0,
        arrival_price=99.5,
        avg_exec_price=99.0,
        end_price=98.0,
        parent_qty=1000,
        executed_qty=800,
        side="sell",
    )
    # sell and prices fell: every component is positive cost
    assert out["delay"] > 0
    assert out["trading"] > 0
    assert out["opportunity"] > 0


def test_is_realized_invalid_executed_qty():
    opt = ImplementationShortfallOptimizer()
    with pytest.raises(ValueError):
        opt.realized_shortfall(100, 100, 100, 100, parent_qty=10,
                                executed_qty=20)


def test_is_optimize_risk_aversion_changes_n():
    """Different risk aversions yield different optimal slice counts.

    In this cost model, risk = lambda * sigma**2 * (qty / n) decreases with n,
    so higher lambda generally pushes the optimum to MORE slices (smaller
    per-slice qty). We just assert that the result actually responds.
    """
    a = ImplementationShortfallOptimizer(
        ISConfig(eta=1e-5, gamma=1e-5, sigma=0.01, risk_aversion=0.0,
                 n_min=1, n_max=200)
    )
    b = ImplementationShortfallOptimizer(
        ISConfig(eta=1e-5, gamma=1e-5, sigma=0.01, risk_aversion=10.0,
                 n_min=1, n_max=200)
    )
    qty = 100_000
    n_a = a.optimize(qty).optimal_n
    n_b = b.optimize(qty).optimal_n
    assert n_a != n_b
