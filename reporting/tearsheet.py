"""HTML/PDF tearsheet generator for BacktestResult.

Self-contained HTML output with base64-embedded matplotlib PNGs.
No external CSS, no JS; can be opened offline or emailed as a single file.

Sections (basic - generate_tearsheet):
    1. Title + key stats table
    2. Equity curve (with optional benchmark overlay)
    3. Drawdown curve
    4. Monthly returns heatmap (year x month)
    5. Returns distribution histogram with normal overlay
    6. Rolling Sharpe (252-bar default window)
    7. Top 5 drawdown periods table
    8. Monthly statistics table
    9. Underwater plot

Extended (generate_full_tearsheet adds):
    10. Round-trip table: top 10 best/worst trades from weights
    11. Monthly returns table (year x month with row totals + YTD)
    12. Distribution comparison (histogram + normal + KDE overlay)
    13. Rolling Sharpe multiple windows (21, 63, 252)
    14. Rolling MDD over time
    15. Year-over-year returns bar chart
    16. Risk-return scatter vs benchmark
    17. 5 worst drawdown periods table (depth + recovery)
"""
from __future__ import annotations

import base64
import contextlib
import html as _html
import io
import os
from dataclasses import asdict
from typing import List, Optional, Tuple

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats as _scstats


def _esc(value) -> str:
    """HTML-escape an arbitrary value for safe interpolation into the
    template. ``None`` / NaN render as ``""``.
    """
    if value is None:
        return ""
    if isinstance(value, float):
        if np.isnan(value) or np.isinf(value):
            return "NaN"
        return _html.escape(repr(value), quote=True)
    return _html.escape(str(value), quote=True)


_BACKEND_FORCED = False


def _ensure_agg_backend():
    """Force Agg backend lazily. Idempotent. Always safe in headless / CI.

    On non-Windows hosts we previously gated on $DISPLAY, but matplotlib's Tk
    backend can fail on minimal Windows installs (no Tk runtime), so we now
    use Agg whenever no GUI display is available. Existing interactive
    sessions with DISPLAY set or running inside an IDE keep their backend.

    NOTE: this performs a *global* backend switch and is reserved for the
    one-shot import-time fallback below. From inside test code, prefer
    :func:`agg_backend_scope`, which restores the prior backend on exit so
    a unit test for tearsheet rendering does not leak backend state into
    sibling tests that assume the user-configured GUI backend.
    """
    global _BACKEND_FORCED
    if _BACKEND_FORCED:
        return
    has_display = (
        os.environ.get("DISPLAY")
        or os.environ.get("MPLBACKEND")
        or os.environ.get("PYCHARM_HOSTED")
    )
    if not has_display:
        try:
            matplotlib.use("Agg", force=True)
        except Exception:
            pass
    _BACKEND_FORCED = True


@contextlib.contextmanager
def agg_backend_scope():
    """Context manager that ensures Agg is the active matplotlib backend
    inside the ``with`` block and restores the prior backend on exit.

    Used by the public render helpers when called under pytest
    (``PYTEST_CURRENT_TEST`` set in env): tearsheet rendering must always
    succeed without a GUI display, but the test should not leak a global
    backend change into other tests.

    Outside a test environment this still works correctly — it just acts
    as a transient switch into Agg with restoration on exit.

    The module-level ``_BACKEND_FORCED`` flag is also reset on exit so
    that a subsequent non-pytest call to :func:`_ensure_agg_backend` will
    re-evaluate display state instead of skipping based on a stale
    "already forced" state from inside the scope.
    """
    global _BACKEND_FORCED
    prior_forced = _BACKEND_FORCED
    prior = matplotlib.get_backend()
    switched = False
    if prior.lower() != "agg":
        try:
            matplotlib.use("Agg", force=True)
            switched = True
        except Exception:
            switched = False
    try:
        yield
    finally:
        if switched:
            try:
                matplotlib.use(prior, force=True)
            except Exception:
                # If we cannot restore (e.g. Tk no longer available in this
                # process), leave Agg active rather than crashing — the
                # original backend was probably non-functional anyway.
                pass
        # Restore the prior ``_BACKEND_FORCED`` value so the lazy switch
        # path can fire again if the surrounding session expects it.
        _BACKEND_FORCED = prior_forced


def _running_under_pytest() -> bool:
    """True iff the current process is executing inside a pytest test.

    Triggered by pytest's per-test ``PYTEST_CURRENT_TEST`` env var, which is
    set even for parameterized and concurrent runs.
    """
    return "PYTEST_CURRENT_TEST" in os.environ


# Force Agg at import time too: many code paths call plt.subplots before the
# first _fig_to_base64 (which is where the lazy switch used to fire), so the
# Tk default backend would be picked up first and fail on Tk-less environments.
# Under pytest we instead defer the switch to render time via
# ``agg_backend_scope`` so tests do not leak a global backend change.
if not _running_under_pytest():
    _ensure_agg_backend()


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _to_pd_index(timestamps) -> pd.DatetimeIndex:
    """Convert np.datetime64 array (or anything pandas can parse) to DatetimeIndex."""
    return pd.DatetimeIndex(pd.to_datetime(timestamps))


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


def _monthly_returns_matrix(returns: np.ndarray, timestamps) -> pd.DataFrame:
    """Pivot returns into year x month grid (compounded monthly returns, percent)."""
    idx = _to_pd_index(timestamps)
    s = pd.Series(np.asarray(returns, dtype=float), index=idx).dropna()
    if len(s) == 0:
        return pd.DataFrame()
    monthly = (1.0 + s).resample("ME").prod() - 1.0
    df = pd.DataFrame({"ret": monthly.values}, index=monthly.index)
    df["year"] = df.index.year
    df["month"] = df.index.month
    pivot = df.pivot_table(index="year", columns="month", values="ret", aggfunc="sum")
    # ensure all 12 columns present
    for m in range(1, 13):
        if m not in pivot.columns:
            pivot[m] = np.nan
    pivot = pivot[sorted(pivot.columns)]
    return pivot * 100.0  # percent


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


def _fig_to_base64(fig) -> str:
    """Render matplotlib Figure to base64-encoded PNG string."""
    _ensure_agg_backend()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=110)
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")


# ---------------------------------------------------------------------------
# Plot builders (basic)
# ---------------------------------------------------------------------------


def _plot_equity(nav: np.ndarray, idx: pd.DatetimeIndex,
                 benchmark_nav: Optional[np.ndarray] = None,
                 bench_idx: Optional[pd.DatetimeIndex] = None) -> str:
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(idx, nav, label="Strategy", color="#1f77b4", linewidth=1.4)
    if benchmark_nav is not None and bench_idx is not None:
        ax.plot(bench_idx, benchmark_nav, label="Benchmark",
                color="#999999", linewidth=1.0, linestyle="--")
    ax.set_title("Equity Curve")
    ax.set_ylabel("NAV (start = 1.0)")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left")
    return _fig_to_base64(fig)


def _plot_drawdown(nav: np.ndarray, idx: pd.DatetimeIndex) -> str:
    cummax = np.maximum.accumulate(nav)
    dd = (nav - cummax) / cummax * 100.0
    fig, ax = plt.subplots(figsize=(10, 3))
    ax.fill_between(idx, dd, 0, color="#d62728", alpha=0.5)
    ax.set_title("Drawdown")
    ax.set_ylabel("Drawdown (%)")
    ax.grid(True, alpha=0.3)
    return _fig_to_base64(fig)


def _plot_monthly_heatmap(pivot: pd.DataFrame) -> str:
    if pivot.empty:
        fig, ax = plt.subplots(figsize=(8, 2))
        ax.text(0.5, 0.5, "No monthly data", ha="center", va="center")
        ax.axis("off")
        return _fig_to_base64(fig)

    fig, ax = plt.subplots(figsize=(10, max(2, 0.4 * len(pivot))))
    data = pivot.values
    vmax = np.nanmax(np.abs(data)) if not np.all(np.isnan(data)) else 1.0
    im = ax.imshow(data, aspect="auto", cmap="RdYlGn", vmin=-vmax, vmax=vmax)
    ax.set_xticks(range(12))
    ax.set_xticklabels(["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels([str(y) for y in pivot.index])
    ax.set_title("Monthly Returns (%)")
    for i in range(data.shape[0]):
        for j in range(data.shape[1]):
            v = data[i, j]
            if not np.isnan(v):
                ax.text(j, i, f"{v:.1f}", ha="center", va="center",
                        fontsize=7, color="black")
    fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02)
    return _fig_to_base64(fig)


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


# ---------------------------------------------------------------------------
# Extended helpers (v2)
# ---------------------------------------------------------------------------


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


def _monthly_returns_table(returns: np.ndarray, timestamps) -> pd.DataFrame:
    """Year x month percent table with row totals (YTD).

    Returns a DataFrame indexed by year, columns Jan..Dec + YTD.
    """
    pivot = _monthly_returns_matrix(returns, timestamps)
    if pivot.empty:
        return pivot
    # rename month columns to short names
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    pivot = pivot.copy()
    pivot.columns = [month_names[m - 1] for m in pivot.columns]
    # YTD = compounded across months in the year
    ytd = []
    for _, row in pivot.iterrows():
        vals = row.dropna().values / 100.0
        if len(vals) == 0:
            ytd.append(np.nan)
        else:
            ytd.append((np.prod(1.0 + vals) - 1.0) * 100.0)
    pivot["YTD"] = ytd
    return pivot


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


def _yoy_bar_chart(returns: np.ndarray, timestamps) -> str:
    """Year-over-year compounded returns as a bar chart."""
    idx = _to_pd_index(timestamps)
    s = pd.Series(np.asarray(returns, dtype=float), index=idx).dropna()
    fig, ax = plt.subplots(figsize=(10, 3.2))
    if len(s) == 0:
        ax.text(0.5, 0.5, "No returns", ha="center", va="center")
        ax.axis("off")
        return _fig_to_base64(fig)
    yearly = (1.0 + s).groupby(s.index.year).prod() - 1.0
    yearly_pct = yearly * 100.0
    colors = ["#2ca02c" if v >= 0 else "#d62728" for v in yearly_pct.values]
    ax.bar([str(y) for y in yearly_pct.index], yearly_pct.values, color=colors,
           edgecolor="white", linewidth=0.6)
    for i, v in enumerate(yearly_pct.values):
        ax.text(i, v, f"{v:.1f}%", ha="center",
                va="bottom" if v >= 0 else "top", fontsize=8)
    ax.axhline(0, color="black", linewidth=0.5)
    ax.set_title("Year-over-Year Returns")
    ax.set_ylabel("Return (%)")
    ax.grid(True, alpha=0.3, axis="y")
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


# ---------------------------------------------------------------------------
# HTML template (basic)
# ---------------------------------------------------------------------------


_CSS = """
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
       max-width: 1100px; margin: 30px auto; color: #222; background: #fafafa; padding: 0 20px; }
h1 { font-size: 26px; border-bottom: 2px solid #333; padding-bottom: 8px; }
h2 { font-size: 18px; color: #333; margin-top: 32px; border-left: 4px solid #1f77b4;
     padding-left: 10px; }
table { border-collapse: collapse; margin: 14px 0; font-size: 13px; }
th, td { padding: 6px 14px; text-align: right; border-bottom: 1px solid #ddd; }
th { background: #ececec; text-align: left; }
td.label { text-align: left; font-weight: 600; }
img { max-width: 100%; height: auto; display: block; margin: 8px 0; }
.section { background: white; padding: 18px 22px; margin: 16px 0;
           border: 1px solid #e0e0e0; border-radius: 5px; }
.stats-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px;
              margin: 12px 0; }
.stat { padding: 10px; background: #f0f4f9; border-left: 4px solid #1f77b4;
        border-radius: 3px; }
.stat .label { font-size: 11px; color: #666; text-transform: uppercase; }
.stat .value { font-size: 18px; font-weight: 600; color: #222; }
.muted { color: #888; font-size: 11px; }
.pos { color: #1a7e1a; }
.neg { color: #b22222; }
.split-tables { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
@media (max-width: 800px) { .split-tables { grid-template-columns: 1fr; } }
"""


def _html_template(title: str,
                   metrics_dict: dict,
                   eq_b64: str,
                   dd_b64: str,
                   heatmap_b64: str,
                   hist_b64: str,
                   rolling_b64: str,
                   uw_b64: str,
                   top_dd_rows: List[Tuple],
                   monthly_pivot: pd.DataFrame) -> str:
    """Compose final HTML with all sections embedded (basic tearsheet)."""

    def fmt(v, pct=False):
        if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
            return "NaN"
        if pct:
            return f"{v:.2f}%"
        if isinstance(v, float):
            return f"{v:.4f}"
        return str(v)

    def _pct_value(key, v):
        # cagr/mdd come pre-multiplied by 100 from compute_metrics; win_rate
        # is in [0,1] and must be scaled before percent rendering.
        if key == "win_rate" and isinstance(v, (int, float)) and v is not None:
            try:
                if not (np.isnan(v) or np.isinf(v)):
                    return float(v) * 100.0
            except (TypeError, ValueError):
                pass
        return v

    # 1) stats grid + full table
    grid_keys = [
        ("CAGR", "cagr", True), ("Max Drawdown", "mdd", True),
        ("Calmar", "calmar", False), ("Sharpe", "sharpe", False),
        ("Sortino", "sortino", False), ("MAR", "mar", False),
        ("Win Rate", "win_rate", True), ("Profit Factor", "profit_factor", False),
    ]
    stat_cards = ""
    for label, key, pct in grid_keys:
        v = metrics_dict.get(key)
        if pct:
            v = _pct_value(key, v)
        stat_cards += (
            f'<div class="stat"><div class="label">{_esc(label)}</div>'
            f'<div class="value">{_esc(fmt(v, pct=pct))}</div></div>'
        )

    full_table = "<table><tr><th>Metric</th><th>Value</th></tr>"
    for k, v in metrics_dict.items():
        is_pct = k in ("cagr", "mdd", "win_rate")
        if is_pct:
            v = _pct_value(k, v)
        full_table += (
            f'<tr><td class="label">{_esc(k)}</td>'
            f'<td>{_esc(fmt(v, pct=is_pct))}</td></tr>'
        )
    full_table += "</table>"

    # 2) top drawdown table
    if top_dd_rows:
        dd_table = ("<table><tr><th>#</th><th>Start</th><th>End</th>"
                    "<th>Depth (%)</th><th>Recovery (days)</th>"
                    "<th>Status</th></tr>")
        for i, row in enumerate(top_dd_rows[:5], 1):
            # Support legacy 4-tuples and new 5-tuples (with unrecovered flag).
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
            dd_table += (
                f"<tr><td>{i}</td><td>{_esc(s_str)}</td><td>{_esc(e_str)}</td>"
                f"<td>{dpct:.2f}</td><td>{_esc(rec_str)}</td>"
                f"<td>{_esc(status)}</td></tr>"
            )
        dd_table += "</table>"
    else:
        dd_table = '<p class="muted">No drawdown periods detected.</p>'

    # 3) monthly statistics table
    if not monthly_pivot.empty:
        flat = monthly_pivot.values.flatten()
        flat = flat[~np.isnan(flat)]
        if len(flat) > 0:
            mstats = (
                f"<table><tr><th>Stat</th><th>Value</th></tr>"
                f"<tr><td class='label'>Mean monthly</td><td>{flat.mean():.2f}%</td></tr>"
                f"<tr><td class='label'>Std monthly</td><td>{flat.std():.2f}%</td></tr>"
                f"<tr><td class='label'>Best month</td><td>{flat.max():.2f}%</td></tr>"
                f"<tr><td class='label'>Worst month</td><td>{flat.min():.2f}%</td></tr>"
                f"<tr><td class='label'>Positive months</td>"
                f"<td>{int((flat > 0).sum())} / {len(flat)}</td></tr>"
                f"</table>"
            )
        else:
            mstats = '<p class="muted">No monthly data.</p>'
    else:
        mstats = '<p class="muted">No monthly data.</p>'

    safe_title = _esc(title)
    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<title>{safe_title}</title>
<style>{_CSS}</style>
</head><body>
<h1>{safe_title}</h1>
<p class="muted">Generated by QuantForge tearsheet.py</p>

<div class="section">
  <h2>1. Key Statistics</h2>
  <div class="stats-grid">{stat_cards}</div>
  {full_table}
</div>

<div class="section">
  <h2>2. Equity Curve</h2>
  <img src="data:image/png;base64,{eq_b64}" alt="Equity curve">
</div>

<div class="section">
  <h2>3. Drawdown</h2>
  <img src="data:image/png;base64,{dd_b64}" alt="Drawdown">
</div>

<div class="section">
  <h2>4. Monthly Returns Heatmap</h2>
  <img src="data:image/png;base64,{heatmap_b64}" alt="Heatmap">
</div>

<div class="section">
  <h2>5. Returns Distribution</h2>
  <img src="data:image/png;base64,{hist_b64}" alt="Returns distribution">
</div>

<div class="section">
  <h2>6. Rolling Sharpe</h2>
  <img src="data:image/png;base64,{rolling_b64}" alt="Rolling Sharpe">
</div>

<div class="section">
  <h2>7. Top 5 Drawdown Periods</h2>
  {dd_table}
</div>

<div class="section">
  <h2>8. Monthly Statistics</h2>
  {mstats}
</div>

<div class="section">
  <h2>9. Underwater Plot</h2>
  <img src="data:image/png;base64,{uw_b64}" alt="Underwater">
</div>

</body></html>"""
    return html


# ---------------------------------------------------------------------------
# Extended HTML rendering helpers (v2)
# ---------------------------------------------------------------------------


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


def _monthly_table_html(table: pd.DataFrame) -> str:
    """Render monthly returns table (year x month + YTD)."""
    if table.empty:
        return '<p class="muted">No monthly data.</p>'
    cols = list(table.columns)
    head = "<tr><th>Year</th>" + "".join(f"<th>{c}</th>" for c in cols) + "</tr>"
    body = ""
    for year, row in table.iterrows():
        cells = []
        for c in cols:
            v = row[c]
            if pd.isna(v):
                cells.append("<td>—</td>")
            else:
                cls = "pos" if v >= 0 else "neg"
                cells.append(f"<td class='{cls}'>{v:.2f}</td>")
        body += f"<tr><td class='label'>{int(year)}</td>" + "".join(cells) + "</tr>"
    return f"<table>{head}{body}</table>"


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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_tearsheet(result, output_path: str,
                       title: str = "QuantForge Tearsheet",
                       benchmark_result=None) -> str:
    """Generate self-contained HTML tearsheet from a BacktestResult.

    Args:
        result: BacktestResult with .nav, .rets, .timestamps, .metrics
        output_path: file path (.html) to write
        title: page title
        benchmark_result: optional BacktestResult overlaid as benchmark

    Returns:
        Absolute path to written HTML file.
    """
    if _running_under_pytest():
        with agg_backend_scope():
            return _generate_tearsheet_impl(result, output_path, title, benchmark_result)
    return _generate_tearsheet_impl(result, output_path, title, benchmark_result)


def _generate_tearsheet_impl(result, output_path: str,
                             title: str,
                             benchmark_result) -> str:
    nav = np.asarray(result.nav, dtype=float)
    rets = np.asarray(result.rets, dtype=float)
    timestamps = result.timestamps
    idx = _to_pd_index(timestamps)

    # NaN-safe
    if len(nav) == 0:
        raise ValueError("BacktestResult has empty nav array")

    # benchmark NAV overlay
    bench_nav, bench_idx = None, None
    if benchmark_result is not None:
        bench_nav = np.asarray(benchmark_result.nav, dtype=float)
        bench_idx = _to_pd_index(benchmark_result.timestamps)

    # plots
    eq_b64 = _plot_equity(nav, idx, bench_nav, bench_idx)
    dd_b64 = _plot_drawdown(nav, idx)
    pivot = _monthly_returns_matrix(rets, timestamps)
    heatmap_b64 = _plot_monthly_heatmap(pivot)
    hist_b64 = _plot_returns_hist(rets[1:] if len(rets) > 1 else rets)

    # rolling sharpe: use full-series window
    n = len(rets)
    win = 252 if n >= 300 else max(20, n // 4)
    rsr = _rolling_sharpe(rets, window=win)
    rolling_b64 = _plot_rolling_sharpe(rsr, idx, win)

    uw_b64 = _plot_underwater(nav, idx)

    # tables
    top_dd = _drawdown_periods(nav, timestamps)

    metrics_dict = (result.metrics.to_dict()
                    if hasattr(result.metrics, "to_dict")
                    else asdict(result.metrics))

    html = _html_template(
        title=title,
        metrics_dict=metrics_dict,
        eq_b64=eq_b64,
        dd_b64=dd_b64,
        heatmap_b64=heatmap_b64,
        hist_b64=hist_b64,
        rolling_b64=rolling_b64,
        uw_b64=uw_b64,
        top_dd_rows=top_dd,
        monthly_pivot=pivot,
    )

    abs_path = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(html)
    return abs_path


def generate_full_tearsheet(result, output_path: str,
                            title: str = "QuantForge Full Tearsheet",
                            benchmark_result=None,
                            include_round_trips: bool = True,
                            include_distributions: bool = True) -> str:
    """Extended tearsheet with all sections enabled.

    Adds quantstats-style sections on top of the basic tearsheet:
        10. Round-trip table (top 10 best/worst trades)
        11. Monthly returns table (year x month + YTD)
        12. Distribution comparison (histogram + normal + KDE)
        13. Rolling Sharpe at 21/63/252 windows
        14. Rolling MDD over time
        15. Year-over-year returns bar chart
        16. Risk-return scatter vs benchmark
        17. 5 worst drawdown periods table

    Args:
        result: BacktestResult
        output_path: HTML file path to write
        title: page title
        benchmark_result: optional BacktestResult for overlays + comparison
        include_round_trips: render round-trip tables (requires weights+nav)
        include_distributions: render distribution comparison + KDE
    """
    if _running_under_pytest():
        with agg_backend_scope():
            return _generate_full_tearsheet_impl(
                result, output_path, title, benchmark_result,
                include_round_trips, include_distributions,
            )
    return _generate_full_tearsheet_impl(
        result, output_path, title, benchmark_result,
        include_round_trips, include_distributions,
    )


def _generate_full_tearsheet_impl(result, output_path: str,
                                  title: str,
                                  benchmark_result,
                                  include_round_trips: bool,
                                  include_distributions: bool) -> str:
    nav = np.asarray(result.nav, dtype=float)
    rets = np.asarray(result.rets, dtype=float)
    weights = np.asarray(result.weights, dtype=float)
    timestamps = result.timestamps
    idx = _to_pd_index(timestamps)

    if len(nav) == 0:
        raise ValueError("BacktestResult has empty nav array")

    # benchmark fields
    bench_nav, bench_idx, bench_rets = None, None, None
    if benchmark_result is not None:
        bench_nav = np.asarray(benchmark_result.nav, dtype=float)
        bench_idx = _to_pd_index(benchmark_result.timestamps)
        bench_rets = np.asarray(benchmark_result.rets, dtype=float)

    # ---- Basic charts ----
    eq_b64 = _plot_equity(nav, idx, bench_nav, bench_idx)
    dd_b64 = _plot_drawdown(nav, idx)
    pivot = _monthly_returns_matrix(rets, timestamps)
    heatmap_b64 = _plot_monthly_heatmap(pivot)
    uw_b64 = _plot_underwater(nav, idx)

    # ---- Extended charts ----
    if include_distributions:
        dist_b64 = _distribution_chart(rets[1:] if len(rets) > 1 else rets,
                                        bench_rets[1:] if bench_rets is not None
                                        and len(bench_rets) > 1 else None)
    else:
        dist_b64 = _plot_returns_hist(rets[1:] if len(rets) > 1 else rets)

    rsr_multi_b64 = _rolling_sharpe_multi(rets, idx, windows=(21, 63, 252))
    rmdd_b64 = _rolling_mdd(rets, idx, window=252)
    yoy_b64 = _yoy_bar_chart(rets, timestamps)
    rr_b64 = _risk_return_scatter(rets[1:] if len(rets) > 1 else rets,
                                   bench_rets[1:] if bench_rets is not None
                                   and len(bench_rets) > 1 else None)

    # ---- Tables ----
    monthly_table = _monthly_returns_table(rets, timestamps)
    top_dd = _top_drawdowns_table(rets, timestamps, n=5)

    # round-trip tables: need a price-like series; use NAV as proxy when prices
    # aren't kept on the result. Caller can substitute by overriding result.nav.
    if include_round_trips:
        best, worst = _top_trades_table(weights, nav, timestamps, n=10)
        rt_html = _trades_to_html(best, worst)
    else:
        rt_html = '<p class="muted">Round-trip extraction disabled.</p>'

    metrics_dict = (result.metrics.to_dict()
                    if hasattr(result.metrics, "to_dict")
                    else asdict(result.metrics))

    # ---- Compose HTML ----
    def fmt(v, pct=False):
        if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
            return "NaN"
        if pct:
            return f"{v:.2f}%"
        if isinstance(v, float):
            return f"{v:.4f}"
        return str(v)

    def _pct_value(key, v):
        # cagr/mdd come pre-multiplied by 100 from compute_metrics; win_rate
        # is in [0,1] and must be scaled before percent rendering.
        if key == "win_rate" and isinstance(v, (int, float)) and v is not None:
            try:
                if not (np.isnan(v) or np.isinf(v)):
                    return float(v) * 100.0
            except (TypeError, ValueError):
                pass
        return v

    grid_keys = [
        ("CAGR", "cagr", True), ("Max Drawdown", "mdd", True),
        ("Calmar", "calmar", False), ("Sharpe", "sharpe", False),
        ("Sortino", "sortino", False), ("MAR", "mar", False),
        ("Win Rate", "win_rate", True), ("Profit Factor", "profit_factor", False),
    ]
    stat_cards = ""
    for label, key, pct in grid_keys:
        v = metrics_dict.get(key)
        if pct:
            v = _pct_value(key, v)
        stat_cards += (
            f'<div class="stat"><div class="label">{_esc(label)}</div>'
            f'<div class="value">{_esc(fmt(v, pct=pct))}</div></div>'
        )

    full_table = "<table><tr><th>Metric</th><th>Value</th></tr>"
    for k, v in metrics_dict.items():
        is_pct = k in ("cagr", "mdd", "win_rate")
        if is_pct:
            v = _pct_value(k, v)
        full_table += (
            f'<tr><td class="label">{_esc(k)}</td>'
            f'<td>{_esc(fmt(v, pct=is_pct))}</td></tr>'
        )
    full_table += "</table>"

    monthly_table_html = _monthly_table_html(monthly_table)
    top_dd_html = _top_dd_html(top_dd)

    # benchmark scatter section: only show if benchmark provided
    rr_section = (
        f"""
<div class="section">
  <h2>16. Risk vs Return (Strategy vs Benchmark)</h2>
  <img src="data:image/png;base64,{rr_b64}" alt="Risk return scatter">
</div>
""" if benchmark_result is not None else ""
    )

    safe_title = _esc(title)
    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<title>{safe_title}</title>
<style>{_CSS}</style>
</head><body>
<h1>{safe_title}</h1>
<p class="muted">Generated by QuantForge tearsheet.py (full)</p>

<div class="section">
  <h2>1. Key Statistics</h2>
  <div class="stats-grid">{stat_cards}</div>
  {full_table}
</div>

<div class="section">
  <h2>2. Equity Curve</h2>
  <img src="data:image/png;base64,{eq_b64}" alt="Equity curve">
</div>

<div class="section">
  <h2>3. Drawdown</h2>
  <img src="data:image/png;base64,{dd_b64}" alt="Drawdown">
</div>

<div class="section">
  <h2>4. Monthly Returns Heatmap</h2>
  <img src="data:image/png;base64,{heatmap_b64}" alt="Heatmap">
</div>

<div class="section">
  <h2>5. Underwater Plot</h2>
  <img src="data:image/png;base64,{uw_b64}" alt="Underwater">
</div>

<div class="section">
  <h2>10. Round-Trip Trades</h2>
  {rt_html}
</div>

<div class="section">
  <h2>11. Monthly Returns Table (with YTD)</h2>
  {monthly_table_html}
</div>

<div class="section">
  <h2>12. Returns Distribution (with KDE + Normal)</h2>
  <img src="data:image/png;base64,{dist_b64}" alt="Distribution">
</div>

<div class="section">
  <h2>13. Rolling Sharpe (21 / 63 / 252)</h2>
  <img src="data:image/png;base64,{rsr_multi_b64}" alt="Rolling Sharpe multi">
</div>

<div class="section">
  <h2>14. Rolling Max Drawdown</h2>
  <img src="data:image/png;base64,{rmdd_b64}" alt="Rolling MDD">
</div>

<div class="section">
  <h2>15. Year-over-Year Returns</h2>
  <img src="data:image/png;base64,{yoy_b64}" alt="YoY">
</div>
{rr_section}
<div class="section">
  <h2>17. 5 Worst Drawdown Periods</h2>
  {top_dd_html}
</div>

</body></html>"""

    abs_path = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(html)
    return abs_path


def generate_pdf(result, output_path: str, title: str = "QuantForge Tearsheet",
                 benchmark_result=None) -> str:
    """Generate PDF tearsheet via WeasyPrint or pdfkit.

    Falls back gracefully: if neither package available, raises ImportError
    with installation hint.
    """
    # produce HTML first (next to PDF, with .html extension)
    base, _ = os.path.splitext(output_path)
    html_path = base + ".html"
    generate_tearsheet(result, html_path, title=title,
                       benchmark_result=benchmark_result)

    abs_pdf = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(abs_pdf) or ".", exist_ok=True)

    # Try WeasyPrint first. We narrow the except to *import-time* errors so
    # genuine runtime failures (corrupt HTML, font issues, OS write errors,
    # MemoryError) propagate up instead of silently falling through to pdfkit.
    try:
        from weasyprint import HTML  # type: ignore
    except (ImportError, ModuleNotFoundError):
        weasy_available = False
    else:
        weasy_available = True
        HTML(filename=html_path).write_pdf(abs_pdf)
        return abs_pdf

    # Then pdfkit (wraps wkhtmltopdf). Same rule: only the import is wrapped.
    try:
        import pdfkit  # type: ignore
    except (ImportError, ModuleNotFoundError):
        pdfkit_available = False
    else:
        pdfkit_available = True
        pdfkit.from_file(html_path, abs_pdf)
        return abs_pdf

    if not weasy_available and not pdfkit_available:
        raise ImportError(
            "PDF export requires either 'weasyprint' or 'pdfkit'. "
            "Install with: pip install weasyprint  (recommended)  "
            "or: pip install pdfkit (also needs wkhtmltopdf binary)."
        )
    # Unreachable: at least one branch above either returned or set
    # ``*_available = False``.
    raise RuntimeError("PDF export reached unexpected fallthrough state")
