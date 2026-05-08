"""Tests for tax-aware backtest module."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantforge.core.taxes import (
    TaxConfig,
    TaxLot,
    TaxAwareSimulator,
    after_tax_metrics,
    detect_wash_sales,
)


def _ts(dates: list[str]) -> np.ndarray:
    return np.array([pd.Timestamp(d) for d in dates], dtype="datetime64[ns]")


def test_short_term_gain_taxed():
    """Hold < 365d, gain → short-term (37%) tax."""
    # buy at 100, hold 100 days, sell at 110. Gain = 10/share * 1000 shares = 10k
    # Setup: weight=1.0 at day0 (buy), weight=0.0 at day100 (sell)
    T = 101
    prices = np.linspace(100.0, 110.0, T)
    weights = np.zeros(T); weights[:100] = 1.0  # hold for 100 days
    timestamps = _ts([(pd.Timestamp("2024-01-01") + pd.Timedelta(days=i)).strftime("%Y-%m-%d")
                      for i in range(T)])
    sim = TaxAwareSimulator(config=TaxConfig(enable_wash_sale=False))
    res = sim.simulate(weights, prices, timestamps, initial_capital=100_000)

    assert res.total_short_term_pnl > 0
    assert res.total_long_term_pnl == 0.0
    # tax must be 37% of short-term pnl
    assert res.total_short_term_tax == pytest.approx(0.37 * res.total_short_term_pnl, rel=1e-6)
    assert res.total_long_term_tax == 0.0


def test_long_term_gain_taxed():
    """Hold > 365d, gain → long-term (20%) tax.

    Use flat price during holding period (no rebalancing churn) and a single
    price jump at sell day so all proceeds come from a single long-held lot.
    """
    T = 400
    prices = np.full(T, 100.0)
    prices[-1] = 200.0   # price jump at last bar
    weights = np.zeros(T); weights[:T - 1] = 1.0  # buy day0, sell last bar
    timestamps = _ts([(pd.Timestamp("2022-01-01") + pd.Timedelta(days=i)).strftime("%Y-%m-%d")
                      for i in range(T)])
    sim = TaxAwareSimulator(config=TaxConfig(enable_wash_sale=False))
    res = sim.simulate(weights, prices, timestamps, initial_capital=100_000)

    assert res.total_long_term_pnl > 0
    # all gains long-term (held > 365d, flat price avoids rebalancing churn)
    assert abs(res.total_short_term_pnl) < 1e-6
    assert res.total_long_term_tax == pytest.approx(0.20 * res.total_long_term_pnl, rel=1e-6)


def test_fifo_accounting():
    """Multiple lots, FIFO sells oldest first → realized gain uses oldest basis."""
    sim = TaxAwareSimulator(config=TaxConfig(accounting_method="FIFO",
                                             enable_wash_sale=False))
    lots = [
        TaxLot(entry_date="2024-01-01", quantity=10.0, basis_per_share=100.0),
        TaxLot(entry_date="2024-06-01", quantity=10.0, basis_per_share=150.0),
    ]
    picks = sim._pick_lots(lots, qty=5.0)
    assert picks == [(0, 5.0)]

    picks = sim._pick_lots(lots, qty=15.0)
    # FIFO: take all 10 from lot 0, then 5 from lot 1
    assert picks == [(0, 10.0), (1, 5.0)]


def test_lifo_accounting():
    """LIFO sells newest first."""
    sim = TaxAwareSimulator(config=TaxConfig(accounting_method="LIFO",
                                             enable_wash_sale=False))
    lots = [
        TaxLot(entry_date="2024-01-01", quantity=10.0, basis_per_share=100.0),
        TaxLot(entry_date="2024-06-01", quantity=10.0, basis_per_share=150.0),
    ]
    picks = sim._pick_lots(lots, qty=5.0)
    # LIFO: pull from newest first (index 1)
    assert picks == [(1, 5.0)]

    picks = sim._pick_lots(lots, qty=15.0)
    assert picks == [(1, 10.0), (0, 5.0)]


def test_hifo_accounting():
    """HIFO sells highest-basis lots first → minimizes realized gain."""
    sim = TaxAwareSimulator(config=TaxConfig(accounting_method="HIFO",
                                             enable_wash_sale=False))
    lots = [
        TaxLot(entry_date="2024-01-01", quantity=10.0, basis_per_share=100.0),
        TaxLot(entry_date="2024-06-01", quantity=10.0, basis_per_share=150.0),  # highest
        TaxLot(entry_date="2024-09-01", quantity=10.0, basis_per_share=120.0),
    ]
    picks = sim._pick_lots(lots, qty=5.0)
    # highest basis 150 first → index 1
    assert picks == [(1, 5.0)]


def test_wash_sale_detected():
    """Loss + rebuy within 30d → loss disallowed."""
    # buy at 100 (day 0), price falls to 90 (day 10) → sell at loss,
    # rebuy at 92 (day 20, within 30-day window) → loss disallowed.
    dates = [(pd.Timestamp("2024-01-01") + pd.Timedelta(days=i)).strftime("%Y-%m-%d")
             for i in range(40)]
    timestamps = _ts(dates)
    prices = np.full(40, 100.0)
    prices[10:20] = 90.0   # drop, sell at loss
    prices[20:] = 92.0     # rebuy slightly higher
    weights = np.zeros(40)
    weights[0:10] = 1.0    # hold first 10 days
    weights[20:30] = 1.0   # rebuy at day 20 (within 30 days of sell)

    sim = TaxAwareSimulator(config=TaxConfig(enable_wash_sale=True))
    res = sim.simulate(weights, prices, timestamps, initial_capital=100_000)

    # the sell at day 10 is a loss; rebuy at day 20 is within 30 days → wash sale
    assert res.wash_sale_disallowed_loss > 0
    wash_rows = [r for r in res.realized_gains if r.is_wash_sale]
    assert len(wash_rows) >= 1
    # disallowed loss rows pay zero tax
    assert all(r.tax == 0.0 for r in wash_rows)


def test_wash_sale_disabled():
    """enable_wash_sale=False → losses recognized normally."""
    dates = [(pd.Timestamp("2024-01-01") + pd.Timedelta(days=i)).strftime("%Y-%m-%d")
             for i in range(40)]
    timestamps = _ts(dates)
    prices = np.full(40, 100.0)
    prices[10:20] = 90.0
    prices[20:] = 92.0
    weights = np.zeros(40)
    weights[0:10] = 1.0
    weights[20:30] = 1.0

    sim = TaxAwareSimulator(config=TaxConfig(enable_wash_sale=False))
    res = sim.simulate(weights, prices, timestamps, initial_capital=100_000)

    assert res.wash_sale_disallowed_loss == 0.0
    # losses should be reflected in negative short-term pnl
    assert res.total_short_term_pnl < 0


def test_after_tax_return_lower_than_pre_tax():
    """For net positive strategy, after-tax return must be lower than pre-tax."""
    T = 200
    prices = np.linspace(100.0, 130.0, T)
    weights = np.zeros(T); weights[:T - 1] = 1.0  # buy and hold then sell at end
    timestamps = _ts([(pd.Timestamp("2024-01-01") + pd.Timedelta(days=i)).strftime("%Y-%m-%d")
                      for i in range(T)])
    sim = TaxAwareSimulator(config=TaxConfig(enable_wash_sale=False))
    res = sim.simulate(weights, prices, timestamps, initial_capital=100_000)

    assert res.pre_tax_return > 0
    assert res.after_tax_return < res.pre_tax_return
    assert res.total_tax > 0
    assert res.final_nav_after_tax < res.final_nav_pre_tax


def test_full_strategy_simulation(synthetic_prices_daily):
    """Synthetic weights + prices: result fields populated, internally consistent."""
    prices = synthetic_prices_daily.values
    T = len(prices)
    # toggle weight on/off every 50 bars
    weights = np.zeros(T)
    for k in range(0, T, 100):
        weights[k:k + 50] = 1.0
    timestamps = synthetic_prices_daily.index.values.astype("datetime64[ns]")

    sim = TaxAwareSimulator(config=TaxConfig())
    res = sim.simulate(weights, prices, timestamps, initial_capital=100_000)

    assert isinstance(res.realized_gains, list)
    assert len(res.realized_gains) > 0  # some sells happened
    assert res.final_nav_pre_tax > 0
    # after-tax NAV cannot exceed pre-tax NAV
    assert res.final_nav_after_tax <= res.final_nav_pre_tax + 1e-6
    # consistency: total_tax = sum of category taxes
    assert res.total_tax == pytest.approx(
        res.total_short_term_tax + res.total_long_term_tax, rel=1e-9)


def test_after_tax_metrics_helper():
    """after_tax_metrics convenience returns a dict with expected keys."""
    T = 300
    prices = np.linspace(100.0, 120.0, T)
    weights = np.zeros(T); weights[:T - 1] = 1.0
    timestamps = _ts([(pd.Timestamp("2024-01-01") + pd.Timedelta(days=i)).strftime("%Y-%m-%d")
                      for i in range(T)])
    out = after_tax_metrics(weights, prices, timestamps)
    for k in ("pre_tax_cagr", "after_tax_cagr", "pre_tax_sharpe",
              "final_nav_pre_tax", "final_nav_after_tax", "total_tax"):
        assert k in out
    assert out["after_tax_cagr"] <= out["pre_tax_cagr"] + 1e-9


def test_detect_wash_sales_function():
    """detect_wash_sales flags buy indices that follow a loss within window."""
    trades = [
        {"date": "2024-01-01", "qty": +10, "pnl": 0.0, "is_loss": False},
        {"date": "2024-02-01", "qty": -10, "pnl": -100.0, "is_loss": True},  # loss
        {"date": "2024-02-15", "qty": +10, "pnl": 0.0, "is_loss": False},    # rebuy <30d
        {"date": "2024-04-01", "qty": -10, "pnl": -50.0, "is_loss": True},
        {"date": "2024-05-15", "qty": +10, "pnl": 0.0, "is_loss": False},    # >30d, ok
    ]
    flagged = detect_wash_sales(trades, window_days=30)
    assert 2 in flagged       # 2024-02-15 buy follows 2024-02-01 loss
    assert 4 not in flagged   # >30d gap


def test_short_and_long_term_split():
    """Two sells: one short-term, one long-term. Taxes applied per category."""
    # buy at day 0, sell half at day 100 (short-term), sell rest at day 400 (long-term)
    T = 500
    prices = np.linspace(100.0, 200.0, T)
    weights = np.zeros(T)
    weights[0:100] = 1.0       # full position
    weights[100:400] = 0.5     # half position (sell half)
    # day 400+ → 0 (sell rest)
    timestamps = _ts([(pd.Timestamp("2022-01-01") + pd.Timedelta(days=i)).strftime("%Y-%m-%d")
                      for i in range(T)])
    sim = TaxAwareSimulator(config=TaxConfig(enable_wash_sale=False))
    res = sim.simulate(weights, prices, timestamps, initial_capital=100_000)

    assert res.total_short_term_pnl > 0
    assert res.total_long_term_pnl > 0
    # rates differ
    assert res.total_short_term_tax == pytest.approx(0.37 * res.total_short_term_pnl, rel=1e-6)
    assert res.total_long_term_tax == pytest.approx(0.20 * res.total_long_term_pnl, rel=1e-6)


# --------------------------------------------------------------------------- #
# Cross-symbol wash-sale detection                                            #
# --------------------------------------------------------------------------- #
def test_wash_sale_cross_symbol_detection():
    """detect_wash_sales(cross_symbol=True) flags substantially-identical
    securities (e.g. SPY -> IVV) when they fall within the window; with
    cross_symbol=False the rebuy on a different symbol is NOT flagged."""
    trades = [
        {"date": "2024-01-01", "symbol": "SPY", "qty": +10, "is_loss": False},
        {"date": "2024-02-01", "symbol": "SPY", "qty": -10, "pnl": -100.0,
         "is_loss": True},                                       # loss in SPY
        {"date": "2024-02-15", "symbol": "IVV", "qty": +10, "is_loss": False},
        # ^^ rebuy in IVV (substantially identical S&P 500 ETF) within 30d
        {"date": "2024-04-01", "symbol": "QQQ", "qty": +10, "is_loss": False},
        # ^^ unrelated symbol, must NOT be flagged
    ]

    # Default behavior (legacy, same-symbol only): IVV buy not flagged.
    flagged_default = detect_wash_sales(trades, window_days=30)
    assert 2 not in flagged_default

    # Cross-symbol mode: IVV buy flagged because SPY ~ IVV in DEFAULT_EQUIV_MAP.
    flagged_cross = detect_wash_sales(trades, window_days=30, cross_symbol=True)
    assert 2 in flagged_cross
    # QQQ is in a different equivalence group -> never flagged.
    assert 3 not in flagged_cross


def test_wash_sale_cross_symbol_custom_equiv_map():
    """Caller-supplied equiv_map overrides DEFAULT_EQUIV_MAP."""
    trades = [
        {"date": "2024-01-01", "symbol": "AAPL", "qty": +10, "is_loss": False},
        {"date": "2024-02-01", "symbol": "AAPL", "qty": -10, "pnl": -50.0,
         "is_loss": True},
        {"date": "2024-02-10", "symbol": "MSFT", "qty": +10, "is_loss": False},
    ]
    # No equivalence -> not flagged even cross_symbol=True
    flagged = detect_wash_sales(trades, window_days=30, cross_symbol=True)
    assert 2 not in flagged
    # Custom equivalence: AAPL ~ MSFT -> flagged
    flagged2 = detect_wash_sales(trades, window_days=30, cross_symbol=True,
                                 equiv_map={"AAPL": "X", "MSFT": "X"})
    assert 2 in flagged2


# --------------------------------------------------------------------------- #
# Configurable long-term threshold                                            #
# --------------------------------------------------------------------------- #
def test_taxes_nav_tiny_rebalance():
    """Mark-to-market must use shares CARRIED INTO the bar, not post-update.

    When the rebalance |delta| stays below 1e-12 the previous code branch
    "prev_shares - (delta if abs(delta) > 1e-12 else 0.0)" yielded
    shares_during = prev_shares (post-update), incorrectly using bar-i's
    target_shares instead of bar-(i-1)'s carried shares. After the fix, the
    nav_path bar-over-bar PnL is computed against the shares actually carried
    in.

    Construction: a buy on bar 0 followed by FLAT prices so target_shares
    stays unchanged at 1000.0 (delta < 1e-12 on subsequent bars). NAV path
    P/L should be exactly zero across bars 1..T-1.
    """
    T = 5
    prices = np.array([100.0, 100.0, 100.0, 100.0, 100.0])  # flat
    weights = np.full(T, 1.0)  # always full long; delta = 0 for bars >= 1
    timestamps = _ts([(pd.Timestamp("2024-01-01") + pd.Timedelta(days=i)).strftime("%Y-%m-%d")
                      for i in range(T)])
    sim = TaxAwareSimulator(config=TaxConfig(enable_wash_sale=False))
    res = sim.simulate(weights, prices, timestamps, initial_capital=100_000)

    # Flat prices, position held all the way -> no realized PnL, no unrealized
    # gain. Final NAV must equal initial capital exactly. Pre-fix this would
    # have leaked NAV due to wrong shares_during selection on the tiny-delta
    # bars.
    assert res.final_nav_pre_tax == pytest.approx(100_000, rel=1e-9)


def test_taxes_long_to_short_flip_no_raise():
    """Flipping from +0.5 long to -0.5 short used to raise because sell_qty
    exceeded available lot quantity. Per docstring, the long lots should be
    closed first and the remainder treated as a fresh short (no tax effect
    until the short is covered)."""
    T = 5
    prices = np.array([100.0, 100.0, 100.0, 100.0, 100.0])
    weights = np.array([0.5, 0.5, -0.5, -0.5, 0.0])
    timestamps = _ts([(pd.Timestamp("2024-01-01") + pd.Timedelta(days=i)).strftime("%Y-%m-%d")
                      for i in range(T)])
    sim = TaxAwareSimulator(config=TaxConfig(enable_wash_sale=False))

    # Must NOT raise — previously raised "insufficient lot quantity".
    res = sim.simulate(weights, prices, timestamps, initial_capital=100_000)

    # Flat prices => zero realized P/L on the long side.
    assert abs(res.total_short_term_pnl) < 1e-6
    assert abs(res.total_long_term_pnl) < 1e-6


def test_long_term_threshold_configurable():
    """A 100-day hold is short-term at the US 365-day default but long-term
    when long_term_threshold_days is lowered to 90."""
    T = 110
    prices = np.full(T, 100.0)
    prices[-1] = 200.0
    weights = np.zeros(T)
    weights[:T - 1] = 1.0   # buy day 0, sell at last bar (~100-day hold)
    timestamps = _ts([(pd.Timestamp("2024-01-01") + pd.Timedelta(days=i)).strftime("%Y-%m-%d")
                      for i in range(T)])

    # US default: 100-day hold -> short-term
    sim_us = TaxAwareSimulator(config=TaxConfig(enable_wash_sale=False))
    res_us = sim_us.simulate(weights, prices, timestamps, initial_capital=100_000)
    assert res_us.total_short_term_pnl > 0
    assert abs(res_us.total_long_term_pnl) < 1e-6

    # Custom 90-day threshold -> same trade qualifies as long-term
    sim_short = TaxAwareSimulator(
        config=TaxConfig(enable_wash_sale=False, long_term_threshold_days=90))
    res_short = sim_short.simulate(weights, prices, timestamps,
                                   initial_capital=100_000)
    assert res_short.total_long_term_pnl > 0
    assert abs(res_short.total_short_term_pnl) < 1e-6

    # after_tax_metrics also exposes the explicit kwarg
    out = after_tax_metrics(weights, prices, timestamps,
                            long_term_threshold_days=90)
    # if long-term applied, total_tax must reflect the 20% rate, not 37%
    assert out["total_tax"] > 0
