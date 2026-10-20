"""v18: small caps, wide. Pre-registered in docs/research/V18_PREREGISTRATION.md.

Every intraday family is a selection on the v14 candidates (``store.cands``, with the v16-v18 flags) and an entry
rule on the minute bars returning (side, entry bar, entry price, stop, exit mode); trades are costed with v15's
R1 book. Daily families build ``v14_swing.Spec`` lists for v16's R1 daily book; weekly families have their own book.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from aurora.research import v14_core as core
from aurora.research import v14_intraday as vi
from aurora.research import v14_swing as vs
from aurora.research import v15_ah as v15
from aurora.research import v16_small as v16

BANDS = ("low", "high")
NONE = (0, -1, np.nan, np.nan, "close")
CATALYSTS = ("none", "1.01", "8.01", "2.02", "7.01", "other")

INTRA_DIMS = {
    "F1_TIMEFADE": {"gap": (0.30, 0.50), "minute": (5, 15, 30, 60), "band": BANDS},
    "F2_VWAPREJECT": {"gap": (0.30, 0.50), "before": (90, 330), "band": BANDS},
    "F3_ORLMULTI": {"gap": (0.20, 0.40), "k": (5, 15, 30, 60), "band": BANDS},
    "F4_HODFAIL": {"gap": (0.20, 0.40), "after": (60, 150), "band": BANDS},
    "F5_EXTFADE": {"ext": (0.20, 0.30, 0.50), "exit": ("vwaptouch", "close"), "band": BANDS},
    "F6_CLOSEFADE": {"up": (0.50, 1.00), "at": (330, 360), "band": BANDS},
    "F7_PMFADEOPEN": {"gap": (0.30, 0.60), "drop": (0.10, 0.20), "band": BANDS},
    "F9_CATALYST": {"cat": CATALYSTS, "band": BANDS},
    "F10_FLOATROT": {"rot": (1.0, 3.0), "exit": ("close", "vwap"), "band": BANDS},
    "F11_REPEAT": {"runs": (2, 3), "pmv": (250e3, 1e6), "band": BANDS},
    "F12_SRFADE": {"sr": ("hi", "lo"), "band": BANDS},
    "F13_OFFFADE": {"off": ("hi", "lo"), "band": BANDS},
    "F14_DILUTIONFADE": {"dil": ("shelf30", "offer", "neither"), "band": BANDS},
    "F15_HALTFADE": {"rise": (0.10, 0.20), "band": BANDS},
    "F16_OPENDRIVE": {"gap": (0.30, 0.50), "drop": (0.02, 0.05), "band": BANDS},
    "F17_GAPFILL": {"exit": ("fill", "close"), "news": ("none", "any"), "band": BANDS},
    "F18_AFTERNOONFADE": {"gap": (0.30, 0.50), "band": BANDS},
    "F19_SECONDPUSH": {"gap": (0.30, 0.50), "band": BANDS},
    "F20_HOTPREMARKET": {"pmv": (1e6, 5e6), "band": BANDS},
    "F21_LOWFLOAT": {"so": (5e6, 10e6), "exit": ("close", "vwap"), "band": BANDS},
    "G1_DIPVWAP": {"gap": (0.30, 0.50), "after": (60, 150), "band": BANDS},
    "G2_RECLAIM": {"gap": (0.30, 0.50), "after": (90, 180), "band": BANDS},
    "G3_GAPDOWNREV": {"gap": (-0.20, -0.35), "k": (15, 30), "band": BANDS},
    "G4_PANICBUY": {"drop": (0.30, 0.50), "exit": ("vwap", "close"), "band": BANDS},
    "G5_EARNGO": {"gap": (0.10, 0.20), "exit": ("close", "vwap"), "band": BANDS},
    "G6_INVERTED": {"rule": ("a2", "a4", "l3", "l4"), "set": (0, 1), "band": BANDS},
    "G7_HODRECLAIM": {"drop": (0.20, 0.30), "after": (210, 270), "band": BANDS},
    "G8_LATEPUSH": {"gap": (0.30, 0.50), "band": BANDS},
    "G9_FIRSTPULLBACK": {"gap": (0.20, 0.40), "exit": ("close", "vwap"), "band": BANDS},
}
DAILY_DIMS = {
    "H1_STRONGCLOSE": {"up": (0.30, 0.50), "top": (0.10, 0.25), "band": BANDS},
    "H2_FADEOVERNIGHT": {"gap": (0.30, 0.50), "drop": (0.10, 0.20), "band": BANDS},
    "W1_FADEGRID": {"rise": (1.0, 2.0, 3.0), "hold": (3, 10), "stop": (0.5, np.nan)},
    "W2_SUPERNOVA": {"rise": (3.0, 5.0), "hold": (10, 20)},
    "W3_RSPLITLONG": {"ratio": (5, 10), "hold": (5, 20)},
    "W4_DEFICLONG": {"hold": (20, 60)},
    "W5_OFFERBOUNCE": {"fall": (0.20, 0.30), "hold": (3, 10)},
    "W6_CRASHBOUNCE": {"news": ("none", "any"), "hold": (3, 10)},
    "W9_OFFSPIKE": {"off": (0.70, 0.80), "up": (0.20, 0.50)},
    "W14_OFFERDAYSHORT": {"gap": (-0.10, -0.20), "band": BANDS},
    "W16_EARNDRIFT": {"side": ("up", "down"), "band": BANDS},
}
WEEKLY_DIMS = {
    "W7_LOTTERYSHORT": {"price": (1.0, 3.0), "weeks": (1, 2)},
    "W8_SRWEEKLY": {"sides": ("long", "ls"), "price": (1.0, 3.0)},
}
MACRO_DIMS = {"W11_IWMTOM": {"before": (1, 4)}}
G6_SET = {"a2": ("gap", (0.20, 0.40)), "a4": ("day1", (0.50, 1.00)), "l3": ("within", (30, 120)),
          "l4": ("gap", (0.20, 0.40))}


# ---------------------------------------------------------------- selection

def band_of(price: pd.Series, band: str) -> pd.Series:
    return (price >= 1) & (price < 5) if band == "low" else (price >= 5) & (price <= 20)


def scope(store: vi.Store, family: str, band: str | None = None) -> pd.Series:
    c = store.cands
    price = band_of(c["open"], band) if band else (c["open"] >= 1) & (c["open"] <= 20)
    if family == "G3_GAPDOWNREV":
        return price & c["s_gap_down"]
    if family == "G6_INVERTED":
        return price & (c["s_gap_up"] | c["s_day2"])
    if family in ("F5_EXTFADE", "F6_CLOSEFADE", "F15_HALTFADE", "G4_PANICBUY"):
        return price & (c["s_gap_up"] | c["s_runner"])
    if family == "G5_EARNGO":
        return price & (c["s_gap_up"] | c["s_gap_down"] | c["s_in_play"])
    return price & c["s_gap_up"]


def candidates(store: vi.Store, family: str, g: dict) -> pd.Index:
    c = store.cands
    s = scope(store, family, g.get("band"))
    gap, news = c["gap"], c["news"]
    if family in ("F1_TIMEFADE", "F2_VWAPREJECT", "F4_HODFAIL", "F16_OPENDRIVE", "F18_AFTERNOONFADE",
                  "F19_SECONDPUSH", "G1_DIPVWAP", "G2_RECLAIM", "G8_LATEPUSH", "G9_FIRSTPULLBACK"):
        s &= gap >= g["gap"]
    elif family == "F3_ORLMULTI":
        s &= (gap >= g["gap"]) & ~news
    elif family == "F7_PMFADEOPEN":
        s &= (gap >= g["gap"]) & (c["open"] <= c["pmh"] * (1 - g["drop"]))
    elif family == "F9_CATALYST":
        s &= (gap >= 0.30) & (c["catalyst"] == g["cat"])
    elif family == "F10_FLOATROT":
        s &= (gap >= 0.30) & np.isfinite(c["so"])
    elif family == "F11_REPEAT":
        s &= (gap >= 0.30) & (c["runs60"] >= g["runs"]) & (c["pmv"] >= g["pmv"])
    elif family == "F12_SRFADE":
        s &= (gap >= 0.30) & ((c["sr_prev"] >= 0.6) if g["sr"] == "hi" else (c["sr_prev"] <= 0.4))
    elif family == "F13_OFFFADE":
        s &= (gap >= 0.30) & ((c["off_prev"] >= 0.6) if g["off"] == "hi" else (c["off_prev"] <= 0.4))
    elif family == "F14_DILUTIONFADE":
        flag = {"shelf30": c["shelf30"], "offer": c["offer"], "neither": ~c["shelf30"] & ~c["offer"]}[g["dil"]]
        s &= (gap >= 0.30) & flag
    elif family == "F17_GAPFILL":
        s &= (gap >= 0.15) & (gap < 0.30)
        if g["news"] == "none":
            s &= ~news
    elif family == "F20_HOTPREMARKET":
        s &= (gap >= 0.30) & (c["pmv"] >= g["pmv"])
    elif family == "F21_LOWFLOAT":
        s &= (gap >= 0.50) & (c["so"] < g["so"])
    elif family == "G3_GAPDOWNREV":
        s &= (gap <= g["gap"]) & ~news
    elif family == "G5_EARNGO":
        s &= c["earn"] & (gap.abs() >= g["gap"])
    elif family == "G6_INVERTED":
        name, values = G6_SET[g["rule"]]
        v = values[g["set"]]
        if g["rule"] in ("a2", "l4"):
            s &= c["s_gap_up"] & (gap >= v) & (c["pmv"] >= 250e3)
        elif g["rule"] == "a4":
            s &= c["s_day2"] & (c["day1"] >= v) & (c["day1_loc"] >= 0.75)
        else:
            s &= c["s_day2"] & (c["open"] < c["pc"])
    elif family == "G7_HODRECLAIM":
        s &= gap >= 0.20
    return c.index[s.to_numpy()]


# ---------------------------------------------------------------- entries

def _orl(b: tuple, k: int):
    j, entry, _ = vi.entry_orb(b, k, -1)
    return (-1, j, entry, float(b[2][:j].max()), "close") if j > 0 else NONE


def _at(m: np.ndarray, minute: int) -> int:
    j = int(np.searchsorted(m, minute))
    return j if j < len(m) and m[j] <= minute + 5 else -1


def _flip(res: tuple) -> tuple:
    side, j, entry, stop, _ = res
    if j < 0 or side <= 0 or not stop < entry:
        return NONE
    return -1, j, entry, entry * (2 - stop / entry), "close"


def entry(family: str, g: dict, b: tuple, cd: pd.Series, line: np.ndarray) -> tuple:
    m, o, h, lo, c, v = b[0], b[1], b[2], b[3], b[4], b[5]
    last = vi.LAST_ENTRY
    if family in ("F9_CATALYST", "F11_REPEAT", "F12_SRFADE", "F13_OFFFADE", "F14_DILUTIONFADE", "F20_HOTPREMARKET"):
        return _orl(b, 5)
    if family == "F21_LOWFLOAT":
        r = _orl(b, 5)
        return r[:4] + (g["exit"],) if r[1] >= 0 else NONE
    if family == "F3_ORLMULTI":
        return _orl(b, g["k"])
    if family == "F10_FLOATROT":
        r = _orl(b, 5)
        if r[1] < 0 or float(v[:r[1]].sum()) < g["rot"] * float(cd["so"]):
            return NONE
        return r[:4] + (g["exit"],)
    if family == "F1_TIMEFADE":
        j = _at(m, g["minute"])
        if j < 1 or not o[j] < line[j - 1]:
            return NONE
        return -1, j, float(o[j]), float(h[:j].max()), "close"
    if family == "F2_VWAPREJECT":
        below = vi.first_true((c < line) & (m >= 5), 0)
        if below < 0:
            return NONE
        j = vi.first_true((h >= line) & (c < line) & (m <= g["before"]), below + 1)
        return (-1, j, float(c[j]), float(h[:j + 1].max()), "close") if j >= 0 else NONE
    if family == "F4_HODFAIL":
        runmax = np.maximum.accumulate(h)
        prev = np.r_[-np.inf, runmax[:-1]]
        j0 = vi.first_true((m >= g["after"]) & (m <= last) & (h > prev), 1)
        if j0 < 0:
            return NONE
        for j in range(max(j0 + 1, 5), len(c)):
            if m[j] > last:
                break
            if c[j] < lo[j - 5:j].min():
                return -1, j, float(c[j]), float(h[:j + 1].max()), "close"
        return NONE
    if family == "F5_EXTFADE":
        return v16._entry("S4_PARABOLIC", {"ext": g["ext"], "exit": g["exit"]}, b, line, cd)
    if family == "F6_CLOSEFADE":
        j = _at(m, g["at"])
        if j < 1 or o[j] < float(cd["pc"]) * (1 + g["up"]) or not o[j] < line[j - 1]:
            return NONE
        return -1, j, float(o[j]), float(h[:j].max()), "close"
    if family == "F7_PMFADEOPEN":
        return -1, 0, float(o[0]), float(cd["pmh"]), "close"
    if family == "F15_HALTFADE":
        r = vi.entry_halt(b, g["rise"])
        if r[0] < 0:
            return NONE
        k = r[0]
        for j in range(k + 1, len(c)):
            if m[j] > last:
                break
            if h[j] < h[j - 1] and c[j] < o[j]:
                return -1, j, float(c[j]), float(h[max(k - 5, 0):j + 1].max()), "close"
        return NONE
    if family == "F16_OPENDRIVE":
        if not c[0] <= o[0] * (1 - g["drop"]):
            return NONE
        j = vi.first_true((lo < lo[0]) & (m <= last), 1)
        return (-1, j, min(float(lo[0]), float(o[j])), float(h[0]), "close") if j >= 0 else NONE
    if family == "F17_GAPFILL":
        r = _orl(b, 15)
        return r[:4] + (g["exit"],) if r[1] >= 0 else NONE
    if family == "F18_AFTERNOONFADE":
        k0, k1 = int(np.searchsorted(m, 210)), int(np.searchsorted(m, 240))
        if k0 < 1 or k1 <= k0 or k1 >= len(m) or not c[k0 - 1] > o[0]:
            return NONE
        rl, rh = float(lo[k0:k1].min()), float(h[k0:k1].max())
        j = vi.first_true((lo < rl) & (m <= last), k1)
        return (-1, j, min(rl, float(o[j])), rh, "close") if j >= 0 else NONE
    if family == "F19_SECONDPUSH":
        _, lo5, first = vi.opening_range(m, h, lo, 5)
        if first == 0:
            return NONE
        j1 = vi.first_true(lo < lo5, first)
        j2 = vi.first_true(c > lo5, j1 + 1) if j1 >= 0 else -1
        j3 = vi.first_true((lo < lo5) & (m <= last), j2 + 1) if j2 >= 0 else -1
        return (-1, j3, min(lo5, float(o[j3])), float(h[:j3].max()), "close") if j3 > 0 else NONE
    if family == "G1_DIPVWAP":
        for j in range(4, len(c)):
            if m[j] > last:
                break
            if m[j] >= g["after"] and lo[j] <= line[j] < c[j] and (c[j - 3:j] > line[j - 3:j]).all():
                return 1, j, float(c[j]), float(lo[:j + 1].min()), "close"
        return NONE
    if family == "G2_RECLAIM":
        was_below = np.maximum.accumulate(c < line)
        for j in range(3, len(c)):
            if m[j] > last:
                break
            if m[j] >= g["after"] and was_below[j - 3] and (c[j - 2:j + 1] > line[j - 2:j + 1]).all():
                return 1, j, float(c[j]), float(lo[:j + 1].min()), "close"
        return NONE
    if family == "G3_GAPDOWNREV":
        j, e, stop = vi.entry_orb(b, g["k"], 1)
        return (1, j, e, stop, "close") if j >= 0 else NONE
    if family == "G4_PANICBUY":
        runmax = np.maximum.accumulate(h)
        hi_at = np.maximum.accumulate(np.where(h >= runmax, np.arange(len(h)), 0))  # bar of the high so far
        for j in range(1, len(c)):
            if m[j] > last:
                break
            if lo[j] <= runmax[j] * (1 - g["drop"]) and m[j] - m[hi_at[j]] <= 30:
                for k in range(j + 1, len(c)):
                    if m[k] > last:
                        break
                    if c[k] > h[k - 1]:
                        return 1, k, float(c[k]), float(lo[j:k + 1].min()), g["exit"]
                return NONE
        return NONE
    if family == "G5_EARNGO":
        side = 1 if cd["gap"] > 0 else -1
        j, e, stop = vi.entry_orb(b, 5, side)
        return (side, j, e, stop, g["exit"]) if j >= 0 else NONE
    if family == "G6_INVERTED":
        rule, val = g["rule"], G6_SET[g["rule"]][1][g["set"]]
        if rule == "a2":
            j, e, stop = vi.entry_pmhigh(b, float(cd["pmh"]), float(cd["pml30"]))
            return _flip((1, j, e, stop, "close"))
        if rule == "a4":
            j, e, stop = vi.entry_orb(b, 5, 1)
            return _flip((1, j, e, stop, "close"))
        if rule == "l3":
            return _flip(v16._entry("L3_R2G", {"within": val, "exit": "close"}, b, line, cd))
        return _flip(v16._entry("L4_MICROPB", {"gap": val, "exit": "close"}, b, line, cd))
    if family == "G7_HODRECLAIM":
        k = int(np.searchsorted(m, g["after"]))
        if k < 2 or k >= len(m):
            return NONE
        hod_i = int(np.argmax(h[:k]))
        hod = float(h[hod_i])
        if lo[hod_i:k].min() > hod * (1 - g["drop"]):
            return NONE
        j = vi.first_true((h > hod) & (m <= 360), k)
        if j < 1:
            return NONE
        e, stop = max(hod, float(o[j])), float(line[j - 1])
        return (1, j, e, stop, "close") if stop < e else NONE
    if family == "G8_LATEPUSH":
        j = _at(m, 330)
        if j < 1:
            return NONE
        px = float(o[j])
        if not (px > line[j - 1] and px >= 0.95 * float(h[:j].max())):
            return NONE
        return 1, j, px, float(line[j - 1]), "close"
    if family == "G9_FIRSTPULLBACK":
        for j in range(3, len(c)):
            if m[j] > 15:
                break
            if h[j - 2] >= h[:j - 1].max() and c[j - 1] < o[j - 1] and h[j] > h[j - 1]:
                return 1, j, max(float(h[j - 1]), float(o[j])), float(lo[j - 1]), g["exit"]
        return NONE
    raise KeyError(family)


def exit18(side: int, j: int, e: float, stop: float, mode: str, b: tuple, line: np.ndarray, pc: float) -> float:
    if mode != "fill":
        return v16.exit16(side, j, e, stop, mode, b, line)
    h, lo = b[2], b[3]
    hit = vi.first_true((h >= stop) if side < 0 else (lo <= stop), j)
    fill = vi.first_true((lo <= pc) if side < 0 else (h >= pc), j + 1)
    if hit >= 0 and (fill < 0 or hit <= fill):
        return v16.exit16(side, j, e, stop, "close", b, line)
    return float(pc) if fill >= 0 else float(b[4][-1])


def intraday_trades(store: vi.Store, family: str, g: dict) -> pd.DataFrame:
    rows = []
    for k in candidates(store, family, g):
        cd = store.cands.loc[k]
        b = store.bars(k)
        if len(b[0]) < 10:
            continue
        line = vi.vwap(b[4], b[5], b[6])
        side, j, e, stop, mode = entry(family, g, b, cd, line)
        if j < 0 or not np.isfinite(e) or not np.isfinite(stop) or (stop - e) * side >= 0:
            continue
        if side < 0:
            j, e = vi._ssr_fill(j, b, float(cd["pc"]), e)
            if j < 0 or (stop - e) * side >= 0:
                continue
        ex = exit18(side, j, e, stop, mode, b, line, float(cd["pc"]))
        r = vi._row(cd, side, j, e, stop, ex, b, abs(float(cd["gap"])))
        r["mode"], r["pc"] = mode, float(cd["pc"])
        rows.append(r)
    cols = ["date", "symbol", "minute", "side", "entry", "exit", "stop", "price", "liq", "prio", "nights", "so",
            "mode", "pc"]
    return pd.DataFrame(rows, columns=cols)


def intraday_placebo(store: vi.Store, real: pd.DataFrame, rng: np.random.Generator, by_day: dict) -> pd.DataFrame:
    rows = []
    for _, r in real.iterrows():
        ch = by_day.get(pd.Timestamp(r["date"]), [])
        if not ch:
            continue
        k = int(rng.choice(ch))
        cd = store.cands.loc[k]
        b = store.bars(k)
        if len(b[0]) < 10:
            continue
        j = int(np.searchsorted(b[0], r["minute"]))
        if j >= len(b[0]) or b[0][j] > vi.LAST_ENTRY + 30:
            continue
        e = float(b[1][j])
        dist = abs(r["entry"] - r["stop"]) / r["entry"]
        stop = e * (1 - r["side"] * dist)
        ex = exit18(int(r["side"]), j, e, stop, r["mode"], b, vi.vwap(b[4], b[5], b[6]), float(cd["pc"]))
        row = vi._row(cd, int(r["side"]), j, e, stop, ex, b, float(r["prio"]))
        row["mode"], row["pc"] = r["mode"], float(cd["pc"])
        rows.append(row)
    return pd.DataFrame(rows, columns=real.columns)


def pool_by_day(store: vi.Store, family: str, band: str | None) -> dict:
    s = scope(store, family, band).to_numpy()
    out: dict = {}
    for k, d in zip(store.cands.index[s], store.cands.loc[s, "date"]):
        out.setdefault(pd.Timestamp(d), []).append(k)
    return out


def book(trades: pd.DataFrame, dates: pd.DatetimeIndex, table: dict, spread: float, gross: bool = False) -> pd.Series:
    """v15's R1 intraday book; ``gross`` drops every cost (the availability weights stay)."""
    tv = v15._v15_cols(trades)
    if not gross:
        return v15.book(tv, dates, table, spread, fixed=False)
    keep = core.COMMISSION
    try:
        core.COMMISSION = 0.0
        return v15.book(tv, dates, table, 0.0, fixed=False)
    finally:
        core.COMMISSION = keep


# ---------------------------------------------------------------- daily

def _band_arr(P: np.ndarray, band: str | None) -> np.ndarray:
    if band is None:
        return (P >= 1) & (P <= 20)
    return (P >= 1) & (P < 5) if band == "low" else (P >= 5) & (P <= 20)


def daily_specs(D: dict, E: dict, family: str, g: dict) -> tuple[list, float, int]:
    O, H, L, C, P = D["O"], D["H"], D["L"], D["C"], D["P"]
    T = C.shape[0]
    prev = np.vstack([np.full((1, C.shape[1]), np.nan), C[:-1]])
    r1 = C / prev - 1
    gap = O / prev - 1
    base = (D["DV"] >= 1e6) & D["valid"]
    out = []

    def add(mask, side, kind, hold, stop, prio, shift=1):
        for t, j in zip(*np.nonzero(mask)):
            tt = t + shift if kind != "close" else t
            if tt < T:
                out.append(vs.Spec(int(j), int(tt), kind, side, hold, stop, float(prio[t, j])))

    with np.errstate(invalid="ignore", divide="ignore"):
        if family == "H1_STRONGCLOSE":
            loc = (C - L) / np.maximum(H - L, 1e-9)
            add((r1 >= g["up"]) & (loc >= 1 - g["top"]) & _band_arr(P, g["band"]) & base, 1, "close", 2, np.nan, r1)
            return out, 0.05, 20
        if family == "H2_FADEOVERNIGHT":
            add((gap >= g["gap"]) & (C <= O * (1 - g["drop"])) & _band_arr(P, g["band"]) & base, -1, "close", 2,
                np.nan, gap)
            return out, 0.05, 20
        if family == "W1_FADEGRID":
            low5 = np.fmin.reduce([np.vstack([np.full((k, C.shape[1]), np.nan), C[:-k]]) for k in range(2, 7)])
            rise = prev / low5 - 1
            prevL = np.vstack([np.full((1, C.shape[1]), np.nan), L[:-1]])
            cond = (rise >= g["rise"]) & (C < prevL) & _band_arr(P, None) & base
            t, j = np.nonzero(cond)
            keep = vs._once(t, j)
            for tt, jj in zip(t[keep], j[keep]):
                if tt + 1 < T:
                    out.append(vs.Spec(int(jj), int(tt + 1), "open", -1, g["hold"], g["stop"], float(rise[tt, jj])))
            return out, 0.05, 20
        if family == "W2_SUPERNOVA":
            low20 = pd.DataFrame(C).rolling(20, min_periods=10).min().to_numpy()
            cond = (C / low20 - 1 >= g["rise"]) & _band_arr(P, None) & base
            t, j = np.nonzero(cond)
            keep = vs._once(t, j, 20)
            for tt, jj in zip(t[keep], j[keep]):
                if tt + 1 < T:
                    out.append(vs.Spec(int(jj), int(tt + 1), "open", -1, g["hold"], np.nan, 0.0))
            return out, 0.05, 20
        if family == "W3_RSPLITLONG":
            for t, j, ratio in E["rsplit"]:
                if ratio >= g["ratio"] and t < T:
                    out.append(vs.Spec(int(j), int(t), "open", 1, g["hold"], np.nan, float(ratio)))
            return out, 0.02, 40
        if family == "W4_DEFICLONG":
            ev = D["events"]["delist"]
            for t, j in zip(ev["t"].to_numpy(), ev["j"].to_numpy()):
                if t < T:
                    out.append(vs.Spec(int(j), int(t), "open", 1, g["hold"], np.nan, 0.0))
            return out, 0.02, 40
        if family == "W5_OFFERBOUNCE":
            add(E["OFFER"] & (r1 <= -g["fall"]) & _band_arr(P, None) & base, 1, "open", g["hold"], np.nan, -r1)
            return out, 0.05, 20
        if family == "W6_CRASHBOUNCE":
            news = ~E["NEWS"] if g["news"] == "none" else np.ones_like(E["NEWS"])
            add((r1 <= -0.30) & news & _band_arr(P, None) & base, 1, "open", g["hold"], np.nan, -r1)
            return out, 0.05, 20
        if family == "W9_OFFSPIKE":
            add((E["OFF"] >= g["off"]) & (r1 >= g["up"]) & _band_arr(P, None) & base, -1, "open", 3, 0.5, r1)
            return out, 0.05, 20
        if family == "W14_OFFERDAYSHORT":
            add(E["OFFER"] & (gap <= g["gap"]) & _band_arr(P, g["band"]) & base, -1, "open", 1, np.nan, -gap, shift=0)
            return out, 0.05, 20
        if family == "W16_EARNDRIFT":
            side = 1 if g["side"] == "up" else -1
            cond = E["EARN"] & ((gap >= 0.10) if side > 0 else (gap <= -0.10)) & _band_arr(P, g["band"]) & base
            add(cond, side, "open", 5, np.nan, np.abs(gap), shift=0)
            return out, 0.05, 20
    raise KeyError(family)


def weekly(D: dict, E: dict, family: str, g: dict, table: dict, spread: float,
           rng: np.random.Generator | None = None) -> pd.Series:
    C, P, dates = D["C"], D["P"], D["dates"]
    r1 = np.vstack([np.full((1, C.shape[1]), np.nan), C[1:] / C[:-1] - 1])
    wk = pd.Series(np.arange(len(dates)), index=dates).groupby(dates.to_period("W")).max().to_numpy()
    step = g.get("weeks", 1)
    out = np.zeros(len(dates))
    for n in range(0, len(wk) - step, step):
        a, b = wk[n], wk[n + step]
        uni = (P[a] >= g["price"]) & (P[a] <= 20) & (D["DV"][a] >= 1e6) & D["valid"][a]
        if family == "W7_LOTTERYSHORT":
            mx = np.nanmax(r1[max(a - 20, 0):a + 1], axis=0)
            ok = uni & np.isfinite(mx)
            if ok.sum() < 50:
                continue
            idx = np.flatnonzero(ok)
            order = idx[np.argsort(mx[idx])]
            longs, shorts = order[:0], order[-max(1, len(order) // 10):][-20:]
        else:
            sr = E["SR5"][a]
            ok = uni & np.isfinite(sr)
            if ok.sum() < 50:
                continue
            idx = np.flatnonzero(ok)
            order = idx[np.argsort(sr[idx])]
            k = max(1, len(order) // 10)
            longs, shorts = order[:k][:20], (order[-k:][-20:] if g["sides"] == "ls" else order[:0])
        if rng is not None:
            longs = rng.choice(idx, len(longs), replace=False) if len(longs) else longs
            shorts = rng.choice(idx, len(shorts), replace=False) if len(shorts) else shorts
        for side, names in ((1, longs), (-1, shorts)):
            if not len(names):
                continue
            px = np.maximum(P[a, names], 0.01)
            cost = 2 * (core.half_spread(px, "mid") * spread + core.COMMISSION / px)
            w = np.full(len(names), 0.05)
            if side < 0:
                pav, fee = v15.lookup(table, px, D["SO"][a, names])
                w = w * pav
                cost = cost + fee / 100 / 360 * 7 * step
            rr = np.nan_to_num(r1[a + 1:b + 1][:, names], nan=0.0)
            out[a + 1:b + 1] += side * (rr * w).sum(axis=1)
            out[a + 1] -= float((w * cost).sum())
    return pd.Series(out, index=dates)


def iwm_tom(X: dict, g: dict, shift: int = 0) -> pd.Series:
    from aurora.research import v14_macro as vm
    pos, _ = vm.tom(X, {"before": g["before"]})
    pos = pos.rename(columns={"SPY": "IWM"})
    if shift:
        pos = vm.shift_positions(pos, shift)
    return vm.returns_from_positions(pos, X["etf_ret"][["IWM"]].reindex(pos.index), vm.ETF_COST)
