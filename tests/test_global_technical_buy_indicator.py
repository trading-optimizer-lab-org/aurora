from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from scripts import global_technical_buy_indicator as gtbi


def _breakout_frame(rows: int = 90) -> pd.DataFrame:
    idx = pd.date_range("2009-11-02", periods=rows, freq="B")
    close = np.full(rows, 100.0)
    close[60:] = np.linspace(112.0, 132.0, rows - 60)
    open_ = np.r_[close[0], close[:-1] * 1.002]
    high = np.maximum(open_, close) * 1.01
    low = np.minimum(open_, close) * 0.99
    volume = np.full(rows, 100_000.0)
    volume[60:] = 260_000.0
    return pd.DataFrame(
        {
            "date": idx,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "adj_close": close,
            "volume": volume,
            "symbol": "AAA",
        }
    )


def _spy_frame(rows: int = 90) -> pd.DataFrame:
    idx = pd.date_range("2009-11-02", periods=rows, freq="B")
    close = np.linspace(100.0, 110.0, rows)
    return pd.DataFrame(
        {
            "date": idx,
            "open": close,
            "high": close * 1.002,
            "low": close * 0.998,
            "close": close,
            "adj_close": close,
            "volume": np.full(rows, 1_000_000.0),
            "symbol": "SPY",
        }
    )


def test_entry_signal_is_minervini_style_and_has_no_lookahead() -> None:
    frame = _breakout_frame()
    spy = _spy_frame()
    config = gtbi.IndicatorConfig(
        family="minervini_sepa",
        minervini_trend=False,
        require_rs=False,
        require_base_tight=True,
        require_breakout=True,
        require_pocket_pivot=False,
        breakout_lookback=20,
        base_lookback=20,
        max_base_range_pct=0.20,
        volume_lookback=20,
        volume_multiple=1.5,
        rsi_max=100.0,
    )

    signal = gtbi.entry_signal(frame, spy, config)

    assert bool(signal.iloc[60]) is True
    shuffled = frame.copy()
    shuffled.loc[shuffled.index > 60, "close"] = shuffled.loc[shuffled.index > 60, "close"].iloc[::-1].to_numpy()
    shuffled_signal = gtbi.entry_signal(shuffled, spy, config)
    pd.testing.assert_series_equal(signal.iloc[:61], shuffled_signal.iloc[:61])


def test_tradingview_minervini_family_set_samples_only_requested_families() -> None:
    rng = np.random.default_rng(7)

    configs = [gtbi.sample_config(rng, search_method="dehb_real", family_set="tradingview_minervini") for _ in range(40)]

    assert {cfg.family for cfg in configs}
    assert {cfg.family for cfg in configs} <= set(gtbi.TRADINGVIEW_MINERVINI_FAMILIES)


def test_tradingview_pocket_pivot_signal_uses_minervini_and_volume_breakout() -> None:
    rows = 260
    idx = pd.date_range("2010-01-04", periods=rows, freq="B")
    close = np.linspace(50.0, 100.0, rows)
    open_ = close * 0.995
    high = close * 1.01
    low = close * 0.99
    volume = np.full(rows, 100_000.0)
    close[-1] = open_[-1] * 1.04
    high[-1] = close[-1] * 1.01
    volume[-1] = 600_000.0
    frame = pd.DataFrame(
        {
            "date": idx,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "adj_close": close,
            "volume": volume,
            "symbol": "AAA",
        }
    )
    spy = _spy_frame(rows)
    spy["date"] = idx
    config = gtbi.IndicatorConfig(
        family="tv_pocket_pivot_breakout",
        require_rs=False,
        near_high_pct=0.70,
        above_low_multiple=1.05,
        rsi_max=100.0,
    )

    signal = gtbi.entry_signal(frame, spy, config)

    assert bool(signal.iloc[-1]) is True


def test_market_trend_filter_blocks_buys_when_spy_regime_is_down() -> None:
    frame = _breakout_frame(260)
    frame["date"] = pd.date_range("2010-01-04", periods=len(frame), freq="B")
    spy = _spy_frame(260)
    spy["date"] = frame["date"]
    spy["close"] = np.linspace(120.0, 80.0, len(spy))
    spy["open"] = spy["close"]
    spy["high"] = spy["close"] * 1.002
    spy["low"] = spy["close"] * 0.998
    config = gtbi.IndicatorConfig(
        family="minervini_sepa",
        minervini_trend=False,
        require_rs=False,
        require_base_tight=False,
        require_breakout=False,
        require_market_trend=True,
        market_ma_days=50,
        market_momentum_days=21,
        rsi_max=100.0,
    )

    signal = gtbi.entry_signal(frame, spy, config)

    assert not bool(signal.iloc[-1])


def test_simulate_trades_uses_next_session_open_and_stop_loss() -> None:
    idx = pd.date_range("2011-01-03", periods=8, freq="B")
    frame = pd.DataFrame(
        {
            "date": idx,
            "open": [100.0, 110.0, 104.0, 99.0, 98.0, 98.0, 98.0, 98.0],
            "high": [101.0, 112.0, 105.0, 100.0, 99.0, 99.0, 99.0, 99.0],
            "low": [99.0, 109.0, 95.0, 97.0, 97.0, 97.0, 97.0, 97.0],
            "close": [100.0, 111.0, 96.0, 98.0, 98.0, 98.0, 98.0, 98.0],
            "adj_close": [100.0, 111.0, 96.0, 98.0, 98.0, 98.0, 98.0, 98.0],
            "volume": [1000.0] * 8,
            "symbol": "AAA",
        }
    )
    signal = pd.Series([True, False, False, False, False, False, False, False], index=idx)
    config = gtbi.IndicatorConfig(stop_loss_pct=0.08, trailing_stop_pct=0.50, max_holding_days=20)

    trades = gtbi.simulate_trades("AAA", frame, signal, config, split="validation")

    assert len(trades) == 1
    trade = trades.iloc[0]
    assert trade["entry_date"] == "2011-01-04"
    assert trade["entry_price"] == pytest.approx(110.0)
    assert trade["exit_reason"] == "stop_loss"
    assert trade["return_pct"] == pytest.approx((99.0 / 110.0 - 1.0) * 100.0)


def test_simulate_trades_exits_on_ma_and_max_holding() -> None:
    idx = pd.date_range("2011-01-03", periods=35, freq="B")
    close = np.r_[np.linspace(100.0, 120.0, 15), np.linspace(119.0, 92.0, 20)]
    frame = pd.DataFrame(
        {
            "date": idx,
            "open": np.r_[close[0], close[:-1]],
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "adj_close": close,
            "volume": np.full(len(idx), 1000.0),
            "symbol": "AAA",
        }
    )
    signal = pd.Series([True] + [False] * (len(idx) - 1), index=idx)
    config = gtbi.IndicatorConfig(
        stop_loss_pct=0.50,
        trailing_stop_pct=0.50,
        max_holding_days=10,
        exit_ma_days=5,
        use_exit_ma=True,
    )

    trades = gtbi.simulate_trades("AAA", frame, signal, config, split="validation")

    assert len(trades) == 1
    assert trades.iloc[0]["exit_reason"] in {"exit_ma", "max_holding"}
    assert trades.iloc[0]["holding_days"] <= 10


def test_simulate_trades_exits_on_market_regime_next_session() -> None:
    idx = pd.date_range("2011-01-03", periods=8, freq="B")
    frame = pd.DataFrame(
        {
            "date": idx,
            "open": [100.0, 101.0, 102.0, 99.0, 98.0, 98.0, 98.0, 98.0],
            "high": [101.0, 103.0, 104.0, 100.0, 99.0, 99.0, 99.0, 99.0],
            "low": [99.0, 100.0, 101.0, 98.0, 97.0, 97.0, 97.0, 97.0],
            "close": [100.0, 102.0, 103.0, 99.0, 98.0, 98.0, 98.0, 98.0],
            "adj_close": [100.0, 102.0, 103.0, 99.0, 98.0, 98.0, 98.0, 98.0],
            "volume": [1000.0] * 8,
            "symbol": "AAA",
        }
    )
    signal = pd.Series([True, False, False, False, False, False, False, False], index=idx)
    exit_signal = pd.Series([False, False, True, False, False, False, False, False], index=idx)
    config = gtbi.IndicatorConfig(stop_loss_pct=0.50, trailing_stop_pct=0.50, max_holding_days=20, use_market_exit=True)

    trades = gtbi.simulate_trades("AAA", frame, signal, config, split="validation", exit_signal=exit_signal)

    assert len(trades) == 1
    assert trades.iloc[0]["exit_reason"] == "market_exit"
    assert trades.iloc[0]["exit_date"] == "2011-01-06"
    assert trades.iloc[0]["exit_price"] == pytest.approx(99.0)


def test_yearly_trade_performance_groups_closed_trades_and_adds_spy_return() -> None:
    trades = pd.DataFrame(
        [
            {"candidate_id": "c1", "split": "train", "exit_date": "2010-01-10", "return_pct": 10.0, "holding_days": 5},
            {"candidate_id": "c1", "split": "train", "exit_date": "2010-06-10", "return_pct": -5.0, "holding_days": 7},
            {"candidate_id": "c1", "split": "validation", "exit_date": "2011-03-10", "return_pct": 4.0, "holding_days": 9},
        ]
    )
    spy = pd.DataFrame(
        {
            "date": pd.to_datetime(["2010-01-01", "2010-12-31", "2011-01-03", "2011-12-30"]),
            "close": [100.0, 120.0, 120.0, 108.0],
        }
    )

    yearly = gtbi.yearly_trade_performance(trades, spy)

    row_2010 = yearly[(yearly["split"] == "train") & (yearly["year"] == 2010)].iloc[0]
    assert row_2010["trades"] == 2
    assert row_2010["avg_trade_return_pct"] == pytest.approx(2.5)
    assert row_2010["median_trade_return_pct"] == pytest.approx(2.5)
    assert row_2010["win_rate"] == pytest.approx(0.5)
    assert row_2010["spy_return_pct"] == pytest.approx(20.0)


def test_merge_stage_outputs_is_deterministic(tmp_path: Path) -> None:
    stage_a = tmp_path / "stage-a"
    stage_b = tmp_path / "stage-b"
    stage_a.mkdir()
    stage_b.mkdir()
    pd.DataFrame(
        [
            {"candidate_id": "b", "family": "oneil_canslim", "score": 1.0, "train_trades": 4},
            {"candidate_id": "a", "family": "minervini_sepa", "score": 2.0, "train_trades": 5},
        ]
    ).to_csv(stage_a / "leaderboard.csv", index=False)
    pd.DataFrame(
        [{"candidate_id": "c", "family": "quallamaggie", "score": 1.5, "train_trades": 6}]
    ).to_csv(stage_b / "leaderboard.csv", index=False)
    (stage_a / "top_indicator_rules.jsonl").write_text(json.dumps({"candidate_id": "b"}) + "\n", encoding="utf-8")
    (stage_b / "top_indicator_rules.jsonl").write_text(json.dumps({"candidate_id": "c"}) + "\n", encoding="utf-8")

    out = tmp_path / "merged"
    summary = gtbi.merge_stage_outputs([stage_a, stage_b], out, top_n=2)

    merged = pd.read_csv(out / "leaderboard.csv")
    assert summary["candidates"] == 3
    assert merged["candidate_id"].tolist() == ["a", "c"]
    assert (out / "summary.json").exists()
    assert (out / "family_summary.csv").exists()
    assert (out / "top_indicator_rules.jsonl").exists()


def _quality_yearly(candidate_id: str = "ok", *, bad_train: bool = False) -> pd.DataFrame:
    rows = []
    for year in range(2011, 2021):
        rows.append(
            {
                "candidate_id": candidate_id,
                "split": "validation",
                "year": year,
                "trades": 160,
                "avg_trade_return_pct": 0.30,
                "median_trade_return_pct": 0.12,
                "win_rate": 0.56,
                "profit_factor": 1.35,
                "avg_holding_days": 6.0,
                "spy_return_pct": 8.0,
            }
        )
    for year in range(2003, 2011):
        rows.append(
            {
                "candidate_id": candidate_id,
                "split": "train",
                "year": year,
                "trades": 120,
                "avg_trade_return_pct": -0.10 if bad_train and year == 2008 else 0.20,
                "median_trade_return_pct": 0.08,
                "win_rate": 0.54,
                "profit_factor": 0.95 if bad_train and year == 2008 else 1.20,
                "avg_holding_days": 6.0,
                "spy_return_pct": 7.0,
            }
        )
    return pd.DataFrame(rows, columns=gtbi.YEARLY_COLUMNS)


def test_strict_quality_filter_accepts_only_full_stability() -> None:
    row = {
        "validation_avg_trade_return_pct": 0.30,
        "validation_median_trade_return_pct": 0.12,
        "validation_profit_factor": 1.60,
        "validation_trades_per_year": 160.0,
        "validation_avg_holding_days": 6.0,
        "validation_max_drawdown_pct": -12.0,
    }

    metrics = gtbi._strict_quality_metrics(
        row=row,
        yearly=_quality_yearly(),
        validation_start="2011-01-01",
        validation_end="2020-12-31",
    )
    bad = gtbi._strict_quality_metrics(
        row=row,
        yearly=_quality_yearly(bad_train=True),
        validation_start="2011-01-01",
        validation_end="2020-12-31",
    )

    assert metrics["strict_quality_pass"] is True
    assert metrics["validation_positive_years"] == 10
    assert metrics["train_2003_2010_positive_years"] == 8
    assert metrics["adjusted_return_time_risk"] == pytest.approx(0.30 / (6.0 * 12.0))
    assert bad["strict_quality_pass"] is False
    assert "train_2003_2010_avg_return_negative" in bad["strict_quality_failures"]


def test_frequency_quality_score_keeps_high_frequency_near_misses_auditable() -> None:
    rare = {
        "strict_quality_pass": False,
        "strict_quality_failure_count": 2,
        "validation_min_yearly_trades": 15,
        "validation_trades_per_year": 30.0,
        "validation_positive_years": 10,
        "validation_median_positive_years": 8,
        "train_2003_2010_positive_years": 8,
        "validation_profit_factor": 2.0,
        "validation_min_yearly_profit_factor": 1.2,
        "train_2003_2010_min_profit_factor": 1.1,
        "validation_median_trade_return_pct": 1.1,
        "validation_avg_trade_return_pct": 2.5,
        "validation_max_profit_contribution_share": 0.20,
    }
    frequent = {
        **rare,
        "strict_quality_failure_count": 4,
        "validation_min_yearly_trades": 120,
        "validation_trades_per_year": 180.0,
        "validation_profit_factor": 1.45,
        "validation_min_yearly_profit_factor": 1.08,
        "validation_median_trade_return_pct": 0.20,
        "validation_avg_trade_return_pct": 0.35,
    }

    assert gtbi._frequency_quality_score(frequent) > gtbi._frequency_quality_score(rare)


def test_merge_stage_outputs_writes_filtered_leaderboard(tmp_path: Path) -> None:
    stage = tmp_path / "stage"
    stage.mkdir()
    pd.DataFrame(
        [
            {
                "candidate_id": "pass",
                "family": "tv_5ma_oneil_minervini",
                "score": 1_000_010.0,
                "strict_quality_pass": True,
                "adjusted_return_time_risk": 0.004,
                "validation_median_trade_return_pct": 0.20,
                "validation_median_positive_years": 9,
                "validation_max_profit_contribution_share": 0.15,
                "validation_max_drawdown_pct": -8.0,
                "validation_trades_per_year": 220.0,
            },
            {
                "candidate_id": "fail",
                "family": "tv_breakout_finder",
                "score": -1.0,
                "strict_quality_pass": False,
                "adjusted_return_time_risk": 0.010,
                "validation_median_trade_return_pct": 0.40,
                "validation_median_positive_years": 6,
                "validation_max_profit_contribution_share": 0.40,
                "validation_max_drawdown_pct": -20.0,
                "validation_trades_per_year": 80.0,
            },
        ]
    ).to_csv(stage / "leaderboard.csv", index=False)

    out = tmp_path / "merged"
    summary = gtbi.merge_stage_outputs([stage], out, top_n=10)

    filtered = pd.read_csv(out / "filtered_leaderboard.csv")
    assert summary["filtered_candidates"] == 1
    assert summary["best_filtered_candidate_id"] == "pass"
    assert filtered["candidate_id"].tolist() == ["pass"]


def test_pack_builder_excludes_locked_rows_and_splits_symbols(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    normalized = lake / "normalized"
    normalized.mkdir(parents=True)
    for symbol in ("AAA", "BBB", "SPY"):
        frame = _breakout_frame(300)
        frame["symbol"] = symbol
        frame["date"] = pd.date_range("2019-01-02", periods=len(frame), freq="B")
        frame.to_parquet(normalized / f"{symbol}.parquet", index=False)
    pd.DataFrame(
        {
            "canonical_symbol": ["AAA", "BBB"],
            "security_name": ["A", "B"],
            "asset_type": ["COMMON_STOCK", "COMMON_STOCK"],
        }
    ).to_parquet(lake / "universe.parquet", index=False)

    out = tmp_path / "pack"
    manifest = gtbi.build_stage_packs(lake, out, stage_count=2, locked_start="2020-01-01")

    assert manifest["stage_count"] == 2
    assert len(list(out.glob("stage-*/prices.parquet"))) == 2
    shard = pd.read_parquet(out / "stage-000" / "prices.parquet")
    assert pd.to_datetime(shard["date"]).max() < pd.Timestamp("2020-01-01")


def test_pack_builder_filters_symbols_by_min_market_cap(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    normalized = lake / "normalized"
    metadata = lake / "metadata"
    normalized.mkdir(parents=True)
    metadata.mkdir(parents=True)
    for symbol in ("BIG", "SMALL", "MISSING", "SPY"):
        frame = _breakout_frame(300)
        frame["symbol"] = symbol
        frame["date"] = pd.date_range("2019-01-02", periods=len(frame), freq="B")
        frame.to_parquet(normalized / f"{symbol}.parquet", index=False)
    pd.DataFrame(
        {
            "canonical_symbol": ["BIG", "SMALL", "MISSING"],
            "security_name": ["Big", "Small", "Missing"],
        }
    ).to_parquet(lake / "universe.parquet", index=False)
    pd.DataFrame(
        {
            "symbol": ["BIG", "SMALL"],
            "market_cap": [3_000_000_000, 500_000_000],
        }
    ).to_parquet(metadata / "company_metadata.parquet", index=False)

    out = tmp_path / "pack"
    manifest = gtbi.build_stage_packs(
        lake,
        out,
        stage_count=1,
        locked_start="2020-06-01",
        min_market_cap=2_000_000_000,
    )

    shard = pd.read_parquet(out / "stage-000" / "prices.parquet")
    assert sorted(shard["symbol"].unique()) == ["BIG"]
    assert manifest["min_market_cap"] == 2_000_000_000
    assert manifest["symbols_requested"] == 1


def test_run_stage_smoke_writes_outputs_from_synthetic_pack(tmp_path: Path) -> None:
    pack = tmp_path / "pack" / "stage-000"
    pack.mkdir(parents=True)
    frame = _breakout_frame(360)
    frame["date"] = pd.date_range("2009-01-02", periods=len(frame), freq="B")
    frame.to_parquet(pack / "prices.parquet", index=False)
    spy = _spy_frame(360)
    spy["date"] = pd.date_range("2009-01-02", periods=len(spy), freq="B")
    spy.to_parquet(pack / "benchmark.parquet", index=False)

    out = tmp_path / "stage-output"
    summary = gtbi.run_stage(
        pack_dir=pack,
        output_dir=out,
        stage=0,
        configs_per_stage=4,
        time_budget_minutes=0.05,
        top_per_stage=2,
        train_end="2009-09-30",
        validation_start="2009-10-01",
        validation_end="2010-06-30",
    )

    assert summary["locked_opened"] is False
    assert summary["configs_evaluated"] >= 1
    assert (out / "leaderboard.csv").exists()
    assert (out / "yearly_trade_performance.csv").exists()
    assert (out / "top_indicator_rules.jsonl").exists()


def test_run_stage_supports_dehb_real_validation_selection(tmp_path: Path) -> None:
    pack = tmp_path / "pack" / "stage-000"
    pack.mkdir(parents=True)
    frame = _breakout_frame(360)
    frame["date"] = pd.date_range("2009-01-02", periods=len(frame), freq="B")
    frame.to_parquet(pack / "prices.parquet", index=False)
    spy = _spy_frame(360)
    spy["date"] = pd.date_range("2009-01-02", periods=len(spy), freq="B")
    spy.to_parquet(pack / "benchmark.parquet", index=False)

    out = tmp_path / "stage-output"
    summary = gtbi.run_stage(
        pack_dir=pack,
        output_dir=out,
        stage=0,
        configs_per_stage=4,
        time_budget_minutes=0.05,
        top_per_stage=2,
        train_end="2009-09-30",
        validation_start="2009-10-01",
        validation_end="2010-06-30",
        search_method="dehb_real",
        selection_split="validation",
        min_selection_trades_per_year=0,
    )

    leaderboard = pd.read_csv(out / "leaderboard.csv")
    assert summary["search_method"] == "dehb_real"
    assert summary["selection_split"] == "validation"
    assert set(leaderboard["search_method"].dropna()) <= {"dehb_real"}
    assert set(leaderboard["selection_split"].dropna()) <= {"validation"}


def test_workflow_is_manual_355_job_indicator_run() -> None:
    path = Path(".github/workflows/global-technical-buy-indicator-355jobs.yml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["name"] == "Global Technical Buy Indicator 355 Jobs"
    assert "workflow_dispatch" in data[True]
    assert "push" not in data[True]

    text = path.read_text(encoding="utf-8")
    assert "range(355)" in text
    assert "max-parallel: 178" in text
    assert "max-parallel: 177" in text
    assert "27936694743" in text
    assert "global-technical-buy-indicator-355jobs-results" in text
    assert "search_method" in text
    assert "--search-method" in text
    assert "--selection-split" in text
    assert "--min-selection-trades-per-year" in text
    assert "--family-set" in text
    assert "--min-market-cap" in text
    assert "--scoring-profile" in text
    assert "final_global_recheck_top_n" in text
    assert "reevaluate_global_technical_buy_indicator_results.py" in text


def test_tradingview_minervini_small_workflow_uses_family_set() -> None:
    path = Path(".github/workflows/tradingview-minervini-indicator-small.yml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["name"] == "TradingView Minervini Indicator Small"
    assert "workflow_dispatch" in data[True]

    text = path.read_text(encoding="utf-8")
    assert "range(64)" in text
    assert "--family-set" in text
    assert "--min-market-cap" in text
    assert "--scoring-profile" in text
    assert "tradingview_minervini" in text
    assert "tradingview-minervini-indicator-small-results" in text


def test_final_recheck_workflow_reuses_stage_artifacts() -> None:
    path = Path(".github/workflows/global-technical-buy-indicator-final-recheck.yml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["name"] == "Global Technical Buy Indicator Final Recheck"
    assert "workflow_dispatch" in data[True]

    text = path.read_text(encoding="utf-8")
    assert "source_run_id" in text
    assert "global-technical-buy-indicator-stage-*" in text
    assert "merge_global_technical_buy_indicator_results.py" in text
    assert "reevaluate_global_technical_buy_indicator_results.py" in text
    assert "global-technical-buy-indicator-final-recheck-results" in text


def test_parallel_final_recheck_workflow_splits_candidates() -> None:
    path = Path(".github/workflows/global-technical-buy-indicator-final-recheck-parallel.yml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["name"] == "Global Technical Buy Indicator Final Recheck Parallel"
    assert "workflow_dispatch" in data[True]

    text = path.read_text(encoding="utf-8")
    assert "candidate_count" in text
    assert "--candidate-offset" in text
    assert "--candidate-limit 1" in text
    assert "global-technical-buy-indicator-recheck-candidate-" in text
    assert "global-technical-buy-indicator-final-recheck-parallel-results" in text


def _external_strategy_payload(strategy_id: str, shard_id: int = 0, slot: int = 0) -> dict:
    return {
        "strategy_id": strategy_id,
        "shard_id": shard_id,
        "slot_in_shard": slot,
        "concept_id": "minervini_trend_template_breakout",
        "market_overlay_id": "spy_above_sma200",
        "trend_profile_id": "stage2_stack",
        "rs_profile_id": "rs_vs_spy",
        "exit_profile_id": "stop_trailing_time",
        "aggression_id": "balanced",
        "source_quality_score": 0.91,
        "entry_rules": {
            "breakout_lookback_days": 50,
            "base_length_days_min": 20,
            "volume_on_signal_min_adv20_mult": 1.5,
        },
        "market_regime_rules": {"spy_close_gt_sma200": True},
        "stock_trend_rules": {
            "close_gt_sma50": True,
            "sma50_gt_sma200": True,
            "close_within_52w_high_pct_max": 0.12,
        },
        "relative_strength_rules": {"return_63d_minus_spy_63d_min_pct": 0.05},
        "exit_rules": {
            "stop_loss_pct": 0.08,
            "trailing_stop_pct": 0.18,
            "max_holding_days": 35,
        },
        "guardrails": {
            "data_scope": "train_validation_only",
            "do_not_load_or_use_data_on_or_after": "2021-01-01",
            "locked_start_exclusive": "2021-01-01",
            "execution": "next_session_open",
            "positioning": "long_cash_no_leverage",
            "min_market_cap_usd": 2_000_000_000,
            "train_end": "2010-12-31",
            "validation_start": "2011-01-01",
            "validation_end": "2020-12-31",
        },
        "research_source_ids": ["unit-test-source"],
        "codex_notes": "synthetic test payload",
    }


def _write_external_shard(pack: Path, shard_id: int, rows: int) -> Path:
    shard_dir = pack / "shards"
    shard_dir.mkdir(parents=True, exist_ok=True)
    path = shard_dir / f"shard_{shard_id:03d}.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for slot in range(rows):
            payload = _external_strategy_payload(
                f"gtbi_test_s{shard_id:03d}_{slot:03d}",
                shard_id=shard_id,
                slot=slot,
            )
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
    return path


def test_external_pack_loader_reads_five_jsonl_strategies(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    _write_external_shard(pack, shard_id=0, rows=5)

    candidates = gtbi.load_external_strategy_candidates(pack, limit=5)

    assert len(candidates) == 5
    assert candidates[0].payload["strategy_id"] == "gtbi_test_s000_000"
    assert candidates[0].payload["guardrails"]["do_not_load_or_use_data_on_or_after"] == "2021-01-01"
    assert candidates[0].unsupported_rules == ()


def test_external_pack_loader_reads_one_shard_and_filters_shard_id(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    _write_external_shard(pack, shard_id=0, rows=3)
    _write_external_shard(pack, shard_id=1, rows=4)

    candidates = gtbi.load_external_strategy_candidates(pack, shard_id=1)

    assert len(candidates) == 4
    assert {item.payload["shard_id"] for item in candidates} == {1}


def test_external_pack_loader_limit_applies_before_full_pack_scan(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    _write_external_shard(pack, shard_id=0, rows=8)

    candidates = gtbi.load_external_strategy_candidates(pack, shard_id=0, limit=2)

    assert [item.payload["slot_in_shard"] for item in candidates] == [0, 1]


def test_external_pack_loader_registers_unsupported_rule(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    shard_dir = pack / "shards"
    shard_dir.mkdir(parents=True)
    payload = _external_strategy_payload("gtbi_bad_rule")
    payload["entry_rules"]["unknown_magic_filter"] = True
    (shard_dir / "shard_000.jsonl").write_text(json.dumps(payload) + "\n", encoding="utf-8")

    candidate = gtbi.load_external_strategy_candidates(pack, shard_id=0, limit=1)[0]

    assert "entry_rules.unknown_magic_filter" in candidate.unsupported_rules


def test_external_pack_real_manifest_has_360_shards_and_72000_strategies() -> None:
    pack = Path("scripts/strategy_packs/gtbi_research_broad_72000")
    manifest = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["total_strategies"] == 72_000
    assert manifest["shard_count"] == 360
    assert manifest["strategies_per_shard"] == 200
    assert len(list((pack / "shards").glob("shard_*.jsonl"))) == 360
    assert len(gtbi.load_external_strategy_candidates(pack, shard_id=0, limit=1)) == 1


def test_long_hold_external_pack_real_config_loads_without_unsupported_rules() -> None:
    pack = Path("scripts/strategy_packs/gtbi_long_hold_fundamental_timing_v1")
    run_config = json.loads((pack / "run_config.json").read_text(encoding="utf-8"))

    assert run_config["strategy_count"] == 72_000
    assert run_config["shard_count"] == 360
    assert run_config["strategies_per_shard"] == 200
    assert len(list((pack / "shards").glob("shard_*.jsonl"))) == 360

    candidates = gtbi.load_external_strategy_candidates(pack, shard_id=0, limit=10)

    assert len(candidates) == 10
    assert {item.payload["shard_id"] for item in candidates} == {0}
    assert [item.payload["slot_in_shard"] for item in candidates] == list(range(10))
    assert all(item.payload["schema_version"] == "gtbi_external_strategy_long_hold_v1" for item in candidates)
    assert all(item.unsupported_rules == () for item in candidates)
    assert all(item.config.family == "gtbi_long_hold" for item in candidates)
    assert all(item.config.max_holding_days >= 45 for item in candidates)
    assert all(item.config.minimum_holding_days_before_soft_exit >= 8 for item in candidates)


def test_long_hold_quality_score_and_holding_columns_are_in_leaderboard_contract() -> None:
    required = {
        "long_hold_quality_score",
        "holding_days_p50",
        "holding_days_p75",
        "holding_days_p90",
        "percent_exits_under_5_days",
        "percent_exits_under_10_days",
        "validation_holding_days_p50",
        "validation_holding_days_p75",
        "validation_holding_days_p90",
        "validation_percent_exits_under_5_days",
        "validation_percent_exits_under_10_days",
    }

    assert required.issubset(set(gtbi.LEADERBOARD_COLUMNS))


def test_external_merge_summary_preserves_locked_start_and_no_local_machine(tmp_path: Path) -> None:
    shard = tmp_path / "downloaded" / "gtbi-external-pack-shard-000"
    shard.mkdir(parents=True)
    (shard / "summary_shard_000.json").write_text(
        json.dumps(
            {
                "strategies_loaded": 5,
                "strategies_evaluated": 4,
                "strategies_unsupported": 1,
                "strategies_failed": 0,
            }
        ),
        encoding="utf-8",
    )
    pd.DataFrame(
        [
            {
                "candidate_id": "c1",
                "score": 1.0,
                "adjusted_return_time_risk": 0.25,
                "family": "minervini_sepa",
                "concept_id": "concept_a",
                "market_overlay_id": "market_a",
            }
        ]
    ).to_csv(shard / "leaderboard_shard_000.csv", index=False)
    pd.DataFrame(columns=["candidate_id", "adjusted_return_time_risk"]).to_csv(
        shard / "filtered_leaderboard_shard_000.csv",
        index=False,
    )
    pd.DataFrame(columns=gtbi.YEARLY_COLUMNS).to_csv(shard / "yearly_trade_performance_shard_000.csv", index=False)
    pd.DataFrame(columns=["strategy_id", "shard_id", "slot_in_shard", "unsupported_rules", "reason"]).to_csv(
        shard / "unsupported_strategies_shard_000.csv",
        index=False,
    )

    summary = gtbi.merge_external_strategy_pack_outputs(
        shards_root=tmp_path / "downloaded",
        output_dir=tmp_path / "final",
        total_strategies_requested=72_000,
        total_shards_requested=360,
        locked_start="2021-01-01",
        train_end="2010-12-31",
        validation_start="2011-01-01",
        validation_end="2020-12-31",
    )

    assert summary["locked_start"] == "2021-01-01"
    assert summary["github_only_run"] is True
    assert summary["requires_local_machine"] is False
    assert json.loads((tmp_path / "final" / "summary.json").read_text(encoding="utf-8"))["requires_local_machine"] is False


def test_external_pack_workflow_is_github_only_manual_ubuntu_hosted() -> None:
    path = Path(".github/workflows/global-technical-buy-indicator-external-pack-360jobs.yml")
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)

    assert data["name"] == "Global Technical Buy Indicator External Pack 360 Jobs"
    assert "workflow_dispatch" in data[True]
    assert "push" not in data[True]
    assert text.count("runs-on: ubuntu-latest") >= 3
    assert "self-hosted" not in text
    assert "C:\\" not in text
    assert "scripts/strategy_packs/gtbi_research_broad_72000" in text
    assert "global-technical-buy-indicator-external-pack-72000-results" in text
    assert "--locked-start \"${{ inputs.locked_start }}\"" in text
    assert "requires_local_machine" not in text
