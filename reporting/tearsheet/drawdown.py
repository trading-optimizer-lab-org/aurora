"""Drawdown analytics: underwater plot, rolling MDD, top-DD periods table."""
from __future__ import annotations

from typing import List, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .header import _esc, _fig_to_base64, _to_pd_index


def _drawdown_periods(nav: np.ndarray, timestamps=None) -> List[Tuple]:
    """Identify all drawdown periods in a NAV curve.

    Returns list of 5-tuples:
        (start_date, end_date, depth_pct, recovery_days, unrecovered)

    Sorted by depth (worst first). Each period runs from a peak to the next
    recovery (back to peak). If a drawdown never recovers (NAV ends below the
    peak), ``recovery_days`` is set to the bars-since-trough sentinel (the
    duration since the trough, finite and informative -- NOT NaN -- so the
    report is still actionable) and ``unrecovered=True``. Recovered periods
    have ``unrecovered=False``.
    """
    nav = np.asarray(nav, dtype=float)
    if len(nav) < 2:
        return []
    if timestamps is None:
        timestamps = np.arange(len(nav))
    idx = _to_pd_index(timestamps) if not np.issubdtype(
        np.asarray(timestamps).dtype, np.integer
    ) else np.asarray(timestamps)

    cummax = np.maximum.accumulate(nav)
    in_dd = nav < cummax
    periods = []
    i = 0
    n = len(nav)
    while i < n:
        if in_dd[i]:
            # find peak just before i
            start = i - 1 if i > 0 else 0
            # walk forward while still in dd
            j = i
            trough_idx = i
            trough_val = nav[i]
            while j < n and nav[j] < cummax[start]:
                if nav[j] < trough_val:
                    trough_val = nav[j]
                    trough_idx = j
                j += 1
            recovery_idx = j if j < n else None
            unrecovered = recovery_idx is None
            depth = (trough_val / cummax[start]) - 1.0
            if isinstance(idx, pd.DatetimeIndex):
                start_date = idx[start]
                if unrecovered:
                    end_date = idx[-1]
                    # Sentinel: days from trough to last observed bar (finite,
                    # informative; the unrecovered flag distinguishes this
                    # from a real recovery duration).
                    rec_days = (idx[-1] - idx[trough_idx]).days
                else:
                    end_date = idx[recovery_idx]
                    rec_days = (idx[recovery_idx] - idx[trough_idx]).days
            else:
                start_date = int(idx[start])
                if unrecovered:
                    end_date = int(idx[-1])
                    rec_days = int((n - 1) - trough_idx)
                else:
                    assert recovery_idx is not None
                    end_date = int(idx[recovery_idx])
                    rec_days = int(recovery_idx - trough_idx)
            periods.append(
                (start_date, end_date, depth * 100.0, rec_days, unrecovered)
            )
            i = j + 1 if not unrecovered else n
        else:
            i += 1
    # sort by depth ascending (most negative first)
    periods.sort(key=lambda x: x[2])
    return periods


def _plot_drawdown(nav: np.ndarray, idx: pd.DatetimeIndex) -> str:
    cummax = np.maximum.accumulate(nav)
    dd = (nav - cummax) / cummax * 100.0
    fig, ax = plt.subplots(figsize=(10, 3))
    ax.fill_between(idx, dd, 0, color="#d62728", alpha=0.5)
    ax.set_title("Drawdown")
    ax.set_ylabel("Drawdown (%)")
    ax.grid(True, alpha=0.3)
    return _fig_to_base64(fig)


def _plot_underwater(nav: np.ndarray, idx: pd.DatetimeIndex) -> str:
    cummax = np.maximum.accumulate(nav)
    underwater = (nav / cummax - 1.0) * 100.0
    fig, ax = plt.subplots(figsize=(10, 3))
    ax.fill_between(idx, underwater, 0, color="#9467bd", alpha=0.4)
    ax.plot(idx, underwater, color="#6a3a99", linewidth=0.8)
    ax.set_title("Underwater Plot")
    ax.set_ylabel("Drawdown from peak (%)")
    ax.grid(True, alpha=0.3)
    return _fig_to_base64(fig)


def _rolling_mdd(returns: np.ndarray, idx: pd.DatetimeIndex,
                 window: int = 252) -> str:
    """Rolling maximum drawdown over a trailing window."""
    r = np.asarray(returns, dtype=float)
    n = len(r)
    out = np.full(n, np.nan)
    if n >= 2:
        nav = np.cumprod(1.0 + np.nan_to_num(r))
        nav = np.where(nav <= 0, 1e-12, nav)
        for i in range(n):
            lo = max(0, i - window + 1)
            seg = nav[lo:i + 1]
            if len(seg) >= 2:
                cm = np.maximum.accumulate(seg)
                dd = (seg - cm) / cm
                out[i] = float(dd.min()) * 100.0
    fig, ax = plt.subplots(figsize=(10, 3))
    ax.fill_between(idx, out, 0, color="#d62728", alpha=0.4)
    ax.plot(idx, out, color="#7a1e1e", linewidth=0.8)
    ax.set_title(f"Rolling Max Drawdown ({window}-bar window)")
    ax.set_ylabel("Max DD (%)")
    ax.grid(True, alpha=0.3)
    return _fig_to_base64(fig)


def _top_drawdowns_table(returns: np.ndarray, timestamps,
                         n: int = 5) -> List[Tuple]:
    """Top n drawdowns by depth, each (start, end, depth_pct, recovery_days)."""
    r = np.asarray(returns, dtype=float)
    if len(r) < 2:
        return []
    nav = np.cumprod(1.0 + np.nan_to_num(r))
    nav = np.where(nav <= 0, 1e-12, nav)
    periods = _drawdown_periods(nav, timestamps)
    return periods[:n]


def _top_dd_html(rows: List[Tuple]) -> str:
    """Render top drawdowns table.

    Supports legacy 4-tuples (start, end, depth, rec_days) and new 5-tuples
    (... rec_days, unrecovered). Unrecovered drawdowns get a trailing '+'
    on rec_days and an explicit "open" status column.
    """
    if not rows:
        return '<p class="muted">No drawdown periods detected.</p>'
    out = ("<table><tr><th>#</th><th>Start</th><th>End</th>"
           "<th>Depth (%)</th><th>Recovery (days)</th><th>Status</th></tr>")
    for i, row in enumerate(rows, 1):
        s, e, dpct, rec = row[0], row[1], row[2], row[3]
        unrec = bool(row[4]) if len(row) > 4 else False
        s_str = pd.Timestamp(s).date() if not isinstance(s, (int, np.integer)) else str(s)
        e_str = pd.Timestamp(e).date() if not isinstance(e, (int, np.integer)) else str(e)
        if isinstance(rec, (float, np.floating)) and np.isnan(rec):
            rec_str = "NaN"
        else:
            rec_str = f"{int(rec)}"
            if unrec:
                rec_str += "+"
        status = "open" if unrec else "recovered"
        out += (
            f"<tr><td>{i}</td><td>{_esc(s_str)}</td><td>{_esc(e_str)}</td>"
            f"<td class='neg'>{dpct:.2f}</td><td>{_esc(rec_str)}</td>"
            f"<td>{_esc(status)}</td></tr>"
        )
    out += "</table>"
    return out
