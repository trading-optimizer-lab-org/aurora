"""Shared absolute admission deadline; absent outside a budgeted gate job."""

import math
import os
import time


def gate_timeout(maximum_seconds: float, *, reserve_seconds: float = 0.0) -> float:
    raw = os.environ.get("CATALOG_GATE_DEADLINE_UNIX")
    if raw is None:
        return maximum_seconds
    try:
        deadline = float(raw)
    except ValueError as exc:
        raise ValueError("CATALOG_GATE_DEADLINE_INVALID") from exc
    if not math.isfinite(deadline) or deadline <= 0:
        raise ValueError("CATALOG_GATE_DEADLINE_INVALID")
    remaining = deadline - time.time() - reserve_seconds
    if remaining <= 0:
        raise ValueError("CATALOG_GATE_DEADLINE_EXCEEDED")
    return min(maximum_seconds, remaining)
