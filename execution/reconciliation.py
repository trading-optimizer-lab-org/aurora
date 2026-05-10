"""R169 -- Engine / replay / broker reconciliation.

Two reconciliation entry points:

* :func:`reconcile_engine_vs_replay` -- compare the trading engine's own
  bookkeeping against the state rebuilt by replaying the canonical event
  log. Drift here means the engine has a bug, the event log has a gap,
  or the engine swallowed a side-effect event.

* :func:`reconcile_broker_vs_engine` -- compare a broker snapshot
  (positions, cash, commissions, recent fills) against engine state.
  Drift here means we missed a broker message or the broker recorded
  something the engine did not request.

Both functions return a list of :class:`Mismatch` records. They never
raise on a discrepancy; impossible inputs (e.g. ``None`` snapshots)
raise :class:`ValueError`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Tuple

from aurora.execution.events import OrderState, OrderStateRecord
from aurora.execution.replay import ExecutionReplayState


# ---------------------------------------------------------------------------
# Mismatch taxonomy
# ---------------------------------------------------------------------------


class MismatchKind(str, Enum):
    MISSING_FILL = "missing_fill"
    DUPLICATE_FILL = "duplicate_fill"
    ORPHAN_ORDER = "orphan_order"
    STALE_ORDER = "stale_order"
    CASH_MISMATCH = "cash_mismatch"
    POSITION_MISMATCH = "position_mismatch"
    COMMISSION_MISMATCH = "commission_mismatch"
    UNKNOWN_BROKER_EVENT = "unknown_broker_event"
    REPLAY_GAP = "replay_gap"


@dataclass(frozen=True)
class Mismatch:
    kind: MismatchKind
    reason: str
    details: Dict[str, Any] = field(default_factory=dict)
    evidence_ids: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind.value,
            "reason": self.reason,
            "details": dict(self.details),
            "evidence_ids": list(self.evidence_ids),
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_TERMINAL_STATES = frozenset({
    OrderState.FILLED,
    OrderState.CANCELLED,
    OrderState.REJECTED,
    OrderState.EXPIRED,
    OrderState.RECONCILED,
})


def _approx_equal(a: float, b: float, atol: float) -> bool:
    if a == b:
        return True
    return abs(a - b) <= atol


def _engine_state_view(state: Any) -> Dict[str, Any]:
    """Coerce a heterogeneous engine state into a uniform mapping."""
    if state is None:
        raise ValueError("engine_state must not be None")
    if isinstance(state, ExecutionReplayState):
        return {
            "orders": dict(state.orders),
            "positions": dict(state.positions),
            "cash": float(state.cash),
            "commissions": float(state.commissions),
        }
    if isinstance(state, Mapping):
        return {
            "orders": dict(state.get("orders", {}) or {}),
            "positions": dict(state.get("positions", {}) or {}),
            "cash": float(state.get("cash", 0.0) or 0.0),
            "commissions": float(state.get("commissions", 0.0) or 0.0),
        }
    raise ValueError(
        f"engine_state must be ExecutionReplayState or Mapping, got {type(state)!r}"
    )


def _normalise_positions(positions: Mapping[str, Any]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for sym, qty in positions.items():
        try:
            v = float(qty)
        except (TypeError, ValueError):
            continue
        if v != 0.0:
            out[sym] = v
    return out


# ---------------------------------------------------------------------------
# Engine vs replay
# ---------------------------------------------------------------------------


def reconcile_engine_vs_replay(
    engine_state: Any,
    replay_state: ExecutionReplayState,
    *,
    atol: float = 1e-6,
) -> List[Mismatch]:
    """Compare engine bookkeeping against the replayed event log."""

    if replay_state is None:
        raise ValueError("replay_state must not be None")
    engine = _engine_state_view(engine_state)

    mismatches: List[Mismatch] = []

    # Cash drift.
    if not _approx_equal(engine["cash"], replay_state.cash, atol):
        mismatches.append(Mismatch(
            kind=MismatchKind.CASH_MISMATCH,
            reason="engine cash differs from replay cash",
            details={
                "engine_cash": engine["cash"],
                "replay_cash": replay_state.cash,
                "delta": engine["cash"] - replay_state.cash,
            },
        ))

    # Commission drift.
    if not _approx_equal(engine["commissions"], replay_state.commissions, atol):
        mismatches.append(Mismatch(
            kind=MismatchKind.COMMISSION_MISMATCH,
            reason="engine commissions differ from replay commissions",
            details={
                "engine_commissions": engine["commissions"],
                "replay_commissions": replay_state.commissions,
                "delta": engine["commissions"] - replay_state.commissions,
            },
        ))

    # Position drift.
    eng_pos = _normalise_positions(engine["positions"])
    rep_pos = _normalise_positions(replay_state.positions)
    for sym in sorted(set(eng_pos) | set(rep_pos)):
        e = eng_pos.get(sym, 0.0)
        r = rep_pos.get(sym, 0.0)
        if not _approx_equal(e, r, atol):
            mismatches.append(Mismatch(
                kind=MismatchKind.POSITION_MISMATCH,
                reason=f"position drift on {sym}",
                details={
                    "symbol": sym,
                    "engine_qty": e,
                    "replay_qty": r,
                    "delta": e - r,
                },
            ))

    # Order universe drift.
    eng_orders: Dict[str, Any] = engine["orders"]
    rep_orders: Dict[str, OrderStateRecord] = replay_state.orders
    eng_order_ids = set(eng_orders.keys())
    rep_order_ids = set(rep_orders.keys())

    for oid in sorted(eng_order_ids - rep_order_ids):
        mismatches.append(Mismatch(
            kind=MismatchKind.ORPHAN_ORDER,
            reason=f"engine has order {oid} that replay does not know",
            details={"order_id": oid},
            evidence_ids=(oid,),
        ))

    for oid in sorted(rep_order_ids - eng_order_ids):
        mismatches.append(Mismatch(
            kind=MismatchKind.REPLAY_GAP,
            reason=f"replay has order {oid} that engine does not know",
            details={"order_id": oid},
            evidence_ids=(oid,),
        ))

    # Per-order fill drift for ids present on both sides.
    for oid in sorted(eng_order_ids & rep_order_ids):
        eng_rec = eng_orders[oid]
        rep_rec = rep_orders[oid]
        eng_filled = float(getattr(eng_rec, "filled_qty", 0.0) or 0.0)
        rep_filled = float(rep_rec.filled_qty)
        if not _approx_equal(eng_filled, rep_filled, atol):
            kind = (
                MismatchKind.MISSING_FILL if rep_filled > eng_filled
                else MismatchKind.DUPLICATE_FILL
            )
            mismatches.append(Mismatch(
                kind=kind,
                reason=f"order {oid} fill quantity disagrees",
                details={
                    "order_id": oid,
                    "engine_filled": eng_filled,
                    "replay_filled": rep_filled,
                    "delta": eng_filled - rep_filled,
                },
                evidence_ids=(oid,),
            ))

        eng_state = getattr(eng_rec, "state", None)
        if eng_state is not None and rep_rec.state in _TERMINAL_STATES:
            if eng_state not in _TERMINAL_STATES:
                mismatches.append(Mismatch(
                    kind=MismatchKind.STALE_ORDER,
                    reason=(
                        f"order {oid} is terminal in replay but engine "
                        f"shows {eng_state}"
                    ),
                    details={
                        "order_id": oid,
                        "engine_state": str(eng_state),
                        "replay_state": rep_rec.state.value,
                    },
                    evidence_ids=(oid,),
                ))

    return mismatches


# ---------------------------------------------------------------------------
# Broker vs engine
# ---------------------------------------------------------------------------


def reconcile_broker_vs_engine(
    broker_snapshot: Mapping[str, Any],
    engine_state: Any,
    *,
    atol: float = 1e-6,
) -> List[Mismatch]:
    """Compare a broker snapshot against engine state.

    ``broker_snapshot`` shape (all keys optional, missing -> assumed empty):
        {
            "positions": {symbol: qty, ...},
            "cash": float,
            "commissions": float,
            "fills": [{"order_id": str, "qty": float, "price": float,
                       "fill_id": str, "side": "buy"/"sell"}, ...],
            "orders": {order_id: {...}, ...},  # optional broker view
            "unknown_events": [{"event_id": str, "kind": str,
                                "details": ...}, ...],
        }
    """

    if broker_snapshot is None:
        raise ValueError("broker_snapshot must not be None")
    if not isinstance(broker_snapshot, Mapping):
        raise ValueError("broker_snapshot must be a Mapping")
    engine = _engine_state_view(engine_state)
    mismatches: List[Mismatch] = []

    broker_cash = float(broker_snapshot.get("cash", engine["cash"]) or 0.0) \
        if "cash" in broker_snapshot else engine["cash"]
    broker_comm = float(broker_snapshot.get("commissions", engine["commissions"])
                         or 0.0) if "commissions" in broker_snapshot \
        else engine["commissions"]

    if "cash" in broker_snapshot and not _approx_equal(
        broker_cash, engine["cash"], atol,
    ):
        mismatches.append(Mismatch(
            kind=MismatchKind.CASH_MISMATCH,
            reason="broker cash differs from engine cash",
            details={
                "broker_cash": broker_cash,
                "engine_cash": engine["cash"],
                "delta": broker_cash - engine["cash"],
            },
        ))

    if "commissions" in broker_snapshot and not _approx_equal(
        broker_comm, engine["commissions"], atol,
    ):
        mismatches.append(Mismatch(
            kind=MismatchKind.COMMISSION_MISMATCH,
            reason="broker commissions differ from engine commissions",
            details={
                "broker_commissions": broker_comm,
                "engine_commissions": engine["commissions"],
                "delta": broker_comm - engine["commissions"],
            },
        ))

    broker_positions = _normalise_positions(broker_snapshot.get("positions", {}) or {})
    engine_positions = _normalise_positions(engine["positions"])
    for sym in sorted(set(broker_positions) | set(engine_positions)):
        b = broker_positions.get(sym, 0.0)
        e = engine_positions.get(sym, 0.0)
        if not _approx_equal(b, e, atol):
            mismatches.append(Mismatch(
                kind=MismatchKind.POSITION_MISMATCH,
                reason=f"broker / engine position drift on {sym}",
                details={
                    "symbol": sym,
                    "broker_qty": b,
                    "engine_qty": e,
                    "delta": b - e,
                },
            ))

    # Per-order fill comparison driven by broker fills.
    fills_iter: Iterable[Mapping[str, Any]] = broker_snapshot.get("fills", []) or []
    broker_fill_qty: Dict[str, float] = {}
    broker_fill_ids: Dict[str, List[str]] = {}
    for fill in fills_iter:
        oid = str(fill.get("order_id", ""))
        if not oid:
            continue
        qty = float(fill.get("qty", 0.0) or 0.0)
        broker_fill_qty[oid] = broker_fill_qty.get(oid, 0.0) + qty
        fid = str(fill.get("fill_id", "")) if fill.get("fill_id") else ""
        if fid:
            broker_fill_ids.setdefault(oid, []).append(fid)

    eng_orders: Dict[str, Any] = engine["orders"]
    for oid in sorted(set(broker_fill_qty) | set(eng_orders)):
        broker_qty = broker_fill_qty.get(oid)
        if broker_qty is None:
            # Engine sees the order but broker reports no fill -- only a
            # mismatch if the engine recorded a fill against it.
            rec = eng_orders.get(oid)
            engine_qty = float(getattr(rec, "filled_qty", 0.0) or 0.0)
            if engine_qty > 0:
                mismatches.append(Mismatch(
                    kind=MismatchKind.DUPLICATE_FILL,
                    reason=(
                        f"engine recorded {engine_qty} filled on order "
                        f"{oid} but broker reports no fill"
                    ),
                    details={
                        "order_id": oid,
                        "engine_filled": engine_qty,
                        "broker_filled": 0.0,
                    },
                    evidence_ids=(oid,),
                ))
            continue

        rec = eng_orders.get(oid)
        if rec is None:
            mismatches.append(Mismatch(
                kind=MismatchKind.MISSING_FILL,
                reason=(
                    f"broker filled order {oid} but engine has no order "
                    f"by that id"
                ),
                details={
                    "order_id": oid,
                    "broker_filled": broker_qty,
                },
                evidence_ids=tuple(broker_fill_ids.get(oid, ())),
            ))
            continue

        engine_qty = float(getattr(rec, "filled_qty", 0.0) or 0.0)
        if not _approx_equal(broker_qty, engine_qty, atol):
            kind = (
                MismatchKind.MISSING_FILL if broker_qty > engine_qty
                else MismatchKind.DUPLICATE_FILL
            )
            mismatches.append(Mismatch(
                kind=kind,
                reason=f"broker / engine fill drift on order {oid}",
                details={
                    "order_id": oid,
                    "broker_filled": broker_qty,
                    "engine_filled": engine_qty,
                    "delta": broker_qty - engine_qty,
                },
                evidence_ids=tuple(broker_fill_ids.get(oid, (oid,))),
            ))

    # Unknown broker events: surface any broker-side notice the engine
    # cannot interpret. This is informational, not necessarily an error.
    for note in broker_snapshot.get("unknown_events", []) or []:
        evid = str(note.get("event_id", "")) if isinstance(note, Mapping) else ""
        kind = str(note.get("kind", "")) if isinstance(note, Mapping) else str(note)
        mismatches.append(Mismatch(
            kind=MismatchKind.UNKNOWN_BROKER_EVENT,
            reason=f"broker emitted unknown event: {kind}" if kind else
                   "broker emitted unknown event",
            details=dict(note) if isinstance(note, Mapping) else {"raw": note},
            evidence_ids=(evid,) if evid else (),
        ))

    return mismatches


__all__ = [
    "Mismatch",
    "MismatchKind",
    "reconcile_broker_vs_engine",
    "reconcile_engine_vs_replay",
]
