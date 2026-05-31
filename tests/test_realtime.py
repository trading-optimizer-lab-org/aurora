"""Tests for the real-time data ingestion adapter.

Run: uv run pytest aurora/tests/test_realtime.py -v
"""
from __future__ import annotations

from collections import deque

import numpy as np
import pandas as pd
import pytest

from aurora.core.realtime import (
    RealtimeAdapter,
    RealtimeConfig,
    StaleDataError,
    SUPPORTED_INTERVALS,
    yfinance_fetch,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bars(symbol: str, n: int, start: str = "2026-01-01 09:30:00") -> pd.DataFrame:
    """Build a synthetic OHLCV DataFrame in canonical long-form."""
    ts = pd.date_range(start=start, periods=n, freq="1min")
    rng = np.random.default_rng(0)
    close = 100.0 + np.cumsum(rng.normal(0, 0.1, n))
    return pd.DataFrame({
        "timestamp": ts,
        "symbol": symbol,
        "open": close,
        "high": close + 0.05,
        "low": close - 0.05,
        "close": close,
        "volume": rng.integers(1000, 5000, n).astype(float),
    })


# ---------------------------------------------------------------------------
# RealtimeConfig
# ---------------------------------------------------------------------------

def test_config_defaults():
    cfg = RealtimeConfig(symbols=["SPY"])
    assert cfg.symbols == ["SPY"]
    assert cfg.interval == "1m"
    assert cfg.poll_seconds == 60
    assert cfg.buffer_max_bars == 1000
    assert cfg.source == "yfinance"


def test_invalid_interval():
    # '2m' is a valid yfinance interval but not in our supported set
    with pytest.raises(ValueError):
        RealtimeConfig(symbols=["SPY"], interval="2m")
    # nonsense string
    with pytest.raises(ValueError):
        RealtimeConfig(symbols=["SPY"], interval="not-a-real-interval")
    # empty symbols
    with pytest.raises(ValueError):
        RealtimeConfig(symbols=[])


def test_supported_intervals_set():
    # safety net: ensure the 4 documented intervals are accepted
    for iv in ("1m", "5m", "15m", "1h"):
        assert iv in SUPPORTED_INTERVALS
        cfg = RealtimeConfig(symbols=["SPY"], interval=iv)
        assert cfg.interval == iv


# ---------------------------------------------------------------------------
# Buffer
# ---------------------------------------------------------------------------

def test_buffer_append_ringbuffer():
    """Add 100 bars to a buffer of maxlen=50 -> only the 50 latest are kept."""
    cfg = RealtimeConfig(symbols=["SPY"], buffer_max_bars=50)
    adapter = RealtimeAdapter(cfg)

    df = _make_bars("SPY", 100)
    appended = adapter.buffer_append(df)
    assert appended == 100  # all rows pass dedup, but deque truncates

    buf = adapter.get_buffer("SPY")
    assert len(buf) == 50
    # latest 50 are kept (oldest dropped)
    expected_ts = df["timestamp"].iloc[-50:].tolist()
    actual_ts = buf["timestamp"].tolist()
    assert actual_ts == expected_ts


def test_dedup():
    """Append same bar twice -> buffer holds 1."""
    cfg = RealtimeConfig(symbols=["SPY"], buffer_max_bars=10)
    adapter = RealtimeAdapter(cfg)

    df = _make_bars("SPY", 1)
    adapter.buffer_append(df)
    adapter.buffer_append(df)  # exact duplicate
    adapter.buffer_append(df)  # again

    buf = adapter.get_buffer("SPY")
    assert len(buf) == 1


def test_dedup_partial_overlap():
    """Append bars 0..9 then 5..14. Only 10..14 should be added."""
    cfg = RealtimeConfig(symbols=["SPY"], buffer_max_bars=100)
    adapter = RealtimeAdapter(cfg)

    df1 = _make_bars("SPY", 10)
    df2 = _make_bars("SPY", 15).iloc[5:]  # bars 5..14, same timestamps as df1[5:]

    adapter.buffer_append(df1)
    n_appended = adapter.buffer_append(df2)
    # only 5 NEW bars (10, 11, 12, 13, 14) should be appended
    assert n_appended == 5
    buf = adapter.get_buffer("SPY")
    assert len(buf) == 15


def test_buffer_get_filter_by_symbol():
    """Multi-symbol buffer: get_buffer returns the correct subset only."""
    cfg = RealtimeConfig(symbols=["SPY", "QQQ"], buffer_max_bars=100)
    adapter = RealtimeAdapter(cfg)

    spy = _make_bars("SPY", 10)
    qqq = _make_bars("QQQ", 7)
    combined = pd.concat([spy, qqq], ignore_index=True)
    adapter.buffer_append(combined)

    spy_buf = adapter.get_buffer("SPY")
    qqq_buf = adapter.get_buffer("QQQ")
    assert len(spy_buf) == 10
    assert len(qqq_buf) == 7
    assert set(spy_buf["symbol"].unique()) == {"SPY"}
    assert set(qqq_buf["symbol"].unique()) == {"QQQ"}


def test_buffer_unknown_symbol_returns_empty():
    cfg = RealtimeConfig(symbols=["SPY"])
    adapter = RealtimeAdapter(cfg)
    out = adapter.get_buffer("NOPE")
    assert isinstance(out, pd.DataFrame)
    assert len(out) == 0


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------

def test_replay_yields():
    """Replay with a constant +1 signal yields exactly N items."""
    cfg = RealtimeConfig(symbols=["SPY"], buffer_max_bars=100)
    adapter = RealtimeAdapter(cfg)
    df = _make_bars("SPY", 25)
    adapter.buffer_append(df)

    items = list(adapter.replay(lambda hist: 1.0))
    assert len(items) == 25
    for bar, sig, eq in items:
        assert sig == 1.0
        assert "timestamp" in bar
        assert "close" in bar
        assert isinstance(eq, float)


def test_replay_signal_call_no_lookahead():
    """signal_fn must only see history up to and including the current bar.

    We assert this by recording the length of `hist` passed at each call:
    at step i we expect len(hist) == i + 1.
    """
    cfg = RealtimeConfig(symbols=["SPY"], buffer_max_bars=100)
    adapter = RealtimeAdapter(cfg)
    df = _make_bars("SPY", 30)
    adapter.buffer_append(df)

    seen_lengths: list[int] = []
    seen_last_ts: list[pd.Timestamp] = []

    def sig_fn(hist: pd.DataFrame) -> float:
        seen_lengths.append(len(hist))
        seen_last_ts.append(pd.Timestamp(hist["timestamp"].iloc[-1]))
        return 0.0

    list(adapter.replay(sig_fn))

    assert seen_lengths == list(range(1, 31))
    # final timestamp seen must equal the last buffered bar (no future leakage)
    assert seen_last_ts[-1] == df["timestamp"].iloc[-1]
    # at step i, the last timestamp seen must be df.timestamp[i] (not later)
    for i, ts in enumerate(seen_last_ts):
        assert ts == df["timestamp"].iloc[i]


def test_replay_equity_with_constant_long():
    """Constant +1 signal -> equity should track buy-and-hold close-to-close."""
    cfg = RealtimeConfig(symbols=["SPY"], buffer_max_bars=100)
    adapter = RealtimeAdapter(cfg)
    df = _make_bars("SPY", 20)
    adapter.buffer_append(df)

    items = list(adapter.replay(lambda hist: 1.0))
    final_eq = items[-1][2]

    closes = df["close"].values
    expected = closes[-1] / closes[0]
    assert np.isclose(final_eq, expected, rtol=1e-9)


def test_replay_empty_buffer_yields_nothing():
    cfg = RealtimeConfig(symbols=["SPY"], buffer_max_bars=10)
    adapter = RealtimeAdapter(cfg)
    out = list(adapter.replay(lambda hist: 1.0))
    assert out == []


# ---------------------------------------------------------------------------
# yfinance wrapper
# ---------------------------------------------------------------------------

def test_yfinance_fetch_mock(monkeypatch):
    """Monkeypatch yfinance.download and verify the wrapper normalizes
    multi-symbol output into long-form OHLCV."""
    import yfinance as yf

    ts = pd.date_range("2026-01-01 09:30", periods=3, freq="1min")
    fake = pd.DataFrame(
        {
            ("SPY", "Open"):   [100.0, 100.5, 101.0],
            ("SPY", "High"):   [100.2, 100.7, 101.2],
            ("SPY", "Low"):    [99.8,  100.3, 100.8],
            ("SPY", "Close"):  [100.1, 100.6, 101.1],
            ("SPY", "Volume"): [1000,  1200,  1500],
            ("QQQ", "Open"):   [200.0, 200.5, 201.0],
            ("QQQ", "High"):   [200.2, 200.7, 201.2],
            ("QQQ", "Low"):    [199.8, 200.3, 200.8],
            ("QQQ", "Close"):  [200.1, 200.6, 201.1],
            ("QQQ", "Volume"): [800,   900,   1100],
        },
        index=ts,
    )
    fake.columns = pd.MultiIndex.from_tuples(fake.columns)
    fake.index.name = "Datetime"

    captured: dict = {}

    def fake_download(*args, **kwargs):
        captured.update(kwargs)
        return fake

    monkeypatch.setattr(yf, "download", fake_download)

    out = yfinance_fetch(["SPY", "QQQ"], interval="1m", period="1d")

    # shape
    assert list(out.columns) == [
        "timestamp", "symbol", "open", "high", "low", "close", "volume"
    ]
    assert len(out) == 6  # 3 bars x 2 symbols
    # symbols round-trip
    assert set(out["symbol"].unique()) == {"SPY", "QQQ"}
    # SPY closes match input
    spy_close = out.loc[out["symbol"] == "SPY", "close"].tolist()
    assert spy_close == [100.1, 100.6, 101.1]
    # the wrapper passed the requested interval through
    assert captured.get("interval") == "1m"


def test_yfinance_fetch_empty(monkeypatch):
    import yfinance as yf

    monkeypatch.setattr(yf, "download", lambda *a, **kw: pd.DataFrame())
    out = yfinance_fetch(["SPY"], interval="1m", period="1d")
    assert len(out) == 0
    assert list(out.columns) == [
        "timestamp", "symbol", "open", "high", "low", "close", "volume"
    ]


def test_realtime_preserves_nanosecond_precision(monkeypatch):
    """yfinance bars whose timestamps carry nanosecond precision must NOT be
    truncated to microseconds by the normalization path."""
    import yfinance as yf

    # Build a DatetimeIndex with explicit nanosecond offsets. Each bar adds
    # a different ns delta so any truncation is detectable by equality check.
    base = pd.Timestamp("2026-01-01 09:30:00")
    ns_offsets = [123_456_789, 987_654_321, 555_555_555]
    ns_index = pd.DatetimeIndex(
        [base + pd.Timedelta(nanoseconds=ns) for ns in ns_offsets],
        name="Datetime",
    )
    assert ns_index.dtype == "datetime64[ns]"

    fake = pd.DataFrame(
        {
            "Open":   [100.0, 100.5, 101.0],
            "High":   [100.2, 100.7, 101.2],
            "Low":    [99.8,  100.3, 100.8],
            "Close":  [100.1, 100.6, 101.1],
            "Volume": [1000,  1200,  1500],
        },
        index=ns_index,
    )
    monkeypatch.setattr(yf, "download", lambda *a, **kw: fake)

    out = yfinance_fetch(["SPY"], interval="1m", period="1d")
    # dtype is preserved as datetime64[ns]
    assert out["timestamp"].dtype == "datetime64[ns]", (
        f"timestamp dtype changed to {out['timestamp'].dtype!r}"
    )
    # exact ns equality round-trip; the wrapper sorts by timestamp so compare
    # against the sorted source ns values
    expected_ns = sorted(ns_index.asi8.tolist())
    actual_ns = out["timestamp"].astype("datetime64[ns]").astype("int64").tolist()
    assert actual_ns == expected_ns, (
        f"nanosecond precision lost: expected {expected_ns}, got {actual_ns}"
    )


# ---------------------------------------------------------------------------
# Staleness + heartbeat
# ---------------------------------------------------------------------------

def test_fetch_latest_stale_warns_or_raises(monkeypatch, caplog):
    """fetch_latest must enforce max_staleness_seconds.

    With raise_on_stale=False (default): logs warning, returns empty frame.
    With raise_on_stale=True: raises StaleDataError.
    """
    import yfinance as yf

    # build a fake response with a bar that is 1 hour old
    old_ts = pd.Timestamp("2026-01-01 09:00:00")
    fake = pd.DataFrame(
        {
            "Open": [100.0],
            "High": [100.2],
            "Low": [99.8],
            "Close": [100.1],
            "Volume": [1000],
        },
        index=pd.DatetimeIndex([old_ts], name="Datetime"),
    )

    monkeypatch.setattr(yf, "download", lambda *a, **kw: fake)

    # wall-clock now is 1 hour after the bar -> 3600s old
    now = pd.Timestamp("2026-01-01 10:00:00")

    # Case 1: raise_on_stale=False -> warns and returns empty
    cfg = RealtimeConfig(
        symbols=["SPY"],
        max_staleness_seconds=300,  # 5 min
        raise_on_stale=False,
    )
    adapter = RealtimeAdapter(cfg)
    import logging
    with caplog.at_level(logging.WARNING, logger="aurora.core.realtime"):
        out = adapter.fetch_latest(_now=now)
    assert len(out) == 0  # empty frame on stale
    assert any("stale" in rec.message.lower() for rec in caplog.records)

    # Case 2: raise_on_stale=True -> raises
    cfg2 = RealtimeConfig(
        symbols=["SPY"],
        max_staleness_seconds=300,
        raise_on_stale=True,
    )
    adapter2 = RealtimeAdapter(cfg2)
    with pytest.raises(StaleDataError, match="stale"):
        adapter2.fetch_latest(_now=now)


def test_fetch_latest_fresh_data_passes(monkeypatch):
    """Fresh bar (within staleness budget) must pass through unchanged."""
    import yfinance as yf

    bar_ts = pd.Timestamp("2026-01-01 09:55:00")
    fake = pd.DataFrame(
        {
            "Open": [100.0],
            "High": [100.2],
            "Low": [99.8],
            "Close": [100.1],
            "Volume": [1000],
        },
        index=pd.DatetimeIndex([bar_ts], name="Datetime"),
    )
    monkeypatch.setattr(yf, "download", lambda *a, **kw: fake)

    # 3 minutes old < 5 min staleness budget
    now = pd.Timestamp("2026-01-01 09:58:00")
    cfg = RealtimeConfig(symbols=["SPY"], max_staleness_seconds=300)
    adapter = RealtimeAdapter(cfg)
    out = adapter.fetch_latest(_now=now)
    assert len(out) == 1


def test_market_halted_detection(monkeypatch):
    """is_market_halted detects gaps > heartbeat_interval_seconds."""
    import yfinance as yf

    bar_ts = pd.Timestamp("2026-01-01 09:30:00")
    fake = pd.DataFrame(
        {
            "Open": [100.0],
            "High": [100.2],
            "Low": [99.8],
            "Close": [100.1],
            "Volume": [1000],
        },
        index=pd.DatetimeIndex([bar_ts], name="Datetime"),
    )
    monkeypatch.setattr(yf, "download", lambda *a, **kw: fake)

    cfg = RealtimeConfig(
        symbols=["SPY"],
        max_staleness_seconds=10_000,  # ignore staleness for this test
        heartbeat_interval_seconds=60,
    )
    adapter = RealtimeAdapter(cfg)

    # before any fetch_latest call -> not halted (no signal yet)
    assert adapter.is_market_halted() is False

    # do a fetch at t=09:30:00
    fetch_time = pd.Timestamp("2026-01-01 09:30:00")
    adapter.fetch_latest(_now=fetch_time)

    # 30 seconds later -> still healthy
    assert adapter.is_market_halted(_now=pd.Timestamp("2026-01-01 09:30:30")) is False
    # 90 seconds later -> halted (gap > 60s)
    assert adapter.is_market_halted(_now=pd.Timestamp("2026-01-01 09:31:30")) is True


def test_realtime_config_invalid_new_params():
    """Validation rejects non-positive staleness and heartbeat values."""
    with pytest.raises(ValueError):
        RealtimeConfig(symbols=["SPY"], max_staleness_seconds=0)
    with pytest.raises(ValueError):
        RealtimeConfig(symbols=["SPY"], heartbeat_interval_seconds=-1)


def test_fetch_latest_calls_yfinance(monkeypatch):
    """Adapter.fetch_latest must invoke yfinance.download with the configured
    interval."""
    import yfinance as yf

    ts = pd.date_range("2026-01-01 09:30", periods=2, freq="1min")
    fake = pd.DataFrame(
        {
            "Open":   [100.0, 100.5],
            "High":   [100.2, 100.7],
            "Low":    [99.8,  100.3],
            "Close":  [100.1, 100.6],
            "Volume": [1000,  1200],
        },
        index=ts,
    )
    fake.index.name = "Datetime"

    seen: dict = {}

    def fake_download(*args, **kwargs):
        seen.update(kwargs)
        return fake

    monkeypatch.setattr(yf, "download", fake_download)

    cfg = RealtimeConfig(symbols=["SPY"], interval="5m")
    adapter = RealtimeAdapter(cfg)
    # pass synthetic now so staleness check passes against the synthetic bar ts
    out = adapter.fetch_latest(_now=pd.Timestamp("2026-01-01 09:31"))

    assert seen.get("interval") == "5m"
    assert len(out) == 2
    assert (out["symbol"] == "SPY").all()
