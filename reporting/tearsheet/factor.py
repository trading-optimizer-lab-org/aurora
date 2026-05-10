"""Calendar / factor-exposure section: monthly returns matrix + heatmap,
year-month + YTD table, year-over-year bar chart.
"""
from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .header import _fig_to_base64, _to_pd_index


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
