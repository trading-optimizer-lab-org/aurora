"""Signal attribution and cost breakdown: round-trips, returns histogram,
rolling Sharpe (single + multi-window), distribution comparison,
risk-return scatter.
"""
from __future__ import annotations

from typing import Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats as _scstats

from .header import _esc, _fig_to_base64, _to_pd_index


def _rolling_sharpe(returns: np.ndarray, window: int = 252, ppy: int = 252) -> np.ndarray:
    """Rolling annualized Sharpe over `window` bars."""
    r = np.asarray(returns, dtype=float)
    n = len(r)
    out = np.full(n, np.nan)
    if n < window:
        return out
    s = pd.Series(r)
    mean = s.rolling(window).mean()
    std = s.rolling(window).std()
    sr = (mean / std) * np.sqrt(ppy)
    return sr.values


def _plot_returns_hist(returns: np.ndarray) -> str:
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    fig, ax = plt.subplots(figsize=(10, 3.5))
    if len(r) == 0:
        ax.text(0.5, 0.5, "No returns", ha="center", va="center")
        ax.axis("off")
        return _fig_to_base64(fig)
    n_bins = min(60, max(10, int(np.sqrt(len(r)))))
    ax.hist(r * 100, bins=n_bins, density=True, color="#1f77b4",
            alpha=0.6, edgecolor="white", linewidth=0.5)
    mu, sigma = float(np.mean(r) * 100), float(np.std(r) * 100)
    if sigma > 1e-9:
        x = np.linspace(r.min() * 100, r.max() * 100, 200)
        ax.plot(x, _scstats.norm.pdf(x, mu, sigma), color="black",
                linestyle="--", linewidth=1.2, label=f"N({mu:.3f}, {sigma:.3f})")
        ax.legend()
    ax.set_title("Returns Distribution")
    ax.set_xlabel("Return (%)")
    ax.set_ylabel("Density")
    ax.grid(True, alpha=0.3)
    return _fig_to_base64(fig)


def _plot_rolling_sharpe(rolling_sr: np.ndarray, idx: pd.DatetimeIndex,
                         window: int) -> str:
    fig, ax = plt.subplots(figsize=(10, 3))
    ax.plot(idx, rolling_sr, color="#2ca02c", linewidth=1.2)
    ax.axhline(0, color="black", linewidth=0.5)
    ax.set_title(f"Rolling Sharpe ({window}-bar window)")
    ax.set_ylabel("Sharpe (annualized)")
    ax.grid(True, alpha=0.3)
    return _fig_to_base64(fig)


def _distribution_chart(returns: np.ndarray,
                        benchmark_returns: Optional[np.ndarray] = None) -> str:
    """Histogram of strategy returns + normal overlay + KDE.

    If benchmark_returns provided, overlay a thin benchmark histogram.
    """
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    fig, ax = plt.subplots(figsize=(10, 3.8))
    if len(r) == 0:
        ax.text(0.5, 0.5, "No returns", ha="center", va="center")
        ax.axis("off")
        return _fig_to_base64(fig)
    n_bins = min(60, max(10, int(np.sqrt(len(r)))))
    ax.hist(r * 100, bins=n_bins, density=True, color="#1f77b4",
            alpha=0.55, edgecolor="white", linewidth=0.5, label="Strategy")
    mu, sigma = float(np.mean(r) * 100), float(np.std(r) * 100)
    if sigma > 1e-9:
        x = np.linspace(r.min() * 100, r.max() * 100, 200)
        ax.plot(x, _scstats.norm.pdf(x, mu, sigma), color="black",
                linestyle="--", linewidth=1.2,
                label=f"Normal({mu:.3f}, {sigma:.3f})")
        # KDE overlay (gaussian kernel)
        try:
            kde = _scstats.gaussian_kde(r * 100)
            ax.plot(x, kde(x), color="#d62728", linewidth=1.4, label="KDE")
        except Exception:
            pass
    if benchmark_returns is not None:
        b = np.asarray(benchmark_returns, dtype=float)
        b = b[~np.isnan(b)]
        if len(b) > 0:
            ax.hist(b * 100, bins=n_bins, density=True, color="#999999",
                    alpha=0.35, edgecolor="white", linewidth=0.4,
                    label="Benchmark")
    ax.set_title("Returns Distribution")
    ax.set_xlabel("Return (%)")
    ax.set_ylabel("Density")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left", fontsize=9)
    return _fig_to_base64(fig)


def _rolling_sharpe_multi(returns: np.ndarray, idx: pd.DatetimeIndex,
                          windows=(21, 63, 252), ppy: int = 252) -> str:
    """Rolling Sharpe at multiple window sizes on a single chart."""
    fig, ax = plt.subplots(figsize=(10, 3.5))
    colors = ["#2ca02c", "#ff7f0e", "#1f77b4", "#9467bd", "#8c564b"]
    for k, w in enumerate(windows):
        sr = _rolling_sharpe(returns, window=w, ppy=ppy)
        ax.plot(idx, sr, color=colors[k % len(colors)], linewidth=1.1,
                label=f"{w}-bar")
    ax.axhline(0, color="black", linewidth=0.5)
    ax.set_title("Rolling Sharpe (multiple windows)")
    ax.set_ylabel("Sharpe (annualized)")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left", fontsize=9)
    return _fig_to_base64(fig)


def _risk_return_scatter(strategy_returns: np.ndarray,
                          benchmark_returns: Optional[np.ndarray] = None,
                          ppy: int = 252) -> str:
    """Annualized risk vs return scatter: strategy vs benchmark."""
    fig, ax = plt.subplots(figsize=(7, 5))
    points = []
    sr = np.asarray(strategy_returns, dtype=float)
    sr = sr[~np.isnan(sr)]
    if len(sr) > 1:
        s_mean = float(np.mean(sr)) * ppy * 100.0
        s_std = float(np.std(sr)) * np.sqrt(ppy) * 100.0
        points.append(("Strategy", s_mean, s_std, "#1f77b4"))
    if benchmark_returns is not None:
        br = np.asarray(benchmark_returns, dtype=float)
        br = br[~np.isnan(br)]
        if len(br) > 1:
            b_mean = float(np.mean(br)) * ppy * 100.0
            b_std = float(np.std(br)) * np.sqrt(ppy) * 100.0
            points.append(("Benchmark", b_mean, b_std, "#999999"))
    if not points:
        ax.text(0.5, 0.5, "No data", ha="center", va="center")
        ax.axis("off")
        return _fig_to_base64(fig)
    for label, ret, vol, color in points:
        ax.scatter([vol], [ret], s=140, color=color, edgecolor="black",
                   linewidth=0.8, label=label, zorder=3)
        ax.annotate(label, (vol, ret), textcoords="offset points",
                    xytext=(8, 6), fontsize=10)
    ax.axhline(0, color="black", linewidth=0.5)
    ax.set_xlabel("Annualized Volatility (%)")
    ax.set_ylabel("Annualized Return (%)")
    ax.set_title("Risk vs Return")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best", fontsize=9)
    return _fig_to_base64(fig)


def _extract_round_trips(weights: np.ndarray, prices: np.ndarray,
                         timestamps) -> pd.DataFrame:
    """Extract round-trip trades from weights series + prices.

    A round-trip is a contiguous run with the same sign weight (long or short).
    Entry: first bar with non-zero weight after a flat or sign-flip.
    Exit: bar where weight returns to zero or flips sign.
    PnL: signed return over holding period times entry weight.

    Returns DataFrame with columns: entry_date, exit_date, side, bars, pnl_pct.
    Empty DataFrame if no trades.
    """
    w = np.asarray(weights, dtype=float)
    p = np.asarray(prices, dtype=float)
    n = len(w)
    if n < 2 or len(p) != n:
        return pd.DataFrame(columns=["entry_date", "exit_date", "side",
                                      "bars", "pnl_pct", "is_open"])

    idx = _to_pd_index(timestamps)
    sign = np.sign(w)
    trades = []
    i = 0
    while i < n:
        if sign[i] == 0:
            i += 1
            continue
        # entry
        s = sign[i]
        entry_i = i
        entry_w = w[i]
        # walk while same sign
        j = i + 1
        while j < n and sign[j] == s:
            j += 1
        # exit at j (or last bar). When ``j == n`` the position is still
        # held at the final bar, so the trade is open and the exit price
        # is only a snapshot. Mirror ``_drawdown_periods`` ``unrecovered``
        # pattern by surfacing this as ``is_open=True``.
        is_open = j >= n
        exit_i = min(j, n - 1)
        if p[entry_i] > 0:
            raw_ret = (p[exit_i] / p[entry_i]) - 1.0
            pnl = raw_ret * entry_w
        else:
            pnl = float("nan")
        trades.append({
            "entry_date": idx[entry_i],
            "exit_date": idx[exit_i],
            "side": "long" if s > 0 else "short",
            "bars": int(exit_i - entry_i),
            "pnl_pct": float(pnl * 100.0),
            "is_open": bool(is_open),
        })
        i = j
    return pd.DataFrame(trades)


def _top_trades_table(weights: np.ndarray, prices: np.ndarray,
                      timestamps, n: int = 10) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Return (top_n_best, top_n_worst) DataFrames of round-trip trades."""
    df = _extract_round_trips(weights, prices, timestamps)
    if df.empty:
        return df, df
    df_sorted = df.sort_values("pnl_pct", ascending=False)
    best = df_sorted.head(n).copy()
    worst = df_sorted.tail(n).iloc[::-1].copy()  # worst first
    return best, worst


def _trades_to_html(best: pd.DataFrame, worst: pd.DataFrame) -> str:
    """Render top best/worst round-trip tables side-by-side."""
    if best.empty and worst.empty:
        return '<p class="muted">No round-trip trades extracted.</p>'

    def _df_to_table(df: pd.DataFrame, caption: str) -> str:
        if df.empty:
            return f'<p class="muted">{_esc(caption)}: none.</p>'
        # ``is_open`` is optional for back-compat with callers that pass
        # legacy round-trip frames (e.g. external tests). Surface a
        # Status column only when at least one row is flagged open, to
        # avoid noise on fully-closed strategies.
        has_open_col = ("is_open" in df.columns and bool(df["is_open"].any()))
        n_cols = 6 if has_open_col else 5
        rows = (
            f"<table><tr><th colspan='{n_cols}'>" + _esc(caption) + "</th></tr>"
            "<tr><th>Entry</th><th>Exit</th><th>Side</th>"
            "<th>Bars</th><th>PnL (%)</th>"
            + ("<th>Status</th>" if has_open_col else "")
            + "</tr>"
        )
        for _, r in df.iterrows():
            ent = pd.Timestamp(r["entry_date"]).date()
            ext = pd.Timestamp(r["exit_date"]).date()
            pnl = r["pnl_pct"]
            cls = "pos" if pnl >= 0 else "neg"
            status_cell = ""
            if has_open_col:
                status = "open" if bool(r.get("is_open", False)) else "closed"
                status_cell = f"<td>{_esc(status)}</td>"
            rows += (
                f"<tr><td>{_esc(ent)}</td><td>{_esc(ext)}</td>"
                f"<td>{_esc(r['side'])}</td>"
                f"<td>{int(r['bars'])}</td><td class='{cls}'>{pnl:.2f}</td>"
                f"{status_cell}</tr>"
            )
        rows += "</table>"
        return rows

    return (
        '<div class="split-tables">'
        f'<div>{_df_to_table(best, "Top 10 Best Trades")}</div>'
        f'<div>{_df_to_table(worst, "Top 10 Worst Trades")}</div>'
        '</div>'
    )
