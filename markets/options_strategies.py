"""Multi-leg options strategy builder.

Constructs vertical spreads, iron condors and butterflies, then provides
payoff diagrams and net-greek summaries from per-leg Black-Scholes greeks.

This module is self-contained: it implements its own BS pricer rather than
depending on any other aurora module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import erf, exp, log, sqrt, pi
from typing import Literal, Optional

import numpy as np
import pandas as pd

OptType = Literal["call", "put"]


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return exp(-0.5 * x * x) / sqrt(2.0 * pi)


def _bs_greeks(S: float, K: float, T: float, r: float, sigma: float,
               opt: OptType) -> dict:
    """Black-Scholes price + greeks for a European option.

    Greeks returned: delta, gamma, vega (per 1.0 vol unit), theta (per year),
    rho (per 1.0 rate unit). Price units match S.
    """
    if T <= 0 or sigma <= 0:
        intrinsic = max(0.0, (S - K) if opt == "call" else (K - S))
        return {"price": intrinsic, "delta": 0.0, "gamma": 0.0,
                "vega": 0.0, "theta": 0.0, "rho": 0.0}
    d1 = (log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * sqrt(T))
    d2 = d1 - sigma * sqrt(T)
    if opt == "call":
        price = S * _norm_cdf(d1) - K * exp(-r * T) * _norm_cdf(d2)
        delta = _norm_cdf(d1)
        rho = K * T * exp(-r * T) * _norm_cdf(d2)
        theta = (-(S * _norm_pdf(d1) * sigma) / (2 * sqrt(T))
                 - r * K * exp(-r * T) * _norm_cdf(d2))
    else:
        price = K * exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)
        delta = _norm_cdf(d1) - 1.0
        rho = -K * T * exp(-r * T) * _norm_cdf(-d2)
        theta = (-(S * _norm_pdf(d1) * sigma) / (2 * sqrt(T))
                 + r * K * exp(-r * T) * _norm_cdf(-d2))
    gamma = _norm_pdf(d1) / (S * sigma * sqrt(T))
    vega = S * _norm_pdf(d1) * sqrt(T)
    return {"price": price, "delta": delta, "gamma": gamma,
            "vega": vega, "theta": theta, "rho": rho}


@dataclass
class OptionsStrategyConfig:
    """Pricing assumptions.

    Attributes:
        risk_free: continuously-compounded risk-free rate.
        iv_default: implied vol used when constructing mock legs.
        spot_default: spot price used in payoff diagram default range.
        days_to_expiry: T in calendar days for builder methods.
    """
    risk_free: float = 0.04
    iv_default: float = 0.25
    spot_default: float = 100.0
    days_to_expiry: int = 30


@dataclass
class _Leg:
    side: Literal["long", "short"]
    opt: OptType
    strike: float
    qty: int = 1
    iv: Optional[float] = None  # uses config default if None


class OptionsStrategyBuilder:
    """Build common multi-leg structures and analyse them."""

    def __init__(self, config: Optional[OptionsStrategyConfig] = None) -> None:
        self.config = config or OptionsStrategyConfig()

    # ------------------------------------------------------------------
    # Constructors
    # ------------------------------------------------------------------
    def vertical_spread(self, lower_k: float, upper_k: float,
                        opt: OptType = "call",
                        debit: bool = True) -> list[_Leg]:
        """Build a vertical spread.

        Debit call spread: long lower call, short upper call.
        Credit call spread: short lower call, long upper call.
        Put spreads use put legs; the lower/upper labels still refer to strike.
        """
        if lower_k >= upper_k:
            raise ValueError("lower_k must be < upper_k")
        if opt == "call":
            long_k, short_k = (lower_k, upper_k) if debit else (upper_k, lower_k)
        else:
            long_k, short_k = (upper_k, lower_k) if debit else (lower_k, upper_k)
        return [_Leg("long", opt, long_k), _Leg("short", opt, short_k)]

    def iron_condor(self, put_long_k: float, put_short_k: float,
                    call_short_k: float, call_long_k: float) -> list[_Leg]:
        """Iron condor: short put + long lower put, short call + long upper call."""
        if not (put_long_k < put_short_k < call_short_k < call_long_k):
            raise ValueError(
                "strikes must satisfy put_long < put_short < call_short < call_long")
        return [
            _Leg("long", "put", put_long_k),
            _Leg("short", "put", put_short_k),
            _Leg("short", "call", call_short_k),
            _Leg("long", "call", call_long_k),
        ]

    def butterfly(self, lower_k: float, mid_k: float, upper_k: float,
                  opt: OptType = "call") -> list[_Leg]:
        """Long butterfly: long 1 lower, short 2 mid, long 1 upper."""
        if not (lower_k < mid_k < upper_k):
            raise ValueError("lower_k < mid_k < upper_k required")
        return [
            _Leg("long", opt, lower_k, qty=1),
            _Leg("short", opt, mid_k, qty=2),
            _Leg("long", opt, upper_k, qty=1),
        ]

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------
    def analyze(self, legs: list[_Leg],
                spot: Optional[float] = None) -> dict:
        """Return net price + greeks for the structure at spot."""
        S = spot if spot is not None else self.config.spot_default
        T = self.config.days_to_expiry / 365.0
        r = self.config.risk_free
        net = {"price": 0.0, "delta": 0.0, "gamma": 0.0,
               "vega": 0.0, "theta": 0.0, "rho": 0.0}
        for leg in legs:
            iv = leg.iv if leg.iv is not None else self.config.iv_default
            g = _bs_greeks(S, leg.strike, T, r, iv, leg.opt)
            sign = 1 if leg.side == "long" else -1
            for k in net:
                net[k] += sign * leg.qty * g[k]
        return net

    def payoff(self, legs: list[_Leg],
               spot_min: Optional[float] = None,
               spot_max: Optional[float] = None,
               steps: int = 51) -> pd.DataFrame:
        """Terminal payoff diagram (T -> 0). No time value remaining.

        Returns DataFrame with columns: spot, payoff.
        """
        if not legs:
            return pd.DataFrame(columns=["spot", "payoff"])
        strikes = [l.strike for l in legs]
        lo = spot_min if spot_min is not None else min(strikes) * 0.7
        hi = spot_max if spot_max is not None else max(strikes) * 1.3
        spots = np.linspace(lo, hi, steps)
        payoffs = []
        for s in spots:
            p = 0.0
            for leg in legs:
                intrinsic = max(0.0, (s - leg.strike)
                                if leg.opt == "call" else (leg.strike - s))
                sign = 1 if leg.side == "long" else -1
                p += sign * leg.qty * intrinsic
            payoffs.append(p)
        return pd.DataFrame({"spot": spots, "payoff": payoffs})

    def signals(self, legs: list[_Leg],
                spot: Optional[float] = None) -> pd.DataFrame:
        """Return net-greeks as a single-row DataFrame."""
        net = self.analyze(legs, spot=spot)
        return pd.DataFrame([net])
