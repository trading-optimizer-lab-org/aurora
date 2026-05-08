"""Trader DNA Profiler.

Analyzes a trade history to produce a compact "DNA fingerprint" of the
trader: estimated risk tolerance, average holding period, and sector bias.
Pure stdlib + numpy.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Iterable


@dataclass
class TraderDNAProfiler:
    """Profile a trade history.

    Parameters
    ----------
    risk_thresholds : tuple[float, float]
        Two cut points on average position size, used to bucket the
        trader as ``conservative``, ``moderate``, or ``aggressive``.
    """

    risk_thresholds: tuple[float, float] = (0.05, 0.15)

    def __post_init__(self) -> None:
        a, b = self.risk_thresholds
        if not (0.0 < a < b):
            raise ValueError("risk_thresholds must satisfy 0 < a < b")

    def _bucket_risk(self, avg_size: float) -> str:
        a, b = self.risk_thresholds
        if avg_size < a:
            return "conservative"
        if avg_size < b:
            return "moderate"
        return "aggressive"

    def profile(self, trades: Iterable[dict]) -> dict:
        """Build the DNA fingerprint.

        Each trade is a dict with keys ``size`` (fraction of NAV),
        ``hold_days``, and ``sector``.
        """
        items = [t for t in trades if isinstance(t, dict)]
        if not items:
            return {
                "n_trades": 0,
                "risk_tolerance": "unknown",
                "avg_hold_days": 0.0,
                "sector_bias": {},
                "fingerprint": "empty",
            }

        sizes = [float(t.get("size", 0.0)) for t in items]
        holds = [float(t.get("hold_days", 0.0)) for t in items]
        sectors = [str(t.get("sector", "unknown")) for t in items]

        avg_size = statistics.fmean(sizes) if sizes else 0.0
        avg_hold = statistics.fmean(holds) if holds else 0.0

        bias: dict[str, float] = {}
        n = len(sectors)
        for s in sectors:
            bias[s] = bias.get(s, 0.0) + 1.0 / n

        risk = self._bucket_risk(avg_size)
        top_sector = max(bias.items(), key=lambda kv: kv[1])[0] if bias else "unknown"
        fingerprint = f"{risk[:3]}-{int(round(avg_hold))}d-{top_sector[:4]}"

        return {
            "n_trades": len(items),
            "risk_tolerance": risk,
            "avg_hold_days": avg_hold,
            "avg_size": avg_size,
            "sector_bias": bias,
            "fingerprint": fingerprint,
        }
