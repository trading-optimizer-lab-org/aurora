"""Options study 2 (docs/research/OPTIONS_STUDY2_PREREGISTRATION.md): 0DTE structures, delta-hedged overnight and
intraday straddles, and monthly single-stock straddles sorted on HV - IV. Pure functions; the data download lives
in scripts/run_options_study2.py. Bars as in aurora.research.earnings_options: 15-minute bars keyed by their start
time (New York, naive) with columns ``t``, ``vw`` and ``c``.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from aurora.research import earnings_options as eo
from aurora.research.earnings_options import FEE, H, M, atm, cluster_t, half

DISCOVERY = eo.DISCOVERY
VALIDATION_START = eo.VALIDATION_START
ETF_BASE = (0.0025, 0.01)
ETF_HIGH = (0.0075, 0.03)
STOCK_BASE = eo.BASE
STOCK_HIGH = eo.HIGH
SHARE_COST = 0.01
EXPIRE_AT = 0.05  # a 0DTE leg priced at or below this at 15:45 is left to expire
T_DISCOVERY = 2.61
T_VALIDATION = 1.65
MIN_TRADES = 200
MIN_MONTHS = 18
TRIALS = ("Z1_short_straddle", "Z2_iron_fly", "Z3_iron_condor", "Z4_risk_reversal", "Z5_put_ratio",
          "N1_overnight_short", "N2_intraday_long", "N3_weekend_short", "X1_vol_spread", "X2_long_cheap",
          "X3_short_rich")
# 0DTE legs: (kind, strike at S0 x moneyness, quantity; negative = sold)
ZDTE = {
    "Z1_short_straddle": [("C", 1.0, -1), ("P", 1.0, -1)],
    "Z2_iron_fly": [("C", 1.0, -1), ("P", 1.0, -1), ("C", 1.01, 1), ("P", 0.99, 1)],
    "Z3_iron_condor": [("C", 1.005, -1), ("P", 0.995, -1), ("C", 1.01, 1), ("P", 0.99, 1)],
    "Z4_risk_reversal": [("C", 1.005, 1), ("P", 0.995, -1)],
    "Z5_put_ratio": [("P", 0.995, 1), ("P", 0.99, -2)],
}


def bar_vw(day: pd.DataFrame | None, hh: int, mm: int) -> float | None:
    """VWAP of the 15-minute bar starting at hh:mm, or None without a trade in it."""
    if day is None or day.empty:
        return None
    at = day[day["t"] - day["t"].dt.normalize() == hh * H + mm * M]
    return float(at["vw"].iloc[0]) if len(at) else None


def bar_close(day: pd.DataFrame | None, hh: int, mm: int) -> float | None:
    if day is None or day.empty:
        return None
    at = day[day["t"] - day["t"].dt.normalize() == hh * H + mm * M]
    return float(at["c"].iloc[0]) if len(at) else None


def structure(trial: str, strikes: np.ndarray, s0: float) -> list[tuple[str, float, int]] | None:
    """The 0DTE legs at listed strikes; None if two legs of one kind fall on the same strike."""
    legs = [(kind, atm(strikes, s0 * m), q) for kind, m, q in ZDTE[trial]]
    for kind in "CP":
        ks = [k for x, k, _ in legs if x == kind]
        if len(ks) != len(set(ks)):
            return None
    return legs


def leg_pnl(qty: int, p_in: float, p_out: float, closed: bool, cost: tuple[float, float]) -> float:
    """P&L per share of one leg; a leg that is not closed is worth p_out (its intrinsic value) with no exit cost."""
    if qty > 0:
        got = (max(p_out - half(p_out, cost), 0.0) - FEE) if closed else p_out
        return qty * (got - (p_in + half(p_in, cost) + FEE))
    paid = (p_out + half(p_out, cost) + FEE) if closed else p_out
    return -qty * ((p_in - half(p_in, cost) - FEE) - paid)


def entry_cash(legs: list[tuple[str, float, int]], p_in: list[float], cost: tuple[float, float]) -> float:
    return sum(-q * (p + half(p, cost) + FEE) if q > 0 else -q * (p - half(p, cost) - FEE)
               for (_, _, q), p in zip(legs, p_in))


def max_loss(legs: list[tuple[str, float, int]], p_in: list[float], cost: tuple[float, float]) -> float:
    """Worst expiry outcome of the structure (positive = a loss), over every strike and the two extremes."""
    ks = sorted({k for _, k, _ in legs})
    grid = [0.0] + ks + [3 * ks[-1]]
    cash = entry_cash(legs, p_in, cost)
    worst = min(sum(q * eo.intrinsic(kind, k, s) for kind, k, q in legs) for s in grid) + cash
    return -worst


def _ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_straddle(s: float, k: float, t: float, v: float) -> float:
    sd = v * math.sqrt(t)
    d1 = (math.log(s / k) + 0.5 * sd * sd) / sd
    call = s * _ncdf(d1) - k * _ncdf(d1 - sd)
    return 2 * call - s + k


def implied_vol(price: float, s: float, k: float, t: float) -> float | None:
    """Black-Scholes volatility (no rate, no dividend) of a straddle price; None outside the model's range."""
    if t <= 0 or price <= abs(s - k) or price <= 0:
        return None
    lo, hi = 1e-4, 5.0
    if bs_straddle(s, k, t, hi) < price:
        return None
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if bs_straddle(s, k, t, mid) < price:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def straddle_delta(s: float, k: float, t: float, v: float) -> float:
    sd = v * math.sqrt(t)
    return 2 * _ncdf((math.log(s / k) + 0.5 * sd * sd) / sd) - 1


def hedged_return(side: int, p_in: list[float], p_out: list[float], s_in: float, s_out: float, delta: float,
                  cost: tuple[float, float]) -> float:
    """Straddle (side +1 long, -1 short) with -side x delta shares, on the straddle's entry price."""
    opt = sum(leg_pnl(side, a, b, True, cost) for a, b in zip(p_in, p_out))
    shares = -side * delta
    hedge = shares * (s_out - s_in) - 2 * abs(shares) * SHARE_COST
    return (opt + hedge) / sum(p_in)


def hold_return(side: int, c_in: float, p_in: float, k: float, s_t: float, cost: tuple[float, float]) -> float:
    """Straddle held to expiry: long on its cost, short on its premium."""
    payoff = abs(s_t - k)
    if side > 0:
        paid = c_in + p_in + half(c_in, cost) + half(p_in, cost) + 2 * FEE
        return (payoff - paid) / paid
    got = c_in + p_in - half(c_in, cost) - half(p_in, cost) - 2 * FEE
    return (got - payoff) / (c_in + p_in)


def deciles(signal: pd.Series) -> pd.Series:
    """0 (lowest) to 9 (highest), ties broken by order."""
    return pd.qcut(signal.rank(method="first"), 10, labels=False)


def period(entry: pd.Timestamp) -> str | None:
    if DISCOVERY[0] <= entry <= DISCOVERY[1]:
        return "discovery"
    if entry >= VALIDATION_START:
        return "validation"
    return None


def stats(tr: pd.DataFrame, monthly: bool = False) -> dict:
    """``tr``: net, net_high, and week (clustered t) or month (one observation a month)."""
    if tr.empty:
        return {"trades": 0}
    if monthly:
        g = tr.groupby("month")[["net", "net_high"]].mean()
        n = len(g)
        sd = float(g["net"].std(ddof=1)) if n > 1 else float("nan")
        m = float(g["net"].mean())
        t = m / (sd / math.sqrt(n)) if n > 1 and sd > 0 else float("nan")
        mh = float(g["net_high"].mean())
        r = g["net"]
    else:
        m, t = cluster_t(tr["net"].to_numpy(), tr["week"].to_numpy())
        mh, _ = cluster_t(tr["net_high"].to_numpy(), tr["week"].to_numpy())
        r = tr["net"]
    worst = np.sort(r.to_numpy())[:max(1, int(len(r) * 0.01))]
    out = {"trades": int(tr["positions"].sum()) if monthly else int(len(tr)), "mean": m, "t": t,
           "mean_high": mh, "median": float(r.median()), "hit": float((r > 0).mean()), "es1": float(worst.mean()),
           "worst": float(r.min())}
    if monthly:
        out["months"] = int(len(r))
    return out


def passes(s: dict, t_min: float, min_trades: int, min_months: int = 0) -> bool:
    return bool(s.get("trades", 0) >= min_trades and s.get("months", min_months) >= min_months and s["mean"] > 0
                and s["t"] >= t_min and s["mean_high"] > 0)


def decide(disc: dict[str, dict], val: dict[str, dict]) -> dict:
    found = [k for k in TRIALS if k in disc
             and passes(disc[k], T_DISCOVERY, MIN_TRADES, MIN_MONTHS if k.startswith("X") else 0)]
    kept = [k for k in found if k in val and passes(val[k], T_VALIDATION, 1)]
    return {"discovery_pass": found, "validation_pass": kept, "met": bool(kept)}
