"""Volatility filter (R95).

Pause trading when a configured volatility metric breaches a band.
Compatible with VIX-driven flat-out, realised-vol throttling and
regime-detector-driven gating.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np


@dataclass
class VolFilterConfig:
    """Knobs for the volatility filter.

    Attributes:
        max_realised_vol_annual: trip when realised vol > this.
            Annualised. Default None disables this gate.
        min_realised_vol_annual: trip when realised vol < this (avoid
            zero-vol no-signal regime). Default None disables.
        vol_lookback: rolling window for realised vol. Default 20 bars.
        external_metric: optional callable returning a (label, value)
            tuple consulted alongside the realised-vol metric. Used
            to feed VIX or a regime detector.
        external_max: trip when ``external_metric`` value > this.
        external_min: trip when ``external_metric`` value < this.
    """

    max_realised_vol_annual: Optional[float] = None
    min_realised_vol_annual: Optional[float] = None
    vol_lookback: int = 20
    external_metric: Optional[Callable[[], tuple[str, float]]] = None
    external_max: Optional[float] = None
    external_min: Optional[float] = None


@dataclass
class VolFilter:
    config: VolFilterConfig

    def realised_vol(self, returns: np.ndarray, ppy: int = 252) -> float:
        if len(returns) < 2:
            return 0.0
        window = returns[-self.config.vol_lookback:]
        return float(np.std(window) * np.sqrt(ppy))

    def is_blocked(
        self,
        recent_returns: np.ndarray,
        ppy: int = 252,
    ) -> tuple[bool, str]:
        """Check both realised-vol and external-metric gates.

        Returns a ``(blocked, reason)`` tuple. ``reason`` is a free-form
        string for the daily ops report.
        """
        rv = self.realised_vol(np.asarray(recent_returns, dtype=float), ppy)
        if (
            self.config.max_realised_vol_annual is not None
            and rv > self.config.max_realised_vol_annual
        ):
            return True, f"realised_vol={rv:.4f} > max"
        if (
            self.config.min_realised_vol_annual is not None
            and rv < self.config.min_realised_vol_annual
        ):
            return True, f"realised_vol={rv:.4f} < min"
        if self.config.external_metric is not None:
            label, val = self.config.external_metric()
            if (
                self.config.external_max is not None
                and val > self.config.external_max
            ):
                return True, f"{label}={val:.4f} > max"
            if (
                self.config.external_min is not None
                and val < self.config.external_min
            ):
                return True, f"{label}={val:.4f} < min"
        return False, "ok"


__all__ = [
    "VolFilterConfig",
    "VolFilter",
]
