"""Intraday / minute-bar backtest engine.

Calendar-aware engine for minute or hourly bars. Supports RTH (09:30-16:00 ET),
ETH (04:00-20:00 ET), and 24h calendars. Position carries across days unless
flat_eod=True. Overnight cost charged on cross-session carry.

CRITICAL: same anti-lookahead convention as engine.py — signal at bar i applies
to return of bar i+1 (i.e. weight known at close of bar i executes at open of
bar i+1, settles by close of bar i+1). Implemented as weights[:-1] * returns[1:].
"""
from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Callable, Optional
import numpy as np
import pandas as pd

from quantforge.core.costs import CostModel, ZERO_costs

_logger = logging.getLogger(__name__)


# Trading-hour windows in minutes-from-midnight (US/Eastern time-of-day on the
# bar timestamp itself; we do NOT apply timezone math here, so callers using
# naive UTC indexes must pre-convert to ET wall-clock or pass calendar='24h').
_RTH_OPEN_MIN = 9 * 60 + 30   # 09:30
_RTH_CLOSE_MIN = 16 * 60      # 16:00
_ETH_OPEN_MIN = 4 * 60        # 04:00
_ETH_CLOSE_MIN = 20 * 60      # 20:00


@dataclass
class IntradayBacktestResult:
    """Result of an intraday backtest.

    Fields:
        equity: pd.Series indexed by timestamp — NAV path (starts at 1.0).
        returns: pd.Series — net per-bar returns (cost-deducted).
        positions: pd.Series — target weight at each bar (post flat_eod adj).
        trades: pd.DataFrame — one row per non-zero |delta_w| event, cols:
                timestamp, prev_pos, new_pos, delta, cost.
        session_pnl: pd.DataFrame — per-session aggregate, cols:
                date, pnl, n_trades, n_bars, end_position.
        metrics: dict — total_return, cagr, sharpe, sortino, mdd, calmar,
                 n_bars, n_sessions, ppy.
    """
    equity: pd.Series
    returns: pd.Series
    positions: pd.Series
    trades: pd.DataFrame
    session_pnl: pd.DataFrame
    metrics: dict


def _session_id(idx: pd.DatetimeIndex, calendar: str,
                tz: str = "America/New_York") -> np.ndarray:
    """Assign a session id (int) per bar.

    For RTH/ETH: session id = ordinal date in ``tz`` wall-clock (one session
    per calendar day in the trading time zone). The conversion to ``tz``
    mirrors :func:`_in_session_mask` so a tz-aware index using UTC times
    does not get its sessions split across UTC date boundaries.
    For 24h: session id = constant 0 (no boundaries).
    """
    if calendar == "24h":
        return np.zeros(len(idx), dtype=np.int64)
    # Convert to the trading tz BEFORE taking .date() so an ETH session that
    # spans the UTC date boundary stays under a single session id.
    if idx.tz is None:
        idx_local = idx.tz_localize(tz)
    else:
        idx_local = idx.tz_convert(tz)
    # session = ordinal date. Use Python date.toordinal via .date() — robust to
    # the underlying datetime64 resolution (ns vs us vs ms in newer pandas).
    return np.array([d.toordinal() for d in idx_local.date], dtype=np.int64)


def _in_session_mask(
    idx: pd.DatetimeIndex,
    calendar: str,
    tz: str = "America/New_York",
) -> np.ndarray:
    """Boolean mask: True if bar is inside the calendar's trading window.

    For 24h, every bar is in session and ``tz`` is ignored. For RTH/ETH, the
    index is converted to ``tz`` (default ``America/New_York``) before the
    wall-clock window is applied. A naive index is assumed to already be in
    ``tz`` and is localized in place.
    """
    if calendar == "24h":
        return np.ones(len(idx), dtype=bool)
    if idx.tz is None:
        _logger.warning(
            "DatetimeIndex is timezone-naive; assuming wall-clock is %s and "
            "localizing in place. Pass a tz-aware index to silence this warning.",
            tz,
        )
        idx_local = idx.tz_localize(tz)
    else:
        idx_local = idx.tz_convert(tz)
    minutes = idx_local.hour * 60 + idx_local.minute
    if calendar == "RTH":
        return (minutes >= _RTH_OPEN_MIN) & (minutes < _RTH_CLOSE_MIN)
    if calendar == "ETH":
        return (minutes >= _ETH_OPEN_MIN) & (minutes < _ETH_CLOSE_MIN)
    raise ValueError(f"unknown calendar: {calendar!r}")


def _is_session_close_bar(session_ids: np.ndarray) -> np.ndarray:
    """Boolean array, True at the LAST bar of each session.

    True at index t when session_ids[t+1] != session_ids[t] (and also last bar).
    """
    n = len(session_ids)
    out: np.ndarray = np.zeros(n, dtype=bool)
    if n == 0:
        return out
    out[-1] = True
    if n > 1:
        out[:-1] = session_ids[1:] != session_ids[:-1]
    return out


def _compute_metrics(net_rets: np.ndarray, ppy: int) -> dict:
    """Compute the intraday metric suite. Annualized via ppy = bars/year."""
    r = net_rets[~np.isnan(net_rets)]
    if len(r) < 2:
        return {
            "total_return": 0.0, "cagr": 0.0, "sharpe": 0.0, "sortino": 0.0,
            "mdd": 0.0, "calmar": 0.0, "n_bars": int(len(r)), "ppy": int(ppy),
        }

    nav = np.cumprod(1.0 + r)
    final = float(nav[-1])
    total_return = final - 1.0

    years = len(r) / ppy if ppy > 0 else 0.0
    cagr = (final ** (1.0 / years)) - 1.0 if years > 0 and final > 0 else 0.0

    cummax = np.maximum.accumulate(nav)
    dd = (nav - cummax) / cummax
    mdd = float(dd.min())

    calmar = cagr / abs(mdd) if abs(mdd) > 1e-12 else 0.0

    std = float(r.std())
    mean = float(r.mean())
    sharpe = (mean / std) * np.sqrt(ppy) if std > 1e-15 else 0.0

    downside = r[r < 0]
    dstd = float(downside.std()) if len(downside) > 1 else std
    sortino = (mean / dstd) * np.sqrt(ppy) if dstd > 1e-15 else 0.0

    return {
        "total_return": float(total_return),
        "cagr": float(cagr),
        "sharpe": float(sharpe),
        "sortino": float(sortino),
        "mdd": float(mdd),
        "calmar": float(calmar),
        "n_bars": int(len(r)),
        "ppy": int(ppy),
    }


def run_intraday_backtest(
    prices: pd.DataFrame,
    signal_fn: Callable,
    bars_per_day: int = 390,
    calendar: str = "RTH",
    costs: Optional[CostModel] = None,
    flat_eod: bool = False,
    overnight_cost_bps: float = 0.0,
    tz: str = "America/New_York",
    partial_fill_factor: float = 1.0,
    **strategy_kwargs,
) -> IntradayBacktestResult:
    """Run an intraday backtest on minute or hourly bars.

    Args:
        prices: DataFrame with DatetimeIndex and at least a 'close' column
                (open/high/low/volume optional but accepted).
        signal_fn: callable signal_fn(prices, **kwargs) -> Series of {-1, 0, +1}
                   aligned to prices.index. MUST not look ahead — only data
                   up to and including bar i may be used to set signal[i].
        bars_per_day: 390 for RTH equities (1-min), 24*60 for crypto, etc.
                      Used to annualize metrics.
        calendar: 'RTH' (09:30-16:00 ET), 'ETH' (04:00-20:00 ET), or '24h'.
        costs: CostModel. Defaults to ZERO_costs.
        flat_eod: if True, force position to 0 at the last bar of each session
                  before settling next bar. No carry, so overnight cost skipped.
        overnight_cost_bps: bps charged on |position| held across a session
                            boundary. Skipped entirely when flat_eod=True.
        tz: IANA timezone used to interpret RTH/ETH wall-clock windows. A
            tz-aware index is converted to this zone; a naive index is assumed
            to already be in ``tz``. Ignored for ``calendar='24h'``.
        partial_fill_factor: forwarded to ``costs.per_trade_bps``. Default 1.0
            (full instant fill). Lower values inflate the slippage component
            for partial-fill regimes.
        **strategy_kwargs: forwarded to signal_fn.

    Returns:
        IntradayBacktestResult
    """
    if not isinstance(prices, pd.DataFrame):
        raise TypeError("prices must be a DataFrame")
    if not isinstance(prices.index, pd.DatetimeIndex):
        raise TypeError("prices index must be a DatetimeIndex")
    if "close" not in prices.columns:
        raise ValueError("prices must contain a 'close' column")
    if calendar not in ("RTH", "ETH", "24h"):
        raise ValueError(f"calendar must be 'RTH', 'ETH', or '24h'; got {calendar!r}")
    if bars_per_day <= 0:
        raise ValueError("bars_per_day must be positive")
    if costs is None:
        costs = ZERO_costs

    idx = prices.index
    n = len(idx)
    close = prices["close"].to_numpy(dtype=float)

    # Compute signal
    raw_sig = signal_fn(prices, **strategy_kwargs)
    if isinstance(raw_sig, pd.Series):
        if len(raw_sig) != n:
            raise ValueError(f"signal length {len(raw_sig)} != prices length {n}")
        weights = raw_sig.to_numpy(dtype=float)
    else:
        weights = np.asarray(raw_sig, dtype=float)
        if len(weights) != n:
            raise ValueError(f"signal length {len(weights)} != prices length {n}")

    # NaN-aware validation BEFORE the magnitude check; otherwise np.abs(NaN)
    # silently passes the |w| <= 1 filter and poisons the cost loop.
    if not np.all(np.isfinite(weights)):
        raise ValueError("non-finite weights")
    if np.any(np.abs(weights) > 1.0 + 1e-9):
        raise ValueError(
            f"signal weights must be in [-1, 1], got max abs {np.abs(weights).max()}"
        )

    # Session structure
    session_ids = _session_id(idx, calendar, tz=tz)
    in_session = _in_session_mask(idx, calendar, tz=tz)
    is_close_bar = _is_session_close_bar(session_ids)

    # Force flat at session close if requested
    if flat_eod and calendar != "24h":
        weights = weights.copy()
        weights[is_close_bar] = 0.0

    # Asset returns: bar-to-bar close-to-close
    asset_rets = np.zeros(n)
    if n > 1:
        asset_rets[1:] = close[1:] / close[:-1] - 1.0

    # Strategy gross returns: weight[t-1] applies to return[t] (no lookahead)
    net = np.zeros(n)
    if n > 1:
        net[1:] = weights[:-1] * asset_rets[1:]

    # Per-bar transaction costs from |delta_w|
    delta_w = np.abs(np.diff(weights, prepend=0.0))
    bps_per_unit_turnover = costs.per_trade_bps(partial_fill_factor) / 1e4
    txn_cost = delta_w * bps_per_unit_turnover

    # Borrow on short side, prorated to per-bar from annual
    if costs.borrow_rate_annual > 0:
        short_notional = np.abs(np.minimum(weights, 0.0))
        ppy_local = bars_per_day * (252 if calendar in ("RTH", "ETH") else 365)
        per_bar_borrow = costs.borrow_rate_annual / max(ppy_local, 1)
        borrow_cost = short_notional * per_bar_borrow
    else:
        borrow_cost = np.zeros(n)

    # Overnight cost on cross-session carry. A "carry" event is defined as
    # holding a non-zero position into the FIRST bar of a new session — i.e.
    # weights[t-1] != 0 and session_ids[t] != session_ids[t-1]. We charge it
    # on bar t (the first bar of the new session).
    overnight_cost = np.zeros(n)
    if not flat_eod and overnight_cost_bps > 0 and n > 1:
        bps = overnight_cost_bps / 1e4
        new_session: np.ndarray = np.zeros(n, dtype=bool)
        new_session[1:] = session_ids[1:] != session_ids[:-1]
        carried = np.zeros(n)
        carried[1:] = np.abs(weights[:-1])
        overnight_cost = new_session * carried * bps

    net = net - txn_cost - borrow_cost - overnight_cost

    # Zero out first-bar return BEFORE cumprod so nav[0] is exactly 1.0
    # without silently overwriting first-bar PnL. Mirrors engine.py.
    if len(net) > 0 and net[0] != 0.0:
        _logger.warning(
            "engine_intraday net[0]=%.6e is non-zero; zeroing to avoid first-bar PnL leak",
            net[0],
        )
        net = net.copy()
        net[0] = 0.0

    # Equity curve
    nav = np.cumprod(1.0 + net)

    # Trades: one row per bar where |delta_w| > 0. Vectorized via boolean mask.
    trade_mask = delta_w > 1e-15
    if trade_mask.any():
        prev_pos = np.zeros(n)
        if n > 1:
            prev_pos[1:] = weights[:-1]
        trades = pd.DataFrame({
            "timestamp": idx[trade_mask],
            "prev_pos": prev_pos[trade_mask].astype(float),
            "new_pos": weights[trade_mask].astype(float),
            "delta": (weights - prev_pos)[trade_mask].astype(float),
            "cost": txn_cost[trade_mask].astype(float),
        })
    else:
        trades = pd.DataFrame(
            columns=["timestamp", "prev_pos", "new_pos", "delta", "cost"],
        )

    # Session-level PnL aggregation: bucket by calendar date for both 24h
    # and RTH/ETH (24h has "no session" but date-bucketing still groups bars
    # naturally for the session_pnl summary).
    date_buckets = idx.normalize()

    df_bars = pd.DataFrame({
        "date": date_buckets,
        "ret": net,
        "pos": weights,
        "is_trade": delta_w > 1e-15,
    })
    grouped = df_bars.groupby("date", sort=True)
    session_pnl = pd.DataFrame({
        "date": grouped["ret"].sum().index,
        "pnl": grouped["ret"].sum().to_numpy(),
        "n_trades": grouped["is_trade"].sum().to_numpy().astype(int),
        "n_bars": grouped["ret"].count().to_numpy().astype(int),
        "end_position": grouped["pos"].last().to_numpy(),
    }).reset_index(drop=True)

    # Metrics — annualization
    days_per_year = 252 if calendar in ("RTH", "ETH") else 365
    ppy = bars_per_day * days_per_year
    metrics = _compute_metrics(net, ppy=ppy)
    metrics["n_sessions"] = int(len(session_pnl))

    return IntradayBacktestResult(
        equity=pd.Series(nav, index=idx, name="equity"),
        returns=pd.Series(net, index=idx, name="returns"),
        positions=pd.Series(weights, index=idx, name="position"),
        trades=trades,
        session_pnl=session_pnl,
        metrics=metrics,
    )
