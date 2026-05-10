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
  :class:`aurora.core.protocol_policy.ProtocolPolicy`.
* Markdown and JSON outputs round-trip the same payload — regenerating
  ``to_markdown`` from the JSON content gives the same string.
* Inputs (returns, positions, prices, regime, drift, etc.) are passed
  in via the ``inputs`` dict on :class:`DailyOpsBuilder`. This module
  does NOT pull data from the network and does NOT touch the
  filesystem unless the caller asks for write_to_disk.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from aurora.core.protocol_policy import ProtocolPolicy
from aurora.reporting.daily_ops._alerts import _AlertChecksMixin
from aurora.reporting.daily_ops._helpers import SEVERITY_LEVELS
from aurora.reporting.daily_ops._models import (
    DailyOpsAlert,
    DailyOpsConfig,
    DailyOpsReport,
    DailyOpsSection,
)
from aurora.reporting.daily_ops._sections_meta import _MetaPanelsMixin
from aurora.reporting.daily_ops._sections_perf import _PerfPanelsMixin


__all__ = [
    "DailyOpsConfig",
    "DailyOpsAlert",
    "DailyOpsSection",
    "DailyOpsReport",
    "DailyOpsBuilder",
    "SEVERITY_LEVELS",
]


class DailyOpsBuilder(_PerfPanelsMixin, _MetaPanelsMixin, _AlertChecksMixin):
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
