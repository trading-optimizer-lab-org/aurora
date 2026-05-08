"""Change Data Capture for broker positions.

Diff-snapshot pattern: store the previous state, compare to the new state,
emit CDC events ``inserted``, ``updated``, ``deleted``. Designed for the
shape ``{symbol: {qty, avg_price}}`` produced by ``brokers`` adapters.
"""
from __future__ import annotations

import copy
import time
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class CDCConfig:
    """Static config for :class:`ChangeDataCapture`.

    Attributes:
        key_field: dict key used as primary key.
        compare_fields: subset of fields used for change detection.
        qty_tol: absolute tolerance for ``qty`` comparison.
        price_tol: absolute tolerance for ``avg_price`` comparison.
    """
    key_field: str = "symbol"
    compare_fields: tuple[str, ...] = ("qty", "avg_price")
    qty_tol: float = 1e-9
    price_tol: float = 1e-6


@dataclass
class CDCEvent:
    op: str  # "insert" | "update" | "delete"
    key: str
    before: Optional[dict]
    after: Optional[dict]
    ts: float


class ChangeDataCapture:
    """Snapshot diff-based CDC stream."""

    def __init__(self, config: Optional[CDCConfig] = None) -> None:
        self.config = config or CDCConfig()
        self._snapshot: dict[str, dict] = {}

    # ------------------------------------------------------------------
    def reset(self, snapshot: Optional[dict[str, dict]] = None) -> None:
        self._snapshot = copy.deepcopy(snapshot or {})

    def snapshot(self) -> dict[str, dict]:
        return copy.deepcopy(self._snapshot)

    def capture(self, new_state: dict[str, dict]) -> list[CDCEvent]:
        """Compare ``new_state`` against the last snapshot and emit events."""
        events: list[CDCEvent] = []
        ts = time.time()
        old = self._snapshot
        new_keys = set(new_state.keys())
        old_keys = set(old.keys())
        for k in sorted(new_keys - old_keys):
            events.append(CDCEvent("insert", k, None,
                                   copy.deepcopy(new_state[k]), ts))
        for k in sorted(old_keys - new_keys):
            events.append(CDCEvent("delete", k,
                                   copy.deepcopy(old[k]), None, ts))
        for k in sorted(new_keys & old_keys):
            if self._row_changed(old[k], new_state[k]):
                events.append(CDCEvent(
                    "update", k,
                    copy.deepcopy(old[k]),
                    copy.deepcopy(new_state[k]), ts,
                ))
        self._snapshot = copy.deepcopy(new_state)
        return events

    # ------------------------------------------------------------------
    def _row_changed(self, before: dict, after: dict) -> bool:
        for field_name in self.config.compare_fields:
            b = before.get(field_name)
            a = after.get(field_name)
            if b is None and a is None:
                continue
            if b is None or a is None:
                return True
            tol = self._tol_for(field_name)
            try:
                if abs(float(a) - float(b)) > tol:
                    return True
            except (TypeError, ValueError):
                if a != b:
                    return True
        return False

    def _tol_for(self, field_name: str) -> float:
        if field_name == "qty":
            return float(self.config.qty_tol)
        if field_name == "avg_price":
            return float(self.config.price_tol)
        return 0.0
