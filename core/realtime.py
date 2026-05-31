"""Real-time data ingestion adapter for Aurora.

Polling-based wrapper around yfinance live API. Buffers recent bars per symbol
in an in-memory ring buffer and exposes a replay generator that streams bars
into a signal_fn one at a time, enforcing causality (no lookahead).

Anti-snooping/lookahead notes:
- The replay generator only ever passes bars[: i + 1] to signal_fn at step i.
- Buffer enforces strictly ascending timestamps and per-symbol deduplication.

Usage:
    cfg = RealtimeConfig(symbols=["SPY", "QQQ"], interval="1m", poll_seconds=60)
    adapter = RealtimeAdapter(cfg)
    df = adapter.fetch_latest()
    adapter.buffer_append(df)
    for bar, signal, equity in adapter.replay(my_signal_fn):
        ...
"""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Iterator, Optional

import numpy as np
import pandas as pd

_logger = logging.getLogger(__name__)


class StaleDataError(RuntimeError):
    """Raised when fetched bars are older than max_staleness_seconds."""


# yfinance accepts only a fixed set of intervals.
VALID_INTERVALS: tuple[str, ...] = (
    "1m", "2m", "5m", "15m", "30m", "60m", "90m",
    "1h", "1d", "5d", "1wk", "1mo", "3mo",
)
# Restrict the adapter to the four documented intervals (project task spec).
SUPPORTED_INTERVALS: tuple[str, ...] = ("1m", "5m", "15m", "1h")


@dataclass
class RealtimeConfig:
    """Configuration for the realtime adapter.

    Args:
        symbols: tickers to poll.
        interval: bar resolution; one of '1m', '5m', '15m', '1h'.
        poll_seconds: cadence between fetch_latest calls when running a poll loop.
        buffer_max_bars: ring-buffer size per symbol (deque maxlen).
        source: data source identifier; only 'yfinance' wired in.
        max_staleness_seconds: max allowed age of the latest fetched bar
            (vs wall-clock now). When exceeded, fetch_latest raises
            StaleDataError if raise_on_stale=True, else logs a warning and
            returns an empty frame. Default 300 (5 minutes).
        raise_on_stale: if True, fetch_latest raises StaleDataError on stale
            data; if False (default), logs a warning and returns empty.
        heartbeat_interval_seconds: max gap (in seconds) between successful
            fetch_latest calls before is_market_halted() returns True.
            Default 60.
    """
    symbols: list[str]
    interval: str = "1m"
    poll_seconds: int = 60
    buffer_max_bars: int = 1000
    source: str = "yfinance"
    max_staleness_seconds: int = 300
    raise_on_stale: bool = False
    heartbeat_interval_seconds: int = 60

    def __post_init__(self) -> None:
        if not isinstance(self.symbols, (list, tuple)) or not self.symbols:
            raise ValueError("symbols must be a non-empty list")
        if self.interval not in SUPPORTED_INTERVALS:
            raise ValueError(
                f"interval {self.interval!r} not supported; "
                f"choose one of {SUPPORTED_INTERVALS}"
            )
        if self.poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        if self.buffer_max_bars <= 0:
            raise ValueError("buffer_max_bars must be positive")
        if self.max_staleness_seconds <= 0:
            raise ValueError("max_staleness_seconds must be positive")
        if self.heartbeat_interval_seconds <= 0:
            raise ValueError("heartbeat_interval_seconds must be positive")


def yfinance_fetch(
    symbols: list[str],
    interval: str = "1m",
    period: str = "1d",
) -> pd.DataFrame:
    """Wrap yfinance.download and normalize the response.

    Returns a long-form DataFrame with columns
    ['timestamp', 'symbol', 'open', 'high', 'low', 'close', 'volume'].
    Timestamp index is preserved on the frame as well (column 'timestamp').
    Empty results yield an empty DataFrame with the canonical columns.
    """
    import yfinance as yf  # imported lazily so tests can monkeypatch easily

    if isinstance(symbols, str):
        symbols = [symbols]
    if not symbols:
        return _empty_bars_frame()

    raw = yf.download(
        tickers=symbols,
        interval=interval,
        period=period,
        progress=False,
        group_by="ticker",
        auto_adjust=False,
        threads=False,
    )
    if raw is None or len(raw) == 0:
        return _empty_bars_frame()

    return _normalize_yf_frame(raw, symbols)


def _empty_bars_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["timestamp", "symbol", "open", "high", "low", "close", "volume"]
    )


def _normalize_yf_frame(raw: pd.DataFrame, symbols: list[str]) -> pd.DataFrame:
    """Flatten yfinance multi-symbol output into long form.

    yfinance with group_by='ticker' returns a column MultiIndex [symbol, field]
    when len(symbols) > 1, and a single-level [field] index otherwise.
    """
    rows: list[pd.DataFrame] = []
    is_multi = isinstance(raw.columns, pd.MultiIndex)

    for sym in symbols:
        if is_multi:
            if sym not in raw.columns.get_level_values(0):
                continue
            sub = raw[sym].copy()
        else:
            sub = raw.copy()

        if sub.empty:
            continue
        sub.columns = [str(c).lower() for c in sub.columns]
        # ensure all OHLCV columns exist
        for col in ("open", "high", "low", "close", "volume"):
            if col not in sub.columns:
                sub[col] = np.nan

        sub = sub[["open", "high", "low", "close", "volume"]].dropna(how="all")
        if sub.empty:
            continue
        sub = sub.reset_index()
        ts_col = sub.columns[0]  # 'Datetime' or 'Date' depending on interval
        sub = sub.rename(columns={ts_col: "timestamp"})
        sub["symbol"] = sym
        # Preserve nanosecond precision from yfinance: older pandas paths can
        # silently truncate to microseconds when re-coercing already-datetime
        # values. Re-cast as datetime64[ns] so the underlying ns counter is
        # kept verbatim regardless of the input dtype.
        # tz-aware values are explicitly converted to UTC before stripping the
        # timezone; ``astype('datetime64[ns]')`` on a tz-aware Series otherwise
        # interprets the wall-clock as already-UTC and silently shifts the
        # timestamp by the original offset.
        ts_in = sub["timestamp"]
        if pd.api.types.is_datetime64_any_dtype(ts_in):
            if getattr(ts_in.dt, "tz", None) is not None:
                sub["timestamp"] = ts_in.dt.tz_convert("UTC").dt.tz_localize(None)
            else:
                sub["timestamp"] = ts_in.astype("datetime64[ns]")
        else:
            sub["timestamp"] = pd.to_datetime(ts_in, unit="ns") \
                if pd.api.types.is_integer_dtype(ts_in) \
                else pd.to_datetime(ts_in).astype("datetime64[ns]")
        rows.append(sub[["timestamp", "symbol", "open", "high", "low", "close", "volume"]])

    if not rows:
        return _empty_bars_frame()

    out = pd.concat(rows, ignore_index=True)
    out = out.sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    return out


@dataclass
class RealtimeAdapter:
    """Polling adapter with per-symbol ring buffers.

    State:
        _buffers: dict[symbol -> deque[dict]] of bar rows.
        _last_ts: dict[symbol -> pd.Timestamp] last seen timestamp for dedup.
        _last_fetch_wall: wall-clock time of last successful fetch_latest.
    """
    config: RealtimeConfig
    _buffers: dict[str, deque] = field(init=False)
    _last_ts: dict[str, Optional[pd.Timestamp]] = field(init=False)

    def __init__(self, config: RealtimeConfig) -> None:
        self.config = config
        self._buffers = {
            s: deque(maxlen=config.buffer_max_bars) for s in config.symbols
        }
        self._last_ts = {s: None for s in config.symbols}
        self._last_fetch_wall: Optional[pd.Timestamp] = None

    # ---- fetch -----------------------------------------------------------

    def fetch_latest(self, _now: Optional[pd.Timestamp] = None) -> pd.DataFrame:
        """Fetch the most recent bars from the configured source.

        Compares the latest bar's timestamp to wall-clock now. When the gap
        exceeds config.max_staleness_seconds, either raises StaleDataError
        (config.raise_on_stale=True) or logs a warning and returns an empty
        frame.

        Args:
            _now: optional wall-clock override for testing (UTC pd.Timestamp).
        """
        if self.config.source != "yfinance":
            raise NotImplementedError(f"source {self.config.source} not wired")
        df = yfinance_fetch(
            symbols=self.config.symbols,
            interval=self.config.interval,
            period=_default_period_for(self.config.interval),
        )
        # update heartbeat regardless of staleness check
        now = _now if _now is not None else pd.Timestamp.now(tz="UTC")
        self._last_fetch_wall = now

        if df is None or len(df) == 0:
            return df if df is not None else _empty_bars_frame()

        # staleness check: compare latest bar timestamp to now
        latest = pd.Timestamp(df["timestamp"].max())
        # normalize timezone — strip both sides to naive for comparison
        if latest.tzinfo is not None:
            latest = latest.tz_convert("UTC").tz_localize(None)
        now_cmp = now
        if now_cmp.tzinfo is not None:
            now_cmp = now_cmp.tz_convert("UTC").tz_localize(None)
        raw_age = (now_cmp - latest).total_seconds()
        # Negative age means the latest bar is timestamped in the future
        # (clock skew or upstream feed bug). Floor at 0 so a stale bar can
        # not slip the staleness gate by reporting a negative number.
        if raw_age < 0:
            _logger.warning(
                "fetched bar timestamp %s is ahead of wall-clock %s by %.1fs; "
                "flooring age to 0",
                latest, now_cmp, -raw_age,
            )
        age_seconds = max(0.0, raw_age)

        if age_seconds > self.config.max_staleness_seconds:
            msg = (
                f"data is stale: latest bar {latest} is "
                f"{age_seconds:.0f}s old (max {self.config.max_staleness_seconds}s)"
            )
            if self.config.raise_on_stale:
                raise StaleDataError(msg)
            _logger.warning(msg)
            return _empty_bars_frame()

        return df

    # ---- health ----------------------------------------------------------

    def is_market_halted(self, _now: Optional[pd.Timestamp] = None) -> bool:
        """Return True if last fetch_latest call was longer ago than
        heartbeat_interval_seconds.

        If fetch_latest has never been called, returns False (no signal yet).

        Args:
            _now: optional wall-clock override for testing.
        """
        if self._last_fetch_wall is None:
            return False
        now = _now if _now is not None else pd.Timestamp.now(tz="UTC")
        last = self._last_fetch_wall
        if last.tzinfo is not None:
            last = last.tz_convert("UTC").tz_localize(None)
        if now.tzinfo is not None:
            now = now.tz_convert("UTC").tz_localize(None)
        gap = (now - last).total_seconds()
        return gap > self.config.heartbeat_interval_seconds

    # ---- buffer ----------------------------------------------------------

    def buffer_append(self, df: pd.DataFrame) -> int:
        """Append rows of `df` into per-symbol ring buffers.

        Drops bars whose (symbol, timestamp) is already at or before the last
        buffered timestamp for that symbol. Enforces strictly ascending order.

        Returns:
            count of rows actually appended (after dedup / out-of-order filter).
        """
        if df is None or len(df) == 0:
            return 0
        if "timestamp" not in df.columns or "symbol" not in df.columns:
            raise ValueError("df must have 'timestamp' and 'symbol' columns")

        appended = 0
        # Sort once, then process per-symbol in vectorized form. iterrows() is
        # ~50-100x slower than building a mask + to_dict('records') for the
        # rows that pass dedup, especially for high-frequency 1m streams.
        df_sorted = df.sort_values(["symbol", "timestamp"])
        # Ensure timestamp column is pd.Timestamp dtype for correct comparison.
        ts_col = pd.to_datetime(df_sorted["timestamp"])
        # Normalize timestamps to naive UTC for the dedup comparison so a
        # batch with a tz-aware timestamp column does not crash when the
        # buffered ``_last_ts[sym]`` (or the new batch) is stored naive,
        # and vice versa. The bar payload itself still carries the original
        # pd.Timestamp value via the per-row loop below.
        if getattr(ts_col.dt, "tz", None) is not None:
            ts_col_cmp = ts_col.dt.tz_convert("UTC").dt.tz_localize(None)
        else:
            ts_col_cmp = ts_col
        sym_col = df_sorted["symbol"].astype(str)
        for sym, sym_mask in sym_col.groupby(sym_col).groups.items():
            if sym not in self._buffers:
                # not configured -> ignore silently
                continue
            sub = df_sorted.loc[sym_mask]
            sub_ts = ts_col.loc[sym_mask]
            sub_ts_cmp = ts_col_cmp.loc[sym_mask]
            last = self._last_ts[sym]
            if last is not None:
                # Normalize the buffered watermark the same way so a tz mix
                # between the previous batch and this one does not raise
                # ``Cannot compare tz-naive and tz-aware timestamps``.
                last_cmp = pd.Timestamp(last)
                if last_cmp.tzinfo is not None:
                    last_cmp = last_cmp.tz_convert("UTC").tz_localize(None)
                keep = sub_ts_cmp > last_cmp
            else:
                keep = pd.Series(True, index=sub.index)
            sub_keep = sub.loc[keep]
            sub_keep_ts = sub_ts.loc[keep]
            sub_keep_ts_cmp = sub_ts_cmp.loc[keep]
            if sub_keep.empty:
                continue
            records = sub_keep.to_dict("records")
            for rec, ts in zip(records, sub_keep_ts):
                ts_p = pd.Timestamp(ts)
                bar = {
                    "timestamp": ts_p,
                    "symbol": sym,
                    "open": float(rec.get("open", np.nan)),
                    "high": float(rec.get("high", np.nan)),
                    "low": float(rec.get("low", np.nan)),
                    "close": float(rec.get("close", np.nan)),
                    "volume": float(rec.get("volume", 0.0)),
                }
                self._buffers[sym].append(bar)
                appended += 1
            # Persist the watermark in the comparison space (naive UTC) so
            # subsequent calls compare apples to apples.
            self._last_ts[sym] = pd.Timestamp(sub_keep_ts_cmp.iloc[-1])
        return appended

    def get_buffer(self, symbol: str) -> pd.DataFrame:
        """Return the current buffered bars for `symbol` as a DataFrame."""
        if symbol not in self._buffers:
            return _empty_bars_frame()
        rows = list(self._buffers[symbol])
        if not rows:
            return _empty_bars_frame()
        df = pd.DataFrame(rows)
        return df.reset_index(drop=True)

    # ---- replay ----------------------------------------------------------

    def replay(
        self,
        signal_fn: Callable[[pd.DataFrame], float],
        costs=None,
        symbol: Optional[str] = None,
    ) -> Iterator[tuple[dict, float, float]]:
        """Stream buffered bars through signal_fn one at a time.

        Causality: at step i, signal_fn receives bars[: i + 1] (history up to and
        INCLUDING the current bar) and must return a signal in [-1, 1] applied
        to the next bar's return.

        Equity is computed off close-to-close returns with the previous bar's
        signal (anti-lookahead) and an optional flat per-trade cost in bps.

        Yields:
            (current_bar_dict, signal, equity_so_far) per buffered bar.
        """
        if symbol is None:
            if len(self.config.symbols) != 1:
                raise ValueError(
                    "replay() requires symbol when adapter has multiple symbols"
                )
            symbol = self.config.symbols[0]
        if symbol not in self._buffers:
            raise KeyError(f"symbol {symbol!r} not in buffer")

        bars = list(self._buffers[symbol])
        if not bars:
            return

        df = pd.DataFrame(bars).reset_index(drop=True)

        cost_bps = 0.0
        if costs is not None:
            # Accept a CostModel-like object with per_trade_bps() or a float.
            if hasattr(costs, "per_trade_bps"):
                cost_bps = float(costs.per_trade_bps())
            else:
                cost_bps = float(costs)

        equity = 1.0
        prev_signal = 0.0
        for i in range(len(df)):
            history = df.iloc[: i + 1]
            current_bar = df.iloc[i].to_dict()

            # apply previous signal to this bar's return (anti-lookahead)
            if i > 0:
                prev_close = float(df.iloc[i - 1]["close"])
                this_close = float(df.iloc[i]["close"])
                if prev_close > 0:
                    bar_ret = this_close / prev_close - 1.0
                else:
                    bar_ret = 0.0
                equity *= 1.0 + prev_signal * bar_ret

            # compute the new signal AFTER updating equity for this bar
            signal = float(signal_fn(history))

            # charge costs on signal change (turnover)
            if cost_bps > 0.0 and i > 0:
                turnover = abs(signal - prev_signal)
                if turnover > 0.0:
                    equity *= 1.0 - turnover * (cost_bps / 1e4)

            yield current_bar, signal, equity
            prev_signal = signal


def _default_period_for(interval: str) -> str:
    """Pick a sensible yfinance `period` argument for the given `interval`."""
    if interval == "1m":
        return "1d"
    if interval in ("5m", "15m"):
        return "5d"
    if interval == "1h":
        return "1mo"
    return "1d"
