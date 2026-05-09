"""Performance / drawdown / exposure / signals panel section builders.

Module-private mixin used by :class:`DailyOpsBuilder`. Public API stays
at ``aurora.reporting.daily_ops.builder``.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING

import numpy as np
import pandas as pd

from aurora.reporting.daily_ops._helpers import (
    _annualized_sharpe,
    _current_drawdown,
    _days_in_drawdown,
    _max_drawdown,
    _series_returns_through,
    _win_rate,
)
from aurora.reporting.daily_ops._models import DailyOpsSection

if TYPE_CHECKING:
    from aurora.core.protocol_policy import ProtocolPolicy
    from aurora.reporting.daily_ops._models import DailyOpsConfig


class _PerfPanelsMixin:
    """Section builders for performance, drawdown, exposure, signals."""

    # Attribute declarations so mypy knows mixins access concrete state
    # populated by :class:`DailyOpsBuilder.__init__`.
    config: "DailyOpsConfig"
    policy: "ProtocolPolicy"
    inputs: Dict[str, Any]

    def _section_performance(self) -> DailyOpsSection:
        returns: Optional[pd.Series] = self.inputs.get("returns")
        benchmark: Optional[pd.Series] = self.inputs.get("benchmark_returns")
        trades: Optional[pd.Series] = self.inputs.get("trades")
        asof = self.config.asof_date

        # default skeleton
        payload: Dict[str, Any] = {
            "daily_pnl_pct": None,
            "daily_pnl_bps": None,
            "weekly_pnl_pct": None,
            "mtd_pnl_pct": None,
            "ytd_pnl_pct": None,
            "itd_pnl_pct": None,
            "vs_benchmark_bps": None,
            "sharpe_60d": None,
            "sharpe_itd": None,
            "win_rate_last_20": None,
            "n_observations": 0,
        }

        if returns is not None and len(returns) > 0:
            r_full = _series_returns_through(returns, asof)
            if len(r_full) > 0:
                last = float(r_full.iloc[-1])
                payload["daily_pnl_pct"] = last
                payload["daily_pnl_bps"] = last * 10000.0
                weekly = r_full.iloc[-5:]
                if len(weekly) > 0:
                    payload["weekly_pnl_pct"] = float(
                        (1.0 + weekly).prod() - 1.0
                    )
                # MTD
                month_start = pd.Timestamp(year=asof.year, month=asof.month, day=1)
                mtd = r_full[r_full.index >= month_start]
                if len(mtd) > 0:
                    payload["mtd_pnl_pct"] = float((1.0 + mtd).prod() - 1.0)
                # YTD
                year_start = pd.Timestamp(year=asof.year, month=1, day=1)
                ytd = r_full[r_full.index >= year_start]
                if len(ytd) > 0:
                    payload["ytd_pnl_pct"] = float((1.0 + ytd).prod() - 1.0)
                # ITD (whole series)
                payload["itd_pnl_pct"] = float((1.0 + r_full).prod() - 1.0)
                # Sharpe 60d / ITD
                payload["sharpe_60d"] = _annualized_sharpe(r_full.iloc[-60:])
                payload["sharpe_itd"] = _annualized_sharpe(r_full)
                payload["n_observations"] = int(len(r_full))

                # vs benchmark
                if benchmark is not None and len(benchmark) > 0:
                    b = _series_returns_through(benchmark, asof)
                    if len(b) > 0:
                        b_last = float(b.iloc[-1])
                        payload["vs_benchmark_bps"] = (last - b_last) * 10000.0

        payload["win_rate_last_20"] = _win_rate(trades, n=20)

        # render markdown
        def _fmt_pct(v: Optional[float]) -> str:
            return "n/a" if v is None else f"{v*100:+.2f}%"

        def _fmt_bps(v: Optional[float]) -> str:
            return "n/a" if v is None else f"{v:+.1f}bps"

        def _fmt_num(v: Optional[float], fmt: str = ".2f") -> str:
            return "n/a" if v is None else format(v, fmt)

        wr = payload["win_rate_last_20"]
        wr_str = "n/a" if wr is None else f"{wr*100:.1f}%"

        md_lines = [
            f"- Daily PnL: {_fmt_pct(payload['daily_pnl_pct'])} "
            f"({_fmt_bps(payload['daily_pnl_bps'])})",
            f"- vs Benchmark ({self.config.benchmark_symbol}): "
            f"{_fmt_bps(payload['vs_benchmark_bps'])}",
            f"- Weekly: {_fmt_pct(payload['weekly_pnl_pct'])}",
            f"- MTD: {_fmt_pct(payload['mtd_pnl_pct'])}",
            f"- YTD: {_fmt_pct(payload['ytd_pnl_pct'])}",
            f"- ITD: {_fmt_pct(payload['itd_pnl_pct'])}",
            f"- Sharpe (60d): {_fmt_num(payload['sharpe_60d'])}",
            f"- Sharpe (ITD): {_fmt_num(payload['sharpe_itd'])}",
            f"- Win rate (last 20): {wr_str}",
            f"- N observations: {payload['n_observations']}",
        ]
        return DailyOpsSection(
            title="Performance",
            content_md="\n".join(md_lines),
            content_json=payload,
        )

    def _section_drawdown(self) -> DailyOpsSection:
        returns: Optional[pd.Series] = self.inputs.get("returns")
        asof = self.config.asof_date
        payload: Dict[str, Any] = {
            "current_drawdown": 0.0,
            "max_dd_30d": 0.0,
            "max_dd_itd": 0.0,
            "days_in_drawdown": 0,
            "distance_to_peak_pct": 0.0,
        }
        if returns is not None and len(returns) > 0:
            r_full = _series_returns_through(returns, asof)
            if len(r_full) > 0:
                payload["current_drawdown"] = _current_drawdown(r_full)
                payload["max_dd_30d"] = _max_drawdown(r_full.iloc[-30:])
                payload["max_dd_itd"] = _max_drawdown(r_full)
                payload["days_in_drawdown"] = _days_in_drawdown(r_full)
                payload["distance_to_peak_pct"] = abs(
                    payload["current_drawdown"]
                )
        md_lines = [
            f"- Current drawdown: {payload['current_drawdown']*100:.2f}%",
            f"- Max DD (30d): {payload['max_dd_30d']*100:.2f}%",
            f"- Max DD (ITD): {payload['max_dd_itd']*100:.2f}%",
            f"- Days in drawdown: {payload['days_in_drawdown']}",
            f"- Distance to last peak: "
            f"{payload['distance_to_peak_pct']*100:.2f}%",
        ]
        return DailyOpsSection(
            title="Drawdown",
            content_md="\n".join(md_lines),
            content_json=payload,
        )

    def _section_exposure(self) -> DailyOpsSection:
        positions: Optional[pd.DataFrame] = self.inputs.get("positions")
        payload: Dict[str, Any] = {
            "gross_exposure": 0.0,
            "net_exposure": 0.0,
            "long_concentration": 0.0,
            "short_concentration": 0.0,
            "top_5": [],
            "sectors": {},
        }
        if positions is not None and len(positions) > 0 and "weight" in positions.columns:
            w = positions["weight"].astype(float).fillna(0.0)
            payload["gross_exposure"] = float(np.abs(w).sum())
            payload["net_exposure"] = float(w.sum())
            longs = w[w > 0]
            shorts = w[w < 0]
            payload["long_concentration"] = float(longs.sum()) if len(longs) else 0.0
            payload["short_concentration"] = float(shorts.sum()) if len(shorts) else 0.0
            top = w.abs().sort_values(ascending=False).head(5)
            payload["top_5"] = [
                {"symbol": str(idx), "weight": float(w.loc[idx])}
                for idx in top.index
            ]
            if "sector" in positions.columns:
                sec = positions.groupby("sector")["weight"].sum()
                payload["sectors"] = {str(k): float(v) for k, v in sec.items()}
        md_lines = [
            f"- Gross exposure: {payload['gross_exposure']*100:.1f}%",
            f"- Net exposure: {payload['net_exposure']*100:+.1f}%",
            f"- Long concentration: {payload['long_concentration']*100:.1f}%",
            f"- Short concentration: {payload['short_concentration']*100:.1f}%",
        ]
        if payload["top_5"]:
            md_lines.append("- Top 5 positions:")
            for row in payload["top_5"]:
                md_lines.append(
                    f"  - {row['symbol']}: {row['weight']*100:+.2f}%"
                )
        if payload["sectors"]:
            md_lines.append("- Sector breakdown:")
            for k, v in payload["sectors"].items():
                md_lines.append(f"  - {k}: {v*100:+.2f}%")
        return DailyOpsSection(
            title="Exposure",
            content_md="\n".join(md_lines),
            content_json=payload,
        )

    def _section_signals(self) -> DailyOpsSection:
        signals: Optional[Dict[str, Any]] = self.inputs.get("signals")
        rows: List[Dict[str, Any]] = []
        for sid in self.config.strategies:
            entry = (signals or {}).get(sid) or {}
            row = {
                "strategy_id": sid,
                "state": str(entry.get("state", "unknown")),
                "last_change": (
                    pd.Timestamp(entry["last_change"]).date().isoformat()
                    if entry.get("last_change") is not None else None
                ),
                "pending": list(entry.get("pending") or []),
            }
            rows.append(row)
        md_lines = []
        for r in rows:
            pend = ", ".join(r["pending"]) if r["pending"] else "(none)"
            md_lines.append(
                f"- **{r['strategy_id']}**: state={r['state']}, "
                f"last_change={r['last_change'] or 'n/a'}, "
                f"pending=[{pend}]"
            )
        if not md_lines:
            md_lines = ["(no strategies configured)"]
        return DailyOpsSection(
            title="Signals",
            content_md="\n".join(md_lines),
            content_json={"strategies": rows},
        )
