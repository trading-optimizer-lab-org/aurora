"""v24: long-only small caps on one-minute bars: supports and resistances (intraday and daily), indicators, chart
and candlestick patterns, momentum setups from the day-trading literature and new ideas. Pre-registered in
docs/research/V24_PREREGISTRATION.md.

Stores: v14's event days (scopes gapup, runner, gapdown, day2), the v23 store of the 100 most liquid small caps of
each session (liquid) and the v24 store of the 100 small caps with the largest gaps of 4% or more outside it
(mover_up, mover_dn); inplay = liquid or mover with a high relative volume over the first five minutes (known at
09:35). One trade per configuration and symbol-day: the first signal. Levels on the day's raw scale; the daily levels
(20/60/252-day highs, 20/60-day lows, 20/50/200-day averages) use the sessions before only.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from aurora.research import v14_intraday as vi
from aurora.research import v19_grid as v19
from aurora.research import v20_grid as v20
from aurora.research import v22_intra as v22i
from aurora.research import v23_ta1m as v23
from aurora.research import v24_fast as fast
from aurora.research import v24_patterns as pat

B3 = ("1-3", "3-8", "8-20")
DAILY = ("h20", "h60", "h252", "l20", "l60", "sma20d", "sma50d", "sma200d")
LONG_SETUPS = ("break_up", "fail_dn", "retest_up")
WIN3 = ("open", "midlate", "all")
NEW_SC = ("mover_up", "mover_dn", "gapdown", "day2")
MOM5 = ("gapup", "runner", "mover_up", "liquid", "day2")
IND4 = ("liquid", "mover_up", "gapup", "runner")
NONE = pat.NONE

INTRA_DIMS: dict[str, dict] = {
    "DL_DAILY": {"level": DAILY, "setup": LONG_SETUPS, "vol": (0.0, 2.0), "window": WIN3, "stop": ("lvl1", "pct10"),
                 "exit": ("r2", "nextlevel", "ema9", "close", "d3", "trail10"),
                 "scope": ("liquid", "mover_up", "mover_dn", "gapup", "runner", "gapdown"), "band": B3},
    "SR_LONG": {"level": v23.LEVELS, "setup": LONG_SETUPS, "vol": (0.0, 2.0), "window": WIN3, "stop": ("lvl1", "pct10"),
                "exit": ("r2", "nextlevel", "ema9", "close", "d3", "be1r"), "scope": NEW_SC, "band": B3},
}
V23L = {"LV_VWAP": "VW_VWAP", "LE_EMA": "EM_EMA", "LO_OSC": "OS_OSC", "LM_MACD": "MD_MACD", "LS_SQUEEZE": "SQ_SQUEEZE",
        "LP_PATTERN": "PT_PATTERN", "LC_CANDLE": "CD_CANDLE", "LX_CLIMAX": "VC_CLIMAX", "LR_ORB": "OR_ORB"}
for _key, _fam in V23L.items():  # v23's other families, long side only, on the scopes v23 did not have
    _d: dict = dict(v23.INTRA_DIMS[_fam])  # type: ignore[call-overload]
    _d["scope"] = NEW_SC
    for _k in ("side", "cside"):
        if _k in _d:
            _d[_k] = ("long",)
    if _fam == "VW_VWAP":
        _d["setup"] = ("reclaim", "bounce", "revert_lo", "break_hi")
    elif _fam == "PT_PATTERN":
        _d["pattern"] = ("double_bottom", "asc_triangle", "bull_flag")
    elif _fam == "VC_CLIMAX":
        _d["candle"] = ("lowwick", "bigup")
    INTRA_DIMS[_key] = _d
INTRA_DIMS.update({
    "SP_INPLAY": {"sel": ("top5", "top10", "top20", "rv3", "rv6"), "k": (5, 15, 30), "candle": ("green", "any"),
                  "gapdir": ("any", "up"), "stop": ("atr10", "atr25", "range"),
                  "exit": ("close", "r2", "r5", "trail10", "vwapx", "next_open"), "scope": ("inplay",), "band": B3},
    "NB_NOISE": {"k": (0.5, 1.0, 1.5, 2.0), "check": ("1m", "30m"), "filter": ("none", "vwap", "rv2"),
                 "stop": ("pct5", "pct10"), "exit": ("bound", "close", "r2", "trail10", "next_open"),
                 "scope": ("liquid", "mover_up", "gapup", "inplay"), "band": B3},
    "LH_LATE": {"up": (0.02, 0.05, 0.10, 0.20), "filter": ("none", "vwap", "hod"), "at": (270, 330, 360),
                "stop": ("pct10", "pct20"), "exit": ("close", "next_open", "d2", "d3"), "scope": IND4, "band": B3},
    "PH_POWER": {"after": (240, 270, 300), "day": (0.0, 0.05, 0.10), "vol": (0.0, 2.0), "stop": ("swing", "pct5", "pct10"),
                 "exit": ("close", "next_open", "d2", "d3", "trail5"), "scope": IND4, "band": B3},
    "MP_MICRO": {"impulse": ("m3", "m6", "m10"), "retrace": (0.33, 0.5), "vol": ("any", "dry"), "window": ("open", "all"),
                 "stop": ("pb", "pct5"), "exit": ("r2", "r3", "trail5", "trail10", "ema9", "close"), "scope": MOM5,
                 "band": B3},
    "AB_ABCD": {"run": (0.05, 0.10, 0.20), "retr": ("38-62", "24-50"), "entry": ("atC", "breakB"), "stop": ("pb", "pct10"),
                "exit": ("measured", "r2", "trail10", "close", "ema9", "d3"), "scope": MOM5, "band": B3},
    "HR_HALT": {"dir": ("up", "down"), "move": (0.08, 0.15), "entry": ("resume", "hold", "dip"),
                "stop": ("pb", "pct10", "pct20"), "exit": ("r2", "trail10", "trail20", "close", "next_open", "t15", "ema9"),
                "scope": ("gapup", "runner", "mover_up", "mover_dn", "liquid"), "band": B3},
    "MD_MORNDIP": {"drop": (0.10, 0.20, 0.30), "window": (30, 60), "trig": ("green5", "vwapre", "hl", "rsi"),
                   "stop": ("lod", "pct10"), "exit": ("r2", "openx", "trail10", "close", "next_open", "ema9"),
                   "scope": ("gapup", "runner", "day2", "mover_up", "liquid"), "band": B3},
    "RG_RED2GREEN": {"gap": (0.0, -0.02, -0.05), "after": (5, 15), "context": ("any", "red2", "up20"), "vol": (0.0, 2.0),
                     "stop": ("lod", "pct10"), "exit": ("r2", "trail10", "ema9", "close", "next_open", "d3"),
                     "scope": ("liquid", "mover_dn", "gapdown"), "band": B3},
    "GF_GAPFILL": {"gap": (-0.04, -0.08, -0.15), "trig": ("orh5", "orh15", "vwapre", "hl", "t30"), "stop": ("lod", "pct10"),
                   "exit": ("fill", "half", "close", "next_open", "d3", "r2"), "scope": ("liquid", "mover_dn", "gapdown"),
                   "band": B3},
    "D2_GO": {"day1": (0.2, 0.5, 1.0), "loc": ("any", "top20"), "trig": ("pmh", "orh5", "orh15", "vwap", "open"),
              "stop": ("lod", "pct10"), "exit": ("r2", "trail10", "close", "next_open", "d3", "ema9"),
              "scope": ("day2", "liquid", "mover_up"), "band": B3},
    "IX_IND": {"ind": fast.INDICATORS, "tf": (1, 5, 15), "filter": ("none", "vwap", "ema50"), "stop": ("swing", "pct10"),
               "exit": ("opp", "r2", "trail10", "ema9", "close", "d3"), "scope": IND4, "band": B3},
    "PX_PATTERN": {"pattern": ("inv_hs", "triple_bottom", "cup_handle", "rectangle", "pennant", "htf"),
                   "size": ("small", "large"), "after": (15, 60), "vol": (0.0, 2.0), "stop": ("pb", "pct10"),
                   "exit": ("measured", "r2", "trail10", "ema9", "close", "d3"), "scope": IND4, "band": B3},
    "CK_CANDLE": {"pattern": pat.CANDLES, "tf": (1, 5, 15), "context": ("drop", "lod", "vwap", "level", "trend"),
                  "vol": (0.0, 2.0), "stop": ("pb", "pct10"), "exit": ("r1", "r2", "trail10", "t30", "close"),
                  "scope": ("liquid", "mover_up", "mover_dn", "gapup"), "band": B3},
    "WO_WASH": {"drop": (0.10, 0.20, 0.30), "reds": (4, 7), "climax": (3.0, 6.0), "confirm": ("hh", "c3"),
                "stop": ("lod", "pct10"), "exit": ("r2", "t30", "tovwap", "trail10", "close", "next_open"),
                "scope": ("liquid", "mover_up", "mover_dn", "gapup", "runner", "gapdown"), "band": B3},
    "HG_GRAIL": {"adx": (25, 30), "tf": (1, 5), "touch": ("ema20", "ema9", "vwap"), "stop": ("pb", "pct10"),
                 "exit": ("r2", "trail10", "crossback", "close", "d3"), "scope": IND4, "band": B3},
    "TS_TREND": {"ctx": ("up", "high", "lead"), "dip": (0.03, 0.06, 0.10), "trig": ("vwapre", "green5", "rsi2", "pdc"),
                 "stop": ("lod", "pct10"), "exit": ("r2", "close", "next_open", "d3", "d5", "g5"),
                 "scope": ("liquid", "mover_dn", "mover_up"), "band": B3},
})
SPECIAL = ("be1r", "scale", "tstop15")
TARGETS = ("half", "openx")
MASKS = ("opp", "bound", "tovwap")


def base_family(family: str) -> str:
    """The v23 family whose signal and exits a v24 family reuses (SR_LONG and DL_DAILY: v23's level logic)."""
    if family in ("SR_LONG", "DL_DAILY"):
        return "SR_LEVEL"
    return V23L.get(family, family)


# ---------------------------------------------------------------- stores, facts, candidates

SCOPE_STORES = {"liquid": ("liquid",), "mover_up": ("mover",), "mover_dn": ("mover",), "inplay": ("liquid", "mover"),
                "gapup": ("event",), "runner": ("event",), "gapdown": ("event",), "day2": ("event",)}
EVENT_COL = {"gapup": "s_gap_up", "runner": "s_runner", "gapdown": "s_gap_down", "day2": "s_day2"}
KEYS = ("date", "t", "j", "symbol", "open", "pc", "gap", "pmv", "pmh", "pml", "pdh", "pdl", "h5", "l5", "so", "day1",
        "day1_loc", "atr14", "rv5", "rvrank", "ret60", "red2") + DAILY


def _trail(x: np.ndarray, w: int, kind: str) -> np.ndarray:
    """Trailing statistic of a daily column over the w sessions ending at each row (nan-aware)."""
    ok = np.isfinite(x)
    if kind == "max":
        return np.where(np.isfinite(r := fast.rmax(np.where(ok, x, -np.inf), w)), r, np.nan)
    if kind == "min":
        return np.where(np.isfinite(r := fast.rmin(np.where(ok, x, np.inf), w)), r, np.nan)
    s, cnt = fast.rsum(np.where(ok, x, 0.0), w), fast.rsum(ok.astype(float), w)
    return np.where(cnt == w, s / w, np.nan)


def prepare(stores: dict, D: dict) -> None:
    """Adds the facts of every candidate from the sessions before it (on that day's raw scale), the relative volume of
    its first five minutes and its rank among the liquid and mover candidates of the day."""
    H, L, C, F = D["H"], D["L"], D["C"], D["F"]
    for name, st in stores.items():
        c = st.cands
        t, j = c["t"].to_numpy(int), c["j"].to_numpy(int)
        out = {k: np.full(len(c), np.nan) for k in ("pdh", "pdl", "h5", "l5", "day1", "day1_loc", "atr14", "ret60",
                                                     "red2") + DAILY}
        for col, rows in c.groupby("j").indices.items():
            h, lo, cl = (np.asarray(X[:, col], float) for X in (H, L, C))
            tr = fast.true_range(h, lo, np.where(np.isfinite(cl), cl, h))
            stats = {"pdh": h, "pdl": lo, "h5": _trail(h, 5, "max"), "l5": _trail(lo, 5, "min"),
                     "h20": _trail(h, 20, "max"), "h60": _trail(h, 60, "max"), "h252": _trail(h, 252, "max"),
                     "l20": _trail(lo, 20, "min"), "l60": _trail(lo, 60, "min"), "sma20d": _trail(cl, 20, "mean"),
                     "sma50d": _trail(cl, 50, "mean"), "sma200d": _trail(cl, 200, "mean"),
                     "atr14": _trail(tr, 14, "mean")}
            tt = t[rows]
            prev = np.maximum(tt - 1, 0)
            f = F[tt, col]
            for k, arr in stats.items():
                out[k][rows] = arr[prev] / f
            c1, c2, c3 = cl[prev], cl[np.maximum(tt - 2, 0)], cl[np.maximum(tt - 3, 0)]
            with np.errstate(invalid="ignore", divide="ignore"):
                out["day1"][rows] = c1 / c2 - 1
                out["day1_loc"][rows] = (c1 - lo[prev]) / np.maximum(h[prev] - lo[prev], 1e-9)
                out["ret60"][rows] = c1 / cl[np.maximum(tt - 61, 0)] - 1
                out["red2"][rows] = ((c1 < c2) & (c2 < c3)).astype(float)
        for k, arr in out.items():
            if k in ("pdh", "pdl", "h5", "l5") and k in c and c[k].notna().all():
                continue  # the v23 and v24 stores carry these from their own build
            c[k] = arr
        if "pml" not in c:
            c["pml"] = c["pml30"]
        m, v = st.arrays["m"], np.asarray(st.arrays["v"], float)
        cs = np.r_[0.0, np.cumsum(np.where(m < 5, v, 0.0))]
        off, n = c["off"].to_numpy(int), c["n"].to_numpy(int)
        first5 = cs[off + n] - cs[off]
        dv1 = D["DV1"][t, j]
        pc = c["pc"].to_numpy(float)
        with np.errstate(invalid="ignore", divide="ignore"):
            c["rv5"] = np.where(np.isfinite(dv1) & (pc > 0), first5 / np.maximum(dv1 / pc / 78, 1.0), 0.0)
        c["rvrank"] = np.inf
    both = [(nm, stores[nm].cands) for nm in ("liquid", "mover") if nm in stores]
    if both:
        allc = pd.concat([x[["date", "rv5"]].assign(src=nm, row=np.arange(len(x))) for nm, x in both])
        rk = allc.groupby("date")["rv5"].rank(ascending=False, method="first").to_numpy() - 1
        for nm, x in both:
            s = (allc["src"] == nm).to_numpy()
            x.loc[x.index[allc["row"].to_numpy()[s]], "rvrank"] = rk[s]
    for st in stores.values():
        st.cols = {k: st.cands[k].to_numpy() for k in KEYS + ("off", "n") if k in st.cands}


def scope_mask(cands: pd.DataFrame, scope: str, band: str, g: dict) -> np.ndarray:
    s = v20.in_band(cands["open"], band).to_numpy()
    if scope in EVENT_COL:
        return s & cands[EVENT_COL[scope]].to_numpy(bool)
    if scope == "mover_up":
        return s & (cands["gap"].to_numpy() > 0)
    if scope == "mover_dn":
        return s & (cands["gap"].to_numpy() < 0)
    if scope == "inplay":
        sel = g.get("sel", "rv3")
        if sel.startswith("top"):
            return s & (cands["rvrank"].to_numpy() < int(sel[3:])) & (cands["rv5"].to_numpy() >= 1.0)
        return s & (cands["rv5"].to_numpy() >= float(sel[2:]))
    return s


_IDX: dict = {}


def candidates(stores: dict, g: dict) -> list[tuple[str, np.ndarray]]:
    key = (g["scope"], g["band"], g.get("sel") if g["scope"] == "inplay" else None)
    if key not in _IDX:
        _IDX[key] = [(nm, np.flatnonzero(scope_mask(stores[nm].cands, g["scope"], g["band"], g)))
                     for nm in SCOPE_STORES[g["scope"]] if nm in stores]
    return _IDX[key]


def row(st, i: int) -> dict:
    return {k: v[i] for k, v in st.cols.items()}


def bars(st, i: int) -> tuple:
    off, n = int(st.cols["off"][i]), int(st.cols["n"][i])
    return tuple(st.arrays[f][off:off + n] for f in vi.FIELDS)


def levels(cd: dict) -> dict:
    """Price levels on the day's raw scale (v23's and the daily ones)."""
    pdh, pdl, pdc = float(cd["pdh"]), float(cd["pdl"]), float(cd["pc"])
    p = (pdh + pdl + pdc) / 3
    lv = {"pmh": float(cd["pmh"]), "pml": float(cd["pml"]), "pdh": pdh, "pdl": pdl, "pdc": pdc, "h5": float(cd["h5"]),
          "l5": float(cd["l5"]), "pivot": p, "r1": 2 * p - pdl, "s1": 2 * p - pdh, "open": float(cd["open"])}
    lv.update({k: float(cd[k]) for k in DAILY})
    return lv


# ---------------------------------------------------------------- signals

def live_mask(family: str, g: dict, b: tuple, cd: dict) -> np.ndarray:
    m, h = b[0], b[2]
    live = m <= (360 if family == "LH_LATE" else vi.LAST_ENTRY)
    if g["scope"] == "runner":  # v22c: risen 40% by the bars before
        live &= v22i.risen(h, float(cd["pc"]))
    if g["scope"] == "inplay":  # the relative volume of the first five minutes is known at 09:35
        live &= m >= 5
    return live


def _hl(lo: np.ndarray, c: np.ndarray, h: np.ndarray) -> np.ndarray:
    """A higher low: the low of the day is at least three bars old and a bar closes above the prior bar's high."""
    idx = np.arange(len(c))
    lowi = np.maximum.accumulate(np.where(lo <= np.minimum.accumulate(lo), idx, 0))
    return (idx - lowi >= 3) & (c > fast.prev(h))


def _orb(b: tuple, k: int, live: np.ndarray) -> tuple:
    m, o, h, lo = b[0], b[1], b[2], b[3]
    hi_, lo_, first = vi.opening_range(m, h, lo, k)
    if not first or not np.isfinite(hi_):
        return NONE
    j = vi.first_true((h > hi_) & live, first)
    return (j, pat._fill(o, h, j, hi_), lo_, hi_ - lo_) if j >= 0 else NONE


def _green5(b: tuple, after: int, live: np.ndarray) -> tuple:
    ends, O, _, _, C, _ = fast.agg(b, 5)
    k = vi.first_true((C > O) & (ends > after) & live[ends], 0)
    if k < 0 or ends[k] >= len(b[0]) - 1:
        return NONE
    return int(ends[k]) + 1, float(b[1][ends[k] + 1]), np.nan, np.nan


def _upper(b: tuple, cd: dict, g: dict) -> tuple[np.ndarray, np.ndarray]:
    """NB: the noise boundary max(open, prior close) x (1 + k x daily ATR% x sqrt(minutes / 390)) and the bars on
    which it is checked."""
    m = b[0]
    sig = float(cd["atr14"]) / float(cd["pc"])
    ref = max(float(cd["open"]), float(cd["pc"]))
    up = ref * (1 + g["k"] * sig * np.sqrt((m + 1.0) / 390.0))
    chk = np.ones(len(m), bool) if g["check"] == "1m" else ((m + 1) % 30 == 0)
    return up, chk


def signal(family: str, g: dict, b: tuple, line: np.ndarray, cd: dict, lv: dict) -> tuple:
    """(entry bar, entry price, stop reference, target height)."""
    if family in ("SR_LONG", "DL_DAILY") or family in V23L:
        return v23.signal(base_family(family), g, 1, b, line, cd, lv)
    m, o, h, lo, c, v = b[:6]
    n = len(c)
    idx = np.arange(n)
    live = live_mask(family, g, b, cd)
    pc, op = float(cd["pc"]), float(cd["open"])
    with np.errstate(invalid="ignore", divide="ignore"):
        if family == "SP_INPLAY":
            hi_, _, first = vi.opening_range(m, h, lo, g["k"])
            if not first or (g["candle"] == "green" and not c[first - 1] > o[0]) or \
                    (g["gapdir"] == "up" and not float(cd["gap"]) > 0):
                return NONE
            return _orb(b, g["k"], live)
        if family == "NB_NOISE":
            if not np.isfinite(float(cd["atr14"])) or (g["filter"] == "rv2" and not float(cd["rv5"]) >= 2):
                return NONE
            up, chk = _upper(b, cd, g)
            x = (c > up) & chk
            if g["filter"] == "vwap":
                x &= c > line
            return pat.close_entry(x, live & (m >= (5 if g["filter"] == "rv2" else 0)), o)
        if family == "LH_LATE":
            i30 = int(np.searchsorted(m, 30)) - 1
            jj = int(np.searchsorted(m, g["at"]))
            if i30 < 0 or jj <= i30 or jj >= n or not live[jj] or not c[i30] / pc - 1 >= g["up"]:
                return NONE
            s = jj - 1
            if (g["filter"] == "vwap" and not c[s] > line[s]) or (g["filter"] == "hod" and not c[s] >= 0.97 * h[:jj].max()):
                return NONE
            return jj, float(o[jj]), np.nan, np.nan
        if family == "PH_POWER":
            x = (c > fast.prev(np.maximum.accumulate(h), np.inf)) & (m >= g["after"]) & (c >= pc * (1 + g["day"]))
            if g["vol"]:
                x &= fast.rv(v) >= g["vol"]
            return pat.close_entry(x, live, o)
        if family == "MP_MICRO":
            return pat.micro(g, b, live & ((m < 60) if g["window"] == "open" else True))
        if family == "AB_ABCD":
            return pat.abcd(g, b, live)
        if family == "HR_HALT":
            return pat.halt(g, b, live)
        if family == "MD_MORNDIP":
            d = vi.first_true((lo <= (1 - g["drop"]) * np.maximum.accumulate(h)) & (m < g["window"]), 0)
            if d < 0:
                return NONE
            win = live & (idx > d) & (m <= m[d] + 60)
            if g["trig"] == "green5":
                return _green5(b, d, win)
            x = {"vwapre": lambda: fast.up_cross(c, line), "hl": lambda: _hl(lo, c, h),
                 "rsi": lambda: (fast.prev(fast.rsi(c, 7)) <= 20) & (c > fast.prev(c))}[g["trig"]]()
            return pat.close_entry(x, win, o)
        if family == "RG_RED2GREEN":
            if not op < pc * (1 + g["gap"]) or (g["context"] == "red2" and not cd["red2"] > 0) or \
                    (g["context"] == "up20" and not pc > float(cd["sma20d"])):
                return NONE
            x = fast.up_cross(c, pc) & (m >= g["after"])
            if g["vol"]:
                x &= fast.rv(v) >= g["vol"]
            return pat.close_entry(x, live, o)
        if family == "GF_GAPFILL":
            if not op <= pc * (1 + g["gap"]):
                return NONE
            tr = g["trig"]
            if tr in ("orh5", "orh15"):
                return _orb(b, int(tr[3:]), live)
            if tr == "t30":
                jj = int(np.searchsorted(m, 30))
                return (jj, float(o[jj]), np.nan, np.nan) if 0 < jj < n and live[jj] and c[jj - 1] > op else NONE
            x = fast.up_cross(c, line) if tr == "vwapre" else _hl(lo, c, h)
            return pat.close_entry(x & (m >= 5), live, o)
        if family == "D2_GO":
            if not float(cd["day1"]) >= g["day1"] or (g["loc"] == "top20" and not float(cd["day1_loc"]) >= 0.8):
                return NONE
            tr = g["trig"]
            if tr == "open":
                return (0, float(o[0]), np.nan, np.nan) if op > pc and live[0] else NONE
            if tr == "pmh":
                L = float(cd["pmh"])
                j = vi.first_true((h > L) & live & (m >= 1), 1) if np.isfinite(L) else -1
                return (j, pat._fill(o, h, j, L), np.nan, np.nan) if j >= 0 else NONE
            if tr in ("orh5", "orh15"):
                return _orb(b, int(tr[3:]), live)
            return pat.close_entry(fast.up_cross(c, line) & (m >= 30), live, o)
        if family == "IX_IND":
            ends, O, H, L, C, V = fast.agg(b, g["tf"])
            sig, _ = fast.indicator(g["ind"], O, H, L, C, V, line[ends])
            if g["filter"] == "vwap":
                sig = sig & (C > line[ends])
            elif g["filter"] == "ema50":
                sig = sig & (C > fast.ema(C, 50))
            k = vi.first_true(sig & live[ends] & (m[ends] >= 14), 0)
            if k < 0 or ends[k] >= n - 1:
                return NONE
            return int(ends[k]) + 1, float(o[ends[k] + 1]), np.nan, np.nan
        if family == "PX_PATTERN":
            return pat.pattern(g, b, live & (m >= g["after"]))
        if family == "CK_CANDLE":
            return pat.candles(g, b, line, lv, live)
        if family == "WO_WASH":
            return pat.washout(g, b, live)
        if family == "HG_GRAIL":
            return pat.grail(g, b, line, live)
        if family == "TS_TREND":
            ok = {"up": pc > float(cd["sma20d"]) > float(cd["sma50d"]), "high": pc >= 0.95 * float(cd["h20"]),
                  "lead": float(cd["ret60"]) >= 0.30}[g["ctx"]]
            d = vi.first_true(lo <= op * (1 - g["dip"]), 0)
            if not ok or d < 0:
                return NONE
            tr = g["trig"]
            if tr == "green5":
                return _green5(b, d, live)
            if tr == "rsi2":
                ends, _, _, _, C, _ = fast.agg(b, 5)
                r = fast.rsi(C, 2)
                k = vi.first_true((fast.prev(r) <= 10) & (C > fast.prev(C)) & (ends > d) & live[ends], 0)
                if k < 0 or ends[k] >= n - 1:
                    return NONE
                return int(ends[k]) + 1, float(o[ends[k] + 1]), np.nan, np.nan
            if tr == "vwapre":
                x = fast.up_cross(c, line)
            else:  # back above the prior close after trading below it
                x = fast.up_cross(c, pc) & fast.prev(np.minimum.accumulate(lo) < pc, False)
            return pat.close_entry(x & (idx > d), live, o)
    raise KeyError(family)


# ---------------------------------------------------------------- stops, exits, trades

def stop_of(family: str, g: dict, b: tuple, j: int, e: float, ref: float, tgt: float, cd: dict) -> float:
    st = g["stop"]
    if family in ("SR_LONG", "DL_DAILY") or family in V23L:
        return v23._stop(g, 1, b, j, e, ref, tgt)
    if st.startswith("pct"):
        return e * (1 - int(st[3:]) / 100)
    if st.startswith("atr"):
        a = float(cd["atr14"])
        return e - int(st[3:]) / 100 * a if np.isfinite(a) else np.nan
    if st == "lod":
        return v19.stop_of("lod", 1, b, j, e, cd)
    if st == "swing":
        return float(b[3][max(j - 10, 0):j].min()) if j > 0 else np.nan
    return ref * 0.998 if np.isfinite(ref) else np.nan  # pb, range: just under the pattern's or range's low


def exit_mask(family: str, g: dict, b: tuple, line: np.ndarray, cd: dict) -> np.ndarray:
    """The bars' own exit signal (independent of the entry, so a placebo takes it from its own bars)."""
    n = len(b[0])
    xm = np.zeros(n, bool)
    if g["exit"] == "opp":
        ends, O, H, L, C, V = fast.agg(b, g["tf"])
        _, opp = fast.indicator(g["ind"], O, H, L, C, V, line[ends])
        xm[ends[opp]] = True
    elif g["exit"] == "bound":
        up, chk = _upper(b, cd, g)
        xm = (b[4] < np.maximum(up, line)) & chk
    return xm


def _row(cd: dict, b: tuple, j: int, e: float, stop: float, px: float, kk: int, rule: str, prio: float) -> dict:
    m, c, v, vw = b[0], b[4], b[5], b[6]
    pv = np.where(np.isfinite(vw) & (vw > 0), vw, c)
    return {"date": cd["date"], "t": int(cd["t"]), "symbol": cd["symbol"], "minute": int(m[j]), "side": 1, "entry": e,
            "stop": stop, "price": float(cd["open"]), "liq": float(cd["pmv"]) + float(np.sum(pv[:j] * v[:j])),
            "prio": prio, "so": float(cd.get("so", np.nan)), "rets": np.array([(px - e) / e]), "nights": 0,
            "rule": rule, "opens": int(j == 0 and e == float(b[1][0])), "xmin": int(m[kk]),
            "leg_in": 0 if (j == 0 and e == float(b[1][0])) else 1, "leg_out": 2 if kk == len(c) - 1 else 1}


def _stop_fill(b: tuple, j: int, k: int, stop: float) -> float:
    return v19._slip(stop, float(b[3][k])) if k == j else v19._past(-1, float(b[1][k]), stop, float(b[3][k]))


def special(D: dict, cd: dict, b: tuple, line: np.ndarray, j: int, e: float, stop: float, rule: str,
            prio: float) -> dict:
    """be1r: the stop moves to the entry once 1R is reached, out at the close otherwise; scale: half at 2R, half at
    the close (one stop for both); tstop15: out after 15 minutes unless above the entry, then at the close."""
    m, o, h, lo, c = b[:5]
    n = len(c)
    if rule == "scale":
        a = v19.trade_row(D, cd, b, line, 1, j, e, stop, "r2", prio)
        z = v19.trade_row(D, cd, b, line, 1, j, e, stop, "close", prio)
        z["rets"] = np.array([0.5 * (a["rets"][0] + z["rets"][0])])
        z["rule"] = "scale"
        return z
    hit = vi.first_true(lo <= stop, j)
    if rule == "be1r":
        k1 = vi.first_true(h >= 2 * e - stop, j)
        if hit >= 0 and (k1 < 0 or hit <= k1):
            px, kk = _stop_fill(b, j, hit, stop), hit
        elif k1 >= 0:
            k2 = vi.first_true(lo <= e, k1 + 1)
            px, kk = (v19._past(-1, float(o[k2]), e, float(lo[k2])), k2) if k2 >= 0 else (float(c[-1]), n - 1)
        else:
            px, kk = float(c[-1]), n - 1
    else:
        k = vi.first_true(m >= m[j] + 15, j)
        if hit >= 0 and (k < 0 or hit <= k):
            px, kk = _stop_fill(b, j, hit, stop), hit
        elif k >= 0 and c[k] <= e:
            px, kk = float(c[k]), k
        elif hit >= 0:
            px, kk = _stop_fill(b, j, hit, stop), hit
        else:
            px, kk = float(c[-1]), n - 1
    return _row(cd, b, j, e, stop, px, kk, rule, prio)


def make_trade(D: dict, family: str, g: dict, cd: dict, b: tuple, line: np.ndarray, lv: dict, j: int, e: float,
               stop: float, tgt: float, prio: float) -> dict:
    ex = g["exit"]
    if ex in SPECIAL:
        return special(D, cd, b, line, j, e, stop, ex, prio)
    if ex in TARGETS:
        t = (float(cd["open"]) + float(cd["pc"])) / 2 if ex == "half" else float(cd["open"])
        return v23.target_row(D, cd, b, line, 1, j, e, stop, t if t > e else np.nan, ex, prio)
    if ex in MASKS:
        return v22i.mask_row(D, cd, b, line, 1, j, e, stop, exit_mask(family, g, b, line, cd), ex, prio)
    return v23.make_trade(D, base_family(family), g, 1, cd, b, line, lv, j, e, stop, tgt, prio)


def trades(stores: dict, D: dict, family: str, g: dict) -> pd.DataFrame:
    rows = []
    for nm, idx in candidates(stores, g):
        st = stores[nm]
        for i in idx:
            cd = row(st, int(i))
            b = bars(st, int(i))
            if len(b[0]) < 30:
                continue
            line = vi.vwap(b[4], b[5], b[6])
            lv = levels(cd)
            j, e, ref, tgt = signal(family, g, b, line, cd, lv)
            if j < 0 or not np.isfinite(e) or e <= 0:
                continue
            stop = stop_of(family, g, b, j, e, ref, tgt, cd)
            if not np.isfinite(stop) or stop >= e:
                continue
            rows.append(make_trade(D, family, g, cd, b, line, lv, j, e, stop, tgt, abs(float(cd["gap"]))))
    return pd.DataFrame(rows, columns=v19.COLS)


def pool_by_day(stores: dict, g: dict) -> dict:
    out: dict = {}
    for nm, idx in candidates(stores, g):
        dates = stores[nm].cols["date"]
        for i in idx:
            out.setdefault(pd.Timestamp(dates[i]), []).append((nm, int(i)))
    return out


def placebo(stores: dict, by_day: dict, D: dict, family: str, g: dict, real: pd.DataFrame,
            rng: np.random.Generator) -> pd.DataFrame:
    """Each real trade moved to a random candidate of its scope and band that day (v23's placebo): same minute (that
    bar's open), stop distance and exit; targets and indicator exits from the placebo's own levels and bars."""
    rows = []
    for r in real.itertuples(index=False):
        ch = by_day.get(pd.Timestamp(r.date), [])
        if not ch:
            continue
        nm, i = ch[int(rng.integers(len(ch)))]
        st = stores[nm]
        cd = row(st, i)
        b = bars(st, i)
        if len(b[0]) < 30:
            continue
        j = int(np.searchsorted(b[0], r.minute))
        if j >= len(b[0]) or b[0][j] > vi.LAST_ENTRY + 30:
            continue
        e = float(b[1][j])
        stop = e * (1 - abs(r.entry - r.stop) / r.entry)
        line = vi.vwap(b[4], b[5], b[6])
        rows.append(make_trade(D, family, g, cd, b, line, levels(cd), j, e, stop, 2 * abs(r.entry - r.stop),
                               float(r.prio)))
    return pd.DataFrame(rows, columns=v19.COLS)
