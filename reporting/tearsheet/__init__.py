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

from .styles import _CSS
from .header import (
    _BACKEND_FORCED,
    _ensure_agg_backend,
    _esc,
    _fig_to_base64,
    _running_under_pytest,
    _to_pd_index,
    agg_backend_scope,
)
from .equity import _plot_equity
from .drawdown import (
    _drawdown_periods,
    _plot_drawdown,
    _plot_underwater,
    _rolling_mdd,
    _top_dd_html,
    _top_drawdowns_table,
)
from .factor import (
    _monthly_returns_matrix,
    _monthly_returns_table,
    _monthly_table_html,
    _plot_monthly_heatmap,
    _yoy_bar_chart,
)
from .attribution import (
    _distribution_chart,
    _extract_round_trips,
    _plot_returns_hist,
    _plot_rolling_sharpe,
    _risk_return_scatter,
    _rolling_sharpe,
    _rolling_sharpe_multi,
    _top_trades_table,
    _trades_to_html,
)
from .metrics_table import _html_template


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
        from weasyprint import HTML
    except (ImportError, ModuleNotFoundError):
        weasy_available = False
    else:
        weasy_available = True
        HTML(filename=html_path).write_pdf(abs_pdf)
        return abs_pdf

    # Then pdfkit (wraps wkhtmltopdf). Same rule: only the import is wrapped.
    try:
        import pdfkit
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
