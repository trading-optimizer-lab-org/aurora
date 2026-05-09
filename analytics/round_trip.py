"""Round-trip trade analysis.

Identifies trades from a weight time-series, computes per-trade PnL, MAE/MFE,
holding period, and aggregate stats (win rate, profit factor, expectancy,
streaks). Inspired by pyfolio.round_trips.

A trade = contiguous segment of constant non-zero weight sign.
Entry: first bar of the segment (i.e. previous bar was 0 or had opposite sign).
Exit: last bar of the segment with the same sign (i.e. the next bar is 0 or
flips sign). Entry/exit prices are read at those bars; MAE/MFE are computed
over the inclusive [entry_bar, exit_bar] price window.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class Trade:
    entry_time: pd.Timestamp
    entry_price: float
    exit_time: pd.Timestamp
    exit_price: float
    direction: int           # +1 long, -1 short
    # Number of *bars* the trade was held. Always integer-valued and unit-
    # consistent with the bar cadence of the input prices, regardless of
    # whether timestamps were supplied. The attribute is kept named
    # ``holding_days`` for backward compatibility, but it is the bar count.
    holding_days: int
    pnl_pct: float           # (exit/entry - 1) * direction
    pnl_dollars: float       # NaN unless notional supplied
    mae_pct: float           # max adverse excursion (worst signed pct loss during trade)
    mfe_pct: float           # max favorable excursion (best signed pct gain during trade)
    # Holding duration in seconds. Populated only when ``timestamps`` is
    # supplied and at least two bars span the trade; otherwise NaN.
    holding_seconds: float = float("nan")


@dataclass
class TradeStats:
    n_trades: int
    win_rate: float
    avg_trade_pct: float
    avg_winner_pct: float
    avg_loser_pct: float
    profit_factor: float
    expectancy_pct: float
    avg_holding_days: float
    median_holding_days: float
    max_consecutive_wins: int
    max_consecutive_losses: int
    avg_mae: float
    avg_mfe: float
    pnl_total_pct: float
    # ``flat_trades`` counts round-trips that finished at exactly zero PnL
    # (entry_price == exit_price and identical direction). These are tracked
    # separately so they do not pollute the loser bucket.
    flat_trades: int = 0


def _segments(weights: np.ndarray) -> list[tuple[int, int, int]]:
    """Return list of (start_idx, end_idx, direction) for each constant-sign run.

    end_idx is the last bar where the position is held (inclusive).
    Bars where weight == 0 are skipped.
    """
    n = len(weights)
    segs: list[tuple[int, int, int]] = []
    i = 0
    while i < n:
        w = weights[i]
        if w == 0:
            i += 1
            continue
        d = 1 if w > 0 else -1
        j = i
        while j + 1 < n:
            wn = weights[j + 1]
            if wn == 0:
                break
            dn = 1 if wn > 0 else -1
            if dn != d:
                break
            j += 1
        segs.append((i, j, d))
        i = j + 1
    return segs


def extract_trades(
    weights: np.ndarray,
    prices: np.ndarray,
    timestamps: Optional[np.ndarray] = None,
    notional: Optional[float] = None,
) -> list[Trade]:
    """Identify trades from weight array.

    A trade = period of constant non-zero weight sign. Entry on the first bar of
    the segment; exit on the last bar of the segment. Entry/exit prices are
    taken at those bars' prices.

    MAE/MFE: cumulative worst/best of (price/entry - 1) * direction during the
    trade duration.
    """
    weights = np.asarray(weights, dtype=float)
    prices = np.asarray(prices, dtype=float)
    if len(weights) != len(prices):
        raise ValueError(f"weights len {len(weights)} != prices len {len(prices)}")

    has_ts = timestamps is not None
    if has_ts:
        timestamps = np.asarray(timestamps)
        if len(timestamps) != len(weights):
            raise ValueError("timestamps length mismatch")

    trades: list[Trade] = []
    for s, e, d in _segments(weights):
        entry_p = float(prices[s])
        exit_p = float(prices[e])
        if entry_p <= 0:
            continue  # skip degenerate
        seg_prices = prices[s:e + 1]
        excursions = (seg_prices / entry_p - 1.0) * d
        mae = float(np.min(excursions))  # worst signed (likely negative)
        mfe = float(np.max(excursions))  # best signed
        pnl = float((exit_p / entry_p - 1.0) * d)
        pnl_dollars = float(pnl * notional) if notional is not None else float("nan")

        # ``holding_days`` is reported in BARS, *inclusive of both endpoints*
        # (entry bar = bar 1, so a same-bar round trip has holding_days = 1).
        # Tearsheet's ``_extract_round_trips`` reports ``bars = exit_i - entry_i``
        # (interval count, exclusive). The two field names mean different
        # things on purpose: ``holding_days`` is "how many bars the position
        # was on the book" and ``bars`` is "how many bar boundaries elapsed".
        holding_bars = int(e - s) + 1
        holding_secs = float("nan")
        if has_ts:
            assert timestamps is not None
            t_entry = pd.Timestamp(timestamps[s])
            t_exit = pd.Timestamp(timestamps[e])
            try:
                holding_secs = float((t_exit - t_entry).total_seconds())
            except Exception:
                holding_secs = float("nan")
        else:
            t_entry = pd.Timestamp(s)
            t_exit = pd.Timestamp(e)

        trades.append(Trade(
            entry_time=t_entry,
            entry_price=entry_p,
            exit_time=t_exit,
            exit_price=exit_p,
            direction=int(d),
            holding_days=holding_bars,
            pnl_pct=pnl,
            pnl_dollars=pnl_dollars,
            mae_pct=mae,
            mfe_pct=mfe,
            holding_seconds=holding_secs,
        ))
    return trades


def consecutive_streak(trades: list[Trade], kind: str = "win") -> int:
    """Max consecutive wins (pnl_pct > 0) or losses (pnl_pct < 0).

    Flat trades (pnl_pct == 0) break BOTH streaks: they are neither wins
    nor losses, so they reset the running counter on each side.
    """
    if kind not in ("win", "loss"):
        raise ValueError("kind must be 'win' or 'loss'")
    if not trades:
        return 0
    best = 0
    cur = 0
    for t in trades:
        is_win = t.pnl_pct > 0
        is_loss = t.pnl_pct < 0
        match = is_win if kind == "win" else is_loss
        if match:
            cur += 1
            if cur > best:
                best = cur
        else:
            cur = 0
    return best


def trade_stats(trades: list[Trade]) -> TradeStats:
    """Aggregate stats from list of Trade objects.

    Trades are partitioned into:
        * winners — strictly positive PnL
        * losers  — strictly negative PnL
        * flats   — exactly zero PnL (tracked separately)

    Profit factor and average loser metrics ignore flats; this prevents a
    0-PnL round-trip from being treated as a small loser and dragging
    profit-factor / avg_loser numbers toward zero.
    """
    if not trades:
        return TradeStats(
            n_trades=0, win_rate=0.0, avg_trade_pct=0.0,
            avg_winner_pct=0.0, avg_loser_pct=0.0,
            profit_factor=0.0, expectancy_pct=0.0,
            avg_holding_days=0.0, median_holding_days=0.0,
            max_consecutive_wins=0, max_consecutive_losses=0,
            avg_mae=0.0, avg_mfe=0.0, pnl_total_pct=0.0,
            flat_trades=0,
        )
    pnls = np.array([t.pnl_pct for t in trades])
    holds = np.array([t.holding_days for t in trades])
    maes = np.array([t.mae_pct for t in trades])
    mfes = np.array([t.mfe_pct for t in trades])
    winners = pnls[pnls > 0]
    losers = pnls[pnls < 0]
    flats = pnls[pnls == 0]

    gross_win = float(winners.sum()) if winners.size else 0.0
    gross_loss = float(-losers.sum()) if losers.size else 0.0
    if gross_loss > 0:
        pf = gross_win / gross_loss
    else:
        pf = float("inf") if gross_win > 0 else 0.0

    win_rate = float(winners.size) / len(pnls)
    loss_rate = float(losers.size) / len(pnls)
    avg_w = float(winners.mean()) if winners.size else 0.0
    avg_l = float(losers.mean()) if losers.size else 0.0
    # Use win_rate + loss_rate (not 1 - win_rate) so flat trades do not get
    # absorbed into the loss bucket. This keeps expectancy equal to the
    # simple sample mean of all PnLs and avoids the previous bias where
    # increasing flats appeared as additional losers.
    expectancy = win_rate * avg_w + loss_rate * avg_l

    return TradeStats(
        n_trades=len(trades),
        win_rate=win_rate,
        avg_trade_pct=float(pnls.mean()),
        avg_winner_pct=avg_w,
        avg_loser_pct=avg_l,
        profit_factor=pf,
        expectancy_pct=float(expectancy),
        avg_holding_days=float(holds.mean()),
        median_holding_days=float(np.median(holds)),
        max_consecutive_wins=consecutive_streak(trades, "win"),
        max_consecutive_losses=consecutive_streak(trades, "loss"),
        avg_mae=float(maes.mean()),
        avg_mfe=float(mfes.mean()),
        pnl_total_pct=float(pnls.sum()),
        flat_trades=int(flats.size),
    )


def trades_dataframe(trades: list[Trade]) -> pd.DataFrame:
    """Convert trade list to DataFrame for inspection."""
    if not trades:
        cols = list(Trade.__dataclass_fields__.keys())
        return pd.DataFrame(columns=cols)
    return pd.DataFrame([asdict(t) for t in trades])


def _bucket_label(d: int) -> str:
    if d <= 1:
        return "1d"
    if d <= 5:
        return "2-5d"
    if d <= 20:
        return "6-20d"
    return ">20d"


def stats_by_holding_period(trades: list[Trade]) -> pd.DataFrame:
    """Group trades into buckets (1d, 2-5d, 6-20d, >20d) and report stats per bucket."""
    buckets_order = ["1d", "2-5d", "6-20d", ">20d"]
    if not trades:
        return pd.DataFrame(columns=["bucket", "n_trades", "win_rate",
                                     "avg_trade_pct", "avg_holding_days",
                                     "pnl_total_pct"])
    grouped: dict[str, list[Trade]] = {b: [] for b in buckets_order}
    for t in trades:
        grouped[_bucket_label(t.holding_days)].append(t)

    rows = []
    for b in buckets_order:
        ts = grouped[b]
        if not ts:
            continue
        s = trade_stats(ts)
        rows.append({
            "bucket": b,
            "n_trades": s.n_trades,
            "win_rate": s.win_rate,
            "avg_trade_pct": s.avg_trade_pct,
            "avg_holding_days": s.avg_holding_days,
            "pnl_total_pct": s.pnl_total_pct,
        })
    return pd.DataFrame(rows)


def stats_by_direction(trades: list[Trade]) -> pd.DataFrame:
    """Long vs short stats separately."""
    if not trades:
        return pd.DataFrame(columns=["direction", "n_trades", "win_rate",
                                     "avg_trade_pct", "profit_factor",
                                     "pnl_total_pct"])
    longs = [t for t in trades if t.direction == 1]
    shorts = [t for t in trades if t.direction == -1]
    rows = []
    for label, group in (("long", longs), ("short", shorts)):
        if not group:
            continue
        s = trade_stats(group)
        rows.append({
            "direction": label,
            "n_trades": s.n_trades,
            "win_rate": s.win_rate,
            "avg_trade_pct": s.avg_trade_pct,
            "profit_factor": s.profit_factor,
            "pnl_total_pct": s.pnl_total_pct,
        })
    return pd.DataFrame(rows)


def mae_mfe_curve(
    trade: Trade,
    prices_during_trade: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute MAE and MFE arrays over the trade duration.

    Returns (mae_curve, mfe_curve) where each element is the cumulative
    worst/best signed excursion seen up to that bar.
    """
    p = np.asarray(prices_during_trade, dtype=float)
    if p.size == 0:
        return np.array([]), np.array([])
    entry = float(trade.entry_price)
    if entry <= 0:
        raise ValueError("entry_price must be positive")
    exc = (p / entry - 1.0) * trade.direction
    mae_curve = np.minimum.accumulate(exc)
    mfe_curve = np.maximum.accumulate(exc)
    return mae_curve, mfe_curve
