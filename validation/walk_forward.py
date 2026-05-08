"""Walk-forward analysis."""
from __future__ import annotations
import warnings
from dataclasses import dataclass
from typing import Callable, Optional
import numpy as np
import pandas as pd

from quantforge.core.engine import run_backtest
from quantforge.core.costs import CostModel, ZERO_costs


@dataclass
class WFWindow:
    label: str
    is_start: str
    is_end: str
    oos_start: str
    oos_end: str


@dataclass
class WFResult:
    windows: list[dict]
    n_pass: int
    n_total: int

    def passed(self, min_pass: int = 3) -> bool:
        return self.n_pass >= min_pass


def generate_wf_windows(prices: pd.Series, n_windows: int = 4, oos_pct: float = 0.20,
                        mode: str = "rolling",
                        start_date: Optional[str] = None,
                        end_date: Optional[str] = None,
                        min_bars: int = 100) -> list[WFWindow]:
    """Auto-generate WF windows.

    Modes:
      'rolling':   IS slides forward; oldest data drops off (window of fixed length)
      'expanding': IS always starts at start_date; grows over time
      'anchored':  IS always start_date -> first OOS_start; same IS for all windows
                   (no re-fit assumption)

    Args:
        prices: pd.Series price data (used for date range if start/end not given)
        n_windows: number of WF folds
        oos_pct: fraction of each fold reserved for OOS (typically 0.20-0.30)
        mode: 'rolling' | 'expanding' | 'anchored'
        start_date, end_date: optional bounds
        min_bars: emit warning if any IS or OOS shorter than this

    Returns:
        list[WFWindow] with non-overlapping OOS periods covering the OOS portion
        of [start_date, end_date].
    """
    if mode not in ("rolling", "expanding", "anchored"):
        raise ValueError(f"mode must be 'rolling'|'expanding'|'anchored', got {mode!r}")
    if n_windows < 1:
        raise ValueError(f"n_windows must be >= 1, got {n_windows}")
    if not (0.0 < oos_pct < 1.0):
        raise ValueError(f"oos_pct must be in (0, 1), got {oos_pct}")

    idx = prices.index
    if start_date is None:
        start_ts = idx[0]
    else:
        start_ts = pd.Timestamp(start_date)
    if end_date is None:
        end_ts = idx[-1]
    else:
        end_ts = pd.Timestamp(end_date)

    in_range = idx[(idx >= start_ts) & (idx <= end_ts)]
    n_total = len(in_range)
    if n_total < n_windows * 2:
        raise ValueError(f"insufficient bars ({n_total}) for {n_windows} windows")

    # Total OOS span = oos_pct of full range; split equally across n_windows
    total_oos = int(round(n_total * oos_pct))
    if total_oos < n_windows:
        raise ValueError(f"OOS portion ({total_oos} bars) too small for {n_windows} windows")

    # IS portion = remainder; each rolling fold uses (n_total - total_oos) // 1 IS bars
    is_full = n_total - total_oos  # bars before first OOS_start
    if is_full < n_windows:
        raise ValueError(f"IS portion ({is_full} bars) too small")

    # OOS chunks: equal split, last chunk absorbs remainder
    oos_sizes = [total_oos // n_windows] * n_windows
    for i in range(total_oos - sum(oos_sizes)):
        oos_sizes[-1 - i] += 1  # pad from the end

    windows: list[WFWindow] = []
    cursor = is_full  # index of first OOS bar for window 0
    # Rolling mode: the IS window has fixed length ``is_full`` and shifts
    # forward by one OOS chunk between folds (oldest bars drop off as the
    # cursor advances). The previous ``is_full // 1`` was a no-op left over
    # from earlier exploration; documented now so intent is explicit.
    rolling_is_len = is_full

    short_is = False
    short_oos = False
    prev_oos_hi = -1  # track previous OOS upper bound to enforce strict non-overlap

    for i in range(n_windows):
        oos_lo = cursor
        oos_hi = oos_lo + oos_sizes[i] - 1
        if oos_hi >= n_total:
            oos_hi = n_total - 1

        # Strict non-overlap invariant: OOS_start[k+1] must be > OOS_end[k]
        # (i.e. test_start[k+1] >= test_end[k] + 1).
        if oos_lo <= prev_oos_hi:
            raise AssertionError(
                f"OOS overlap detected at window {i}: "
                f"oos_lo={oos_lo} <= prev_oos_hi={prev_oos_hi}"
            )

        if mode == "rolling":
            # IS = oos_lo - rolling_is_len .. oos_lo - 1
            is_lo = oos_lo - rolling_is_len
            if is_lo < 0:
                is_lo = 0
            is_hi = oos_lo - 1
        elif mode == "expanding":
            # IS = 0 .. oos_lo - 1 (grows each window)
            is_lo = 0
            is_hi = oos_lo - 1
        else:  # anchored
            # IS = 0 .. (first OOS_start - 1) for ALL windows
            is_lo = 0
            is_hi = is_full - 1

        is_len = is_hi - is_lo + 1
        oos_len = oos_hi - oos_lo + 1
        if is_len < min_bars:
            short_is = True
        if oos_len < min_bars:
            short_oos = True

        windows.append(WFWindow(
            label=f"WF{i+1}",
            is_start=in_range[is_lo].strftime("%Y-%m-%d"),
            is_end=in_range[is_hi].strftime("%Y-%m-%d"),
            oos_start=in_range[oos_lo].strftime("%Y-%m-%d"),
            oos_end=in_range[oos_hi].strftime("%Y-%m-%d"),
        ))

        prev_oos_hi = oos_hi
        cursor = oos_hi + 1

    if short_is:
        warnings.warn(f"At least one IS window has fewer than {min_bars} bars",
                      UserWarning, stacklevel=2)
    if short_oos:
        warnings.warn(f"At least one OOS window has fewer than {min_bars} bars",
                      UserWarning, stacklevel=2)

    return windows


def walk_forward(strategy_factory: Callable, prices: pd.Series,
                 windows: Optional[list[WFWindow]] = None,
                 costs: CostModel = ZERO_costs,
                 ppy: int = 252, criterion: str = "calmar_positive",
                 benchmark_calmar: float = 0.0,
                 mode: Optional[str] = None,
                 n_windows: int = 4, oos_pct: float = 0.20,
                 start_date: Optional[str] = None,
                 end_date: Optional[str] = None,
                 min_oos_bars: int = 60) -> WFResult:
    """Run walk-forward across windows.

    Args:
        strategy_factory: callable() -> Strategy or callable(is_prices) -> Strategy.
                         Called fresh each window (no carry-over state). When the
                         factory accepts a positional argument we pass the IS slice
                         so strategies can re-fit on the in-sample bars. Falling
                         back to ``factory()`` emits a UserWarning since the
                         strategy is then using globally-tuned parameters and
                         the WF analysis becomes optimistic.
        prices: full price series (engine slices to windows)
        windows: explicit list of WFWindow specs. If None and mode given,
                 auto-generates via generate_wf_windows.
        costs: CostModel
        ppy: periods per year
        criterion: "calmar_positive" | "calmar_above_bh" | "sharpe_positive"
        benchmark_calmar: for "calmar_above_bh"
        mode: 'rolling' | 'expanding' | 'anchored' (used only when windows=None)
        n_windows, oos_pct, start_date, end_date: forwarded to generate_wf_windows
        min_oos_bars: minimum OOS bars required to mark a window as ok.
            Default 60 (about a quarter of business days) so a tiny OOS slice
            cannot rubber-stamp ``ok=True`` on a noisy positive Calmar.

    Returns:
        WFResult with per-window metrics and pass count
    """
    if windows is None:
        if mode is None:
            raise ValueError("must pass either windows= or mode=")
        windows = generate_wf_windows(prices, n_windows=n_windows, oos_pct=oos_pct,
                                      mode=mode, start_date=start_date, end_date=end_date)
    if min_oos_bars < 1:
        raise ValueError(f"min_oos_bars must be >= 1 (got {min_oos_bars})")
    rows = []
    for w in windows:
        # Slice IS so the factory can fit on it; engineering convention:
        # try factory(is_prices) first, fall back to factory() if the
        # signature does not accept an argument. The fallback path warns,
        # since a globally-fit strategy makes WF over-optimistic.
        is_prices = prices[(prices.index >= pd.Timestamp(w.is_start))
                           & (prices.index <= pd.Timestamp(w.is_end))]
        try:
            strat = strategy_factory(is_prices)
        except TypeError:
            warnings.warn(
                "WF factory accepts no args; using globally-fit strategy. "
                "Walk-forward results will be optimistic — refactor the factory "
                "to take is_prices and refit on each window.",
                UserWarning,
                stacklevel=2,
            )
            strat = strategy_factory()
        oos = prices[(prices.index >= pd.Timestamp(w.oos_start))
                     & (prices.index <= pd.Timestamp(w.oos_end))]
        if len(oos) < 20:
            rows.append({"window": w.label, "ok": False, "reason": "insufficient data"})
            continue
        res = run_backtest(oos, strat.signals, costs=costs, ppy=ppy)
        ok = False
        if criterion == "calmar_positive":
            ok = res.calmar > 0
        elif criterion == "calmar_above_bh":
            ok = res.calmar > benchmark_calmar
        elif criterion == "sharpe_positive":
            ok = res.sharpe > 0
        else:
            raise ValueError(f"unknown criterion: {criterion!r}")
        # Reject ok=True on too-short OOS slices: even a positive Calmar on
        # a 20-bar window is mostly noise. Threshold is configurable.
        if ok and len(oos) < min_oos_bars:
            ok = False
        rows.append({
            "window": w.label,
            "ok": ok,
            "calmar": res.calmar,
            "cagr": res.cagr,
            "mdd": res.mdd,
            "sharpe": res.sharpe,
            "n_oos_bars": int(len(oos)),
        })
    n_pass = sum(1 for r in rows if r.get("ok"))
    return WFResult(windows=rows, n_pass=n_pass, n_total=len(rows))
