"""Tests for aurora.core.bars (Batch M.2 — alternative bars per AFML Ch. 2).

Run: uv run pytest aurora/tests/test_bars.py -v
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aurora.core.bars import (
    auto_threshold,
    compute_vwap,
    dollar_bars,
    tick_bars,
    volume_bars,
)


# ---------- fixtures ---------------------------------------------------------


def _make_ticks(prices, volumes, start="2024-01-01 09:30:00", freq_s=1):
    """Build a tick frame from arrays. timestamp is column, not index."""
    n = len(prices)
    ts = pd.date_range(start=start, periods=n, freq=f"{freq_s}s")
    return pd.DataFrame(
        {
            "timestamp": ts,
            "price": np.asarray(prices, dtype=np.float64),
            "volume": np.asarray(volumes, dtype=np.int64),
        }
    )


def _make_ticks_indexed(prices, volumes, start="2024-01-01 09:30:00", freq_s=1):
    """Build a tick frame where timestamp is the index (alternate input form)."""
    n = len(prices)
    ts = pd.date_range(start=start, periods=n, freq=f"{freq_s}s")
    df = pd.DataFrame(
        {
            "price": np.asarray(prices, dtype=np.float64),
            "volume": np.asarray(volumes, dtype=np.int64),
        },
        index=ts,
    )
    df.index.name = "timestamp"
    return df


# ---------- tick_bars --------------------------------------------------------


def test_tick_bars_count():
    """1000 ticks, n=100 -> exactly 10 bars (no trailing partial)."""
    rng = np.random.default_rng(0)
    prices = 100.0 + rng.standard_normal(1000).cumsum() * 0.1
    volumes = rng.integers(1, 100, size=1000)
    ticks = _make_ticks(prices, volumes)

    bars = tick_bars(ticks, n_ticks=100)
    assert len(bars) == 10
    assert list(bars.columns) == [
        "open", "high", "low", "close", "volume", "n_ticks", "vwap",
    ]
    assert (bars["n_ticks"] == 100).all()


def test_tick_bars_trailing_partial():
    """1005 ticks, n=100 -> 11 bars, last has 5 ticks."""
    rng = np.random.default_rng(1)
    prices = 100.0 + rng.standard_normal(1005).cumsum() * 0.1
    volumes = rng.integers(1, 100, size=1005)
    ticks = _make_ticks(prices, volumes)
    bars = tick_bars(ticks, n_ticks=100)
    assert len(bars) == 11
    assert bars["n_ticks"].iloc[-1] == 5
    assert (bars["n_ticks"].iloc[:-1] == 100).all()


def test_tick_bars_index_input():
    """Tick frame with DatetimeIndex (no timestamp column) also works."""
    rng = np.random.default_rng(2)
    prices = 100.0 + rng.standard_normal(300).cumsum() * 0.1
    volumes = rng.integers(1, 50, size=300)
    ticks = _make_ticks_indexed(prices, volumes)
    bars = tick_bars(ticks, n_ticks=50)
    assert len(bars) == 6
    assert isinstance(bars.index, pd.DatetimeIndex)


# ---------- volume_bars ------------------------------------------------------


def test_volume_bars_threshold():
    """Constant volume per tick: threshold respected.

    1000 ticks of volume=10 each -> total volume 10_000. With threshold=1000,
    each bar collects 100 ticks of volume 10 == exactly the threshold.
    """
    n = 1000
    prices = np.linspace(100.0, 110.0, n)
    volumes = np.full(n, 10, dtype=np.int64)
    ticks = _make_ticks(prices, volumes)

    bars = volume_bars(ticks, volume_threshold=1000.0)
    # exactly 10 full bars, no trailing partial
    assert len(bars) == 10
    # each bar's volume must be >= threshold (last may equal threshold exactly)
    assert (bars["volume"] >= 1000).all()
    # each bar of constant volume==10 ticks -> exactly 100 ticks
    assert (bars["n_ticks"] == 100).all()


def test_volume_bars_trailing_partial():
    """If totals don't divide evenly, last bar is partial and < threshold."""
    n = 1050
    prices = np.linspace(100.0, 110.0, n)
    volumes = np.full(n, 10, dtype=np.int64)
    ticks = _make_ticks(prices, volumes)
    bars = volume_bars(ticks, volume_threshold=1000.0)
    # 10 full + 1 partial (50 ticks * 10 = 500 volume)
    assert len(bars) == 11
    assert bars["volume"].iloc[-1] == 500
    assert bars["n_ticks"].iloc[-1] == 50


# ---------- dollar_bars ------------------------------------------------------


def test_dollar_bars_threshold():
    """Constant price*volume: threshold respected.

    1000 ticks at price=100, volume=10 -> dollar per tick=1000. threshold=10_000
    means 10 ticks per bar, total 100 bars.
    """
    n = 1000
    prices = np.full(n, 100.0)
    volumes = np.full(n, 10, dtype=np.int64)
    ticks = _make_ticks(prices, volumes)
    bars = dollar_bars(ticks, dollar_threshold=10_000.0)
    assert len(bars) == 100
    # each bar dollar value (volume * close-equiv at constant price) >= threshold
    dollar_vals = bars["volume"] * bars["close"]
    assert (dollar_vals >= 10_000.0 - 1e-9).all()
    assert (bars["n_ticks"] == 10).all()


# ---------- OHLC consistency -------------------------------------------------


def test_ohlc_consistency():
    """high >= max(open,close) >= min(open,close) >= low for every bar.

    Run across all three bar types on a randomwalk-with-noise tick stream.
    """
    rng = np.random.default_rng(42)
    n = 2000
    prices = 100.0 + rng.standard_normal(n).cumsum() * 0.05
    volumes = rng.integers(1, 200, size=n)
    ticks = _make_ticks(prices, volumes)

    for bars in (
        tick_bars(ticks, n_ticks=37),
        volume_bars(ticks, volume_threshold=5000.0),
        dollar_bars(ticks, dollar_threshold=500_000.0),
    ):
        assert len(bars) > 0
        oc_max = np.maximum(bars["open"].values, bars["close"].values)
        oc_min = np.minimum(bars["open"].values, bars["close"].values)
        assert (bars["high"].values >= oc_max - 1e-12).all()
        assert (oc_max >= oc_min - 1e-12).all()
        assert (oc_min >= bars["low"].values - 1e-12).all()


# ---------- vwap correctness -------------------------------------------------


def test_vwap_correctness():
    """Hand-computed VWAP example.

    Prices [10, 20, 30], volumes [1, 2, 3] -> sum_pv = 10+40+90=140, sum_v=6,
    vwap = 140/6 = 23.333...
    """
    assert compute_vwap(np.array([10.0, 20.0, 30.0]),
                       np.array([1.0, 2.0, 3.0])) == pytest.approx(140.0 / 6.0)

    # zero-volume edge: falls back to mean of prices
    assert compute_vwap(np.array([10.0, 20.0]),
                       np.array([0.0, 0.0])) == pytest.approx(15.0)

    # vwap embedded in tick_bars: feed exactly 3 ticks as one bar
    ticks = _make_ticks([10.0, 20.0, 30.0], [1, 2, 3])
    bars = tick_bars(ticks, n_ticks=3)
    assert len(bars) == 1
    assert bars["vwap"].iloc[0] == pytest.approx(140.0 / 6.0)
    assert bars["volume"].iloc[0] == 6
    assert bars["open"].iloc[0] == 10.0
    assert bars["high"].iloc[0] == 30.0
    assert bars["low"].iloc[0] == 10.0
    assert bars["close"].iloc[0] == 30.0


# ---------- empty input ------------------------------------------------------


def test_empty_input():
    """Empty ticks -> empty bar frame with the right columns and dtypes."""
    empty = pd.DataFrame({"timestamp": pd.to_datetime([]), "price": [], "volume": []})
    expected_cols = ["open", "high", "low", "close", "volume", "n_ticks", "vwap"]

    for fn, arg in (
        (tick_bars, 100),
        (volume_bars, 1000.0),
        (dollar_bars, 10_000.0),
    ):
        bars = fn(empty, arg)
        assert len(bars) == 0
        assert list(bars.columns) == expected_cols
        assert isinstance(bars.index, pd.DatetimeIndex)


# ---------- auto_threshold ---------------------------------------------------


def test_auto_threshold():
    """Target 100 bars/day -> output is 100 +/- 20%.

    Build 24h of ticks with constant volume; auto_threshold for 100 bars/day
    should split that into ~100 volume bars.
    """
    # one trading day at 1Hz = 86400 ticks
    n = 86_400
    prices = np.full(n, 100.0)
    volumes = np.full(n, 5, dtype=np.int64)
    ts = pd.date_range(start="2024-01-01 00:00:00", periods=n, freq="1s")
    ticks = pd.DataFrame({"timestamp": ts, "price": prices, "volume": volumes})

    target = 100
    thr = auto_threshold(ticks, target_bars_per_day=target, mode="volume")
    bars = volume_bars(ticks, volume_threshold=thr)
    # within +/- 20%
    assert 80 <= len(bars) <= 120

    # dollar mode also works
    thr_d = auto_threshold(ticks, target_bars_per_day=target, mode="dollar")
    dbars = dollar_bars(ticks, dollar_threshold=thr_d)
    assert 80 <= len(dbars) <= 120


def test_auto_threshold_invalid_mode():
    ticks = _make_ticks([100.0, 101.0], [1, 1])
    with pytest.raises(ValueError, match="mode must be"):
        auto_threshold(ticks, target_bars_per_day=10, mode="ticks")


# ---------- statelessness ----------------------------------------------------


def test_stateless_dollar_bars():
    """Calling dollar_bars twice on the same input must give identical output.

    Catches accidental module-level state in the JIT path.
    """
    rng = np.random.default_rng(7)
    n = 5000
    prices = 100.0 + rng.standard_normal(n).cumsum() * 0.02
    volumes = rng.integers(1, 50, size=n)
    ticks = _make_ticks(prices, volumes)

    a = dollar_bars(ticks, dollar_threshold=50_000.0)
    b = dollar_bars(ticks, dollar_threshold=50_000.0)
    pd.testing.assert_frame_equal(a, b)

    # also sanity-check tick_bars and volume_bars
    pd.testing.assert_frame_equal(
        tick_bars(ticks, n_ticks=200),
        tick_bars(ticks, n_ticks=200),
    )
    pd.testing.assert_frame_equal(
        volume_bars(ticks, volume_threshold=1000.0),
        volume_bars(ticks, volume_threshold=1000.0),
    )


# ---------- dtype preservation ----------------------------------------------


def test_dtype_preservation():
    """prices float64, volume int64."""
    ticks = _make_ticks([10.0, 20.0, 30.0, 40.0], [1, 2, 3, 4])
    bars = tick_bars(ticks, n_ticks=2)
    assert bars["open"].dtype == np.float64
    assert bars["high"].dtype == np.float64
    assert bars["low"].dtype == np.float64
    assert bars["close"].dtype == np.float64
    assert bars["vwap"].dtype == np.float64
    assert bars["volume"].dtype == np.int64
    assert bars["n_ticks"].dtype == np.int64


# ---------- input validation -------------------------------------------------


def test_invalid_n_ticks():
    ticks = _make_ticks([10.0, 20.0], [1, 1])
    with pytest.raises(ValueError):
        tick_bars(ticks, n_ticks=0)
    with pytest.raises(ValueError):
        tick_bars(ticks, n_ticks=-5)


def test_invalid_threshold():
    ticks = _make_ticks([10.0, 20.0], [1, 1])
    with pytest.raises(ValueError):
        volume_bars(ticks, volume_threshold=0.0)
    with pytest.raises(ValueError):
        dollar_bars(ticks, dollar_threshold=-100.0)


def test_missing_columns():
    bad = pd.DataFrame({"timestamp": pd.to_datetime(["2024-01-01"]), "price": [10.0]})
    with pytest.raises(ValueError, match="price' and 'volume'"):
        tick_bars(bad, n_ticks=1)


# ---------- trailing partial bar timestamp ---------------------------------


def test_trailing_partial_bar_timestamp_correct():
    """The trailing partial bar's index timestamp must equal the LAST tick
    in that partial bar (not the threshold-closing tick of the previous bar
    or any earlier tick).

    Validates the contract for tick_bars, volume_bars, and dollar_bars.
    """
    # 105 ticks, n=100 -> bar 0 spans ticks 0..99, bar 1 (partial) spans 100..104
    n = 105
    prices = np.linspace(100.0, 110.0, n)
    volumes = np.full(n, 1, dtype=np.int64)
    ticks = _make_ticks(prices, volumes)
    last_tick_ts = ticks["timestamp"].iloc[-1]

    # tick_bars
    tb = tick_bars(ticks, n_ticks=100)
    assert len(tb) == 2
    assert tb["n_ticks"].iloc[-1] == 5
    assert tb.index[-1] == last_tick_ts

    # volume_bars: threshold 100 means each full bar is 100 ticks (volume=1 each)
    # 105 ticks of vol=1 -> bar 0 closes on tick 99 (cumvol=100), bar 1 partial
    # has 5 ticks (cumvol=5), trailing partial last tick = ticks[-1]
    vb = volume_bars(ticks, volume_threshold=100.0)
    assert len(vb) == 2
    assert vb["n_ticks"].iloc[-1] == 5
    assert vb.index[-1] == last_tick_ts

    # dollar_bars: same pattern with dollar threshold tuned to make 100 ticks/bar
    # at price ~100.x, dollar per tick ~100, so threshold 10_000 -> ~100 ticks
    db = dollar_bars(ticks, dollar_threshold=10_000.0)
    assert len(db) >= 2
    # the index timestamp of the trailing bar must be the last tick
    assert db.index[-1] == last_tick_ts


def test_bars_rejects_nan_input():
    """All three public bar APIs must raise a ValueError on NaN price input
    rather than silently producing nonsense bars from JIT-kernel NaN propagation."""
    prices = np.array([100.0, 101.0, np.nan, 99.5, 100.2], dtype=np.float64)
    volumes = np.array([10, 20, 15, 5, 8], dtype=np.int64)
    ticks = _make_ticks(prices, volumes)

    with pytest.raises(ValueError, match="NaN"):
        tick_bars(ticks, n_ticks=2)
    with pytest.raises(ValueError, match="NaN"):
        volume_bars(ticks, volume_threshold=20.0)
    with pytest.raises(ValueError, match="NaN"):
        dollar_bars(ticks, dollar_threshold=2_000.0)
