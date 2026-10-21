"""v22: technical analysis on small caps, daily bars. Pre-registered in docs/research/V22_PREREGISTRATION.md.

Every daily family is an indicator, candle or chart-pattern signal on the setup day's bar (known at its close) over
all small caps of a price band with $1M of 20-day dollar volume, entered at that close or at the next open, and left
by an indicator signal, a holding period, a target, a trailing stop or a stop. At most 30 signals a day enter the
book (the highest priority first); a symbol is not entered again while a trade on it could still be open.
Indicators are on split-adjusted prices.
"""
from __future__ import annotations

from collections import OrderedDict

import numpy as np
import pandas as pd

from aurora.research import v14_core as core
from aurora.research import v14_swing as vs
from aurora.research import v19_grid as v19
from aurora.research import v20_grid as v20

B3 = ("1-3", "3-8", "8-20")
TOP_K = 30
MAX_HOLD = 40  # sessions, for signal and trailing exits
TREND = ("none", "up200", "down200", "up50")

DAILY_DIMS = {
    "RS_RSI": {"n": (2, 3, 5, 14), "lvl": (5, 10, 25), "side": ("long", "short"), "trend": TREND,
               "entry": ("close", "open"), "exit": ("rsi50", "sma5", "t3", "t5", "t10"), "stop": ("none", 0.10, 0.20),
               "band": B3},
    "BB_BOLL": {"n": (10, 20, 50), "k": (2.0, 2.5, 3.0), "mode": ("revert", "break"), "side": ("long", "short"),
                "trend": ("none", "up200"), "entry": ("close", "open"), "exit": ("mid", "opp", "t5", "t10", "atr2"),
                "stop": ("none", 0.10, 0.20), "band": B3},
    "MA_CROSS": {"pair": ("5/20", "10/50", "20/100", "50/200", "10/20", "20/50"), "type": ("sma", "ema"),
                 "signal": ("cross", "pullback"), "side": ("long", "short"), "entry": ("close", "open"), 
                 "exit": ("crossback", "closefast", "atr3", "t20"), "stop": ("none", 0.10, 0.20), "band": B3},
    "DN_DONCHIAN": {"n": (10, 20, 55, 120, 252), "vol": (0.0, 1.5, 3.0), "loc": ("any", "top25"),
                    "side": ("long", "short"), "entry": ("close", "open"), "exit": ("low5", "low10", "low20", "atr2", "atr3", "t10", "t20", "t40"),
                    "stop": ("none", 0.08, 0.15), "band": B3},
    "FB_FAILBREAK": {"n": (20, 55, 252), "within": (1, 3), "vol": (0.0, 2.0), "side": ("short", "long"),
                     "exit": ("t3", "t5", "t10", "target20", "reclaim"), "stop": ("none", 0.10, 0.20), "band": B3},
    "CS_CANDLE": {"pattern": ("bull_engulf", "bear_engulf", "hammer", "shooting_star", "doji_low", "doji_high",
                              "inside_up", "inside_down", "outside_up", "outside_down", "nr7_up", "nr7_down",
                              "three_white", "three_black"),
                  "context": ("any", "move5", "move20", "move3"), "entry": ("close", "open"),
                  "exit": ("t1", "t3", "t5", "t10", "target10"), "stop": ("extreme", 0.10, "none"), "band": B3},
    "MC_MACD": {"set": ("12/26/9", "5/35/5", "3/10/16"), "signal": ("sig", "zero", "hist", "div"),
                "side": ("long", "short"), "trend": ("none", "up200", "down200"), "entry": ("close", "open"), 
                "exit": ("opp", "t5", "t10", "t20", "atr3"), "stop": ("none", 0.10, 0.20), "band": B3},
    "SO_STOCH": {"set": ("14/3", "5/3"), "lvl": (20, 10), "signal": ("cross", "leave"), "side": ("long", "short"),
                 "trend": ("none", "up200", "down200"), "entry": ("close", "open"), "exit": ("opp", "t3", "t5", "t10"),
                 "stop": ("none", 0.10, 0.20), "band": B3},
    "AX_ADX": {"thr": (20, 25, 30), "signal": ("dicross", "pullback"), "side": ("long", "short"), "entry": ("close", "open"),
               "exit": ("dicross", "atr3", "t10", "t20"), "stop": ("none", 0.10, 0.20), "band": B3},
    "VC_BASE": {"len": (10, 20, 40), "tight": (0.10, 0.20, 0.30), "prior": (0.0, 0.30, 1.00), "dry": ("any", "yes"),
                "bvol": (1.5, 3.0), "entry": ("close", "open"), "exit": ("low10", "low20", "ma10", "t20", "t60", "target20", "target50"),
                "stop": ("baselow", 0.08, 0.15), "band": B3},
    "EX_EXTEND": {"ma": (10, 20, 50), "atr": (3, 4, 6, 8), "side": ("short", "long"),
                  "confirm": ("none", "color", "lowerhigh"), "entry": ("close", "open"), 
                  "exit": ("backma", "t3", "t5", "t10", "target20", "target30"), "stop": ("none", "atr1", 0.20, "c50"),
                  "band": B3},
    "IB_IBS": {"thr": (0.05, 0.10, 0.20), "side": ("long", "short"), "trend": ("none", "up200", "down200"),
               "prior": ("any", "move10"), "exit": ("nextopen", "nextclose", "ibsrev", "t3"), "band": B3},
    "VO_CLIMAX": {"mult": (3, 5, 10), "candle": ("upwick", "lowwick", "bigup", "bigdown"),
                  "after": ("any", "up50", "down30"), "entry": ("close", "open"), "exit": ("t1", "t3", "t5", "t10", "target20"),
                  "stop": ("none", 0.10, 0.20), "band": B3},
    "DV_DIVERGE": {"rsi": (5, 14), "look": (20, 55), "side": ("long", "short"), "confirm": ("none", "color"),
                   "entry": ("close", "open"),
                   "exit": ("t5", "t10", "t20", "rsi50", "atr3"), "stop": ("none", 0.10, 0.20), "band": B3},
    "GP_GAPDAY": {"gap": (0.05, 0.10, 0.20, 0.30, 0.40), "dir": ("up", "down"), "close": ("cont", "fade"),
                  "entry": ("close", "open"), "exit": ("t1", "t3", "t5", "fill", "target20"),
                  "stop": ("none", 0.10, 0.20), "band": B3},
}
# the side each candle pattern trades
CANDLE_SIDE = {"bull_engulf": 1, "bear_engulf": -1, "hammer": 1, "shooting_star": -1, "doji_low": 1, "doji_high": -1,
               "inside_up": 1, "inside_down": -1, "outside_up": 1, "outside_down": -1, "nr7_up": 1, "nr7_down": -1,
               "three_white": 1, "three_black": -1}


# ---------------------------------------------------------------- indicators (cached per process)

_C: OrderedDict = OrderedDict()


def _cache(key, fn):
    if key in _C:
        _C.move_to_end(key)
        return _C[key]
    val = fn()
    _C[key] = val
    while len(_C) > 5:
        _C.popitem(last=False)
    return val


def _f(x) -> np.ndarray:
    return np.asarray(x, dtype=np.float32)


def sma(D: dict, n: int, field: str = "C") -> np.ndarray:
    return _cache(("sma", field, n), lambda: _f(pd.DataFrame(D[field]).rolling(n, min_periods=n).mean()))


def ema(D: dict, n: int) -> np.ndarray:
    return _cache(("ema", n), lambda: _f(pd.DataFrame(D["C"]).ewm(span=n, adjust=False, min_periods=n).mean()))


def rsi(D: dict, n: int) -> np.ndarray:
    def make():
        d = pd.DataFrame(np.diff(D["C"], axis=0, prepend=np.nan))
        up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
        dn = (-d).clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
        u, w = up.to_numpy(), dn.to_numpy()
        with np.errstate(invalid="ignore", divide="ignore"):
            r = np.where(w > 0, 100 - 100 / (1 + u / np.where(w > 0, w, 1.0)), np.where(u > 0, 100.0, 50.0))
        return _f(np.where(np.isfinite(u) & np.isfinite(w), r, np.nan))
    return _cache(("rsi", n), make)


def atr(D: dict, n: int = 14) -> np.ndarray:
    def make():
        C, H, L = D["C"], D["H"], D["L"]
        pc = vs._shift(C, 1)
        tr = np.fmax(H - L, np.fmax(np.abs(H - pc), np.abs(L - pc)))
        return _f(pd.DataFrame(tr).rolling(n, min_periods=n).mean())
    return _cache(("atr", n), make)


def hh(D: dict, n: int) -> np.ndarray:
    """Highest high of the n sessions before (not including) each day."""
    return _cache(("hh", n), lambda: _f(pd.DataFrame(D["H"]).rolling(n, min_periods=n).max().shift(1)))


def ll(D: dict, n: int) -> np.ndarray:
    return _cache(("ll", n), lambda: _f(pd.DataFrame(D["L"]).rolling(n, min_periods=n).min().shift(1)))


def std(D: dict, n: int) -> np.ndarray:
    return _cache(("std", n), lambda: _f(pd.DataFrame(D["C"]).rolling(n, min_periods=n).std()))


def vol_ratio(D: dict, E: dict) -> np.ndarray:
    """The day's volume over the 20 sessions before it."""
    return _cache(("vr",), lambda: _f(E["V"] / pd.DataFrame(E["V"]).rolling(20, min_periods=10).mean().shift(1)))


def macd(D: dict, fast: int, slow: int, sig: int) -> tuple[np.ndarray, np.ndarray]:
    def make():
        c = pd.DataFrame(D["C"])
        m = c.ewm(span=fast, adjust=False, min_periods=slow).mean() - c.ewm(span=slow, adjust=False,
                                                                            min_periods=slow).mean()
        return _f(m), _f(m.ewm(span=sig, adjust=False, min_periods=sig).mean())
    return _cache(("macd", fast, slow, sig), make)


def stoch(D: dict, n: int, d: int) -> tuple[np.ndarray, np.ndarray]:
    def make():
        hi = pd.DataFrame(D["H"]).rolling(n, min_periods=n).max()
        lo = pd.DataFrame(D["L"]).rolling(n, min_periods=n).min()
        k = 100 * (pd.DataFrame(D["C"]) - lo) / (hi - lo).replace(0, np.nan)
        return _f(k), _f(k.rolling(d, min_periods=d).mean())
    return _cache(("stoch", n, d), make)


def adx(D: dict, n: int = 14) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    def make():
        H, L, C = D["H"], D["L"], D["C"]
        up, dn = H - vs._shift(H, 1), vs._shift(L, 1) - L
        pdm = np.where((up > dn) & (up > 0), up, 0.0)
        mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
        pc = vs._shift(C, 1)
        tr = pd.DataFrame(np.fmax(H - L, np.fmax(np.abs(H - pc), np.abs(L - pc))))
        sm = {k: pd.DataFrame(v).ewm(alpha=1 / n, adjust=False, min_periods=n).mean() for k, v in
              (("p", pdm), ("m", mdm))}
        atr_ = tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean().replace(0, np.nan)
        pdi, mdi = 100 * sm["p"] / atr_, 100 * sm["m"] / atr_
        dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
        return _f(pdi), _f(mdi), _f(dx.ewm(alpha=1 / n, adjust=False, min_periods=n).mean())
    return _cache(("adx", n), make)


def _prev(x: np.ndarray, k: int = 1) -> np.ndarray:
    return vs._shift(x, k)


def _cross_up(a: np.ndarray, b) -> np.ndarray:
    return (a > b) & (_prev(a) <= (_prev(b) if isinstance(b, np.ndarray) else b))


def _cross_dn(a: np.ndarray, b) -> np.ndarray:
    return (a < b) & (_prev(a) >= (_prev(b) if isinstance(b, np.ndarray) else b))


def trend_ok(D: dict, trend: str) -> np.ndarray | bool:
    C = D["C"]
    if trend == "none":
        return True
    if trend == "up50":
        return C > sma(D, 50)
    s = sma(D, 200)
    return C > s if trend == "up200" else C < s


# ---------------------------------------------------------------- signals

def signals(D: dict, E: dict, family: str, g: dict) -> tuple[np.ndarray, np.ndarray, int, np.ndarray | None]:
    """(entry mask on the setup day, priority, side, exit mask or None)."""
    O, H, L, C = D["O"], D["H"], D["L"], D["C"]
    side = CANDLE_SIDE[g["pattern"]] if family == "CS_CANDLE" else (
        1 if g.get("side", g.get("dir", "long")) in ("long", "up") else -1)
    rng = np.maximum(H - L, 1e-9)
    ibs = (C - L) / rng
    body = np.abs(C - O)
    xm = None
    with np.errstate(invalid="ignore", divide="ignore"):
        if family == "RS_RSI":
            r = rsi(D, g["n"])
            m = (r <= g["lvl"]) if side > 0 else (r >= 100 - g["lvl"])
            m &= trend_ok(D, g["trend"])
            prio = np.abs(r - 50)
            if g["exit"] == "rsi50":
                xm = (r >= 50) if side > 0 else (r <= 50)
            elif g["exit"] == "sma5":
                xm = (C > sma(D, 5)) if side > 0 else (C < sma(D, 5))
        elif family == "BB_BOLL":
            mid, sd = sma(D, g["n"]), std(D, g["n"])
            up, lo = mid + g["k"] * sd, mid - g["k"] * sd
            if g["mode"] == "revert":
                m = (C < lo) if side > 0 else (C > up)
            else:
                m = (C > up) if side > 0 else (C < lo)
            m &= trend_ok(D, g["trend"])
            prio = np.abs(C - mid) / np.maximum(sd, 1e-9)
            if g["exit"] == "mid":
                xm = (C >= mid) if side > 0 else (C <= mid)
            elif g["exit"] == "opp":
                xm = (C >= up) if side > 0 else (C <= lo)
        elif family == "MA_CROSS":
            f, s = (int(x) for x in g["pair"].split("/"))
            fa, sl = (sma(D, f), sma(D, s)) if g["type"] == "sma" else (ema(D, f), ema(D, s))
            if g["signal"] == "cross":
                m = _cross_up(fa, sl) if side > 0 else _cross_dn(fa, sl)
            else:  # in trend, a close back across the fast average after touching it
                m = ((fa > sl) & (L <= fa) & (C > fa) & (_prev(C) > _prev(fa))) if side > 0 else \
                    ((fa < sl) & (H >= fa) & (C < fa) & (_prev(C) < _prev(fa)))
            prio = np.abs(fa / sl - 1)
            if g["exit"] == "crossback":
                xm = (fa < sl) if side > 0 else (fa > sl)
            elif g["exit"] == "closefast":
                xm = (C < fa) if side > 0 else (C > fa)
        elif family == "DN_DONCHIAN":
            n = g["n"]
            m = (C > hh(D, n)) if side > 0 else (C < ll(D, n))
            if g["vol"]:
                m &= vol_ratio(D, E) >= g["vol"]
            if g["loc"] == "top25":
                m &= (ibs >= 0.75) if side > 0 else (ibs <= 0.25)
            prio = vol_ratio(D, E)
            if g["exit"].startswith("low"):
                k = int(g["exit"][3:])
                xm = (C < ll(D, k)) if side > 0 else (C > hh(D, k))
        elif family == "FB_FAILBREAK":
            n, w = g["n"], g["within"]
            lvl_hi, lvl_lo = hh(D, n), ll(D, n)
            brk_hi = pd.DataFrame(H > lvl_hi).rolling(w, min_periods=1).max().shift(1).to_numpy() > 0
            brk_lo = pd.DataFrame(L < lvl_lo).rolling(w, min_periods=1).max().shift(1).to_numpy() > 0
            ref_hi = pd.DataFrame(np.where(H > lvl_hi, lvl_hi, np.nan)).ffill(limit=w).shift(1).to_numpy()
            ref_lo = pd.DataFrame(np.where(L < lvl_lo, lvl_lo, np.nan)).ffill(limit=w).shift(1).to_numpy()
            m = (brk_hi & (C < ref_hi)) if side < 0 else (brk_lo & (C > ref_lo))
            if g["vol"]:
                m &= vol_ratio(D, E) >= g["vol"]
            prio = vol_ratio(D, E)
            if g["exit"] == "reclaim":
                xm = (C > hh(D, n)) if side < 0 else (C < ll(D, n))
        elif family == "CS_CANDLE":
            m = candle(D, g["pattern"])
            ctx = g["context"]
            if ctx != "any":
                k, x = {"move3": (3, 0.15), "move5": (5, 0.20), "move20": (20, 0.50)}[ctx]
                mv = C / _prev(C, k) - 1
                m &= (mv <= -x) if side > 0 else (mv >= x)
            prio = body / rng
        elif family == "MC_MACD":
            f, s, sg = (int(x) for x in g["set"].split("/"))
            mc, sig = macd(D, f, s, sg)
            hist = mc - sig
            if g["signal"] == "sig":
                m = _cross_up(mc, sig) if side > 0 else _cross_dn(mc, sig)
            elif g["signal"] == "zero":
                m = _cross_up(mc, 0.0) if side > 0 else _cross_dn(mc, 0.0)
            elif g["signal"] == "hist":
                m = ((hist > _prev(hist)) & (_prev(hist) <= _prev(hist, 2)) & (hist < 0)) if side > 0 else \
                    ((hist < _prev(hist)) & (_prev(hist) >= _prev(hist, 2)) & (hist > 0))
            else:  # divergence: a 20-day closing extreme while MACD is above (below) its 20-day extreme
                lo20 = pd.DataFrame(C).rolling(20, min_periods=20).min().to_numpy()
                hi20 = pd.DataFrame(C).rolling(20, min_periods=20).max().to_numpy()
                mlo = pd.DataFrame(mc).rolling(20, min_periods=20).min().shift(1).to_numpy()
                mhi = pd.DataFrame(mc).rolling(20, min_periods=20).max().shift(1).to_numpy()
                m = ((C <= lo20) & (mc > mlo)) if side > 0 else ((C >= hi20) & (mc < mhi))
            m &= trend_ok(D, g["trend"])
            prio = np.abs(hist) / np.maximum(C, 1e-9)
            if g["exit"] == "opp":
                xm = (mc < sig) if side > 0 else (mc > sig)
        elif family == "SO_STOCH":
            n, d = (int(x) for x in g["set"].split("/"))
            k, dd = stoch(D, n, d)
            lo, hi = g["lvl"], 100 - g["lvl"]
            if g["signal"] == "cross":
                m = (_cross_up(k, dd) & (k < lo)) if side > 0 else (_cross_dn(k, dd) & (k > hi))
            else:
                m = _cross_up(k, float(lo)) if side > 0 else _cross_dn(k, float(hi))
            m &= trend_ok(D, g["trend"])
            prio = np.abs(k - 50)
            if g["exit"] == "opp":
                xm = (k >= hi) if side > 0 else (k <= lo)
        elif family == "AX_ADX":
            pdi, mdi, ax = adx(D)
            strong = ax >= g["thr"]
            if g["signal"] == "dicross":
                m = (_cross_up(pdi, mdi) if side > 0 else _cross_up(mdi, pdi)) & strong
            else:
                e20 = ema(D, 20)
                m = strong & (((pdi > mdi) & (L <= e20) & (C > e20)) if side > 0 else
                              ((mdi > pdi) & (H >= e20) & (C < e20)))
            prio = ax
            if g["exit"] == "dicross":
                xm = (mdi > pdi) if side > 0 else (pdi > mdi)
        elif family == "VC_BASE":
            n = g["len"]
            top, bot = hh(D, n), ll(D, n)
            m = ((top - bot) / np.maximum(_prev(C), 1e-9) <= g["tight"]) & (C > top) & (vol_ratio(D, E) >= g["bvol"])
            if g["prior"]:
                m &= _prev(C, n) / _prev(C, n + 60) - 1 >= g["prior"]
            if g["dry"] == "yes":
                v5 = pd.DataFrame(E["V"]).rolling(5, min_periods=5).mean().shift(1).to_numpy()
                v50 = pd.DataFrame(E["V"]).rolling(50, min_periods=30).mean().shift(1).to_numpy()
                m &= v5 < 0.7 * v50
            prio = vol_ratio(D, E)
            if g["exit"].startswith("low"):
                xm = C < ll(D, int(g["exit"][3:]))
            elif g["exit"] == "ma10":
                xm = C < sma(D, 10)
        elif family == "EX_EXTEND":
            base = ema(D, g["ma"])
            a = atr(D)
            m = (C >= base + g["atr"] * a) if side < 0 else (C <= base - g["atr"] * a)
            if g["confirm"] == "color":
                m &= (C < O) if side < 0 else (C > O)
            elif g["confirm"] == "lowerhigh":
                m &= (H < _prev(H)) if side < 0 else (L > _prev(L))
            prio = np.abs(C - base) / np.maximum(a, 1e-9)
            if g["exit"] == "backma":
                xm = (C <= base) if side < 0 else (C >= base)
        elif family == "IB_IBS":
            m = (ibs <= g["thr"]) if side > 0 else (ibs >= 1 - g["thr"])
            m &= trend_ok(D, g["trend"])
            if g["prior"] == "move10":
                r1 = C / _prev(C) - 1
                m &= (r1 <= -0.10) if side > 0 else (r1 >= 0.10)
            prio = np.abs(ibs - 0.5)
            if g["exit"] == "ibsrev":
                xm = (ibs >= 0.5) if side > 0 else (ibs <= 0.5)
        elif family == "VO_CLIMAX":
            cd = g["candle"]
            side = {"upwick": -1, "lowwick": 1, "bigup": -1, "bigdown": 1}[cd]
            shape = {"upwick": (H - np.fmax(O, C)) >= 0.6 * rng, "lowwick": (np.fmin(O, C) - L) >= 0.6 * rng,
                     "bigup": (C > O) & (body >= 0.7 * rng), "bigdown": (C < O) & (body >= 0.7 * rng)}[cd]
            m = (vol_ratio(D, E) >= g["mult"]) & shape
            if g["after"] != "any":
                mv = C / _prev(C, 5) - 1
                m &= (mv >= 0.5) if g["after"] == "up50" else (mv <= -0.3)
            prio = vol_ratio(D, E)
        elif family == "DV_DIVERGE":
            r = rsi(D, g["rsi"])
            n = g["look"]
            lo_n = pd.DataFrame(C).rolling(n, min_periods=n).min().to_numpy()
            hi_n = pd.DataFrame(C).rolling(n, min_periods=n).max().to_numpy()
            rlo = pd.DataFrame(r).rolling(n, min_periods=n).min().shift(1).to_numpy()
            rhi = pd.DataFrame(r).rolling(n, min_periods=n).max().shift(1).to_numpy()
            m = ((C <= lo_n) & (r > rlo + 5)) if side > 0 else ((C >= hi_n) & (r < rhi - 5))
            if g["confirm"] == "color":
                m &= (C > O) if side > 0 else (C < O)
            prio = np.abs(r - 50)
            if g["exit"] == "rsi50":
                xm = (r >= 50) if side > 0 else (r <= 50)
        elif family == "GP_GAPDAY":
            gap = O / _prev(C) - 1
            up = g["dir"] == "up"
            m = (gap >= g["gap"]) if up else (gap <= -g["gap"])
            cont = (C > O) if up else (C < O)
            m &= cont if g["close"] == "cont" else ~cont
            side = (1 if up else -1) * (1 if g["close"] == "cont" else -1)
            prio = np.abs(gap)
        else:
            raise KeyError(family)
    return np.asarray(m, bool), np.nan_to_num(np.asarray(prio, np.float32), nan=0.0), side, xm


def candle(D: dict, p: str) -> np.ndarray:
    O, H, L, C = D["O"], D["H"], D["L"], D["C"]
    po, pcl, ph, pl = _prev(O), _prev(C), _prev(H), _prev(L)
    rng = np.maximum(H - L, 1e-9)
    body = np.abs(C - O)
    with np.errstate(invalid="ignore"):
        if p == "bull_engulf":
            return (pcl < po) & (C > O) & (C >= po) & (O <= pcl)
        if p == "bear_engulf":
            return (pcl > po) & (C < O) & (C <= po) & (O >= pcl)
        if p == "hammer":
            return (np.fmin(O, C) - L >= 2 * body) & (H - np.fmax(O, C) <= 0.25 * rng)
        if p == "shooting_star":
            return (H - np.fmax(O, C) >= 2 * body) & (np.fmin(O, C) - L <= 0.25 * rng)
        if p in ("doji_low", "doji_high"):
            doji = body <= 0.1 * rng
            lo20, hi20 = ll(D, 20), hh(D, 20)
            return doji & ((L <= lo20) if p == "doji_low" else (H >= hi20))
        if p in ("inside_up", "inside_down"):
            inside_prev = (ph < _prev(H, 2)) & (pl > _prev(L, 2))
            return inside_prev & ((C > ph) if p == "inside_up" else (C < pl))
        if p == "outside_up":
            return (H > ph) & (L < pl) & (C > ph)
        if p == "outside_down":
            return (H > ph) & (L < pl) & (C < pl)
        if p in ("nr7_up", "nr7_down"):
            r = H - L
            nr7 = _prev(r) <= pd.DataFrame(r).rolling(7, min_periods=7).min().shift(1).to_numpy()
            return nr7 & ((C > ph) if p == "nr7_up" else (C < pl))
        if p in ("three_white", "three_black"):
            up = C > O if p == "three_white" else C < O
            step = (C > pcl) if p == "three_white" else (C < pcl)
            return up & _prev(up) & _prev(up, 2) & step & _prev(step)
    raise KeyError(p)


# ---------------------------------------------------------------- specs, paths, books

def _exit_params(D: dict, g: dict, side: int, xm) -> tuple[int, str, float, float, float]:
    """(hold, rule, target, trail fraction kind, close stop) of the exit dimension; trailing and stops in ATRs
    are turned into fractions per trade in ``specs``."""
    ex = g.get("exit", "t5")
    if ex.startswith("t") and ex[1:].isdigit():
        return int(ex[1:]), "time", np.nan, np.nan, np.nan
    if ex.startswith("target"):
        return 20, "time", int(ex[6:]) / 100, np.nan, np.nan
    if ex.startswith("atr"):
        return MAX_HOLD, "time", np.nan, float(ex[3:]), np.nan
    if ex == "nextopen":
        return 1, "open1", np.nan, np.nan, np.nan
    if ex == "nextclose":
        return 1, "time", np.nan, np.nan, np.nan
    if ex == "fill":
        return 5, "fill", np.nan, np.nan, np.nan
    return MAX_HOLD if xm is not None else 10, "time", np.nan, np.nan, np.nan  # an indicator exit, at most 40


def specs(D: dict, E: dict, family: str, g: dict) -> tuple[list, np.ndarray | None]:
    m, prio, side, xm = signals(D, E, family, g)
    base = (D["DV"] >= 1e6) & D["valid"] & v20.in_band(D["P"], g["band"])
    tt, jj = np.nonzero(m & base)
    T = D["C"].shape[0]
    entry_close = g.get("entry", "open") == "close" or g.get("exit") in ("nextopen", "nextclose")
    if not entry_close:
        ok = tt + 1 < T
        tt, jj = tt[ok], jj[ok]
    if not len(tt):
        return [], xm
    pr = prio[tt, jj]
    order = np.lexsort((-pr, tt))
    tt, jj, pr = tt[order], jj[order], pr[order]
    rank = np.arange(len(tt)) - np.searchsorted(tt, tt, side="left")
    keep = rank < TOP_K
    tt, jj, pr = tt[keep], jj[keep], pr[keep]
    hold, rule, target, trail_atr, cstop = _exit_params(D, g, side, xm)
    once = vs._once(tt, jj, max(hold, 1) if hold < MAX_HOLD else 20)
    a = atr(D) if (np.isfinite(trail_atr) or g.get("stop") == "atr1") else None
    C, H, L = D["C"], D["H"], D["L"]
    out = []
    for t, j, p in zip(tt[once], jj[once], pr[once]):
        c = float(C[t, j])
        stop = g.get("stop", "none")
        if stop == "none":
            sf, cs = np.nan, cstop
        elif stop == "c50":
            sf, cs = np.nan, 0.5
        elif stop == "atr1":
            sf, cs = float(a[t, j]) / c, cstop
        elif stop in ("extreme", "baselow"):
            ref = float(L[t, j]) if stop == "extreme" else float(ll(D, g.get("len", 10))[t, j])
            ref = ref if side > 0 else float(H[t, j])
            sf, cs = abs(c - ref) / c, cstop
        else:
            sf, cs = float(stop), cstop
        tr = float(trail_atr) * float(a[t, j]) / c if np.isfinite(trail_atr) else np.nan
        tg = target
        if rule == "fill":  # back to the gap day's prior close
            tg = abs(c - float(D["C"][t - 1, j])) / c if t > 0 else np.nan
        sf = sf if np.isfinite(sf) and sf > 0 else np.nan
        kind, t0 = ("close", int(t)) if entry_close else ("open", int(t + 1))
        out.append(v19.Spec(int(j), t0, kind, side, hold, sf, tg, tr, "time" if rule == "fill" else rule, float(p),
                            cs))
    return out, xm


def path(D: dict, s, xm: np.ndarray | None) -> tuple | None:
    """v19's daily path with an indicator exit (out at the first close where ``xm`` is true, from the day after
    the entry) and no costs: (first, gross returns, priority, weight before availability, raw price, nights,
    legs)."""
    O, H, L, C, P, new = D["O"], D["H"], D["L"], D["C"], D["P"], D["new"]
    T = C.shape[0]
    t, j, side = s.t, s.j, s.side
    if s.kind == "close":
        entry, first, raw, last = C[t, j], t + 1, P[t, j], min(T - 1, t + s.hold)
    else:
        entry, first, last = O[t, j], t, min(T - 1, t + s.hold - 1)
        raw = P[t - 1, j] * (entry / C[t - 1, j]) if t > 0 and C[t - 1, j] > 0 else P[t, j]
    if not np.isfinite(entry) or entry <= 0 or first > last or not np.isfinite(raw):
        return None
    stop = entry * (1 - side * s.stop) if np.isfinite(s.stop) else np.nan
    tgt = entry * (1 + side * s.target) if np.isfinite(s.target) else np.nan
    best, prev, rets, out_leg = entry, entry, [], 2
    for u in range(first, last + 1):
        if new[u, j] and (u > first or s.kind == "close"):
            break
        o, h, lo, c = O[u, j], H[u, j], L[u, j], C[u, j]
        if not np.isfinite(c):
            break
        o = o if np.isfinite(o) else c
        if s.rule == "open1":
            rets.append(side * (o - prev) / entry)
            out_leg = 0
            break
        eff = stop
        if np.isfinite(s.trail) and u > first:
            lvl = best * (1 - side * s.trail)
            eff = lvl if not np.isfinite(eff) else (min(eff, lvl) if side < 0 else max(eff, lvl))
        opened = u == first and s.kind == "open"
        if np.isfinite(eff) and ((h >= eff) if side < 0 else (lo <= eff)):
            extreme = h if side < 0 else lo
            px = v19._slip(eff, extreme) if opened else v19._past(-side, o, eff, extreme)
            rets.append(side * (px - prev) / entry)
            out_leg = 1
            break
        if np.isfinite(tgt) and ((lo <= tgt) if side < 0 else (h >= tgt)):
            px = tgt if opened else (min(o, tgt) if side < 0 else max(o, tgt))
            rets.append(side * (px - prev) / entry)
            out_leg = 1
            break
        rets.append(side * (c - prev) / entry)
        prev = c
        best = min(best, c) if side < 0 else max(best, c)
        if np.isfinite(s.cstop) and (c - entry * (1 - side * s.cstop)) * side <= 0:
            break
        if xm is not None and u > t and xm[u, j]:
            break
    if not rets:
        return None
    nights = max(len(rets) - (0 if s.kind == "close" else 1), 0)
    w = min(0.05, 0.01 * D["DV1"][t, j] / core.ACCOUNT) if np.isfinite(D["DV1"][t, j]) else 0.0
    ssr = side < 0 and s.kind == "open" and t > 0 and entry <= 0.9 * C[t - 1, j]
    return first, np.array(rets), s.prio, w, float(raw), nights, (0 if s.kind == "open" else 2, out_leg), side, \
        float(D["SO"][t, j]), ssr


def book(D: dict, sp: list, xm, table: dict, scenarios: list) -> tuple[dict, list, np.ndarray]:
    """Gross paths once; each scenario (name, model, slip half table, spread, fee multiple, gross flag) only
    changes the costs. Returns {name: daily returns}, paths and which the book took."""
    paths = [p for s in sp if (p := path(D, s, xm)) is not None]
    dates = D["dates"]
    if not paths:
        z = pd.Series(0.0, index=dates)
        return {sc[0]: z for sc in scenarios}, [], np.zeros(0, bool)
    raw = np.array([p[4] for p in paths])
    nights = np.array([p[5] for p in paths], float)
    legs = (np.array([p[6][0] for p in paths]), np.array([p[6][1] for p in paths]))
    side = np.array([p[7] for p in paths])
    so = np.array([p[8] for p in paths])
    ssr = np.array([p[9] for p in paths], float) * vs.SSR_EXTRA
    out, taken, net = {}, None, None
    for name, half, spread, fee, gross in scenarios:
        v19.set_costs("r4", v19.SLIP, half)
        cost, avail = v19._costs(raw, so, side, nights, (legs[0] == 0).astype(int) + (legs[1] == 0), table, spread,
                                 fee, gross, legs)
        cost = cost if gross else cost + ssr
        bp = [(p[0], p[1] - np.r_[cost[i], np.zeros(len(p[1]) - 1)], p[2], p[3] * float(avail[i]))
              for i, p in enumerate(paths)]
        s, tk = v19.book_paths(bp, dates)
        out[name] = s
        if taken is None:
            taken, net = tk, bp
    return out, net, taken


def placebo(D: dict, sp: list, rng: np.random.Generator, band: str) -> list:
    ok = v20.in_band(D["P1"], band) & (D["DV1"] >= 1e6) & D["valid1"]
    out = []
    for s in sp:
        cols = np.flatnonzero(ok[s.t])
        if len(cols):
            out.append(v19.Spec(int(rng.choice(cols)), s.t, s.kind, s.side, s.hold, s.stop, s.target, s.trail, s.rule,
                                s.prio, s.cstop))
    return out
