"""DailyOpsBuilder -- assemble the daily operational report.

Public surface
--------------
- :class:`DailyOpsConfig`
- :class:`DailyOpsAlert`
- :class:`DailyOpsSection`
- :class:`DailyOpsReport`
- :class:`DailyOpsBuilder`

Design contract
---------------
* All sections optional via :class:`DailyOpsConfig` flags so the report
  degrades gracefully when an upstream module is unavailable or returns
  empty data.
* Reports are deterministic given (config, inputs). No wall-clock
  side effects beyond ``asof_date`` (which the caller picks).
* :attr:`DailyOpsReport.policy_hash` binds the report to the active
  :class:`quantforge.core.protocol_policy.ProtocolPolicy`.
* Markdown and JSON outputs round-trip the same payload — regenerating
  ``to_markdown`` from the JSON content gives the same string.
* Inputs (returns, positions, prices, regime, drift, etc.) are passed
  in via the ``inputs`` dict on :class:`DailyOpsBuilder`. This module
  does NOT pull data from the network and does NOT touch the
  filesystem unless the caller asks for write_to_disk.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from string import Template
from typing import Any, Dict, List, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from aurora.core.protocol_policy import ProtocolPolicy


__all__ = [
    "DailyOpsConfig",
    "DailyOpsAlert",
    "DailyOpsSection",
    "DailyOpsReport",
    "DailyOpsBuilder",
]


# --------------------------------------------------------------------------- #
# Dataclasses                                                                 #
# --------------------------------------------------------------------------- #
SEVERITY_LEVELS = ("info", "warn", "critical")


@dataclass
class DailyOpsConfig:
    """Knobs for the daily ops report.

    Attributes:
        asof_date: Trading date the report describes (``"as of"`` date).
        strategies: Strategy ids to include in the report.
        portfolio_id: Optional human label for the deployed portfolio.
        output_format: Output formats to render. Subset of ``("md", "json")``.
        output_dir: Directory for written artifacts. The builder does
            NOT create the directory; callers may pass any Path.
        include_regime: When False, the regime section is skipped.
        include_attribution: When False, the attribution section is skipped.
        include_alerts: When False, all alert checks are skipped.
        include_no_trade_reasoning: When False, no-trade reasoning is skipped.
        benchmark_symbol: Symbol used for benchmark comparison (default SPY).
    """

    asof_date: pd.Timestamp
    strategies: List[str]
    portfolio_id: Optional[str] = None
    output_format: List[str] = field(default_factory=lambda: ["md", "json"])
    output_dir: Optional[Path] = None
    include_regime: bool = True
    include_attribution: bool = True
    include_alerts: bool = True
    include_no_trade_reasoning: bool = True
    benchmark_symbol: str = "SPY"

    def __post_init__(self) -> None:
        # Normalize asof_date to a Timestamp.
        if not isinstance(self.asof_date, pd.Timestamp):
            self.asof_date = pd.Timestamp(self.asof_date)
        if self.output_dir is not None and not isinstance(self.output_dir, Path):
            self.output_dir = Path(self.output_dir)
        if not self.strategies:
            raise ValueError("DailyOpsConfig.strategies must be non-empty")
        for fmt in self.output_format:
            if fmt not in ("md", "json"):
                raise ValueError(
                    f"DailyOpsConfig.output_format entries must be 'md' or "
                    f"'json'; got {fmt!r}"
                )

    @classmethod
    def from_yaml(cls, path: str | Path,
                  asof_date: pd.Timestamp,
                  strategies: List[str],
                  portfolio_id: Optional[str] = None) -> "DailyOpsConfig":
        """Build a config by overlaying YAML defaults with per-call args."""
        import yaml
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        out_dir = data.get("output_dir")
        return cls(
            asof_date=asof_date,
            strategies=strategies,
            portfolio_id=portfolio_id,
            output_format=list(data.get("output_format") or ["md", "json"]),
            output_dir=Path(out_dir) if out_dir else None,
            include_regime=bool(data.get("include_regime", True)),
            include_attribution=bool(data.get("include_attribution", True)),
            include_alerts=bool(data.get("include_alerts", True)),
            include_no_trade_reasoning=bool(
                data.get("include_no_trade_reasoning", True)
            ),
            benchmark_symbol=str(data.get("benchmark_symbol", "SPY")),
        )


@dataclass(frozen=True)
class DailyOpsAlert:
    """A single immutable alert record.

    Attributes:
        severity: One of ``("info", "warn", "critical")``.
        code: Stable machine-readable code (e.g. ``"DD_BREACH"``).
        title: One-line human-readable headline.
        detail: Multi-line context: thresholds, current values, hints.
        suggested_action: Optional remediation hint for the operator.
    """
    severity: str
    code: str
    title: str
    detail: str
    suggested_action: Optional[str] = None

    def __post_init__(self) -> None:
        if self.severity not in SEVERITY_LEVELS:
            raise ValueError(
                f"DailyOpsAlert.severity must be one of {SEVERITY_LEVELS}, "
                f"got {self.severity!r}"
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "title": self.title,
            "detail": self.detail,
            "suggested_action": self.suggested_action,
        }


@dataclass(frozen=True)
class DailyOpsSection:
    """One section of the daily report.

    ``content_md`` and ``content_json`` MUST describe the same data so
    operators can switch between the two without losing information.
    """
    title: str
    content_md: str
    content_json: Dict[str, Any]


@dataclass(frozen=True)
class DailyOpsReport:
    """Final assembled daily report.

    Attributes:
        asof_date: Trading date this report describes.
        strategies: Strategies included in the report.
        portfolio_id: Optional portfolio label.
        sections: Ordered list of :class:`DailyOpsSection`.
        alerts: Aggregated alerts across all sections (deduped).
        summary_one_line: Short Slack/cron friendly digest.
        policy_hash: ``ProtocolPolicy.policy_hash`` of the active policy.
    """
    asof_date: pd.Timestamp
    strategies: List[str]
    portfolio_id: Optional[str]
    sections: List[DailyOpsSection]
    alerts: List[DailyOpsAlert]
    summary_one_line: str
    policy_hash: str

    def has_critical_alerts(self) -> bool:
        """True iff at least one alert is ``severity == 'critical'``."""
        return any(a.severity == "critical" for a in self.alerts)

    def alert_counts(self) -> Dict[str, int]:
        """Return counts grouped by severity."""
        out = {s: 0 for s in SEVERITY_LEVELS}
        for a in self.alerts:
            out[a.severity] = out.get(a.severity, 0) + 1
        return out

    # ---- rendering ----

    def to_markdown(self) -> str:
        """Render the report as markdown."""
        sections_md = "\n\n".join(
            f"## {s.title}\n\n{s.content_md}".rstrip()
            for s in self.sections
        )
        alerts_md = self._render_alerts_md()
        tpl_path = (Path(__file__).parent / "templates" /
                    "daily_report.md.j2")
        with open(tpl_path, "r", encoding="utf-8") as f:
            tpl = Template(f.read())
        return tpl.safe_substitute(
            asof_date=self.asof_date.date().isoformat(),
            portfolio_id=self.portfolio_id or "(none)",
            strategies=", ".join(self.strategies),
            policy_hash=self.policy_hash[:16] if self.policy_hash else "(unset)",
            summary_one_line=self.summary_one_line,
            sections_md=sections_md,
            alerts_md=alerts_md,
        )

    def to_json(self) -> str:
        """Render the report as JSON."""
        payload = {
            "asof_date": self.asof_date.date().isoformat(),
            "portfolio_id": self.portfolio_id,
            "strategies": list(self.strategies),
            "summary_one_line": self.summary_one_line,
            "policy_hash": self.policy_hash,
            "sections": [
                {
                    "title": s.title,
                    "content_md": s.content_md,
                    "content_json": s.content_json,
                }
                for s in self.sections
            ],
            "alerts": [a.to_dict() for a in self.alerts],
            "alert_counts": self.alert_counts(),
            "has_critical": self.has_critical_alerts(),
        }
        return json.dumps(payload, sort_keys=True, indent=2,
                          ensure_ascii=False, default=str)

    def to_summary_line(self) -> str:
        """Render one-line summary using the summary.txt template."""
        tpl_path = (Path(__file__).parent / "templates" / "summary.txt")
        with open(tpl_path, "r", encoding="utf-8") as f:
            tpl = Template(f.read())
        # extract daily PnL bps and DD pct from sections if available
        daily_pnl_bps = "n/a"
        current_dd_pct = "n/a"
        for s in self.sections:
            if s.title.lower().startswith("performance"):
                v = s.content_json.get("daily_pnl_bps")
                if v is not None:
                    daily_pnl_bps = f"{v:+.1f}"
            if s.title.lower().startswith("drawdown"):
                v = s.content_json.get("current_drawdown")
                if v is not None:
                    current_dd_pct = f"{v * 100:.2f}"
        ac = self.alert_counts()
        alert_summary = (
            f"crit={ac.get('critical', 0)},warn={ac.get('warn', 0)},"
            f"info={ac.get('info', 0)}"
        )
        return tpl.safe_substitute(
            asof_date=self.asof_date.date().isoformat(),
            portfolio_id=self.portfolio_id or "(none)",
            daily_pnl_bps=daily_pnl_bps,
            current_dd_pct=current_dd_pct,
            alert_summary=alert_summary,
        ).strip()

    def _render_alerts_md(self) -> str:
        if not self.alerts:
            return "## Alerts\n\nNo alerts."
        # group by severity, critical first
        order = {"critical": 0, "warn": 1, "info": 2}
        sorted_alerts = sorted(self.alerts, key=lambda a: order.get(a.severity, 99))
        lines = ["## Alerts", ""]
        for a in sorted_alerts:
            tag = a.severity.upper()
            lines.append(f"### [{tag}] {a.code} -- {a.title}")
            lines.append("")
            lines.append(a.detail)
            if a.suggested_action:
                lines.append("")
                lines.append(f"_Suggested action:_ {a.suggested_action}")
            lines.append("")
        return "\n".join(lines).rstrip()


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _safe_get(d: Optional[Mapping[str, Any]], key: str, default: Any = None) -> Any:
    if d is None:
        return default
    return d.get(key, default)


def _series_returns_through(returns: Optional[pd.Series],
                            asof: pd.Timestamp,
                            window_days: Optional[int] = None) -> pd.Series:
    """Slice a returns series up to ``asof`` (inclusive), optionally last N."""
    if returns is None or len(returns) == 0:
        return pd.Series(dtype=float)
    s = returns.copy()
    if not isinstance(s.index, pd.DatetimeIndex):
        s.index = pd.to_datetime(s.index)
    s = s[s.index <= asof]
    if window_days is not None and len(s) > window_days:
        s = s.iloc[-window_days:]
    return s


def _annualized_sharpe(returns: pd.Series, ppy: int = 252) -> float:
    if returns is None or len(returns) < 2:
        return 0.0
    r = returns.dropna().to_numpy(dtype=float)
    if r.size < 2:
        return 0.0
    mu = float(r.mean())
    sd = float(r.std(ddof=1))
    if sd <= 1e-12:
        return 0.0
    return float(mu / sd * np.sqrt(ppy))


def _drawdown_series(returns: pd.Series) -> pd.Series:
    if returns is None or len(returns) == 0:
        return pd.Series(dtype=float)
    eq = (1.0 + returns.fillna(0.0)).cumprod()
    cummax = eq.cummax()
    return (eq - cummax) / cummax


def _max_drawdown(returns: pd.Series) -> float:
    dd = _drawdown_series(returns)
    return float(dd.min()) if len(dd) else 0.0


def _current_drawdown(returns: pd.Series) -> float:
    dd = _drawdown_series(returns)
    return float(dd.iloc[-1]) if len(dd) else 0.0


def _days_in_drawdown(returns: pd.Series) -> int:
    """Return the number of consecutive bars with non-zero drawdown."""
    dd = _drawdown_series(returns)
    if len(dd) == 0:
        return 0
    n = 0
    for v in reversed(dd.tolist()):
        if v < -1e-12:
            n += 1
        else:
            break
    return n


def _win_rate(trades: Optional[pd.Series], n: int = 20) -> Optional[float]:
    if trades is None or len(trades) == 0:
        return None
    last = trades.dropna().iloc[-n:]
    if len(last) == 0:
        return None
    return float((last > 0).mean())


# --------------------------------------------------------------------------- #
# Builder                                                                     #
# --------------------------------------------------------------------------- #


class DailyOpsBuilder:
    """Assemble a :class:`DailyOpsReport` from inputs.

    Inputs schema (via the ``inputs`` dict)
    ---------------------------------------
    All keys are optional; sections degrade when their input is missing.

    - ``returns`` (pd.Series): strategy daily returns indexed by date.
    - ``benchmark_returns`` (pd.Series): same shape as ``returns``.
    - ``trades`` (pd.Series): per-trade PnL in dollars or bps.
    - ``positions`` (pd.DataFrame): index symbol, columns include
      ``weight``, ``side``, ``sector`` (optional).
    - ``signals`` (Dict[strategy_id, dict]): strategy state with keys
      ``state`` (str), ``last_change`` (Timestamp), ``pending`` (list).
    - ``regime`` (dict): keys ``label``, ``probs`` (dict), ``last_transition``,
      ``days_in_regime``.
    - ``factor_attribution`` (pd.DataFrame): rows = factor, cols = ``contrib``,
      optional ``tstat``.
    - ``no_trade_reasons`` (Dict[strategy_id, dict]): see
      :meth:`_section_no_trade_reasoning` for the schema.
    - ``data_freshness`` (dict): ``last_update`` (Timestamp).
    - ``drift`` (dict): keys ``breached`` (bool), ``detector``, ``stat``.
    - ``kill_switch`` (dict): keys ``triggered`` (bool), ``reason``.
    - ``validation_marker`` (dict): keys ``path``, ``mtime`` (Timestamp).
    """

    def __init__(self,
                 config: DailyOpsConfig,
                 policy: ProtocolPolicy,
                 inputs: Optional[Dict[str, Any]] = None):
        self.config = config
        self.policy = policy
        self.inputs: Dict[str, Any] = inputs or {}

    # ----- top-level entry point ----------------------------------------- #

    def build(self) -> DailyOpsReport:
        """Assemble all configured sections + run all alert checks."""
        sections: List[DailyOpsSection] = []
        sections.append(self._section_performance())
        sections.append(self._section_drawdown())
        sections.append(self._section_exposure())
        sections.append(self._section_signals())
        if self.config.include_regime:
            sections.append(self._section_regime())
        if self.config.include_attribution:
            sections.append(self._section_attribution())
        if self.config.include_no_trade_reasoning:
            sections.append(self._section_no_trade_reasoning())

        alerts: List[DailyOpsAlert] = []
        if self.config.include_alerts:
            alerts.extend(self._check_drawdown_breach())
            alerts.extend(self._check_kill_switch_triggered())
            alerts.extend(self._check_data_freshness())
            alerts.extend(self._check_regime_change())
            alerts.extend(self._check_drift())
            alerts.extend(self._check_validation_marker_stale())

        sections.append(self._section_alerts(alerts))

        summary = self._build_summary_line(sections, alerts)

        return DailyOpsReport(
            asof_date=self.config.asof_date,
            strategies=list(self.config.strategies),
            portfolio_id=self.config.portfolio_id,
            sections=sections,
            alerts=alerts,
            summary_one_line=summary,
            policy_hash=self.policy.policy_hash or "",
        )

    # ---------------------------------------------------------------- summary
    def _build_summary_line(self, sections: List[DailyOpsSection],
                            alerts: List[DailyOpsAlert]) -> str:
        # Pull a few headline stats out of the sections.
        perf = next((s for s in sections if s.title.lower().startswith(
            "performance")), None)
        dd = next((s for s in sections if s.title.lower().startswith(
            "drawdown")), None)
        crit = sum(1 for a in alerts if a.severity == "critical")
        warn = sum(1 for a in alerts if a.severity == "warn")
        bits = [self.config.asof_date.date().isoformat()]
        if self.config.portfolio_id:
            bits.append(self.config.portfolio_id)
        if perf is not None:
            v = perf.content_json.get("daily_pnl_bps")
            if v is not None:
                bits.append(f"PnL={v:+.1f}bps")
        if dd is not None:
            v = dd.content_json.get("current_drawdown")
            if v is not None:
                bits.append(f"DD={v*100:.2f}%")
        bits.append(f"alerts: {crit} critical / {warn} warn")
        return " | ".join(bits)

    # ============================================================ #
    # Section builders                                             #
    # ============================================================ #

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

    def _section_regime(self) -> DailyOpsSection:
        regime = self.inputs.get("regime") or {}
        payload = {
            "label": regime.get("label"),
            "probs": dict(regime.get("probs") or {}),
            "days_in_regime": int(regime.get("days_in_regime") or 0),
            "last_transition": (
                pd.Timestamp(regime["last_transition"]).date().isoformat()
                if regime.get("last_transition") is not None else None
            ),
        }
        md_lines = [
            f"- Current regime: {payload['label'] or 'unknown'}",
            f"- Days in regime: {payload['days_in_regime']}",
            f"- Last transition: {payload['last_transition'] or 'n/a'}",
        ]
        if payload["probs"]:
            md_lines.append("- Regime probabilities:")
            for k, v in payload["probs"].items():
                md_lines.append(f"  - {k}: {v*100:.1f}%")
        return DailyOpsSection(
            title="Regime",
            content_md="\n".join(md_lines),
            content_json=payload,
        )

    def _section_attribution(self) -> DailyOpsSection:
        df: Optional[pd.DataFrame] = self.inputs.get("factor_attribution")
        rows: List[Dict[str, Any]] = []
        top_contrib: List[Dict[str, Any]] = []
        top_detract: List[Dict[str, Any]] = []
        if df is not None and len(df) > 0 and "contrib" in df.columns:
            for idx, row in df.iterrows():
                rec = {
                    "factor": str(idx),
                    "contrib": float(row["contrib"]),
                }
                if "tstat" in df.columns:
                    rec["tstat"] = float(row["tstat"])
                rows.append(rec)
            sorted_rows = sorted(rows, key=lambda r: r["contrib"], reverse=True)
            top_contrib = sorted_rows[:3]
            top_detract = sorted(rows, key=lambda r: r["contrib"])[:3]
        payload = {
            "rows": rows,
            "top_contributors": top_contrib,
            "top_detractors": top_detract,
        }
        md_lines: List[str] = []
        if top_contrib:
            md_lines.append("- Top contributors:")
            for r in top_contrib:
                md_lines.append(
                    f"  - {r['factor']}: {r['contrib']*100:+.2f}%"
                )
        if top_detract:
            md_lines.append("- Top detractors:")
            for r in top_detract:
                md_lines.append(
                    f"  - {r['factor']}: {r['contrib']*100:+.2f}%"
                )
        if not md_lines:
            md_lines = ["(no attribution data)"]
        return DailyOpsSection(
            title="Attribution",
            content_md="\n".join(md_lines),
            content_json=payload,
        )

    def _section_no_trade_reasoning(self) -> DailyOpsSection:
        """Explain why each strategy did NOT trade today.

        Input schema (per strategy id)::

            no_trade_reasons[sid] = {
                "traded": bool,         # True iff strategy traded today
                "reasons": [
                    {
                        "code": "vol_gate" | "data_insufficient" |
                                "regime_mismatch" | "cooldown" |
                                "validation_marker_stale" | "kill_switch" |
                                "other",
                        "detail": "...human readable...",
                        "metric": optional float,
                        "threshold": optional float,
                    },
                    ...
                ],
            }

        Strategies with ``traded=True`` are reported as "traded".
        """
        reasons_in: Dict[str, Any] = self.inputs.get("no_trade_reasons") or {}
        rows: List[Dict[str, Any]] = []
        md_lines: List[str] = []
        for sid in self.config.strategies:
            entry = reasons_in.get(sid) or {"traded": False, "reasons": []}
            traded = bool(entry.get("traded", False))
            reasons = list(entry.get("reasons") or [])
            row = {"strategy_id": sid, "traded": traded, "reasons": reasons}
            rows.append(row)
            if traded:
                md_lines.append(f"- **{sid}**: traded today.")
                continue
            md_lines.append(f"- **{sid}**: did NOT trade today.")
            if not reasons:
                md_lines.append(
                    f"  - (no reason recorded; check upstream)"
                )
            for r in reasons:
                code = r.get("code", "other")
                detail = r.get("detail", "")
                metric = r.get("metric")
                thr = r.get("threshold")
                bits = [f"  - [{code}] {detail}"]
                if metric is not None and thr is not None:
                    bits.append(
                        f" (metric={metric}, threshold={thr})"
                    )
                md_lines.append("".join(bits))
        if not md_lines:
            md_lines = ["(no strategies configured)"]
        return DailyOpsSection(
            title="No-Trade Reasoning",
            content_md="\n".join(md_lines),
            content_json={"strategies": rows},
        )

    def _section_alerts(self,
                        alerts: List[DailyOpsAlert]) -> DailyOpsSection:
        rows = [a.to_dict() for a in alerts]
        ac = {s: 0 for s in SEVERITY_LEVELS}
        for a in alerts:
            ac[a.severity] = ac.get(a.severity, 0) + 1
        payload = {"alerts": rows, "counts": ac}
        if not alerts:
            md = "No alerts."
        else:
            order = {"critical": 0, "warn": 1, "info": 2}
            sorted_alerts = sorted(
                alerts, key=lambda a: order.get(a.severity, 99)
            )
            md = "\n".join(
                f"- [{a.severity.upper()}] {a.code}: {a.title}"
                for a in sorted_alerts
            )
        return DailyOpsSection(
            title="Alerts (summary)",
            content_md=md,
            content_json=payload,
        )

    # ============================================================ #
    # Alert checks                                                 #
    # ============================================================ #

    def _check_drawdown_breach(self) -> List[DailyOpsAlert]:
        returns: Optional[pd.Series] = self.inputs.get("returns")
        if returns is None or len(returns) == 0:
            return []
        r_full = _series_returns_through(returns, self.config.asof_date)
        cur_dd = _current_drawdown(r_full)
        threshold = float(
            self.policy.risk_limits.max_drawdown_promotion_threshold
        )
        if abs(cur_dd) >= threshold:
            return [DailyOpsAlert(
                severity="critical",
                code="DD_BREACH",
                title="Drawdown breaches policy threshold",
                detail=(
                    f"Current drawdown {cur_dd*100:.2f}% breaches policy "
                    f"max_drawdown_promotion_threshold "
                    f"{threshold*100:.2f}%."
                ),
                suggested_action=(
                    "Halt new entries; review position sizing; consider "
                    "consulting the lockbox before resuming."
                ),
            )]
        return []

    def _check_kill_switch_triggered(self) -> List[DailyOpsAlert]:
        ks = self.inputs.get("kill_switch") or {}
        if bool(ks.get("triggered")):
            return [DailyOpsAlert(
                severity="critical",
                code="KILL_SWITCH",
                title="Kill switch is ARMED",
                detail=(
                    f"Reason: {ks.get('reason', 'unspecified')}. "
                    f"All order submissions are rejected at the broker."
                ),
                suggested_action=(
                    "Investigate the trigger; only ``disarm`` after "
                    "manual verification."
                ),
            )]
        return []

    def _check_data_freshness(self) -> List[DailyOpsAlert]:
        df_in = self.inputs.get("data_freshness") or {}
        last_update = df_in.get("last_update")
        if last_update is None:
            return []
        last_ts = pd.Timestamp(last_update)
        delta = (self.config.asof_date - last_ts).days
        if delta >= 2:
            return [DailyOpsAlert(
                severity="warn",
                code="DATA_STALE",
                title="Data feed is stale",
                detail=(
                    f"Last update {last_ts.date().isoformat()} is "
                    f"{delta} days behind asof_date "
                    f"{self.config.asof_date.date().isoformat()}."
                ),
                suggested_action=(
                    "Refresh the data feed before relying on signals."
                ),
            )]
        return []

    def _check_regime_change(self) -> List[DailyOpsAlert]:
        regime = self.inputs.get("regime") or {}
        last_trans = regime.get("last_transition")
        label = regime.get("label")
        if last_trans is None:
            return []
        last_ts = pd.Timestamp(last_trans)
        if (self.config.asof_date - last_ts).days <= 1:
            return [DailyOpsAlert(
                severity="info",
                code="REGIME_CHANGE",
                title="Regime transition in last 24h",
                detail=(
                    f"Current regime: {label}. "
                    f"Transition at {last_ts.date().isoformat()}."
                ),
                suggested_action=(
                    "Review regime-conditioned strategy params; some "
                    "models require warm-up after a transition."
                ),
            )]
        return []

    def _check_drift(self) -> List[DailyOpsAlert]:
        drift = self.inputs.get("drift") or {}
        if not bool(drift.get("breached")):
            return []
        det = drift.get("detector", "?")
        stat = drift.get("stat")
        thr = drift.get("threshold")
        bits = [f"Detector {det} fired."]
        if stat is not None and thr is not None:
            bits.append(f"stat={stat}, threshold={thr}.")
        return [DailyOpsAlert(
            severity="warn",
            code="DRIFT_DETECTED",
            title="Concept drift detected",
            detail=" ".join(bits),
            suggested_action=(
                "Run validation on recent data; consider retraining."
            ),
        )]

    def _check_validation_marker_stale(self) -> List[DailyOpsAlert]:
        vm = self.inputs.get("validation_marker") or {}
        if "mtime" not in vm:
            return []
        mtime = pd.Timestamp(vm["mtime"])
        # Threshold derived from policy: pick the OOS_DEV tier window length
        # divided by N (here N=8 -- ~1 year of an 8-year window) so the
        # threshold scales with the protocol horizon. Falls back to 30 days
        # if the tier is malformed.
        threshold_days = self._validation_marker_threshold_days()
        delta = (self.config.asof_date - mtime).days
        if delta >= threshold_days:
            return [DailyOpsAlert(
                severity="critical",
                code="VALIDATION_MARKER_STALE",
                title="Validation marker is stale",
                detail=(
                    f"Marker at {vm.get('path', '<unknown>')} mtime="
                    f"{mtime.date().isoformat()} is {delta} days old; "
                    f"threshold {threshold_days} days. Deployment refuses "
                    f"orders until re-validated."
                ),
                suggested_action=(
                    "Re-run the validation pipeline; refresh the marker."
                ),
            )]
        return []

    def _validation_marker_threshold_days(self) -> int:
        try:
            tier = self.policy.tiers.get("OOS_DEV")
            if tier is None or tier.start is None or tier.end is None:
                return 30
            start = pd.Timestamp(tier.start)
            end = pd.Timestamp(tier.end)
            window_days = max(1, (end - start).days)
            return max(30, window_days // 8)
        except Exception:
            return 30
