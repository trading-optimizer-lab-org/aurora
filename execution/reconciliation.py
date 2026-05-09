"""Compare replayed broker state against engine and broker snapshots.

Phase 3 -- Candidate A. ``reconcile`` does field-by-field comparison and
emits one :class:`ReconciliationDiff` per mismatch. The diff carries
both the engine value and the broker value (when available) so the
mismatch report cannot collapse to a generic "failed".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from quantforge.execution.replay import ReplayResult


@dataclass(frozen=True)
class ReconciliationDiff:
    """One field-level mismatch between replay and engine / broker."""

    field_name: str
    replayed_value: Any
    engine_value: Any
    broker_value: Any
    severity: str  # "critical", "high", "medium", "low"


@dataclass
class ReconciliationReport:
    """Bag of diffs grouped by category."""

    diffs: List[ReconciliationDiff] = field(default_factory=list)

    @property
    def has_critical(self) -> bool:
        return any(d.severity == "critical" for d in self.diffs)

    @property
    def is_clean(self) -> bool:
        return not self.diffs


def _approx_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(float(a) - float(b)) <= tol


def _compare_dict(
    field_name: str,
    replayed: Dict[str, float],
    engine: Dict[str, float],
    broker: Dict[str, float] | None,
    severity: str,
    diffs: List[ReconciliationDiff],
) -> None:
    """Emit a diff per key whose values disagree between replay and engine."""
    keys = set(replayed) | set(engine or {})
    if broker:
        keys |= set(broker)
    for key in sorted(keys):
        rv = replayed.get(key, 0.0)
        ev = (engine or {}).get(key, 0.0)
        bv = (broker or {}).get(key) if broker is not None else None
        engine_match = _approx_equal(rv, ev)
        broker_match = bv is None or _approx_equal(rv, bv)
        if engine_match and broker_match:
            continue
        diffs.append(
            ReconciliationDiff(
                field_name=f"{field_name}[{key}]",
                replayed_value=rv,
                engine_value=ev,
                broker_value=bv,
                severity=severity,
            )
        )


def reconcile(
    replayed: ReplayResult,
    engine_state: Dict[str, Any],
    broker_state: Dict[str, Any] | None,
) -> ReconciliationReport:
    """Compare replay output against engine and (optional) broker snapshots.

    ``engine_state`` and ``broker_state`` are loose dicts with the same
    keys produced by :class:`ReplayResult` (``positions``, ``cash``,
    ``realised_pnl``, ``commissions``, ``open_orders``). Missing keys
    are treated as zero / empty to keep the diff surface small.
    """
    diffs: List[ReconciliationDiff] = []

    _compare_dict(
        "positions",
        replayed.positions,
        engine_state.get("positions", {}),
        (broker_state or {}).get("positions"),
        "critical",
        diffs,
    )
    _compare_dict(
        "realised_pnl",
        replayed.realised_pnl,
        engine_state.get("realised_pnl", {}),
        (broker_state or {}).get("realised_pnl"),
        "high",
        diffs,
    )

    # Cash: scalar comparison.
    engine_cash = float(engine_state.get("cash", 0.0))
    broker_cash = (
        float(broker_state["cash"]) if broker_state and "cash" in broker_state else None
    )
    cash_engine_match = _approx_equal(replayed.cash, engine_cash)
    cash_broker_match = broker_cash is None or _approx_equal(replayed.cash, broker_cash)
    if not (cash_engine_match and cash_broker_match):
        diffs.append(
            ReconciliationDiff(
                field_name="cash",
                replayed_value=replayed.cash,
                engine_value=engine_cash,
                broker_value=broker_cash,
                severity="critical",
            )
        )

    # Commissions: scalar.
    engine_comm = float(engine_state.get("commissions", 0.0))
    broker_comm = (
        float(broker_state["commissions"])
        if broker_state and "commissions" in broker_state
        else None
    )
    comm_engine_match = _approx_equal(replayed.commissions, engine_comm)
    comm_broker_match = broker_comm is None or _approx_equal(
        replayed.commissions, broker_comm
    )
    if not (comm_engine_match and comm_broker_match):
        diffs.append(
            ReconciliationDiff(
                field_name="commissions",
                replayed_value=replayed.commissions,
                engine_value=engine_comm,
                broker_value=broker_comm,
                severity="medium",
            )
        )

    # Open orders: set comparison.
    engine_open = sorted(engine_state.get("open_orders", []))
    broker_open = (
        sorted(broker_state["open_orders"])
        if broker_state and "open_orders" in broker_state
        else None
    )
    if engine_open != sorted(replayed.open_orders):
        diffs.append(
            ReconciliationDiff(
                field_name="open_orders",
                replayed_value=sorted(replayed.open_orders),
                engine_value=engine_open,
                broker_value=broker_open,
                severity="high",
            )
        )
    elif broker_open is not None and broker_open != sorted(replayed.open_orders):
        diffs.append(
            ReconciliationDiff(
                field_name="open_orders",
                replayed_value=sorted(replayed.open_orders),
                engine_value=engine_open,
                broker_value=broker_open,
                severity="high",
            )
        )

    # Orphan events surface as high-severity diffs.
    for orphan in replayed.orphan_events:
        diffs.append(
            ReconciliationDiff(
                field_name=f"orphan_event[{orphan.event_type}]",
                replayed_value=orphan.order_id,
                engine_value=None,
                broker_value=None,
                severity="high",
            )
        )

    # Duplicate fills are medium severity (they were de-duplicated, but
    # the operator should know).
    for dup in replayed.duplicate_events:
        diffs.append(
            ReconciliationDiff(
                field_name=f"duplicate_event[{dup.event_type}]",
                replayed_value=dup.order_id,
                engine_value=None,
                broker_value=None,
                severity="medium",
            )
        )

    # Out-of-order events: low severity (replay still applies them).
    for ooo in replayed.out_of_order_events:
        diffs.append(
            ReconciliationDiff(
                field_name=f"out_of_order_event[{ooo.event_type}]",
                replayed_value=ooo.timestamp_iso,
                engine_value=None,
                broker_value=None,
                severity="low",
            )
        )

    return ReconciliationReport(diffs=diffs)


__all__ = ["ReconciliationDiff", "ReconciliationReport", "reconcile"]
