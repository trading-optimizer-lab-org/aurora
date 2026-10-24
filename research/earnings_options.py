"""Earnings options study (docs/research/EARNINGS_OPTIONS_PREREGISTRATION.md): events, prices, trade returns,
statistics and the decision. Pure functions; the data download lives in scripts/run_earnings_options.py.

Times are New York wall-clock, naive pandas Timestamps. Option and stock bars are 15-minute bars keyed by their
start time, with columns ``t`` (start), ``vw`` (volume-weighted price) and ``c`` (close).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

NY = "America/New_York"
DISCOVERY = (pd.Timestamp("2024-02-01"), pd.Timestamp("2025-12-31"))
VALIDATION_START = pd.Timestamp("2026-01-01")
BASE = (0.02, 0.025)
HIGH = (0.04, 0.05)
FEE = 0.05 / 100  # $0.05 a contract a side, per share of the 100-share multiplier
MIN_PRICE = 10.0
MIN_DVOL = 50e6
WING = 1.5
T_DISCOVERY = 2.58
T_VALIDATION = 1.65
MIN_TRADES = 200
RISK = 0.02
MAX_AT_RISK = 0.15

TRIALS = ("H1_runup_3", "H1_runup_5", "H2_hold_all", "H2_cheap_08", "H2_cheap_06", "H3_momentum",
          "H3_last_reaction", "H4_fly_all", "H4_fly_12", "H4_fly_15")
ENTRY_LAG = {"H1_runup_3": 3, "H1_runup_5": 5}  # sessions before the eve; every other trial enters on the eve


def sec_time(value: str) -> pd.Timestamp:
    """The SEC's acceptanceDateTime is New York time converted to UTC twice; undo both conversions."""
    once = pd.Timestamp(value).tz_convert(NY).tz_localize(None)
    return once.tz_localize("UTC").tz_convert(NY).tz_localize(None)


def reaction_session(t: pd.Timestamp, sessions: pd.DatetimeIndex) -> pd.Timestamp | None:
    """The first session whose open follows the release, or None for a release during a session."""
    day = t.normalize()
    clock = t - day
    if day in sessions:
        if clock < pd.Timedelta(hours=9, minutes=30):
            return day
        if clock < pd.Timedelta(hours=16):
            return None
    i = sessions.searchsorted(day, side="right")
    return sessions[i] if i < len(sessions) else None


def build_events(filings: pd.DataFrame, sessions: pd.DatetimeIndex) -> pd.DataFrame:
    """Rows ``symbol, t`` (release time) -> one row per kept release with R, E, the session index of R and
    ``scheduled`` (previous kept release 70-110 calendar days earlier)."""
    rows = []
    for sym, g in filings.sort_values("t").groupby("symbol"):
        last_r = None
        last_t = None
        for t in g["t"]:
            r = reaction_session(t, sessions)
            if r is None:
                continue
            ir = int(sessions.get_loc(r))
            if ir < 1:
                continue
            if last_r is not None and ir - last_r < 20:
                continue
            gap = None if last_t is None else (t.normalize() - last_t.normalize()).days
            rows.append({"symbol": sym, "t": t, "R": r, "E": sessions[ir - 1], "iR": ir,
                         "scheduled": gap is not None and 70 <= gap <= 110})
            last_r, last_t = ir, t
    return pd.DataFrame(rows, columns=["symbol", "t", "R", "E", "iR", "scheduled"])


def history(events: pd.DataFrame, closes: dict[str, pd.Series], sessions: pd.DatetimeIndex) -> pd.DataFrame:
    """HM (median |close(R)/close(E) - 1| of the previous 4-8 scheduled releases within three years), the sign of
    the previous scheduled reaction, and the 60-session momentum to the eve's prior close."""
    out = events.copy()
    out["reaction"] = np.nan
    out["hm"] = np.nan
    out["last_sign"] = np.nan
    out["mom"] = np.nan
    for sym, g in out.groupby("symbol"):
        c = closes.get(sym)
        if c is None:
            continue
        for i in g.index:
            e, r = out.at[i, "E"], out.at[i, "R"]
            if e in c.index and r in c.index:
                out.at[i, "reaction"] = c[r] / c[e] - 1
            ie = int(sessions.get_loc(e))
            if ie >= 61 and sessions[ie - 1] in c.index and sessions[ie - 61] in c.index:
                out.at[i, "mom"] = c[sessions[ie - 1]] / c[sessions[ie - 61]] - 1
        for i in g.index:
            e = out.at[i, "E"]
            prev = out.loc[(out["symbol"] == sym) & out["scheduled"] & (out["R"] < e)
                           & (out["R"] >= e - pd.DateOffset(years=3)) & out["reaction"].notna()]
            if len(prev):
                out.at[i, "last_sign"] = np.sign(prev["reaction"].iloc[-1])
            if len(prev) >= 4:
                out.at[i, "hm"] = float(prev["reaction"].iloc[-8:].abs().median())
    return out


def dollar_volume_ok(dvol: pd.Series, sessions: pd.DatetimeIndex, entry: pd.Timestamp) -> bool:
    """Median dollar volume of the 20 sessions before the entry session, at least MIN_DVOL."""
    i = int(sessions.get_loc(entry))
    if i < 20:
        return False
    v = dvol.reindex(sessions[i - 20:i])
    return bool(v.notna().sum() >= 15 and v.median() >= MIN_DVOL)


def _clock(df: pd.DataFrame) -> pd.Series:
    return df["t"] - df["t"].dt.normalize()


H = pd.Timedelta(hours=1)
M = pd.Timedelta(minutes=1)


def price_entry(day: pd.DataFrame) -> float | None:
    """The 15:30 bar's VWAP, else the latest bar with a trade from 14:30 on (before 15:45 included)."""
    if day is None or day.empty:
        return None
    k = _clock(day)
    at = day[k == 15 * H + 30 * M]
    if len(at):
        return float(at["vw"].iloc[0])
    late = day[(k >= 14 * H + 30 * M) & (k <= 15 * H + 45 * M)]
    return float(late["vw"].iloc[-1]) if len(late) else None


def price_morning(day: pd.DataFrame) -> float | None:
    """The 09:45 bar's VWAP, else the first later bar with a trade that session."""
    if day is None or day.empty:
        return None
    k = _clock(day)
    later = day[(k >= 9 * H + 45 * M) & (k <= 15 * H + 45 * M)]
    return float(later["vw"].iloc[0]) if len(later) else None


def price_eve_exit(day: pd.DataFrame) -> float | None:
    """H1's exit on the eve: the 15:30 bar, else the latest bar with a trade that session."""
    if day is None or day.empty:
        return None
    k = _clock(day)
    at = day[k == 15 * H + 30 * M]
    if len(at):
        return float(at["vw"].iloc[0])
    reg = day[(k >= 9 * H + 30 * M) & (k <= 15 * H + 45 * M)]
    return float(reg["vw"].iloc[-1]) if len(reg) else None


def last_close(day: pd.DataFrame) -> float | None:
    """The close of the last regular-session bar."""
    if day is None or day.empty:
        return None
    k = _clock(day)
    reg = day[(k >= 9 * H + 30 * M) & (k <= 15 * H + 45 * M)]
    return float(reg["c"].iloc[-1]) if len(reg) else None


def atm(strikes: np.ndarray, s: float) -> float:
    """The listed strike nearest to s (ties: the lower)."""
    k = np.sort(np.asarray(strikes, float))
    d = np.abs(k - s)
    return float(k[np.flatnonzero(d == d.min())[0]])


def wings(strikes: np.ndarray, k0: float, im: float) -> tuple[float, float] | None:
    """Long call nearest K(1 + 1.5 IM) above K, long put nearest K(1 - 1.5 IM) below K."""
    k = np.sort(np.asarray(strikes, float))
    up, dn = k[k > k0], k[k < k0]
    if not len(up) or not len(dn):
        return None
    return atm(up, k0 * (1 + WING * im)), atm(dn, k0 * (1 - WING * im))


def half(p: float, cost: tuple[float, float]) -> float:
    return max(cost[0] * p, cost[1])


def long_return(p_in: list[float], p_out: list[float], cost: tuple[float, float]) -> float:
    paid = sum(p + half(p, cost) + FEE for p in p_in)
    got = sum(max(p - half(p, cost), 0.0) - FEE for p in p_out)
    return (got - paid) / paid


def fly_return(short_in: list[float], long_in: list[float], short_out: list[float], long_out: list[float],
               width: float, cost: tuple[float, float]) -> float | None:
    """Short iron fly on its maximum loss (the wider wing less the net credit); None if that is not positive."""
    credit = sum(p - half(p, cost) - FEE for p in short_in) - sum(p + half(p, cost) + FEE for p in long_in)
    debit = sum(p + half(p, cost) + FEE for p in short_out) - sum(max(p - half(p, cost), 0.0) - FEE for p in long_out)
    risk = width - credit
    if risk <= 0:
        return None
    return (credit - debit) / risk


def intrinsic(kind: str, k: float, s: float) -> float:
    return max(s - k, 0.0) if kind == "C" else max(k - s, 0.0)


def cluster_t(r: np.ndarray, groups: np.ndarray) -> tuple[float, float]:
    """Mean and its t with a cluster-robust standard error (clusters = groups)."""
    r = np.asarray(r, float)
    n = len(r)
    if n < 2:
        return (float(r.mean()) if n else float("nan")), float("nan")
    m = r.mean()
    sums = pd.Series(r - m).groupby(np.asarray(groups)).sum().to_numpy()
    g = len(sums)
    if g < 2:
        return float(m), float("nan")
    se = math.sqrt((g / (g - 1)) * float((sums ** 2).sum())) / n
    return float(m), (float(m / se) if se > 0 else float("nan"))


def stats(tr: pd.DataFrame) -> dict:
    """``tr`` has columns net (base), net_high, week."""
    if tr.empty:
        return {"trades": 0}
    m, t = cluster_t(tr["net"].to_numpy(), tr["week"].to_numpy())
    mh, _ = cluster_t(tr["net_high"].to_numpy(), tr["week"].to_numpy())
    return {"trades": int(len(tr)), "mean": m, "t": t, "mean_high": mh, "median": float(tr["net"].median()),
            "hit": float((tr["net"] > 0).mean())}


def passes(s: dict, t_min: float, min_trades: int) -> bool:
    return bool(s.get("trades", 0) >= min_trades and s["mean"] > 0 and s["t"] >= t_min and s["mean_high"] > 0)


def decide(disc: dict[str, dict], val: dict[str, dict]) -> dict:
    found = [k for k in TRIALS if k in disc and passes(disc[k], T_DISCOVERY, MIN_TRADES)]
    kept = [k for k in found if k in val and passes(val[k], T_VALIDATION, 1)]
    return {"discovery_pass": found, "validation_pass": kept, "met": bool(kept)}


@dataclass
class Trade:
    entry: pd.Timestamp
    exit: pd.Timestamp
    ret: float
    priority: float


def book(trades: list[Trade], start: float = 100_000.0) -> dict:
    """Each trade risks RISK of the equity at its entry, at most MAX_AT_RISK of it at once; equity moves at exits."""
    ev = sorted(trades, key=lambda x: (x.entry, -x.priority))
    eq = start
    open_: list[tuple[pd.Timestamp, float, float]] = []
    marks = [(ev[0].entry if ev else pd.Timestamp("2024-01-01"), eq)]
    taken = 0
    for tr in ev:
        for o in sorted([o for o in open_ if o[0] <= tr.entry], key=lambda o: o[0]):
            eq += o[1] * o[2]
            marks.append((o[0], eq))
        open_ = [o for o in open_ if o[0] > tr.entry]
        at_risk = sum(o[1] for o in open_)
        r = RISK * eq
        if at_risk + r > MAX_AT_RISK * eq + 1e-9:
            continue
        open_.append((tr.exit, r, tr.ret))
        taken += 1
    for o in sorted(open_, key=lambda o: o[0]):
        eq += o[1] * o[2]
        marks.append((o[0], eq))
    s = pd.Series([v for _, v in marks], index=pd.DatetimeIndex([t for t, _ in marks]))
    s = s.groupby(s.index.normalize()).last()
    dd = float((s / s.cummax() - 1).min())
    worst = float(s.pct_change().min()) if len(s) > 1 else 0.0
    years = max((s.index[-1] - s.index[0]).days / 365.25, 1e-9)
    cagr = float((s.iloc[-1] / start) ** (1 / years) - 1) if s.iloc[-1] > 0 else -1.0
    return {"taken": taken, "end": float(s.iloc[-1]), "cagr": cagr, "max_dd": dd, "worst_session": worst}
