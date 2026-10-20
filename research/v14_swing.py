"""v14 multi-day stock families on daily bars: small-cap shorts after spikes and filings (B10-B14), the small-cap
overnight bounce (C18 part) and the event families (C19-C22). Pre-registered in docs/research/V14_PREREGISTRATION.md.

``D`` holds wide daily arrays (dates x symbols, split-adjusted O, H, L, C; raw close P; 20-day dollar volume DV;
``new`` marks the first bar of a series after a gap of 5 or more sessions) and the event tables.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from aurora.research import v14_core as core

SSR_EXTRA = 0.005  # a daily-bar short opened 10% or more below the prior close pays this much more

SWING_DIMS = {
    "B10_OVERNIGHT": {"up": (0.40, 0.80, 1.50), "loc": (0.50, 1.00)},
    "B11_FIRSTRED": {"rise": (1.00, 2.00), "entry": ("open", "break"), "hold": (1, 5)},
    "B12_FADE": {"up": (0.50, 1.00), "hold": (5, 10, 20), "stop": (0.50, 1.00)},
    "B13_DILUTION": {"window": (5, 20), "spike": (True, False), "hold": (5, 20)},
    "B14_DELIST": {"hold": (5, 20, 60)},
    "C18_SMALLNIGHT": {"down": (0.20, 0.40)},
    "C19_PEAD": {"sides": ("ls", "long"), "gap": ("any", "agree"), "hold": (20, 60)},
    "C20_INSIDER": {"n": (2, 3), "value": (100e3, 500e3), "hold": (20, 60)},
    "C21_ACTIVIST": {"hold": (20, 60)},
    "C22_RUSSELL": {"entry": ("rankday", "june"), "exit": ("recon", "recon5")},
}


@dataclass
class Spec:
    """One trade before its returns: symbol column, entry row, how it enters, side, last row, stop and priority."""
    j: int
    t: int
    kind: str  # "open", "close" (enters at the close of row t), or "level" (at ``level``, else the open)
    side: int
    hold: int  # trading days the position is held, the entry day counting as the first
    stop: float  # fraction above (short) or below (long) the entry; nan for none; or an absolute price if "abs"
    prio: float
    level: float = np.nan
    stop_abs: float = np.nan


def pool(D: dict, family: str) -> np.ndarray:
    """Eligible symbols for each row, using the prior row's raw close and dollar volume (known before the open)."""
    P, DV = D["P1"], D["DV1"]
    if family in ("C19_PEAD",):
        return (P >= 5) & (DV >= 5e6)
    if family in ("C21_ACTIVIST",):
        return (P >= 2) & (DV >= 1e6)
    if family in ("C20_INSIDER", "C22_RUSSELL"):
        return (P >= 1) & (DV >= 1e6)
    return (P >= 1) & (P <= 20) & (DV >= 1e6)


def _once(t: np.ndarray, j: np.ndarray, gap: int = 10) -> np.ndarray:
    """Keep the first signal of a symbol and drop later ones within ``gap`` rows."""
    keep = np.ones(len(t), bool)
    last: dict[int, int] = {}
    for k in np.lexsort((t, j)):
        if j[k] in last and t[k] - last[j[k]] < gap:
            keep[k] = False
        else:
            last[j[k]] = t[k]
    return keep


def specs(D: dict, family: str, g: dict) -> list[Spec]:
    O, H, L, C, P = D["O"], D["H"], D["L"], D["C"], D["P"]
    ok = pool(D, family) & D["valid1"]
    T = C.shape[0]
    r1 = np.full_like(C, np.nan)
    r1[1:] = C[1:] / C[:-1] - 1
    out: list[Spec] = []
    if family == "B10_OVERNIGHT":
        rng = np.where(H > L, (C - L) / np.maximum(H - L, 1e-9), 0.5)
        band = (P >= 1) & (P <= 20) & (D["DV"] >= 1e6)
        t, j = np.nonzero((r1 >= g["up"]) & (rng <= g["loc"]) & band & D["valid"])
        out = [Spec(jj, tt, "close", -1, 2, np.nan, r1[tt, jj]) for tt, jj in zip(t, j) if tt + 1 < T]
    elif family == "C18_SMALLNIGHT":
        band = (P >= 1) & (P <= 20) & (D["DV"] >= 1e6)
        t, j = np.nonzero((r1 <= -g["down"]) & band & D["valid"])
        out = [Spec(jj, tt, "close", 1, 2, np.nan, -r1[tt, jj]) for tt, jj in zip(t, j) if tt + 1 < T]
    elif family == "B11_FIRSTRED":
        low3 = np.fmin(np.fmin(_shift(C, 2), _shift(C, 3)), _shift(C, 4))
        rise = _shift(C, 1) / low3 - 1
        green = _shift(r1, 1) > 0
        hi4 = np.fmax(np.fmax(_shift(H, 1), _shift(H, 2)), np.fmax(_shift(H, 3), _shift(H, 4)))
        cond = (rise >= g["rise"]) & green & ok
        if g["entry"] == "open":
            cond &= O < _shift(C, 1)
        else:
            cond &= L < _shift(L, 1)
        t, j = np.nonzero(cond)
        keep = _once(t, j)
        for tt, jj in zip(t[keep], j[keep]):
            lvl = np.nan if g["entry"] == "open" else float(L[tt - 1, jj])
            out.append(Spec(jj, tt, "open" if g["entry"] == "open" else "level", -1, g["hold"], np.nan,
                            float(rise[tt, jj]), level=lvl, stop_abs=float(hi4[tt, jj])))
    elif family == "B12_FADE":
        t, j = np.nonzero((_shift(r1, 1) >= g["up"]) & ok)
        keep = _once(t, j)
        out = [Spec(jj, tt, "open", -1, g["hold"], g["stop"], float(r1[tt - 1, jj]))
               for tt, jj in zip(t[keep], j[keep])]
    elif family in ("B13_DILUTION", "B14_DELIST", "C20_INSIDER", "C21_ACTIVIST"):
        ev = D["events"][{"B13_DILUTION": "offering", "B14_DELIST": "delist", "C20_INSIDER": "insider",
                          "C21_ACTIVIST": "activist"}[family]]
        if family == "C20_INSIDER":
            ev = ev[(ev["n"] >= g["n"]) & (ev["value"] >= g["value"])]
        side = -1 if family.startswith("B") else 1
        stop = 0.5 if family.startswith("B") else np.nan
        tt_all, jj_all = ev["t"].to_numpy(), ev["j"].to_numpy()
        keep = _once(tt_all, jj_all, 20)
        for tt, jj in zip(tt_all[keep], jj_all[keep]):
            if tt >= T or not ok[tt, jj]:
                continue
            if family == "B13_DILUTION" and g["spike"]:
                lo = max(1, tt - 1 - g["window"])
                if not np.nanmax(r1[lo:tt, jj], initial=-1) >= 0.5:
                    continue
            out.append(Spec(jj, tt, "open", side, g["hold"], stop, 0.0))
    elif family == "C19_PEAD":
        ev = D["events"]["pead"]
        for tt, jj, s, q in ev[["t", "j", "sue", "decile"]].itertuples(index=False):
            if tt >= T or not ok[tt, jj] or q not in (0, 9):
                continue
            side = 1 if q == 9 else -1
            if g["sides"] == "long" and side < 0:
                continue
            if g["gap"] == "agree" and np.sign(O[tt, jj] / C[tt - 1, jj] - 1) != side:
                continue
            out.append(Spec(jj, tt, "open", side, g["hold"], np.nan, abs(s)))
    elif family == "C22_RUSSELL":
        ev = D["events"]["russell"]
        for tt_rank, tt_june, tt_recon, jj, prio in ev[["t_rank", "t_june", "t_recon", "j", "prio"]].itertuples(
                index=False):
            t0 = tt_rank + 1 if g["entry"] == "rankday" else tt_june
            t1 = tt_recon + (5 if g["exit"] == "recon5" else 0)
            if t0 >= T or t1 >= T or t1 < t0 or not ok[t0, jj]:
                continue
            out.append(Spec(jj, t0, "open", 1, t1 - t0 + 1, np.nan, prio))
    else:
        raise KeyError(family)
    return out


def _shift(a: np.ndarray, k: int) -> np.ndarray:
    out = np.full_like(a, np.nan)
    out[k:] = a[:-k]
    return out


def path(D: dict, s: Spec, scenario: str) -> tuple[int, np.ndarray, float, float] | None:
    """(first row with a return, daily net returns, priority, weight) of one trade, or None if it cannot enter."""
    O, H, L, C, P, new = D["O"], D["H"], D["L"], D["C"], D["P"], D["new"]
    T = C.shape[0]
    t, j, side = s.t, s.j, s.side
    if s.kind == "close":
        entry, first = C[t, j], t + 1
        raw = P[t, j]
    else:
        o = O[t, j]
        if not np.isfinite(o):
            return None
        entry = o
        if s.kind == "level" and np.isfinite(s.level):
            entry = min(o, s.level) if side < 0 else max(o, s.level)
        first = t
        raw = P[t - 1, j] * (entry / C[t - 1, j]) if t > 0 and C[t - 1, j] > 0 else P[t, j]
    if not np.isfinite(entry) or entry <= 0:
        return None
    if scenario == "high" and side < 0 and not core.shortable_high(np.array([raw]), np.array([D["SO"][t, j]]))[0]:
        return None
    if np.isfinite(s.stop_abs):
        stop = s.stop_abs
    elif np.isfinite(s.stop):
        stop = entry * (1 + s.stop) if side < 0 else entry * (1 - s.stop)
    else:
        stop = np.nan
    rets, prev = [], entry
    last = min(T - 1, t + s.hold - 1) if s.kind != "close" else min(T - 1, t + 1)
    for u in range(first, last + 1):
        if u > first and new[u, j]:
            break
        o, h, lo, c = O[u, j], H[u, j], L[u, j], C[u, j]
        if not np.isfinite(c):
            break
        if s.kind == "close" and u == first:  # held overnight only, out at the next open
            rets.append(side * (o / prev - 1) if np.isfinite(o) else 0.0)
            break
        if np.isfinite(stop):
            hit = (h >= stop) if side < 0 else (lo <= stop)
            if hit:
                px = stop if (u == first and s.kind != "close") else (max(o, stop) if side < 0 else min(o, stop))
                rets.append(side * (px / prev - 1))
                break
        rets.append(side * (c / prev - 1))
        prev = c
    if not rets:
        return None
    r = np.array(rets)
    nights = max(len(r) - (0 if s.kind == "close" else 1), 0)
    cost = core.stock_cost(np.array([raw]), scenario)[0]
    if side < 0:
        cost += core.short_cost(np.array([raw]), np.array([nights]), scenario)[0]
        if s.kind != "close" and t > 0 and entry <= 0.9 * C[t - 1, j]:
            cost += SSR_EXTRA
    r[0] -= cost
    w = min(0.05, 0.01 * D["DV1"][t, j] / core.ACCOUNT) if np.isfinite(D["DV1"][t, j]) else 0.0
    return first, r, s.prio, w


def book(D: dict, sp: list[Spec], scenario: str) -> pd.Series:
    paths = [p for s in sp if (p := path(D, s, scenario)) is not None]
    return core.swing_book(paths, D["dates"])


def placebo_specs(D: dict, family: str, real: list[Spec], rng: np.random.Generator) -> list[Spec]:
    """Each real trade moved to a random symbol of the family's pool on its entry row, same side, holding and stop
    distance (absolute stops become the same fraction of the entry)."""
    ok = pool(D, family) & D["valid1"]
    out = []
    for s in real:
        cols = np.flatnonzero(ok[s.t])
        if not len(cols):
            continue
        stop = s.stop
        if np.isfinite(s.stop_abs):
            ref = D["O"][s.t, s.j]
            stop = abs(s.stop_abs / ref - 1) if np.isfinite(ref) and ref > 0 else 0.5
        out.append(Spec(int(rng.choice(cols)), s.t, "close" if s.kind == "close" else "open", s.side, s.hold, stop,
                        s.prio))
    return out
