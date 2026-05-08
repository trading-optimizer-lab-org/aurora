"""Daily operational report (P2.B).

Operators get a single morning artifact per deployed strategy that explains
what happened yesterday, what's the state today, why we are or are not
trading, and any alerts. Replaces ad-hoc dashboard checking.

Public API
----------
- :class:`DailyOpsConfig`      — knobs (asof_date, strategies, output_dir, ...)
- :class:`DailyOpsAlert`       — frozen alert record
- :class:`DailyOpsSection`     — one report section (markdown + json)
- :class:`DailyOpsReport`      — assembled report with ``to_markdown`` / ``to_json``
- :class:`DailyOpsBuilder`     — assembles the report from inputs

Usage::

    from quantforge.core.protocol_policy import get_active_policy
    from quantforge.reporting.daily_ops import DailyOpsBuilder, DailyOpsConfig
    import pandas as pd

    cfg = DailyOpsConfig(
        asof_date=pd.Timestamp("2026-05-07"),
        strategies=["S1"],
        portfolio_id="P",
        output_format=["md", "json"],
        output_dir=Path("reports/daily"),
    )
    report = DailyOpsBuilder(cfg, get_active_policy()).build()
    print(report.to_markdown())
"""
from __future__ import annotations

from quantforge.reporting.daily_ops.builder import (
    DailyOpsAlert,
    DailyOpsBuilder,
    DailyOpsConfig,
    DailyOpsReport,
    DailyOpsSection,
)

__all__ = [
    "DailyOpsAlert",
    "DailyOpsBuilder",
    "DailyOpsConfig",
    "DailyOpsReport",
    "DailyOpsSection",
]
