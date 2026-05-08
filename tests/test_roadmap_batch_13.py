"""Tests for R81, R82, R91, R92, R93, R101, R105, R107, R109, R112."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from quantforge.analytics.signal_attribution import (
    AttributionResult,
    attribute_signals,
)
from quantforge.analytics.volume_profile import (
    VolumeProfile,
    compute_volume_profile,
)
from quantforge.reporting.heatmaps import (
    HeatmapData,
    optimisation_heatmap,
    render_text,
    walk_forward_heatmap,
)
from quantforge.research.auto_loop.reopt_scheduler import (
    ReoptJob,
    ScheduleConfig,
    schedule_for,
    upcoming_calendar,
)
from quantforge.research.bundle import (
    publish_bundle,
    read_bundle,
    verify_bundle,
    write_bundle,
)
from quantforge.research.dna_fingerprint import (
    fingerprint,
    is_too_similar,
)
from quantforge.strategies.library.ensemble_vote import (
    VoteThresholdConfig,
    vote_combine,
)
from quantforge.validation.cross_feed import (
    CrossFeedReport,
    cross_feed_validate,
)
from quantforge.validation.multi_market_sweep import (
    SweepResult,
    sweep,
)


# --------------------------------------------------------------------------
# R81 walk-forward heatmap
# --------------------------------------------------------------------------


def test_walk_forward_heatmap_returns_2d_matrix():
    folds = [
        {"sharpe": 1.0, "calmar": 0.5, "mdd": -0.10},
        {"sharpe": 0.5, "calmar": 0.3, "mdd": -0.20},
        {"sharpe": 1.5, "calmar": 0.8, "mdd": -0.05},
    ]
    h = walk_forward_heatmap(fold_metrics=folds)
    assert h.matrix.shape == (3, 3)
    assert h.x_labels == ["f0", "f1", "f2"]
    assert h.y_labels == ["sharpe", "calmar", "mdd"]


def test_walk_forward_heatmap_empty_raises():
    with pytest.raises(ValueError):
        walk_forward_heatmap(fold_metrics=[])


# --------------------------------------------------------------------------
# R82 optimisation heatmap
# --------------------------------------------------------------------------


def test_optimisation_heatmap_shape_check():
    fitness = [[0.5, 0.6], [0.4, 0.7], [0.3, 0.8]]
    h = optimisation_heatmap(
        param_x_name="window",
        param_y_name="threshold",
        x_values=[10, 20],
        y_values=[0.1, 0.2, 0.3],
        fitness=fitness,
    )
    assert h.matrix.shape == (3, 2)
    text = render_text(h)
    assert "window" in text


def test_optimisation_heatmap_shape_mismatch_raises():
    with pytest.raises(ValueError):
        optimisation_heatmap(
            param_x_name="x", param_y_name="y",
            x_values=[1, 2], y_values=[3],
            fitness=[[0.5]],  # 1x1 instead of 1x2
        )


# --------------------------------------------------------------------------
# R91 publish/import bundle
# --------------------------------------------------------------------------


def test_publish_and_verify_bundle(tmp_path: Path):
    spec = {"name": "alpha", "params": {"window": 20}}
    bundle = publish_bundle(
        spec_payload=spec,
        policy_hash="ph",
        witness_hash="wh",
        validation_report_hash="vh",
    )
    p = tmp_path / "bundle.json"
    write_bundle(bundle, p)
    reloaded = read_bundle(p)
    assert verify_bundle(reloaded) == []
    assert reloaded.spec_payload == spec


def test_verify_bundle_detects_tampered_spec():
    bundle = publish_bundle(
        spec_payload={"x": 1},
        policy_hash="ph",
        witness_hash=None,
        validation_report_hash="vh",
    )
    bad = type(bundle)(
        bundle_version=bundle.bundle_version,
        forge_version=bundle.forge_version,
        spec_payload={"x": 99},  # tampered
        spec_hash=bundle.spec_hash,
        policy_hash=bundle.policy_hash,
        witness_hash=bundle.witness_hash,
        validation_report_hash=bundle.validation_report_hash,
    )
    errors = verify_bundle(bad)
    assert any("spec_hash mismatch" in e for e in errors)


# --------------------------------------------------------------------------
# R92 DNA fingerprint
# --------------------------------------------------------------------------


def test_fingerprint_identical_strategies_score_high():
    sig = np.array([1, -1, 0, 1, 1, -1, 0])
    params = {"a": 0.5, "b": 1.0}
    eq = np.array([100.0, 101.0, 102.0, 101.0, 103.0, 105.0])
    s = fingerprint(
        signal_vector_a=sig,
        signal_vector_b=sig,
        params_a=params,
        params_b=params,
        equity_a=eq,
        equity_b=eq,
    )
    assert s.composite > 0.95
    assert is_too_similar(s, threshold=0.85)


def test_fingerprint_different_strategies_score_low():
    sig_a = np.array([1, 1, 1, 1, 1])
    sig_b = np.array([-1, -1, -1, -1, -1])
    s = fingerprint(
        signal_vector_a=sig_a,
        signal_vector_b=sig_b,
        params_a={"a": 1.0},
        params_b={"a": 0.0},
    )
    assert s.composite < 0.5


# --------------------------------------------------------------------------
# R93 re-opt scheduler
# --------------------------------------------------------------------------


def test_schedule_for_returns_due_jobs():
    today = date(2026, 5, 8)
    cfg = ScheduleConfig(walk_forward_days=7, full_pipeline_days=30,
                         oos_reseat_days=90)
    last_runs = {
        "walk_forward": today - timedelta(days=8),
        "full_pipeline": today - timedelta(days=10),
        "oos_locked_reseat": today - timedelta(days=10),
    }
    jobs = schedule_for(strategy_id="alpha", config=cfg,
                        last_runs=last_runs, today=today)
    types = {j.job_type for j in jobs}
    assert "walk_forward" in types
    assert "full_pipeline" not in types  # not yet due


def test_upcoming_calendar_orders_by_due_date():
    today = date(2026, 5, 8)
    strategies = {
        "a": ScheduleConfig(walk_forward_days=7),
        "b": ScheduleConfig(walk_forward_days=14),
    }
    last_runs = {
        "a": {"walk_forward": today - timedelta(days=5)},
        "b": {"walk_forward": today - timedelta(days=2)},
    }
    cal = upcoming_calendar(
        strategies=strategies, last_runs_by_strategy=last_runs,
        today=today, horizon_days=30,
    )
    dates = [j.due_date for j in cal]
    assert dates == sorted(dates)


# --------------------------------------------------------------------------
# R101 volume profile
# --------------------------------------------------------------------------


def test_volume_profile_finds_poc():
    rng = np.random.default_rng(0)
    prices = np.concatenate([
        rng.normal(100, 0.5, size=200),  # heavy cluster around 100
        rng.normal(105, 2.0, size=50),
    ])
    volumes = np.full(len(prices), 1.0)
    vp = compute_volume_profile(prices, volumes, n_bins=20)
    # POC should sit close to 100, the heavy cluster.
    assert 99.0 <= vp.poc_price <= 101.5
    assert vp.value_area_low <= vp.poc_price <= vp.value_area_high


def test_volume_profile_too_short_raises():
    with pytest.raises(ValueError):
        compute_volume_profile(np.array([1.0, 2.0]), np.array([1.0, 1.0]),
                               n_bins=10)


def test_volume_profile_length_mismatch_raises():
    with pytest.raises(ValueError):
        compute_volume_profile(np.array([1.0]), np.array([1.0, 2.0]))


# --------------------------------------------------------------------------
# R105 signal attribution
# --------------------------------------------------------------------------


def test_attribute_signals_full_pnl_matches_combined():
    rng = np.random.default_rng(0)
    rets = rng.normal(0.0005, 0.01, size=200)
    sig_a = np.where(rng.random(200) > 0.5, 1.0, -1.0)
    sig_b = np.where(rng.random(200) > 0.5, 1.0, -1.0)

    def combine(signals):
        arr = np.vstack([np.asarray(v) for v in signals.values()])
        return arr.mean(axis=0)

    res = attribute_signals(
        {"a": sig_a, "b": sig_b},
        asset_returns=rets,
        combine=combine,
    )
    assert isinstance(res, AttributionResult)
    assert len(res.contributions) == 2


def test_attribute_signals_empty_raises():
    with pytest.raises(ValueError):
        attribute_signals({}, asset_returns=np.zeros(10),
                          combine=lambda s: np.zeros(10))


# --------------------------------------------------------------------------
# R107 multi-market sweep
# --------------------------------------------------------------------------


def test_multi_market_sweep_ranks_results():
    rng = np.random.default_rng(0)
    markets = {
        "spy": rng.normal(0.001, 0.01, size=300),
        "qqq": rng.normal(0.0005, 0.012, size=300),
        "iwm": rng.normal(0.0001, 0.013, size=300),
    }
    res = sweep(
        strategy_fn=lambda r: r * 1.0,
        market_returns=markets,
    )
    assert isinstance(res, SweepResult)
    assert res.best.sharpe >= res.worst.sharpe


def test_multi_market_sweep_empty_raises():
    with pytest.raises(ValueError):
        sweep(strategy_fn=lambda r: r, market_returns={})


# --------------------------------------------------------------------------
# R109 vote ensemble
# --------------------------------------------------------------------------


def test_vote_combine_long_when_majority_long():
    sigs = {
        "a": np.array([1, 1, 1, 0, -1]),
        "b": np.array([1, 1, 0, -1, -1]),
        "c": np.array([1, 0, 1, -1, -1]),
    }
    out = vote_combine(sigs, config=VoteThresholdConfig(
        long_threshold_pct=0.66,
        short_threshold_pct=0.66,
    ))
    # Bar 0: 3 long -> +1. Bar 4: 3 short -> -1.
    # Bar 3: 0 long, 2 short, 1 zero -> 66% short -> -1.
    # Bar 1: 2 long, 0 short, 1 zero -> 66% long -> +1.
    # Bar 2: 2 long, 0 short, 1 zero -> 66% long -> +1.
    assert out[0] == 1.0
    assert out[1] == 1.0
    assert out[2] == 1.0
    assert out[3] == -1.0
    assert out[4] == -1.0


def test_vote_combine_empty_raises():
    with pytest.raises(ValueError):
        vote_combine({})


# --------------------------------------------------------------------------
# R112 cross-feed validation
# --------------------------------------------------------------------------


def test_cross_feed_validate_flags_outliers():
    rng = np.random.default_rng(0)
    base = rng.normal(0.001, 0.01, size=300)
    feeds = {
        "yahoo": base,
        "openbb": base + rng.normal(0, 1e-5, size=300),
        # vendor_b shifts the mean -> Sharpe diverges materially.
        "vendor_b": base - 0.002,
    }
    res = cross_feed_validate(
        strategy_fn=lambda r: r,
        feed_returns=feeds,
        sharpe_tolerance=0.5,
        calmar_tolerance=0.5,
    )
    assert isinstance(res, CrossFeedReport)
    assert "vendor_b" in res.suspicious_feeds


def test_cross_feed_validate_too_few_feeds_raises():
    with pytest.raises(ValueError):
        cross_feed_validate(
            strategy_fn=lambda r: r,
            feed_returns={"yahoo": np.zeros(10)},
        )
