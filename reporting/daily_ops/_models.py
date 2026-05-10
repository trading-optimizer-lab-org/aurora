"""Dataclasses for the daily ops report.

Public surface is re-exported from ``aurora.reporting.daily_ops.builder``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from string import Template
from typing import Any, Dict, List, Optional

import pandas as pd

from aurora.reporting.daily_ops._helpers import SEVERITY_LEVELS


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
        payload: Dict[str, Any] = {
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
