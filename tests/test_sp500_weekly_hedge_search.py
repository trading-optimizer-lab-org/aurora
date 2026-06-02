from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from aurora.research.sp500_weekly_hedge_search import (
    SP500WeeklyHedgeConfig,
    candidate_id_from_spec,
    choose_train_size,
    downside_hedge_score,
    evaluate_spec,
    generate_negative_sp500_years_report,
    generate_subperiod_report,
    hedge_train_score,
    merge_stage_rows,
    portfolio_metrics,
    run_stage,
    train_fail_reason,
)


def _dataset() -> dict[str, object]:
    idx = pd.date_range("2020-01-03", periods=80, freq="W-FRI")
    spy = np.resize(np.array([0.03, -0.04, 0.02, -0.03], dtype=float), len(idx))
    tlt = np.where(spy < 0.0, 0.025, 0.002)
    xle = np.where(spy < 0.0, -0.020, 0.020)
    asset_returns = pd.DataFrame({"SPY": spy, "TLT": tlt, "XLE": xle}, index=idx)
    features = pd.DataFrame(
        {
            "SPY__ret_1w": spy,
            "TLT__ret_1w": tlt,
            "XLE__ret_1w": xle,
            "macro__stress": np.where(spy < 0.0, 1.0, -1.0),
        },
        index=idx,
    )
    return {
        "train_x": features.iloc[:50],
        "valid_x": features.iloc[50:],
        "train_asset_returns": asset_returns.iloc[:50],
        "valid_asset_returns": asset_returns.iloc[50:],
        "train_spy_returns": asset_returns["SPY"].iloc[:50].to_numpy(dtype=float),
        "valid_spy_returns": asset_returns["SPY"].iloc[50:].to_numpy(dtype=float),
        "train_index": pd.DatetimeIndex(idx[:50]),
        "valid_index": pd.DatetimeIndex(idx[50:]),
        "feature_names": tuple(features.columns),
        "asset_symbols": ("SPY", "TLT", "XLE"),
    }


def test_score_prefers_strategy_that_gains_when_spy_falls_and_does_not_lose_when_spy_rises() -> None:
    idx = pd.date_range("2020-01-03", periods=8, freq="W-FRI")
    spy = np.array([0.03, -0.04, 0.02, -0.03, 0.01, -0.02, 0.02, -0.01])
    good = np.where(spy < 0.0, 0.02, 0.003)
    bad = np.where(spy < 0.0, -0.02, 0.010)
    assert hedge_train_score(portfolio_metrics(good, spy, idx, size=1.0)) > hedge_train_score(
        portfolio_metrics(bad, spy, idx, size=1.0)
    )


def test_downside_score_weights_large_spy_drops_more_than_small_drops() -> None:
    idx = pd.date_range("2008-01-04", periods=6, freq="W-FRI")
    spy = np.array([-0.01, -0.08, 0.02, 0.03, -0.02, -0.06])
    protects_crashes = np.array([-0.01, 0.05, 0.001, 0.001, -0.01, 0.04])
    protects_small_dips = np.array([0.05, -0.01, 0.001, 0.001, 0.04, -0.01])

    crash_metrics = portfolio_metrics(protects_crashes, spy, idx, size=1.0)
    small_metrics = portfolio_metrics(protects_small_dips, spy, idx, size=1.0)

    assert crash_metrics["down_weighted_mean_weekly"] > small_metrics["down_weighted_mean_weekly"]
    assert downside_hedge_score(crash_metrics) > downside_hedge_score(small_metrics)


def test_train_verification_fails_when_crash_weeks_are_bad_even_if_total_return_is_good() -> None:
    idx = pd.date_range("2008-01-04", periods=120, freq="W-FRI")
    spy = np.resize(np.array([-0.08, -0.04, -0.01, 0.02, 0.03]), len(idx))
    strategy = np.where(spy <= -0.04, -0.03, np.where(spy < 0.0, 0.10, 0.04))
    config = SP500WeeklyHedgeConfig(
        min_train_weeks=100,
        min_down_weeks=60,
        min_crash_weeks=20,
        min_crash_positive_pct=0.45,
    )
    metrics = portfolio_metrics(strategy, spy, idx, size=1.0)

    assert metrics["final_nav"] > 1.0
    assert train_fail_reason(metrics, config) == "train_not_positive_on_crash_weeks"


def test_late_entry_returns_do_not_fill_missing_asset_history_with_zero() -> None:
    idx = pd.date_range("2000-01-07", periods=12, freq="W-FRI")
    features = pd.DataFrame({"signal": np.ones(len(idx))}, index=idx)
    returns = pd.DataFrame({"LATE": [np.nan] * 5 + [0.01] * 7}, index=idx)
    spec = {
        "features": ("signal",),
        "signal_weights": (1.0,),
        "threshold": 0.0,
        "assets": ("LATE",),
        "asset_weights": (1.0,),
    }

    base, exposure = __import__(
        "aurora.research.sp500_weekly_hedge_search",
        fromlist=["returns_for_spec"],
    ).returns_for_spec(features, returns, spec)

    assert np.isnan(base[:5]).all()
    assert np.isfinite(base[5:]).all()
    assert np.isnan(exposure[:5]).all()


def test_subperiod_and_negative_sp500_year_reports_are_generated() -> None:
    idx = pd.date_range("1999-01-01", periods=220, freq="W-FRI")
    spy = np.resize(np.array([-0.03, 0.02, -0.02, 0.01]), len(idx))
    strategy = np.where(spy < 0.0, 0.01, 0.002)
    frame = pd.DataFrame(
        [
            {
                "candidate_id": "hedge",
                "period": "train",
                "strategy_returns_json": json.dumps(strategy.tolist()),
                "spy_returns_json": json.dumps(spy.tolist()),
                "returns_index_json": json.dumps([d.isoformat() for d in idx]),
            }
        ]
    )

    subperiods = generate_subperiod_report(frame)
    negative_years = generate_negative_sp500_years_report(frame)

    assert set(subperiods["subperiod"]).issuperset({"train_1999_2002", "train_2003_2006"})
    assert {"sp500_return", "strategy_return", "beats_sp500"}.issubset(negative_years.columns)


def test_size_is_chosen_only_from_train() -> None:
    idx = pd.date_range("2020-01-03", periods=8, freq="W-FRI")
    config = SP500WeeklyHedgeConfig(size_grid=(0.5, 1.0, 2.0, 5.0))
    train_base = np.full(len(idx), 0.01)
    valid_base = np.full(len(idx), -0.02)
    spy = np.full(len(idx), -0.01)
    size, train_metrics = choose_train_size(train_base, spy, idx, config)
    valid_metrics = portfolio_metrics(valid_base, spy, idx, size=size)
    assert size == 5.0
    assert train_metrics["final_nav"] > 1.0
    assert valid_metrics["final_nav"] < 1.0


def test_evaluate_spec_allows_short_asset_weights_and_keeps_validation_report_only() -> None:
    config = SP500WeeklyHedgeConfig(size_grid=(1.0,), top_rows_per_stage=5)
    spec = {
        "method": "dehb_real",
        "route": "weekly_hedge_linear",
        "features": ("macro__stress",),
        "signal_weights": (1.0,),
        "threshold": 0.0,
        "assets": ("XLE",),
        "asset_weights": (-1.0,),
        "iteration": 0,
        "stage": 0,
    }
    row = evaluate_spec(_dataset(), config, spec)
    assert row["method"] == "dehb_real"
    assert row["allows_short"] is True
    assert row["validation_used_for_selection"] is False
    assert row["locked_opened"] is False
    assert float(row["short_gross_weight"]) > 0.0
    assert "XLE:-1" in row["asset_weights"]


def test_run_stage_uses_dehb_real_only() -> None:
    config = SP500WeeklyHedgeConfig(top_rows_per_stage=10, size_grid=(1.0,), random_seed=7)
    rows, meta, audit = run_stage(
        config,
        stage=0,
        total_stages=3,
        time_budget_minutes=0.001,
        wave=2,
        total_waves=6,
        dataset=_dataset(),
    )
    assert rows
    assert {row["method"] for row in rows} == {"dehb_real"}
    assert {row["wave"] for row in rows} == {2}
    assert {row["total_waves"] for row in rows} == {6}
    assert meta["method"] == "dehb_real"
    assert meta["wave"] == 2
    assert meta["total_waves"] == 6
    assert audit["locked_opened"] is False


def test_manifest_filter_excludes_crypto_and_single_name_equities_but_keeps_etfs() -> None:
    module = __import__("aurora.research.sp500_weekly_hedge_search", fromlist=["_symbols_from_manifest"])
    manifest = yaml.safe_load(Path("config/diversified_seed_dataset.yaml").read_text(encoding="utf-8"))

    tradable, context, excluded = module._symbols_from_manifest(
        manifest,
        ("crypto_spot", "equity_single_name"),
    )
    tradable_symbols = {symbol for _, symbol in tradable}

    assert "BTCUSDT" not in tradable_symbols
    assert "AAPL" not in tradable_symbols
    assert "SPY" in tradable_symbols
    assert "TLT" in tradable_symbols
    assert "GLD" in tradable_symbols
    assert "EURUSD" in tradable_symbols
    assert any(item.startswith("crypto_spot/crypto_daily/") for item in excluded)
    assert any(item.startswith("equity_single_name/prices_daily/") for item in excluded)
    assert context


def test_wave_changes_seed_but_not_candidate_identity_contract() -> None:
    config = SP500WeeklyHedgeConfig(top_rows_per_stage=5, size_grid=(1.0,), random_seed=11)
    _, meta0, _ = run_stage(
        config,
        stage=0,
        total_stages=2,
        time_budget_minutes=0.001,
        wave=0,
        total_waves=6,
        dataset=_dataset(),
    )
    _, meta1, _ = run_stage(
        config,
        stage=0,
        total_stages=2,
        time_budget_minutes=0.001,
        wave=1,
        total_waves=6,
        dataset=_dataset(),
    )
    assert meta0["seed"] != meta1["seed"]
    spec = {
        "method": "dehb_real",
        "route": "weekly_hedge_linear",
        "features": ("macro__stress",),
        "signal_weights": (1.0,),
        "threshold": 0.0,
        "assets": ("TLT",),
        "asset_weights": (1.0,),
        "iteration": 0,
        "stage_bucket": 0,
        "engine": "dehb_real",
        "can_short": True,
    }
    assert candidate_id_from_spec(spec) == candidate_id_from_spec(dict(spec))
    rows, _, _ = run_stage(
        config,
        stage=0,
        total_stages=2,
        time_budget_minutes=0.001,
        wave=1,
        total_waves=6,
        dataset=_dataset(),
    )
    assert rows
    assert all("wave" not in json.loads(row["rule"]) for row in rows)


def test_merge_dedupes_by_candidate_id() -> None:
    a = pd.DataFrame([{"candidate_id": "x", "train_score": 1.0}, {"candidate_id": "y", "train_score": 2.0}])
    b = pd.DataFrame([{"candidate_id": "x", "train_score": 3.0}])
    merged = merge_stage_rows([a, b])
    assert len(merged) == 2
    assert float(merged.loc[merged["candidate_id"] == "x", "train_score"].iloc[0]) == 3.0


def test_workflow_shapes_for_1wave_and_6waves_are_comparable() -> None:
    one = Path(".github/workflows/sp500-weekly-hedge-dehb-policy1995-downside-1wave-80jobs-1h.yml")
    six = Path(".github/workflows/sp500-weekly-hedge-dehb-policy1995-downside-6waves-80jobs-1h.yml")
    one_data = yaml.safe_load(one.read_text(encoding="utf-8"))
    six_data = yaml.safe_load(six.read_text(encoding="utf-8"))
    assert one_data["env"]["EXPECTED_JOBS"] == "80"
    assert one_data["env"]["WAVES"] == "1"
    assert one_data["env"]["JOBS_PER_WAVE"] == "80"
    assert one_data["env"]["ASSUMED_EFFECTIVE_PARALLELISM"] == "180"
    assert one_data["env"]["TRAIN_START"] == "1995-01-01"
    assert one_data["env"]["LOCKED_START"] == "2021-01-01"
    assert one_data["jobs"]["wave_0"]["strategy"]["max-parallel"] == 500
    assert len(one_data["jobs"]["wave_0"]["strategy"]["matrix"]["stage"]) == 80
    assert six_data["env"]["EXPECTED_JOBS"] == "480"
    assert six_data["env"]["WAVES"] == "6"
    assert six_data["env"]["JOBS_PER_WAVE"] == "80"
    assert six_data["env"]["ASSUMED_EFFECTIVE_PARALLELISM"] == "180"
    assert six_data["env"]["TRAIN_START"] == "1995-01-01"
    assert six_data["env"]["LOCKED_START"] == "2021-01-01"
    for wave in range(6):
        job = six_data["jobs"][f"wave_{wave}"]
        assert job["strategy"]["max-parallel"] == 500
        assert len(job["strategy"]["matrix"]["stage"]) == 80
    for text in (one.read_text(encoding="utf-8"), six.read_text(encoding="utf-8")):
        assert '--start "$TRAIN_START" --end "$VALIDATION_END"' in text
        assert '--locked-start "$LOCKED_START"' in text
        assert "--allow-late-entry" in text
        assert "genetic" not in text
        assert "github_ml" not in text
        assert "beam" not in text
        assert "bandit" not in text


def test_policy1995_6waves_9h_workflow_shape() -> None:
    path = Path(".github/workflows/sp500-weekly-hedge-dehb-policy1995-downside-6waves-80jobs-9h.yml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    text = path.read_text(encoding="utf-8")

    assert data["name"] == "SP500 Weekly Hedge DEHB Policy1995 Downside 6 Waves 80 Jobs 9h"
    assert data["env"]["WAVES"] == "6"
    assert data["env"]["JOBS_PER_WAVE"] == "80"
    assert data["env"]["EXPECTED_JOBS"] == "480"
    assert data["env"]["ASSUMED_EFFECTIVE_PARALLELISM"] == "180"
    assert data["env"]["TRAIN_START"] == "1995-01-01"
    assert data["env"]["LOCKED_START"] == "2021-01-01"
    assert data["jobs"]["wave_0"]["strategy"]["max-parallel"] == 500
    assert data["jobs"]["wave_0"]["timeout-minutes"] == 115
    assert data["jobs"]["merge"]["timeout-minutes"] == 120
    assert len(data["jobs"]["wave_0"]["strategy"]["matrix"]["stage"]) == 80
    assert 'default: "85"' in text
    assert 'test "${{ inputs.minutes_per_stage || \'85\' }}" = "85"' in text
    assert "sp500-weekly-hedge-dehb-policy1995-downside-6waves-80jobs-9h-results" in text
    assert "sp500_weekly_hedge_dehb_policy1995_downside_6waves_80jobs_9h" in text
    assert "genetic" not in text
    assert "github_ml" not in text
    assert "beam" not in text
    assert "bandit" not in text


def test_no_crypto_no_stocks_6waves_3h_workflow_shape() -> None:
    path = Path(".github/workflows/sp500-weekly-hedge-dehb-no-crypto-no-stocks-6waves-80jobs-3h.yml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    text = path.read_text(encoding="utf-8")

    assert data["name"] == "SP500 Weekly Hedge DEHB No Crypto No Stocks 6 Waves 80 Jobs 3h"
    assert data["env"]["WAVES"] == "6"
    assert data["env"]["JOBS_PER_WAVE"] == "80"
    assert data["env"]["EXPECTED_JOBS"] == "480"
    assert data["env"]["ASSUMED_EFFECTIVE_PARALLELISM"] == "180"
    assert data["env"]["FILE_PREFIX"] == "sp500_weekly_hedge_dehb_no_crypto_no_stocks_6waves_80jobs_3h"
    assert data["jobs"]["wave_0"]["strategy"]["max-parallel"] == 500
    assert data["jobs"]["wave_0"]["timeout-minutes"] == 45
    assert data["jobs"]["merge"]["timeout-minutes"] == 120
    assert len(data["jobs"]["wave_0"]["strategy"]["matrix"]["stage"]) == 80
    assert 'default: "30"' in text
    assert 'test "${{ inputs.minutes_per_stage || \'30\' }}" = "30"' in text
    assert "--exclude-asset-group crypto_spot" in text
    assert "--exclude-asset-group equity_single_name" in text
    assert "sp500-weekly-hedge-dehb-no-crypto-no-stocks-6waves-80jobs-3h-results" in text
    assert "genetic" not in text
    assert "github_ml" not in text
    assert "beam" not in text
    assert "bandit" not in text


def test_no_crypto_no_stocks_2waves_500jobs_180parallel_workflow_shape() -> None:
    path = Path(".github/workflows/sp500-weekly-hedge-dehb-no-crypto-no-stocks-2waves-500jobs-180parallel-1h.yml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    text = path.read_text(encoding="utf-8")

    assert data["name"] == "SP500 Weekly Hedge DEHB No Crypto No Stocks 2 Waves 500 Jobs 180 Parallel 1h"
    assert data["env"]["WAVES"] == "2"
    assert data["env"]["JOBS_PER_WAVE"] == "500"
    assert data["env"]["EXPECTED_JOBS"] == "1000"
    assert data["env"]["ASSUMED_EFFECTIVE_PARALLELISM"] == "180"
    assert data["env"]["TRAIN_START"] == "1995-01-01"
    assert data["env"]["LOCKED_START"] == "2021-01-01"
    assert data["env"]["FILE_PREFIX"] == "sp500_weekly_hedge_dehb_no_crypto_no_stocks_2waves_500jobs_180parallel_1h"
    assert data["jobs"]["wave_0_a"]["strategy"]["max-parallel"] == 90
    assert data["jobs"]["wave_0_b"]["strategy"]["max-parallel"] == 90
    assert data["jobs"]["wave_1_a"]["strategy"]["max-parallel"] == 90
    assert data["jobs"]["wave_1_b"]["strategy"]["max-parallel"] == 90
    assert len(data["jobs"]["wave_0_a"]["strategy"]["matrix"]["stage"]) == 250
    assert len(data["jobs"]["wave_0_b"]["strategy"]["matrix"]["stage"]) == 250
    assert len(data["jobs"]["wave_1_a"]["strategy"]["matrix"]["stage"]) == 250
    assert len(data["jobs"]["wave_1_b"]["strategy"]["matrix"]["stage"]) == 250
    assert data["jobs"]["merge"]["timeout-minutes"] == 120
    assert 'default: "10"' in text
    assert 'default: "180"' in text
    assert 'python scripts/download_diversified_seed.py --start "$TRAIN_START" --end "$VALIDATION_END"' in text
    assert "--total-stages 500" in text
    assert "--max-parallel-requested 180" in text
    assert "--exclude-asset-group crypto_spot" in text
    assert "--exclude-asset-group equity_single_name" in text
    assert "sp500-weekly-hedge-dehb-no-crypto-no-stocks-2waves-500jobs-180parallel-1h-results" in text
    assert "genetic" not in text
    assert "github_ml" not in text
    assert "beam" not in text
    assert "bandit" not in text


def test_spy_momentum_trend_stage_filter_forces_spy_only_and_rejects_forbidden_features() -> None:
    module = __import__(
        "scripts.run_sp500_weekly_hedge_momentum_trend_stage",
        fromlist=["_synthetic_dataset", "_spy_momentum_trend_dataset"],
    )

    filtered, audit = module._spy_momentum_trend_dataset(module._synthetic_dataset(), {"locked_opened": False})

    assert filtered["asset_symbols"] == ("SPY",)
    assert list(filtered["train_asset_returns"].columns) == ["SPY"]
    assert "SPY__ret_1w" in filtered["feature_names"]
    assert "SPY__ma_gap_10w" in filtered["feature_names"]
    assert "QQQ__ret_13w" in filtered["feature_names"]
    assert "macro__VIXCLS__chg_4w" in filtered["feature_names"]
    assert "macro__UNRATE__level" not in filtered["feature_names"]
    assert "BTCUSDT__ret_1w" not in filtered["feature_names"]
    assert audit["spy_only"] is True
    assert audit["crypto_used"] is False
    assert audit["feature_filter"] == "momentum_trend_only"


def test_spy_momentum_trend_stage_filter_requires_feature_history_since_1995() -> None:
    module = __import__(
        "scripts.run_sp500_weekly_hedge_momentum_trend_stage",
        fromlist=["_spy_momentum_trend_dataset"],
    )
    idx = pd.date_range("1995-01-06", "1997-12-26", freq="W-FRI")
    train_x = pd.DataFrame(
        {
            "SPY__ret_1w": np.linspace(-0.02, 0.02, len(idx)),
            "TLT__ret_26w": np.nan,
        },
        index=idx,
    )
    train_x.loc[train_x.index.year >= 1997, "TLT__ret_26w"] = 0.01
    train_x.attrs["availability_mask"] = train_x.notna()
    valid_idx = pd.date_range("2011-01-07", periods=12, freq="W-FRI")
    valid_x = pd.DataFrame(
        {
            "SPY__ret_1w": 0.01,
            "TLT__ret_26w": 0.01,
        },
        index=valid_idx,
    )
    valid_x.attrs["availability_mask"] = valid_x.notna()
    dataset = {
        "train_x": train_x,
        "valid_x": valid_x,
        "train_asset_returns": pd.DataFrame({"SPY": 0.001}, index=idx),
        "valid_asset_returns": pd.DataFrame({"SPY": 0.001}, index=valid_idx),
        "train_spy_returns": np.full(len(idx), 0.001),
        "valid_spy_returns": np.full(len(valid_idx), 0.001),
        "train_index": pd.DatetimeIndex(idx),
        "valid_index": pd.DatetimeIndex(valid_idx),
        "feature_names": tuple(train_x.columns),
        "asset_symbols": ("SPY",),
    }

    filtered, audit = module._spy_momentum_trend_dataset(
        dataset,
        {"locked_opened": False},
        require_feature_data_from_year=1995,
        min_feature_weeks_per_year=26,
    )

    assert filtered["feature_names"] == ("SPY__ret_1w",)
    assert "TLT__ret_26w" in audit["feature_columns_rejected_history_names"]
    assert audit["feature_columns_rejected_history_count"] == 1


def test_spy_dehb_real_500_parallel_1h_momentum_trend_workflow_shape() -> None:
    path = Path(".github/workflows/weekly-spy-dehb-real-500-parallel-1h-momentum-trend.yml")
    merge_path = Path(".github/workflows/weekly-spy-dehb-real-500-parallel-1h-momentum-trend-merge-now.yml")
    stop_path = Path(".github/workflows/weekly-spy-dehb-real-500-parallel-1h-momentum-trend-stop.yml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    merge = yaml.safe_load(merge_path.read_text(encoding="utf-8"))
    stop = yaml.safe_load(stop_path.read_text(encoding="utf-8"))
    text = path.read_text(encoding="utf-8")
    merge_text = merge_path.read_text(encoding="utf-8")

    assert data["name"] == "Weekly SPY DEHB Real 500 Parallel 1h Momentum Trend"
    assert "push" not in data.get(True, {})
    assert data["jobs"]["search_a"]["strategy"]["max-parallel"] == 250
    assert data["jobs"]["search_b"]["strategy"]["max-parallel"] == 250
    assert data["jobs"]["search_a"]["timeout-minutes"] == 60
    assert data["jobs"]["search_b"]["timeout-minutes"] == 60
    assert data["jobs"]["watchdog"]["timeout-minutes"] == 70
    assert 'default: "50"' in text
    assert 'default: "500"' in text
    assert "--total-stages 500" in text
    assert "--require-feature-data-from-year \"$FEATURE_HISTORY_START_YEAR\"" in text
    assert "--min-feature-weeks-per-year \"$MIN_FEATURE_WEEKS_PER_YEAR\"" in text
    assert data["env"]["FEATURE_HISTORY_START_YEAR"] == "1995"
    assert data["env"]["MIN_FEATURE_WEEKS_PER_YEAR"] == "26"
    assert "scripts/run_sp500_weekly_hedge_momentum_trend_stage.py" in text
    assert "sleep 3600" in text
    assert "gh run cancel" in text
    assert "genetic" not in text
    assert "github_ml" not in text
    assert "beam" not in text
    assert "bandit" not in text
    assert merge["name"] == "Weekly SPY DEHB Real 500 Parallel 1h Momentum Trend Merge Now"
    assert "--allow-partial" in merge_text
    assert "--require-spy-only" in merge_text
    assert "--require-momentum-trend-only" in merge_text
    assert stop["name"] == "Weekly SPY DEHB Real 500 Parallel 1h Momentum Trend Stop"


def test_merge_guard_allows_partial_only_when_explicit_for_spy_momentum_trend() -> None:
    guard = __import__("scripts.merge_sp500_weekly_hedge_dehb", fromlist=["_fail_if_invalid_summary"])._fail_if_invalid_summary
    summary = {
        "stage_files_found": 120,
        "expected_jobs": 500,
        "partial": True,
        "rows": 10,
        "locked_opened": False,
        "excluded_asset_groups": ["crypto_spot", "equity_single_name"],
        "crypto_used": False,
        "single_name_equities_used": False,
    }
    audit = {
        "locked_opened": False,
        "spy_only": True,
        "feature_filter": "momentum_trend_only",
        "feature_columns_used_names": ["SPY__ret_1w"],
        "forbidden_features_found": ["BTCUSDT__ret_1w"],
    }

    with pytest.raises(SystemExit):
        guard(summary, audit)
    guard(summary, audit, allow_partial=True, require_spy_only=True, require_momentum_trend_only=True)


def test_merge_guard_rejects_empty_partial_or_unconfirmed_runs() -> None:
    guard = __import__("scripts.merge_sp500_weekly_hedge_dehb", fromlist=["_fail_if_invalid_summary"])._fail_if_invalid_summary
    good = {
        "stage_files_found": 1000,
        "expected_jobs": 1000,
        "partial": False,
        "rows": 10,
        "locked_opened": False,
        "excluded_asset_groups": ["crypto_spot", "equity_single_name"],
        "crypto_used": False,
        "single_name_equities_used": False,
    }

    guard(good, {"locked_opened": False})
    for bad in (
        {**good, "stage_files_found": 0},
        {**good, "partial": True},
        {**good, "rows": 0},
        {**good, "locked_opened": True},
        {**good, "crypto_used": None},
        {**good, "single_name_equities_used": None},
    ):
        with pytest.raises(SystemExit):
            guard(bad, {"locked_opened": False})


def test_policy1995_autostart_9h_workflow_filters_current_run_and_success_only() -> None:
    path = Path(".github/workflows/sp500-weekly-hedge-policy1995-autostart-9h.yml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    text = path.read_text(encoding="utf-8")

    assert data["name"] == "SP500 Weekly Hedge Policy1995 Autostart 9h"
    assert "SP500 Weekly Hedge DEHB Policy1995 Downside 6 Waves 80 Jobs 1h" in text
    assert "github.event.workflow_run.id == 26721369552" in text
    assert "github.event.workflow_run.conclusion == 'success'" in text
    assert "github.event.workflow_run.head_branch == 'codex/universal-robustness'" in text
    assert "sp500-weekly-hedge-dehb-policy1995-downside-6waves-80jobs-9h.yml" in text
    assert "minutes_per_stage=85" in text
    assert "max_parallel_requested=500" in text
    assert "status=in_progress" in text
    assert "status=queued" in text


def test_policy1995_data_download_does_not_request_pre_binance_crypto_months() -> None:
    from scripts.download_diversified_seed import binance_effective_start

    assert binance_effective_start("BTCUSDT", "1995-01-01") == "2017-08-01"
    assert binance_effective_start("SOLUSDT", "1995-01-01") == "2020-08-01"
    assert binance_effective_start("BTCUSDT", "2019-01-01") == "2019-01-01"


def test_policy1995_yfinance_download_uses_runtime_start(monkeypatch) -> None:
    import scripts.download_diversified_seed as downloader

    calls = []

    def fake_download(symbol, *, start, end, progress, auto_adjust, threads):
        calls.append((symbol, start, end, progress, auto_adjust, threads))
        idx = pd.date_range(start, periods=2, freq="D")
        return pd.DataFrame(
            {
                "Open": [1.0, 1.1],
                "High": [1.1, 1.2],
                "Low": [0.9, 1.0],
                "Close": [1.0, 1.1],
                "Adj Close": [1.0, 1.1],
                "Volume": [100, 120],
            },
            index=idx,
        )

    monkeypatch.setattr(downloader.yf, "download", fake_download)
    monkeypatch.setattr(downloader, "START", "1995-01-01")
    monkeypatch.setattr(downloader, "END", "2020-12-31")

    frame = downloader.fetch_yfinance("SPY")

    assert calls[0][1] == "1995-01-01"
    assert calls[0][2] == "2020-12-31"
    assert not frame.empty


def test_stage_script_smoke_with_synthetic_dataset(tmp_path: Path) -> None:
    out = tmp_path / "out"
    cmd = [
        sys.executable,
        "scripts/run_sp500_weekly_hedge_dehb_stage.py",
        "--synthetic-smoke",
        "--wave",
        "1",
        "--total-waves",
        "2",
        "--stage",
        "0",
        "--total-stages",
        "2",
        "--time-budget-minutes",
        "0.001",
        "--output-dir",
        str(out),
        "--top-rows-per-stage",
        "5",
        "--exclude-asset-group",
        "crypto_spot",
        "--exclude-asset-group",
        "equity_single_name",
    ]
    completed = subprocess.run(cmd, check=True, capture_output=True, text=True)
    meta = json.loads(completed.stdout)
    assert meta["wave"] == 1
    assert meta["total_waves"] == 2
    assert meta["locked_opened"] is False
    assert meta["validation_used_for_selection"] is False
    assert meta["excluded_asset_groups"] == ["crypto_spot", "equity_single_name"]
    assert list(out.glob("*_wave_1_stage_0.csv"))
