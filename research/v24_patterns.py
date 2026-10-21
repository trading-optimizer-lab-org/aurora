"""v24: long entries that need a pattern search on one-minute bars (micro pullbacks, ABCD, halts, chart patterns,
candlesticks, washouts, the Holy Grail). Pre-registered in docs/research/V24_PREREGISTRATION.md.

Each function returns (entry bar, entry price, stop reference, target height or nan). A signal known at a bar's close
enters at the next bar's open; a break of a level enters at the level (v19's stop-type fill). ``live`` marks the
bars on which an entry may be taken. Pattern extremes (pivots) are confirmed ``ROLL`` bars after they form, and of all
the patterns of a day the one whose entry comes first is traded (v23b: no later pattern may decide the trade).
"""
from __future__ import annotations

import numpy as np
from scipy.ndimage import maximum_filter1d, minimum_filter1d

from aurora.research import v14_intraday as vi
from aurora.research import v19_grid as v19
from aurora.research import v24_fast as fast

NONE = (-1, np.nan, np.nan, np.nan)
ROLL = 5
MOVES = {"m3": 0.03, "m6": 0.06, "m10": 0.10}
RETR = {"38-62": (0.382, 0.618), "24-50": (0.236, 0.50)}


def close_entry(x: np.ndarray, live: np.ndarray, o: np.ndarray, ref=None, tgt=None) -> tuple:
    j = vi.first_true(x & live, 0)
    if not 0 <= j < len(o) - 1:
        return NONE
    return j + 1, float(o[j + 1]), (float(ref[j]) if ref is not None else np.nan), \
        (float(tgt[j]) if tgt is not None else np.nan)


def _fill(o: np.ndarray, h: np.ndarray, k: int, level: float) -> float:
    return v19._past(1, float(o[k]), float(level), float(h[k]))


# ---------------------------------------------------------------- momentum: micro pullback, ABCD, halts

def micro(g: dict, b: tuple, live: np.ndarray) -> tuple:
    """An impulse (a new high of the day at least 3/6/10% above the low of the ten bars before), then one to three
    bars that stay below its high and retrace at most ``retrace`` of it; the entry at the break of the prior bar's
    high."""
    m, o, h, lo, c, v = b[:6]
    n = len(c)
    base = fast.rmin(lo, 11)
    with np.errstate(invalid="ignore", divide="ignore"):
        imp = (h >= np.maximum.accumulate(h)) & (h / base - 1 >= MOVES[g["impulse"]]) & (np.arange(n) >= 3)
    best: tuple | None = None
    for p in map(int, np.flatnonzero(imp)):
        if best is not None and p + 2 >= best[0]:
            break
        top, bs = float(h[p]), float(base[p])
        for k in range(p + 2, min(p + 5, n)):
            seg = slice(p + 1, k)
            if h[seg].max() > top or (top - lo[seg].min()) / max(top - bs, 1e-9) > g["retrace"]:
                break
            if not live[k] or h[k] <= h[k - 1]:
                continue
            if g["vol"] == "dry" and v[seg].mean() >= v[max(p - 2, 0):p + 1].mean():
                continue
            if best is None or k < best[0]:
                best = (k, _fill(o, h, k, h[k - 1]), float(lo[seg].min()), top - bs)
            break
    return best or NONE


def abcd(g: dict, b: tuple, live: np.ndarray) -> tuple:
    """A: the low before B; B: a high of the day at least ``run`` above A; C: a pullback of ``retr`` of AB without a
    new high. Entry at C (the first bar closing above the prior bar's high once the pullback is deep enough) or at
    the break of B; the target C + AB (the AB = CD move)."""
    o, h, lo, c = b[1], b[2], b[3], b[4]
    n = len(c)
    run, (dmin, dmax) = g["run"], RETR[g["retr"]]
    if h.max() / max(lo.min(), 1e-9) - 1 < run:  # no move of that size today: no signal can fire (speed only)
        return NONE
    H, L, C, O, LV = h.tolist(), lo.tolist(), c.tolist(), o.tolist(), live.tolist()
    hi, hi_i, a, low_so_far = H[0], 0, L[0], L[0]
    cmin, armed, valid = np.inf, False, True
    for i in range(1, n):
        if g["entry"] == "breakB" and armed and valid and H[i] > hi and LV[i] and hi / a - 1 >= run:
            e = _fill(o, h, i, hi)
            return i, e, cmin, (cmin + hi - a - e) if cmin + hi - a > e else np.nan
        low_so_far = min(low_so_far, L[i])
        if H[i] > hi:
            hi, hi_i, a = H[i], i, low_so_far
            cmin, armed, valid = np.inf, False, True
            continue
        if not valid or hi / a - 1 < run:
            continue
        cmin = min(cmin, L[i])
        depth = (hi - cmin) / max(hi - a, 1e-9)
        if depth > dmax:
            valid = False
            continue
        armed = armed or depth >= dmin
        if g["entry"] == "atC" and armed and i > hi_i + 1 and C[i] > H[i - 1] and LV[i] and i < n - 1:
            e = O[i + 1]
            return i + 1, e, cmin, (cmin + hi - a - e) if cmin + hi - a > e else np.nan
    return NONE


def halt(g: dict, b: tuple, live: np.ndarray) -> tuple:
    """A trading pause (four or more missing minutes) after a 5-bar move of ``move`` up or down; entry at the
    resumption's open if it reopens at or above the last price, on the first close above the resumption bar's high
    (hold), or on the first bar closing above the prior red bar's high (dip)."""
    m, o, h, lo, c = b[:5]
    n = len(c)
    up, mv = g["dir"] == "up", g["move"]
    best: tuple | None = None
    for k in map(int, np.flatnonzero(np.diff(m.astype(int)) >= 5) + 1):
        if k < 6 or k >= n - 1:
            continue
        if best is not None and k >= best[0]:
            break
        pre = c[k - 6:k - 1]
        r = c[k - 1] / pre.min() - 1 if up else c[k - 1] / pre.max() - 1
        if (r < mv) if up else (r > -mv):
            continue
        cand = None
        if g["entry"] == "resume":
            if live[k] and o[k] >= c[k - 1]:
                cand = (k, float(o[k]), float(lo[k - 6:k].min()) if up else float(lo[k - 1]), np.nan)
        elif g["entry"] == "hold":
            for i in range(k + 1, min(k + 10, n - 1)):
                if c[i] > h[k] and live[i]:
                    cand = (i + 1, float(o[i + 1]), float(lo[k:i + 1].min()), np.nan)
                    break
        else:
            for i in range(k + 2, min(k + 16, n - 1)):
                if c[i - 1] < o[i - 1] and c[i] > h[i - 1] and live[i]:
                    cand = (i + 1, float(o[i + 1]), float(lo[k:i + 1].min()), np.nan)
                    break
        if cand is not None and (best is None or cand[0] < best[0]):
            best = cand
    return best or NONE


# ---------------------------------------------------------------- chart patterns (PX)

def _pivots(x: np.ndarray, low: bool) -> np.ndarray:
    f = minimum_filter1d if low else maximum_filter1d
    return np.flatnonzero(x == f(x, 2 * ROLL + 1, mode="nearest"))


def _earliest(piv: np.ndarray, test) -> tuple | None:
    """Over the pivots in order, the pattern whose break comes first; ``test(index in piv)`` -> (break bar, ref,
    height) or None. A pivot is known ROLL bars after it."""
    best = None
    for t in range(len(piv)):
        if best is not None and piv[t] + ROLL >= best[0]:
            break
        r = test(t)
        if r is not None and (best is None or r[0] < best[0]):
            best = r
    return best


def pattern(g: dict, b: tuple, live: np.ndarray) -> tuple:
    m, o, h, lo, c, v = b[:6]
    n = len(c)
    big = g["size"] == "large"
    brk_ok = live & ((fast.rv(v) >= 2.0) if g["vol"] else True)
    p = g["pattern"]
    tol, gap = (0.03, 10) if big else (0.01, 5)

    def brk(level: float, start: int) -> int:
        k = vi.first_true((c > level) & brk_ok, start)
        return k if 0 <= k < n - 1 else -1

    if p in ("inv_hs", "triple_bottom"):
        piv = _pivots(lo, True)

        def test(t):
            if t < 2:
                return None
            p1, p2, p3 = piv[t - 2], piv[t - 1], piv[t]
            if p2 - p1 < gap or p3 - p2 < gap:
                return None
            a, mid, z = lo[p1], lo[p2], lo[p3]
            if p == "inv_hs":
                if not (mid < a and mid < z and abs(z / a - 1) <= tol):
                    return None
                ref, bottom = float(z), float(mid)
            else:
                trio = (a, mid, z)
                if max(trio) / min(trio) - 1 > tol:
                    return None
                ref = bottom = float(min(trio))
            neck = float(h[p1:p3 + 1].max())
            k = brk(neck, p3 + ROLL)
            return (k, ref, neck - bottom) if k >= 0 else None

        best = _earliest(piv, test)
    elif p == "cup_handle":
        piv = _pivots(h, False)
        dmin = 0.08 if big else 0.03

        def test(t):
            r2 = piv[t]
            for r1 in piv[:t]:  # the earliest matching left rim
                if r2 - r1 < 2 * gap or abs(h[r2] / h[r1] - 1) > tol:
                    continue
                rim, cup = float(max(h[r1], h[r2])), float(lo[r1:r2 + 1].min())
                if (rim - cup) / rim < dmin:
                    continue
                k = brk(rim, r2 + ROLL)
                if k < 0:
                    return None
                handle = float(lo[r2 + 1:k + 1].min())
                return (k, handle, rim - cup) if handle >= rim - 0.5 * (rim - cup) else None
            return None

        best = _earliest(piv, test)
    else:
        with np.errstate(invalid="ignore", divide="ignore"):
            if p == "rectangle":
                w, width = (60, 0.04) if big else (30, 0.02)
                hh, ll = fast.prev(fast.full(fast.rmax(h, w), w)), fast.prev(fast.full(fast.rmin(lo, w), w))
                x = (hh / ll - 1 <= width) & (c > hh)
                ref, tgt = ll, hh - ll
            elif p == "pennant":
                pole, w2 = (0.15, 20) if big else (0.06, 10)
                half = w2 // 2
                h2, l2 = fast.prev(fast.full(fast.rmax(h, half), half)), fast.prev(fast.full(fast.rmin(lo, half), half))
                h1, l1 = np.r_[np.full(half, np.nan), h2[:-half]], np.r_[np.full(half, np.nan), l2[:-half]]
                b15 = fast.prev(fast.full(fast.rmin(lo, 15), 15))
                base = np.r_[np.full(w2, np.nan), b15[:-w2]]
                x = (h2 < h1) & (l2 > l1) & (h1 / base - 1 >= pole) & (c > h2)
                ref, tgt = l2, h1 - base
            else:  # htf: a pole of 20% / 40% from the session's low, then a flag no deeper than a quarter of it
                pole, w = (0.40, 20) if big else (0.20, 10)
                hh, ll = fast.prev(fast.full(fast.rmax(h, w), w)), fast.prev(fast.full(fast.rmin(lo, w), w))
                lowb = np.r_[np.full(w + 1, np.nan), np.minimum.accumulate(lo)[:-(w + 1)]] if n > w + 1 else \
                    np.full(n, np.nan)
                x = (hh / lowb - 1 >= pole) & (hh - ll <= 0.25 * (hh - lowb)) & (c > hh)
                ref, tgt = ll, hh - lowb
        return close_entry(x & brk_ok, np.ones(n, bool), o, ref, tgt)
    if best is None:
        return NONE
    k, ref, height = best
    return k + 1, float(o[k + 1]), ref, height


# ---------------------------------------------------------------- candlesticks (CK)

CANDLES = ("hammer", "bull_engulf", "morning_star", "piercing", "three_white", "harami", "tweezer", "marubozu",
           "dragonfly")


def candle_mask(name: str, O, H, L, C) -> np.ndarray:
    rng = np.maximum(H - L, 1e-9)
    body = np.abs(C - O)
    lows, ups = np.minimum(O, C) - L, H - np.maximum(O, C)
    po, pc_, pl = fast.prev(O), fast.prev(C), fast.prev(L)
    prng = fast.prev(rng)
    green, red = C > O, C < O
    pred = fast.prev(red.astype(float), 0.0) > 0
    with np.errstate(invalid="ignore"):
        if name == "hammer":
            return (lows >= 2 * body) & (ups <= 0.3 * rng) & (lows >= 0.5 * rng)
        if name == "bull_engulf":
            return pred & green & (C >= po) & (O <= pc_)
        if name == "morning_star":
            p2o, p2c = fast.prev(po), fast.prev(pc_)
            big2 = (p2o - p2c) >= 0.6 * fast.prev(prng)
            return big2 & (np.abs(pc_ - po) <= 0.3 * prng) & green & (C > (p2o + p2c) / 2)
        if name == "piercing":
            return pred & green & (O <= pc_) & (C > (po + pc_) / 2) & (C < po)
        if name == "three_white":
            g3 = fast.rsum(green.astype(float), 3) == 3
            return g3 & (C > pc_) & (pc_ > fast.prev(pc_)) & (O >= po) & (O <= pc_)
        if name == "harami":
            return pred & ((po - pc_) >= 0.6 * prng) & green & (O >= pc_) & (C <= po)
        if name == "tweezer":
            return pred & green & (np.abs(L - pl) <= 0.001 * L)
        if name == "marubozu":
            return green & (body >= 0.9 * rng)
        if name == "dragonfly":
            return (body <= 0.1 * rng) & (lows >= 0.7 * rng)
    raise KeyError(name)


def candles(g: dict, b: tuple, line: np.ndarray, lv: dict, live: np.ndarray) -> tuple:
    ends, O, H, L, C, V = fast.agg(b, g["tf"])
    x = candle_mask(g["pattern"], O, H, L, C)
    ctx = g["context"]
    with np.errstate(invalid="ignore", divide="ignore"):
        if ctx == "drop":
            x &= C <= 0.97 * fast.prev(fast.rmax(C, 10))
        elif ctx == "lod":
            x &= L <= 1.005 * np.minimum.accumulate(L)
        elif ctx == "vwap":
            le = line[ends]
            x &= (np.abs(L / le - 1) <= 0.005) & (C > le)
        elif ctx == "level":
            near = np.zeros(len(C), bool)
            for name in ("pdl", "pdc", "pml", "l5"):
                lvl = lv.get(name, np.nan)
                if np.isfinite(lvl) and lvl > 0:
                    near |= np.abs(L / lvl - 1) <= 0.005
            x &= near
        else:  # trend: EMA20 above EMA50 of the timeframe, the candle's low through EMA20 and its close above
            e20 = fast.ema(C, 20)
            x &= (e20 > fast.ema(C, 50)) & (L <= e20) & (C >= e20) & (np.arange(len(C)) >= 20)
        if g["vol"]:
            x &= V >= 2 * fast.prev(fast.rmean(V, 20))
    x &= live[ends] & (b[0][ends] >= 5)
    k = vi.first_true(x, 0)
    if k < 0 or ends[k] >= len(b[0]) - 1:
        return NONE
    j = int(ends[k]) + 1
    return j, float(b[1][j]), float(L[max(k - 2, 0):k + 1].min()), np.nan


# ---------------------------------------------------------------- washout (WO) and the Holy Grail (HG)

def washout(g: dict, b: tuple, live: np.ndarray) -> tuple:
    """``reds`` red bars in a row, a low ``drop`` below the high of the day so far and a minute of ``climax`` times
    the usual volume among them; entry on the first higher high (stop-type at the prior bar's high) or the first
    close above the three bars before, within ten bars."""
    m, o, h, lo, c, v = b[:6]
    n = len(c)
    idx = np.arange(n)
    red = c < o
    rl = idx - np.maximum.accumulate(np.where(~red, idx, -1))
    with np.errstate(invalid="ignore"):
        drop = lo <= (1 - g["drop"]) * np.maximum.accumulate(h)
        clim = fast.rmax(np.nan_to_num(fast.rv(v)), g["reds"]) >= g["climax"]
    best: tuple | None = None
    for s in map(int, np.flatnonzero((rl >= g["reds"]) & drop & clim)):
        if best is not None and s + 1 >= best[0]:
            break
        cand = None
        for k in range(s + 1, min(s + 11, n)):
            if g["confirm"] == "hh":
                if h[k] > h[k - 1] and live[k]:
                    cand = (k, _fill(o, h, k, h[k - 1]), float(lo[:k].min()), np.nan)
                    break
            elif k >= 3 and k < n - 1 and c[k] > h[k - 3:k].max() and live[k]:
                cand = (k + 1, float(o[k + 1]), float(lo[:k + 1].min()), np.nan)
                break
        if cand is not None and (best is None or cand[0] < best[0]):
            best = cand
    return best or NONE


def grail(g: dict, b: tuple, line: np.ndarray, live: np.ndarray) -> tuple:
    """Raschke's Holy Grail: ADX above ``adx`` with +DI above -DI, a bar of the timeframe touching the line (EMA20,
    EMA9 or VWAP); entry at the break of that bar's high within the next three bars of the timeframe."""
    m, o, h = b[0], b[1], b[2]
    n = len(m)
    tf = g["tf"]
    ends, O, H, L, C, V = fast.agg(b, tf)
    adx, pdi, mdi = fast.dmi(H, L, C)
    tl = {"ema20": fast.ema(C, 20), "ema9": fast.ema(C, 9), "vwap": line[ends]}[g["touch"]]
    with np.errstate(invalid="ignore"):
        touch = (adx > g["adx"]) & (pdi > mdi) & (L <= tl) & (H >= tl)
    best: tuple | None = None
    for i in map(int, np.flatnonzero(touch)):
        e_i = int(ends[i])
        if best is not None and e_i + 1 >= best[0]:
            break
        for k in range(e_i + 1, n):
            if m[k] > m[e_i] + 3 * tf:
                break
            if h[k] > H[i] and live[k]:
                if best is None or k < best[0]:
                    best = (k, _fill(o, h, k, H[i]), float(L[i]), np.nan)
                break
    return best or NONE
