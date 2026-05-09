"""Alternative bar construction (Lopez de Prado, AFML Chapter 2).

Tick, volume, and dollar bars sample by information content rather than calendar
time. Heavy-traded periods produce more bars; quiet periods produce fewer. This
yields series closer to IID Gaussian than fixed-time bars, which is desirable for
downstream ML feature pipelines.

Functions:
    tick_bars(ticks, n_ticks)      -> aggregate every n_ticks into one bar
    volume_bars(ticks, threshold)  -> aggregate until cumulative volume >= threshold
    dollar_bars(ticks, threshold)  -> aggregate until cumulative price*volume >= threshold

Helpers:
    compute_vwap(prices, volumes)
    auto_threshold(ticks, target_bars_per_day, mode)

Each output bar carries [open, high, low, close, volume, n_ticks, vwap] indexed by
the timestamp of the last tick in the bar. Inner accumulation loop is JIT-compiled
via numba (with pure-numpy fallback) following the engine_jit.py pattern.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# numba optional — fall back to no-op decorator if missing (mirrors engine_jit.py)
try:
    from numba import njit
    NUMBA_AVAILABLE = True
except ImportError:  # pragma: no cover
    NUMBA_AVAILABLE = False

    def njit(*args, **kwargs):
        if len(args) == 1 and callable(args[0]) and not kwargs:
            return args[0]

        def deco(fn):
            return fn

        return deco


_BAR_COLS = ["open", "high", "low", "close", "volume", "n_ticks", "vwap"]


# ---------- helpers ----------------------------------------------------------


def compute_vwap(prices: np.ndarray, volumes: np.ndarray) -> float:
    """Volume-weighted average price.

    Returns sum(price*volume) / sum(volume). When total volume is zero, falls back
    to the simple mean of prices to avoid division by zero.
    """
    p = np.asarray(prices, dtype=np.float64)
    v = np.asarray(volumes, dtype=np.float64)
    total_v = v.sum()
    if total_v <= 0.0:
        if p.size == 0:
            return float("nan")
        return float(p.mean())
    return float((p * v).sum() / total_v)


def _normalize_ticks(ticks: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Validate and unpack a tick frame into (timestamps_ns, prices, volumes).

    Accepts timestamps as either a column or the index. Returns int64 nanosecond
    timestamps, float64 prices, int64 volumes.
    """
    if not isinstance(ticks, pd.DataFrame):
        raise TypeError("ticks must be a pandas DataFrame")

    if "timestamp" in ticks.columns:
        ts = pd.to_datetime(ticks["timestamp"]).values
    elif isinstance(ticks.index, pd.DatetimeIndex):
        ts = ticks.index.values
    else:
        raise ValueError(
            "ticks must have a 'timestamp' column or a DatetimeIndex"
        )

    if "price" not in ticks.columns or "volume" not in ticks.columns:
        raise ValueError("ticks must contain columns 'price' and 'volume'")

    prices = ticks["price"].to_numpy(dtype=np.float64)
    volumes = ticks["volume"].to_numpy(dtype=np.int64)
    ts_ns = np.asarray(ts, dtype="datetime64[ns]").astype(np.int64)
    return ts_ns, prices, volumes


def _empty_bars() -> pd.DataFrame:
    """Empty bar frame with correct columns and dtypes."""
    df = pd.DataFrame(
        {
            "open": pd.Series(dtype=np.float64),
            "high": pd.Series(dtype=np.float64),
            "low": pd.Series(dtype=np.float64),
            "close": pd.Series(dtype=np.float64),
            "volume": pd.Series(dtype=np.int64),
            "n_ticks": pd.Series(dtype=np.int64),
            "vwap": pd.Series(dtype=np.float64),
        }
    )
    df.index = pd.DatetimeIndex([], name="timestamp")
    return df


def _build_frame(
    open_arr: np.ndarray,
    high_arr: np.ndarray,
    low_arr: np.ndarray,
    close_arr: np.ndarray,
    volume_arr: np.ndarray,
    nticks_arr: np.ndarray,
    vwap_arr: np.ndarray,
    ts_arr: np.ndarray,
) -> pd.DataFrame:
    """Assemble bar arrays into a DataFrame with DatetimeIndex of last-tick timestamps."""
    if open_arr.size == 0:
        return _empty_bars()
    df = pd.DataFrame(
        {
            "open": open_arr.astype(np.float64),
            "high": high_arr.astype(np.float64),
            "low": low_arr.astype(np.float64),
            "close": close_arr.astype(np.float64),
            "volume": volume_arr.astype(np.int64),
            "n_ticks": nticks_arr.astype(np.int64),
            "vwap": vwap_arr.astype(np.float64),
        },
        index=pd.DatetimeIndex(ts_arr.astype("datetime64[ns]"), name="timestamp"),
    )
    return df


# ---------- JIT kernels ------------------------------------------------------


@njit(cache=True)
def _tick_bars_kernel(
    ts_ns: np.ndarray, prices: np.ndarray, volumes: np.ndarray, n_ticks: int
):
    """Tick bars: aggregate every n_ticks ticks into one bar.

    Returns 8 arrays: open, high, low, close, volume, n_ticks, vwap, last_ts_ns.
    """
    T = prices.shape[0]
    if T == 0 or n_ticks <= 0:
        empty_f: np.ndarray = np.empty(0, dtype=np.float64)
        empty_i: np.ndarray = np.empty(0, dtype=np.int64)
        return empty_f, empty_f, empty_f, empty_f, empty_i, empty_i, empty_f, empty_i

    # full bars + possibly one trailing partial
    n_full = T // n_ticks
    has_partial = (T % n_ticks) != 0
    n_bars = n_full + (1 if has_partial else 0)

    o = np.empty(n_bars, dtype=np.float64)
    h = np.empty(n_bars, dtype=np.float64)
    lo = np.empty(n_bars, dtype=np.float64)
    c = np.empty(n_bars, dtype=np.float64)
    vol = np.empty(n_bars, dtype=np.int64)
    nt = np.empty(n_bars, dtype=np.int64)
    vw = np.empty(n_bars, dtype=np.float64)
    last_ts = np.empty(n_bars, dtype=np.int64)

    bar_idx = 0
    i = 0
    while i < T:
        end = i + n_ticks
        if end > T:
            end = T
        o_v = float(prices[i])
        h_v = float(prices[i])
        l_v = float(prices[i])
        sum_pv = 0.0
        sum_v = 0.0
        for k in range(i, end):
            p = float(prices[k])
            v = float(volumes[k])
            if p > h_v:
                h_v = p
            if p < l_v:
                l_v = p
            sum_pv += p * v
            sum_v += v
        c_v = float(prices[end - 1])
        o[bar_idx] = o_v
        h[bar_idx] = h_v
        lo[bar_idx] = l_v
        c[bar_idx] = c_v
        vol[bar_idx] = sum_v
        nt[bar_idx] = end - i
        if sum_v > 0:
            vw[bar_idx] = sum_pv / sum_v
        else:
            # zero-volume window: use simple mean of prices
            s = 0.0
            for k in range(i, end):
                s += prices[k]
            vw[bar_idx] = s / (end - i)
        last_ts[bar_idx] = ts_ns[end - 1]
        bar_idx += 1
        i = end

    return o, h, lo, c, vol, nt, vw, last_ts


@njit(cache=True)
def _threshold_bars_kernel(
    ts_ns: np.ndarray,
    prices: np.ndarray,
    volumes: np.ndarray,
    threshold: np.float64,
    mode: int,
):
    """Aggregate ticks until cumulative metric >= threshold.

    mode == 0: cumulative metric is volume
    mode == 1: cumulative metric is price * volume (dollar value)

    Two-pass: first pass counts bars to size output, second pass fills.
    Stateful inner loop — required by the threshold semantics. Following the
    AFML reference, a bar closes on the tick that pushes cumulative >= threshold;
    leftover ticks form one final partial bar.
    """
    T = prices.shape[0]
    if T == 0 or threshold <= 0.0:
        empty_f: np.ndarray = np.empty(0, dtype=np.float64)
        empty_i: np.ndarray = np.empty(0, dtype=np.int64)
        return empty_f, empty_f, empty_f, empty_f, empty_i, empty_i, empty_f, empty_i

    # pass 1: count bars
    n_bars = 0
    cum = 0.0
    has_open = False
    for k in range(T):
        if mode == 0:
            cum += volumes[k]
        else:
            cum += prices[k] * volumes[k]
        has_open = True
        if cum >= threshold:
            n_bars += 1
            cum = 0.0
            has_open = False
    if has_open:
        n_bars += 1  # trailing partial bar

    o: np.ndarray = np.empty(n_bars, dtype=np.float64)
    h: np.ndarray = np.empty(n_bars, dtype=np.float64)
    lo: np.ndarray = np.empty(n_bars, dtype=np.float64)
    c: np.ndarray = np.empty(n_bars, dtype=np.float64)
    vol: np.ndarray = np.empty(n_bars, dtype=np.int64)
    nt: np.ndarray = np.empty(n_bars, dtype=np.int64)
    vw: np.ndarray = np.empty(n_bars, dtype=np.float64)
    last_ts: np.ndarray = np.empty(n_bars, dtype=np.int64)

    # pass 2: fill bars
    bar_idx = 0
    start = 0
    cum = 0.0
    for k in range(T):
        if mode == 0:
            cum += volumes[k]
        else:
            cum += prices[k] * volumes[k]
        close_bar = (cum >= threshold) or (k == T - 1)
        if close_bar:
            o_v = float(prices[start])
            h_v = float(prices[start])
            l_v = float(prices[start])
            sum_pv = 0.0
            sum_v = 0.0
            for j in range(start, k + 1):
                p = float(prices[j])
                v = float(volumes[j])
                if p > h_v:
                    h_v = p
                if p < l_v:
                    l_v = p
                sum_pv += p * v
                sum_v += v
            o[bar_idx] = o_v
            h[bar_idx] = h_v
            lo[bar_idx] = l_v
            c[bar_idx] = float(prices[k])
            vol[bar_idx] = sum_v
            nt[bar_idx] = k - start + 1
            if sum_v > 0:
                vw[bar_idx] = sum_pv / sum_v
            else:
                s = 0.0
                for j in range(start, k + 1):
                    s += prices[j]
                vw[bar_idx] = s / (k - start + 1)
            last_ts[bar_idx] = ts_ns[k]
            bar_idx += 1
            start = k + 1
            cum = 0.0

    return o, h, lo, c, vol, nt, vw, last_ts


# ---------- public API -------------------------------------------------------


def _check_no_nan(prices: np.ndarray, fn_name: str) -> None:
    """Reject NaN-bearing price arrays before they reach a JIT kernel.

    The numba kernels propagate NaN silently (e.g. `cum += NaN` poisons the
    threshold loop and produces nonsensical bar boundaries). Raise here with
    a clear message so callers see the failure at the public API boundary.
    """
    if np.any(np.isnan(prices)):
        n_nan = int(np.isnan(prices).sum())
        raise ValueError(
            f"{fn_name}: input 'price' column contains {n_nan} NaN value(s); "
            "drop or impute NaNs before bar construction"
        )


def tick_bars(ticks: pd.DataFrame, n_ticks: int) -> pd.DataFrame:
    """Aggregate every n_ticks into one bar.

    Args:
        ticks: DataFrame with columns [price, volume] and either a 'timestamp'
               column or a DatetimeIndex.
        n_ticks: positive integer — number of ticks per bar.

    Returns:
        DataFrame [open, high, low, close, volume, n_ticks, vwap] indexed by the
        timestamp of the last tick in each bar. Trailing incomplete bar is emitted.
        Empty input returns an empty frame with the correct columns/dtypes.
    """
    if int(n_ticks) <= 0:
        raise ValueError(f"n_ticks must be positive, got {n_ticks}")
    if len(ticks) == 0:
        return _empty_bars()
    ts_ns, prices, volumes = _normalize_ticks(ticks)
    _check_no_nan(prices, "tick_bars")
    o, h, lo, c, vol, nt, vw, last_ts = _tick_bars_kernel(
        ts_ns, prices, volumes, int(n_ticks)
    )
    return _build_frame(o, h, lo, c, vol, nt, vw, last_ts)


def volume_bars(ticks: pd.DataFrame, volume_threshold: float) -> pd.DataFrame:
    """Aggregate ticks until cumulative volume reaches volume_threshold.

    Same input/output format as tick_bars. A trailing incomplete bar is emitted
    if the last tick does not push cumulative volume across the threshold.
    """
    if float(volume_threshold) <= 0.0:
        raise ValueError(f"volume_threshold must be positive, got {volume_threshold}")
    if len(ticks) == 0:
        return _empty_bars()
    ts_ns, prices, volumes = _normalize_ticks(ticks)
    _check_no_nan(prices, "volume_bars")
    o, h, lo, c, vol, nt, vw, last_ts = _threshold_bars_kernel(
        ts_ns, prices, volumes, np.float64(volume_threshold), 0
    )
    return _build_frame(o, h, lo, c, vol, nt, vw, last_ts)


def dollar_bars(ticks: pd.DataFrame, dollar_threshold: float) -> pd.DataFrame:
    """Aggregate ticks until cumulative price*volume reaches dollar_threshold.

    Same input/output format as tick_bars. A trailing incomplete bar is emitted
    if the last tick does not push cumulative dollars across the threshold.
    """
    if float(dollar_threshold) <= 0.0:
        raise ValueError(f"dollar_threshold must be positive, got {dollar_threshold}")
    if len(ticks) == 0:
        return _empty_bars()
    ts_ns, prices, volumes = _normalize_ticks(ticks)
    _check_no_nan(prices, "dollar_bars")
    o, h, lo, c, vol, nt, vw, last_ts = _threshold_bars_kernel(
        ts_ns, prices, volumes, np.float64(dollar_threshold), 1
    )
    return _build_frame(o, h, lo, c, vol, nt, vw, last_ts)


def auto_threshold(
    ticks: pd.DataFrame, target_bars_per_day: int, mode: str = "volume"
) -> float:
    """Recommend a threshold so output averages ~target_bars_per_day bars.

    Estimates the daily aggregate (total volume or total dollar value) from the
    tick frame, divides by target_bars_per_day, and returns that as the threshold.
    Spans the full date range covered by the ticks (calendar days, not trading
    days), so a quiet weekend in the data lowers the per-day estimate accordingly.

    Args:
        ticks: tick DataFrame (same shape as tick_bars input).
        target_bars_per_day: desired average bar count per day (positive int).
        mode: 'volume' or 'dollar'.

    Returns:
        Recommended threshold (float). For mode='volume' returns volume per bar;
        for mode='dollar' returns dollar value per bar.
    """
    if mode not in ("volume", "dollar"):
        raise ValueError(f"mode must be 'volume' or 'dollar', got {mode!r}")
    if int(target_bars_per_day) <= 0:
        raise ValueError(
            f"target_bars_per_day must be positive, got {target_bars_per_day}"
        )
    if len(ticks) == 0:
        raise ValueError("cannot compute auto_threshold on empty ticks")

    ts_ns, prices, volumes = _normalize_ticks(ticks)
    # Reject NaN-bearing prices BEFORE any aggregation; otherwise the dollar
    # mode poisons the sum silently and emits a NaN threshold.
    _check_no_nan(prices, "auto_threshold")

    if mode == "volume":
        total = float(volumes.sum())
    else:
        total = float((prices * volumes.astype(np.float64)).sum())

    # span in days based on first/last tick timestamp (calendar days)
    span_ns = float(ts_ns.max() - ts_ns.min())
    one_day_ns = 86_400.0 * 1e9
    n_days = span_ns / one_day_ns
    if n_days < 1.0:
        n_days = 1.0

    per_day = total / n_days
    threshold = per_day / float(target_bars_per_day)
    if np.isnan(threshold):
        raise ValueError(
            "computed threshold is NaN; check tick volumes/prices for non-finite values"
        )
    if threshold <= 0.0:
        raise ValueError(
            "computed threshold is non-positive; check tick volumes/prices"
        )
    return threshold
