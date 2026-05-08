"""Tests for quantforge.registry.journal.TradeJournal."""
from __future__ import annotations

import datetime as _dt
import os

import pandas as pd
import pytest

from quantforge.registry.journal import TradeJournal, JournalEntry


@pytest.fixture
def journal(tmp_path) -> TradeJournal:
    db = str(tmp_path / "journal.db")
    return TradeJournal(db_path=db)


def test_log_and_retrieve(journal):
    rid = journal.log_trade(
        strategy_name="MACross", symbol="SPY", side="BUY",
        quantity=10, fill_price=400.0, signal_value=0.85,
        commission=1.0, slippage_bps=2.5, status="FILLED",
        strategy_version="v1.2", order_id="ord-001", note="entry",
    )
    assert rid > 0
    e = journal.get(rid)
    assert isinstance(e, JournalEntry)
    assert e.strategy_name == "MACross"
    assert e.strategy_version == "v1.2"
    assert e.symbol == "SPY"
    assert e.side == "BUY"
    assert e.quantity == 10.0
    assert e.fill_price == 400.0
    # signed notional: BUY -> +qty*price
    assert e.notional == pytest.approx(10 * 400.0)
    assert e.commission == 1.0
    assert e.slippage_bps == 2.5
    assert e.signal_value == 0.85
    assert e.status == "FILLED"
    assert e.order_id == "ord-001"
    assert e.note == "entry"
    assert journal.count() == 1


def test_log_sell_signed_notional(journal):
    rid = journal.log_trade(
        strategy_name="MACross", symbol="SPY", side="SELL",
        quantity=5, fill_price=410.0, signal_value=0.0,
    )
    e = journal.get(rid)
    # SELL -> negative notional
    assert e.notional == pytest.approx(-5 * 410.0)


def test_invalid_side_raises(journal):
    with pytest.raises(ValueError):
        journal.log_trade(
            strategy_name="X", symbol="SPY", side="HOLD",
            quantity=1, fill_price=1.0, signal_value=0.0,
        )


def test_invalid_status_raises(journal):
    with pytest.raises(ValueError):
        journal.log_trade(
            strategy_name="X", symbol="SPY", side="BUY",
            quantity=1, fill_price=1.0, signal_value=0.0, status="WTF",
        )


def test_update_status(journal):
    rid = journal.log_trade(
        strategy_name="MACross", symbol="SPY", side="BUY",
        quantity=10, fill_price=399.0, signal_value=0.5,
        status="PENDING",
    )
    e = journal.get(rid)
    assert e.status == "PENDING"

    ok = journal.update_status(rid, "FILLED", fill_price=401.0)
    assert ok is True

    e2 = journal.get(rid)
    assert e2.status == "FILLED"
    assert e2.fill_price == 401.0
    # notional recomputed off updated fill price
    assert e2.notional == pytest.approx(10 * 401.0)

    # missing id -> False
    assert journal.update_status(999_999, "CANCELED") is False


def test_query_by_strategy(journal):
    journal.log_trade("MACross", "SPY", "BUY", 1, 100.0, 0.0)
    journal.log_trade("MeanRev", "SPY", "BUY", 1, 100.0, 0.0)
    journal.log_trade("MACross", "QQQ", "BUY", 1, 200.0, 0.0)

    rows = journal.query(strategy_name="MACross")
    assert len(rows) == 2
    assert all(r.strategy_name == "MACross" for r in rows)


def test_query_by_symbol(journal):
    journal.log_trade("MACross", "SPY", "BUY", 1, 100.0, 0.0)
    journal.log_trade("MACross", "QQQ", "BUY", 1, 200.0, 0.0)
    journal.log_trade("MACross", "SPY", "SELL", 1, 110.0, 0.0)

    rows = journal.query(symbol="SPY")
    assert len(rows) == 2
    assert all(r.symbol == "SPY" for r in rows)


def test_query_by_status(journal):
    journal.log_trade("MACross", "SPY", "BUY", 1, 100.0, 0.0, status="FILLED")
    journal.log_trade("MACross", "SPY", "BUY", 1, 100.0, 0.0, status="PENDING")
    rows = journal.query(status="PENDING")
    assert len(rows) == 1
    assert rows[0].status == "PENDING"


def test_query_since_date(journal):
    # Inject deterministic timestamps via the _now seam to avoid relying on
    # wall-clock sleeps (flaky in CI). Timestamps are second-resolution.
    t_old = _dt.datetime(2024, 1, 1, 12, 0, 0)
    t_cutoff = _dt.datetime(2024, 1, 1, 12, 0, 5)
    t_new = _dt.datetime(2024, 1, 1, 12, 0, 10)
    journal.log_trade("MACross", "SPY", "BUY", 1, 100.0, 0.0, _now=t_old)
    cutoff = t_cutoff.isoformat(timespec="seconds")
    journal.log_trade("MACross", "SPY", "SELL", 1, 110.0, 0.0, _now=t_new)

    rows = journal.query(since=cutoff)
    assert len(rows) == 1
    assert rows[0].side == "SELL"


def test_query_limit(journal):
    for i in range(5):
        journal.log_trade("MACross", "SPY", "BUY", 1, 100.0 + i, 0.0)
    rows = journal.query(limit=2)
    assert len(rows) == 2


def test_daily_pnl_aggregates(journal):
    # 3 fills today: BUY 10@400, SELL 5@410, SELL 5@420
    # cash flow = -(-)notional - commission per row.
    # BUY notional=+4000 -> cash -4000
    # SELL notional=-2050 -> cash +2050
    # SELL notional=-2100 -> cash +2100
    # net = +150, n_trades=3
    journal.log_trade("MACross", "SPY", "BUY", 10, 400.0, 0.0)
    journal.log_trade("MACross", "SPY", "SELL", 5, 410.0, 0.0)
    journal.log_trade("MACross", "SPY", "SELL", 5, 420.0, 0.0)

    df = journal.daily_pnl()
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["date", "pnl", "n_trades"]
    assert len(df) == 1
    assert df.iloc[0]["n_trades"] == 3
    assert df.iloc[0]["pnl"] == pytest.approx(150.0)


def test_daily_pnl_filters_by_strategy(journal):
    journal.log_trade("MACross", "SPY", "BUY", 1, 100.0, 0.0)
    journal.log_trade("Other", "SPY", "BUY", 1, 100.0, 0.0)
    df = journal.daily_pnl(strategy_name="MACross")
    assert int(df.iloc[0]["n_trades"]) == 1


def test_daily_pnl_skips_non_filled(journal):
    journal.log_trade("MACross", "SPY", "BUY", 1, 100.0, 0.0, status="PENDING")
    df = journal.daily_pnl()
    assert df.empty


def test_position_history_reconstructs(journal):
    journal.log_trade("MACross", "SPY", "BUY", 10, 400.0, 0.0)
    journal.log_trade("MACross", "SPY", "BUY", 5, 405.0, 0.0)
    journal.log_trade("MACross", "SPY", "SELL", 8, 410.0, 0.0)
    journal.log_trade("MACross", "QQQ", "BUY", 100, 50.0, 0.0)

    df = journal.position_history("SPY")
    assert list(df.columns) == ["timestamp", "side", "quantity",
                                "fill_price", "position"]
    assert len(df) == 3
    # cumulative position: 10, 15, 7
    assert list(df["position"]) == [10.0, 15.0, 7.0]


def test_position_history_filters_by_strategy(journal):
    journal.log_trade("A", "SPY", "BUY", 10, 400.0, 0.0)
    journal.log_trade("B", "SPY", "BUY", 5, 401.0, 0.0)
    df = journal.position_history("SPY", strategy_name="A")
    assert len(df) == 1
    assert df["position"].iloc[0] == 10.0


def test_position_history_empty_when_no_fills(journal):
    journal.log_trade("MACross", "SPY", "BUY", 10, 400.0, 0.0, status="PENDING")
    df = journal.position_history("SPY")
    assert df.empty


def test_export_csv(journal, tmp_path):
    journal.log_trade("MACross", "SPY", "BUY", 10, 400.0, 0.5)
    journal.log_trade("MACross", "SPY", "SELL", 5, 410.0, -0.5)
    out = tmp_path / "out.csv"
    n = journal.export_csv(str(out))
    assert n == 2
    assert out.exists()
    df = pd.read_csv(out)
    assert len(df) == 2
    assert {"id", "timestamp", "strategy_name", "symbol", "side",
            "quantity", "fill_price", "notional", "status"}.issubset(df.columns)


def test_export_csv_with_filters(journal, tmp_path):
    journal.log_trade("MACross", "SPY", "BUY", 1, 100.0, 0.0)
    journal.log_trade("Other", "SPY", "BUY", 1, 100.0, 0.0)
    out = tmp_path / "filtered.csv"
    n = journal.export_csv(str(out), strategy_name="MACross")
    assert n == 1
    df = pd.read_csv(out)
    assert df["strategy_name"].iloc[0] == "MACross"


def test_to_dataframe_columns(journal):
    journal.log_trade("MACross", "SPY", "BUY", 10, 400.0, 0.5,
                      strategy_version="v1.2", order_id="o1", note="n1")
    df = journal.to_dataframe()
    expected = ["id", "timestamp", "strategy_name", "strategy_version",
                "symbol", "side", "quantity", "fill_price", "notional",
                "commission", "slippage_bps", "signal_value", "status",
                "order_id", "note"]
    assert list(df.columns) == expected
    assert len(df) == 1


def test_to_dataframe_empty(journal):
    df = journal.to_dataframe()
    assert df.empty
    assert "timestamp" in df.columns


def test_persistence(tmp_path):
    db = str(tmp_path / "persist.db")
    j1 = TradeJournal(db_path=db)
    rid = j1.log_trade("MACross", "SPY", "BUY", 1, 100.0, 0.0)
    j2 = TradeJournal(db_path=db)
    assert j2.get(rid) is not None
    assert j2.count() == 1


def test_default_db_path_creates_dir(tmp_path, monkeypatch):
    nested = tmp_path / "deep" / "dir" / "trade.db"
    j = TradeJournal(db_path=str(nested))
    assert os.path.isdir(os.path.dirname(str(nested)))
    j.log_trade("X", "SPY", "BUY", 1, 1.0, 0.0)
    assert j.count() == 1


def test_journal_rejects_zero_price(journal):
    """Negative or NaN price always blocks. fill_price=0 is allowed only
    when the caller explicitly passes ``kind='closure'``."""
    # NaN and negative prices are always rejected.
    with pytest.raises(ValueError, match="price must be >= 0"):
        journal.log_trade("MACross", "SPY", "BUY", 1, -10.0, 0.0)
    with pytest.raises(ValueError, match="price must be >= 0"):
        journal.log_trade("MACross", "SPY", "BUY", 1, float("nan"), 0.0)
    # fill_price=0 without kind='closure' is rejected (would corrupt PnL).
    with pytest.raises(ValueError, match="closure"):
        journal.log_trade("MACross", "SPY", "BUY", 1, 0.0, 0.85)
    # fill_price=0 with kind='closure' is the explicit closure case and
    # must succeed regardless of signal_value (e.g. derivatives flatten
    # while the signal is still active).
    rid = journal.log_trade(
        "MACross", "SPY", "SELL", 1, 0.0, 0.85, kind="closure",
    )
    assert rid > 0
    assert journal.count() == 1
    e = journal.get(rid)
    assert e.fill_price == 0.0
    assert e.signal_value == 0.85


def test_journal_closure_kind_invalid(journal):
    """``kind`` only accepts 'trade' (default) or 'closure'."""
    with pytest.raises(ValueError, match="kind"):
        journal.log_trade(
            "MACross", "SPY", "BUY", 1, 100.0, 0.0, kind="bogus",
        )


def test_journal_sqlite_wal_enabled(tmp_path):
    """TradeJournal must enable WAL + busy_timeout on its connections."""
    import sqlite3 as _sql

    j = TradeJournal(db_path=str(tmp_path / "journal.db"))
    with _sql.connect(j.db_path) as con:
        mode = con.execute("PRAGMA journal_mode").fetchone()[0]
    assert str(mode).lower() == "wal"
    with j._conn() as c:
        bt = c.execute("PRAGMA busy_timeout").fetchone()[0]
    assert int(bt) >= 5000


def test_journal_no_real_sleep_dependency():
    """The test module must not depend on real wall-clock sleeps for ordering.

    Guards against re-introducing flaky time.sleep(1.1) calls. Walks this
    module's AST and asserts ``time.sleep(...)`` is never invoked.
    """
    import ast
    import pathlib

    src = pathlib.Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)

    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
            if f.value.id == "time" and f.attr == "sleep":
                offenders.append(f"line {node.lineno}: time.sleep(...)")
    assert not offenders, (
        "test_journal.py must not call time.sleep — use the _now=... seam: "
        + "; ".join(offenders)
    )
