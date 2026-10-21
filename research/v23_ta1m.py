"""v23: technical analysis on one-minute bars of small caps: supports and resistances, indicators, patterns.
Pre-registered in docs/research/V23_PREREGISTRATION.md.

Candidates: the 100 most liquid small caps of every session (the v23 minute store, scope "liquid") and v14's event
days (scopes "gapup", "runner", "gapdown"). One trade per configuration and symbol-day: the first signal. Levels are
on the day's raw scale: premarket high and low, the prior day's high, low and close, the opening ranges, the five-day
high and low, round numbers, floor pivots, VWAP and the session's high and low so far. Entries at a signal bar's
close (the next bar is the entry bar) or, for range breaks, at the level; exits by v19's rules (close, d3, next
open, R multiples, minutes), at the next level, at a measured move, or by an indicator (EMA9 close, cross back,
oscillator back to the middle); stops beyond the level, at the pattern, a swing, or a percentage.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from aurora.research import v14_intraday as vi
from aurora.research import v19_grid as v19
from aurora.research import v20_grid as v20
from aurora.research import v22_intra as v22i

B3 = ("1-3", "3-8", "8-20")
SC3 = ("liquid", "gapup", "runner")
LEVELS = ("pmh", "pml", "pdh", "pdl", "pdc", "orh5", "orl5", "orh15", "orl15", "orh30", "orl30", "h5", "l5",
          "round1", "round050", "pivot", "r1", "s1")
SETUPS = ("break_up", "break_dn", "fail_up", "fail_dn", "retest_up", "retest_dn")
SETUP_SIDE = {"break_up": 1, "break_dn": -1, "fail_up": -1, "fail_dn": 1, "retest_up": 1, "retest_dn": -1}
WINDOWS = {"open": (0, 60), "midlate": (60, 330), "all": (0, 330)}

INTRA_DIMS = {
    "SR_LEVEL": {"level": LEVELS, "setup": SETUPS, "vol": (0.0, 2.0), "window": ("open", "midlate", "all"),
                 "stop": ("lvl1", "pct10"), "exit": ("r2", "nextlevel", "ema9", "t30", "close", "d3"), "scope": SC3,
                 "band": B3},
    "VW_VWAP": {"setup": ("reclaim", "loss", "bounce", "reject", "revert_lo", "revert_hi", "break_hi", "break_lo"),
                "after": (15, 60),
                "vol": (0.0, 2.0), "stop": ("swing", "pct10"), "exit": ("r2", "vwapx", "ema9", "t30", "close", "d3"),
                "scope": SC3, "band": B3},
    "EM_EMA": {"pair": ("9/20", "20/50", "50/200"), "tf": (1, 5, 15), "setup": ("cross", "pullback"),
               "side": ("long", "short"), "stop": ("swing", "pct10"), "exit": ("crossback", "r2", "t30", "close", "d3"),
               "scope": SC3, "band": B3},
    "OS_OSC": {"ind": ("rsi2", "rsi7", "rsi14", "stoch14"), "tf": (1, 5), "lvl": ("x10", "x20"),
               "side": ("long", "short"), "confirm": ("none", "turn"), "near": ("any", "level"),
               "stop": ("swing", "pct10"), "exit": ("mid", "r2", "t30", "close"), "scope": SC3, "band": B3},
    "MD_MACD": {"set": ("12/26/9", "5/35/5"), "tf": (1, 5), "signal": ("cross", "zero", "div"), "side": ("long", "short"),
                "stop": ("swing", "pct10"), "exit": ("crossback", "r2", "t30", "close", "d3"), "scope": SC3, "band": B3},
    "SQ_SQUEEZE": {"kc": (1.5, 2.0), "bars": (10, 20), "side": ("long", "short"), "vol": (0.0, 2.0),
                   "stop": ("swing", "pct10"), "exit": ("r2", "ema9", "t30", "close", "d3"), "scope": SC3, "band": B3},
    "PT_PATTERN": {"pattern": ("double_top", "double_bottom", "asc_triangle", "desc_triangle", "bull_flag",
                               "bear_flag"),
                   "size": ("small", "large"), "after": (15, 60), "stop": ("pattern", "pct10"),
                   "exit": ("r2", "measured", "ema9", "close", "d3"), "scope": SC3, "band": B3},
    "CD_CANDLE": {"candle": ("engulf", "pin", "inside", "doji"), "cside": ("long", "short"),
                  "at": ("pm", "pd", "vwap", "hod"), "tf": (1, 5), "stop": ("swing", "pct10"),
                  "exit": ("r1", "r2", "t15", "t30", "close"), "scope": SC3, "band": B3},
    "VC_CLIMAX": {"mult": (5.0, 10.0), "candle": ("upwick", "lowwick", "bigup", "bigdown"), "after": (15, 60),
                  "stop": ("swing", "pct10"), "exit": ("r1", "r2", "t15", "t30", "close"), "scope": SC3, "band": B3},
    "OR_ORB": {"k": (1, 5, 15, 30, 60), "side": ("long", "short"), "filter": ("none", "vwap", "rvol", "gapdir"),
               "stop": ("range", "half", "pct10"), "exit": ("r1", "r2", "r3", "close", "d3", "ema9"), "scope": SC3,
               "band": B3},
}
PATTERN_SIDE = {"double_top": -1, "double_bottom": 1, "asc_triangle": 1, "desc_triangle": -1, "bull_flag": 1,
                "bear_flag": -1}
CANDLE_FLIP = {"upwick": -1, "lowwick": 1, "bigup": 1, "bigdown": -1}


def side_of(family: str, g: dict) -> int:
    if family == "SR_LEVEL":
        return SETUP_SIDE[g["setup"]]
    if family == "VW_VWAP":
        return 1 if g["setup"] in ("reclaim", "bounce", "revert_lo", "break_hi") else -1
    if family == "PT_PATTERN":
        return PATTERN_SIDE[g["pattern"]]
    if family == "VC_CLIMAX":
        return CANDLE_FLIP[g["candle"]]
    if family == "CD_CANDLE":
        return 1 if g["cside"] == "long" else -1
    return 1 if g["side"] == "long" else -1


# ---------------------------------------------------------------- candidates and levels

def stores(event_store: vi.Store, liquid_store: vi.Store, scope: str) -> vi.Store:
    return liquid_store if scope == "liquid" else event_store


def scope_mask(c: pd.DataFrame, scope: str, band: str) -> pd.Series:
    price = v20.in_band(c["open"], band)
    if scope == "liquid":
        return price
    return price & c[{"gapup": "s_gap_up", "runner": "s_runner", "gapdown": "s_gap_down"}[scope]]


def facts(cd: pd.Series, D: dict) -> dict:
    """The day's static levels; event days take the prior day's bars from the daily arrays."""
    t, j = int(cd["t"]), int(cd["j"])
    f = D["F"][t, j]
    pdh = float(cd["pdh"]) if "pdh" in cd and np.isfinite(cd.get("pdh", np.nan)) else float(D["H"][t - 1, j] / f)
    pdl = float(cd["pdl"]) if "pdl" in cd and np.isfinite(cd.get("pdl", np.nan)) else float(D["L"][t - 1, j] / f)
    pdc = float(cd["pc"])
    if "h5" in cd and np.isfinite(cd.get("h5", np.nan)):
        h5, l5 = float(cd["h5"]), float(cd["l5"])
    else:
        h5, l5 = float(np.nanmax(D["H"][max(t - 5, 0):t, j]) / f), float(np.nanmin(D["L"][max(t - 5, 0):t, j]) / f)
    pml = float(cd["pml"]) if "pml" in cd and np.isfinite(cd.get("pml", np.nan)) else float(cd.get("pml30", np.nan))
    p = (pdh + pdl + pdc) / 3
    return {"pmh": float(cd["pmh"]), "pml": pml, "pdh": pdh, "pdl": pdl, "pdc": pdc, "h5": h5, "l5": l5,
            "pivot": p, "r1": 2 * p - pdl, "s1": 2 * p - pdh, "open": float(cd["open"])}


def level_of(name: str, lv: dict, b: tuple, up: bool) -> float:
    m, h, lo = b[0], b[2], b[3]
    if name.startswith("or"):
        hi_, lo_, first = vi.opening_range(m, h, lo, int(name[3:]))
        return (hi_ if name[2] == "h" else lo_) if first else np.nan
    if name == "round1":
        return float(np.ceil(lv["open"])) if up else float(np.floor(lv["open"]))
    if name == "round050":
        return float(np.ceil(lv["open"] * 2) / 2) if up else float(np.floor(lv["open"] * 2) / 2)
    return lv.get(name, np.nan)


def _rv(v: np.ndarray) -> np.ndarray:
    """A minute's volume over the average of the 30 minutes before."""
    avg = pd.Series(v).rolling(30, min_periods=10).mean().shift(1).to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        return v / avg


def _agg(b: tuple, k: int) -> tuple:
    """k-minute bars: (index of each bucket's last one-minute bar, open, high, low, close, volume)."""
    m = b[0].astype(int)
    key = m // k
    ends = np.r_[np.flatnonzero(np.diff(key)), len(m) - 1]
    starts = np.r_[0, ends[:-1] + 1]
    o, h, lo, c, v = b[1], b[2], b[3], b[4], b[5]
    return (ends, o[starts], np.maximum.reduceat(h, starts), np.minimum.reduceat(lo, starts), c[ends],
            np.add.reduceat(v, starts))


# ---------------------------------------------------------------- signals: (entry bar, entry price, stop ref, target)

NONE = (-1, np.nan, np.nan, np.nan)


def _close_entry(mask: np.ndarray, live: np.ndarray, c: np.ndarray, ref=None, tgt=None, o: np.ndarray | None = None):
    """A signal known at a bar's close, filled at the next bar's open."""
    j = vi.first_true(mask & live, 0)
    if not 0 <= j < len(c) - 1:
        return NONE
    return j + 1, float(o[j + 1]),(float(ref[j]) if ref is not None else np.nan), \
        (float(tgt[j]) if tgt is not None else np.nan)


def signal(family: str, g: dict, side: int, b: tuple, line: np.ndarray, cd: pd.Series, lv: dict) -> tuple:
    m, o, h, lo, c, v = b[0], b[1], b[2], b[3], b[4], b[5]
    n = len(c)
    live = m <= vi.LAST_ENTRY
    if g.get("scope") == "runner":  # the runner scope is defined by the day's high: trade it only once risen 40%
        live &= np.maximum.accumulate(h) >= 1.4 * float(cd["pc"])
    if family == "SR_LEVEL":
        a, z = WINDOWS[g["window"]]
        live &= (m >= a) & (m < z)
        up = g["setup"].endswith("_up")
        L = level_of(g["level"], lv, b, up)
        if not np.isfinite(L) or L <= 0:
            return NONE
        if g["level"].startswith("or"):
            live &= m >= int(g["level"][3:])
        if g["vol"]:
            live &= _rv(v) >= g["vol"]
        prev_c = np.r_[np.nan, c[:-1]]
        lvl = np.full(n, L)
        kind = g["setup"].split("_")[0]
        if kind == "break":
            x = (c > L) & (prev_c <= L) if up else (c < L) & (prev_c >= L)
            return _close_entry(x, live, c, lvl, o=o)
        if kind == "fail":  # through the level by 0.2%, then a close back on the other side within three bars
            p0 = vi.first_true((h > L * 1.002) if up else (lo < L * 0.998), 0)
            if p0 < 0:
                return NONE
            idx = np.arange(n)
            x = (idx >= p0) & (idx <= p0 + 3) & ((c < L) if up else (c > L))
            return _close_entry(x, live, c, lvl, o=o)
        brk = (c > L) & (prev_c <= L) if up else (c < L) & (prev_c >= L)
        j0 = vi.first_true(brk, 0)
        if j0 < 0:
            return NONE
        after = np.arange(n) > j0 + 2
        x = after & ((lo <= L * 1.003) & (c > L) if up else (h >= L * 0.997) & (c < L))
        return _close_entry(x, live, c, lvl, o=o)
    if family == "VW_VWAP":
        live &= m >= g["after"]
        if g["vol"]:
            live &= _rv(v) >= g["vol"]
        st = g["setup"]
        prev_c, prev_l = np.r_[np.nan, c[:-1]], np.r_[np.nan, line[:-1]]
        if st == "reclaim":
            x = (c > line) & (prev_c <= prev_l)
        elif st == "loss":
            x = (c < line) & (prev_c >= prev_l)
        elif st == "bounce":
            x = (lo <= line) & (c > line) & (prev_c > prev_l)
        elif st == "reject":
            x = (h >= line) & (c < line) & (prev_c < prev_l)
        else:  # two volume-weighted deviations from VWAP: faded back towards it, or followed
            dev = v22i._vwap_dev(b, line)
            hi2, lo2 = line + 2 * dev, line - 2 * dev
            x = {"revert_lo": c < lo2, "revert_hi": c > hi2, "break_hi": c > hi2, "break_lo": c < lo2}[st] & (dev > 0)
        return _close_entry(x, live, c, o=o)
    if family == "EM_EMA":
        f, s = (int(x) * g["tf"] for x in g["pair"].split("/"))
        fa, sl = v22i._ema(c, f), v22i._ema(c, s)
        live &= m >= 15
        if g["setup"] == "cross":
            x = v22i._up(fa, sl) if side > 0 else v22i._dn(fa, sl)
        else:
            x = ((fa > sl) & (lo <= fa) & (c > fa)) if side > 0 else ((fa < sl) & (h >= fa) & (c < fa))
        return _close_entry(x, live, c, o=o)
    if family == "OS_OSC":
        tf = g["tf"]
        if g["ind"].startswith("rsi"):
            osc = v22i._rsi(c, int(g["ind"][3:]) * tf)
        else:
            hi = pd.Series(h).rolling(14 * tf, min_periods=5).max().to_numpy()
            low = pd.Series(lo).rolling(14 * tf, min_periods=5).min().to_numpy()
            with np.errstate(invalid="ignore", divide="ignore"):
                osc = 100 * (c - low) / np.maximum(hi - low, 1e-9)
        q = int(g["lvl"][1:])
        x = (osc <= q) if side > 0 else (osc >= 100 - q)
        if g["confirm"] == "turn":
            x &= (c > np.r_[np.inf, c[:-1]]) if side > 0 else (c < np.r_[-np.inf, c[:-1]])
        if g["near"] == "level":
            lvls = np.array([lv[k] for k in ("pmh", "pml", "pdh", "pdl", "pdc") if np.isfinite(lv[k])])
            near = np.zeros(n, bool)
            for L in lvls:
                near |= np.abs(c / L - 1) <= 0.01
            x &= near | (np.abs(c / line - 1) <= 0.01)
        live &= m >= 15
        return _close_entry(x, live, c, o=o)
    if family == "MD_MACD":
        f, s, sg = (int(x) * g["tf"] for x in g["set"].split("/"))
        mc = v22i._ema(c, f) - v22i._ema(c, s)
        sig = v22i._ema(mc, sg)
        live &= m >= 15
        if g["signal"] == "cross":
            x = v22i._up(mc, sig) if side > 0 else v22i._dn(mc, sig)
        elif g["signal"] == "zero":
            x = v22i._up(mc, 0.0) if side > 0 else v22i._dn(mc, 0.0)
        else:
            hist = mc - sig
            ext = pd.Series(c).rolling(30, min_periods=10)
            hx = pd.Series(hist).rolling(30, min_periods=10)
            x = ((c <= ext.min().to_numpy()) & (hist > hx.min().shift(1).to_numpy())) if side > 0 else \
                ((c >= ext.max().to_numpy()) & (hist < hx.max().shift(1).to_numpy()))
        return _close_entry(x, live, c, o=o)
    if family == "SQ_SQUEEZE":
        cs = pd.Series(c)
        mid, sd = cs.rolling(20, min_periods=20).mean().to_numpy(), cs.rolling(20, min_periods=20).std().to_numpy()
        tr = np.maximum(h - lo, np.abs(h - np.r_[c[0], c[:-1]]))
        atr = pd.Series(tr).rolling(20, min_periods=20).mean().to_numpy()
        inside = (mid + 2 * sd < mid + g["kc"] * atr) & (mid - 2 * sd > mid - g["kc"] * atr)
        run = pd.Series(inside.astype(float)).rolling(g["bars"], min_periods=g["bars"]).min().shift(1).to_numpy() > 0
        x = run & ((c > mid + 2 * sd) if side > 0 else (c < mid - 2 * sd))
        if g["vol"]:
            x &= _rv(v) >= g["vol"]
        return _close_entry(x, live, c, o=o)
    if family == "PT_PATTERN":
        live &= m >= g["after"]
        return _pattern(g, side, b, live)
    if family == "CD_CANDLE":
        return _candle_at(g, side, b, line, lv, live)
    if family == "VC_CLIMAX":
        live &= m >= g["after"]
        rng = np.maximum(h - lo, 1e-9)
        body = np.abs(c - o)
        shape = {"upwick": (h - np.maximum(o, c)) >= 0.6 * rng, "lowwick": (np.minimum(o, c) - lo) >= 0.6 * rng,
                 "bigup": (c > o) & (body >= 0.7 * rng), "bigdown": (c < o) & (body >= 0.7 * rng)}[g["candle"]]
        return _close_entry((_rv(v) >= g["mult"]) & shape, live, c, o=o)
    if family == "OR_ORB":
        hi_, lo_, first = vi.opening_range(m, h, lo, g["k"])
        if not first or not np.isfinite(hi_):
            return NONE
        x = (h > hi_) if side > 0 else (lo < lo_)
        if g["filter"] == "vwap":
            x &= (c > line) if side > 0 else (c < line)
        elif g["filter"] == "rvol":
            x &= _rv(v) >= 2.0
        elif g["filter"] == "gapdir":
            if (lv["open"] - lv["pdc"]) * side <= 0:
                return NONE
        j = vi.first_true(x & live, first)
        if j < 0:
            return NONE
        lvl = hi_ if side > 0 else lo_
        other = lo_ if side > 0 else hi_
        return j, v19._past(side, float(o[j]), float(lvl), float(h[j] if side > 0 else lo[j])), float(other), \
            float(abs(hi_ - lo_))
    raise KeyError(family)


def _pattern(g: dict, side: int, b: tuple, live: np.ndarray) -> tuple:
    m, o, h, lo, c = b[0], b[1], b[2], b[3], b[4]
    n = len(c)
    big = g["size"] == "large"
    p = g["pattern"]
    if p in ("bull_flag", "bear_flag"):
        gg = {"pole": 0.15 if big else 0.06, "retrace": 0.50, "after": 5}
        j, e, ext = v22i.entry("IF_FLAG", gg, side, b, np.zeros(n), {})
        if j < 0 or not live[min(j, n - 1)]:
            return NONE
        return j, e, ext, np.nan
    tol, gap = (0.015, 20) if big else (0.005, 10)
    roll = 5
    if p in ("double_top", "double_bottom"):
        top = p == "double_top"
        x = h if top else lo
        ext = pd.Series(x).rolling(2 * roll + 1, center=True, min_periods=roll).max() if top else \
            pd.Series(x).rolling(2 * roll + 1, center=True, min_periods=roll).min()
        piv = np.flatnonzero(x == ext.to_numpy())
        for a_i, a in enumerate(piv):
            for bb in piv[a_i + 1:]:
                if bb - a < gap:
                    continue
                if abs(x[bb] / x[a] - 1) > tol:
                    continue
                neck = float(lo[a:bb + 1].min()) if top else float(h[a:bb + 1].max())
                k = vi.first_true((c < neck) if top else (c > neck), bb + roll)
                if 0 <= k < n - 1 and live[k]:
                    height = abs(max(x[a], x[bb]) - neck) if top else abs(neck - min(x[a], x[bb]))
                    return k + 1, float(o[k + 1]), float(max(x[a], x[bb]) if top else min(x[a], x[bb])), height
                break
        return NONE
    # triangles over the last 30 (60) bars in two halves: the flat side's two halves within tol of each other, the
    # other side rising (falling), and a close through the flat side
    asc = p == "asc_triangle"
    half = 30 if big else 15
    hs, ls = pd.Series(h), pd.Series(lo)
    h2, l2 = hs.rolling(half, min_periods=half).max().shift(1), ls.rolling(half, min_periods=half).min().shift(1)
    h1, l1 = h2.shift(half), l2.shift(half)
    h1, h2, l1, l2 = (x.to_numpy() for x in (h1, h2, l1, l2))
    with np.errstate(invalid="ignore", divide="ignore"):
        if asc:
            flat = np.fmax(h1, h2)
            x = (np.abs(h2 / h1 - 1) <= tol) & (l2 > l1) & (c > flat)
            other = l2
        else:
            flat = np.fmin(l1, l2)
            x = (np.abs(l2 / l1 - 1) <= tol) & (h2 < h1) & (c < flat)
            other = h2
    j, e, ref, _ = _close_entry(x, live, c, other, o=o)
    if j < 0:
        return NONE
    return j, e, ref, abs(float(flat[j - 1]) - ref)


def _candle_at(g: dict, side: int, b: tuple, line: np.ndarray, lv: dict, live: np.ndarray) -> tuple:
    m = b[0]
    if g["tf"] == 1:
        ends, o, h, lo, c = np.arange(len(m)), b[1], b[2], b[3], b[4]
    else:
        ends, o, h, lo, c, _ = _agg(b, 5)
    po, pc_, ph, pl = np.r_[np.nan, o[:-1]], np.r_[np.nan, c[:-1]], np.r_[np.nan, h[:-1]], np.r_[np.nan, lo[:-1]]
    rng = np.maximum(h - lo, 1e-9)
    body = np.abs(c - o)
    cd_ = g["candle"]
    with np.errstate(invalid="ignore"):
        if cd_ == "engulf":
            x = ((pc_ < po) & (c > o) & (c >= po) & (o <= pc_)) if side > 0 else ((pc_ > po) & (c < o) & (c <= po) &
                                                                                   (o >= pc_))
        elif cd_ == "pin":
            x = ((np.minimum(o, c) - lo) >= 2 * body) if side > 0 else ((h - np.maximum(o, c)) >= 2 * body)
        elif cd_ == "inside":
            inside = (ph < np.r_[np.nan, ph[:-1]]) & (pl > np.r_[np.nan, pl[:-1]])
            x = inside & ((c > ph) if side > 0 else (c < pl))
        else:
            x = (body <= 0.1 * rng)
    at = g["at"]
    line_e = line[ends]
    if at == "vwap":
        near = np.abs((lo if side > 0 else h) / line_e - 1) <= 0.005
    elif at == "hod":
        ext = np.minimum.accumulate(lo) if side > 0 else np.maximum.accumulate(h)
        near = np.abs((lo if side > 0 else h) / ext - 1) <= 0.003
    else:
        L = lv["pml" if side > 0 else "pmh"] if at == "pm" else lv["pdl" if side > 0 else "pdh"]
        near = np.abs((lo if side > 0 else h) / L - 1) <= 0.005 if np.isfinite(L) else np.zeros(len(c), bool)
    sig = x & near & live[ends] & (m[ends] >= 5)
    k = vi.first_true(sig, 0)
    if k < 0 or ends[k] >= len(m) - 1:
        return NONE
    return int(ends[k]) + 1, float(b[1][int(ends[k]) + 1]), float(lo[k] if side > 0 else h[k]), np.nan


# ---------------------------------------------------------------- stops, exits, trades

def _stop(g: dict, side: int, b: tuple, j: int, e: float, ref: float, tgt: float) -> float:
    st = g["stop"]
    if st.startswith("pct"):
        return e * (1 - side * int(st[3:]) / 100)
    if st == "lvl1":
        return ref * (1 - side * 0.01) if np.isfinite(ref) else np.nan
    if st in ("pattern", "range"):
        return ref * (1 - side * 0.002) if np.isfinite(ref) else np.nan
    if st == "half":
        return e - side * 0.5 * tgt if np.isfinite(tgt) else np.nan
    a = max(j - 10, 0)
    if j <= a:
        return np.nan
    return float(b[2][a:j].max()) if side < 0 else float(b[3][a:j].min())


def _next_level(lv: dict, b: tuple, side: int, e: float) -> float:
    vals = [x for k, x in lv.items() if k != "open" and np.isfinite(x)]
    vals += [float(np.ceil(e)), float(np.floor(e)), float(np.ceil(e * 2) / 2), float(np.floor(e * 2) / 2)]
    ahead = [x for x in vals if (x - e) * side >= 0.005 * e]
    return (min(ahead) if side > 0 else max(ahead)) if ahead else np.nan


def target_row(D: dict, cd: pd.Series, b: tuple, line: np.ndarray, side: int, j: int, e: float, stop: float, tgt: float,
               rule: str, prio: float) -> dict:
    """A same-day trade with a limit target (filled at the target or the open beyond it), unless the stop comes
    first; at the close otherwise."""
    if not np.isfinite(tgt):
        return v19.trade_row(D, cd, b, line, side, j, e, stop, "close", prio)
    xm = (b[2] >= tgt) if side > 0 else (b[3] <= tgt)
    r = v22i.mask_row(D, cd, b, line, side, j, e, stop, xm, "target", prio)
    k = vi.first_true(xm, j + 1)
    hit = vi.first_true((b[2] >= stop) if side < 0 else (b[3] <= stop), j)
    if k >= 0 and (hit < 0 or k < hit):
        px = max(float(b[1][k]), tgt) if side > 0 else min(float(b[1][k]), tgt)
        r["rets"] = np.array([side * (px - e) / e])
    r["rule"] = rule
    return r


def make_trade(D: dict, family: str, g: dict, side: int, cd: pd.Series, b: tuple, line: np.ndarray, lv: dict, j: int,
               e: float, stop: float, tgt: float, prio: float) -> dict:
    ex = g["exit"]
    c = b[4]
    if ex in ("nextlevel", "measured"):
        t = _next_level(lv, b, side, e) if ex == "nextlevel" else (e + side * tgt if np.isfinite(tgt) else np.nan)
        return target_row(D, cd, b, line, side, j, e, stop, t, ex, prio)
    if ex in ("ema9", "crossback", "mid", "vwapx"):
        if ex == "ema9":
            xm = (c < v22i._ema(c, 9)) if side > 0 else (c > v22i._ema(c, 9))
        elif ex == "crossback":
            span = (9, 20)
            if family in ("EM_EMA", "MD_MACD"):
                key = g.get("pair", g.get("set", "9/20")).split("/")
                span = (int(key[0]) * g.get("tf", 1), int(key[1]) * g.get("tf", 1))
            fa, sl = v22i._ema(c, span[0]), v22i._ema(c, span[1])
            xm = (fa < sl) if side > 0 else (fa > sl)
        elif ex == "mid":
            r = v22i._rsi(c, 14)
            xm = (r >= 50) if side > 0 else (r <= 50)
        else:
            xm = (c < line) if side > 0 else (c > line)
        return v22i.mask_row(D, cd, b, line, side, j, e, stop, xm, ex, prio)
    return v19.trade_row(D, cd, b, line, side, j, e, stop, ex, prio)


def trades(event_store: vi.Store, liquid_store: vi.Store, D: dict, family: str, g: dict) -> pd.DataFrame:
    st = stores(event_store, liquid_store, g["scope"])
    c = st.cands
    rows = []
    for k in c.index[scope_mask(c, g["scope"], g["band"]).to_numpy()]:
        cd = c.loc[k]
        b = st.bars(k)
        if len(b[0]) < 30:
            continue
        side = side_of(family, g)
        line = vi.vwap(b[4], b[5], b[6])
        lv = facts(cd, D)
        j, e, ref, tgt = signal(family, g, side, b, line, cd, lv)
        if j < 0 or not np.isfinite(e) or e <= 0:
            continue
        if side < 0:
            j, e = vi._ssr_fill(j, b, float(cd["pc"]), e)
            if j < 0:
                continue
        stop = _stop(g, side, b, j, e, ref, tgt)
        if not np.isfinite(stop) or (stop - e) * side >= 0:
            continue
        rows.append(make_trade(D, family, g, side, cd, b, line, lv, j, e, stop, tgt, abs(float(cd["gap"]))))
    return pd.DataFrame(rows, columns=v19.COLS)


def pool_by_day(event_store: vi.Store, liquid_store: vi.Store, g: dict) -> tuple[vi.Store, dict]:
    st = stores(event_store, liquid_store, g["scope"])
    s = scope_mask(st.cands, g["scope"], g["band"]).to_numpy()
    out: dict = {}
    for k, d in zip(st.cands.index[s], st.cands.loc[s, "date"]):
        out.setdefault(pd.Timestamp(d), []).append(k)
    return st, out


def placebo(st: vi.Store, by_day: dict, D: dict, family: str, g: dict, real: pd.DataFrame,
            rng: np.random.Generator) -> pd.DataFrame:
    """Each real trade moved to a random candidate of its scope and band that day: same minute (that bar's open),
    side, stop distance and exit (targets and indicator exits from the placebo's own levels and bars)."""
    rows = []
    for r in real.itertuples(index=False):
        ch = by_day.get(pd.Timestamp(r.date), [])
        if not ch:
            continue
        k = int(rng.choice(ch))
        cd = st.cands.loc[k]
        b = st.bars(k)
        if len(b[0]) < 30:
            continue
        j = int(np.searchsorted(b[0], r.minute))
        if j >= len(b[0]) or b[0][j] > vi.LAST_ENTRY + 30:
            continue
        e = float(b[1][j])
        stop = e * (1 - r.side * abs(r.entry - r.stop) / r.entry)
        line = vi.vwap(b[4], b[5], b[6])
        tgt = abs(r.entry - r.stop) * 2  # a measured move of twice the stop distance stands in for the pattern's
        rows.append(make_trade(D, family, g, int(r.side), cd, b, line, facts(cd, D), j, e, stop, tgt, float(r.prio)))
    return pd.DataFrame(rows, columns=v19.COLS)
