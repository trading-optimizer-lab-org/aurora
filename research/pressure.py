"""Research pressure scoring (Phase 2 / Candidate B).

Quantifies the ratio of research choices to data length. The intuition:
the more variants and parameters a researcher tries against a fixed
data window, the higher the chance the surviving strategy is overfit.

This module is intentionally narrow. It does not compute Deflated
Sharpe, PBO or purged-CV; those live next to the validation gates
that already implement them. ``ResearchPressureScore`` is a single
summary score consumed by the validation report and operator
dashboards.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aurora.research.ledger import ResearchLedger


# Thresholds applied to ``pressure_ratio`` (variants*params / data_length).
# Mirrored in :mod:`aurora.validation.research_pressure` so the
# validation report and the score itself agree on labels.
_LOW_MAX = 0.01
_MEDIUM_MAX = 0.05
_HIGH_MAX = 0.20


@dataclass(frozen=True)
class ResearchPressureScore:
    """Snapshot of how hard the research process pushed against the data."""

    n_variants: int
    n_parameters: int
    data_length_bars: int
    n_manual_interventions: int
    n_oos_touches: int

    @property
    def pressure_ratio(self) -> float:
        """Variants times parameters per bar of data.

        Returns ``inf`` when ``data_length_bars`` is zero -- a research
        run with no data is unconditionally extreme pressure.
        """
        if self.data_length_bars <= 0:
            return float("inf")
        return (self.n_variants * self.n_parameters) / self.data_length_bars

    def risk_label(self) -> str:
        """Map the pressure ratio onto a four-bucket risk label."""
        ratio = self.pressure_ratio
        if ratio <= _LOW_MAX:
            return "low"
        if ratio <= _MEDIUM_MAX:
            return "medium"
        if ratio <= _HIGH_MAX:
            return "high"
        return "extreme"


def compute_pressure(
    ledger: "ResearchLedger",
    run_id: str,
    data_length_bars: int,
) -> ResearchPressureScore:
    """Aggregate ledger entries for ``run_id`` into a pressure score.

    Counting rules:

    * ``n_variants`` -- distinct ``strategy_hash`` entries for the run.
      A run with no recorded strategy hash is treated as one variant.
    * ``n_parameters`` -- total number of ``parameters`` choices.
    * ``n_manual_interventions`` -- count of ``manual_override`` rows.
    * ``n_oos_touches`` -- count of ``validation_window`` rows whose
      payload mentions an OOS-style window. Heuristic: the payload
      contains a key starting with "oos" or a value matching that
      pattern.
    """
    rows = ledger.read(run_id=run_id)

    variants: set[str] = set()
    for row in rows:
        if row.kind == "strategy_hash":
            h = row.payload.get("hash") or row.payload.get("strategy_hash")
            if h:
                variants.add(str(h))

    n_variants = len(variants) if variants else 1
    n_parameters = sum(1 for row in rows if row.kind == "parameters")
    n_manual = sum(1 for row in rows if row.kind == "manual_override")
    n_oos = sum(
        1
        for row in rows
        if row.kind == "validation_window"
        and _payload_mentions_oos(row.payload)
    )

    return ResearchPressureScore(
        n_variants=n_variants,
        n_parameters=n_parameters,
        data_length_bars=int(data_length_bars),
        n_manual_interventions=n_manual,
        n_oos_touches=n_oos,
    )


def _payload_mentions_oos(payload: dict) -> bool:
    """True if a validation_window payload references an OOS-style tier."""
    for key, value in payload.items():
        if isinstance(key, str) and key.lower().startswith("oos"):
            return True
        if isinstance(value, str) and "oos" in value.lower():
            return True
    return False


__all__ = [
    "ResearchPressureScore",
    "compute_pressure",
]
