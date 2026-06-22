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
