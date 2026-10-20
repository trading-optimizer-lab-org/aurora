"""v14 intraday families on minute bars: small caps long (A1-A7), small caps short (B8-B9), stocks in play (C15)
and the index windows (C16-C17). Pre-registered in docs/research/V14_PREREGISTRATION.md.

Minute bars of the regular session only, minute 0 = 09:30, prices raw. A candidate is one symbol-day of a scope;
``Store`` holds every candidate's bars in flat arrays with an offset and a length.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from aurora.research import v14_core as core

LAST_ENTRY = 330  # 15:00
FIELDS = ("m", "o", "h", "l", "c", "v", "vw")


@dataclass
class Store:
    cands: pd.DataFrame  # one row per candidate: date, symbol, off, n and the per-candidate facts
    arrays: dict  # m (int16, minute of the session), o, h, l, c, v, vw (float32)

    def bars(self, k: int) -> tuple:
        off, n = int(self.cands.at[k, "off"]), int(self.cands.at[k, "n"])
        return tuple(self.arrays[f][off:off + n] for f in FIELDS)


def vwap(c: np.ndarray, v: np.ndarray, vw: np.ndarray) -> np.ndarray:
    px = np.where(np.isfinite(vw) & (vw > 0), vw, c)
    cv = np.cumsum(v)
    return np.where(cv > 0, np.cumsum(px * v) / np.maximum(cv, 1e-9), c)


def opening_range(m: np.ndarray, h: np.ndarray, l: np.ndarray, k: int) -> tuple[float, float, int]:
    """High and low of the first k minutes and the index of the first bar after them."""
    first = int(np.searchsorted(m, k))
    if first == 0:
        return np.nan, np.nan, 0
    return float(h[:first].max()), float(l[:first].min()), first


def first_true(mask: np.ndarray, start: int = 0) -> int:
    if start >= len(mask):
        return -1
    j = int(np.argmax(mask[start:]))
    return start + j if mask[start + j] else -1


def run_exit(side: int, i: int, entry: float, stop: float, mode: str, b: tuple, vw_line: np.ndarray,
             same_bar: bool = True) -> tuple[float, int]:
    """Exit at the stop (the bar's open if it gaps through), on a close beyond VWAP after 5 minutes (mode "vwap"),
    or at the last bar's close. ``same_bar``: a stop entry can be stopped in its own bar (conservative)."""
    m, o, h, l, c = b[0], b[1], b[2], b[3], b[4]
    s0 = i if same_bar else i + 1
    if side > 0:
        hit = first_true(l <= stop, s0)
    else:
        hit = first_true(h >= stop, s0)
    end = len(c) - 1
    vx = -1
    if mode == "vwap":
        late = m >= m[i] + 5
        cond = (c < vw_line) if side > 0 else (c > vw_line)
        vx = first_true(late & cond, i + 1)
    cands = [(hit, "stop"), (vx, "vwap")]
    cands = [(j, kind) for j, kind in cands if j >= 0]
    if not cands:
        return float(c[end]), end
    j, kind = min(cands)
    if kind == "stop":
        px = min(float(o[j]), stop) if side > 0 else max(float(o[j]), stop)
        if j == i:
            px = stop
        return px, j
    return float(c[j]), j


def _ssr_fill(i: int, b: tuple, pc: float, entry: float, limit: int = 15) -> tuple[int, float]:
    """Short-sale restriction: 10% or more below the prior close, a short fills only on an up-close minute."""
    if entry > 0.9 * pc:
        return i, entry
    m, c = b[0], b[4]
    for j in range(max(i, 1), len(c)):
        if m[j] > m[i] + limit:
            break
        if c[j] > c[j - 1]:
            return j, float(c[j])
    return -1, np.nan


def _row(cd: pd.Series, side: int, j_entry: int, entry: float, stop: float, ex: float, b: tuple,
         prio: float) -> dict:
    m, c, v, vw = b[0], b[4], b[5], b[6]
    px = np.where(np.isfinite(vw) & (vw > 0), vw, c)
    liq = float(cd["pmv"]) + float(np.sum(px[:j_entry] * v[:j_entry]))
    return {"date": cd["date"], "symbol": cd["symbol"], "minute": int(m[j_entry]), "side": side, "entry": entry,
            "exit": ex, "stop": stop, "price": float(cd["open"]), "liq": liq, "prio": prio, "nights": 0,
            "so": float(cd.get("so", np.nan))}


# ---------------------------------------------------------------- entries

def entry_orb(b: tuple, k: int, side: int) -> tuple[int, float, float]:
    m, o, h, l = b[0], b[1], b[2], b[3]
    hi, lo, first = opening_range(m, h, l, k)
    if not np.isfinite(hi):
        return -1, np.nan, np.nan
    ok = m <= LAST_ENTRY
    if side > 0:
        j = first_true((h > hi) & ok, first)
        return (j, max(hi, float(o[j])), lo) if j >= 0 else (-1, np.nan, np.nan)
    j = first_true((l < lo) & ok, first)
    return (j, min(lo, float(o[j])), hi) if j >= 0 else (-1, np.nan, np.nan)


def entry_pmhigh(b: tuple, pmh: float, pml30: float) -> tuple[int, float, float]:
    m, o, h, l = b[0], b[1], b[2], b[3]
    if not np.isfinite(pmh):
        return -1, np.nan, np.nan
    j = first_true((h > pmh) & (m <= LAST_ENTRY), 0)
    if j < 0:
        return -1, np.nan, np.nan
    stop = float(l[:j].min()) if j > 0 else pml30
    entry = max(pmh, float(o[j]))
    return (j, entry, stop) if np.isfinite(stop) and stop < entry else (-1, np.nan, np.nan)


def entry_vwap_pullback(b: tuple, line: np.ndarray) -> tuple[int, float, float]:
    m, l, c = b[0], b[3], b[4]
    j = first_true((m >= 15) & (m <= LAST_ENTRY) & (l <= line) & (c > line), 0)
    if j < 0:
        return -1, np.nan, np.nan
    stop = float(l[:j + 1].min())
    return (j + 1, float(c[j]), stop) if j + 1 < len(c) and stop < c[j] else (-1, np.nan, np.nan)


def entry_vwap_loss(b: tuple, line: np.ndarray) -> tuple[int, float, float]:
    m, h, c = b[0], b[2], b[4]
    above = np.maximum.accumulate(c > line)
    prior_above = np.r_[False, above[:-1]]
    j = first_true((m >= 15) & (m <= LAST_ENTRY) & prior_above & (c < line), 0)
    if j < 0 or j + 1 >= len(c):
        return -1, np.nan, np.nan
    return j + 1, float(c[j]), float(h[:j + 1].max())


def entry_at(b: tuple, minute: int) -> int:
    j = int(np.searchsorted(b[0], minute))
    return j if j < len(b[0]) and b[0][j] <= minute + 5 else -1


def entry_halt(b: tuple, rise: float) -> tuple[int, float, float]:
    m, o, c = b[0], b[1], b[4]
    gaps = np.flatnonzero(np.diff(m) >= 6)
    for g in gaps:
        before = int(np.searchsorted(m, m[g] - 5))
        if c[before] > 0 and c[g] / c[before] - 1 >= rise and m[g + 1] <= LAST_ENTRY:
            if o[g + 1] > c[g]:
                return g + 1, float(o[g + 1]), float(c[g])
            return -1, np.nan, np.nan
    return -1, np.nan, np.nan


# ---------------------------------------------------------------- families

A_DIMS = {
    "A1_GAPGO": {"gap": (0.20, 0.40, 0.80), "orb": (1, 5, 15), "exit": ("close", "vwap"), "pmv": (250e3, 1e6)},
    "A2_PMHIGH": {"gap": (0.20, 0.40, 0.80), "exit": ("close", "vwap"), "pmv": (250e3, 1e6)},
    "A3_VWAPPB": {"gap": (0.20, 0.40, 0.80), "exit": ("close", "vwap"), "pmv": (250e3, 1e6)},
    "A4_DAY2": {"day1": (0.50, 1.00), "loc": (0.75, 0.90), "orb": (5, 15), "exit": ("close", "vwap")},
    "A5_LOWFLOAT": {"gap": (0.20, 0.40), "orb": (1, 5), "exit": ("close", "vwap"), "so": (10e6, 20e6)},
    "A6_HALTUP": {"rise": (0.10, 0.20), "exit": ("close", "vwap")},
    "A7_GAPDOWN": {"gap": (-0.20, -0.35), "orb": (5, 15), "exit": ("close", "vwap"), "pmv": (250e3, 1e6)},
    "B8_GAPFADE": {"gap": (0.30, 0.50, 1.00), "entry": ("orl5", "orl15", "vwaploss"), "exit": ("close", "vwap"),
                   "pmv": (250e3, 1e6)},
    "B9_LATEFADE": {"at": (330, 360), "up": (0.40, 0.80), "below_vwap": (True, False)},
    "C15_INPLAY": {"top": (5, 20), "orb": (5, 15), "stop": ("atr10", "atr25", "bar"), "sides": ("both", "long")},
}


def pool(store: Store, family: str) -> pd.Series:
    """The scope each family draws from (its broad filter); placebo draws come from the same set."""
    c = store.cands
    band = (c["open"] >= 1) & (c["open"] <= 20)
    if family in ("A7_GAPDOWN",):
        return band & c["s_gap_down"]
    if family == "A4_DAY2":
        return band & c["s_day2"]
    if family == "C15_INPLAY":
        return c["s_in_play"]
    if family == "B9_LATEFADE":
        return band & (c["s_runner"] | c["s_gap_up"])
    return band & c["s_gap_up"]


def candidates(store: Store, family: str, g: dict) -> pd.Index:
    c = store.cands
    base = pool(store, family)
    if family in ("A1_GAPGO", "A2_PMHIGH", "A3_VWAPPB", "B8_GAPFADE"):
        sel = base & (c["gap"] >= g["gap"]) & (c["pmv"] >= g["pmv"])
    elif family == "A5_LOWFLOAT":
        sel = base & (c["gap"] >= g["gap"]) & (c["so"] < g["so"])
    elif family == "A4_DAY2":
        sel = base & (c["day1"] >= g["day1"]) & (c["day1_loc"] >= g["loc"])
    elif family == "A6_HALTUP":
        sel = base & (c["gap"] >= 0.20)
    elif family == "A7_GAPDOWN":
        sel = base & (c["gap"] <= g["gap"]) & (c["pmv"] >= g["pmv"])
    elif family == "B9_LATEFADE":
        sel = base
    elif family == "C15_INPLAY":
        sel = base & (c["rv5"] > 0)
        rk = c.loc[sel].groupby("date")["rv5"].rank(ascending=False, method="first")
        sel = sel & c.index.isin(rk.index[rk <= g["top"]])
    else:
        raise KeyError(family)
    return c.index[sel.to_numpy()]


def trade(store: Store, family: str, g: dict, k: int) -> dict | None:
    """The trade of one configuration on one candidate, or None."""
    cd = store.cands.loc[k]
    b = store.bars(k)
    if len(b[0]) < 10:
        return None
    line = vwap(b[4], b[5], b[6])
    side, prio = 1, float(cd["gap"])
    if family in ("A1_GAPGO", "A4_DAY2", "A5_LOWFLOAT", "A7_GAPDOWN"):
        j, entry, stop = entry_orb(b, g["orb"], 1)
        mode = g["exit"]
    elif family == "A2_PMHIGH":
        j, entry, stop = entry_pmhigh(b, float(cd["pmh"]), float(cd["pml30"]))
        mode = g["exit"]
    elif family == "A3_VWAPPB":
        j, entry, stop = entry_vwap_pullback(b, line)
        mode = g["exit"]
    elif family == "A6_HALTUP":
        j, entry, stop = entry_halt(b, g["rise"])
        mode = g["exit"]
    elif family == "B8_GAPFADE":
        side, mode = -1, g["exit"]
        if g["entry"] == "vwaploss":
            j, entry, stop = entry_vwap_loss(b, line)
        else:
            j, entry, stop = entry_orb(b, 5 if g["entry"] == "orl5" else 15, -1)
            if j > 0:
                stop = float(b[2][:j].max())  # the session high so far
    elif family == "B9_LATEFADE":
        side, mode = -1, "close"
        j = entry_at(b, g["at"])
        if j < 1:
            return None
        entry = float(b[1][j])
        pc = float(cd["pc"])
        if entry < pc * (1 + g["up"]) or (g["below_vwap"] and not entry < line[j - 1]):
            return None
        stop = float(b[2][:j].max())
        prio = entry / pc - 1
    elif family == "C15_INPLAY":
        m, o, c = b[0], b[1], b[4]
        _, _, first = opening_range(m, b[2], b[3], g["orb"])
        if first == 0:
            return None
        d = np.sign(c[first - 1] - o[0])
        if d == 0 or (g["sides"] == "long" and d < 0):
            return None
        side = int(d)
        j, entry, opp = entry_orb(b, g["orb"], side)
        if j < 0:
            return None
        atr = float(cd["atr14"])
        stop = {"atr10": entry - side * 0.10 * atr, "atr25": entry - side * 0.25 * atr, "bar": opp}[g["stop"]]
        mode, prio = "close", float(cd["rv5"])
    else:
        raise KeyError(family)
    if j < 0 or not np.isfinite(entry) or not np.isfinite(stop) or (stop - entry) * side >= 0:
        return None
    if side < 0:
        j, entry = _ssr_fill(j, b, float(cd["pc"]), entry)
        if j < 0 or (stop - entry) * side >= 0:
            return None
    ex, _ = run_exit(side, j, entry, stop, mode, b, line)
    return _row(cd, side, j, entry, stop, ex, b, prio)


def placebo_trade(store: Store, real: dict, k: int, mode: str) -> dict | None:
    """The placebo of one real trade: same minute, side, stop distance and exit rule, on candidate ``k``."""
    cd = store.cands.loc[k]
    b = store.bars(k)
    if len(b[0]) < 10:
        return None
    j = int(np.searchsorted(b[0], real["minute"]))
    if j >= len(b[0]) or b[0][j] > LAST_ENTRY + 30:
        return None
    entry = float(b[1][j])
    dist = abs(real["entry"] - real["stop"]) / real["entry"]
    side = real["side"]
    stop = entry * (1 - side * dist)
    ex, _ = run_exit(side, j, entry, stop, mode, b, vwap(b[4], b[5], b[6]), same_bar=False)
    return _row(cd, side, j, entry, stop, ex, b, real["prio"])


def family_trades(store: Store, family: str, g: dict) -> pd.DataFrame:
    rows = [t for k in candidates(store, family, g) if (t := trade(store, family, g, k)) is not None]
    cols = ["date", "symbol", "minute", "side", "entry", "exit", "stop", "price", "liq", "prio", "nights", "so"]
    return pd.DataFrame(rows, columns=cols)


def pool_by_day(store: Store, family: str) -> dict:
    p = pool(store, family).to_numpy()
    idx = store.cands.index[p]
    days = store.cands.loc[p, "date"].to_numpy()
    out: dict = {}
    for k, d in zip(idx, days):
        out.setdefault(pd.Timestamp(d), []).append(k)
    return out


def placebo(store: Store, family: str, g: dict, real: pd.DataFrame, rng: np.random.Generator,
            by_day: dict | None = None) -> pd.DataFrame:
    """Each real trade moved to a random candidate of the family's pool on the same day."""
    if real.empty:
        return real
    mode = g.get("exit", "close")
    by_day = by_day if by_day is not None else pool_by_day(store, family)
    rows = []
    for _, r in real.iterrows():
        choices = by_day.get(pd.Timestamp(r["date"]), [])
        if not choices:
            continue
        t = placebo_trade(store, r.to_dict(), int(rng.choice(choices)), mode)
        if t is not None:
            rows.append(t)
    return pd.DataFrame(rows, columns=real.columns)


# ---------------------------------------------------------------- index windows (C16, C17)

INDEX_DIMS = {
    "C16_IDXMOM": {"inst": ("SPY", "QQQ", "IWM", "MIX"), "thr": (0.0, 0.0025, 0.005)},
    "C16_NOISE": {"inst": ("SPY", "QQQ"), "every": (30, 60)},
    "C17_LETFFLOW": {"inst": ("SPY", "QQQ"), "thr": (0.005, 0.01, 0.02)},
}
ETF_COST = 0.0002


def _price_at(m: np.ndarray, x: np.ndarray, minute: int) -> float:
    j = int(np.searchsorted(m, minute, side="right")) - 1
    return float(x[j]) if j >= 0 else np.nan


def _window(m: np.ndarray, o: np.ndarray, c: np.ndarray, start_minute: int) -> float:
    j = int(np.searchsorted(m, start_minute))
    return float(c[-1]) / float(o[j]) - 1 if j < len(m) and o[j] > 0 else 0.0


def index_signal(bars: tuple, pc: float, family: str, g: dict) -> tuple[float, float]:
    """C16_IDXMOM and C17_LETFFLOW: (direction, gross return of 15:30-16:00) for one instrument-day."""
    m, o, c = bars[0], bars[1], bars[4]
    if len(m) < 300 or not np.isfinite(pc) or pc <= 0:
        return 0.0, 0.0
    at = 29 if family == "C16_IDXMOM" else 359
    r = _price_at(m, c, at) / pc - 1
    d = float(np.sign(r)) if abs(r) > g["thr"] else 0.0
    return d, _window(m, o, c, 360)


def noise_day(bars: tuple, hist: list[np.ndarray], every: int) -> float:
    """C16_NOISE: net return of one day of the noise-area breakout (long above the upper band, short below the
    lower one, held while beyond the band and VWAP, checked every ``every`` minutes, flat at the close)."""
    m, o, c = bars[0], bars[1], bars[4]
    if len(m) < 300 or len(hist) < 14:
        return 0.0
    sigma = np.nanmean(np.vstack(hist[-14:]), axis=0)
    op = float(o[0])
    line = vwap(c, bars[5], bars[6])
    pos, total, last_px = 0.0, 0.0, None
    for t in range(30, 390, every):
        px = _price_at(m, c, t)
        if not np.isfinite(px):
            continue
        if last_px is not None and pos != 0:
            total += pos * (px / last_px - 1)
        ub, lb, vwp = op * (1 + sigma[t]), op * (1 - sigma[t]), _price_at(m, line, t)
        if px > ub and px > vwp:
            new = 1.0
        elif px < lb and px < vwp:
            new = -1.0
        else:
            new = 0.0
        total -= ETF_COST * abs(new - pos)
        pos, last_px = new, px
    if pos != 0 and last_px:
        total += pos * (float(c[-1]) / last_px - 1) - ETF_COST * abs(pos)
    return total


def move_profile(bars: tuple) -> np.ndarray:
    """|close at each minute / open - 1| for the noise-area bands."""
    m, o, c = bars[0], bars[1], bars[4]
    out = np.full(390, np.nan)
    if len(m) == 0:
        return out
    idx = np.searchsorted(m, np.arange(390), side="right") - 1
    ok = idx >= 0
    out[ok] = np.abs(c[idx[ok]] / o[0] - 1)
    return out
