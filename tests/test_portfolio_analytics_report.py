# ruff: noqa: N806
"""Tests for the portfolio analytics report (R172).

Covers:
- Contributions sum to portfolio return within tolerance.
- Report carries policy + snapshot hash placeholders.
- Markdown rendering is deterministic (same input -> identical output).
- Attribution by sector handles missing metadata gracefully.
"""
from __future__ import annotations

import numpy as np
import pytest
from aurora.portfolio.attribution import (
    benchmark_relative_alpha,
    contribution_to_return,
    contribution_to_risk,
    exposure_by_group,
)
from aurora.reporting.portfolio_report import (
    PortfolioReport,
    build_portfolio_report,
)


def _synth_returns(seed: int = 0, T: int = 250, N: int = 4) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(0.0008, 0.012, size=(T, N))


# --------------------------------------------------------------------------- #
# Contributions sum / closed-form check                                       #
# --------------------------------------------------------------------------- #
def test_contribution_to_return_sums_to_portfolio_mean():
    R = _synth_returns(seed=201, T=200, N=4)
    w = np.array([0.4, 0.3, 0.2, 0.1])
    out = contribution_to_return(w, R)
    portfolio_mean = float(np.mean(R @ w))
    # Sum of per-asset contributions equals portfolio mean exactly
    # (within float tolerance) because mean is a linear functional.
    assert out["total"] == pytest.approx(portfolio_mean, abs=1e-12)
    assert out["portfolio"] == pytest.approx(portfolio_mean, abs=1e-12)


def test_contribution_to_risk_sums_to_portfolio_variance():
    R = _synth_returns(seed=202, T=300, N=4)
    w = np.array([0.4, 0.3, 0.2, 0.1])
    out = contribution_to_risk(w, R)
    portfolio_var = float(np.var(R @ w, ddof=1))
    assert out["total"] == pytest.approx(portfolio_var, rel=1e-9)
    # Shares sum to ~ 1 (or 0 when total <= 0).
    if out["total"] > 0:
        assert float(np.sum(out["share"])) == pytest.approx(1.0, abs=1e-9)


# --------------------------------------------------------------------------- #
# Report payload + hash placeholders                                          #
# --------------------------------------------------------------------------- #
def test_report_carries_hash_placeholders():
    R = _synth_returns(seed=203, T=200, N=4)
    w = np.array([0.25, 0.25, 0.25, 0.25])
    rep = build_portfolio_report(
        w, R,
        policy_hash="abc123",
        snapshot_hash="def456",
        data_quality_status="ok",
    )
    assert isinstance(rep, PortfolioReport)
    assert rep.policy_hash == "abc123"
    assert rep.snapshot_hash == "def456"
    assert rep.data_quality_status == "ok"


# --------------------------------------------------------------------------- #
# Determinism of markdown rendering                                           #
# --------------------------------------------------------------------------- #
def test_markdown_is_deterministic():
    R = _synth_returns(seed=204, T=200, N=3)
    w = np.array([0.5, 0.3, 0.2])
    rep1 = build_portfolio_report(
        w, R,
        sectors=("tech", "tech", "energy"),
        policy_hash="HASH",
        snapshot_hash="SNAP",
        data_quality_status="ok",
    )
    rep2 = build_portfolio_report(
        w, R,
        sectors=("tech", "tech", "energy"),
        policy_hash="HASH",
        snapshot_hash="SNAP",
        data_quality_status="ok",
    )
    md1 = rep1.render_markdown()
    md2 = rep2.render_markdown()
    assert md1 == md2
    assert "policy_hash: `HASH`" in md1
    assert "snapshot_hash: `SNAP`" in md1


# --------------------------------------------------------------------------- #
# Sector attribution / missing metadata                                       #
# --------------------------------------------------------------------------- #
def test_attribution_by_sector_buckets_missing_to_unknown():
    w = np.array([0.4, 0.3, 0.2, 0.1])
    sectors = ("tech", None, "", "energy")
    out = exposure_by_group(w, sectors)
    # 0.3 + 0.2 -> unknown; 0.4 -> tech; 0.1 -> energy
    assert out["unknown"] == pytest.approx(0.5, abs=1e-12)
    assert out["tech"] == pytest.approx(0.4, abs=1e-12)
    assert out["energy"] == pytest.approx(0.1, abs=1e-12)


def test_report_default_sectors_bucket_to_unknown_when_omitted():
    R = _synth_returns(seed=205, T=120, N=3)
    w = np.array([0.5, 0.3, 0.2])
    rep = build_portfolio_report(w, R)  # no sectors arg
    # All weight should bucket into "unknown"
    assert "unknown" in rep.exposure_by_sector_dict
    assert rep.exposure_by_sector_dict["unknown"] == pytest.approx(
        1.0, abs=1e-12,
    )


# --------------------------------------------------------------------------- #
# Benchmark alpha / beta sanity                                               #
# --------------------------------------------------------------------------- #
def test_benchmark_relative_alpha_handles_identical_series():
    R = _synth_returns(seed=206, T=200, N=2)
    w = np.array([0.5, 0.5])
    port = R @ w
    out = benchmark_relative_alpha(port, port)
    # Beta of a series against itself is exactly 1.
    assert out["beta"] == pytest.approx(1.0, rel=1e-9)
    assert out["alpha"] == pytest.approx(0.0, abs=1e-12)
    assert out["r_squared"] == pytest.approx(1.0, abs=1e-9)
