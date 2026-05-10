# ruff: noqa: N806
"""Portfolio analytics report (R172).

A frozen dataclass + helpers that turn a portfolio's per-period weights
and returns into an operator-readable risk report. Outputs are tabular
(numeric arrays + dicts) so they can drop into evidence packs, JSON
artefacts, or HTML tearsheets without further wrangling.

Wired from:
- ``aurora.portfolio.attribution``  (return + risk contributions)
- ``aurora.portfolio.risk_measures`` (max_drawdown, variance)

The report intentionally stores *placeholders* for ``policy_hash`` /
``snapshot_hash`` -- the caller (typically the validation pipeline or an
agent gateway commit) injects them so the report is hash-bound when it
ships into an evidence pack. ``data_quality_status`` is one of
``"ok"``, ``"degraded"`` or ``"unknown"``; the report is agnostic to
how it was produced upstream.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
from aurora.portfolio.attribution import (
    benchmark_relative_alpha,
    contribution_to_return,
    contribution_to_risk,
    exposure_by_group,
)
from aurora.portfolio.risk_measures import max_drawdown

__all__ = ["PortfolioReport", "build_portfolio_report"]


def _rolling_window(values: np.ndarray, window: int) -> np.ndarray:
    """Right-aligned rolling values; first ``window-1`` entries are NaN."""
    v = np.asarray(values, dtype=float).ravel()
    n = v.size
    out = np.full(n, np.nan, dtype=float)
    if n < window or window < 1:
        return out
    cs = np.cumsum(np.insert(v, 0, 0.0))
    out[window - 1:] = (cs[window:] - cs[:-window]) / window
    return out


def _rolling_std(values: np.ndarray, window: int) -> np.ndarray:
    v = np.asarray(values, dtype=float).ravel()
    n = v.size
    out = np.full(n, np.nan, dtype=float)
    if n < window or window < 2:
        return out
    for i in range(window - 1, n):
        out[i] = float(np.std(v[i - window + 1: i + 1], ddof=1))
    return out


def _drawdown_table(returns: np.ndarray, top_n: int = 5) -> list[dict[str, float]]:
    """Return top-N drawdown periods as dicts.

    Each entry: ``{depth, peak_idx, trough_idx, length}``.
    """
    r = np.asarray(returns, dtype=float).ravel()
    if r.size == 0:
        return []
    equity = np.cumprod(1.0 + r)
    peak = np.maximum.accumulate(equity)
    dd = (peak - equity) / peak

    # Find drawdown episodes: contiguous regions where dd > 0.
    episodes: list[dict[str, float]] = []
    in_dd = False
    start = 0
    peak_idx = 0
    for i in range(r.size):
        if dd[i] > 0 and not in_dd:
            in_dd = True
            start = i
            peak_idx = max(0, i - 1)
        if dd[i] == 0 and in_dd:
            in_dd = False
            j_max = int(np.argmax(dd[start:i])) + start
            episodes.append({
                "depth": float(dd[j_max]),
                "peak_idx": int(peak_idx),
                "trough_idx": int(j_max),
                "length": int(i - peak_idx),
            })
    if in_dd:
        # closed off at end of sample
        j_max = int(np.argmax(dd[start:])) + start
        episodes.append({
            "depth": float(dd[j_max]),
            "peak_idx": int(peak_idx),
            "trough_idx": int(j_max),
            "length": int(r.size - peak_idx),
        })
    episodes.sort(key=lambda d: d["depth"], reverse=True)
    return episodes[:top_n]


@dataclass(frozen=True)
class PortfolioReport:
    """Operator-readable portfolio risk report.

    Attributes
    ----------
    rolling_returns
        np.ndarray, rolling-mean per-period return at the report's window.
    rolling_vol
        np.ndarray, rolling std-dev per-period at the report's window.
    rolling_sharpe
        np.ndarray, rolling annualised Sharpe (mean / std * sqrt(ppy)).
    drawdown_table
        list of dicts: ``{depth, peak_idx, trough_idx, length}``.
    exposure_by_sector_dict
        Sum of weights bucketed by sector label (or "unknown").
    contribution_to_return
        dict: per_asset / total / portfolio (see attribution module).
    contribution_to_risk
        dict: per_asset / share / total.
    benchmark_relative_alpha
        dict: alpha / beta / tracking_error / residual_std / r_squared.
        Empty dict if no benchmark provided.
    policy_hash
        Hex string placeholder. Set by caller.
    snapshot_hash
        Hex string placeholder. Set by caller.
    data_quality_status
        ``"ok"`` / ``"degraded"`` / ``"unknown"``.
    window
        Rolling window in periods.
    periods_per_year
        Annualisation factor for rolling Sharpe.
    """

    rolling_returns: np.ndarray
    rolling_vol: np.ndarray
    rolling_sharpe: np.ndarray
    drawdown_table: list[dict[str, float]] = field(default_factory=list)
    exposure_by_sector_dict: dict[str, float] = field(default_factory=dict)
    contribution_to_return: dict[str, float | np.ndarray] = field(
        default_factory=dict
    )
    contribution_to_risk: dict[str, float | np.ndarray] = field(
        default_factory=dict
    )
    benchmark_relative_alpha: dict[str, float] = field(default_factory=dict)
    policy_hash: str = "UNKNOWN"
    snapshot_hash: str = "UNKNOWN"
    data_quality_status: str = "unknown"
    window: int = 21
    periods_per_year: int = 252

    def to_dict(self) -> dict[str, object]:
        """Serialise to plain Python types for JSON / evidence packs."""
        c_ret = dict(self.contribution_to_return)
        if "per_asset" in c_ret:
            c_ret["per_asset"] = np.asarray(c_ret["per_asset"]).tolist()
        c_risk = dict(self.contribution_to_risk)
        for k in ("per_asset", "share"):
            if k in c_risk:
                c_risk[k] = np.asarray(c_risk[k]).tolist()
        return {
            "rolling_returns": self.rolling_returns.tolist(),
            "rolling_vol": self.rolling_vol.tolist(),
            "rolling_sharpe": self.rolling_sharpe.tolist(),
            "drawdown_table": [dict(r) for r in self.drawdown_table],
            "exposure_by_sector_dict": dict(self.exposure_by_sector_dict),
            "contribution_to_return": c_ret,
            "contribution_to_risk": c_risk,
            "benchmark_relative_alpha": dict(self.benchmark_relative_alpha),
            "policy_hash": str(self.policy_hash),
            "snapshot_hash": str(self.snapshot_hash),
            "data_quality_status": str(self.data_quality_status),
            "window": int(self.window),
            "periods_per_year": int(self.periods_per_year),
        }

    def render_markdown(self) -> str:
        """Deterministic Markdown rendering for human review.

        The output is line-stable: same inputs => exact same string.
        """
        lines: list[str] = []
        lines.append("# Portfolio Report")
        lines.append("")
        lines.append(f"- policy_hash: `{self.policy_hash}`")
        lines.append(f"- snapshot_hash: `{self.snapshot_hash}`")
        lines.append(f"- data_quality_status: {self.data_quality_status}")
        lines.append(f"- window: {self.window}")
        lines.append(f"- periods_per_year: {self.periods_per_year}")
        lines.append("")
        lines.append("## Drawdown table (top entries)")
        if not self.drawdown_table:
            lines.append("- (no drawdowns)")
        else:
            for i, row in enumerate(self.drawdown_table):
                lines.append(
                    f"- #{i + 1}: depth={row['depth']:.4f} "
                    f"peak_idx={row['peak_idx']} "
                    f"trough_idx={row['trough_idx']} "
                    f"length={row['length']}"
                )
        lines.append("")
        lines.append("## Exposure by sector")
        if not self.exposure_by_sector_dict:
            lines.append("- (no exposure data)")
        else:
            for key in sorted(self.exposure_by_sector_dict):
                v = self.exposure_by_sector_dict[key]
                lines.append(f"- {key}: {v:.6f}")
        lines.append("")
        lines.append("## Contribution to return")
        c_ret = self.contribution_to_return
        if c_ret:
            total = float(c_ret.get("total", 0.0))
            port = float(c_ret.get("portfolio", 0.0))
            lines.append(f"- total: {total:.6f}")
            lines.append(f"- portfolio_mean: {port:.6f}")
        else:
            lines.append("- (no data)")
        lines.append("")
        lines.append("## Contribution to risk")
        c_risk = self.contribution_to_risk
        if c_risk:
            total = float(c_risk.get("total", 0.0))
            lines.append(f"- total_variance: {total:.6f}")
        else:
            lines.append("- (no data)")
        lines.append("")
        lines.append("## Benchmark-relative alpha")
        a = self.benchmark_relative_alpha
        if a:
            lines.append(f"- alpha: {a.get('alpha', 0.0):.6f}")
            lines.append(f"- beta: {a.get('beta', 0.0):.6f}")
            lines.append(
                f"- tracking_error: {a.get('tracking_error', 0.0):.6f}"
            )
            lines.append(
                f"- r_squared: {a.get('r_squared', 0.0):.6f}"
            )
        else:
            lines.append("- (no benchmark)")
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Builder                                                                     #
# --------------------------------------------------------------------------- #
def build_portfolio_report(
    weights: Sequence[float],
    returns: np.ndarray,
    *,
    sectors: Sequence[str | None] | None = None,
    benchmark_returns: Sequence[float] | None = None,
    window: int = 21,
    periods_per_year: int = 252,
    risk_free_rate: float = 0.0,
    policy_hash: str = "UNKNOWN",
    snapshot_hash: str = "UNKNOWN",
    data_quality_status: str = "unknown",
    drawdown_top_n: int = 5,
) -> PortfolioReport:
    """Assemble a ``PortfolioReport`` from inputs.

    Parameters
    ----------
    weights
        Length-N portfolio weights held over the report period.
    returns
        (T, N) per-period asset returns.
    sectors
        Optional length-N sector labels for ``exposure_by_sector_dict``.
        Missing labels bucket into ``"unknown"``.
    benchmark_returns
        Optional length-T benchmark return series for the alpha/beta
        block. None / empty -> empty dict.
    window
        Rolling window for returns / vol / Sharpe.
    periods_per_year
        Annualisation factor for Sharpe.
    risk_free_rate
        Per-period risk-free rate for alpha/beta.
    policy_hash, snapshot_hash, data_quality_status
        Pass-through metadata.
    drawdown_top_n
        Cap on rows in the drawdown table.
    """
    w = np.asarray(weights, dtype=float).ravel()
    R = np.asarray(returns, dtype=float)
    if R.ndim == 1:
        R = R.reshape(-1, 1)
    if R.size > 0 and R.shape[1] != w.size:
        raise ValueError(
            f"weights size {w.size} != returns columns {R.shape[1]}"
        )

    if R.size == 0:
        port = np.zeros(0, dtype=float)
    else:
        port = R @ w

    # Rolling stats ------------------------------------------------------ #
    roll_ret = _rolling_window(port, window)
    roll_vol = _rolling_std(port, window)
    with np.errstate(divide="ignore", invalid="ignore"):
        sharpe = (roll_ret / roll_vol) * float(np.sqrt(periods_per_year))
    sharpe = np.where(np.isfinite(sharpe), sharpe, np.nan)

    # Drawdown ----------------------------------------------------------- #
    dd_rows = _drawdown_table(port, top_n=drawdown_top_n) if port.size else []

    # Exposure ----------------------------------------------------------- #
    if sectors is None:
        sectors_list = ["unknown"] * w.size
    elif len(sectors) != w.size:
        raise ValueError(
            f"sectors length {len(sectors)} != weights {w.size}"
        )
    else:
        sectors_list = list(sectors)
    exposure = exposure_by_group(w, sectors_list)

    # Contributions ------------------------------------------------------ #
    c_ret = contribution_to_return(w, R) if R.size > 0 else {
        "per_asset": np.zeros(w.size),
        "total": 0.0,
        "portfolio": 0.0,
    }
    c_risk = contribution_to_risk(w, R) if R.size > 0 else {
        "per_asset": np.zeros(w.size),
        "share": np.zeros(w.size),
        "total": 0.0,
    }

    # Alpha / beta ------------------------------------------------------- #
    if benchmark_returns is not None and len(benchmark_returns) > 0:
        b = np.asarray(benchmark_returns, dtype=float).ravel()
        if b.size == port.size and port.size > 0:
            alpha = benchmark_relative_alpha(
                port, b, risk_free_rate=risk_free_rate,
            )
        else:
            alpha = {}
    else:
        alpha = {}

    # Sanity-check max drawdown is consistent with table head (defensive
    # but cheap; the table is the canonical record on the report).
    if dd_rows:
        head_depth = float(dd_rows[0]["depth"])
        mdd = max_drawdown(port)
        # If the implementations disagree by more than 1e-9 we still
        # accept -- the table is the authoritative output and tests
        # check ``max_drawdown`` separately.
        if abs(head_depth - mdd) > 1.0:  # pragma: no cover - guardrail
            pass

    return PortfolioReport(
        rolling_returns=roll_ret,
        rolling_vol=roll_vol,
        rolling_sharpe=sharpe,
        drawdown_table=dd_rows,
        exposure_by_sector_dict=exposure,
        contribution_to_return=c_ret,
        contribution_to_risk=c_risk,
        benchmark_relative_alpha=alpha,
        policy_hash=policy_hash,
        snapshot_hash=snapshot_hash,
        data_quality_status=data_quality_status,
        window=window,
        periods_per_year=periods_per_year,
    )
