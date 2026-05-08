"""Tests for R40 (benchmark scaffold) + R43 (gateway RBAC)."""
from __future__ import annotations

import pytest

from quantforge.agent_gateway.rbac_roles import (
    GatewayRBAC,
    KILL_SWITCH,
    LIVE_TRADE,
    PAPER_TRADE,
    PROMOTE_STRATEGY,
    READ_AUDIT,
    ROTATE_KEYS,
    RUN_BACKTEST,
)
from quantforge.examples.benchmarks import (
    BenchmarkResult,
    bench_ga_loop,
    bench_single_asset_30y,
    bench_triage_10k,
    bench_validation_pipeline,
    run_all,
)


# --------------------------------------------------------------------------
# R40 benchmark scaffold
# --------------------------------------------------------------------------


def test_bench_triage_10k_runs_and_hashes_output():
    res = bench_triage_10k(seed=42)
    assert isinstance(res, BenchmarkResult)
    assert res.name == "triage_10k"
    assert res.wall_seconds > 0
    assert len(res.output_hash) == 64
    assert res.extra["n_variants"] == 10_000


def test_bench_triage_10k_is_deterministic():
    a = bench_triage_10k(seed=7)
    b = bench_triage_10k(seed=7)
    assert a.output_hash == b.output_hash


def test_bench_validation_pipeline_returns_result():
    res = bench_validation_pipeline(seed=42)
    assert isinstance(res, BenchmarkResult)
    assert res.name == "validation_pipeline"
    assert "n_resamples" in res.extra


def test_bench_ga_loop_runs():
    res = bench_ga_loop(seed=42, generations=3, population=10)
    assert res.name == "ga_loop"
    assert res.extra["generations"] == 3


def test_bench_single_asset_30y_returns_metrics():
    res = bench_single_asset_30y(seed=42)
    assert res.name == "single_asset_30y"
    assert "sharpe" in res.extra


def test_run_all_returns_four_benchmarks():
    results = run_all(seed=42)
    names = {r.name for r in results}
    assert names == {
        "triage_10k", "validation_pipeline",
        "ga_loop", "single_asset_30y",
    }


# --------------------------------------------------------------------------
# R43 gateway RBAC
# --------------------------------------------------------------------------


def test_standard_rbac_lists_three_roles():
    rbac = GatewayRBAC.standard()
    assert set(rbac.list_roles()) == {"junior_ops", "senior_ops", "admin"}


def test_junior_ops_can_paper_but_not_live():
    rbac = GatewayRBAC.standard()
    rbac.assign("alice", "junior_ops")
    assert rbac.authorise("alice", PAPER_TRADE)
    assert not rbac.authorise("alice", LIVE_TRADE)
    assert rbac.authorise("alice", RUN_BACKTEST)


def test_senior_ops_can_live_and_kill_switch():
    rbac = GatewayRBAC.standard()
    rbac.assign("bob", "senior_ops")
    assert rbac.authorise("bob", LIVE_TRADE)
    assert rbac.authorise("bob", KILL_SWITCH)
    assert rbac.authorise("bob", PROMOTE_STRATEGY)
    assert not rbac.authorise("bob", ROTATE_KEYS)


def test_admin_has_every_documented_permission():
    rbac = GatewayRBAC.standard()
    rbac.assign("carol", "admin")
    for perm in (
        PAPER_TRADE, LIVE_TRADE, PROMOTE_STRATEGY, RUN_BACKTEST,
        READ_AUDIT, KILL_SWITCH, ROTATE_KEYS,
    ):
        assert rbac.authorise("carol", perm), perm


def test_unknown_role_raises():
    rbac = GatewayRBAC.standard()
    with pytest.raises(KeyError):
        rbac.assign("dave", "wizard")


def test_require_raises_permission_error():
    rbac = GatewayRBAC.standard()
    rbac.assign("alice", "junior_ops")
    with pytest.raises(PermissionError):
        rbac.require("alice", LIVE_TRADE)


def test_permissions_for_returns_role_perm_set():
    rbac = GatewayRBAC.standard()
    perms = rbac.permissions_for("junior_ops")
    assert PAPER_TRADE in perms
    assert LIVE_TRADE not in perms


def test_unassigned_user_denied_by_default():
    rbac = GatewayRBAC.standard()
    assert not rbac.authorise("nobody", PAPER_TRADE)
