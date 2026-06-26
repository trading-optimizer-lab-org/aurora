from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

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
    assert "gtbi-external-pack-data" in text
    assert "original_shards = 360" in text
    assert "original_strategies_per_shard = 200" in text
    assert "chunks_per_shard = (original_strategies_per_shard + candidate_limit - 1) // candidate_limit" in text
    assert "jobs_per_block=180" in text
    assert text.count("max-parallel: 180") == 40
    assert "max-parallel: 60" not in text
    assert "run_chunk_0" in data["jobs"]
    assert "run_chunk_39" in data["jobs"]
    assert "--prebuilt-pack-dir external-pack-data" in text
    assert "--external-strategy-offset \"${{ steps.vars.outputs.strategy_offset }}\"" in text
    assert "--candidate-timeout-seconds \"${{ inputs.candidate_timeout_seconds }}\"" in text
    assert "FAIL_ARGS=()" in text
    assert '"${FAIL_ARGS[@]}"' in text
    assert '"$FAIL_FLAG"' not in text
    assert "--locked-start \"${{ inputs.locked_start }}\"" in text
    assert "requires_local_machine" not in text


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
    assert "FAIL_ARGS=()" in text
    assert '"${FAIL_ARGS[@]}"' in text
    assert '"$FAIL_FLAG"' not in text
    assert 'name: gtbi-external-pack-job-${{ steps.vars.outputs.job_padded }}' in text
    assert "pattern: gtbi-external-pack-job-*" in text
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
