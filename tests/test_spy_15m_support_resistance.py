from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from scripts.run_spy_15m_support_resistance import (
    build_feature_frame,
    feature_families,
    filter_regular_session,
    normalise_yfinance_ohlcv,
    prepare_matrix,
    run_retest_shard,
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


def test_spy_15m_2015_retest_workflow_uses_polygon_and_source_artifact() -> None:
    path = Path(".github/workflows/spy-15m-support-resistance-2015-retest.yml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    text = path.read_text(encoding="utf-8")
    assert data["name"] == "SPY 15m Support Resistance 2015 Retest"
    assert "workflow_dispatch" in data[True]
    assert data[True]["workflow_dispatch"]["inputs"]["start_date"]["default"] == "2015-01-01"
    assert data[True]["workflow_dispatch"]["inputs"]["source_run_id"]["default"] == "27494610826"
    assert "preflight" in data["jobs"]
    assert data["jobs"]["source"]["needs"] == ["preflight"]
    assert data["jobs"]["data"]["needs"] == ["preflight"]
    assert "needs.data.result == 'success'" in str(data["jobs"]["merge"]["if"])
    assert "POLYGON_API_KEY: ${{ secrets.POLYGON_API_KEY }}" in text
    assert "yfinance cannot cover this range" in text
    assert 'find "$OUTPUT_DIR/source" -path "*/final/accepted.csv"' in text
    assert "--data-source polygon" in text
    assert "--mode retest-shard" in text
    assert "range(355)" in text
    assert "spy-15m-support-resistance-2015-retest-results" in text


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


def test_normalise_yfinance_price_ticker_multiindex() -> None:
    idx = pd.date_range("2026-01-02 09:30", periods=3, freq="15min")
    columns = pd.MultiIndex.from_product([["Open", "High", "Low", "Close", "Volume"], ["SPY"]])
    raw = pd.DataFrame(
        [
            [100.0, 101.0, 99.0, 100.5, 1_000_000],
            [100.5, 102.0, 100.0, 101.5, 1_100_000],
            [101.5, 103.0, 101.0, 102.5, 1_200_000],
        ],
        index=idx,
        columns=columns,
    )
    out = normalise_yfinance_ohlcv(raw)
    assert list(out.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert out.loc[idx[0], "Close"] == 100.5
    assert out.loc[idx[-1], "Volume"] == 1_200_000


def test_filter_regular_session_keeps_only_us_cash_bars() -> None:
    idx = pd.DatetimeIndex(
        [
            "2026-01-02 08:00",
            "2026-01-02 09:30",
            "2026-01-02 15:45",
            "2026-01-02 16:00",
            "2026-01-03 09:30",
        ]
    )
    bars = pd.DataFrame(
        {"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": 1.0},
        index=idx,
    )
    out = filter_regular_session(bars)
    assert list(out.index) == [idx[1], idx[2]]


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


def test_run_retest_shard_revalidates_source_candidates(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True)
    panel = build_feature_frame(make_spy_15m_bars(days=55), target_bars=4)
    panel.to_csv(data_dir / "spy_15m_sr_feature_panel.csv", index_label="timestamp")
    (data_dir / "feature_audit.json").write_text(
        '{"target_bars": 4, "data_source": "polygon", "start_date_requested": "2015-01-01"}',
        encoding="utf-8",
    )
    feature_cols = [c for c in panel.columns if c not in {"target_return", "target_direction"}]
    params = sample_params(np.random.default_rng(3), feature_cols, stage=0, config_index=1)
    source_dir = output_dir / "source" / "final"
    source_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "strategy_id": "sr15m_source_000001",
                "score": 3.0,
                "train_sharpe": 2.0,
                "validation_sharpe": 2.5,
                "validation_trades": 7,
                "focus_family": params["focus_family"],
                "params_json": __import__("json").dumps(params),
            }
        ]
    ).to_csv(source_dir / "accepted.csv", index=False)

    run_retest_shard(
        output_dir,
        stage=0,
        source_candidates=source_dir / "accepted.csv",
        candidates_per_stage=100,
        top_per_stage=100,
        target_sharpe=1.5,
        cost_bps=1.0,
        validation_fraction=0.30,
    )

    out = pd.read_csv(output_dir / "shards" / "stage_000" / "top_candidates.csv")
    assert list(out["strategy_id"]) == ["sr15m_source_000001"]
    assert "source_validation_sharpe" in out.columns
    assert "validation_sharpe" in out.columns
