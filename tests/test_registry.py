"""Tests for quantforge.registry — SQLite-backed backtest registry."""
from __future__ import annotations

import os

import numpy as np
import pandas as pd
import pytest

from quantforge.registry import (
    BacktestRegistry,
    RegistryEntry,
    hash_config,
    store_backtest_result,
)


# ---------- fixtures ----------

@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "registry.db")


@pytest.fixture
def reg(db_path):
    return BacktestRegistry(db_path=db_path)


def _sample_metrics(calmar=1.5, sharpe=1.2, mdd=-15.0, cagr=22.5):
    return {
        "cagr": cagr, "mdd": mdd, "calmar": calmar, "sharpe": sharpe,
        "sortino": 1.4, "mar": calmar, "skew": -0.1, "kurtosis": 3.2,
        "win_rate": 0.55, "profit_factor": 1.8,
        "n_periods": 1000, "final_nav": 5.5,
    }


# ---------- core CRUD ----------

def test_store_and_retrieve(reg):
    eid = reg.store(
        strategy_class="MomentumStrategy",
        strategy_params={"lookback": 20, "threshold": 0.0},
        asset="SPY",
        period_start="1995-01-01",
        period_end="2012-12-31",
        metrics=_sample_metrics(),
        tags=["momentum", "is"],
    )
    assert isinstance(eid, int) and eid > 0

    entry = reg.get(eid)
    assert entry is not None
    assert isinstance(entry, RegistryEntry)
    assert entry.strategy_class == "MomentumStrategy"
    assert entry.strategy_params == {"lookback": 20, "threshold": 0.0}
    assert entry.asset == "SPY"
    assert entry.period_start == "1995-01-01"
    assert entry.period_end == "2012-12-31"
    assert entry.metrics["calmar"] == 1.5
    assert entry.tags == ["momentum", "is"]
    assert entry.config_hash  # non-empty


def test_dedup_same_config(reg):
    args = dict(
        strategy_class="MeanRevStrategy",
        strategy_params={"period": 5, "z": 1.5},
        asset="QQQ",
        period_start="1995-01-01",
        period_end="2012-12-31",
        metrics=_sample_metrics(),
    )
    id1 = reg.store(**args)
    id2 = reg.store(**args)  # same config_hash -> dedup
    assert id1 == id2
    assert reg.count() == 1


def test_insert_or_ignore_duplicate_returns_existing_id(reg):
    """When a duplicate insert is ignored, return the existing row's id.

    Regression: a previous implementation trusted lastrowid after
    INSERT OR IGNORE; sqlite leaves lastrowid stale across an ignored
    insert when other rows have been written, which can return the wrong
    id. Insert several distinct rows, then re-insert the first config and
    confirm the id matches the original first row.
    """
    args1 = dict(
        strategy_class="StratX",
        strategy_params={"v": 1},
        asset="SPY",
        period_start="1995-01-01",
        period_end="2012-12-31",
        metrics=_sample_metrics(calmar=1.0),
    )
    args2 = dict(
        strategy_class="StratX",
        strategy_params={"v": 2},
        asset="SPY",
        period_start="1995-01-01",
        period_end="2012-12-31",
        metrics=_sample_metrics(calmar=1.5),
    )
    args3 = dict(
        strategy_class="StratX",
        strategy_params={"v": 3},
        asset="SPY",
        period_start="1995-01-01",
        period_end="2012-12-31",
        metrics=_sample_metrics(calmar=2.0),
    )
    id1 = reg.store(**args1)
    id2 = reg.store(**args2)
    id3 = reg.store(**args3)
    assert {id1, id2, id3} == {id1, id2, id3}
    assert len({id1, id2, id3}) == 3
    # Now re-insert args1 — should ignore + return id1, not id3 + 1.
    id1_dup = reg.store(**args1)
    assert id1_dup == id1
    assert reg.count() == 3
    # And re-inserting args2 must return id2.
    assert reg.store(**args2) == id2


def test_query_handles_null_metric_values(reg):
    """A row with null/non-numeric metric values must not crash filter queries
    or be incorrectly included by the comparison filter.
    """
    # Row with all numeric metrics
    reg.store(
        "S", {"v": 1}, "SPY", "1995-01-01", "2012-12-31",
        _sample_metrics(calmar=2.5),
    )
    # Row with null calmar (json null)
    reg.store(
        "S", {"v": 2}, "SPY", "1995-01-01", "2012-12-31",
        {**_sample_metrics(), "calmar": None},
    )
    # Row with non-numeric calmar (string)
    reg.store(
        "S", {"v": 3}, "SPY", "1995-01-01", "2012-12-31",
        {**_sample_metrics(), "calmar": "n/a"},
    )
    # Row with calmar key entirely missing
    metrics_missing = _sample_metrics()
    metrics_missing.pop("calmar")
    reg.store(
        "S", {"v": 4}, "SPY", "1995-01-01", "2012-12-31",
        metrics_missing,
    )

    # Query without filter still returns all four
    assert len(reg.query()) == 4

    # Filter on min_calmar must not crash AND must drop the null/string/missing rows
    high = reg.query(min_calmar=1.0)
    assert len(high) == 1
    assert high[0].metrics["calmar"] == 2.5

    # best_by must also skip non-numeric rows
    best = reg.best_by(metric="calmar", n=10)
    assert len(best) == 1
    assert best[0].metrics["calmar"] == 2.5


# ---------- query ----------

def test_query_by_strategy_class(reg):
    reg.store("StratA", {"x": 1}, "SPY", "1995-01-01", "2012-12-31",
              _sample_metrics(calmar=1.0))
    reg.store("StratB", {"x": 1}, "SPY", "1995-01-01", "2012-12-31",
              _sample_metrics(calmar=2.0))
    reg.store("StratA", {"x": 2}, "SPY", "1995-01-01", "2012-12-31",
              _sample_metrics(calmar=3.0))

    a_entries = reg.query(strategy_class="StratA")
    assert len(a_entries) == 2
    assert all(e.strategy_class == "StratA" for e in a_entries)

    b_entries = reg.query(strategy_class="StratB")
    assert len(b_entries) == 1
    assert b_entries[0].strategy_class == "StratB"


def test_query_by_min_calmar(reg):
    reg.store("S", {"v": 1}, "SPY", "1995-01-01", "2012-12-31",
              _sample_metrics(calmar=0.5))
    reg.store("S", {"v": 2}, "SPY", "1995-01-01", "2012-12-31",
              _sample_metrics(calmar=1.5))
    reg.store("S", {"v": 3}, "SPY", "1995-01-01", "2012-12-31",
              _sample_metrics(calmar=3.0))

    high = reg.query(min_calmar=1.0)
    assert len(high) == 2
    assert all(e.metrics["calmar"] >= 1.0 for e in high)

    very_high = reg.query(min_calmar=2.5)
    assert len(very_high) == 1
    assert very_high[0].metrics["calmar"] == 3.0


def test_query_by_tags(reg):
    reg.store("S", {"v": 1}, "SPY", "1995-01-01", "2012-12-31",
              _sample_metrics(), tags=["is", "momentum"])
    reg.store("S", {"v": 2}, "SPY", "1995-01-01", "2012-12-31",
              _sample_metrics(), tags=["oos", "momentum"])
    reg.store("S", {"v": 3}, "SPY", "1995-01-01", "2012-12-31",
              _sample_metrics(), tags=["is", "meanrev"])

    is_entries = reg.query(tags=["is"])
    assert len(is_entries) == 2
    momo_entries = reg.query(tags=["momentum"])
    assert len(momo_entries) == 2
    is_momo = reg.query(tags=["is", "momentum"])
    assert len(is_momo) == 1
    assert "is" in is_momo[0].tags and "momentum" in is_momo[0].tags


# ---------- best_by ----------

def test_best_by_calmar(reg):
    cals = [0.3, 1.5, 2.7, 0.8, 3.5, 1.1]
    for i, c in enumerate(cals):
        reg.store("S", {"v": i}, "SPY", "1995-01-01", "2012-12-31",
                  _sample_metrics(calmar=c))

    top3 = reg.best_by(metric="calmar", n=3)
    assert len(top3) == 3
    cals_returned = [e.metrics["calmar"] for e in top3]
    assert cals_returned == sorted(cals_returned, reverse=True)
    assert cals_returned[0] == 3.5


# ---------- DataFrame ----------

def test_to_dataframe_columns(reg):
    reg.store("S", {"x": 1}, "SPY", "1995-01-01", "2012-12-31",
              _sample_metrics(), tags=["is"])
    reg.store("S", {"x": 2}, "QQQ", "1995-01-01", "2012-12-31",
              _sample_metrics())

    df = reg.to_dataframe()
    expected = {
        "id", "strategy_class", "strategy_params", "asset",
        "period_start", "period_end", "metrics", "timestamp",
        "git_hash", "config_hash", "tags",
    }
    assert expected.issubset(set(df.columns))
    assert len(df) == 2
    # JSON columns decoded back to Python objects
    assert isinstance(df.iloc[0]["strategy_params"], dict)
    assert isinstance(df.iloc[0]["metrics"], dict)
    assert isinstance(df.iloc[0]["tags"], list)


def test_to_dataframe_empty(reg):
    df = reg.to_dataframe()
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 0
    assert "strategy_class" in df.columns


# ---------- delete ----------

def test_delete(reg):
    eid = reg.store("S", {"v": 1}, "SPY", "1995-01-01", "2012-12-31",
                    _sample_metrics())
    assert reg.count() == 1
    assert reg.delete(eid) is True
    assert reg.count() == 0
    assert reg.get(eid) is None
    # deleting non-existent
    assert reg.delete(99999) is False


# ---------- hash_config ----------

def test_hash_config_deterministic():
    h1 = hash_config("S", {"a": 1, "b": 2}, "SPY", "1995-01-01", "2012-12-31")
    h2 = hash_config("S", {"b": 2, "a": 1}, "SPY", "1995-01-01", "2012-12-31")
    assert h1 == h2  # key order does not matter

    h3 = hash_config("S", {"a": 1, "b": 2}, "SPY", "1995-01-01", "2012-12-31")
    assert h1 == h3

    # Differ on every component
    assert h1 != hash_config("OTHER", {"a": 1, "b": 2}, "SPY", "1995-01-01", "2012-12-31")
    assert h1 != hash_config("S", {"a": 1, "b": 3}, "SPY", "1995-01-01", "2012-12-31")
    assert h1 != hash_config("S", {"a": 1, "b": 2}, "QQQ", "1995-01-01", "2012-12-31")
    assert h1 != hash_config("S", {"a": 1, "b": 2}, "SPY", "2000-01-01", "2012-12-31")
    assert h1 != hash_config("S", {"a": 1, "b": 2}, "SPY", "1995-01-01", "2010-12-31")


# ---------- store_backtest_result convenience ----------

def test_store_from_backtest_result(db_path):
    """Convenience function takes a BacktestResult-like object."""
    from quantforge.core.engine import BacktestResult
    from quantforge.core.metrics import compute_metrics

    rng = np.random.default_rng(42)
    rets = rng.normal(0.0005, 0.01, 500)
    nav = np.cumprod(1.0 + rets)
    weights = np.ones(500) * 0.5
    timestamps = pd.date_range("1995-01-01", periods=500, freq="B").values
    metrics = compute_metrics(rets, ppy=252)

    result = BacktestResult(
        metrics=metrics,
        nav=nav,
        rets=rets,
        weights=weights,
        timestamps=timestamps,
    )

    eid = store_backtest_result(
        result,
        strategy_class="DummyStrategy",
        strategy_params={"window": 10},
        asset="SPY",
        registry_path=db_path,
        tags=["is", "test"],
    )
    assert eid > 0

    reg = BacktestRegistry(db_path=db_path)
    entry = reg.get(eid)
    assert entry is not None
    assert entry.strategy_class == "DummyStrategy"
    assert entry.asset == "SPY"
    assert entry.tags == ["is", "test"]
    # period extracted from timestamps
    assert entry.period_start == pd.Timestamp(timestamps[0]).strftime("%Y-%m-%d")
    assert entry.period_end == pd.Timestamp(timestamps[-1]).strftime("%Y-%m-%d")
    # metrics round-trip
    assert entry.metrics["calmar"] == metrics.calmar
    assert entry.metrics["sharpe"] == metrics.sharpe


# ---------------------------------------------------------------------------
# Hardening: WAL on registry, metric whitelist, BEGIN IMMEDIATE serialized
# ---------------------------------------------------------------------------


def test_sqlite_wal_enabled(db_path):
    """BacktestRegistry must enable WAL + busy_timeout on its connections."""
    import sqlite3 as _sql

    BacktestRegistry(db_path=db_path)  # init schema
    with _sql.connect(db_path) as con:
        mode = con.execute("PRAGMA journal_mode").fetchone()[0]
        bt = con.execute("PRAGMA busy_timeout").fetchone()[0]
    # journal_mode is sticky per file; opening with WAL once persists.
    assert str(mode).lower() == "wal"
    # busy_timeout is per-connection and not sticky; verify a new
    # registry-managed connection sets it.
    reg = BacktestRegistry(db_path=db_path)
    with reg._conn() as c:
        bt = c.execute("PRAGMA busy_timeout").fetchone()[0]
        sync = c.execute("PRAGMA synchronous").fetchone()[0]
        autockpt = c.execute("PRAGMA wal_autocheckpoint").fetchone()[0]
    # bumped from 5000 -> 30000 in v1.4 to cover slow VACUUM/backup windows.
    assert int(bt) >= 30000
    # synchronous=NORMAL is encoded as 1 by SQLite.
    assert int(sync) == 1
    # wal_autocheckpoint pinned to 1000 frames in v1.4 to bound WAL growth.
    assert int(autockpt) == 1000


def test_best_by_metric_whitelist(reg):
    """best_by must reject metric names outside the explicit whitelist."""
    # An alphanumeric-but-unsupported name must be rejected even though the
    # old loose check allowed it.
    with pytest.raises(ValueError, match="invalid metric name"):
        reg.best_by(metric="totally_made_up_score")
    # The whitelisted names must continue to work.
    for ok in ("calmar", "sharpe", "mdd", "cagr", "sortino"):
        reg.best_by(metric=ok, n=1)


def test_registry_connection_autocommit(reg):
    """``_conn`` must yield a connection in autocommit mode.

    The previous default (sqlite3 implicit transactions) layered an
    auto-BEGIN under every statement, so ``store()``'s explicit
    ``BEGIN IMMEDIATE`` raised ``cannot start a transaction within a
    transaction``. Autocommit (``isolation_level=None``) lets ``store()``
    own its own transaction boundaries.
    """
    with reg._conn() as c:
        assert c.isolation_level is None


def test_store_dedup_under_concurrency(reg):
    """``store()`` must serialize via BEGIN IMMEDIATE: two writers racing
    the same config_hash both come away with the same row id and never
    raise ``cannot start a transaction within a transaction`` on the
    autocommit connection."""
    import threading

    rid_box: dict[int, int] = {}
    barrier = threading.Barrier(4)

    def _store(slot: int) -> None:
        barrier.wait()
        rid = reg.store(
            strategy_class="MA", strategy_params={"w": 5}, asset="SPY",
            period_start="2010-01-01", period_end="2020-12-31",
            metrics={"sharpe": 1.1}, tags=["t1"],
        )
        rid_box[slot] = rid

    threads = [threading.Thread(target=_store, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(set(rid_box.values())) == 1
    assert reg.count() == 1
