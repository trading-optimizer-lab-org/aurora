"""Audit-replay integrity check (R147).

Reproduce every trade in a session from the audit log alone, with no
access to the source strategy code. If reproduction fails, the audit
chain is incomplete and the session is not auditable -- this is a
regulator-relevant gap.

Approach:

- Read the JSONL audit log.
- For each ``order_submitted`` entry, expect a matching
  ``order_filled`` (or ``order_cancelled`` / ``order_rejected``) entry
  later in the chain.
- Apply the fills to a synthetic portfolio book and reconstruct
  positions, cash, and realised PnL.
- Compare the reconstructed portfolio state at the end of the session
  to a reference state (supplied by the live runner).
- Mismatches surface as :class:`AuditReplayDiff` entries.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


# Order-event vocabulary expected in the audit log.
_ORDER_OPEN_EVENTS = {"order_submitted", "order_placed"}
_ORDER_CLOSE_EVENTS = {"order_filled", "order_cancelled", "order_rejected"}


@dataclass
class ReplayState:
    """Per-symbol reconstruction of position + cash."""

    positions: Dict[str, float] = field(default_factory=dict)
    cash: float = 0.0
    realised_pnl: float = 0.0
    trades_replayed: int = 0
    open_orders: Dict[str, Dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class AuditReplayDiff:
    """One mismatch between replayed state and reference state."""

    field_name: str
    replayed_value: Any
    reference_value: Any
    detail: str


@dataclass(frozen=True)
class AuditReplayResult:
    """Outcome of a full session replay."""

    state: ReplayState
    diffs: List[AuditReplayDiff]
    orphan_open_events: List[str]

    @property
    def passed(self) -> bool:
        return not self.diffs and not self.orphan_open_events


def _read_audit_log(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _apply_fill(state: ReplayState, entry: Dict[str, Any]) -> None:
    symbol = str(entry.get("symbol", ""))
    qty = float(entry.get("filled_qty", entry.get("quantity", 0)))
    price = float(entry.get("fill_price", entry.get("price", 0.0)))
    side = str(entry.get("side", "buy")).lower()
    signed = qty if side == "buy" else -qty
    prev_pos = state.positions.get(symbol, 0.0)
    state.positions[symbol] = prev_pos + signed
    state.cash -= signed * price
    if prev_pos != 0 and (prev_pos > 0) != (signed > 0):
        # Closing/reducing a position: book realised PnL.
        closed = min(abs(prev_pos), abs(signed)) * (1 if prev_pos > 0 else -1)
        state.realised_pnl += closed * price
    state.trades_replayed += 1


def replay_session(
    audit_log_path: Path,
    *,
    reference_state: Optional[Dict[str, Any]] = None,
) -> AuditReplayResult:
    """Replay an audit log and compare against a reference state.

    Args:
        audit_log_path: path to the JSONL audit log.
        reference_state: optional dict with ``positions``, ``cash``, and
            ``realised_pnl`` to compare against. If None, no diffs are
            emitted (the function only checks chain completeness).

    Returns:
        :class:`AuditReplayResult`.
    """
    rows = _read_audit_log(audit_log_path)
    state = ReplayState()
    open_orders: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        event = str(row.get("event", row.get("type", "")))
        order_id = str(row.get("order_id", ""))
        if event in _ORDER_OPEN_EVENTS and order_id:
            open_orders[order_id] = row
        elif event in _ORDER_CLOSE_EVENTS and order_id:
            open_orders.pop(order_id, None)
            if event == "order_filled":
                _apply_fill(state, row)
    state.open_orders = open_orders
    diffs: List[AuditReplayDiff] = []
    if reference_state is not None:
        ref_positions = dict(reference_state.get("positions", {}))
        for sym in set(list(state.positions.keys()) + list(ref_positions.keys())):
            replayed = state.positions.get(sym, 0.0)
            reference = ref_positions.get(sym, 0.0)
            if abs(replayed - reference) > 1e-9:
                diffs.append(AuditReplayDiff(
                    field_name=f"position[{sym}]",
                    replayed_value=replayed,
                    reference_value=reference,
                    detail="position quantity diverges from reference",
                ))
        if "cash" in reference_state and abs(state.cash - float(reference_state["cash"])) > 1e-6:
            diffs.append(AuditReplayDiff(
                field_name="cash",
                replayed_value=state.cash,
                reference_value=reference_state["cash"],
                detail="reconstructed cash diverges from reference",
            ))
        if "realised_pnl" in reference_state and abs(
            state.realised_pnl - float(reference_state["realised_pnl"])
        ) > 1e-6:
            diffs.append(AuditReplayDiff(
                field_name="realised_pnl",
                replayed_value=state.realised_pnl,
                reference_value=reference_state["realised_pnl"],
                detail="reconstructed realised PnL diverges from reference",
            ))
    return AuditReplayResult(
        state=state,
        diffs=diffs,
        orphan_open_events=list(open_orders.keys()),
    )


__all__ = [
    "ReplayState",
    "AuditReplayDiff",
    "AuditReplayResult",
    "replay_session",
]
