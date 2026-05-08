"""Tests for quantforge.monitoring.dashboard.

The dashboard helpers ``compute_dashboard_metrics`` and
``fetch_dashboard_data`` are pure pandas / sqlite and run without Streamlit.
``run_dashboard`` import is exercised via a Streamlit smoke test that skips
when streamlit is unavailable.
"""
from __future__ import annotations

import datetime as _dt
import math
import os
import sqlite3

import pandas as pd
import pytest

from quantforge.monitoring.dashboard import (
    DashboardConfig,
    STREAMLIT_AVAILABLE,
    compute_dashboard_metrics,
    fetch_dashboard_data,
)
from quantforge.registry.journal import TradeJournal


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_trades_df(rows):
    """Build a trades DataFrame with the journal schema columns."""
    df = pd.DataFrame(rows)
    cols = ["id", "timestamp", "strategy_name", "strategy_version", "symbol",
            "side", "quantity", "fill_price", "notional", "commission",
            "slippage_bps", "signal_value", "status", "order_id", "note"]
    for c in cols:
        if c not in df.columns:
            if c in ("quantity", "fill_price", "notional", "commission",
                     "slippage_bps", "signal_value"):
                df[c] = 0.0
            elif c == "id":
                df[c] = list(range(1, len(df) + 1))
            else:
                df[c] = ""
    return df[cols]


def _signed_notional(side: str, qty: float, price: float) -> float:
    return qty * price if side == "BUY" else -qty * price


# ---------------------------------------------------------------------------
# compute_dashboard_metrics
# ---------------------------------------------------------------------------


def test_dashboard_metrics_basic():
    """Synthetic trades DataFrame produces all expected metric keys."""
    # 3 round-trip pairs across 3 different days. SELL produces positive cash
    # flow (-notional - commission, with notional negative for SELL).
    rows = [
        # Day 1: BUY then SELL at higher price -> profit
        dict(timestamp="2026-01-02T09:30:00", strategy_name="A", symbol="SPY",
             side="BUY", quantity=10.0, fill_price=400.0,
             notional=_signed_notional("BUY", 10.0, 400.0),
             commission=1.0, status="FILLED"),
        dict(timestamp="2026-01-02T15:55:00", strategy_name="A", symbol="SPY",
             side="SELL", quantity=10.0, fill_price=405.0,
             notional=_signed_notional("SELL", 10.0, 405.0),
             commission=1.0, status="FILLED"),
        # Day 2: BUY then SELL at lower price -> loss
        dict(timestamp="2026-01-05T09:30:00", strategy_name="A", symbol="SPY",
             side="BUY", quantity=10.0, fill_price=410.0,
             notional=_signed_notional("BUY", 10.0, 410.0),
             commission=1.0, status="FILLED"),
        dict(timestamp="2026-01-05T15:55:00", strategy_name="A", symbol="SPY",
             side="SELL", quantity=10.0, fill_price=408.0,
             notional=_signed_notional("SELL", 10.0, 408.0),
             commission=1.0, status="FILLED"),
        # Day 3: BUY then SELL at higher price -> profit
        dict(timestamp="2026-01-06T09:30:00", strategy_name="A", symbol="SPY",
             side="BUY", quantity=10.0, fill_price=412.0,
             notional=_signed_notional("BUY", 10.0, 412.0),
             commission=1.0, status="FILLED"),
        dict(timestamp="2026-01-06T15:55:00", strategy_name="A", symbol="SPY",
             side="SELL", quantity=10.0, fill_price=415.0,
             notional=_signed_notional("SELL", 10.0, 415.0),
             commission=1.0, status="FILLED"),
    ]
    df = _make_trades_df(rows)

    m = compute_dashboard_metrics(df)
    assert set(m.keys()) == {"total_pnl", "sharpe", "max_dd", "n_trades",
                             "win_rate"}
    # Total PnL = sum of (-notional - commission) across all rows.
    expected_total = sum(-r["notional"] - r["commission"] for r in rows)
    assert m["total_pnl"] == pytest.approx(expected_total)
    assert m["n_trades"] == 6
    # Wins: 3 SELLs with positive cash flow.
    assert m["win_rate"] == pytest.approx(3 / 6)
    # Max DD <= 0 by construction.
    assert m["max_dd"] <= 0.0
    # Sharpe is finite (3 daily PnLs with non-zero std).
    assert isinstance(m["sharpe"], float)
    assert not math.isnan(m["sharpe"])


def test_dashboard_metrics_empty():
    """Empty DataFrame returns sane defaults (0 PnL, NaN Sharpe is ok)."""
    empty = pd.DataFrame(columns=["timestamp", "status", "notional",
                                  "commission"])
    m = compute_dashboard_metrics(empty)
    assert m["total_pnl"] == 0.0
    assert m["n_trades"] == 0
    assert m["max_dd"] == 0.0
    assert math.isnan(m["sharpe"])
    assert math.isnan(m["win_rate"])


def test_compute_win_rate():
    """6 wins / 4 losses -> 0.6 win rate."""
    rows = []
    # 6 winning SELLs (positive cash flow): notional negative, no commission
    for i in range(6):
        rows.append(dict(
            timestamp=f"2026-01-0{(i % 5) + 1}T10:00:00",
            strategy_name="W", symbol="SPY",
            side="SELL", quantity=1.0, fill_price=100.0,
            notional=-100.0, commission=0.0, status="FILLED",
        ))
    # 4 losing BUYs (negative cash flow): notional positive
    for i in range(4):
        rows.append(dict(
            timestamp=f"2026-01-0{(i % 5) + 1}T11:00:00",
            strategy_name="W", symbol="SPY",
            side="BUY", quantity=1.0, fill_price=100.0,
            notional=100.0, commission=0.0, status="FILLED",
        ))
    df = _make_trades_df(rows)
    m = compute_dashboard_metrics(df)
    assert m["n_trades"] == 10
    assert m["win_rate"] == pytest.approx(0.6)


def test_compute_max_dd():
    """Hand-computed max DD example.

    Daily PnL: +10, -5, -8, +3
    Equity curve: 10, 5, -3, 0
    Running max: 10, 10, 10, 10
    Drawdown: 0, -5, -13, -10
    Max DD = -13.
    """
    # Build per-trade rows that aggregate to the daily PnL above. Each day
    # has one SELL row with cash flow = daily PnL.
    # cash flow = -notional - commission = -(-pnl) - 0 = pnl. So set
    # notional = -pnl.
    daily = [
        ("2026-01-02", 10.0),
        ("2026-01-05", -5.0),
        ("2026-01-06", -8.0),
        ("2026-01-07", 3.0),
    ]
    rows = []
    for date, pnl in daily:
        rows.append(dict(
            timestamp=f"{date}T15:00:00",
            strategy_name="DD", symbol="SPY",
            side="SELL" if pnl > 0 else "BUY",
            quantity=1.0, fill_price=abs(pnl),
            notional=-pnl,
            commission=0.0, status="FILLED",
        ))
    df = _make_trades_df(rows)
    m = compute_dashboard_metrics(df)
    assert m["total_pnl"] == pytest.approx(0.0)
    assert m["max_dd"] == pytest.approx(-13.0)


# ---------------------------------------------------------------------------
# fetch_dashboard_data
# ---------------------------------------------------------------------------


def test_fetch_data_with_temp_journal(temp_journal_db):
    """Create a temp SQLite journal, populate it, verify fetch shape."""
    j = temp_journal_db
    db = j.db_path
    # 4 trades across two strategies and two symbols.
    j.log_trade("A", "SPY", "BUY", 10, 400.0, 0.5,
                commission=1.0, status="FILLED")
    j.log_trade("A", "SPY", "SELL", 10, 405.0, 0.0,
                commission=1.0, status="FILLED")
    j.log_trade("B", "QQQ", "BUY", 5, 350.0, 0.4,
                commission=0.5, status="FILLED")
    j.log_trade("B", "QQQ", "SELL", 5, 355.0, 0.0,
                commission=0.5, status="FILLED")

    data = fetch_dashboard_data(db)
    assert isinstance(data, dict)
    assert set(data.keys()) >= {"trades", "recent_trades", "equity_curve",
                                "open_positions", "per_strategy", "metrics"}

    trades = data["trades"]
    assert isinstance(trades, pd.DataFrame)
    assert len(trades) == 4
    assert {"timestamp", "strategy_name", "symbol", "side", "notional",
            "commission", "status"}.issubset(trades.columns)

    metrics = data["metrics"]
    assert metrics["n_trades"] == 4
    # Two round trips with positive PnL each: SPY (+50-2) + QQQ (+25-1) = 72
    assert metrics["total_pnl"] == pytest.approx(72.0)

    per_strat = data["per_strategy"]
    assert len(per_strat) == 2
    assert set(per_strat["strategy_name"]) == {"A", "B"}

    positions = data["open_positions"]
    # Both positions netted to zero
    assert positions.empty


def test_fetch_data_missing_journal(tmp_path):
    """Nonexistent file -> empty dict (graceful)."""
    missing = str(tmp_path / "does_not_exist.db")
    assert not os.path.exists(missing)
    out = fetch_dashboard_data(missing)
    assert out == {}


def test_fetch_data_open_positions(temp_journal_db):
    """Open BUY without matching SELL appears in open_positions."""
    j = temp_journal_db
    db = j.db_path
    j.log_trade("A", "SPY", "BUY", 10, 400.0, 0.5,
                commission=1.0, status="FILLED")
    j.log_trade("A", "SPY", "BUY", 5, 401.0, 0.5,
                commission=0.5, status="FILLED")
    data = fetch_dashboard_data(db)
    pos = data["open_positions"]
    assert len(pos) == 1
    row = pos.iloc[0]
    assert row["strategy_name"] == "A"
    assert row["symbol"] == "SPY"
    assert row["position"] == pytest.approx(15.0)


# ---------------------------------------------------------------------------
# Streamlit optional smoke test
# ---------------------------------------------------------------------------


def test_streamlit_optional():
    """Lightweight smoke test that ``run_dashboard`` is importable.

    Does not actually execute the streamlit page (would need a running
    streamlit server). Just verifies import works when streamlit is present.
    """
    pytest.importorskip("streamlit")
    from quantforge.monitoring.dashboard import run_dashboard
    assert callable(run_dashboard)
    assert STREAMLIT_AVAILABLE is True


def test_run_dashboard_raises_without_streamlit(monkeypatch):
    """When streamlit is unavailable the function raises a clear error."""
    import quantforge.monitoring.dashboard as dash_mod
    monkeypatch.setattr(dash_mod, "STREAMLIT_AVAILABLE", False)
    with pytest.raises(RuntimeError, match="streamlit"):
        dash_mod.run_dashboard(DashboardConfig(journal_path="x.db"))


# ---------------------------------------------------------------------------
# DashboardConfig
# ---------------------------------------------------------------------------


def test_dashboard_config_defaults():
    cfg = DashboardConfig()
    assert cfg.journal_path == "quantforge.db"
    assert cfg.refresh_seconds == 30
    assert cfg.show_alerts is True
    assert cfg.show_per_strategy is True
    assert "total_pnl" in cfg.metrics
    assert "sharpe" in cfg.metrics
    assert "max_dd" in cfg.metrics
    assert "n_trades" in cfg.metrics
    assert "win_rate" in cfg.metrics
