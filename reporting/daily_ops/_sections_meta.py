"""Regime / attribution / no-trade-reasoning / alerts panel section builders.

Module-private mixin used by :class:`DailyOpsBuilder`. Public API stays
at ``aurora.reporting.daily_ops.builder``.
"""
from __future__ import annotations

from typing import Any, Dict, List, TYPE_CHECKING

import pandas as pd

from aurora.reporting.daily_ops._helpers import SEVERITY_LEVELS
from aurora.reporting.daily_ops._models import DailyOpsAlert, DailyOpsSection

if TYPE_CHECKING:
    from aurora.core.protocol_policy import ProtocolPolicy
    from aurora.reporting.daily_ops._models import DailyOpsConfig


class _MetaPanelsMixin:
    """Section builders for regime, attribution, no-trade reasoning, alerts."""

    # Attribute declarations so mypy knows mixins access concrete state
    # populated by :class:`DailyOpsBuilder.__init__`.
    config: "DailyOpsConfig"
    policy: "ProtocolPolicy"
    inputs: Dict[str, Any]

    def _section_regime(self) -> DailyOpsSection:
        regime = self.inputs.get("regime") or {}
        payload: Dict[str, Any] = {
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
        df = self.inputs.get("factor_attribution")
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
                    "  - (no reason recorded; check upstream)"
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
