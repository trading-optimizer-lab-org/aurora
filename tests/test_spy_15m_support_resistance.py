from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from scripts.run_spy_15m_support_resistance import (
    build_feature_frame,
    feature_families,
    prepare_matrix,
    sample_params,
)

pytestmark = pytest.mark.filterwarnings("ignore::pandas.errors.PerformanceWarning")


def make_spy_15m_bars(days: int = 35) -> pd.DataFrame:
    rng = np.random.default_rng(17)
    stamps = []
    for day in pd.bdate_range("2026-01-02", periods=days):
        start = day + pd.Timedelta(hours=9, minutes=30)
        stamps.extend(start + pd.Timedelta(minutes=15 * i) for i in range(26))
    idx = pd.DatetimeIndex(stamps)
    drift = np.linspace(0.0, 8.0, len(idx))
    wave = np.sin(np.arange(len(idx)) / 11.0) * 1.7
    noise = rng.normal(0.0, 0.25, len(idx)).cumsum()
    close = pd.Series(430.0 + drift + wave + noise, index=idx)
    open_ = close.shift(1).fillna(close.iloc[0]) + rng.normal(0.0, 0.08, len(idx))
    high = pd.concat([open_, close], axis=1).max(axis=1) + rng.uniform(0.05, 0.7, len(idx))
    low = pd.concat([open_, close], axis=1).min(axis=1) - rng.uniform(0.05, 0.7, len(idx))
    volume = pd.Series(1_000_000 + rng.integers(0, 250_000, len(idx)), index=idx)
    return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume}, index=idx)


def test_spy_15m_support_resistance_workflow_is_manual_355_jobs() -> None:
    path = Path(".github/workflows/spy-15m-support-resistance-355jobs.yml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["name"] == "SPY 15m Support Resistance 355 Jobs"
    assert "workflow_dispatch" in data[True]
    assert "push" not in data[True]
    text = path.read_text(encoding="utf-8")
    assert "range(355)" in text
    assert "max-parallel: 178" in text
    assert "max-parallel: 177" in text
    assert data[True]["workflow_dispatch"]["inputs"]["period"]["default"] == "60d"
    assert data[True]["workflow_dispatch"]["inputs"]["target_bars"]["default"] == "4"
    assert "--interval 15m" in text


def test_build_feature_frame_contains_all_support_resistance_families() -> None:
    panel = build_feature_frame(make_spy_15m_bars(), target_bars=4)
    expected = [
        "sr_roll_dist_prior_high_26b",
        "sr_pivot_r1_gap",
        "sr_opening_range_high_gap_4b",
        "sr_vwap_session_gap",
        "sr_volume_profile_poc_gap_26b",
        "sr_fib_0382_gap_52b",
        "sr_round_nearest_gap_1p0",
        "sr_band_bollinger_upper_gap_52b",
        "sr_trendline_upper_gap_52b",
        "sr_fractal_pivot_high_gap_3b",
        "sr_gap_upper_gap",
        "sr_confluence_support_count",
        "target_return",
    ]
    for column in expected:
        assert column in panel.columns
    feature_cols = [c for c in panel.columns if c not in {"target_return", "target_direction"}]
    families = feature_families(feature_cols)
    for family in [
        "rolling_levels",
        "pivots",
        "opening_range",
        "vwap",
        "volume_profile",
        "fibonacci",
        "round_numbers",
        "dynamic_bands",
        "fractal_pivots",
        "gaps",
        "candles",
        "session",
        "confluence",
    ]:
        assert families[family], family


def test_prepare_matrix_uses_last_fraction_as_validation() -> None:
    panel = build_feature_frame(make_spy_15m_bars(), target_bars=4)
    feature_cols = [c for c in panel.columns if c not in {"target_return", "target_direction"}]
    matrix, target, train_mask, validation_mask = prepare_matrix(panel, feature_cols, validation_fraction=0.25)
    assert matrix.shape[0] == len(panel)
    assert matrix.shape[1] == len(feature_cols)
    assert target.shape[0] == len(panel)
    assert train_mask.sum() > validation_mask.sum()
    assert not train_mask[-1]
    assert validation_mask[-1]
    assert np.isfinite(matrix).all()


def test_sample_params_can_focus_directly_on_rolling_levels() -> None:
    feature_cols = [
        "sr_roll_dist_prior_high_26b",
        "sr_vwap_session_gap",
        "sr_pivot_r1_gap",
        "sr_fib_0382_gap_52b",
    ]
    params = sample_params(np.random.default_rng(3), feature_cols, stage=0, config_index=1)
    assert params["focus_family"] == "rolling_levels"
    selected = [feature_cols[i] for i in params["feature_indices"]]
    assert selected == ["sr_roll_dist_prior_high_26b"]
