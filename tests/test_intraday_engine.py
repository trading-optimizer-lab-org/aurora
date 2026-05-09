"""Tests for aurora.core.engine_intraday — minute/hourly backtest engine."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from aurora.core.costs import CostModel, ZERO_costs, IBKR_costs
from aurora.core.engine_intraday import (
    IntradayBacktestResult,
    run_intraday_backtest,
)


# ---------- fixtures ----------

def _rth_index(n_days: int = 3, freq: str = "1min", start: str = "2024-01-08") -> pd.DatetimeIndex:
    """Build a DatetimeIndex spanning RTH minute bars across business days.

    Each session: 09:30 to 15:59 inclusive at 1-min frequency = 390 bars.
    """
    parts = []
    cur = pd.Timestamp(start)
    days = 0
    while days < n_days:
        if cur.weekday() < 5:  # Mon-Fri
            session_start = pd.Timestamp(cur.date()) + pd.Timedelta(hours=9, minutes=30)
            session_end = pd.Timestamp(cur.date()) + pd.Timedelta(hours=16)
            bars = pd.date_range(session_start, session_end, freq=freq, inclusive="left")
            parts.append(bars)
            days += 1
        cur = cur + pd.Timedelta(days=1)
    return pd.DatetimeIndex(np.concatenate([p.to_numpy() for p in parts]))


def _make_prices(idx: pd.DatetimeIndex, drift: float = 0.0001, vol: float = 0.0005,
                 seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, vol, len(idx))
    close = 100.0 * np.cumprod(1.0 + rets)
    return pd.DataFrame({
        "open": close,
        "high": close * 1.0002,
        "low": close * 0.9998,
        "close": close,
        "volume": rng.integers(1000, 10000, len(idx)),
    }, index=idx)


def _const_signal(prices: pd.DataFrame, value: float = 1.0) -> pd.Series:
    return pd.Series(value, index=prices.index)


def _zero_signal(prices: pd.DataFrame) -> pd.Series:
    return pd.Series(0.0, index=prices.index)


# ---------- tests ----------

def test_basic_run():
    idx = _rth_index(n_days=3)
    prices = _make_prices(idx, drift=0.0002, vol=0.0003, seed=1)
    res = run_intraday_backtest(
        prices, _const_signal, bars_per_day=390, calendar="RTH",
        costs=ZERO_costs,
    )
    assert isinstance(res, IntradayBacktestResult)
    assert len(res.equity) == len(idx)
    assert res.equity.iloc[0] == pytest.approx(1.0)
    # positive drift constant long should produce equity > 1 with high prob
    assert res.equity.iloc[-1] > 1.0
    assert res.metrics["total_return"] > 0
    assert res.metrics["n_bars"] == len(idx)


def test_calendar_rth():
    """RTH: only 09:30-15:59 bars are in-session; mask should match."""
    from aurora.core.engine_intraday import _in_session_mask
    idx = pd.DatetimeIndex([
        pd.Timestamp("2024-01-08 09:00"),  # pre-market
        pd.Timestamp("2024-01-08 09:30"),  # in
        pd.Timestamp("2024-01-08 12:00"),  # in
        pd.Timestamp("2024-01-08 15:59"),  # in
        pd.Timestamp("2024-01-08 16:00"),  # close edge - exclusive
        pd.Timestamp("2024-01-08 18:00"),  # post
    ])
    mask = _in_session_mask(idx, "RTH")
    assert list(mask) == [False, True, True, True, False, False]


def test_calendar_24h():
    """24h: all bars in-session, single session id for everything."""
    from aurora.core.engine_intraday import _in_session_mask, _session_id
    idx = pd.date_range("2024-01-08", periods=2880, freq="1min")
    mask = _in_session_mask(idx, "24h")
    assert mask.all()
    sids = _session_id(idx, "24h")
    assert (sids == 0).all()


def test_flat_eod():
    """flat_eod=True forces position to 0 at the last bar of each session."""
    idx = _rth_index(n_days=2)
    prices = _make_prices(idx)
    res = run_intraday_backtest(
        prices, _const_signal, bars_per_day=390, calendar="RTH",
        flat_eod=True,
    )
    # Last bar of each session should have position == 0
    # Session boundary detection: groupby date, last bar
    by_date = res.positions.groupby(res.positions.index.normalize()).last()
    for date, pos in by_date.items():
        assert pos == 0.0, f"position at session close on {date} = {pos}, expected 0"


def test_overnight_cost():
    """Overnight bps charged when position carries across sessions."""
    idx = _rth_index(n_days=3)
    prices = _make_prices(idx, drift=0.0, vol=0.0001, seed=2)

    # Without overnight cost
    res_no = run_intraday_backtest(
        prices, _const_signal, bars_per_day=390, calendar="RTH",
        flat_eod=False, overnight_cost_bps=0.0,
    )
    # With overnight cost
    res_yes = run_intraday_backtest(
        prices, _const_signal, bars_per_day=390, calendar="RTH",
        flat_eod=False, overnight_cost_bps=10.0,
    )
    # Equity with overnight cost must be lower
    assert res_yes.equity.iloc[-1] < res_no.equity.iloc[-1]
    # Approximate: 2 carries (between 3 sessions) * 10bps each = 20bps total drag
    drag = 1.0 - (res_yes.equity.iloc[-1] / res_no.equity.iloc[-1])
    assert drag == pytest.approx(20e-4, abs=1e-5)


def test_overnight_cost_skipped_with_flat_eod():
    """When flat_eod=True there is no carry, so overnight cost has no effect."""
    idx = _rth_index(n_days=3)
    prices = _make_prices(idx, drift=0.0, vol=0.0001, seed=3)

    res_a = run_intraday_backtest(
        prices, _const_signal, bars_per_day=390, calendar="RTH",
        flat_eod=True, overnight_cost_bps=50.0,
    )
    res_b = run_intraday_backtest(
        prices, _const_signal, bars_per_day=390, calendar="RTH",
        flat_eod=True, overnight_cost_bps=0.0,
    )
    assert res_a.equity.iloc[-1] == pytest.approx(res_b.equity.iloc[-1], rel=1e-12)


def test_zero_signal():
    """All-zero signal: flat equity, no trades, no costs."""
    idx = _rth_index(n_days=2)
    prices = _make_prices(idx)
    res = run_intraday_backtest(
        prices, _zero_signal, bars_per_day=390, calendar="RTH",
        costs=IBKR_costs,
    )
    assert (res.equity == 1.0).all()
    assert (res.returns == 0.0).all()
    assert len(res.trades) == 0
    assert res.metrics["total_return"] == 0.0


def test_costs_applied():
    """A non-trivial cost model strictly reduces equity vs cost-free."""
    idx = _rth_index(n_days=2)
    prices = _make_prices(idx, drift=0.0001, vol=0.0003, seed=7)

    # Signal that flips every 10 bars to force turnover
    def flip_signal(p):
        s = np.zeros(len(p))
        s[::20] = 1.0
        s[10::20] = -1.0
        return pd.Series(s, index=p.index)

    res_free = run_intraday_backtest(
        prices, flip_signal, bars_per_day=390, calendar="RTH",
        costs=ZERO_costs,
    )
    res_costly = run_intraday_backtest(
        prices, flip_signal, bars_per_day=390, calendar="RTH",
        costs=IBKR_costs,
    )
    assert res_costly.equity.iloc[-1] < res_free.equity.iloc[-1]
    # Trades should exist
    assert len(res_costly.trades) > 0
    # Costs should be positive on every trade row
    assert (res_costly.trades["cost"] > 0).all()


def test_metrics_computed():
    """All required metric keys are present and finite."""
    idx = _rth_index(n_days=5)
    prices = _make_prices(idx, drift=0.00005, vol=0.0004, seed=11)
    res = run_intraday_backtest(
        prices, _const_signal, bars_per_day=390, calendar="RTH",
    )
    required = {"total_return", "cagr", "sharpe", "sortino", "mdd",
                "calmar", "n_bars", "n_sessions", "ppy"}
    assert required.issubset(res.metrics.keys())
    for k in ("total_return", "cagr", "sharpe", "sortino", "mdd", "calmar"):
        assert np.isfinite(res.metrics[k]), f"{k} is not finite"
    assert res.metrics["n_bars"] == len(idx)
    assert res.metrics["n_sessions"] == 5
    assert res.metrics["ppy"] == 390 * 252


def test_no_lookahead():
    """The engine's shift convention must be `weight[i-1] * return[i]`.

    A signal that uses ONLY bar-i return as input (sign of bar-i return) must
    NOT be able to capture bar-i return — it can only capture bar-(i+1) return.
    If the engine were looking ahead (using `weight[i] * return[i]` directly),
    the strategy would achieve perfect alpha by capturing the same-bar return.
    With proper anti-lookahead the strategy captures only the NEXT bar's
    return, which on a random walk has zero expected correlation with the
    signal — so equity[-1] should be well below the perfect-alpha bound.
    """
    idx = _rth_index(n_days=2)
    prices = _make_prices(idx, drift=0.0, vol=0.001, seed=99)

    close = prices["close"].to_numpy()
    same_bar_ret = np.zeros(len(idx))
    same_bar_ret[1:] = close[1:] / close[:-1] - 1.0
    # Signal at bar i uses sign of return[i] (information available at close
    # of bar i — this is causal, NOT lookahead).
    sig = np.sign(same_bar_ret)

    def causal_sign_signal(p):
        return pd.Series(sig, index=p.index)

    res = run_intraday_backtest(
        prices, causal_sign_signal, bars_per_day=390, calendar="RTH",
        costs=ZERO_costs,
    )

    # Perfect-alpha upper bound (engine WITH lookahead would deliver this by
    # using weight[i] * return[i] where weight[i] = sign(return[i])):
    perfect = float(np.prod(1.0 + np.abs(same_bar_ret[1:])))
    achieved = float(res.equity.iloc[-1])

    # With anti-lookahead, achieved must be MUCH lower than perfect because
    # signal at bar i applies to return[i+1], uncorrelated with return[i] on
    # a random walk. Perfect-alpha here is ~1.88; causal achievement should
    # be near 1.0 (random walk drift).
    assert achieved < perfect * 0.6, (
        f"engine appears to be looking ahead: achieved={achieved}, "
        f"perfect={perfect}"
    )
    # And confirm it's roughly a random walk (close to 1.0)
    assert abs(achieved - 1.0) < 0.2, (
        f"achieved equity {achieved} far from random-walk baseline 1.0"
    )


def test_session_pnl_structure():
    """session_pnl DataFrame has expected columns and one row per session."""
    idx = _rth_index(n_days=3)
    prices = _make_prices(idx)
    res = run_intraday_backtest(
        prices, _const_signal, bars_per_day=390, calendar="RTH",
    )
    assert list(res.session_pnl.columns) == ["date", "pnl", "n_trades", "n_bars", "end_position"]
    assert len(res.session_pnl) == 3
    assert res.session_pnl["n_bars"].sum() == len(idx)


def test_24h_calendar_run():
    """24h calendar: all bars are in-session, ppy uses 365."""
    idx = pd.date_range("2024-01-08", periods=2880, freq="1min")  # 2 days
    prices = _make_prices(idx, drift=0.00001, vol=0.0001, seed=4)
    res = run_intraday_backtest(
        prices, _const_signal, bars_per_day=24 * 60, calendar="24h",
    )
    assert res.metrics["ppy"] == 24 * 60 * 365
    assert res.metrics["n_bars"] == len(idx)


def test_calendar_rth_utc_input():
    """UTC-tz-aware index: wall-clock 14:30-21:00 UTC corresponds to 09:30-16:00 ET.

    With the 2024-01-08 winter date (EST = UTC-5), the RTH session in UTC is
    14:30-21:00. The mask must include those bars and exclude bars outside.
    """
    from aurora.core.engine_intraday import _in_session_mask
    idx = pd.DatetimeIndex([
        pd.Timestamp("2024-01-08 13:30", tz="UTC"),  # 08:30 ET pre-market
        pd.Timestamp("2024-01-08 14:30", tz="UTC"),  # 09:30 ET in
        pd.Timestamp("2024-01-08 17:00", tz="UTC"),  # 12:00 ET in
        pd.Timestamp("2024-01-08 20:59", tz="UTC"),  # 15:59 ET in
        pd.Timestamp("2024-01-08 21:00", tz="UTC"),  # 16:00 ET close edge
        pd.Timestamp("2024-01-08 23:00", tz="UTC"),  # 18:00 ET post
    ])
    mask = _in_session_mask(idx, "RTH")
    assert list(mask) == [False, True, True, True, False, False]


def test_calendar_rth_naive_input():
    """Naive index assumed to be in ET; backwards-compat behavior preserved."""
    from aurora.core.engine_intraday import _in_session_mask
    idx = pd.DatetimeIndex([
        pd.Timestamp("2024-01-08 09:00"),  # pre-market
        pd.Timestamp("2024-01-08 09:30"),  # in
        pd.Timestamp("2024-01-08 12:00"),  # in
        pd.Timestamp("2024-01-08 15:59"),  # in
        pd.Timestamp("2024-01-08 16:00"),  # close edge - exclusive
        pd.Timestamp("2024-01-08 18:00"),  # post
    ])
    mask = _in_session_mask(idx, "RTH")
    assert list(mask) == [False, True, True, True, False, False]


def test_intraday_borrow_calendar_correct_per_calendar():
    """Borrow rate annualization must use 252 days/yr for RTH/ETH and 365 for 24h.

    Build identical setups (same bars_per_day, same constant short position,
    same borrow_rate_annual) on two calendars and verify the per-bar borrow
    drag ratio matches the expected calendar ratio (252/365).
    """
    cm = CostModel(borrow_rate_annual=0.10)  # 10% annual

    # Same number of bars_per_day for both, single bar with full short
    # We build an idx of equal length on each calendar so the only difference
    # in equity drag is the calendar denominator (252 vs 365).
    idx_rth = _rth_index(n_days=2)
    prices_rth = _make_prices(idx_rth, drift=0.0, vol=0.0, seed=0)

    # 24h: equal-length contiguous minute index spanning 2 days = 2880 bars
    idx_24h = pd.date_range("2024-01-08", periods=len(idx_rth), freq="1min")
    prices_24h = _make_prices(idx_24h, drift=0.0, vol=0.0, seed=0)

    # Constant -100% short position; no other costs
    def short_signal(p):
        return pd.Series(-1.0, index=p.index)

    res_rth = run_intraday_backtest(
        prices_rth, short_signal, bars_per_day=390, calendar="RTH", costs=cm,
    )
    res_24h = run_intraday_backtest(
        prices_24h, short_signal, bars_per_day=390, calendar="24h", costs=cm,
    )

    # Per-bar borrow cost should be:
    #   RTH:  rate / (390 * 252)
    #   24h:  rate / (390 * 365)
    expected_rth = 0.10 / (390 * 252)
    expected_24h = 0.10 / (390 * 365)

    # Returns are pure -borrow drag (no price moves, no txn costs after first bar)
    # First bar is delta_w=1.0 with zero per_trade_bps -> 0 cost; remaining bars
    # carry only borrow.
    rets_rth = res_rth.returns.to_numpy()
    rets_24h = res_24h.returns.to_numpy()

    # Skip the initial bar (delta_w = 1 from 0 to -1, but ZERO_costs txn so it's
    # just borrow). Compare from bar 1 onward.
    np.testing.assert_allclose(rets_rth[1:], -expected_rth, atol=1e-15)
    np.testing.assert_allclose(rets_24h[1:], -expected_24h, atol=1e-15)

    # Calendar ratio sanity: 24h drag is smaller per bar (denominator larger)
    assert abs(rets_24h[1]) < abs(rets_rth[1])
    ratio = abs(rets_rth[1]) / abs(rets_24h[1])
    assert ratio == pytest.approx(365.0 / 252.0, rel=1e-9)
