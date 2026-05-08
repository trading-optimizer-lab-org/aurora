"""OOS Plus pre-construction holdout (R106).

Today the tier protocol has IS_TRAIN / IS_VALID / OOS_DEV /
OOS_LOCKED / FORWARD. R106 adds an additional **OOS_PLUS** partition
reserved BEFORE strategy construction even begins -- consulted only
once at the very end, after OOS_LOCKED, before live deployment. It
sits between OOS_LOCKED and FORWARD.

The defence layer: the factory and the auto-loop must never read the
OOS_PLUS partition. Only the operator-driven "final-check ceremony"
consults it.

This module ships:

- the new tier value string (``OOS_PLUS``),
- a guard primitive (``OOSPlusGuard``) that gates reads,
- a final-check helper (``run_final_check``) the operator wraps the
  one allowed evaluation in.

The existing tier registry (``core/data_tiers.py``) is the source of
truth for tier values. The guard here is additive: it does NOT edit
the existing module, so consumers that don't import ``oos_plus``
keep the previous behaviour.
"""
from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import Iterator


OOS_PLUS = "OOS_PLUS"


class OOSPlusViolation(Exception):
    """Raised when code reads the OOS_PLUS partition without the guard."""


@dataclass
class OOSPlusGuard:
    """Context manager that authorises a single OOS_PLUS read."""

    operator_id: str
    rationale: str
    _open: bool = False

    @contextlib.contextmanager
    def open(self) -> Iterator["OOSPlusGuard"]:
        if self._open:
            raise OOSPlusViolation(
                "nested OOS_PLUS guard not allowed; close the outer one first"
            )
        self._open = True
        try:
            yield self
        finally:
            self._open = False


def assert_can_read(guard: "OOSPlusGuard | None") -> None:
    """Raise unless ``guard`` is currently open."""
    if guard is None or not guard._open:
        raise OOSPlusViolation(
            "OOS_PLUS partition is not readable without an active OOSPlusGuard"
        )


@dataclass(frozen=True)
class FinalCheckResult:
    """The single allowed OOS_PLUS evaluation."""

    metric_name: str
    metric_value: float
    threshold: float
    passed: bool


def run_final_check(
    *,
    guard: OOSPlusGuard,
    metric_name: str,
    metric_value: float,
    threshold: float,
) -> FinalCheckResult:
    """Run THE single OOS_PLUS evaluation under an open guard.

    Raises:
        OOSPlusViolation: guard is not open.
    """
    assert_can_read(guard)
    return FinalCheckResult(
        metric_name=metric_name,
        metric_value=float(metric_value),
        threshold=float(threshold),
        passed=metric_value >= threshold,
    )


__all__ = [
    "OOS_PLUS",
    "OOSPlusGuard",
    "OOSPlusViolation",
    "FinalCheckResult",
    "assert_can_read",
    "run_final_check",
]
