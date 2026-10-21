"""v24: fast trailing indicators on one-minute (or aggregated) bars. Pre-registered in
docs/research/V24_PREREGISTRATION.md.

Every value at bar i uses bars 0..i only. scipy's C filters stand in for pandas' rolling and ewm (about ten times
faster on a session's 390 bars); tests/test_v24.py checks them against pandas. ``indicator`` returns, for one of
the sixteen indicators of family IX, the long signal and the opposite signal as masks over the bars.
"""
from __future__ import annotations

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from scipy.ndimage import maximum_filter1d, minimum_filter1d
from scipy.signal import lfilter

INDICATORS = ("supertrend", "psar", "heikin", "ichimoku", "cci", "willr", "mfi", "obv", "aroon", "don20", "don55",
              "kelt", "roc", "trix", "adx", "stack")


def prev(x: np.ndarray, fill=np.nan) -> np.ndarray:
    return np.r_[fill, x[:-1]]


def ema(x: np.ndarray, span: float) -> np.ndarray:
    """pandas' ewm(span, adjust=False).mean()."""
    a = 2.0 / (span + 1.0)
    return lfilter([a], [1.0, a - 1.0], x, zi=[(1.0 - a) * x[0]])[0]


def wilder(x: np.ndarray, n: int) -> np.ndarray:
    """pandas' ewm(alpha=1/n, adjust=False).mean()."""
    a = 1.0 / n
    return lfilter([a], [1.0, a - 1.0], x, zi=[(1.0 - a) * x[0]])[0]


def rmax(x: np.ndarray, w: int) -> np.ndarray:
    """Trailing max over the last w bars (fewer at the start)."""
    return maximum_filter1d(x, w, origin=(w - 1) // 2, mode="nearest")


def rmin(x: np.ndarray, w: int) -> np.ndarray:
    return minimum_filter1d(x, w, origin=(w - 1) // 2, mode="nearest")


def rmean(x: np.ndarray, w: int) -> np.ndarray:
    """Trailing mean over exactly w bars (nan before)."""
    cs = np.cumsum(np.r_[0.0, x])
    out = np.full(len(x), np.nan)
    if len(x) >= w:
        out[w - 1:] = (cs[w:] - cs[:-w]) / w
    return out


def rsum(x: np.ndarray, w: int) -> np.ndarray:
    return rmean(x, w) * w


def rstd(x: np.ndarray, w: int) -> np.ndarray:
    m, m2 = rmean(x, w), rmean(x * x, w)
    return np.sqrt(np.maximum(m2 - m * m, 0.0) * w / max(w - 1, 1))


def full(x: np.ndarray, w: int) -> np.ndarray:
    """x with nan before bar w - 1 (a window not yet complete)."""
    out = x.astype(float).copy()
    out[:w - 1] = np.nan
    return out


def rsi(c: np.ndarray, n: int) -> np.ndarray:
    d = np.diff(c, prepend=c[0])
    up, dn = wilder(np.clip(d, 0, None), n), wilder(np.clip(-d, 0, None), n)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(dn > 0, 100 - 100 / (1 + up / dn), 100.0)


def true_range(h: np.ndarray, lo: np.ndarray, c: np.ndarray) -> np.ndarray:
    pc = prev(c, c[0])
    return np.maximum(h - lo, np.maximum(np.abs(h - pc), np.abs(lo - pc)))


def up_cross(a, b) -> np.ndarray:
    pb = prev(b) if isinstance(b, np.ndarray) else b
    with np.errstate(invalid="ignore"):
        return (a > b) & (prev(a) <= pb)


def dn_cross(a, b) -> np.ndarray:
    pb = prev(b) if isinstance(b, np.ndarray) else b
    with np.errstate(invalid="ignore"):
        return (a < b) & (prev(a) >= pb)


def agg(b: tuple, k: int) -> tuple:
    """k-minute bars: (index of each bucket's last one-minute bar, open, high, low, close, volume); k = 1: the bars."""
    m = b[0].astype(int)
    if k == 1:
        return np.arange(len(m)), b[1], b[2], b[3], b[4], b[5]
    key = m // k
    ends = np.r_[np.flatnonzero(np.diff(key)), len(m) - 1]
    starts = np.r_[0, ends[:-1] + 1]
    return (ends, b[1][starts], np.maximum.reduceat(b[2], starts), np.minimum.reduceat(b[3], starts), b[4][ends],
            np.add.reduceat(b[5], starts))


def rv(v: np.ndarray) -> np.ndarray:
    """A minute's volume over the average of the 30 minutes before (v23's _rv)."""
    with np.errstate(invalid="ignore", divide="ignore"):
        avg = prev(rmean(v, 30))
        early = np.r_[np.nan, np.cumsum(v)[:-1] / np.arange(1, len(v))]  # 10-29 bars: the mean so far
        avg = np.where(np.isnan(avg) & (np.arange(len(v)) >= 10), early, avg)
        return v / avg


# ---------------------------------------------------------------- the sixteen indicators of IX

def _supertrend(h, lo, c, n=10, mult=3.0):
    atr = wilder(true_range(h, lo, c), n)
    mid = (h + lo) / 2
    ub, lb = mid + mult * atr, mid - mult * atr
    fu, fl, up = ub.copy(), lb.copy(), np.ones(len(c), bool)
    for i in range(1, len(c)):
        fu[i] = ub[i] if (ub[i] < fu[i - 1] or c[i - 1] > fu[i - 1]) else fu[i - 1]
        fl[i] = lb[i] if (lb[i] > fl[i - 1] or c[i - 1] < fl[i - 1]) else fl[i - 1]
        up[i] = (c[i] > fu[i - 1]) if not up[i - 1] else not (c[i] < fl[i - 1])
    sig, opp = up & ~prev(up, True), ~up & prev(up, False)
    sig[:n] = opp[:n] = False  # the ATR's warm-up
    return sig, opp


def _psar(h, lo, step=0.02, top=0.2):
    n = len(h)
    longs = np.zeros(n, bool)
    if n < 3:
        return longs, longs
    lng, af, ep, sar = True, step, h[0], lo[0]
    for i in range(1, n):
        sar = sar + af * (ep - sar)
        if lng:
            sar = min(sar, lo[i - 1], lo[i - 2] if i > 1 else lo[i - 1])
            if lo[i] < sar:
                lng, sar, ep, af = False, ep, lo[i], step
            elif h[i] > ep:
                ep, af = h[i], min(af + step, top)
        else:
            sar = max(sar, h[i - 1], h[i - 2] if i > 1 else h[i - 1])
            if h[i] > sar:
                lng, sar, ep, af = True, ep, h[i], step
            elif lo[i] < ep:
                ep, af = lo[i], min(af + step, top)
        longs[i] = lng
    sig, opp = longs & ~prev(longs, True), ~longs & prev(longs, False)
    sig[:5] = opp[:5] = False
    return sig, opp


def indicator(name: str, o, h, lo, c, v, line) -> tuple[np.ndarray, np.ndarray]:
    """(long signal, opposite signal) over the bars; ``line`` is VWAP at each bar."""
    n = len(c)
    with np.errstate(invalid="ignore", divide="ignore"):
        if name == "supertrend":
            return _supertrend(h, lo, c)
        if name == "psar":
            return _psar(h, lo)
        if name == "heikin":
            hc = (o + h + lo + c) / 4
            ho = lfilter([0.5], [1.0, -0.5], prev(hc, (o[0] + c[0]) / 2), zi=[0.5 * (o[0] + c[0]) / 2])[0]
            ho[0] = (o[0] + c[0]) / 2
            green = hc > ho
            red3 = (rsum((~green).astype(float), 3) == 3)
            return green & prev(red3, False), ~green & prev(green, False)
        if name == "ichimoku":
            ten = (full(rmax(h, 9), 9) + full(rmin(lo, 9), 9)) / 2
            kij = (full(rmax(h, 26), 26) + full(rmin(lo, 26), 26)) / 2
            sa = np.r_[np.full(26, np.nan), ((ten + kij) / 2)[:-26]] if n > 26 else np.full(n, np.nan)
            sb_ = (full(rmax(h, 52), 52) + full(rmin(lo, 52), 52)) / 2
            sb = np.r_[np.full(26, np.nan), sb_[:-26]] if n > 26 else np.full(n, np.nan)
            return up_cross(ten, kij) & (c > np.fmax(sa, sb)) & np.isfinite(sa) & np.isfinite(sb), c < kij
        if name == "cci":
            tp = (h + lo + c) / 3
            cci = np.full(n, np.nan)
            if n >= 20:
                win = sliding_window_view(tp, 20)
                mu = win.mean(axis=1)
                md = np.abs(win - mu[:, None]).mean(axis=1)
                cci[19:] = (tp[19:] - mu) / np.where(md > 0, 0.015 * md, np.nan)
            return up_cross(cci, -100.0), dn_cross(cci, 100.0)
        if name == "willr":
            hh, ll = full(rmax(h, 14), 14), full(rmin(lo, 14), 14)
            wr = -100 * (hh - c) / np.where(hh > ll, hh - ll, np.nan)
            return up_cross(wr, -80.0), dn_cross(wr, -20.0)
        if name == "mfi":
            tp = (h + lo + c) / 3
            mf = tp * v
            dtp = tp - prev(tp, tp[0])
            pos, neg = rsum(np.where(dtp > 0, mf, 0.0), 14), rsum(np.where(dtp < 0, mf, 0.0), 14)
            mfi = np.where(neg > 0, 100 - 100 / (1 + pos / np.where(neg > 0, neg, 1.0)), 100.0)
            mfi[np.isnan(pos)] = np.nan
            return up_cross(mfi, 20.0), dn_cross(mfi, 80.0)
        if name == "obv":
            obv = np.cumsum(np.sign(c - prev(c, c[0])) * v)
            top = rmax(obv, 30)
            sig = (obv >= top) & (obv > prev(top)) & (c < prev(rmax(c, 30))) & (np.arange(n) >= 29)
            return sig, obv < ema(obv, 20)
        if name == "aroon":
            up, dn = np.full(n, np.nan), np.full(n, np.nan)
            if n >= 26:
                up[25:] = 100 * sliding_window_view(h, 26).argmax(axis=1) / 25
                dn[25:] = 100 * sliding_window_view(lo, 26).argmin(axis=1) / 25
            return up_cross(up, 70.0) & (dn < 30), dn > up
        if name in ("don20", "don55"):
            w, x = (20, 10) if name == "don20" else (55, 20)
            return (c > prev(full(rmax(h, w), w))), (c < prev(full(rmin(lo, x), x)))
        if name == "kelt":
            mid = ema(c, 20)
            return up_cross(c, mid + 2 * wilder(true_range(h, lo, c), 20)) & (np.arange(n) >= 20), c < mid
        if name == "roc":
            roc = c / np.r_[np.full(10, np.nan), c[:-10]] - 1 if n > 10 else np.full(n, np.nan)
            return up_cross(roc, 0.0), dn_cross(roc, 0.0)
        if name == "trix":
            e3 = ema(ema(ema(c, 15), 15), 15)
            tx = e3 / prev(e3) - 1
            tx[:45] = np.nan
            return up_cross(tx, 0.0), dn_cross(tx, 0.0)
        if name == "adx":
            adx, pdi, mdi = dmi(h, lo, c)
            return (adx > 25) & up_cross(pdi, mdi), mdi > pdi
        if name == "stack":
            e9, e20 = ema(c, 9), ema(c, 20)
            s = (e9 > e20) & (e20 > line)
            return s & ~prev(s, True) & (np.arange(n) >= 20), c < e20
    raise KeyError(name)


def dmi(h: np.ndarray, lo: np.ndarray, c: np.ndarray, n: int = 14) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(ADX, +DI, -DI), Wilder's smoothing; nan for the first 2n bars."""
    upm, dnm = h - prev(h, h[0]), prev(lo, lo[0]) - lo
    pdm = np.where((upm > dnm) & (upm > 0), upm, 0.0)
    mdm = np.where((dnm > upm) & (dnm > 0), dnm, 0.0)
    tr = wilder(true_range(h, lo, c), n)
    with np.errstate(invalid="ignore", divide="ignore"):
        pdi = 100 * wilder(pdm, n) / tr
        mdi = 100 * wilder(mdm, n) / tr
        dx = 100 * np.abs(pdi - mdi) / (pdi + mdi)
    adx = wilder(np.nan_to_num(dx), n)
    adx[:2 * n] = np.nan
    return adx, pdi, mdi
