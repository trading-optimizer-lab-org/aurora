"""Tests for aurora.analytics.round_trip."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aurora.analytics.round_trip import (
    Trade,
    consecutive_streak,
    extract_trades,
    mae_mfe_curve,
    stats_by_direction,
    stats_by_holding_period,
    trade_stats,
    trades_dataframe,
)


def _ts(n: int, start: str = "2024-01-01") -> np.ndarray:
    return pd.date_range(start, periods=n, freq="D").values


def test_extract_single_long_trade():
    weights = np.array([0, 1, 1, 1, 0], dtype=float)
    prices = np.array([100, 101, 102, 103, 99], dtype=float)
    trades = extract_trades(weights, prices, _ts(5))
    assert len(trades) == 1
    t = trades[0]
    assert t.direction == 1
    # entry @ idx=1 (price=101), exit @ idx=3 (price=103)
    assert t.entry_price == 101.0
    assert t.exit_price == 103.0
    assert t.pnl_pct == pytest.approx((103 / 101 - 1.0))


def test_extract_two_trades_with_zero_between():
    weights = np.array([0, 1, 1, 0, 0, 1, 1, 0], dtype=float)
    prices = np.array([10, 11, 12, 13, 14, 15, 16, 17], dtype=float)
    trades = extract_trades(weights, prices, _ts(8))
    assert len(trades) == 2
    assert trades[0].entry_price == 11 and trades[0].exit_price == 12
    assert trades[1].entry_price == 15 and trades[1].exit_price == 16


def test_extract_sign_flip_creates_two_trades():
    weights = np.array([0, 1, 1, -1, -1, 0], dtype=float)
    prices = np.array([100, 100, 110, 105, 95, 100], dtype=float)
    trades = extract_trades(weights, prices, _ts(6))
    assert len(trades) == 2
    assert trades[0].direction == 1
    assert trades[1].direction == -1


def test_short_trade_pnl_negated():
    # Short from price 100 -> 95 should be +5%
    weights = np.array([0, -1, -1, 0], dtype=float)
    prices = np.array([100, 100, 95, 90], dtype=float)
    trades = extract_trades(weights, prices, _ts(4))
    assert len(trades) == 1
    t = trades[0]
    assert t.direction == -1
    assert t.pnl_pct == pytest.approx(0.05)


def test_mae_mfe_basic():
    # Long trade, prices dip to 90 (MAE = -10%), peak at 115 (MFE = +15%)
    weights = np.array([0, 1, 1, 1, 1, 0], dtype=float)
    prices = np.array([100, 100, 90, 115, 105, 100], dtype=float)
    trades = extract_trades(weights, prices, _ts(6))
    assert len(trades) == 1
    t = trades[0]
    # Entry @ idx=1 price=100, segment idx 1..4 => [100, 90, 115, 105]
    assert t.mae_pct == pytest.approx(-0.10)
    assert t.mfe_pct == pytest.approx(0.15)
    # Exit @ idx=4 price=105
    assert t.pnl_pct == pytest.approx(0.05)


def test_mae_mfe_short():
    # Short trade: direction=-1, price rises against us
    weights = np.array([0, -1, -1, -1, 0], dtype=float)
    prices = np.array([100, 100, 110, 95, 95], dtype=float)
    trades = extract_trades(weights, prices, _ts(5))
    t = trades[0]
    # excursions = (p/100 - 1) * -1 => [0, -0.10, +0.05]
    assert t.mae_pct == pytest.approx(-0.10)
    assert t.mfe_pct == pytest.approx(0.05)


def test_mae_mfe_curve_helper():
    trade = Trade(
        entry_time=pd.Timestamp("2024-01-01"),
        entry_price=100.0,
        exit_time=pd.Timestamp("2024-01-05"),
        exit_price=105.0,
        direction=1,
        holding_days=4,
        pnl_pct=0.05,
        pnl_dollars=float("nan"),
        mae_pct=-0.10,
        mfe_pct=0.15,
    )
    prices = np.array([100, 90, 115, 105], dtype=float)
    mae_c, mfe_c = mae_mfe_curve(trade, prices)
    np.testing.assert_allclose(mae_c, [0.0, -0.10, -0.10, -0.10])
    np.testing.assert_allclose(mfe_c, [0.0, 0.0, 0.15, 0.15])


def test_trade_stats_aggregates():
    weights = np.array([0, 1, 1, 0, 1, 1, 0, 1, 1, 0], dtype=float)
    # Two winners, one loser
    prices = np.array([100, 100, 110, 110, 100, 105, 105, 100, 90, 90], dtype=float)
    trades = extract_trades(weights, prices, _ts(10))
    assert len(trades) == 3
    s = trade_stats(trades)
    assert s.n_trades == 3
    assert s.win_rate == pytest.approx(2 / 3)
    assert s.profit_factor > 1.0
    assert s.pnl_total_pct == pytest.approx(0.10 + 0.05 + (-0.10))


def test_consecutive_streak_wins():
    trades = [
        Trade(pd.Timestamp("2024-01-01"), 100, pd.Timestamp("2024-01-02"),
              101, 1, 1, 0.01, float("nan"), 0.0, 0.01),
        Trade(pd.Timestamp("2024-01-03"), 100, pd.Timestamp("2024-01-04"),
              102, 1, 1, 0.02, float("nan"), 0.0, 0.02),
        Trade(pd.Timestamp("2024-01-05"), 100, pd.Timestamp("2024-01-06"),
              99, 1, 1, -0.01, float("nan"), -0.01, 0.0),
        Trade(pd.Timestamp("2024-01-07"), 100, pd.Timestamp("2024-01-08"),
              105, 1, 1, 0.05, float("nan"), 0.0, 0.05),
        Trade(pd.Timestamp("2024-01-09"), 100, pd.Timestamp("2024-01-10"),
              98, 1, 1, -0.02, float("nan"), -0.02, 0.0),
        Trade(pd.Timestamp("2024-01-11"), 100, pd.Timestamp("2024-01-12"),
              97, 1, 1, -0.03, float("nan"), -0.03, 0.0),
    ]
    assert consecutive_streak(trades, "win") == 2
    assert consecutive_streak(trades, "loss") == 2


def test_stats_by_holding_period():
    weights = np.array([0, 1, 0, 1, 1, 1, 0, 1, 1, 1, 1, 1, 1, 0], dtype=float)
    prices = np.linspace(100, 130, 14)
    trades = extract_trades(weights, prices, _ts(14))
    df = stats_by_holding_period(trades)
    assert "bucket" in df.columns
    assert df["n_trades"].sum() == len(trades)
    assert set(df["bucket"]).issubset({"1d", "2-5d", "6-20d", ">20d"})


def test_stats_by_direction():
    weights = np.array([0, 1, 1, 0, -1, -1, 0], dtype=float)
    prices = np.array([100, 100, 110, 110, 100, 90, 90], dtype=float)
    trades = extract_trades(weights, prices, _ts(7))
    df = stats_by_direction(trades)
    assert set(df["direction"]) == {"long", "short"}
    long_row = df[df["direction"] == "long"].iloc[0]
    short_row = df[df["direction"] == "short"].iloc[0]
    assert long_row["n_trades"] == 1
    assert short_row["n_trades"] == 1
    # Long: 100 -> 110 = +10%, Short: 100 -> 90 = +10% (price down, short wins)
    assert long_row["pnl_total_pct"] == pytest.approx(0.10)
    assert short_row["pnl_total_pct"] == pytest.approx(0.10)


def test_no_trades_zero_weights():
    weights = np.zeros(10, dtype=float)
    prices = np.linspace(100, 110, 10)
    trades = extract_trades(weights, prices, _ts(10))
    assert trades == []
    s = trade_stats(trades)
    assert s.n_trades == 0
    df = trades_dataframe(trades)
    assert df.empty
    assert stats_by_holding_period(trades).empty
    assert stats_by_direction(trades).empty


def test_trades_dataframe_columns():
    weights = np.array([0, 1, 1, 0], dtype=float)
    prices = np.array([100, 100, 110, 110], dtype=float)
    trades = extract_trades(weights, prices, _ts(4))
    df = trades_dataframe(trades)
    expected = {"entry_time", "entry_price", "exit_time", "exit_price",
                "direction", "holding_days", "pnl_pct", "pnl_dollars",
                "mae_pct", "mfe_pct"}
    assert expected.issubset(df.columns)
    assert len(df) == 1


def test_pnl_dollars_with_notional():
    weights = np.array([0, 1, 1, 0], dtype=float)
    prices = np.array([100, 100, 110, 110], dtype=float)
    trades = extract_trades(weights, prices, _ts(4), notional=10_000.0)
    assert trades[0].pnl_dollars == pytest.approx(0.10 * 10_000.0)


def test_trade_stats_no_losers_profit_factor_inf():
    weights = np.array([0, 1, 1, 0, 1, 1, 0], dtype=float)
    prices = np.array([100, 100, 110, 110, 100, 105, 105], dtype=float)
    trades = extract_trades(weights, prices, _ts(7))
    s = trade_stats(trades)
    assert s.profit_factor == float("inf")


def test_trade_at_end_of_series():
    # Position open through the last bar -> exit at last bar
    weights = np.array([0, 1, 1, 1], dtype=float)
    prices = np.array([100, 100, 105, 110], dtype=float)
    trades = extract_trades(weights, prices, _ts(4))
    assert len(trades) == 1
    assert trades[0].exit_price == 110


def test_expectancy_unbiased_by_flat_trades() -> None:
    """Round V regression: flats must not be absorbed into the loss bucket.

    With many flat trades, expectancy = win_rate*avg_w + loss_rate*avg_l
    must equal the full-sample mean of pnls -- not (1 - win_rate)*avg_l,
    which over-weights losses in the presence of flats.
    """
    # 1 winner (+5), 1 loser (-3), 8 flats. Sample mean = (5 - 3) / 10 = 0.2.
    win = Trade(
        entry_time=pd.Timestamp("2024-01-01"),
        entry_price=100.0,
        exit_time=pd.Timestamp("2024-01-02"),
        exit_price=105.0,
        direction=1,
        holding_days=1,
        pnl_pct=5.0,
        pnl_dollars=float("nan"),
        mae_pct=0.0,
        mfe_pct=5.0,
    )
    loss = Trade(
        entry_time=pd.Timestamp("2024-01-03"),
        entry_price=100.0,
        exit_time=pd.Timestamp("2024-01-04"),
        exit_price=97.0,
        direction=1,
        holding_days=1,
        pnl_pct=-3.0,
        pnl_dollars=float("nan"),
        mae_pct=-3.0,
        mfe_pct=0.0,
    )
    flats = [
        Trade(
            entry_time=pd.Timestamp("2024-02-01"),
            entry_price=100.0,
            exit_time=pd.Timestamp("2024-02-02"),
            exit_price=100.0,
            direction=1,
            holding_days=1,
            pnl_pct=0.0,
            pnl_dollars=float("nan"),
            mae_pct=0.0,
            mfe_pct=0.0,
        )
        for _ in range(8)
    ]
    from aurora.analytics.round_trip import trade_stats as _ts_stats

    s = _ts_stats([win, loss] + flats)
    # Expectancy must equal the simple sample mean of all PnLs.
    assert s.expectancy_pct == pytest.approx(0.2, abs=1e-12)
    assert s.flat_trades == 8
    # And it must equal avg_trade_pct (the documented sample mean).
    assert s.expectancy_pct == pytest.approx(s.avg_trade_pct, abs=1e-12)
