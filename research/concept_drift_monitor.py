"""Concept drift monitoring for live strategies.

Three classic detectors are implemented from scratch over numpy:

    DDM    -- Drift Detection Method (Gama 2004) on binary error stream
    EDDM   -- Early DDM (Baena-Garcia 2006) tracking distance between errors
    KSWIN  -- Kolmogorov-Smirnov sliding window (Raab 2020) on continuous
              data; compares the most recent window to the older window.

All detectors expose a unified ``update(value) -> DriftSignal`` API. The
monitor wraps multiple detectors and reports a verdict per detector.
"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass
from typing import Literal
import math


DriftLevel = Literal["stable", "warning", "drift"]


@dataclass
class DriftSignal:
    level: DriftLevel
    detector: str
    statistic: float
    n_seen: int


class _DDM:
    """DDM on a binary error stream (1 = error, 0 = correct)."""

    def __init__(self, warning_z: float = 2.0, drift_z: float = 3.0):
        if drift_z <= warning_z:
            raise ValueError("drift_z must be > warning_z")
        self.warning_z = float(warning_z)
        self.drift_z = float(drift_z)
        self.n = 0
        self.p = 0.0
        self.s = 0.0
        self.p_min = float("inf")
        self.s_min = float("inf")

    def update(self, error: int | float) -> DriftSignal:
        e = float(error)
        if e not in (0.0, 1.0):
            # treat anything > 0.5 as an error for floating inputs
            e = 1.0 if e >= 0.5 else 0.0
        self.n += 1
        # streaming binomial estimate
        self.p = ((self.n - 1) * self.p + e) / self.n
        self.s = math.sqrt(max(0.0, self.p * (1.0 - self.p) / self.n))
        # track minimum p+s
        if self.p + self.s < self.p_min + self.s_min:
            self.p_min = self.p
            self.s_min = self.s
        z = ((self.p + self.s) - (self.p_min + self.s_min)) / max(self.s_min, 1e-12)
        if self.n < 30:
            level: DriftLevel = "stable"
        elif z >= self.drift_z:
            level = "drift"
        elif z >= self.warning_z:
            level = "warning"
        else:
            level = "stable"
        return DriftSignal(level=level, detector="ddm",
                           statistic=float(z), n_seen=self.n)


class _EDDM:
    """EDDM tracks mean distance between errors."""

    def __init__(self, warning_ratio: float = 0.95,
                 drift_ratio: float = 0.90):
        if not (0.0 < drift_ratio < warning_ratio <= 1.0):
            raise ValueError("require 0 < drift_ratio < warning_ratio <= 1")
        self.warning_ratio = float(warning_ratio)
        self.drift_ratio = float(drift_ratio)
        self.n = 0
        self.last_error_idx: int | None = None
        self.errors_seen = 0
        self.dist_mean = 0.0
        self.dist_m2 = 0.0
        self.peak_score = 0.0

    def update(self, error: int | float) -> DriftSignal:
        e = float(error)
        if e not in (0.0, 1.0):
            e = 1.0 if e >= 0.5 else 0.0
        self.n += 1
        score = 0.0
        if e == 1.0:
            if self.last_error_idx is not None:
                d = float(self.n - self.last_error_idx)
                self.errors_seen += 1
                # Welford
                delta = d - self.dist_mean
                self.dist_mean += delta / self.errors_seen
                self.dist_m2 += delta * (d - self.dist_mean)
            else:
                self.errors_seen += 1
            self.last_error_idx = self.n
            sd = math.sqrt(self.dist_m2 / self.errors_seen) if self.errors_seen > 1 else 0.0
            score = self.dist_mean + 2 * sd
            if score > self.peak_score:
                self.peak_score = score
        if self.errors_seen < 30 or self.peak_score == 0:
            level: DriftLevel = "stable"
        else:
            ratio = score / self.peak_score
            if ratio < self.drift_ratio:
                level = "drift"
            elif ratio < self.warning_ratio:
                level = "warning"
            else:
                level = "stable"
        return DriftSignal(level=level, detector="eddm",
                           statistic=float(score), n_seen=self.n)


class _KSWIN:
    """KS test between two halves of a sliding window."""

    def __init__(self, window: int = 100, alpha: float = 0.005):
        if window < 20:
            raise ValueError("window must be >= 20")
        if not (0.0 < alpha < 1.0):
            raise ValueError("alpha must be in (0, 1)")
        self.window = int(window)
        self.alpha = float(alpha)
        self._buf: deque[float] = deque(maxlen=self.window)
        self.n = 0

    def update(self, value: float) -> DriftSignal:
        self._buf.append(float(value))
        self.n += 1
        if len(self._buf) < self.window:
            return DriftSignal(level="stable", detector="kswin",
                               statistic=0.0, n_seen=self.n)
        half = self.window // 2
        a = sorted(list(self._buf)[:half])
        b = sorted(list(self._buf)[half:])
        # two-sample KS statistic
        d = self._ks_stat(a, b)
        # critical value approximation
        crit = math.sqrt(-0.5 * math.log(self.alpha / 2.0)) * math.sqrt(
            (len(a) + len(b)) / (len(a) * len(b))
        )
        if d > crit:
            level: DriftLevel = "drift"
        elif d > 0.7 * crit:
            level = "warning"
        else:
            level = "stable"
        return DriftSignal(level=level, detector="kswin",
                           statistic=float(d), n_seen=self.n)

    @staticmethod
    def _ks_stat(a: list[float], b: list[float]) -> float:
        i = j = 0
        d = 0.0
        n_a, n_b = len(a), len(b)
        while i < n_a and j < n_b:
            if a[i] <= b[j]:
                i += 1
            else:
                j += 1
            f1 = i / n_a
            f2 = j / n_b
            d = max(d, abs(f1 - f2))
        return d


class ConceptDriftMonitor:
    """Bundle DDM/EDDM/KSWIN under a single ``update`` call."""

    def __init__(self, ddm: bool = True, eddm: bool = True,
                 kswin: bool = True, kswin_window: int = 100):
        self._detectors: dict[str, object] = {}
        if ddm:
            self._detectors["ddm"] = _DDM()
        if eddm:
            self._detectors["eddm"] = _EDDM()
        if kswin:
            self._detectors["kswin"] = _KSWIN(window=kswin_window)
        if not self._detectors:
            raise ValueError("at least one detector must be enabled")
        self._signals: list[DriftSignal] = []

    def update(self, value: float) -> dict[str, DriftSignal]:
        out: dict[str, DriftSignal] = {}
        for name, det in self._detectors.items():
            sig = det.update(value)  # type: ignore[attr-defined]
            out[name] = sig
            self._signals.append(sig)
        return out

    def any_drift(self) -> bool:
        return any(s.level == "drift" for s in self._signals)

    def history(self) -> list[DriftSignal]:
        return list(self._signals)
