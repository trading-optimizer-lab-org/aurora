from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

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


def test_stability_family_set_samples_only_stability_families() -> None:
    rng = np.random.default_rng(11)

    configs = [gtbi.sample_config(rng, search_method="dehb_real", family_set="stability") for _ in range(40)]

    assert {cfg.family for cfg in configs}
    assert {cfg.family for cfg in configs} <= set(gtbi.STABILITY_FAMILIES)
    assert "stability_rs_reclaim_frequent" in set(gtbi.STABILITY_FAMILIES)
    assert any(cfg.require_market_trend for cfg in configs)


def test_stability_rs_family_set_excludes_market_dip_and_samples_hybrid() -> None:
    rng = np.random.default_rng(12)

    configs = [gtbi.sample_config(rng, search_method="dehb_real", family_set="stability_rs") for _ in range(80)]
    families = {cfg.family for cfg in configs}

    assert families <= set(gtbi.STABILITY_RS_FAMILIES)
    assert "stability_market_dip" not in families
    assert "stability_rs_pullback_breakout" in set(gtbi.STABILITY_RS_FAMILIES)


def test_seed_mutation_respects_requested_family_set() -> None:
    rng = np.random.default_rng(13)
    seed = gtbi.IndicatorConfig(family="stability_market_dip")

    configs = gtbi._neighbourhood_configs(rng, [seed], 25, family_set="stability_rs")

    assert {cfg.family for cfg in configs} <= set(gtbi.STABILITY_RS_FAMILIES)
    assert "stability_market_dip" not in {cfg.family for cfg in configs}


def test_stability_pullback_rebound_signal_uses_past_pullback() -> None:
    rows = 260
    idx = pd.date_range("2010-01-04", periods=rows, freq="B")
    close = np.linspace(50.0, 100.0, rows)
    close[-3] = 97.0
    close[-2] = 95.0
    close[-1] = 98.35
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * 1.01
    low = np.minimum(open_, close) * 0.99
    frame = pd.DataFrame(
        {
            "date": idx,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "adj_close": close,
            "volume": np.full(rows, 100_000.0),
            "symbol": "AAA",
        }
    )
    spy = _spy_frame(rows)
    spy["date"] = idx
    config = gtbi.IndicatorConfig(
        family="stability_pullback_rebound",
        require_rs=False,
        require_market_trend=False,
        ma_short=20,
        ma_mid=80,
        ma_long=120,
        rsi_period=7,
        rsi_max=65.0,
    )

    signal = gtbi.entry_signal(frame, spy, config)

    assert bool(signal.iloc[-1]) is True
    changed_future = frame.copy()
    changed_future.loc[changed_future.index[-1], "close"] = frame["close"].iloc[-1]
    pd.testing.assert_series_equal(signal.iloc[:-1], gtbi.entry_signal(changed_future, spy, config).iloc[:-1])


def test_strict_market_filter_requires_long_regime_even_with_short_market_ma() -> None:
    rows = 220
    idx = pd.date_range("2010-01-04", periods=rows, freq="B")
    close = np.r_[np.linspace(140.0, 70.0, 180), np.linspace(70.0, 90.0, 40)]
    spy = pd.DataFrame(
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
    config = gtbi.IndicatorConfig(
        require_market_trend=True,
        strict_market_filter=True,
        market_ma_days=50,
        market_momentum_days=21,
    )

    market_ok = gtbi._market_trend_ok(pd.DatetimeIndex(idx), spy, config)

    assert bool(market_ok.iloc[-1]) is False


def test_stability_rs_momentum_pullback_requires_relative_strength() -> None:
    rows = 260
    idx = pd.date_range("2010-01-04", periods=rows, freq="B")
    spy_close = np.linspace(100.0, 110.0, rows)
    close = np.linspace(50.0, 100.0, rows)
    close[-3] = 97.0
    close[-2] = 96.0
    close[-1] = 98.35
    open_ = np.r_[close[0], close[:-1]]
    frame = pd.DataFrame(
        {
            "date": idx,
            "open": open_,
            "high": np.maximum(open_, close) * 1.01,
            "low": np.minimum(open_, close) * 0.99,
            "close": close,
            "adj_close": close,
            "volume": np.full(rows, 100_000.0),
            "symbol": "AAA",
        }
    )
    spy = pd.DataFrame(
        {
            "date": idx,
            "open": spy_close,
            "high": spy_close * 1.002,
            "low": spy_close * 0.998,
            "close": spy_close,
            "adj_close": spy_close,
            "volume": np.full(rows, 1_000_000.0),
            "symbol": "SPY",
        }
    )
    config = gtbi.IndicatorConfig(
        family="stability_rs_momentum_pullback",
        require_market_trend=False,
        ma_short=20,
        ma_mid=80,
        ma_long=120,
        rs_lookback=42,
        rs_near_high_pct=0.88,
        prior_runup_lookback=63,
        prior_runup_min_pct=0.08,
        near_high_pct=0.70,
        rsi_period=7,
        rsi_max=65.0,
    )

    signal = gtbi.entry_signal(frame, spy, config)
    weak_signal = gtbi.entry_signal(frame, frame.assign(symbol="SPY"), config)

    assert bool(signal.iloc[-1]) is True
    assert not bool(weak_signal.iloc[-1])


def test_stability_rs_reclaim_frequent_is_hybrid_and_more_permissive() -> None:
    rows = 260
    idx = pd.date_range("2010-01-04", periods=rows, freq="B")
    spy_close = np.linspace(100.0, 112.0, rows)
    close = np.linspace(50.0, 95.0, rows)
    close[-4] = 92.0
    close[-3] = 90.0
    close[-2] = 89.5
    close[-1] = 94.0
    open_ = np.r_[close[0], close[:-1]]
    frame = pd.DataFrame(
        {
            "date": idx,
            "open": open_,
            "high": np.maximum(open_, close) * 1.01,
            "low": np.minimum(open_, close) * 0.99,
            "close": close,
            "adj_close": close,
            "volume": np.full(rows, 100_000.0),
            "symbol": "AAA",
        }
    )
    spy = pd.DataFrame(
        {
            "date": idx,
            "open": spy_close,
            "high": spy_close * 1.002,
            "low": spy_close * 0.998,
            "close": spy_close,
            "adj_close": spy_close,
            "volume": np.full(rows, 1_000_000.0),
            "symbol": "SPY",
        }
    )
    config = gtbi.IndicatorConfig(
        family="stability_rs_reclaim_frequent",
        require_market_trend=False,
        ma_short=20,
        ma_mid=80,
        ma_long=120,
        rs_lookback=42,
        rs_near_high_pct=0.82,
        prior_runup_lookback=63,
        prior_runup_min_pct=0.05,
        near_high_pct=0.55,
        rsi_period=10,
        rsi_max=67.0,
    )

    signal = gtbi.entry_signal(frame, spy, config)
    weak_signal = gtbi.entry_signal(frame, frame.assign(symbol="SPY"), config)

    assert bool(signal.iloc[-1]) is True
    assert not bool(weak_signal.iloc[-1])


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


def test_strict_market_filter_requires_healthy_spy_stack() -> None:
    idx = pd.date_range("2010-01-04", periods=260, freq="B")
    spy_close = np.r_[np.linspace(90.0, 130.0, 220), np.linspace(130.0, 112.0, 40)]
    spy = pd.DataFrame(
        {
            "date": idx,
            "open": spy_close,
            "high": spy_close * 1.002,
            "low": spy_close * 0.998,
            "close": spy_close,
            "adj_close": spy_close,
            "volume": np.full(len(idx), 1_000_000.0),
            "symbol": "SPY",
        }
    )
    config = gtbi.IndicatorConfig(
        require_market_trend=True,
        strict_market_filter=True,
        market_ma_days=120,
        market_momentum_days=5,
    )

    strict = gtbi._market_trend_ok(idx, spy, config)

    assert not bool(strict.iloc[-1])


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


def test_simulate_trades_skips_directly_to_sparse_signals() -> None:
    idx = pd.date_range("2011-01-03", periods=80, freq="B")
    close = np.linspace(100.0, 120.0, len(idx))
    frame = pd.DataFrame(
        {
            "date": idx,
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "adj_close": close,
            "volume": np.full(len(idx), 1000.0),
            "symbol": "AAA",
        }
    )
    signal = pd.Series(False, index=idx)
    signal.iloc[40] = True
    config = gtbi.IndicatorConfig(
        stop_loss_pct=0.50,
        trailing_stop_pct=0.50,
        max_holding_days=5,
    )

    trades = gtbi.simulate_trades("AAA", frame, signal, config, split="validation")

    assert len(trades) == 1
    assert trades.iloc[0]["entry_date"] == idx[41].date().isoformat()
    assert trades.iloc[0]["exit_reason"] == "max_holding"


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


def test_split_trade_frame_uses_iso_dates_without_pandas_datetime_conversion() -> None:
    trades = pd.DataFrame(
        [
            {"candidate_id": "c1", "symbol": "AAA", "split": "unassigned", "exit_date": "2010-12-31"},
            {"candidate_id": "c1", "symbol": "AAA", "split": "unassigned", "exit_date": "2011-01-03"},
            {"candidate_id": "c1", "symbol": "AAA", "split": "unassigned", "exit_date": "2020-12-31"},
            {"candidate_id": "c1", "symbol": "AAA", "split": "unassigned", "exit_date": "2021-01-04"},
            {"candidate_id": "c1", "symbol": "AAA", "split": "unassigned", "exit_date": "not-a-date"},
        ],
        columns=gtbi.TRADE_COLUMNS,
    )

    out = gtbi.split_trade_frame(
        trades,
        train_end="2010-12-31",
        validation_start="2011-01-01",
        validation_end="2020-12-31",
    )

    assert out["exit_date"].tolist() == ["2010-12-31", "2011-01-03", "2020-12-31"]
    assert out["split"].tolist() == ["train", "validation", "validation"]


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


def test_recheck_batches_group_candidates_after_one_download() -> None:
    batches = gtbi.recheck_batches(candidate_count=150, batch_size=10)

    assert len(batches) == 15
    assert batches[0] == {"offset": 0, "limit": 10, "batch": 0, "batch_padded": "000"}
    assert batches[-1] == {"offset": 140, "limit": 10, "batch": 14, "batch_padded": "014"}


def test_recheck_batches_clamps_last_batch() -> None:
    batches = gtbi.recheck_batches(candidate_count=23, batch_size=10)

    assert [row["offset"] for row in batches] == [0, 10, 20]
    assert [row["limit"] for row in batches] == [10, 10, 3]


def test_near_miss_seed_ids_prefer_close_high_frequency_candidates() -> None:
    leaderboard = pd.DataFrame(
        [
            {
                "candidate_id": "lottery",
                "strict_quality_pass": False,
                "strict_quality_failure_count": 2,
                "validation_min_yearly_trades": 3,
                "validation_trades_per_year": 8,
                "validation_positive_years": 10,
                "validation_median_positive_years": 10,
                "train_2003_2010_positive_years": 8,
                "validation_profit_factor": 3.0,
                "validation_min_yearly_profit_factor": 1.2,
                "train_2003_2010_min_profit_factor": 1.2,
                "validation_median_trade_return_pct": 2.0,
                "validation_avg_trade_return_pct": 8.0,
                "validation_max_profit_contribution_share": 0.6,
                "score": 1000.0,
            },
            {
                "candidate_id": "close",
                "strict_quality_pass": False,
                "strict_quality_failure_count": 3,
                "validation_min_yearly_trades": 120,
                "validation_trades_per_year": 180,
                "validation_positive_years": 9,
                "validation_median_positive_years": 8,
                "train_2003_2010_positive_years": 8,
                "validation_profit_factor": 1.32,
                "validation_min_yearly_profit_factor": 1.01,
                "train_2003_2010_min_profit_factor": 1.04,
                "validation_median_trade_return_pct": 0.12,
                "validation_avg_trade_return_pct": 0.25,
                "validation_max_profit_contribution_share": 0.22,
                "score": 10.0,
            },
        ]
    )

    assert gtbi.near_miss_seed_ids(leaderboard, limit=1) == ["close"]


def test_stability_quality_score_prefers_distribution_over_lottery_average() -> None:
    stable = {
        "strict_quality_pass": False,
        "strict_quality_failure_count": 1,
        "validation_min_yearly_trades": 140,
        "validation_trades_per_year": 240.0,
        "validation_positive_years": 10,
        "validation_median_positive_years": 8,
        "train_2003_2010_positive_years": 8,
        "validation_profit_factor": 1.45,
        "validation_min_yearly_profit_factor": 1.03,
        "train_2003_2010_min_profit_factor": 1.08,
        "validation_median_trade_return_pct": 0.18,
        "validation_avg_trade_return_pct": 0.42,
        "validation_max_profit_contribution_share": 0.22,
    }
    lottery = {
        **stable,
        "strict_quality_failure_count": 3,
        "validation_median_positive_years": 1,
        "validation_median_trade_return_pct": 0.01,
        "validation_avg_trade_return_pct": 4.0,
        "validation_max_profit_contribution_share": 0.80,
    }

    assert gtbi._stability_quality_score(stable) > gtbi._stability_quality_score(lottery)


def test_stability_sort_prefers_fewer_failures_over_lottery_score() -> None:
    leaderboard = pd.DataFrame(
        [
            {
                "candidate_id": "lottery",
                "score": 10_000.0,
                "strict_quality_pass": False,
                "strict_quality_failure_count": 8,
                "validation_min_yearly_trades": 0,
                "validation_trades_per_year": 1.0,
                "validation_positive_years": 1,
                "validation_median_positive_years": 1,
                "train_2003_2010_positive_years": 1,
                "validation_profit_factor": 99.0,
                "validation_min_yearly_profit_factor": 0.0,
                "train_2003_2010_min_profit_factor": 0.0,
                "validation_max_profit_contribution_share": 1.0,
            },
            {
                "candidate_id": "near_pass",
                "score": -100_000.0,
                "strict_quality_pass": False,
                "strict_quality_failure_count": 2,
                "validation_min_yearly_trades": 120,
                "validation_trades_per_year": 170.0,
                "validation_positive_years": 10,
                "validation_median_positive_years": 8,
                "train_2003_2010_positive_years": 8,
                "validation_profit_factor": 1.35,
                "validation_min_yearly_profit_factor": 1.04,
                "train_2003_2010_min_profit_factor": 1.08,
                "validation_max_profit_contribution_share": 0.20,
            },
        ]
    )

    sorted_ids = gtbi._sort_for_stability(leaderboard)["candidate_id"].tolist()

    assert sorted_ids == ["near_pass", "lottery"]


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


def test_pack_price_preparation_filters_locked_rows_without_boolean_frame_slice() -> None:
    frame = pd.DataFrame(
        {
            "date": ["2020-01-03", "2021-01-01", "2020-01-02", "2019-12-31"],
            "open": [11.0, 99.0, 10.0, -1.0],
            "high": [12.0, 100.0, 11.0, 2.0],
            "low": [10.0, 98.0, 9.0, 1.0],
            "close": [11.5, 99.5, 10.5, 1.5],
            "volume": [1000, 2000, 1500, 500],
        }
    )

    prepared = gtbi._prepare_pack_prices_before_locked(frame, symbol="000001-SZ", locked_start="2021-01-01")

    assert prepared.columns.tolist() == gtbi.PRICE_COLUMNS
    assert prepared["symbol"].tolist() == ["000001-SZ", "000001-SZ"]
    assert prepared["date"].tolist() == [pd.Timestamp("2020-01-02"), pd.Timestamp("2020-01-03")]
    assert prepared["adj_close"].tolist() == prepared["close"].tolist()
    assert pd.to_datetime(prepared["date"]).max() < pd.Timestamp("2021-01-01")


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


def test_pack_builder_groups_by_group_count_not_stage_count(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    normalized = lake / "normalized"
    normalized.mkdir(parents=True)
    symbols = ["AAA", "BBB", "CCC", "DDD", "SPY"]
    for symbol in symbols:
        frame = _breakout_frame(300)
        frame["symbol"] = symbol
        frame["date"] = pd.date_range("2019-01-02", periods=len(frame), freq="B")
        frame.to_parquet(normalized / f"{symbol}.parquet", index=False)
    pd.DataFrame(
        {
            "canonical_symbol": ["AAA", "BBB", "CCC", "DDD"],
            "security_name": ["A", "B", "C", "D"],
        }
    ).to_parquet(lake / "universe.parquet", index=False)

    out = tmp_path / "pack"
    gtbi.build_stage_packs(lake, out, stage_count=4, group_count=2, locked_start="2020-06-01")

    group_0 = pd.read_parquet(out / "group-000" / "prices.parquet")
    group_1 = pd.read_parquet(out / "group-001" / "prices.parquet")
    manifest = pd.read_csv(out / "manifest.csv")
    assert sorted(group_0["symbol"].unique()) == ["AAA", "CCC"]
    assert sorted(group_1["symbol"].unique()) == ["BBB", "DDD"]
    assert not list((out / "group-000").glob("stage-*"))
    assert manifest.loc[manifest["stage"].isin([0, 2]), "symbols"].tolist() == [2, 2]
    assert manifest.loc[manifest["stage"] == 1, "symbols"].tolist() == [2]


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
    assert "seed_source_run_id" in text
    assert "prepare_seed_rules" in text
    assert "--seed-rules-path" in text
    assert "--seed-mutation-share" in text
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
    assert "candidate_batch_size" in text
    assert "--candidate-offset" in text
    assert '--candidate-limit "${{ matrix.limit }}"' in text
    assert "Reuse source SPY benchmark" in text
    assert "global-technical-buy-indicator-pack-group-000" in text
    assert "rm -rf \"candidate-batch-${{ matrix.batch_padded }}/_global_recheck_pack\"" in text
    assert "global-technical-buy-indicator-recheck-batch-" in text
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


def test_external_pack_loader_splits_shard_into_40_strategy_offsets(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    _write_external_shard(pack, shard_id=0, rows=200)

    chunk_0 = gtbi.load_external_strategy_candidates(pack, shard_id=0, offset=0, limit=40)
    chunk_1 = gtbi.load_external_strategy_candidates(pack, shard_id=0, offset=40, limit=40)
    chunk_4 = gtbi.load_external_strategy_candidates(pack, shard_id=0, offset=160, limit=40)
    chunk_past_end = gtbi.load_external_strategy_candidates(pack, shard_id=0, offset=200, limit=40)

    assert len(chunk_0) == 40
    assert len(chunk_1) == 40
    assert len(chunk_4) == 40
    assert chunk_past_end == []
    assert [item.payload["slot_in_shard"] for item in chunk_0] == list(range(0, 40))
    assert [item.payload["slot_in_shard"] for item in chunk_1] == list(range(40, 80))
    assert [item.payload["slot_in_shard"] for item in chunk_4] == list(range(160, 200))
    assert {item.payload["strategy_id"] for item in chunk_0}.isdisjoint(
        {item.payload["strategy_id"] for item in chunk_1}
    )
    assert chunk_0[0].payload["guardrails"]["do_not_load_or_use_data_on_or_after"] == "2021-01-01"
    assert chunk_0[0].payload["guardrails"]["validation_end"] == "2020-12-31"


def test_external_pack_loader_rejects_negative_offset(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    _write_external_shard(pack, shard_id=0, rows=5)

    with pytest.raises(ValueError, match="external_strategy_offset"):
        gtbi.load_external_strategy_candidates(pack, shard_id=0, offset=-1, limit=1)


def test_external_pack_loader_registers_unsupported_rule(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    shard_dir = pack / "shards"
    shard_dir.mkdir(parents=True)
    payload = _external_strategy_payload("gtbi_bad_rule")
    payload["entry_rules"]["unknown_magic_filter"] = True
    (shard_dir / "shard_000.jsonl").write_text(json.dumps(payload) + "\n", encoding="utf-8")

    candidate = gtbi.load_external_strategy_candidates(pack, shard_id=0, limit=1)[0]

    assert "entry_rules.unknown_magic_filter" in candidate.unsupported_rules


def test_external_canonical_hash_ignores_notes_but_changes_exit_rules(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    shard = pack / "shards"
    shard.mkdir(parents=True)
    first = _external_strategy_payload("same_effective_a")
    second = _external_strategy_payload("same_effective_b")
    second["codex_notes"] = "different note should not alter effective rules"
    second["research_source_ids"] = ["different-source"]
    third = _external_strategy_payload("different_exit")
    third["exit_rules"]["take_profit_pct"] = 0.11
    (shard / "shard_000.jsonl").write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in (first, second, third)) + "\n",
        encoding="utf-8",
    )

    candidates = gtbi.load_external_strategy_candidates(pack, shard_id=0, limit=3)

    assert gtbi.canonical_external_strategy_hash(candidates[0]) == gtbi.canonical_external_strategy_hash(candidates[1])
    assert gtbi.canonical_external_strategy_hash(candidates[0]) != gtbi.canonical_external_strategy_hash(candidates[2])


def test_signal_external_strategy_hash_ignores_exit_rules_but_not_entry_rules(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    shard = pack / "shards"
    shard.mkdir(parents=True)
    base = _external_strategy_payload("base")
    different_exit = _external_strategy_payload("different_exit")
    different_exit["exit_rules"]["take_profit_pct"] = 0.25
    different_entry = _external_strategy_payload("different_entry")
    different_entry["entry_rules"]["prior_runup_min_pct"] = 0.55
    (shard / "shard_000.jsonl").write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in (base, different_exit, different_entry)) + "\n",
        encoding="utf-8",
    )

    candidates = gtbi.load_external_strategy_candidates(pack, shard_id=0, limit=3)

    assert gtbi.canonical_external_strategy_hash(candidates[0]) != gtbi.canonical_external_strategy_hash(candidates[1])
    assert gtbi.signal_external_strategy_hash(candidates[0]) == gtbi.signal_external_strategy_hash(candidates[1])
    assert gtbi.signal_external_strategy_hash(candidates[0]) != gtbi.signal_external_strategy_hash(candidates[2])


def test_signal_external_strategy_hash_uses_effective_signal_config_not_labels() -> None:
    first_payload = _external_strategy_payload("signal_hash_effective_a")
    second_payload = _external_strategy_payload("signal_hash_effective_b")
    second_payload["concept_id"] = "q_stair_step_breakout"
    second_payload["market_overlay_id"] = "different_overlay_label"
    second_payload["trend_profile_id"] = "different_trend_label"
    second_payload["rs_profile_id"] = "different_rs_label"
    second_payload["aggression_id"] = "different_aggression_label"
    first = gtbi.external_strategy_to_config(first_payload)
    second = gtbi.external_strategy_to_config(second_payload)

    assert first.config == second.config
    assert gtbi.signal_external_strategy_hash(first) == gtbi.signal_external_strategy_hash(second)


def test_external_cost_scheduling_orders_fast_candidates_first() -> None:
    fast = _external_strategy_payload("fast_candidate")
    slow = _external_strategy_payload("slow_candidate")
    slow["concept_id"] = "bollinger_squeeze_breakout"
    slow["exit_profile_id"] = "balanced_tp_ema20"
    slow["market_overlay_id"] = "spy_low_vol_uptrend"
    slow["aggression_id"] = "frequency_quality"

    ordered = sorted([slow, fast], key=lambda payload: gtbi._estimated_cost_score(payload)[0])

    assert ordered[0]["strategy_id"] == "fast_candidate"
    assert gtbi._estimated_cost_score(slow)[1] == "very_slow"


def test_v3_observed_timeout_concepts_are_not_marked_fast() -> None:
    for concept in (
        "moving_average_timing_cross",
        "q_stair_step_breakout",
        "time_series_momentum_reentry",
        "rsi2_pullback_rebound_trend",
    ):
        payload = _external_strategy_payload(f"{concept}_candidate")
        payload["concept_id"] = concept

        _, bucket = gtbi._estimated_cost_score(payload)

        assert bucket in {"slow", "very_slow"}


def test_v5_observed_expensive_event_first_concepts_are_not_marked_fast() -> None:
    for concept in (
        "three_weeks_tight_daily_proxy",
        "q_stair_step_reclaim",
        "q_stair_step_breakout",
        "macd_histogram_turnup_trend",
        "post_ep_pullback_reclaim_proxy",
        "bollinger_lower_band_reclaim_trend",
        "rs_pullback_hold_rebound",
    ):
        payload = _external_strategy_payload(f"{concept}_candidate")
        payload["concept_id"] = concept

        _, bucket = gtbi._estimated_cost_score(
            payload,
            optimized_evaluation_mode="optimized_evaluation_v5_event_first",
        )

        assert bucket in {"slow", "very_slow"}


def test_v5_cost_weights_do_not_change_default_or_v4_scheduling() -> None:
    payload = _external_strategy_payload("event_first_only_cost")
    payload["concept_id"] = "three_weeks_tight_daily_proxy"

    default_score = gtbi._estimated_cost_score(payload)
    v4_score = gtbi._estimated_cost_score(payload, optimized_evaluation_mode="optimized_evaluation_v4_zero_timeout")
    v5_score = gtbi._estimated_cost_score(payload, optimized_evaluation_mode="optimized_evaluation_v5_event_first")

    assert default_score == v4_score
    assert default_score[1] == "fast"
    assert v5_score[1] in {"slow", "very_slow"}


def test_balanced_external_strategy_candidates_group_fast_signal_siblings_before_slow(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    shard_dir = pack / "shards"
    shard_dir.mkdir(parents=True)
    rows = []
    for idx in range(24):
        payload = _external_strategy_payload(f"fast_{idx:02d}", shard_id=idx // 20, slot=idx % 20)
        payload["concept_id"] = "rs_pullback_hold_rebound"
        rows.append(payload)
    for idx in range(24):
        payload = _external_strategy_payload(f"slow_{idx:02d}", shard_id=1 + idx // 20, slot=idx % 20)
        payload["concept_id"] = "bollinger_squeeze_breakout"
        payload["exit_profile_id"] = "balanced_tp_ema20"
        payload["market_overlay_id"] = "spy_low_vol_uptrend"
        payload["aggression_id"] = "frequency_quality"
        rows.append(payload)
    by_shard: dict[int, list[dict[str, object]]] = {}
    for row in rows:
        by_shard.setdefault(int(row["shard_id"]), []).append(row)
    for shard_id, shard_rows in by_shard.items():
        (shard_dir / f"shard_{shard_id:03d}.jsonl").write_text(
            "\n".join(json.dumps(row, sort_keys=True) for row in shard_rows) + "\n",
            encoding="utf-8",
        )

    first_job, total_jobs = gtbi._balanced_external_strategy_candidates_for_job(
        pack,
        job_index=0,
        candidate_count_per_job=4,
    )
    later_job, _ = gtbi._balanced_external_strategy_candidates_for_job(
        pack,
        job_index=6,
        candidate_count_per_job=4,
    )

    assert total_jobs == 12
    assert first_job[0].payload["concept_id"] == "rs_pullback_hold_rebound"
    assert later_job[0].payload["concept_id"] == "bollinger_squeeze_breakout"
    assert len(first_job) == 4
    assert len({gtbi.signal_external_strategy_hash(candidate) for candidate in first_job}) == 1


def test_balanced_external_strategy_candidates_uses_active_job_window_for_smoke(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    shard_dir = pack / "shards"
    shard_dir.mkdir(parents=True)
    rows = []
    for idx in range(20):
        payload = _external_strategy_payload(f"fast_{idx:02d}", shard_id=idx // 10, slot=idx % 10)
        payload["concept_id"] = "rs_pullback_hold_rebound"
        rows.append(payload)
    for idx in range(20):
        payload = _external_strategy_payload(f"slow_{idx:02d}", shard_id=2 + idx // 10, slot=idx % 10)
        payload["concept_id"] = "bollinger_squeeze_breakout"
        payload["exit_profile_id"] = "balanced_tp_ema20"
        payload["market_overlay_id"] = "spy_low_vol_uptrend"
        payload["aggression_id"] = "frequency_quality"
        rows.append(payload)
    by_shard: dict[int, list[dict[str, object]]] = {}
    for row in rows:
        by_shard.setdefault(int(row["shard_id"]), []).append(row)
    for shard_id, shard_rows in by_shard.items():
        (shard_dir / f"shard_{shard_id:03d}.jsonl").write_text(
            "\n".join(json.dumps(row, sort_keys=True) for row in shard_rows) + "\n",
            encoding="utf-8",
        )

    first_job, total_jobs = gtbi._balanced_external_strategy_candidates_for_job(
        pack,
        job_index=0,
        candidate_count_per_job=4,
        schedule_active_jobs=2,
    )
    second_job, _ = gtbi._balanced_external_strategy_candidates_for_job(
        pack,
        job_index=1,
        candidate_count_per_job=4,
        schedule_active_jobs=2,
    )

    assert total_jobs == 10
    assert [candidate.payload["concept_id"] for candidate in first_job] == ["rs_pullback_hold_rebound"] * 4
    assert [candidate.payload["concept_id"] for candidate in second_job] == ["rs_pullback_hold_rebound"] * 4


def test_balanced_external_strategy_candidates_groups_signal_siblings_for_smoke(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    shard_dir = pack / "shards"
    shard_dir.mkdir(parents=True)
    exit_variants = [
        ("quick_tp_ema10", {"take_profit_pct": 0.10, "max_holding_days": 12}),
        ("balanced_tp_ema20", {"take_profit_pct": 0.20, "max_holding_days": 25}),
        ("chandelier_runner", {"trailing_stop_pct": 0.22, "max_holding_days": 60}),
        ("setup_low_fast_exit", {"stop_loss_pct": 0.05, "max_holding_days": 8}),
    ]
    rows = []
    for group in range(4):
        for variant, (exit_profile, exit_rules) in enumerate(exit_variants):
            payload = _external_strategy_payload(
                f"group_{group}_exit_{variant}",
                shard_id=0,
                slot=group * 4 + variant,
            )
            payload["concept_id"] = "q_stair_step_breakout"
            payload["entry_rules"]["breakout_lookback_days"] = 30 + group
            payload["exit_profile_id"] = exit_profile
            payload["exit_rules"].update(exit_rules)
            rows.append(payload)
    (shard_dir / "shard_000.jsonl").write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )

    first_job, total_jobs = gtbi._balanced_external_strategy_candidates_for_job(
        pack,
        job_index=0,
        candidate_count_per_job=4,
        schedule_active_jobs=4,
    )

    assert total_jobs == 4
    signal_hashes = [gtbi.signal_external_strategy_hash(candidate) for candidate in first_job]
    canonical_hashes = [gtbi.canonical_external_strategy_hash(candidate) for candidate in first_job]
    assert len(set(signal_hashes)) == 1
    assert len(set(canonical_hashes)) == 4


def test_signal_first_balancer_selects_complete_signal_groups(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    shard_dir = pack / "shards"
    shard_dir.mkdir(parents=True)
    rows: list[dict[str, object]] = []
    for group_index in range(3):
        for exit_index in range(4):
            payload = _external_strategy_payload(
                f"signal_{group_index}_exit_{exit_index}",
                shard_id=0,
                slot=group_index * 4 + exit_index,
            )
            payload["concept_id"] = f"concept_{group_index}"
            payload["entry_rules"]["breakout_lookback_days"] = 30 + group_index
            payload["exit_rules"]["take_profit_pct"] = 0.05 + exit_index * 0.05
            rows.append(payload)
    (shard_dir / "shard_000.jsonl").write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )

    selected, total_jobs, total_signal_groups = gtbi._balanced_external_signal_groups_for_job(
        pack,
        job_index=0,
        signal_groups_per_job=2,
        schedule_active_jobs=None,
        max_signal_groups=None,
        strategy_format="jsonl",
    )

    assert total_signal_groups == 3
    assert total_jobs == 2
    assert len(selected) == 2
    assert [len(group) for group in selected] == [4, 4]
    assert all(len({gtbi.signal_external_strategy_hash(candidate) for candidate in group}) == 1 for group in selected)


def test_signal_first_balancer_uses_lower_cost_signal_groups_for_smoke_window(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    shard_dir = pack / "shards"
    shard_dir.mkdir(parents=True)
    rows: list[dict[str, object]] = []
    for concept in ("post_ep_pullback_reclaim_proxy", "atr_compression_nr_breakout"):
        for group_index in range(3):
            for exit_index in range(4):
                payload = _external_strategy_payload(
                    f"{concept}_{group_index}_exit_{exit_index}",
                    shard_id=0,
                    slot=len(rows),
                )
                payload["concept_id"] = concept
                payload["entry_rules"]["breakout_lookback_days"] = 30 + group_index
                payload["exit_rules"]["take_profit_pct"] = 0.05 + exit_index * 0.05
                rows.append(payload)
    (shard_dir / "shard_000.jsonl").write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )

    selected, total_jobs, total_signal_groups = gtbi._balanced_external_signal_groups_for_job(
        pack,
        job_index=0,
        signal_groups_per_job=2,
        schedule_active_jobs=1,
        max_signal_groups=None,
        strategy_format="jsonl",
        optimized_evaluation_mode="optimized_evaluation_v5_event_first",
    )

    assert total_jobs == 1
    assert total_signal_groups == 2
    selected_concepts = {candidate.payload["concept_id"] for group in selected for candidate in group}
    assert selected_concepts == {"atr_compression_nr_breakout"}
    selected_cost = min(
        gtbi._estimated_cost_score(candidate.payload, optimized_evaluation_mode="optimized_evaluation_v5_event_first")[0]
        for group in selected
        for candidate in group
    )
    skipped_post_ep = [row for row in rows if row["concept_id"] == "post_ep_pullback_reclaim_proxy"]
    skipped_cost = min(
        gtbi._estimated_cost_score(row, optimized_evaluation_mode="optimized_evaluation_v5_event_first")[0]
        for row in skipped_post_ep
    )
    assert selected_cost < skipped_cost


def test_v5_signal_scheduler_caps_strategy_budget_per_job(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    shard_dir = pack / "shards"
    shard_dir.mkdir(parents=True)
    rows: list[dict[str, object]] = []
    for group_index in range(30):
        for exit_index in range(16):
            payload = _external_strategy_payload(
                f"budget_group_{group_index}_exit_{exit_index}",
                shard_id=0,
                slot=len(rows),
            )
            payload["concept_id"] = "ep_gap_volume_continuation_proxy"
            payload["entry_rules"]["breakout_lookback_days"] = 20 + group_index
            payload["exit_rules"]["take_profit_pct"] = 0.03 + exit_index * 0.01
            rows.append(payload)
    (shard_dir / "shard_000.jsonl").write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )

    selected, total_jobs, total_signal_groups = gtbi._balanced_external_signal_groups_for_job(
        pack,
        job_index=0,
        signal_groups_per_job=10,
        schedule_active_jobs=4,
        max_signal_groups=None,
        strategy_format="jsonl",
        optimized_evaluation_mode="optimized_evaluation_v5_event_first",
    )

    assert total_jobs == 4
    assert total_signal_groups <= 12
    assert len(selected) <= 3
    assert sum(len(group) for group in selected) <= 50


def test_optimized_v2_does_not_use_job_wall_clock_as_hard_candidate_deadline() -> None:
    assert gtbi._effective_job_deadline(
        optimized_evaluation_mode="optimized_evaluation_v2",
        job_start=100.0,
        job_wall_clock_seconds=300,
    ) is None
    assert gtbi._effective_job_deadline(
        optimized_evaluation_mode="optimized_evaluation_v3_signal_first",
        job_start=100.0,
        job_wall_clock_seconds=300,
    ) is None
    assert gtbi._effective_job_deadline(
        optimized_evaluation_mode="optimized_evaluation_v1",
        job_start=100.0,
        job_wall_clock_seconds=300,
    ) == 400.0


def test_feature_store_preserves_entry_signals() -> None:
    frame = gtbi._prepare_ohlcv(_breakout_frame(140))
    spy = gtbi._prepare_ohlcv(_spy_frame(140))
    config = gtbi.IndicatorConfig(
        family="minervini_sepa",
        minervini_trend=False,
        require_rs=False,
        require_base_tight=True,
        require_breakout=True,
        breakout_lookback=20,
        base_lookback=20,
        volume_lookback=20,
        volume_multiple=1.5,
        max_base_range_pct=0.20,
        rsi_max=100.0,
    )

    baseline = gtbi.entry_signal(frame.copy(), spy.copy(), config)
    store = gtbi.build_feature_store({"AAA": frame}, spy, enabled=True)
    cached = gtbi.entry_signal(store.symbol_frames["AAA"], store.benchmark_prices, config)

    pd.testing.assert_series_equal(baseline, cached)
    assert store.seconds_build >= 0.0


def test_signal_primitive_store_reuses_boolean_primitives() -> None:
    frame = gtbi._prepare_ohlcv(_breakout_frame(140))
    spy = gtbi._prepare_ohlcv(_spy_frame(140))
    store = gtbi.SignalPrimitiveStore(frame, spy)

    close_gt_ema10 = store.close_gt_ema(10)
    close_gt_ema10_again = store.close_gt_ema(10)
    ema10_gt_ema20 = store.ema_gt_ema(10, 20)
    breakout_20 = store.close_breaks_high(20)
    volume_breakout = store.volume_gt_adv(20, 1.5)
    rs_filter = store.rs_ratio_gt_ma(20)

    assert close_gt_ema10 is close_gt_ema10_again
    assert len(ema10_gt_ema20) == len(frame)
    assert len(breakout_20) == len(frame)
    assert len(volume_breakout) == len(frame)
    assert len(rs_filter) == len(frame)


def test_simulate_trades_executes_next_session_open_with_array_safe_rules() -> None:
    idx = pd.date_range("2020-01-01", periods=6, freq="B")
    frame = pd.DataFrame(
        {
            "date": idx,
            "open": [10.0, 11.0, 12.0, 13.0, 14.0, 15.0],
            "high": [10.5, 11.2, 13.5, 13.2, 14.2, 15.2],
            "low": [9.8, 10.8, 11.8, 12.7, 13.8, 14.8],
            "close": [10.1, 11.1, 12.8, 13.0, 14.1, 15.1],
            "adj_close": [10.1, 11.1, 12.8, 13.0, 14.1, 15.1],
            "volume": [1000, 1000, 1000, 1000, 1000, 1000],
            "symbol": "AAA",
        }
    )
    prepared = gtbi._prepare_ohlcv(frame)
    signal = pd.Series(False, index=prepared.index)
    signal.iloc[0] = True
    config = gtbi.IndicatorConfig(
        family="minervini_sepa",
        take_profit_pct=0.10,
        stop_loss_pct=0.50,
        trailing_stop_pct=0.0,
        use_exit_ma=False,
        use_market_exit=False,
        max_holding_days=5,
    )

    trades = gtbi.simulate_trades("AAA", prepared, signal, config, split="unassigned", candidate_id="c")

    assert len(trades) == 1
    row = trades.iloc[0]
    assert row["entry_date"] == "2020-01-02"
    assert row["entry_price"] == 11.0
    assert row["exit_date"] == "2020-01-06"
    assert row["exit_price"] == 13.0
    assert row["exit_reason"] == "take_profit"


def test_simulate_trades_array_route_matches_pandas_reference() -> None:
    idx = pd.date_range("2019-01-01", periods=80, freq="B")
    close = 50.0 + np.sin(np.arange(len(idx)) / 3.0) * 1.5 + np.arange(len(idx)) * 0.08
    frame = gtbi._prepare_ohlcv(
        pd.DataFrame(
            {
                "date": idx,
                "open": close * 1.001,
                "high": close * 1.035,
                "low": close * 0.965,
                "close": close,
                "adj_close": close,
                "volume": np.full(len(idx), 100_000.0),
                "symbol": "AAA",
            }
        )
    )
    signal = pd.Series(False, index=frame.index)
    signal.iloc[::9] = True
    exit_signal = pd.Series(False, index=frame.index)
    exit_signal.iloc[25] = True
    config = gtbi.IndicatorConfig(
        family="minervini_sepa",
        stop_loss_pct=0.06,
        take_profit_pct=0.08,
        trailing_stop_pct=0.05,
        use_exit_ma=True,
        use_market_exit=True,
        exit_ma_days=7,
        max_holding_days=6,
    )

    def pandas_reference() -> pd.DataFrame:
        reference_frame = gtbi._prepare_ohlcv(frame)
        reference_signal = signal.reindex(reference_frame.index).fillna(False).astype(bool)
        reference_exit_signal = exit_signal.reindex(reference_frame.index).fillna(False).astype(bool)
        exit_ma = reference_frame["close"].rolling(config.exit_ma_days, min_periods=config.exit_ma_days).mean()
        trades: list[dict[str, object]] = []
        in_position = False
        entry_idx = -1
        entry_price = 0.0
        high_water = 0.0
        i = 0
        while i < len(reference_frame) - 1:
            if not in_position:
                if not bool(reference_signal.iloc[i]):
                    i += 1
                    continue
                entry_idx = i + 1
                entry_price = float(reference_frame["open"].iloc[entry_idx])
                high_water = float(reference_frame["high"].iloc[entry_idx])
                in_position = True
                i = entry_idx
                continue
            high_water = max(high_water, float(reference_frame["high"].iloc[i]))
            reason = None
            if float(reference_frame["low"].iloc[i]) <= entry_price * (1.0 - config.stop_loss_pct):
                reason = "stop_loss"
            elif config.take_profit_pct > 0 and float(reference_frame["high"].iloc[i]) >= entry_price * (1.0 + config.take_profit_pct):
                reason = "take_profit"
            elif config.trailing_stop_pct > 0 and float(reference_frame["low"].iloc[i]) <= high_water * (1.0 - config.trailing_stop_pct):
                reason = "trailing_stop"
            elif config.use_exit_ma and pd.notna(exit_ma.iloc[i]) and float(reference_frame["close"].iloc[i]) < float(exit_ma.iloc[i]):
                reason = "exit_ma"
            elif config.use_market_exit and bool(reference_exit_signal.iloc[i]):
                reason = "market_exit"
            elif min(i + 1, len(reference_frame) - 1) - entry_idx >= config.max_holding_days:
                reason = "max_holding"
            if reason is not None:
                exit_idx = min(i + 1, len(reference_frame) - 1)
                exit_price = float(reference_frame["open"].iloc[exit_idx])
                trades.append(
                    {
                        "candidate_id": "array",
                        "symbol": "AAA",
                        "split": "unassigned",
                        "entry_date": pd.Timestamp(reference_frame.index[entry_idx]).date().isoformat(),
                        "exit_date": pd.Timestamp(reference_frame.index[exit_idx]).date().isoformat(),
                        "entry_price": entry_price,
                        "exit_price": exit_price,
                        "return_pct": float((exit_price / entry_price - 1.0) * 100.0),
                        "holding_days": int(exit_idx - entry_idx),
                        "exit_reason": reason,
                    }
                )
                in_position = False
                i = exit_idx
                continue
            i += 1
        if in_position:
            exit_idx = len(reference_frame) - 1
            exit_price = float(reference_frame["open"].iloc[exit_idx])
            trades.append(
                {
                    "candidate_id": "array",
                    "symbol": "AAA",
                    "split": "unassigned",
                    "entry_date": pd.Timestamp(reference_frame.index[entry_idx]).date().isoformat(),
                    "exit_date": pd.Timestamp(reference_frame.index[exit_idx]).date().isoformat(),
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "return_pct": float((exit_price / entry_price - 1.0) * 100.0),
                    "holding_days": int(exit_idx - entry_idx),
                    "exit_reason": "end_of_data",
                }
            )
        return pd.DataFrame(trades, columns=gtbi.TRADE_COLUMNS)

    array_trades = gtbi.simulate_trades(
        "AAA",
        frame,
        signal,
        config,
        split="unassigned",
        candidate_id="array",
        exit_signal=exit_signal,
    )
    reference_trades = pandas_reference()

    pd.testing.assert_frame_equal(array_trades.reset_index(drop=True), reference_trades.reset_index(drop=True))
    assert gtbi.summarize_trades(array_trades, years=1.0) == gtbi.summarize_trades(reference_trades, years=1.0)


def test_numba_trade_core_matches_python_core_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    if gtbi._simulate_trade_arrays_numba is None:
        pytest.skip("numba optional dependency is not installed")
    idx = pd.date_range("2019-01-01", periods=55, freq="B")
    close = 40.0 + np.sin(np.arange(len(idx)) / 4.0) * 1.2 + np.arange(len(idx)) * 0.05
    frame = gtbi._prepare_ohlcv(
        pd.DataFrame(
            {
                "date": idx,
                "open": close * 1.002,
                "high": close * 1.035,
                "low": close * 0.965,
                "close": close,
                "adj_close": close,
                "volume": np.full(len(idx), 100_000.0),
                "symbol": "AAA",
            }
        )
    )
    signal = np.zeros(len(frame), dtype=bool)
    signal[::8] = True
    signal_positions = np.flatnonzero(signal[:-1])
    exit_signal = np.zeros(len(frame), dtype=bool)
    exit_signal[28] = True
    config = gtbi.IndicatorConfig(
        stop_loss_pct=0.06,
        take_profit_pct=0.08,
        trailing_stop_pct=0.05,
        use_exit_ma=True,
        use_market_exit=True,
        exit_ma_days=7,
        max_holding_days=6,
    )
    exit_ma = frame["close"].rolling(config.exit_ma_days, min_periods=config.exit_ma_days).mean().to_numpy(
        dtype=float,
        copy=False,
    )
    args = (
        frame["open"].to_numpy(dtype=float, copy=False),
        frame["high"].to_numpy(dtype=float, copy=False),
        frame["low"].to_numpy(dtype=float, copy=False),
        frame["close"].to_numpy(dtype=float, copy=False),
        exit_ma,
        exit_signal,
        signal_positions,
        float(config.stop_loss_pct),
        float(config.take_profit_pct),
        float(config.trailing_stop_pct),
        bool(config.use_exit_ma),
        bool(config.use_market_exit),
        int(config.max_holding_days),
    )

    python_result = gtbi._simulate_trade_arrays_core(*args)
    numba_result = gtbi._simulate_trade_arrays_numba(*args)

    assert int(numba_result[-1]) == int(python_result[-1])
    count = int(python_result[-1])
    for python_values, numba_values in zip(python_result[:-1], numba_result[:-1], strict=True):
        np.testing.assert_allclose(numba_values[:count], python_values[:count])

    monkeypatch.setenv("GTBI_ENABLE_NUMBA_SIM", "1")
    assert gtbi._numba_simulation_state() == (True, "enabled_by_env")


def test_numba_trade_simulation_auto_uses_available_accelerator(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GTBI_ENABLE_NUMBA_SIM", raising=False)
    enabled, reason = gtbi._numba_simulation_state()

    assert enabled is (gtbi._simulate_trade_arrays_numba is not None)
    assert reason in {"auto_enabled_numba", "numba_unavailable"}


def test_optimized_candidate_matches_legacy_when_prefilter_disabled() -> None:
    frame = gtbi._prepare_ohlcv(_breakout_frame(180))
    spy = gtbi._prepare_ohlcv(_spy_frame(180))
    config = gtbi.IndicatorConfig(
        family="minervini_sepa",
        minervini_trend=False,
        require_rs=False,
        require_base_tight=True,
        require_breakout=True,
        breakout_lookback=20,
        base_lookback=20,
        volume_lookback=20,
        volume_multiple=1.5,
        max_base_range_pct=0.20,
        rsi_max=100.0,
        max_holding_days=10,
    )

    legacy_row, legacy_trades, legacy_yearly = gtbi.evaluate_candidate(
        config=config,
        candidate_id="legacy",
        stage=0,
        symbol_frames={"AAA": frame},
        benchmark_prices=spy,
        selection_split="validation",
        scoring_profile="strict_quality",
    )
    opt_row, opt_trades, opt_yearly, diagnostic = gtbi.evaluate_candidate_optimized(
        config=config,
        candidate_id="legacy",
        stage=0,
        symbol_frames={"AAA": frame},
        benchmark_prices=spy,
        selection_split="validation",
        scoring_profile="strict_quality",
        enable_safe_prefilter=False,
        enable_early_stopping=False,
    )

    for key in ("score", "train_trades", "validation_trades", "strict_quality_pass", "adjusted_return_time_risk"):
        left = legacy_row[key]
        right = opt_row[key]
        if isinstance(left, float) and np.isnan(left):
            assert np.isnan(right)
        else:
            assert right == left
    pd.testing.assert_frame_equal(legacy_trades.reset_index(drop=True), opt_trades.reset_index(drop=True))
    pd.testing.assert_frame_equal(legacy_yearly.reset_index(drop=True), opt_yearly.reset_index(drop=True))
    assert diagnostic["symbols_processed"] == 1


def test_optimized_candidate_can_reuse_precomputed_signal_vectors(monkeypatch: pytest.MonkeyPatch) -> None:
    frame = gtbi._prepare_ohlcv(_breakout_frame(180))
    spy = gtbi._prepare_ohlcv(_spy_frame(180))
    config = gtbi.IndicatorConfig(
        family="minervini_sepa",
        minervini_trend=False,
        require_rs=False,
        require_base_tight=True,
        require_breakout=True,
        breakout_lookback=20,
        base_lookback=20,
        volume_lookback=20,
        volume_multiple=1.5,
        max_base_range_pct=0.20,
        rsi_max=100.0,
        max_holding_days=10,
    )
    signal = gtbi.entry_signal(frame, spy, config)

    def fail_if_called(*args: object, **kwargs: object) -> pd.Series:
        raise AssertionError("entry_signal should not be called when signals are precomputed")

    monkeypatch.setattr(gtbi, "entry_signal", fail_if_called)
    row, trades, yearly, diagnostic = gtbi.evaluate_candidate_optimized(
        config=config,
        candidate_id="reused",
        stage=0,
        symbol_frames={"AAA": frame},
        benchmark_prices=spy,
        selection_split="validation",
        scoring_profile="strict_quality",
        enable_safe_prefilter=False,
        enable_early_stopping=False,
        precomputed_signals_by_symbol={"AAA": signal},
        precomputed_signal_seconds=0.0,
        precomputed_symbols_processed=1,
        precomputed_raw_signals_total=int(signal.sum()),
    )

    assert row["candidate_id"] == "reused"
    assert diagnostic["seconds_signal"] == 0.0
    assert diagnostic["symbols_processed"] == 1
    assert not trades.empty
    assert not yearly.empty


def test_early_stopping_flag_enables_safe_signal_reject_without_prefilter_flag() -> None:
    idx = pd.date_range("2003-01-01", "2020-12-31", freq="B")
    close = np.linspace(50.0, 150.0, len(idx))
    frame = gtbi._prepare_ohlcv(
        pd.DataFrame(
            {
                "date": idx,
                "open": close,
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
                "adj_close": close,
                "volume": np.full(len(idx), 100_000.0),
                "symbol": "AAA",
            }
        )
    )
    sparse_signal = pd.Series(False, index=frame.index)
    sparse_signal.iloc[100] = True
    with pytest.raises(gtbi.EarlyRejectedStrategy, match="raw_signal_yearly_trades_lt_100"):
        gtbi.evaluate_candidate_optimized(
            config=gtbi.IndicatorConfig(family="minervini_sepa"),
            candidate_id="sparse",
            stage=0,
            symbol_frames={"AAA": frame},
            benchmark_prices=frame,
            enable_safe_prefilter=False,
            enable_early_stopping=True,
            precomputed_signals_by_symbol={"AAA": sparse_signal},
            precomputed_signal_seconds=0.0,
            precomputed_symbols_processed=1,
            precomputed_raw_signals_total=1,
        )


def test_external_runner_reuses_signal_signature_for_exit_variants(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_payload = _external_strategy_payload("same_signal_a")
    second_payload = _external_strategy_payload("same_signal_b")
    second_payload["exit_rules"]["take_profit_pct"] = 0.25
    candidates = [gtbi.external_strategy_to_config(first_payload), gtbi.external_strategy_to_config(second_payload)]
    frame = gtbi._prepare_ohlcv(_breakout_frame(180))
    spy = gtbi._prepare_ohlcv(_spy_frame(180))
    signal = pd.Series(False, index=frame.index)
    signal.iloc[70] = True
    signal_calls = {"count": 0}
    core_precomputed: list[bool] = []

    def fake_load_candidates(*args: object, **kwargs: object) -> list[gtbi.ExternalStrategyCandidate]:
        return candidates

    def fake_entry_signal(*args: object, **kwargs: object) -> pd.Series:
        signal_calls["count"] += 1
        return signal

    def fake_core(**kwargs: object) -> tuple[dict[str, object], pd.DataFrame, pd.DataFrame, dict[str, object]]:
        core_precomputed.append(kwargs.get("precomputed_signals_by_symbol") is not None)
        candidate_id = str(kwargs["candidate_id"])
        row = {
            "candidate_id": candidate_id,
            "stage": 0,
            "search_method": gtbi.EXTERNAL_SEARCH_METHOD,
            "family": "minervini_sepa",
            "score": 0.0,
            "strict_quality_pass": False,
            "adjusted_return_time_risk": 0.0,
            "train_trades": 0,
            "validation_trades": 0,
        }
        diagnostic = {
            "seconds_total": 0.1,
            "seconds_feature_build": 0.0,
            "seconds_signal": 0.0 if kwargs.get("precomputed_signals_by_symbol") is not None else 1.0,
            "seconds_simulation": 0.0,
            "seconds_train": 0.0,
            "seconds_validation": 0.0,
            "symbols_total": 1,
            "symbols_processed": 1,
            "raw_signals_total": int(signal.sum()),
            "trades_total": 0,
            "train_trades": 0,
            "validation_trades": 0,
        }
        return row, pd.DataFrame(columns=gtbi.TRADE_COLUMNS), pd.DataFrame(columns=gtbi.YEARLY_COLUMNS), diagnostic

    monkeypatch.setattr(gtbi, "load_external_strategy_candidates", fake_load_candidates)
    monkeypatch.setattr(gtbi, "_load_symbol_frames", lambda path: {"AAA": frame})
    monkeypatch.setattr(gtbi.pd, "read_parquet", lambda path: spy)
    monkeypatch.setattr(gtbi, "entry_signal", fake_entry_signal)
    monkeypatch.setattr(gtbi, "_evaluate_external_candidate_core", fake_core)
    pack_dir = tmp_path / "prebuilt"
    pack_dir.mkdir()
    (pack_dir / "prices.parquet").write_text("stub", encoding="utf-8")
    (pack_dir / "benchmark.parquet").write_text("stub", encoding="utf-8")

    gtbi.run_external_strategy_pack_shard(
        data_lake_root=tmp_path,
        external_strategy_pack_path=tmp_path / "pack",
        output_dir=tmp_path / "out" / "job-0000",
        prebuilt_pack_dir=pack_dir,
        external_strategy_shard_id=0,
        external_strategy_limit=2,
        optimized_evaluation_mode="optimized_evaluation_v2",
        enable_dedupe=True,
        enable_safe_prefilter=False,
        job_wall_clock_seconds=0,
    )

    dedupe = pd.read_csv(tmp_path / "out" / "job-0000" / "dedupe_map_job_0000.csv")
    assert signal_calls["count"] == 1
    assert core_precomputed == [True, True]
    assert dedupe["deduped"].tolist() == [False, False]
    assert dedupe["signal_deduped"].tolist() == [False, True]


def test_event_first_runner_reuses_result_for_same_signal_and_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_payload = _external_strategy_payload("same_signal_exit_a")
    second_payload = _external_strategy_payload("same_signal_exit_b")
    second_payload["concept_id"] = "q_stair_step_breakout"
    second_payload["market_overlay_id"] = "different_overlay_label"
    second_payload["trend_profile_id"] = "different_trend_label"
    second_payload["rs_profile_id"] = "different_rs_label"
    second_payload["aggression_id"] = "different_aggression_label"
    candidates = [gtbi.external_strategy_to_config(first_payload), gtbi.external_strategy_to_config(second_payload)]
    assert candidates[0].config == candidates[1].config
    assert gtbi.canonical_external_strategy_hash(candidates[0]) != gtbi.canonical_external_strategy_hash(candidates[1])
    assert gtbi.signal_external_strategy_hash(candidates[0]) == gtbi.signal_external_strategy_hash(candidates[1])
    assert gtbi.exit_external_strategy_hash(candidates[0]) == gtbi.exit_external_strategy_hash(candidates[1])
    frame = gtbi._prepare_ohlcv(_breakout_frame(180))
    spy = gtbi._prepare_ohlcv(_spy_frame(180))
    signal = pd.Series(False, index=frame.index)
    signal.iloc[70] = True
    signal_calls = {"count": 0}
    core_calls = {"count": 0}

    def fake_load_candidates(*args: object, **kwargs: object) -> list[gtbi.ExternalStrategyCandidate]:
        return candidates

    def fake_entry_signal(*args: object, **kwargs: object) -> pd.Series:
        signal_calls["count"] += 1
        return signal

    def fake_core(**kwargs: object) -> tuple[dict[str, object], pd.DataFrame, pd.DataFrame, dict[str, object]]:
        core_calls["count"] += 1
        candidate_id = str(kwargs["candidate_id"])
        row = {
            "candidate_id": candidate_id,
            "stage": 0,
            "search_method": gtbi.EXTERNAL_SEARCH_METHOD,
            "family": "minervini_sepa",
            "score": 0.0,
            "strict_quality_pass": False,
            "adjusted_return_time_risk": 0.0,
            "train_trades": 0,
            "validation_trades": 0,
        }
        diagnostic = {
            "seconds_total": 0.1,
            "seconds_feature_build": 0.0,
            "seconds_signal": 0.0,
            "seconds_simulation": 0.5,
            "seconds_train": 0.1,
            "seconds_validation": 0.1,
            "symbols_total": 1,
            "symbols_processed": 1,
            "raw_signals_total": int(signal.sum()),
            "trades_total": 0,
            "train_trades": 0,
            "validation_trades": 0,
        }
        return row, pd.DataFrame(columns=gtbi.TRADE_COLUMNS), pd.DataFrame(columns=gtbi.YEARLY_COLUMNS), diagnostic

    monkeypatch.setattr(gtbi, "load_external_strategy_candidates", fake_load_candidates)
    monkeypatch.setattr(gtbi, "_load_symbol_frames", lambda path: {"AAA": frame})
    monkeypatch.setattr(gtbi.pd, "read_parquet", lambda path: spy)
    monkeypatch.setattr(gtbi, "entry_signal", fake_entry_signal)
    monkeypatch.setattr(gtbi, "_evaluate_external_candidate_core", fake_core)
    monkeypatch.setattr(gtbi, "_safe_prefilter_raw_signals", lambda *args, **kwargs: (None, 0))
    pack_dir = tmp_path / "prebuilt"
    pack_dir.mkdir()
    (pack_dir / "prices.parquet").write_text("stub", encoding="utf-8")
    (pack_dir / "benchmark.parquet").write_text("stub", encoding="utf-8")

    gtbi.run_external_strategy_pack_shard(
        data_lake_root=tmp_path,
        external_strategy_pack_path=tmp_path / "pack",
        output_dir=tmp_path / "out" / "job-0000",
        prebuilt_pack_dir=pack_dir,
        external_strategy_shard_id=0,
        external_strategy_limit=2,
        optimized_evaluation_mode="optimized_evaluation_v5_event_first",
        enable_dedupe=True,
        enable_safe_prefilter=False,
        job_wall_clock_seconds=0,
    )

    dedupe = pd.read_csv(tmp_path / "out" / "job-0000" / "dedupe_map_job_0000.csv")
    timing = pd.read_csv(tmp_path / "out" / "job-0000" / "timing_diagnostics_job_0000.csv")
    assert signal_calls["count"] == 1
    assert core_calls["count"] == 1
    assert dedupe["deduped"].tolist() == [False, True]
    assert dedupe["signal_deduped"].tolist() == [False, True]
    assert timing["result_status"].tolist() == ["evaluated", "deduped"]


def test_external_runner_counts_signal_reuse_when_candidate_is_early_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_payload = _external_strategy_payload("same_signal_reject_a")
    second_payload = _external_strategy_payload("same_signal_reject_b")
    second_payload["exit_rules"]["take_profit_pct"] = 0.25
    candidates = [gtbi.external_strategy_to_config(first_payload), gtbi.external_strategy_to_config(second_payload)]
    frame = gtbi._prepare_ohlcv(_breakout_frame(180))
    spy = gtbi._prepare_ohlcv(_spy_frame(180))
    signal = pd.Series(False, index=frame.index)
    signal.iloc[70] = True
    signal_calls = {"count": 0}

    def fake_load_candidates(*args: object, **kwargs: object) -> list[gtbi.ExternalStrategyCandidate]:
        return candidates

    def fake_entry_signal(*args: object, **kwargs: object) -> pd.Series:
        signal_calls["count"] += 1
        return signal

    def fake_core(**kwargs: object) -> tuple[dict[str, object], pd.DataFrame, pd.DataFrame, dict[str, object]]:
        raise gtbi.EarlyRejectedStrategy(
            "raw_signal_yearly_trades_lt_100",
            split="validation",
            year=2011,
            actual=1,
            threshold=100,
            symbols_processed=1,
            diagnostic={
                "seconds_total": 0.1,
                "seconds_signal": 0.0,
                "symbols_total": 1,
                "symbols_processed": 1,
                "raw_signals_total": 1,
            },
        )

    monkeypatch.setattr(gtbi, "load_external_strategy_candidates", fake_load_candidates)
    monkeypatch.setattr(gtbi, "_load_symbol_frames", lambda path: {"AAA": frame})
    monkeypatch.setattr(gtbi.pd, "read_parquet", lambda path: spy)
    monkeypatch.setattr(gtbi, "entry_signal", fake_entry_signal)
    monkeypatch.setattr(gtbi, "_evaluate_external_candidate_core", fake_core)
    pack_dir = tmp_path / "prebuilt"
    pack_dir.mkdir()
    (pack_dir / "prices.parquet").write_text("stub", encoding="utf-8")
    (pack_dir / "benchmark.parquet").write_text("stub", encoding="utf-8")

    gtbi.run_external_strategy_pack_shard(
        data_lake_root=tmp_path,
        external_strategy_pack_path=tmp_path / "pack",
        output_dir=tmp_path / "out" / "job-0000",
        prebuilt_pack_dir=pack_dir,
        external_strategy_shard_id=0,
        external_strategy_limit=2,
        optimized_evaluation_mode="optimized_evaluation_v2",
        enable_dedupe=True,
        enable_safe_prefilter=False,
        job_wall_clock_seconds=0,
    )

    dedupe = pd.read_csv(tmp_path / "out" / "job-0000" / "dedupe_map_job_0000.csv")
    summary = json.loads((tmp_path / "out" / "job-0000" / "summary_job_0000.json").read_text(encoding="utf-8"))
    assert signal_calls["count"] == 1
    assert dedupe["signal_deduped"].tolist() == [False, True]
    assert summary["cached_signal_reuses"] == 1


def test_signal_first_runner_rejects_whole_signal_group_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_payload = _external_strategy_payload("same_signal_group_a")
    second_payload = _external_strategy_payload("same_signal_group_b")
    second_payload["exit_rules"]["take_profit_pct"] = 0.25
    candidates = [gtbi.external_strategy_to_config(first_payload), gtbi.external_strategy_to_config(second_payload)]
    frame = gtbi._prepare_ohlcv(_breakout_frame(180))
    spy = gtbi._prepare_ohlcv(_spy_frame(180))
    signal = pd.Series(False, index=frame.index)
    signal.iloc[70] = True
    signal_calls = {"count": 0}
    core_calls = {"count": 0}
    prewarm_calls = {"count": 0}

    def fake_load_candidates(*args: object, **kwargs: object) -> list[gtbi.ExternalStrategyCandidate]:
        return candidates

    def fake_build_signal(**kwargs: object) -> tuple[dict[str, pd.Series], dict[str, object]]:
        signal_calls["count"] += 1
        return {"AAA": signal}, {"seconds_signal": 1.5, "symbols_processed": 1, "raw_signals_total": 1}

    def fake_prefilter(**kwargs: object) -> tuple[dict[str, object] | None, int]:
        return (
            {
                "reason": "raw_signal_yearly_trades_lt_100",
                "split": "validation",
                "year": 2011,
                "actual": 1,
                "threshold": 100,
                "stage": "safe_prefilter",
            },
            1,
        )

    def fake_core(**kwargs: object) -> tuple[dict[str, object], pd.DataFrame, pd.DataFrame, dict[str, object]]:
        core_calls["count"] += 1
        raise AssertionError("signal-first prefilter should stop before exit simulation")

    def fake_prewarm(*args: object, **kwargs: object) -> None:
        prewarm_calls["count"] += 1

    monkeypatch.setattr(gtbi, "load_external_strategy_candidates", fake_load_candidates)
    monkeypatch.setattr(gtbi, "_load_symbol_frames", lambda path: {"AAA": frame})
    monkeypatch.setattr(gtbi.pd, "read_parquet", lambda path: spy)
    monkeypatch.setattr(gtbi, "_build_signals_by_symbol", fake_build_signal)
    monkeypatch.setattr(gtbi, "_safe_prefilter_raw_signals", fake_prefilter)
    monkeypatch.setattr(gtbi, "_evaluate_external_candidate_core", fake_core)
    monkeypatch.setattr(gtbi, "_prewarm_common_features", fake_prewarm)
    pack_dir = tmp_path / "prebuilt"
    pack_dir.mkdir()
    (pack_dir / "prices.parquet").write_text("stub", encoding="utf-8")
    (pack_dir / "benchmark.parquet").write_text("stub", encoding="utf-8")

    summary = gtbi.run_external_strategy_pack_shard(
        data_lake_root=tmp_path,
        external_strategy_pack_path=tmp_path / "pack",
        output_dir=tmp_path / "out" / "job-0000",
        prebuilt_pack_dir=pack_dir,
        external_strategy_shard_id=0,
        external_strategy_limit=2,
        optimized_evaluation_mode="optimized_evaluation_v3_signal_first",
        enable_dedupe=True,
        job_wall_clock_seconds=0,
    )

    timing = pd.read_csv(tmp_path / "out" / "job-0000" / "timing_diagnostics_job_0000.csv")
    assert signal_calls["count"] == 1
    assert core_calls["count"] == 0
    assert prewarm_calls["count"] == 0
    assert summary["signal_groups_loaded"] == 1
    assert summary["signal_groups_early_rejected"] == 1
    assert summary["strategies_early_rejected"] == 2
    assert summary["strategies_signal_reused"] == 1
    assert timing["result_status"].tolist() == ["signal_early_rejected", "signal_early_rejected"]


def test_signal_first_runner_stops_before_job_wall_clock_shutdown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_payload = _external_strategy_payload("slow_signal_group_a")
    second_payload = _external_strategy_payload("slow_signal_group_b")
    second_payload["entry_rules"]["breakout_lookback_days"] = 80
    candidates = [gtbi.external_strategy_to_config(first_payload), gtbi.external_strategy_to_config(second_payload)]
    frame = gtbi._prepare_ohlcv(_breakout_frame(180))
    spy = gtbi._prepare_ohlcv(_spy_frame(180))
    signal_calls = {"count": 0}

    def fake_load_candidates(*args: object, **kwargs: object) -> list[gtbi.ExternalStrategyCandidate]:
        return candidates

    def fake_build_signal(**kwargs: object) -> tuple[dict[str, pd.Series], dict[str, object]]:
        signal_calls["count"] += 1
        deadline = kwargs.get("deadline")
        if deadline is not None and deadline <= gtbi.time.perf_counter():
            raise gtbi.CandidateEvaluationTimeout("candidate evaluation exceeded cooperative deadline while building signals")
        signal = pd.Series(False, index=frame.index)
        signal.iloc[70] = True
        return {"AAA": signal}, {"seconds_signal": 0.0, "symbols_processed": 1, "raw_signals_total": 1}

    monkeypatch.setattr(gtbi, "load_external_strategy_candidates", fake_load_candidates)
    monkeypatch.setattr(gtbi, "_load_symbol_frames", lambda path: {"AAA": frame})
    monkeypatch.setattr(gtbi.pd, "read_parquet", lambda path: spy)
    monkeypatch.setattr(gtbi, "_build_signals_by_symbol", fake_build_signal)
    pack_dir = tmp_path / "prebuilt"
    pack_dir.mkdir()
    (pack_dir / "prices.parquet").write_text("stub", encoding="utf-8")
    (pack_dir / "benchmark.parquet").write_text("stub", encoding="utf-8")

    summary = gtbi.run_external_strategy_pack_shard(
        data_lake_root=tmp_path,
        external_strategy_pack_path=tmp_path / "pack",
        output_dir=tmp_path / "out" / "job-0000",
        prebuilt_pack_dir=pack_dir,
        external_strategy_shard_id=0,
        external_strategy_limit=2,
        optimized_evaluation_mode="optimized_evaluation_v3_signal_first",
        enable_dedupe=True,
        job_wall_clock_seconds=1,
    )

    timeouts = pd.read_csv(tmp_path / "out" / "job-0000" / "timeout_strategies_job_0000.csv")
    manifest = pd.read_csv(tmp_path / "out" / "job-0000" / "signal_group_manifest_job_0000.csv")
    assert signal_calls["count"] <= 1
    assert summary["strategies_timed_out"] == 2
    assert summary["signal_groups_timed_out"] == 2
    assert timeouts["strategy_id"].tolist() == ["slow_signal_group_a", "slow_signal_group_b"]
    assert manifest["result_status"].tolist() == ["signal_timeout", "signal_timeout"]


def test_zero_timeout_runner_defers_known_slow_signal_group_before_signal_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_payload = _external_strategy_payload("slow_known_a")
    second_payload = _external_strategy_payload("slow_known_b")
    first_payload["concept_id"] = "macd_histogram_turnup_trend"
    second_payload["concept_id"] = "macd_histogram_turnup_trend"
    second_payload["exit_rules"]["take_profit_pct"] = 0.25
    candidates = [gtbi.external_strategy_to_config(first_payload), gtbi.external_strategy_to_config(second_payload)]
    frame = gtbi._prepare_ohlcv(_breakout_frame(180))
    spy = gtbi._prepare_ohlcv(_spy_frame(180))

    def fake_load_candidates(*args: object, **kwargs: object) -> list[gtbi.ExternalStrategyCandidate]:
        return candidates

    def fail_build_signal(**kwargs: object) -> tuple[dict[str, pd.Series], dict[str, object]]:
        raise AssertionError("known slow v4 concepts should enter slow queue before signal build")

    def no_specific_precheck(**kwargs: object) -> tuple[None, int, int, int, float]:
        return None, 0, 0, 0, 0.0

    monkeypatch.setattr(gtbi, "load_external_strategy_candidates", fake_load_candidates)
    monkeypatch.setattr(gtbi, "_load_symbol_frames", lambda path: {"AAA": frame})
    monkeypatch.setattr(gtbi.pd, "read_parquet", lambda path: spy)
    monkeypatch.setattr(gtbi, "_specific_slow_concept_precheck", no_specific_precheck)
    monkeypatch.setattr(gtbi, "_build_signals_by_symbol", fail_build_signal)
    pack_dir = tmp_path / "prebuilt"
    pack_dir.mkdir()
    (pack_dir / "prices.parquet").write_text("stub", encoding="utf-8")
    (pack_dir / "benchmark.parquet").write_text("stub", encoding="utf-8")

    summary = gtbi.run_external_strategy_pack_shard(
        data_lake_root=tmp_path,
        external_strategy_pack_path=tmp_path / "pack",
        output_dir=tmp_path / "out" / "job-0000",
        prebuilt_pack_dir=pack_dir,
        external_strategy_shard_id=0,
        external_strategy_limit=2,
        optimized_evaluation_mode="optimized_evaluation_v4_zero_timeout",
        enable_dedupe=True,
        job_wall_clock_seconds=300,
    )

    slow = pd.read_csv(tmp_path / "out" / "job-0000" / "slow_deferred_strategies_job_0000.csv")
    queue = pd.read_csv(tmp_path / "out" / "job-0000" / "slow_queue_manifest_job_0000.csv")
    timing = pd.read_csv(tmp_path / "out" / "job-0000" / "timing_diagnostics_job_0000.csv")
    timeouts = pd.read_csv(tmp_path / "out" / "job-0000" / "timeout_strategies_job_0000.csv")
    assert summary["zero_timeout_mode"] is True
    assert summary["strategies_timed_out"] == 0
    assert summary["strategies_slow_deferred"] == 2
    assert summary["strategies_loaded"] == (
        summary["strategies_evaluated"]
        + summary["strategies_early_rejected"]
        + summary["strategies_slow_deferred"]
        + summary["strategies_unsupported"]
        + summary["strategies_runtime_error"]
    )
    assert summary["signal_groups_slow_deferred"] == 1
    assert timeouts.empty
    assert slow["strategy_id"].tolist() == ["slow_known_a", "slow_known_b"]
    assert set(slow["reason"]) == {"known_slow_concept"}
    assert queue["concept"].tolist() == ["macd_histogram_turnup_trend"]
    assert timing["result_status"].tolist() == ["slow_deferred", "slow_deferred"]
    assert timing["timeout"].astype(bool).tolist() == [False, False]


@pytest.mark.parametrize(
    ("concept", "reason_prefix"),
    [
        ("macd_histogram_turnup_trend", "macd_histogram_turnup_trend_precheck_"),
        ("post_ep_pullback_reclaim_proxy", "post_ep_pullback_reclaim_proxy_precheck_"),
    ],
)
def test_zero_timeout_specific_slow_precheck_early_rejects_impossible_sparse_concepts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    concept: str,
    reason_prefix: str,
) -> None:
    payload = _external_strategy_payload(f"sparse_{concept}")
    payload["concept_id"] = concept
    candidates = [gtbi.external_strategy_to_config(payload)]
    idx = pd.date_range("2003-01-01", "2020-12-31", freq="B")
    close = np.full(len(idx), 100.0)
    frame = gtbi._prepare_ohlcv(
        pd.DataFrame(
            {
                "date": idx,
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "adj_close": close,
                "volume": np.full(len(idx), 100_000.0),
                "symbol": "AAA",
            }
        )
    )
    spy = gtbi._prepare_ohlcv(
        pd.DataFrame(
            {
                "date": idx,
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "adj_close": close,
                "volume": np.full(len(idx), 1_000_000.0),
                "symbol": "SPY",
            }
        )
    )

    def fake_load_candidates(*args: object, **kwargs: object) -> list[gtbi.ExternalStrategyCandidate]:
        return candidates

    def fail_build_signal(**kwargs: object) -> tuple[dict[str, pd.Series], dict[str, object]]:
        raise AssertionError("specific slow precheck should reject before full signal build")

    monkeypatch.setattr(gtbi, "load_external_strategy_candidates", fake_load_candidates)
    monkeypatch.setattr(gtbi, "_load_symbol_frames", lambda path: {"AAA": frame})
    monkeypatch.setattr(gtbi.pd, "read_parquet", lambda path: spy)
    monkeypatch.setattr(gtbi, "_build_signals_by_symbol", fail_build_signal)
    pack_dir = tmp_path / "prebuilt"
    pack_dir.mkdir()
    (pack_dir / "prices.parquet").write_text("stub", encoding="utf-8")
    (pack_dir / "benchmark.parquet").write_text("stub", encoding="utf-8")

    summary = gtbi.run_external_strategy_pack_shard(
        data_lake_root=tmp_path,
        external_strategy_pack_path=tmp_path / "pack",
        output_dir=tmp_path / "out" / "job-0000",
        prebuilt_pack_dir=pack_dir,
        external_strategy_shard_id=0,
        external_strategy_limit=1,
        optimized_evaluation_mode="optimized_evaluation_v4_zero_timeout",
        enable_dedupe=True,
        job_wall_clock_seconds=300,
    )

    early = pd.read_csv(tmp_path / "out" / "job-0000" / "early_rejected_strategies_job_0000.csv")
    timeouts = pd.read_csv(tmp_path / "out" / "job-0000" / "timeout_strategies_job_0000.csv")
    manifest = pd.read_csv(tmp_path / "out" / "job-0000" / "signal_group_manifest_job_0000.csv")
    assert summary["strategies_timed_out"] == 0
    assert summary["strategies_early_rejected"] == 1
    assert summary["strategies_slow_deferred"] == 0
    assert timeouts.empty
    assert early["reason"].iloc[0].startswith(reason_prefix)
    assert early["stage"].iloc[0] == f"{concept}_precheck"
    assert manifest["result_status"].tolist() == ["signal_early_rejected"]


@pytest.mark.parametrize("concept", ["macd_histogram_turnup_trend", "post_ep_pullback_reclaim_proxy"])
def test_zero_timeout_specific_slow_precheck_does_not_false_reject_dense_superset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    concept: str,
) -> None:
    payload = _external_strategy_payload(f"dense_{concept}")
    payload["concept_id"] = concept
    candidates = [gtbi.external_strategy_to_config(payload)]
    idx = pd.date_range("2003-01-01", "2020-12-31", freq="B")
    close = np.linspace(50.0, 150.0, len(idx))
    frame = gtbi._prepare_ohlcv(
        pd.DataFrame(
            {
                "date": idx,
                "open": close,
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
                "adj_close": close,
                "volume": np.full(len(idx), 100_000.0),
                "symbol": "AAA",
            }
        )
    )
    spy = frame.copy()

    def fake_load_candidates(*args: object, **kwargs: object) -> list[gtbi.ExternalStrategyCandidate]:
        return candidates

    def dense_precheck_signal(**kwargs: object) -> pd.Series:
        return pd.Series(True, index=frame.index)

    def fail_build_signal(**kwargs: object) -> tuple[dict[str, pd.Series], dict[str, object]]:
        raise AssertionError("dense known-slow precheck should defer before full signal build")

    monkeypatch.setattr(gtbi, "load_external_strategy_candidates", fake_load_candidates)
    monkeypatch.setattr(gtbi, "_load_symbol_frames", lambda path: {"AAA": frame})
    monkeypatch.setattr(gtbi.pd, "read_parquet", lambda path: spy)
    monkeypatch.setattr(gtbi, "_specific_slow_concept_precheck_signal", dense_precheck_signal)
    monkeypatch.setattr(gtbi, "_build_signals_by_symbol", fail_build_signal)
    pack_dir = tmp_path / "prebuilt"
    pack_dir.mkdir()
    (pack_dir / "prices.parquet").write_text("stub", encoding="utf-8")
    (pack_dir / "benchmark.parquet").write_text("stub", encoding="utf-8")

    summary = gtbi.run_external_strategy_pack_shard(
        data_lake_root=tmp_path,
        external_strategy_pack_path=tmp_path / "pack",
        output_dir=tmp_path / "out" / "job-0000",
        prebuilt_pack_dir=pack_dir,
        external_strategy_shard_id=0,
        external_strategy_limit=1,
        optimized_evaluation_mode="optimized_evaluation_v4_zero_timeout",
        enable_dedupe=True,
        job_wall_clock_seconds=300,
    )

    early = pd.read_csv(tmp_path / "out" / "job-0000" / "early_rejected_strategies_job_0000.csv")
    slow = pd.read_csv(tmp_path / "out" / "job-0000" / "slow_deferred_strategies_job_0000.csv")
    timeouts = pd.read_csv(tmp_path / "out" / "job-0000" / "timeout_strategies_job_0000.csv")
    assert summary["strategies_timed_out"] == 0
    assert summary["strategies_early_rejected"] == 0
    assert summary["strategies_slow_deferred"] == 1
    assert early.empty
    assert timeouts.empty
    assert slow["reason"].tolist() == ["known_slow_concept"]


@pytest.mark.parametrize(
    "concept",
    [
        "academic_6_12m_momentum_reclaim",
        "academic_52w_high_pullback_reclaim",
        "adx_di_pullback_reversal",
        "ep_gap_volume_continuation_proxy",
        "q_stair_step_reclaim",
        "q_stair_step_breakout",
        "bollinger_lower_band_reclaim_trend",
        "rs_pullback_hold_rebound",
    ],
)
def test_event_first_prechecks_extra_slow_concepts_without_slow_queue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    concept: str,
) -> None:
    payload = _external_strategy_payload(f"event_first_sparse_{concept}")
    payload["concept_id"] = concept
    candidates = [gtbi.external_strategy_to_config(payload)]
    idx = pd.date_range("2003-01-01", "2020-12-31", freq="B")
    close = np.full(len(idx), 100.0)
    frame = gtbi._prepare_ohlcv(
        pd.DataFrame(
            {
                "date": idx,
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "adj_close": close,
                "volume": np.full(len(idx), 100_000.0),
                "symbol": "AAA",
            }
        )
    )
    spy = frame.copy()

    def fake_load_candidates(*args: object, **kwargs: object) -> list[gtbi.ExternalStrategyCandidate]:
        return candidates

    def fail_build_signal(**kwargs: object) -> tuple[dict[str, pd.Series], dict[str, object]]:
        raise AssertionError("event-first precheck should reject sparse extra concepts before full signal build")

    monkeypatch.setattr(gtbi, "load_external_strategy_candidates", fake_load_candidates)
    monkeypatch.setattr(gtbi, "_load_symbol_frames", lambda path: {"AAA": frame})
    monkeypatch.setattr(gtbi.pd, "read_parquet", lambda path: spy)
    monkeypatch.setattr(gtbi, "_build_signals_by_symbol", fail_build_signal)
    pack_dir = tmp_path / "prebuilt"
    pack_dir.mkdir()
    (pack_dir / "prices.parquet").write_text("stub", encoding="utf-8")
    (pack_dir / "benchmark.parquet").write_text("stub", encoding="utf-8")

    summary = gtbi.run_external_strategy_pack_shard(
        data_lake_root=tmp_path,
        external_strategy_pack_path=tmp_path / "pack",
        output_dir=tmp_path / "out" / "job-0000",
        prebuilt_pack_dir=pack_dir,
        external_strategy_shard_id=0,
        external_strategy_limit=1,
        optimized_evaluation_mode="optimized_evaluation_v5_event_first",
        enable_dedupe=True,
        job_wall_clock_seconds=300,
    )

    out = tmp_path / "out" / "job-0000"
    early = pd.read_csv(out / "early_rejected_strategies_job_0000.csv")
    slow = pd.read_csv(out / "slow_deferred_strategies_job_0000.csv")
    concept_diag = pd.read_csv(out / "concept_precheck_diagnostics_job_0000.csv")
    event_manifest = pd.read_csv(out / "event_store_manifest_job_0000.csv")
    assert summary["strategies_timed_out"] == 0
    assert summary["strategies_slow_deferred"] == 0
    assert summary["zero_slow_deferred_mode"] is True
    assert summary["strategies_early_rejected"] == 1
    assert slow.empty
    assert early["reason"].iloc[0].startswith(f"{concept}_precheck_")
    assert concept_diag["decision"].tolist() == ["early_rejected"]
    assert event_manifest["concept"].tolist() == [concept]


@pytest.mark.parametrize("concept", ["bollinger_lower_band_reclaim_trend", "rs_pullback_hold_rebound"])
def test_event_first_breakout_superset_precheck_contains_legacy_signal(concept: str) -> None:
    payload = _external_strategy_payload(f"superset_{concept}")
    payload["concept_id"] = concept
    payload["entry_rules"]["volume_on_signal_min_adv20_mult"] = 0.50
    candidate = gtbi.external_strategy_to_config(payload)
    idx = pd.date_range("2003-01-01", "2020-12-31", freq="B")
    close = np.linspace(20.0, 220.0, len(idx))
    frame = gtbi._prepare_ohlcv(
        pd.DataFrame(
            {
                "date": idx,
                "open": close,
                "high": close,
                "low": close * 0.99,
                "close": close,
                "adj_close": close,
                "volume": np.full(len(idx), 100_000.0),
                "symbol": "AAA",
            }
        )
    )
    benchmark = gtbi._prepare_ohlcv(
        pd.DataFrame(
            {
                "date": idx,
                "open": close * 0.95,
                "high": close * 0.95,
                "low": close * 0.94,
                "close": close * 0.95,
                "adj_close": close * 0.95,
                "volume": np.full(len(idx), 1_000_000.0),
                "symbol": "SPY",
            }
        )
    )

    legacy = gtbi.entry_signal(frame, benchmark, candidate.config).reindex(frame.index).fillna(False).astype(bool)
    precheck = gtbi._specific_slow_concept_precheck_signal(
        concept=concept,
        frame=frame,
        config=candidate.config,
    ).reindex(frame.index).fillna(False).astype(bool)

    assert bool(legacy.any())
    assert not bool((legacy & ~precheck).any())


def test_zero_timeout_long_budget_single_candidate_evaluates_known_slow_signal_group(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_payload = _external_strategy_payload("slow_queue_a")
    first_payload["concept_id"] = "macd_histogram_turnup_trend"
    candidates = [gtbi.external_strategy_to_config(first_payload)]
    frame = gtbi._prepare_ohlcv(_breakout_frame(180))
    spy = gtbi._prepare_ohlcv(_spy_frame(180))
    signal = pd.Series(False, index=frame.index)
    signal.iloc[70] = True
    signal_calls = {"count": 0}
    core_calls: list[str] = []

    def fake_load_candidates(*args: object, **kwargs: object) -> list[gtbi.ExternalStrategyCandidate]:
        return candidates

    def fake_build_signal(**kwargs: object) -> tuple[dict[str, pd.Series], dict[str, object]]:
        signal_calls["count"] += 1
        return {"AAA": signal}, {"seconds_signal": 0.5, "symbols_processed": 1, "raw_signals_total": 1}

    def fake_prefilter(**kwargs: object) -> tuple[dict[str, object] | None, int]:
        return None, 1

    def fake_core(**kwargs: object) -> tuple[dict[str, object], pd.DataFrame, pd.DataFrame, dict[str, object]]:
        candidate_id = str(kwargs["candidate_id"])
        core_calls.append(candidate_id)
        row = {
            "candidate_id": candidate_id,
            "stage": 0,
            "search_method": gtbi.EXTERNAL_SEARCH_METHOD,
            "family": "minervini_sepa",
            "score": 0.0,
            "strict_quality_pass": False,
            "adjusted_return_time_risk": 0.0,
            "train_trades": 0,
            "validation_trades": 0,
        }
        diagnostic = {
            "seconds_total": 0.2,
            "seconds_feature_build": 0.0,
            "seconds_signal": 0.0,
            "seconds_simulation": 0.1,
            "seconds_train": 0.0,
            "seconds_validation": 0.0,
            "symbols_total": 1,
            "symbols_processed": 1,
            "raw_signals_total": 1,
            "trades_total": 0,
            "train_trades": 0,
            "validation_trades": 0,
        }
        return row, pd.DataFrame(columns=gtbi.TRADE_COLUMNS), pd.DataFrame(columns=gtbi.YEARLY_COLUMNS), diagnostic

    monkeypatch.setattr(gtbi, "load_external_strategy_candidates", fake_load_candidates)
    monkeypatch.setattr(gtbi, "_load_symbol_frames", lambda path: {"AAA": frame})
    monkeypatch.setattr(gtbi.pd, "read_parquet", lambda path: spy)
    monkeypatch.setattr(gtbi, "_build_signals_by_symbol", fake_build_signal)
    monkeypatch.setattr(gtbi, "_safe_prefilter_raw_signals", fake_prefilter)
    monkeypatch.setattr(gtbi, "_evaluate_external_candidate_core", fake_core)
    pack_dir = tmp_path / "prebuilt"
    pack_dir.mkdir()
    (pack_dir / "prices.parquet").write_text("stub", encoding="utf-8")
    (pack_dir / "benchmark.parquet").write_text("stub", encoding="utf-8")

    summary = gtbi.run_external_strategy_pack_shard(
        data_lake_root=tmp_path,
        external_strategy_pack_path=tmp_path / "pack",
        output_dir=tmp_path / "out" / "job-0000",
        prebuilt_pack_dir=pack_dir,
        external_strategy_shard_id=0,
        external_strategy_limit=1,
        optimized_evaluation_mode="optimized_evaluation_v4_zero_timeout",
        enable_dedupe=True,
        candidate_timeout_seconds=1800,
        job_wall_clock_seconds=2100,
    )

    slow = pd.read_csv(tmp_path / "out" / "job-0000" / "slow_deferred_strategies_job_0000.csv")
    timeouts = pd.read_csv(tmp_path / "out" / "job-0000" / "timeout_strategies_job_0000.csv")
    leaderboard = pd.read_csv(tmp_path / "out" / "job-0000" / "leaderboard_job_0000.csv")
    manifest = pd.read_csv(tmp_path / "out" / "job-0000" / "signal_group_manifest_job_0000.csv")
    assert summary["zero_timeout_mode"] is True
    assert summary["strategies_timed_out"] == 0
    assert summary["strategies_slow_deferred"] == 0
    assert signal_calls["count"] == 1
    assert core_calls == ["slow_queue_a"]
    assert slow.empty
    assert timeouts.empty
    assert leaderboard["candidate_id"].tolist() == ["slow_queue_a"]
    assert manifest["result_status"].tolist() == ["signal_ready"]


def test_zero_timeout_runner_defers_when_job_budget_is_exhausted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_payload = _external_strategy_payload("budget_slow_a")
    second_payload = _external_strategy_payload("budget_slow_b")
    second_payload["entry_rules"]["breakout_lookback_days"] = 80
    candidates = [gtbi.external_strategy_to_config(first_payload), gtbi.external_strategy_to_config(second_payload)]
    frame = gtbi._prepare_ohlcv(_breakout_frame(180))
    spy = gtbi._prepare_ohlcv(_spy_frame(180))
    signal_calls = {"count": 0}

    def fake_load_candidates(*args: object, **kwargs: object) -> list[gtbi.ExternalStrategyCandidate]:
        return candidates

    def fake_build_signal(**kwargs: object) -> tuple[dict[str, pd.Series], dict[str, object]]:
        signal_calls["count"] += 1
        signal = pd.Series(False, index=frame.index)
        signal.iloc[70] = True
        return {"AAA": signal}, {"seconds_signal": 0.0, "symbols_processed": 1, "raw_signals_total": 1}

    monkeypatch.setattr(gtbi, "load_external_strategy_candidates", fake_load_candidates)
    monkeypatch.setattr(gtbi, "_load_symbol_frames", lambda path: {"AAA": frame})
    monkeypatch.setattr(gtbi.pd, "read_parquet", lambda path: spy)
    monkeypatch.setattr(gtbi, "_build_signals_by_symbol", fake_build_signal)
    pack_dir = tmp_path / "prebuilt"
    pack_dir.mkdir()
    (pack_dir / "prices.parquet").write_text("stub", encoding="utf-8")
    (pack_dir / "benchmark.parquet").write_text("stub", encoding="utf-8")

    summary = gtbi.run_external_strategy_pack_shard(
        data_lake_root=tmp_path,
        external_strategy_pack_path=tmp_path / "pack",
        output_dir=tmp_path / "out" / "job-0000",
        prebuilt_pack_dir=pack_dir,
        external_strategy_shard_id=0,
        external_strategy_limit=2,
        optimized_evaluation_mode="optimized_evaluation_v4_zero_timeout",
        enable_dedupe=True,
        job_wall_clock_seconds=1,
    )

    slow = pd.read_csv(tmp_path / "out" / "job-0000" / "slow_deferred_strategies_job_0000.csv")
    manifest = pd.read_csv(tmp_path / "out" / "job-0000" / "signal_group_manifest_job_0000.csv")
    assert signal_calls["count"] == 0
    assert summary["strategies_timed_out"] == 0
    assert summary["strategies_slow_deferred"] == 2
    assert summary["strategies_loaded"] == (
        summary["strategies_evaluated"]
        + summary["strategies_early_rejected"]
        + summary["strategies_slow_deferred"]
        + summary["strategies_unsupported"]
        + summary["strategies_runtime_error"]
    )
    assert summary["signal_groups_timed_out"] == 0
    assert summary["signal_groups_slow_deferred"] == 2
    assert set(slow["reason"]) == {"insufficient_job_budget"}
    assert manifest["result_status"].tolist() == ["signal_slow_deferred", "signal_slow_deferred"]


def test_event_first_runner_never_slow_defers_known_slow_signal_group(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_payload = _external_strategy_payload("event_first_a")
    second_payload = _external_strategy_payload("event_first_b")
    first_payload["concept_id"] = "macd_histogram_turnup_trend"
    second_payload["concept_id"] = "macd_histogram_turnup_trend"
    second_payload["exit_rules"]["take_profit_pct"] = 0.25
    candidates = [gtbi.external_strategy_to_config(first_payload), gtbi.external_strategy_to_config(second_payload)]
    frame = gtbi._prepare_ohlcv(_breakout_frame(180))
    spy = gtbi._prepare_ohlcv(_spy_frame(180))
    signal = pd.Series(False, index=frame.index)
    signal.iloc[[70, 90, 120]] = True
    signal_calls = {"count": 0}
    core_calls: list[str] = []

    def fake_load_candidates(*args: object, **kwargs: object) -> list[gtbi.ExternalStrategyCandidate]:
        return candidates

    def fake_build_signal(**kwargs: object) -> tuple[dict[str, pd.Series], dict[str, object]]:
        signal_calls["count"] += 1
        return {"AAA": signal}, {"seconds_signal": 0.75, "symbols_processed": 1, "raw_signals_total": 3}

    def fake_prefilter(**kwargs: object) -> tuple[dict[str, object] | None, int]:
        return None, 3

    def fake_core(**kwargs: object) -> tuple[dict[str, object], pd.DataFrame, pd.DataFrame, dict[str, object]]:
        candidate_id = str(kwargs["candidate_id"])
        core_calls.append(candidate_id)
        assert kwargs.get("deadline") is not None
        assert kwargs.get("precomputed_signals_by_symbol") is not None
        row = {
            "candidate_id": candidate_id,
            "stage": 0,
            "search_method": gtbi.EXTERNAL_SEARCH_METHOD,
            "family": "minervini_sepa",
            "score": 0.0,
            "strict_quality_pass": False,
            "adjusted_return_time_risk": 0.0,
            "train_trades": 0,
            "validation_trades": 0,
        }
        diagnostic = {
            "seconds_total": 0.2,
            "seconds_feature_build": 0.0,
            "seconds_signal": 0.0,
            "seconds_simulation": 0.1,
            "seconds_train": 0.0,
            "seconds_validation": 0.0,
            "symbols_total": 1,
            "symbols_processed": 1,
            "raw_signals_total": 3,
            "trades_total": 0,
            "train_trades": 0,
            "validation_trades": 0,
        }
        return row, pd.DataFrame(columns=gtbi.TRADE_COLUMNS), pd.DataFrame(columns=gtbi.YEARLY_COLUMNS), diagnostic

    monkeypatch.setattr(gtbi, "load_external_strategy_candidates", fake_load_candidates)
    monkeypatch.setattr(gtbi, "_load_symbol_frames", lambda path: {"AAA": frame})
    monkeypatch.setattr(gtbi.pd, "read_parquet", lambda path: spy)
    monkeypatch.setattr(gtbi, "_build_signals_by_symbol", fake_build_signal)
    monkeypatch.setattr(gtbi, "_safe_prefilter_raw_signals", fake_prefilter)
    monkeypatch.setattr(gtbi, "_evaluate_external_candidate_core", fake_core)
    pack_dir = tmp_path / "prebuilt"
    pack_dir.mkdir()
    (pack_dir / "prices.parquet").write_text("stub", encoding="utf-8")
    (pack_dir / "benchmark.parquet").write_text("stub", encoding="utf-8")

    summary = gtbi.run_external_strategy_pack_shard(
        data_lake_root=tmp_path,
        external_strategy_pack_path=tmp_path / "pack",
        output_dir=tmp_path / "out" / "job-0000",
        prebuilt_pack_dir=pack_dir,
        external_strategy_shard_id=0,
        external_strategy_limit=2,
        optimized_evaluation_mode="optimized_evaluation_v5_event_first",
        enable_dedupe=True,
        candidate_timeout_seconds=300,
        job_wall_clock_seconds=300,
    )

    out = tmp_path / "out" / "job-0000"
    slow = pd.read_csv(out / "slow_deferred_strategies_job_0000.csv")
    timeouts = pd.read_csv(out / "timeout_strategies_job_0000.csv")
    manifest = pd.read_csv(out / "signal_group_manifest_job_0000.csv")
    compiled = pd.read_csv(out / "compiled_signal_plan_job_0000.csv")
    event_manifest = pd.read_csv(out / "event_store_manifest_job_0000.csv")
    exits = pd.read_csv(out / "exit_group_manifest_job_0000.csv")
    cost_profile = json.loads((out / "cost_profile_v5_job_0000.json").read_text(encoding="utf-8"))
    assert signal_calls["count"] == 1
    assert core_calls == ["event_first_a", "event_first_b"]
    assert summary["zero_timeout_mode"] is True
    assert summary["zero_slow_deferred_mode"] is True
    assert summary["strategies_timed_out"] == 0
    assert summary["strategies_slow_deferred"] == 0
    assert summary["signal_groups_slow_deferred"] == 0
    assert slow.empty
    assert timeouts.empty
    assert manifest["result_status"].tolist() == ["signal_ready"]
    assert compiled["uses_event_store"].astype(bool).tolist() == [True]
    assert event_manifest["events_total"].tolist() == [3]
    assert set(exits["strategy_id"]) == {"event_first_a", "event_first_b"}
    assert cost_profile["optimized_evaluation_mode"] == "optimized_evaluation_v5_event_first"
    assert cost_profile["signal_groups_loaded"] == 1


def test_event_first_runner_passes_cooperative_deadline_to_signal_builder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _external_strategy_payload("event_first_deadline")
    payload["concept_id"] = "moving_average_timing_cross"
    candidates = [gtbi.external_strategy_to_config(payload)]
    frame = gtbi._prepare_ohlcv(_breakout_frame(180))
    spy = gtbi._prepare_ohlcv(_spy_frame(180))
    captured_deadlines: list[float | None] = []

    def fake_load_candidates(*args: object, **kwargs: object) -> list[gtbi.ExternalStrategyCandidate]:
        return candidates

    def fake_build_signal(**kwargs: object) -> tuple[dict[str, pd.Series], dict[str, object]]:
        deadline = kwargs.get("deadline")
        captured_deadlines.append(deadline if deadline is None else float(deadline))
        signal = pd.Series(False, index=frame.index)
        signal.iloc[[70, 90, 120]] = True
        return {"AAA": signal}, {"seconds_signal": 0.1, "symbols_processed": 1, "raw_signals_total": 3}

    def fake_prefilter(**kwargs: object) -> tuple[dict[str, object], int]:
        return (
            {
                "reason": "raw_signal_yearly_trades_lt_100",
                "split": "validation",
                "year": 2011,
                "actual": 3,
                "threshold": 100,
                "stage": "safe_prefilter",
            },
            3,
        )

    monkeypatch.setattr(gtbi, "load_external_strategy_candidates", fake_load_candidates)
    monkeypatch.setattr(gtbi, "_load_symbol_frames", lambda path: {"AAA": frame})
    monkeypatch.setattr(gtbi.pd, "read_parquet", lambda path: spy)
    monkeypatch.setattr(gtbi, "_build_signals_by_symbol", fake_build_signal)
    monkeypatch.setattr(gtbi, "_safe_prefilter_raw_signals", fake_prefilter)
    pack_dir = tmp_path / "prebuilt"
    pack_dir.mkdir()
    (pack_dir / "prices.parquet").write_text("stub", encoding="utf-8")
    (pack_dir / "benchmark.parquet").write_text("stub", encoding="utf-8")

    gtbi.run_external_strategy_pack_shard(
        data_lake_root=tmp_path,
        external_strategy_pack_path=tmp_path / "pack",
        output_dir=tmp_path / "out" / "job-0000",
        prebuilt_pack_dir=pack_dir,
        external_strategy_shard_id=0,
        external_strategy_limit=1,
        optimized_evaluation_mode="optimized_evaluation_v5_event_first",
        enable_dedupe=True,
        candidate_timeout_seconds=300,
        job_wall_clock_seconds=300,
    )

    assert captured_deadlines
    assert captured_deadlines[0] is not None
    assert float(captured_deadlines[0]) > gtbi.time.perf_counter()


def test_event_first_signal_timeout_is_reported_without_slow_deferred(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _external_strategy_payload("event_first_signal_timeout")
    payload["concept_id"] = "moving_average_timing_cross"
    candidates = [gtbi.external_strategy_to_config(payload)]
    frame = gtbi._prepare_ohlcv(_breakout_frame(180))
    spy = gtbi._prepare_ohlcv(_spy_frame(180))

    def fake_load_candidates(*args: object, **kwargs: object) -> list[gtbi.ExternalStrategyCandidate]:
        return candidates

    def fake_build_signal(**kwargs: object) -> tuple[dict[str, pd.Series], dict[str, object]]:
        raise gtbi.CandidateEvaluationTimeout("forced event-first signal timeout")

    monkeypatch.setattr(gtbi, "load_external_strategy_candidates", fake_load_candidates)
    monkeypatch.setattr(gtbi, "_load_symbol_frames", lambda path: {"AAA": frame})
    monkeypatch.setattr(gtbi.pd, "read_parquet", lambda path: spy)
    monkeypatch.setattr(gtbi, "_build_signals_by_symbol", fake_build_signal)
    pack_dir = tmp_path / "prebuilt"
    pack_dir.mkdir()
    (pack_dir / "prices.parquet").write_text("stub", encoding="utf-8")
    (pack_dir / "benchmark.parquet").write_text("stub", encoding="utf-8")

    summary = gtbi.run_external_strategy_pack_shard(
        data_lake_root=tmp_path,
        external_strategy_pack_path=tmp_path / "pack",
        output_dir=tmp_path / "out" / "job-0000",
        prebuilt_pack_dir=pack_dir,
        external_strategy_shard_id=0,
        external_strategy_limit=1,
        optimized_evaluation_mode="optimized_evaluation_v5_event_first",
        enable_dedupe=True,
        candidate_timeout_seconds=300,
        job_wall_clock_seconds=300,
    )

    out = tmp_path / "out" / "job-0000"
    slow = pd.read_csv(out / "slow_deferred_strategies_job_0000.csv")
    timeouts = pd.read_csv(out / "timeout_strategies_job_0000.csv")
    manifest = pd.read_csv(out / "signal_group_manifest_job_0000.csv")
    assert slow.empty
    assert len(timeouts) == 1
    assert summary["strategies_slow_deferred"] == 0
    assert summary["signal_groups_slow_deferred"] == 0
    assert summary["signal_groups_timed_out"] == 1
    assert manifest["result_status"].tolist() == ["signal_timeout"]


def test_event_first_exit_hash_uses_only_effective_exit_rules() -> None:
    first_payload = _external_strategy_payload("exit_hash_a")
    second_payload = _external_strategy_payload("exit_hash_b")
    second_payload["concept_id"] = "q_stair_step_reclaim"
    first = gtbi.external_strategy_to_config(first_payload)
    second = gtbi.external_strategy_to_config(second_payload)

    assert gtbi.exit_external_strategy_hash(first) == gtbi.exit_external_strategy_hash(second)

    changed_payload = _external_strategy_payload("exit_hash_c")
    changed_payload["exit_rules"]["take_profit_pct"] = 22.0
    changed = gtbi.external_strategy_to_config(changed_payload)

    assert gtbi.exit_external_strategy_hash(first) != gtbi.exit_external_strategy_hash(changed)


def test_signal_first_runner_reserves_time_for_exit_simulation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_payload = _external_strategy_payload("ready_signal_group_a")
    second_payload = _external_strategy_payload("deferred_signal_group_b")
    second_payload["entry_rules"]["breakout_lookback_days"] = 80
    candidates = [gtbi.external_strategy_to_config(first_payload), gtbi.external_strategy_to_config(second_payload)]
    frame = gtbi._prepare_ohlcv(_breakout_frame(180))
    spy = gtbi._prepare_ohlcv(_spy_frame(180))
    signal = pd.Series(False, index=frame.index)
    signal.iloc[70] = True
    signal_calls = {"count": 0}
    core_calls: list[str] = []

    def fake_load_candidates(*args: object, **kwargs: object) -> list[gtbi.ExternalStrategyCandidate]:
        return candidates

    def fake_build_signal(**kwargs: object) -> tuple[dict[str, pd.Series], dict[str, object]]:
        signal_calls["count"] += 1
        return {"AAA": signal}, {"seconds_signal": 1.0, "symbols_processed": 1, "raw_signals_total": 1}

    def fake_prefilter(**kwargs: object) -> tuple[dict[str, object] | None, int]:
        return None, 1

    def fake_core(**kwargs: object) -> tuple[dict[str, object], pd.DataFrame, pd.DataFrame, dict[str, object]]:
        candidate_id = str(kwargs["candidate_id"])
        core_calls.append(candidate_id)
        row = {
            "candidate_id": candidate_id,
            "stage": 0,
            "search_method": gtbi.EXTERNAL_SEARCH_METHOD,
            "family": "minervini_sepa",
            "score": 0.0,
            "strict_quality_pass": False,
            "adjusted_return_time_risk": 0.0,
            "train_trades": 0,
            "validation_trades": 0,
        }
        diagnostic = {
            "seconds_total": 0.2,
            "seconds_feature_build": 0.0,
            "seconds_signal": 0.0,
            "seconds_simulation": 0.1,
            "seconds_train": 0.0,
            "seconds_validation": 0.0,
            "symbols_total": 1,
            "symbols_processed": 1,
            "raw_signals_total": 1,
            "trades_total": 0,
            "train_trades": 0,
            "validation_trades": 0,
        }
        return row, pd.DataFrame(columns=gtbi.TRADE_COLUMNS), pd.DataFrame(columns=gtbi.YEARLY_COLUMNS), diagnostic

    monkeypatch.setattr(gtbi, "load_external_strategy_candidates", fake_load_candidates)
    monkeypatch.setattr(gtbi, "_load_symbol_frames", lambda path: {"AAA": frame})
    monkeypatch.setattr(gtbi.pd, "read_parquet", lambda path: spy)
    monkeypatch.setattr(gtbi, "_build_signals_by_symbol", fake_build_signal)
    monkeypatch.setattr(gtbi, "_safe_prefilter_raw_signals", fake_prefilter)
    monkeypatch.setattr(gtbi, "_evaluate_external_candidate_core", fake_core)
    pack_dir = tmp_path / "prebuilt"
    pack_dir.mkdir()
    (pack_dir / "prices.parquet").write_text("stub", encoding="utf-8")
    (pack_dir / "benchmark.parquet").write_text("stub", encoding="utf-8")

    summary = gtbi.run_external_strategy_pack_shard(
        data_lake_root=tmp_path,
        external_strategy_pack_path=tmp_path / "pack",
        output_dir=tmp_path / "out" / "job-0000",
        prebuilt_pack_dir=pack_dir,
        external_strategy_shard_id=0,
        external_strategy_limit=2,
        optimized_evaluation_mode="optimized_evaluation_v3_signal_first",
        enable_dedupe=True,
        job_wall_clock_seconds=300,
    )

    manifest = pd.read_csv(tmp_path / "out" / "job-0000" / "signal_group_manifest_job_0000.csv")
    timeouts = pd.read_csv(tmp_path / "out" / "job-0000" / "timeout_strategies_job_0000.csv")
    leaderboard = pd.read_csv(tmp_path / "out" / "job-0000" / "leaderboard_job_0000.csv")
    assert signal_calls["count"] == 1
    assert core_calls == ["ready_signal_group_a"]
    assert summary["signal_groups_evaluated"] == 1
    assert summary["signal_groups_timed_out"] == 1
    assert summary["strategies_evaluated"] == 1
    assert leaderboard["candidate_id"].tolist() == ["ready_signal_group_a"]
    assert timeouts["strategy_id"].tolist() == ["deferred_signal_group_b"]
    assert manifest["result_status"].tolist() == ["signal_ready", "signal_timeout"]


def test_compact_signal_events_roundtrip_preserves_signal_positions(tmp_path: Path) -> None:
    frame = gtbi._prepare_ohlcv(_breakout_frame(180))
    signal = pd.Series(False, index=frame.index)
    signal.iloc[[12, 70, 121]] = True

    path = tmp_path / "signal_events_job_0000.npz"
    gtbi._write_compact_signal_events(
        path,
        signal_events={"hash_a": {"AAA": signal}},
        symbol_frames={"AAA": frame},
    )
    loaded = gtbi._load_compact_signal_events(path, symbol_frames={"AAA": frame})

    assert list(loaded) == ["hash_a"]
    pd.testing.assert_series_equal(loaded["hash_a"]["AAA"], signal)


def test_signal_first_split_phase_writes_events_and_exits_reuse_them(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_payload = _external_strategy_payload("split_signal_a")
    second_payload = _external_strategy_payload("split_signal_b")
    second_payload["exit_rules"]["take_profit_pct"] = 0.25
    candidates = [gtbi.external_strategy_to_config(first_payload), gtbi.external_strategy_to_config(second_payload)]
    frame = gtbi._prepare_ohlcv(_breakout_frame(180))
    spy = gtbi._prepare_ohlcv(_spy_frame(180))
    signal = pd.Series(False, index=frame.index)
    signal.iloc[70] = True
    signal_calls = {"count": 0}
    core_precomputed: list[bool] = []

    def fake_load_candidates(*args: object, **kwargs: object) -> list[gtbi.ExternalStrategyCandidate]:
        return candidates

    def fake_build_signal(**kwargs: object) -> tuple[dict[str, pd.Series], dict[str, object]]:
        signal_calls["count"] += 1
        return {"AAA": signal}, {"seconds_signal": 1.25, "symbols_processed": 1, "raw_signals_total": 1}

    def fake_prefilter(**kwargs: object) -> tuple[dict[str, object] | None, int]:
        return None, 1

    def fake_core(**kwargs: object) -> tuple[dict[str, object], pd.DataFrame, pd.DataFrame, dict[str, object]]:
        core_precomputed.append(kwargs.get("precomputed_signals_by_symbol") is not None)
        candidate_id = str(kwargs["candidate_id"])
        row = {
            "candidate_id": candidate_id,
            "stage": 0,
            "search_method": gtbi.EXTERNAL_SEARCH_METHOD,
            "family": "minervini_sepa",
            "score": 0.0,
            "strict_quality_pass": False,
            "adjusted_return_time_risk": 0.0,
            "train_trades": 0,
            "validation_trades": 0,
        }
        diagnostic = {
            "seconds_total": 0.2,
            "seconds_feature_build": 0.0,
            "seconds_signal": 0.0,
            "seconds_simulation": 0.1,
            "seconds_train": 0.0,
            "seconds_validation": 0.0,
            "symbols_total": 1,
            "symbols_processed": 1,
            "raw_signals_total": 1,
            "trades_total": 0,
            "train_trades": 0,
            "validation_trades": 0,
        }
        return row, pd.DataFrame(columns=gtbi.TRADE_COLUMNS), pd.DataFrame(columns=gtbi.YEARLY_COLUMNS), diagnostic

    monkeypatch.setattr(gtbi, "load_external_strategy_candidates", fake_load_candidates)
    monkeypatch.setattr(gtbi, "_load_symbol_frames", lambda path: {"AAA": frame})
    monkeypatch.setattr(gtbi.pd, "read_parquet", lambda path: spy)
    monkeypatch.setattr(gtbi, "_build_signals_by_symbol", fake_build_signal)
    monkeypatch.setattr(gtbi, "_safe_prefilter_raw_signals", fake_prefilter)
    monkeypatch.setattr(gtbi, "_evaluate_external_candidate_core", fake_core)
    pack_dir = tmp_path / "prebuilt"
    pack_dir.mkdir()
    (pack_dir / "prices.parquet").write_text("stub", encoding="utf-8")
    (pack_dir / "benchmark.parquet").write_text("stub", encoding="utf-8")

    signal_summary = gtbi.run_external_strategy_pack_shard(
        data_lake_root=tmp_path,
        external_strategy_pack_path=tmp_path / "pack",
        output_dir=tmp_path / "signals" / "job-0000",
        prebuilt_pack_dir=pack_dir,
        external_strategy_shard_id=0,
        external_strategy_limit=2,
        optimized_evaluation_mode="optimized_evaluation_v3_signal_first",
        signal_first_phase="signals",
        enable_dedupe=True,
        job_wall_clock_seconds=300,
    )
    assert signal_summary["signal_first_phase"] == "signals"
    assert signal_summary["signal_groups_evaluated"] == 1
    assert signal_summary["strategies_evaluated"] == 0
    assert signal_calls["count"] == 1
    assert (tmp_path / "signals" / "job-0000" / "signal_events_job_0000.npz").exists()
    assert (tmp_path / "signals" / "job-0000" / "signal_ready_groups_job_0000.jsonl").exists()

    def fail_build_signal(**kwargs: object) -> tuple[dict[str, pd.Series], dict[str, object]]:
        raise AssertionError("exit phase must consume compact signal events")

    monkeypatch.setattr(gtbi, "_build_signals_by_symbol", fail_build_signal)
    exit_summary = gtbi.run_external_strategy_pack_shard(
        data_lake_root=tmp_path,
        external_strategy_pack_path=tmp_path / "pack",
        output_dir=tmp_path / "out" / "job-0000",
        prebuilt_pack_dir=pack_dir,
        external_strategy_shard_id=0,
        external_strategy_limit=2,
        optimized_evaluation_mode="optimized_evaluation_v3_signal_first",
        signal_first_phase="exits",
        signal_events_dir=tmp_path / "signals" / "job-0000",
        enable_dedupe=True,
        job_wall_clock_seconds=300,
    )

    leaderboard = pd.read_csv(tmp_path / "out" / "job-0000" / "leaderboard_job_0000.csv")
    assert exit_summary["signal_first_phase"] == "exits"
    assert exit_summary["signal_groups_loaded"] == 1
    assert exit_summary["strategies_loaded"] == 2
    assert exit_summary["strategies_evaluated"] == 2
    assert core_precomputed == [True, True]
    assert leaderboard["candidate_id"].tolist() == ["split_signal_a", "split_signal_b"]


def test_safe_prefilter_rejects_only_mathematically_impossible_signal_counts() -> None:
    idx = pd.date_range("2003-01-01", "2020-12-31", freq="B")
    close = np.linspace(50.0, 150.0, len(idx))
    frame = pd.DataFrame(
        {
            "date": idx,
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "adj_close": close,
            "volume": np.full(len(idx), 100_000.0),
            "symbol": "AAA",
        }
    )
    sparse_signal = pd.Series(False, index=idx)
    sparse_signal.loc[pd.date_range("2015-01-02", periods=10, freq="20B")] = True
    reject, _ = gtbi._safe_prefilter_raw_signals(
        signals_by_symbol={"AAA": sparse_signal},
        symbol_frames={"AAA": frame},
        config=gtbi.IndicatorConfig(max_holding_days=5),
        validation_start="2011-01-01",
        validation_end="2020-12-31",
    )
    assert reject is not None
    assert reject["reason"] == "raw_signal_yearly_trades_lt_100"

    dense_signal = pd.Series(True, index=idx)
    reject, _ = gtbi._safe_prefilter_raw_signals(
        signals_by_symbol={"AAA": dense_signal},
        symbol_frames={"AAA": frame},
        config=gtbi.IndicatorConfig(max_holding_days=5),
        validation_start="2011-01-01",
        validation_end="2020-12-31",
    )
    assert reject is None


def test_signal_year_counts_uses_numpy_dates_without_pandas_index_slice() -> None:
    idx = pd.date_range("2010-12-20", "2012-01-10", freq="B")
    close = np.linspace(50.0, 75.0, len(idx))
    frame = pd.DataFrame(
        {
            "date": idx,
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "adj_close": close,
            "volume": np.full(len(idx), 100_000.0),
            "symbol": "AAA",
        }
    )
    signal = pd.Series(False, index=idx)
    signal.loc[pd.Timestamp("2010-12-20")] = True
    signal.loc[pd.Timestamp("2011-01-03")] = True
    signal.loc[pd.Timestamp("2011-12-30")] = True
    signal.loc[pd.Timestamp("2012-01-10")] = True

    counts = gtbi._signal_year_counts_for_possible_exits(
        signals_by_symbol={"AAA": signal.sample(frac=1.0, random_state=7).sort_index()},
        symbol_frames={"AAA": frame},
        config=gtbi.IndicatorConfig(max_holding_days=5),
        years=range(2011, 2013),
    )

    assert counts == {2011: 3, 2012: 1}


def test_optimized_candidate_prefilters_if_deadline_hits_after_final_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    idx = pd.date_range("2003-01-01", "2020-12-31", freq="B")
    close = np.linspace(50.0, 150.0, len(idx))
    frame = gtbi._prepare_ohlcv(
        pd.DataFrame(
            {
                "date": idx,
                "open": close,
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
                "adj_close": close,
                "volume": np.full(len(idx), 100_000.0),
                "symbol": "AAA",
            }
        )
    )
    spy = gtbi._prepare_ohlcv(_spy_frame(len(idx)))

    def slow_empty_signal(prices: pd.DataFrame, benchmark_prices: pd.DataFrame, config: gtbi.IndicatorConfig) -> pd.Series:
        del benchmark_prices, config
        time.sleep(0.02)
        prepared = gtbi._prepare_ohlcv(prices)
        return pd.Series(False, index=prepared.index)

    monkeypatch.setattr(gtbi, "entry_signal", slow_empty_signal)
    with pytest.raises(gtbi.EarlyRejectedStrategy) as raised:
        gtbi.evaluate_candidate_optimized(
            config=gtbi.IndicatorConfig(max_holding_days=5),
            candidate_id="deadline-final-signal",
            stage=0,
            symbol_frames={"AAA": frame},
            benchmark_prices=spy,
            validation_start="2011-01-01",
            validation_end="2020-12-31",
            deadline=time.perf_counter() + 0.01,
        )

    assert raised.value.reason == "raw_signal_yearly_trades_lt_100"
    assert raised.value.symbols_processed == 1


def test_external_pack_real_manifest_has_360_shards_and_72000_strategies() -> None:
    pack = Path("scripts/strategy_packs/gtbi_research_broad_72000")
    manifest = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["total_strategies"] == 72_000
    assert manifest["shard_count"] == 360
    assert manifest["strategies_per_shard"] == 200
    assert len(list((pack / "shards").glob("shard_*.jsonl"))) == 360
    assert len(gtbi.load_external_strategy_candidates(pack, shard_id=0, limit=1)) == 1


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


def test_external_merge_accepts_job_artifacts_and_reports_job_counts(tmp_path: Path) -> None:
    job = tmp_path / "downloaded" / "gtbi-external-pack-job-0000"
    job.mkdir(parents=True)
    (job / "summary_job_0000.json").write_text(
        json.dumps(
            {
                "strategies_loaded": 40,
                "strategies_evaluated": 39,
                "strategies_unsupported": 1,
                "strategies_failed": 0,
                "strategies_timed_out": 0,
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
    ).to_csv(job / "leaderboard_job_0000.csv", index=False)
    pd.DataFrame(columns=["candidate_id", "adjusted_return_time_risk"]).to_csv(
        job / "filtered_leaderboard_job_0000.csv",
        index=False,
    )
    pd.DataFrame(columns=gtbi.YEARLY_COLUMNS).to_csv(job / "yearly_trade_performance_job_0000.csv", index=False)
    pd.DataFrame(columns=gtbi.TRADE_COLUMNS).to_csv(job / "top_trades_sample_job_0000.csv", index=False)
    pd.DataFrame(columns=["strategy_id", "shard_id", "slot_in_shard", "unsupported_rules", "reason"]).to_csv(
        job / "unsupported_strategies_job_0000.csv",
        index=False,
    )
    pd.DataFrame(
        [{"strategy_id": "slow", "reason": "CandidateEvaluationTimeout", "seconds_until_timeout": 300.0}]
    ).to_csv(job / "timeout_strategies_job_0000.csv", index=False)
    pd.DataFrame(
        [{"strategy_id": "early", "reason": "raw_signal_yearly_trades_lt_100", "stage": "safe_prefilter"}]
    ).to_csv(job / "early_rejected_strategies_job_0000.csv", index=False)
    pd.DataFrame(columns=gtbi.RUNTIME_ERROR_COLUMNS).to_csv(job / "runtime_errors_job_0000.csv", index=False)
    pd.DataFrame(
        [{"strategy_id": "c1", "result_status": "evaluated", "seconds_total": 1.25, "timeout": False}]
    ).to_csv(job / "timing_diagnostics_job_0000.csv", index=False)
    pd.DataFrame(
        [{"strategy_id": "c1", "canonical_hash": "abc", "canonical_strategy_id": "c1", "deduped": False}]
    ).to_csv(job / "dedupe_map_job_0000.csv", index=False)
    pd.DataFrame(
        [{"job_id": "0000", "strategy_id": "c1", "canonical_hash": "abc", "cost_score": 1.0}]
    ).to_csv(job / "job_manifest_job_0000.csv", index=False)
    (job / "top_indicator_rules_job_0000.jsonl").write_text("", encoding="utf-8")

    summary = gtbi.merge_external_strategy_pack_outputs(
        shards_root=tmp_path / "downloaded",
        output_dir=tmp_path / "final",
        total_strategies_requested=800,
        total_shards_requested=360,
        total_jobs_requested=20,
        candidate_count_per_job=40,
        locked_start="2021-01-01",
        train_end="2010-12-31",
        validation_start="2011-01-01",
        validation_end="2020-12-31",
    )

    assert summary["total_jobs_requested"] == 20
    assert summary["total_jobs_completed"] == 1
    assert summary["candidate_count_per_job"] == 40
    assert summary["total_strategies_requested"] == 800
    assert summary["total_strategies_loaded"] == 40
    assert summary["total_strategies_timed_out"] == 0
    for name in (
        "timeout_strategies.csv",
        "early_rejected_strategies.csv",
        "runtime_errors.csv",
        "timing_diagnostics.csv",
        "dedupe_map.csv",
        "job_manifest.csv",
    ):
        assert (tmp_path / "final" / name).exists()


def test_external_merge_summary_uses_best_adjusted_return_time_risk(tmp_path: Path) -> None:
    specs = [
        ("0000", "best_score_only", 10.0, 0.10),
        ("0001", "best_adjusted", 1.0, 0.90),
    ]
    for job_id, candidate_id, score, adjusted in specs:
        job = tmp_path / "downloaded" / f"gtbi-external-pack-job-{job_id}"
        job.mkdir(parents=True)
        (job / f"summary_job_{job_id}.json").write_text(
            json.dumps(
                {
                    "strategies_loaded": 1,
                    "strategies_evaluated": 1,
                    "strategies_unsupported": 0,
                    "strategies_failed": 0,
                    "strategies_timed_out": 0,
                }
            ),
            encoding="utf-8",
        )
        pd.DataFrame(
            [
                {
                    "candidate_id": candidate_id,
                    "score": score,
                    "adjusted_return_time_risk": adjusted,
                    "validation_median_trade_return_pct": adjusted,
                    "family": "minervini_sepa",
                    "concept_id": "concept_a",
                    "market_overlay_id": "market_a",
                }
            ]
        ).to_csv(job / f"leaderboard_job_{job_id}.csv", index=False)
        pd.DataFrame(columns=["candidate_id", "adjusted_return_time_risk"]).to_csv(
            job / f"filtered_leaderboard_job_{job_id}.csv",
            index=False,
        )

    summary = gtbi.merge_external_strategy_pack_outputs(
        shards_root=tmp_path / "downloaded",
        output_dir=tmp_path / "final",
        total_strategies_requested=2,
        total_shards_requested=360,
        total_jobs_requested=2,
        candidate_count_per_job=1,
    )

    assert list(pd.read_csv(tmp_path / "final" / "leaderboard.csv")["candidate_id"]) == [
        "best_score_only",
        "best_adjusted",
    ]
    assert summary["best_candidate_id"] == "best_adjusted"
    assert summary["best_adjusted_return_time_risk"] == pytest.approx(0.90)


def test_external_merge_ignores_empty_job_csvs_and_counts_timeouts(tmp_path: Path) -> None:
    job = tmp_path / "downloaded" / "gtbi-external-pack-job-0007"
    job.mkdir(parents=True)
    (job / "summary_job_0007.json").write_text(
        json.dumps(
            {
                "strategies_loaded": 10,
                "strategies_evaluated": 0,
                "strategies_unsupported": 0,
                "strategies_failed": 10,
                "strategies_timed_out": 10,
            }
        ),
        encoding="utf-8",
    )
    for name in (
        "leaderboard_job_0007.csv",
        "filtered_leaderboard_job_0007.csv",
        "yearly_trade_performance_job_0007.csv",
        "top_trades_sample_job_0007.csv",
    ):
        (job / name).write_text("", encoding="utf-8")
    pd.DataFrame(
        [
            {
                "strategy_id": "slow",
                "shard_id": 0,
                "slot_in_shard": 70,
                "unsupported_rules": "",
                "reason": "CandidateEvaluationTimeout('candidate evaluation exceeded 300 seconds')",
            }
        ]
    ).to_csv(job / "unsupported_strategies_job_0007.csv", index=False)
    (job / "top_indicator_rules_job_0007.jsonl").write_text("", encoding="utf-8")

    summary = gtbi.merge_external_strategy_pack_outputs(
        shards_root=tmp_path / "downloaded",
        output_dir=tmp_path / "final",
        total_strategies_requested=200,
        total_shards_requested=360,
        total_jobs_requested=20,
        candidate_count_per_job=10,
    )

    assert summary["total_jobs_completed"] == 1
    assert summary["total_strategies_evaluated"] == 0
    assert summary["total_strategies_failed"] == 10
    assert summary["total_strategies_timed_out"] == 10
    assert (tmp_path / "final" / "leaderboard.csv").exists()


def test_external_block_merge_sums_block_artifacts(tmp_path: Path) -> None:
    for block_id, candidate in enumerate(("a", "b")):
        block = tmp_path / "downloaded" / f"gtbi-external-pack-block-{block_id}-results"
        block.mkdir(parents=True)
        (block / "summary.json").write_text(
            json.dumps(
                {
                    "total_jobs_completed": 2,
                    "total_strategies_loaded": 20,
                    "total_strategies_evaluated": 18,
                    "total_strategies_early_rejected": 1,
                    "total_strategies_timed_out": 1,
                    "total_strategies_runtime_error": 0,
                    "total_strategies_failed": 1,
                    "total_strategies_unsupported": 0,
                    "total_strategies_deduped": 0,
                    "candidate_timeout_seconds": 300,
                    "optimized_evaluation_mode": "optimized_evaluation_v2",
                }
            ),
            encoding="utf-8",
        )
        pd.DataFrame(
            [
                {
                    "candidate_id": candidate,
                    "score": float(block_id),
                    "adjusted_return_time_risk": 0.1 + block_id,
                    "family": "oneil_canslim",
                    "concept_id": "concept",
                    "market_overlay_id": "market",
                }
            ]
        ).to_csv(block / "leaderboard.csv", index=False)
        pd.DataFrame(columns=["candidate_id", "adjusted_return_time_risk"]).to_csv(block / "filtered_leaderboard.csv", index=False)
        pd.DataFrame(columns=gtbi.YEARLY_COLUMNS).to_csv(block / "yearly_trade_performance.csv", index=False)
        pd.DataFrame(columns=gtbi.TRADE_COLUMNS).to_csv(block / "top_trades_sample.csv", index=False)
        pd.DataFrame(columns=gtbi.UNSUPPORTED_COLUMNS).to_csv(block / "unsupported_strategies.csv", index=False)
        pd.DataFrame(columns=gtbi.TIMEOUT_COLUMNS).to_csv(block / "timeout_strategies.csv", index=False)
        pd.DataFrame(columns=gtbi.EARLY_REJECT_COLUMNS).to_csv(block / "early_rejected_strategies.csv", index=False)
        pd.DataFrame(columns=gtbi.RUNTIME_ERROR_COLUMNS).to_csv(block / "runtime_errors.csv", index=False)
        pd.DataFrame(columns=gtbi.TIMING_DIAGNOSTIC_COLUMNS).to_csv(block / "timing_diagnostics.csv", index=False)
        pd.DataFrame(columns=gtbi.DEDUPE_MAP_COLUMNS).to_csv(block / "dedupe_map.csv", index=False)
        pd.DataFrame(columns=gtbi.JOB_MANIFEST_COLUMNS).to_csv(block / "job_manifest.csv", index=False)
        (block / "top_indicator_rules.jsonl").write_text("", encoding="utf-8")

    summary = gtbi.merge_external_strategy_pack_outputs(
        shards_root=tmp_path / "downloaded",
        output_dir=tmp_path / "final",
        total_strategies_requested=40,
        total_shards_requested=360,
        total_jobs_requested=4,
        candidate_count_per_job=10,
    )

    assert summary["total_jobs_completed"] == 4
    assert summary["total_strategies_loaded"] == 40
    assert summary["total_strategies_evaluated"] == 36
    assert summary["total_strategies_early_rejected"] == 2
    assert summary["total_strategies_timed_out"] == 2
    assert summary["optimized_evaluation_mode"] == "optimized_evaluation_v2"
    assert list(pd.read_csv(tmp_path / "final" / "leaderboard.csv")["candidate_id"]) == ["b", "a"]


def test_external_merge_sums_zero_timeout_slow_deferred_outputs(tmp_path: Path) -> None:
    job = tmp_path / "downloaded" / "gtbi-external-pack-job-0000"
    job.mkdir(parents=True)
    (job / "summary_job_0000.json").write_text(
        json.dumps(
            {
                "strategies_loaded": 10,
                "strategies_evaluated": 4,
                "strategies_early_rejected": 2,
                "strategies_slow_deferred": 4,
                "strategies_timed_out": 0,
                "strategies_unsupported": 0,
                "strategies_runtime_error": 0,
                "strategies_failed": 0,
                "signal_groups_loaded": 5,
                "signal_groups_slow_deferred": 2,
                "candidate_timeout_seconds": 300,
                "optimized_evaluation_mode": "optimized_evaluation_v4_zero_timeout",
                "zero_timeout_mode": True,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    pd.DataFrame(
        [
            {
                "strategy_id": "slow_a",
                "reason": "known_slow_concept",
                "concept": "macd_histogram_turnup_trend",
                "signal_hash": "sig",
            }
        ]
    ).to_csv(job / "slow_deferred_strategies_job_0000.csv", index=False)
    pd.DataFrame(
        [
            {
                "job_id": "0000",
                "signal_hash": "sig",
                "strategy_ids": "slow_a;slow_b",
                "concept": "macd_histogram_turnup_trend",
                "family": "minervini_sepa",
                "estimated_cost": 9.0,
                "reason": "known_slow_concept",
                "suggested_timeout_seconds": 1800,
                "suggested_strategies_per_job": 1,
            }
        ]
    ).to_csv(job / "slow_queue_manifest_job_0000.csv", index=False)

    summary = gtbi.merge_external_strategy_pack_outputs(
        shards_root=tmp_path / "downloaded",
        output_dir=tmp_path / "final",
        total_strategies_requested=10,
        total_shards_requested=1,
        total_jobs_requested=1,
        candidate_count_per_job=10,
    )

    slow = pd.read_csv(tmp_path / "final" / "slow_deferred_strategies.csv")
    queue = pd.read_csv(tmp_path / "final" / "slow_queue_manifest.csv")
    assert summary["zero_timeout_mode"] is True
    assert summary["total_strategies_timed_out"] == 0
    assert summary["total_strategies_slow_deferred"] == 4
    assert summary["total_signal_groups_slow_deferred"] == 2
    assert len(slow) == 1
    assert queue["suggested_timeout_seconds"].tolist() == [1800]


def test_external_merge_preserves_event_first_artifacts(tmp_path: Path) -> None:
    job = tmp_path / "downloaded" / "gtbi-external-pack-job-0000"
    job.mkdir(parents=True)
    (job / "summary_job_0000.json").write_text(
        json.dumps(
            {
                "strategies_loaded": 2,
                "strategies_evaluated": 1,
                "strategies_early_rejected": 1,
                "strategies_timed_out": 0,
                "strategies_slow_deferred": 0,
                "strategies_unsupported": 0,
                "strategies_runtime_error": 0,
                "strategies_failed": 0,
                "signal_groups_loaded": 1,
                "signal_groups_evaluated": 1,
                "signal_groups_slow_deferred": 0,
                "optimized_evaluation_mode": "optimized_evaluation_v5_event_first",
                "zero_timeout_mode": True,
                "zero_slow_deferred_mode": True,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    pd.DataFrame(
        [
            {
                "candidate_id": "event_first_a",
                "score": 0.0,
                "adjusted_return_time_risk": 0.1,
                "family": "minervini_sepa",
                "concept_id": "macd_histogram_turnup_trend",
                "market_overlay_id": "spy_stage2_bull",
            }
        ]
    ).to_csv(job / "leaderboard_job_0000.csv", index=False)
    pd.DataFrame(columns=["candidate_id", "adjusted_return_time_risk"]).to_csv(
        job / "filtered_leaderboard_job_0000.csv",
        index=False,
    )
    pd.DataFrame(columns=gtbi.YEARLY_COLUMNS).to_csv(job / "yearly_trade_performance_job_0000.csv", index=False)
    pd.DataFrame(columns=gtbi.TRADE_COLUMNS).to_csv(job / "top_trades_sample_job_0000.csv", index=False)
    pd.DataFrame(columns=gtbi.UNSUPPORTED_COLUMNS).to_csv(job / "unsupported_strategies_job_0000.csv", index=False)
    pd.DataFrame(columns=gtbi.TIMEOUT_COLUMNS).to_csv(job / "timeout_strategies_job_0000.csv", index=False)
    pd.DataFrame(columns=gtbi.SLOW_DEFERRED_COLUMNS).to_csv(job / "slow_deferred_strategies_job_0000.csv", index=False)
    pd.DataFrame(columns=gtbi.EARLY_REJECT_COLUMNS).to_csv(job / "early_rejected_strategies_job_0000.csv", index=False)
    pd.DataFrame(columns=gtbi.RUNTIME_ERROR_COLUMNS).to_csv(job / "runtime_errors_job_0000.csv", index=False)
    pd.DataFrame(columns=gtbi.TIMING_DIAGNOSTIC_COLUMNS).to_csv(job / "timing_diagnostics_job_0000.csv", index=False)
    pd.DataFrame(columns=gtbi.DEDUPE_MAP_COLUMNS).to_csv(job / "dedupe_map_job_0000.csv", index=False)
    pd.DataFrame(columns=gtbi.JOB_MANIFEST_COLUMNS).to_csv(job / "job_manifest_job_0000.csv", index=False)
    pd.DataFrame(
        [
            {
                "job_id": "0000",
                "signal_hash": "sig",
                "concept": "macd_histogram_turnup_trend",
                "uses_event_store": True,
                "uses_sparse_events": True,
                "uses_bitset": False,
            }
        ]
    ).to_csv(job / "compiled_signal_plan_job_0000.csv", index=False)
    pd.DataFrame(
        [
            {
                "job_id": "0000",
                "signal_hash": "sig",
                "concept": "macd_histogram_turnup_trend",
                "events_total": 123,
                "symbols_with_events": 7,
            }
        ]
    ).to_csv(job / "event_store_manifest_job_0000.csv", index=False)
    pd.DataFrame(
        [
            {
                "strategy_id": "event_first_b",
                "concept": "macd_histogram_turnup_trend",
                "precheck_name": "event_max_yearly_trades",
                "decision": "early_rejected",
                "reason": "event_max_yearly_trades_lt_100",
            }
        ]
    ).to_csv(job / "concept_precheck_diagnostics_job_0000.csv", index=False)
    pd.DataFrame(
        [
            {
                "job_id": "0000",
                "strategy_id": "event_first_a",
                "exit_group_hash": "exit",
                "signal_hash": "sig",
                "result_status": "evaluated",
            }
        ]
    ).to_csv(job / "exit_group_manifest_job_0000.csv", index=False)
    (job / "cost_profile_v5_job_0000.json").write_text(
        json.dumps({"optimized_evaluation_mode": "optimized_evaluation_v5_event_first", "signal_groups_loaded": 1}),
        encoding="utf-8",
    )
    (job / "top_indicator_rules_job_0000.jsonl").write_text("", encoding="utf-8")

    summary = gtbi.merge_external_strategy_pack_outputs(
        shards_root=tmp_path / "downloaded",
        output_dir=tmp_path / "final",
        total_strategies_requested=2,
        total_shards_requested=1,
        total_jobs_requested=1,
        candidate_count_per_job=2,
    )

    assert summary["optimized_evaluation_mode"] == "optimized_evaluation_v5_event_first"
    assert summary["zero_timeout_mode"] is True
    assert summary["zero_slow_deferred_mode"] is True
    assert summary["total_strategies_slow_deferred"] == 0
    assert summary["total_strategies_timed_out"] == 0
    for name in (
        "compiled_signal_plan.csv",
        "event_store_manifest.csv",
        "concept_precheck_diagnostics.csv",
        "exit_group_manifest.csv",
        "cost_profile_v5.json",
    ):
        assert (tmp_path / "final" / name).exists()
    assert pd.read_csv(tmp_path / "final" / "event_store_manifest.csv")["events_total"].tolist() == [123]


def test_external_pack_workflow_is_github_only_manual_ubuntu_hosted() -> None:
    path = Path(".github/workflows/global-technical-buy-indicator-external-pack-360jobs.yml")
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)

    assert data["name"] == "Global Technical Buy Indicator External Pack 7200 Jobs"
    assert "workflow_dispatch" in data[True]
    assert "push" not in data[True]
    assert text.count("runs-on: ubuntu-latest") >= 12
    assert "self-hosted" not in text
    assert "C:\\" not in text
    assert "runner.temp" not in text
    assert "scripts/strategy_packs/gtbi_research_broad_72000" in text
    assert "global-technical-buy-indicator-external-pack-72000-results" in text
    assert "Normalize data lake layout and ensure SPY benchmark exists" in text
    assert "out_path = out_dir / \"SPY.parquet\"" in text
    assert "pd.read_parquet(src)" not in text
    assert "shutil.copy2(src, out_path)" in text
    assert "import yfinance" not in text
    assert "v8/finance/chart/SPY" in text
    assert "gtbi-external-pack-data" in text
    assert "original_shards = 360" in text
    assert "original_strategies_per_shard = 200" in text
    assert "chunks_per_shard = (original_strategies_per_shard + candidate_limit - 1) // candidate_limit" in text
    assert "jobs_per_block=180" in text
    assert text.count("max-parallel: 180") == 40
    assert "max-parallel: 60" not in text
    assert "optimized_evaluation_v4_zero_timeout" in text
    assert "--optimized-evaluation-mode" in text
    assert len(data[True]["workflow_dispatch"]["inputs"]) <= 25
    assert "test_max_signal_groups" in data[True]["workflow_dispatch"]["inputs"]
    assert "--test-max-signal-groups" in text
    assert "--signal-first-phase signals" in text
    assert "--signal-first-phase exits" in text
    assert "--signal-events-dir" in text
    assert "enable_block_merge" in text
    assert "merge_block_0" in data["jobs"]
    assert "merge_block_39" in data["jobs"]
    assert "gtbi-external-pack-block-*-results" in text
    assert "run_chunk_0" in data["jobs"]
    assert "run_chunk_39" in data["jobs"]
    assert "--prebuilt-pack-dir external-pack-data" in text
    assert "--external-strategy-offset \"${{ steps.vars.outputs.strategy_offset }}\"" in text
    assert "--candidate-timeout-seconds \"${{ inputs.candidate_timeout_seconds }}\"" in text
    assert "job_wall_clock_seconds" in text
    assert "--job-wall-clock-seconds \"${{ inputs.job_wall_clock_seconds }}\"" in text
    assert "SCHEDULE_ACTIVE_JOBS=0" in text
    assert 'SCHEDULE_ACTIVE_JOBS="${{ inputs.test_max_jobs }}"' in text
    assert '--schedule-active-jobs "$SCHEDULE_ACTIVE_JOBS"' in text
    assert "FAIL_ARGS=()" in text
    assert '"${FAIL_ARGS[@]}"' in text
    assert '"$FAIL_FLAG"' not in text
    assert "--locked-start \"${{ inputs.locked_start }}\"" in text
    assert "GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}" in text
    assert 'gh run download "${{ github.run_id }}"' in text
    assert "requires_local_machine" not in text
    assert "optimized_evaluation_v5_event_first" in text
    assert "smoke_test" in data["jobs"]
    assert "merge_smoke" in data["jobs"]
    assert "timeout-minutes: 35" in text
    assert 'if: ${{ inputs.recovery_job_indices == \'\' && inputs.test_mode == \'true\' }}' in text
    assert 'if: ${{ inputs.recovery_job_indices == \'\' && inputs.test_mode != \'true\' }}' in text
    assert "matrix: ${{ fromJson(needs.plan_smoke.outputs.matrix) }}" in text
    assert "gtbi-external-pack-smoke-results" in text


def test_optimized_evaluation_v1_workflow_alias_uses_v2_engine() -> None:
    path = Path(".github/workflows/global-technical-buy-indicator-optimized-evaluation-v1.yml")
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)

    assert data["name"] == "Global Technical Buy Indicator Optimized Evaluation v1"
    assert "workflow_dispatch" in data[True]
    assert "optimized_evaluation_v2" in text
    assert '--schedule-active-jobs "$SCHEDULE_ACTIVE_JOBS"' in text
    assert "self-hosted" not in text
    assert "C:\\" not in text


def test_gtbi_v5_smoke_workflow_is_push_only_small_github_smoke() -> None:
    path = Path(".github/workflows/global-technical-buy-indicator-v5-smoke.yml")
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)

    assert data["name"] == "Global Technical Buy Indicator V5 Event First Smoke"
    assert "push" in data[True]
    assert "workflow_dispatch" in data[True]
    assert "codex/gtbi-github-only-external-pack-72000" in text
    assert "TEST_MAX_JOBS: \"100\"" in text
    assert "TEST_MAX_SIGNAL_GROUPS: \"1000\"" in text
    assert "optimized_evaluation_v5_event_first" in text
    assert "max-parallel: 100" in text
    assert "timeout-minutes: 35" in text
    assert "QF_DATA_DIR: /tmp/aurora-data" in text
    assert "if: ${{ success() }}" in text
    assert "global-technical-buy-indicator-external-pack-72000-results" in text
    assert "gtbi-external-pack-smoke-results" in text
    assert "self-hosted" not in text
    assert "C:\\" not in text
    assert "runner.temp" not in text
    assert "pd.read_parquet(src)" not in text
    assert "shutil.copy2(src, out_path)" in text
    assert "import yfinance" not in text
    assert "v8/finance/chart/SPY" in text
    assert "locked_start" not in text
    assert "LOCKED_START: \"2021-01-01\"" in text
    assert "VALIDATION_END: \"2020-12-31\"" in text


def test_external_pack_1800jobs_workflow_splits_into_10_strategy_jobs_after_25_timeout_risk() -> None:
    path = Path(".github/workflows/global-technical-buy-indicator-external-pack-1800jobs.yml")
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)

    assert data["name"] == "Global Technical Buy Indicator External Pack 7200 Jobs"
    assert "workflow_dispatch" in data[True]
    assert "push" not in data[True]
    assert "C:\\" not in text
    assert "runner.temp" not in text
    assert text.count("runs-on: ubuntu-latest") >= 12
    assert "self-hosted" not in text
    assert 'default: "27936694743"' in text
    assert 'default: "free-global-yahoo-daily-data-lake"' in text
    assert 'default: "scripts/strategy_packs/gtbi_research_broad_72000"' in text
    assert 'default: "10"' in text
    assert 'default: "300"' in text
    assert 'default: "2000000000"' in text
    assert 'default: "2010-12-31"' in text
    assert 'default: "2011-01-01"' in text
    assert 'default: "2020-12-31"' in text
    assert 'default: "2021-01-01"' in text
    assert "original_shards = 360" in text
    assert "original_strategies_per_shard = 200" in text
    assert "chunks_per_shard = (original_strategies_per_shard + candidate_limit - 1) // candidate_limit" in text
    assert "jobs_per_block=180" in text
    assert "block_count=40" in text
    assert 'job_padded=$(printf "%04d" "$job_index")' in text
    assert 'echo "strategy_offset=$strategy_offset" >> "$GITHUB_OUTPUT"' in text
    assert 'echo "strategy_limit=$strategy_limit" >> "$GITHUB_OUTPUT"' in text
    assert "total_jobs=$(( original_shards * chunks_per_shard ))" in text
    assert "total_strategies += min(candidate_limit, original_strategies_per_shard - strategy_offset)" in text
    assert text.count("max-parallel: 180") == 40
    assert "max-parallel: 60" not in text
    for idx in range(40):
        assert f"run_chunk_{idx}:" in text
        matrix_values = data["jobs"][f"run_chunk_{idx}"]["strategy"]["matrix"]["local_job_index"]
        assert len(matrix_values) == 180
        assert matrix_values[0] == 0
        assert matrix_values[-1] == 179
    assert "--external-strategy-shard-id \"${{ steps.vars.outputs.base_shard_id }}\"" in text
    assert "--external-strategy-offset \"${{ steps.vars.outputs.strategy_offset }}\"" in text
    assert "--external-strategy-limit \"${{ steps.vars.outputs.strategy_limit }}\"" in text
    assert "--candidate-timeout-seconds \"${{ inputs.candidate_timeout_seconds }}\"" in text
    assert "job_wall_clock_seconds" in text
    assert "--job-wall-clock-seconds \"${{ inputs.job_wall_clock_seconds }}\"" in text
    assert "SCHEDULE_ACTIVE_JOBS=0" in text
    assert 'SCHEDULE_ACTIVE_JOBS="${{ inputs.test_max_jobs }}"' in text
    assert '--schedule-active-jobs "$SCHEDULE_ACTIVE_JOBS"' in text
    assert "FAIL_ARGS=()" in text
    assert '"${FAIL_ARGS[@]}"' in text
    assert '"$FAIL_FLAG"' not in text
    assert 'name: gtbi-external-pack-job-${{ steps.vars.outputs.job_padded }}' in text
    assert '--pattern "gtbi-external-pack-job-*"' in text
    assert "GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}" in text
    assert 'gh run download "${{ github.run_id }}"' in text
    assert "--total-jobs-requested" in text
    assert "--candidate-count-per-job" in text
    assert "global-technical-buy-indicator-external-pack-72000-results" in text


def test_external_pack_wrappers_import_from_script_path() -> None:
    env = os.environ.copy()
    env["GITHUB_ACTIONS"] = "true"
    shard_help = subprocess.run(
        [sys.executable, "scripts/run_global_technical_buy_indicator_external_pack_shard.py", "--help"],
        cwd=Path.cwd(),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    merge_help = subprocess.run(
        [sys.executable, "scripts/merge_global_technical_buy_indicator_external_pack.py", "--help"],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert shard_help.returncode == 0, shard_help.stderr
    assert merge_help.returncode == 0, merge_help.stderr
    assert "external GTBI strategy-pack shard" in shard_help.stdout
    assert "Merge external GTBI strategy-pack shard outputs" in merge_help.stdout
