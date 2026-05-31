"""Research-pressure validation report integration (Phase 2 / Candidate B).

Bridges the research ledger's pressure score into the validation
pipeline's plain-text report. Operators reading a promotion report
should be able to see at a glance whether a candidate strategy was
the survivor of an aggressive search or a low-pressure run.

Thresholds are exposed as a module-level mapping so other modules can
reference them without hard-coding numeric constants.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aurora.research.pressure import ResearchPressureScore


# Public threshold table. Mirrors the cut-points in
# :mod:`aurora.research.pressure`. Keys are the labels emitted by
# ``ResearchPressureScore.risk_label()``; values are the *upper bound*
# of the corresponding bucket. Any pressure ratio strictly above
# ``high`` is reported as "extreme".
RESEARCH_PRESSURE_THRESHOLDS = {
    "low": 0.01,
    "medium": 0.05,
    "high": 0.20,
}


def format_pressure_warning(score: "ResearchPressureScore") -> str:
    """Format a research-pressure score as operator-readable text.

    Used by the validation pipeline report. The output mentions the
    risk label, the underlying counts and a short interpretation so
    the reader does not need to recompute the ratio mentally.
    """
    label = score.risk_label()
    ratio = score.pressure_ratio

    interpretations = {
        "low": (
            "Low research pressure. The number of variants and "
            "parameters tried is small relative to the data window."
        ),
        "medium": (
            "Moderate research pressure. Some search has happened; "
            "deflated metrics and CSCV/PBO checks are recommended."
        ),
        "high": (
            "HIGH research pressure. Many variants/parameters were "
            "tried for the available data. Treat single-pick metrics "
            "with strong skepticism."
        ),
        "extreme": (
            "EXTREME research pressure. The search budget exceeds "
            "what this data window can honestly support. Promotion "
            "should be blocked unless an explicit override is logged."
        ),
    }

    ratio_str = f"{ratio:.4f}" if ratio != float("inf") else "inf (no data)"
    body = interpretations[label]
    return (
        f"Research pressure: {label.upper()} "
        f"(ratio={ratio_str}, "
        f"variants={score.n_variants}, "
        f"parameters={score.n_parameters}, "
        f"data_length_bars={score.data_length_bars}, "
        f"manual_interventions={score.n_manual_interventions}, "
        f"oos_touches={score.n_oos_touches}). "
        f"{body}"
    )


__all__ = [
    "RESEARCH_PRESSURE_THRESHOLDS",
    "format_pressure_warning",
]
