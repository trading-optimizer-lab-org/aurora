"""v46: the book's trades on one-minute bars with technical analysis of every kind (V46_PREREGISTRATION.md): entry
triggers, close entry timing into the after-hours, stops, TA exits, overnight covers before the open, execution and
meta-label filters on v44's engine.

  stage1  one shard of the 164 one-dimension replays, each with the 55 filters at the four cost sets, plus the symbol
          halves at base costs
  select  the stage 2 grid from stage 1's 2018-2022 results
  stage2  one shard of the 98,304 factorial replays, each with the 8 chosen filters at the four cost sets
  final   the walk-forward choice, the bootstrap, the halves, Q1-Q4 and V46_REPORT.md
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import multiprocessing as mp
import sys
import time
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


M44 = _script("run_v44m")
R43 = M44.R43
R40, R32, R29 = M44.R40, M44.R32, M44.R29
core, vi, st = M44.core, M44.vi, M44.st
OPEN, LAST, AH, LEVEL, TASKS = R43.OPEN, R43.LAST, R43.AH, R43.LEVEL, R43.TASKS
FILL, PART, LIQ, EFILL = M44.FILL, M44.PART, M44.LIQ, M44.EFILL
QUICK = R29.QUICK
GAIN, MAX_RUIN, E2K = 1.15, 0.025, 2_000.0
EARLY_END = 2022
CHECK = (22_006.0, 0.001)
K2, KF = 7, 7  # stage 2: the top values of each replay dimension and the top filters, besides the base

# ---------------------------------------------------------------- the grid

TRIG_KINDS = tuple(f"T{k}" for k in range(9, 25))
WINDOWS = ((15, "skip"), (30, "skip"), (30, "deadline"), (90, "deadline"), (180, "deadline"))
TRIGS: list = ["none"] + [(k, w, to) for k in TRIG_KINDS for w, to in WINDOWS]
CENTRIES: list = (["auction", ("mkt", 951), ("mkt", 955)] + [("ah", s) for s in (5, 15, 30, 60, 120, 180, 235)]
                  + [("ahlim", x) for x in (0.02, 0.05, 0.10)] + [("ahvwap", 60)])
STOPS: list = (["shield", "none"] + [("hod", x) for x in (0.01, 0.03, 0.05, 0.10)] + [("atr", k) for k in (5, 10, 20)]
               + [("pct", x) for x in (0.10, 0.20, 0.30, 0.50)])
TEXITS: list = (["none"] + [("rsi_lt", n, x) for n, x in ((14, 15), (14, 20), (14, 25), (7, 10), (7, 15))]
                + [("rsi_up", 14, x) for x in (25, 30)] + [("bb_low", 20, k) for k in (2.0, 2.5, 3.0)]
                + [("vwap_rc", m) for m in (10, 30, 60)] + [("ema_up", 9, 20), ("ema_up", 20, 50), ("macd_up",)]
                + [("st_up", 10, k) for k in (2, 3)] + [("psar_up",)] + [("ha_green", k) for k in (2, 3)]
                + [("hammer",)] + [("capit", x) for x in (3.0, 5.0)] + [("don_hi", n) for n in (15, 30, 60)]
                + [("stoch_up", 20)] + [("time", s) for s in (600, 630, 660, 690, 720, 780, 840, 900, 930)])
PMX: list = (["open"] + [("at", s) for s in (240, 300, 360, 420, 480, 510, 540, 555, 565)]
             + [("tgt", x) for x in (0.03, 0.05, 0.10, 0.15)] + [("pmstop", x) for x in (0.05, 0.10, 0.20)]
             + [("ah", s) for s in (5, 60, 235)])
EXES = ("auction", "twap3", "passive")
DIMS = (TRIGS, CENTRIES, STOPS, TEXITS, PMX, EXES)
DNAMES = ("trigger", "close entry", "stop", "TA exit", "overnight cover", "execution")
NF_CONT = ("rsi14", "rsi7", "macd_h", "bb_pb", "bb_w", "atr_p", "stoch_k", "ema9_20", "ema50", "cci20", "willr14",
           "mfi14", "obv30", "vwap_sl30", "don30", "roc5", "roc30", "upwick5", "green_run", "ha_run", "skew60",
           "since_hod")
NF_BIN = ("st_dir", "psar_dir")
NFEATS = NF_CONT + NF_BIN
FILTERS: list = (["none"] + [("terc", f, s) for f in range(len(NF_CONT)) for s in ("top", "bottom")]
                 + [("bin", f, v) for f in range(len(NF_BIN)) for v in (1, -1)]
                 + [("model", mdl, a) for mdl in M44.MODELS for a in M44.ACTS])
BASE_COMBO = (0, 0, 0, 0, 0, 0)
S1: list[tuple] = [BASE_COMBO] + [tuple(v if i == d else 0 for i in range(len(DIMS)))
                                  for d in range(len(DIMS)) for v in range(1, len(DIMS[d]))]

_G: dict = {"ind": {}, "delay": {}, "flt": {}, "xm": {}, "pre": {}}


def combo_name(c: tuple) -> str:
    return "; ".join(f"{DNAMES[d]} {_vname(DIMS[d][v])}" for d, v in enumerate(c))


def _vname(x) -> str:
    return x if isinstance(x, str) else " ".join(str(a) for a in x)


def filter_name(f: int) -> str:
    x = FILTERS[f]
    if x == "none":
        return "none"
    if x[0] == "terc":
        return f"skip {NF_CONT[x[1]]} {x[2]} tercile"
    if x[0] == "bin":
        return f"skip {NF_BIN[x[1]]} = {x[2]}"
    return f"{x[1]} {'size x(0.5+p)' if x[2] == 'size' else f'skip p<0.{x[2][1:]}'}"


# ---------------------------------------------------------------- indicators (each from the bars up to it)

def ema(x: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(x).ewm(span=n, adjust=False).mean().to_numpy(copy=True)


def wilder(x: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(x).ewm(alpha=1 / n, adjust=False).mean().to_numpy(copy=True)


def rsi(c: np.ndarray, n: int) -> np.ndarray:
    d = np.diff(c, prepend=np.nan)
    up, dn = wilder(np.nan_to_num(np.maximum(d, 0)), n), wilder(np.nan_to_num(np.maximum(-d, 0)), n)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.where(dn > 0, 100 - 100 / (1 + up / dn), 100.0)
    out[: n] = np.nan
    return out


def atr(h: np.ndarray, lo: np.ndarray, c: np.ndarray, n: int = 14) -> np.ndarray:
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - lo, np.maximum(np.abs(h - pc), np.abs(lo - pc)))
    out = wilder(tr, n)
    out[: n - 1] = np.nan
    return out


def supertrend(h: np.ndarray, lo: np.ndarray, c: np.ndarray, n: int, k: float) -> np.ndarray:
    """+1 up, -1 down; 0 before the ATR exists."""
    a = atr(h, lo, c, n)
    mid = (h + lo) / 2
    up, dn = mid - k * a, mid + k * a
    d = np.zeros(len(c))
    fu, fd = np.nan, np.nan
    for i in range(len(c)):
        if not np.isfinite(a[i]):
            continue
        fu = up[i] if not np.isfinite(fu) or c[i - 1] < fu else max(up[i], fu)
        fd = dn[i] if not np.isfinite(fd) or c[i - 1] > fd else min(dn[i], fd)
        prev = d[i - 1] if i else 0
        d[i] = 1 if c[i] > fd else -1 if c[i] < fu else (prev or 1)
    return d


def psar(h: np.ndarray, lo: np.ndarray, af0: float = 0.02, step: float = 0.02, mx: float = 0.2) -> np.ndarray:
    """+1 up, -1 down (the trend of the SAR after each bar)."""
    n = len(h)
    d = np.zeros(n)
    if n < 2:
        return d
    up = h[1] >= h[0]
    sar, ep, af = (lo[0], h[0], af0) if up else (h[0], lo[0], af0)
    d[0] = 1 if up else -1
    for i in range(1, n):
        sar = sar + af * (ep - sar)
        if up:
            sar = min(sar, lo[i - 1], lo[i - 2] if i > 1 else lo[i - 1])
            if lo[i] < sar:
                up, sar, ep, af = False, ep, lo[i], af0
            elif h[i] > ep:
                ep, af = h[i], min(af + step, mx)
        else:
            sar = max(sar, h[i - 1], h[i - 2] if i > 1 else h[i - 1])
            if h[i] > sar:
                up, sar, ep, af = True, ep, h[i], af0
            elif lo[i] < ep:
                ep, af = lo[i], min(af + step, mx)
        d[i] = 1 if up else -1
    return d


def heikin(o: np.ndarray, h: np.ndarray, lo: np.ndarray, c: np.ndarray) -> np.ndarray:
    """Heikin-Ashi green (True) bars."""
    hc = (o + h + lo + c) / 4
    ho = np.empty(len(c))
    ho[0] = (o[0] + c[0]) / 2
    for i in range(1, len(c)):
        ho[i] = (ho[i - 1] + hc[i - 1]) / 2
    return hc > ho


def run_len(x: np.ndarray) -> np.ndarray:
    """Consecutive True values ending at each bar."""
    out = np.zeros(len(x), int)
    for i, v in enumerate(x):
        out[i] = out[i - 1] + 1 if v and i else int(bool(v))
    return out


def stoch(h: np.ndarray, lo: np.ndarray, c: np.ndarray, n: int = 14, s: int = 3) -> np.ndarray:
    hh = pd.Series(h).rolling(n, min_periods=n).max().to_numpy()
    ll = pd.Series(lo).rolling(n, min_periods=n).min().to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        k = np.where(hh > ll, (c - ll) / (hh - ll) * 100, 50.0)
    k[~np.isfinite(hh)] = np.nan
    return pd.Series(k).rolling(s, min_periods=s).mean().to_numpy()


def prior_max(h: np.ndarray, n: int) -> np.ndarray:
    """The highest high of the n bars before each bar (nan until there are n)."""
    return pd.Series(h).rolling(n, min_periods=n).max().shift(1).to_numpy()


def session_ind(B: dict) -> dict | None:
    """The regular session's indicators on its bars (``idx``: their steps) and the premarket's high and low."""
    idx = np.flatnonzero(np.isfinite(B["o"][OPEN:LAST + 1])) + OPEN
    if len(idx) < 10:
        return None
    o, h, lo, c, v, vw = (np.asarray(B[k][idx], float) for k in ("o", "h", "l", "c", "v", "vw"))
    v = np.where(np.isfinite(v), v, 0.0)
    pm = np.isfinite(B["o"][AH:OPEN])
    pmh = float(np.nanmax(B["h"][AH:OPEN])) if pm.any() else np.nan
    pml = float(np.nanmin(B["l"][AH:OPEN])) if pm.any() else np.nan
    line = vi.vwap(c, v, vw)
    m = ema(c, 12) - ema(c, 26)
    mid = pd.Series(c).rolling(20, min_periods=20).mean().to_numpy()
    sd = pd.Series(c).rolling(20, min_periods=20).std(ddof=0).to_numpy()
    med = np.array([np.median(v[:k + 1]) for k in range(len(v))])
    out = {"o": o, "h": h, "lo": lo, "c": c, "line": line, "rsi14": rsi(c, 14), "rsi7": rsi(c, 7),
           "mh": m - ema(m, 9), "mid": mid, "sd": sd, "e9": ema(c, 9), "e20": ema(c, 20), "e50": ema(c, 50),
           "st2": supertrend(h, lo, c, 10, 2), "st3": supertrend(h, lo, c, 10, 3), "ps": psar(h, lo),
           "hag": heikin(o, h, lo, c).astype(float), "sk": stoch(h, lo, c), "z": st.zscore(c, line, "sess"),
           "vrel": np.where(med > 0, v / np.maximum(med, 1e-12), np.nan)}
    out = {k: np.asarray(x, np.float32) for k, x in out.items()}
    return {**out, "idx": idx.astype(np.int16), "pmh": pmh, "pml": pml}


def _ind_job(key: tuple) -> tuple:
    B = R43.timeline(*key)
    return key, (session_ind(B) if B is not None else None)


def _cross_dn(x: np.ndarray, lvl: float) -> np.ndarray:
    return np.r_[False, (x[:-1] >= lvl) & (x[1:] < lvl)]


def _cross_up(x: np.ndarray, lvl) -> np.ndarray:
    return np.r_[False, (x[:-1] < lvl) & (x[1:] >= lvl)]


def _flip(d: np.ndarray, to: int) -> np.ndarray:
    return np.r_[False, (d[1:] == to) & (d[:-1] == -to)]


def trigger_steps(F: dict | None) -> np.ndarray:
    """The step of the first bar of each entry trigger T9-T24 (10,000: none), from the bars up to it."""
    out = np.full(len(TRIG_KINDS), 10_000)
    if F is None:
        return out
    idx = F["idx"]
    o, h, lo, c = (F[k].astype(float) for k in ("o", "h", "lo", "c"))
    hod = np.r_[-np.inf, np.maximum.accumulate(h)[:-1]]  # the session high before each bar
    newhi = h > hod
    body, rng_ = np.abs(c - o), np.maximum(h - lo, 1e-12)
    upw = h - np.maximum(o, c)
    ha = F["hag"] > 0.5
    ha_run = np.r_[0, run_len(ha)[:-1]]
    first15 = idx < OPEN + 15
    orl = lo[first15].min() if first15.any() else np.nan
    pmh, pml = F["pmh"], F["pml"]
    above_pmh = np.maximum.accumulate(h > pmh) if np.isfinite(pmh) else np.zeros(len(c), bool)
    last_hi = np.maximum.accumulate(np.where(newhi, np.arange(len(c)), 0))  # the bar of the session high so far
    prev_hi = np.r_[0, last_hi[:-1]]
    with np.errstate(invalid="ignore"):
        masks = (
            _cross_dn(F["rsi14"], 70),                                          # T9
            _cross_dn(F["rsi7"], 80),                                           # T10
            np.r_[False, (F["mh"][:-1] >= 0) & (F["mh"][1:] < 0)],              # T11
            np.r_[False, (c[:-1] > (F["mid"] + 2 * F["sd"])[:-1]) & (c[1:] <= (F["mid"] + 2 * F["sd"])[1:])],  # T12
            np.r_[False, (F["e9"][:-1] >= F["e20"][:-1]) & (F["e9"][1:] < F["e20"][1:])],  # T13
            _flip(F["st3"], -1),                                                # T14
            _flip(F["ps"], -1),                                                 # T15
            ~ha & (ha_run >= 3),                                                # T16
            newhi & (upw >= 2 * body) & (upw >= 0.6 * rng_),                    # T17
            np.r_[False, above_pmh[:-1]] & (c < pmh),                           # T18
            c < pml,                                                            # T19
            (c < orl) & ~first15,                                               # T20
            _cross_dn(F["sk"], 80),                                             # T21
            newhi & (F["vrel"] >= 3) & (c < (h + lo) / 2),                      # T22
            ~newhi & (h >= 0.99 * hod) & (np.arange(len(c)) - prev_hi >= 10) & (c < o),  # T23
            _cross_dn(F["z"], 2),                                               # T24
        )
    for i, m in enumerate(masks):
        hit = np.flatnonzero(m)
        if len(hit):
            out[i] = int(idx[hit[0]])
    return out


def delay_of(steps: np.ndarray, tr: int) -> int | None:
    """v44's delay rule for TRIGS[tr]: the bar after the trigger, the deadline, or None (skipped)."""
    if TRIGS[tr] == "none":
        return 0
    kind, w, to = TRIGS[tr]
    s = int(steps[TRIG_KINDS.index(kind)])
    if s <= OPEN + w - 1:
        return s + 1 - OPEN
    return None if to == "skip" else w


def texit_of(tx: int):
    """TEXITS[tx] as replay's ``xmask`` (None: no TA exit)."""
    x = TEXITS[tx]
    if x == "none":
        return None

    def f(B: dict, u: int, j: int, e: float) -> np.ndarray:
        key = (tx, u, j)
        if key not in _G["xm"]:
            _G["xm"][key] = _texit_mask(x, _G["ind"].get((u, j)))
        return _G["xm"][key]

    return f


def _texit_mask(x: tuple, F: dict | None) -> np.ndarray:
    """The 960-step mask of a TA exit on a session's indicators (none set off without them)."""
    out = np.zeros(960, bool)
    if F is not None:
        kind = x[0]
        idx = F["idx"]
        o, h, lo, c = (F[k].astype(float) for k in ("o", "h", "lo", "c"))
        with np.errstate(invalid="ignore"):
            if kind == "rsi_lt":
                m = F[f"rsi{x[1]}"] < x[2]
            elif kind == "rsi_up":
                m = _cross_up(F[f"rsi{x[1]}"], x[2])
            elif kind == "bb_low":
                m = lo <= F["mid"] - x[2] * F["sd"]
            elif kind == "vwap_rc":
                below = np.r_[0, run_len(c < F["line"])[:-1]]
                m = (c > F["line"]) & (below >= x[1])
            elif kind == "ema_up":
                a, b = F[f"e{x[1]}"], F[f"e{x[2]}"]
                m = np.r_[False, (a[:-1] <= b[:-1]) & (a[1:] > b[1:])]
            elif kind == "macd_up":
                m = np.r_[False, (F["mh"][:-1] < 0) & (F["mh"][1:] >= 0)]
            elif kind == "st_up":
                m = _flip(F[f"st{x[2]}"], 1)
            elif kind == "psar_up":
                m = _flip(F["ps"], 1)
            elif kind == "ha_green":
                g = F["hag"] > 0.5
                r = run_len(g)
                m = (r == x[1]) & (np.arange(len(g)) >= x[1])
            elif kind == "hammer":
                lod = np.r_[np.inf, np.minimum.accumulate(lo)[:-1]]
                body, rg = np.abs(c - o), np.maximum(h - lo, 1e-12)
                low_w = np.minimum(o, c) - lo
                m = (lo < lod) & (low_w >= 2 * body) & (low_w >= 0.6 * rg)
            elif kind == "capit":
                rg = np.maximum(h - lo, 1e-12)
                m = (F["vrel"] >= x[1]) & (c < o) & ((np.minimum(o, c) - lo) >= 0.5 * rg)
            elif kind == "don_hi":
                m = h > prior_max(h, x[1])
            elif kind == "stoch_up":
                m = _cross_up(F["sk"], x[1])
            else:
                m = idx >= x[1]
        out[idx] = m
    return out


def pmx_of(px: int):
    """PMX[px] as replay's ``pmx`` (None: the open auction as now)."""
    x = PMX[px]
    if x == "open":
        return None
    kind, a = x

    def f(B: dict, u: int, j: int, e: float, ref: float, lo: int) -> int | None:
        if kind in ("at", "ah"):
            return max(int(a) - 1, lo)  # set off the minute before: filled from the first bar at or after it
        ok = np.isfinite(B["c"][:OPEN]) & (np.arange(OPEN) >= lo)
        if kind == "tgt":
            hit = np.flatnonzero(ok & (B["c"][:OPEN] <= ref * (1 - a)))
        else:
            hit = np.flatnonzero(ok & (np.arange(OPEN) >= AH) & (B["c"][:OPEN] >= ref * (1 + a)))
        return int(hit[0]) if len(hit) else None

    return f


def _hs(price: float) -> float:
    return float(core.half_spread(np.array([max(float(price), 0.01)]), "mid")[0])


def centry_of(ce: int):
    """CENTRIES[ce] for close entries as an ``exe`` part: (e, es) or None (no trade); None: the auction."""
    x = CENTRIES[ce]
    if x == "auction":
        return None
    kind, a = x

    def f(it: dict, m: dict, e: float, es: int):
        t, j = int(it["t"]), int(it["j"])
        if kind == "mkt":
            B = R43.timeline(t, j)
            if B is None:
                return e, es
            s = M44._at(B["o"], int(a))
            return (float(B["o"][s]), es) if s <= LAST else (e, es)
        B1 = R43.timeline(t + 1, j)
        if B1 is None:
            return None
        o, hh, v, vw = B1["o"][:AH], B1["h"][:AH], B1["v"][:AH], B1["vw"][:AH]
        if kind == "ah":
            s = M44._at(o, int(a), AH - 1)
            return (float(o[s]) * (1 - _hs(o[s])), s) if s < AH else None
        if kind == "ahlim":
            lim = e * (1 + a)  # e: the closing auction price
            hit = np.flatnonzero(np.isfinite(o) & (hh >= lim))
            return (float(max(o[hit[0]], lim)), int(hit[0])) if len(hit) else None
        w = np.isfinite(o[: int(a)]) & np.isfinite(v[: int(a)]) & (v[: int(a)] > 0)
        if not w.any():
            return None
        px = float(np.sum(vw[: int(a)][w] * v[: int(a)][w]) / np.sum(v[: int(a)][w]))
        return px * (1 - _hs(px)), int(np.flatnonzero(w)[-1])

    return f


def exe_of(ce: int, ex: int):
    """The entry hook of a close entry timing and an open entry execution (None: both as now)."""
    fc, fo = centry_of(ce), M44.exe_of(M44.EXES.index(EXES[ex]))
    if fc is None and fo is None:
        return None

    def f(it: dict, m: dict, e: float, es: int):
        g = fo if m["kind"] == "open" else fc
        return (e, es) if g is None else g(it, m, e, es)

    return f


def stop_of(sp: int):
    """STOPS[sp] as replay's ``stopf`` (None: the shield's)."""
    x = STOPS[sp]
    if x == "shield":
        return None
    if x == "none":
        return lambda it, m, e, es, S: np.inf
    kind, a = x

    def f(it: dict, m: dict, e: float, es: int, S: float) -> float:
        if kind == "pct":
            return e * (1 + a)
        B = R43.timeline(int(it["t"]), int(it["j"]))
        if B is None:
            return S
        hi = (es if m["kind"] == "open" else 950) - 1
        seg = slice(AH, max(hi, AH) + 1)
        if kind == "hod":
            hmax = np.nanmax(B["h"][seg]) if np.isfinite(B["h"][seg]).any() else np.nan
            if not np.isfinite(hmax):
                return S
            return max(float(hmax), e) * (1 + a)
        ok = np.isfinite(B["o"][seg])
        h_, l_, c_ = (np.asarray(B[k][seg], float)[ok] for k in ("h", "l", "c"))
        if len(c_) < 15:
            return S
        av = atr(h_, l_, c_)[-1]
        return e + a * float(av) if np.isfinite(av) else S

    return f


# ---------------------------------------------------------------- the features at the entry and the filters

def trade_features(it: dict, kind: str) -> np.ndarray:
    """The 24 new features of a trade at its entry: open entries from the bars 04:00-09:29, close entries from the
    session's bars to 15:49."""
    f = np.full(len(NFEATS), np.nan)
    B = R43.timeline(int(it["t"]), int(it["j"]))
    if B is None:
        return f
    sl = slice(AH, OPEN) if kind == "open" else slice(OPEN, 950)
    ok = np.isfinite(B["o"][sl])
    o, h, lo, c, v = (np.asarray(B[k][sl], float)[ok] for k in ("o", "h", "l", "c", "v"))
    v = np.where(np.isfinite(v), v, 0.0)
    n = len(c)
    if n < 15:
        return f
    with np.errstate(invalid="ignore", divide="ignore"):
        f[0], f[1] = rsi(c, 14)[-1], rsi(c, 7)[-1]
        mm = ema(c, 12) - ema(c, 26)
        f[2] = (mm - ema(mm, 9))[-1] / c[-1]
        if n >= 20:
            mid, sd = c[-20:].mean(), c[-20:].std()
            f[3] = (c[-1] - (mid - 2 * sd)) / (4 * sd) if sd > 0 else np.nan
            f[4] = 4 * sd / mid if mid > 0 else np.nan
            tp = (h + lo + c) / 3
            md = np.mean(np.abs(tp[-20:] - tp[-20:].mean()))
            f[9] = (tp[-1] - tp[-20:].mean()) / (0.015 * md) if md > 0 else np.nan
        f[5] = atr(h, lo, c)[-1] / c[-1]
        f[6] = stoch(h, lo, c)[-1]
        f[7] = ema(c, 9)[-1] / ema(c, 20)[-1] - 1
        f[8] = c[-1] / ema(c, 50)[-1] - 1
        hh, ll = h[-14:].max(), lo[-14:].min()
        f[10] = (c[-1] - hh) / (hh - ll) * 100 if hh > ll else np.nan
        tp = (h + lo + c) / 3
        mf = tp * v
        dtp = np.diff(tp)
        pos, neg = mf[1:][dtp > 0][-14:].sum(), mf[1:][dtp < 0][-14:].sum()
        f[11] = 100 - 100 / (1 + pos / neg) if neg > 0 else 100.0
        w = min(30, n - 1)
        obv = np.cumsum(np.sign(np.diff(c)) * v[1:])
        f[12] = (obv[-1] - obv[-w]) / max(v[-w:].sum(), 1e-12) if w > 1 else np.nan
        line = vi.vwap(c, v, np.asarray(B["vw"][sl], float)[ok])
        f[13] = line[-1] / line[-w - 1] - 1 if n > w else np.nan
        h30, l30 = h[-30:].max(), lo[-30:].min()
        f[14] = (c[-1] - l30) / (h30 - l30) if h30 > l30 else np.nan
        f[15] = c[-1] / c[-6] - 1 if n > 5 else np.nan
        f[16] = c[-1] / c[-31] - 1 if n > 30 else np.nan
        rg = np.maximum(h - lo, 1e-12)
        f[17] = float(np.mean(((h - np.maximum(o, c)) / rg)[-5:]))
        f[18] = float(run_len(c > o)[-1])
        f[19] = float(run_len(heikin(o, h, lo, c))[-1])
        if n >= 61:
            r = np.diff(np.log(c[-61:]))
            sd = r.std()
            f[20] = float(np.mean((r - r.mean()) ** 3) / sd ** 3) if sd > 0 else np.nan
        f[21] = (n - 1 - int(np.argmax(h))) / n
        f[22] = supertrend(h, lo, c, 10, 3)[-1] or np.nan
        f[23] = psar(h, lo)[-1] or np.nan
    return np.where(np.isfinite(f), f, np.nan)


def fit_filters(keys: list[tuple], years: np.ndarray, XN: np.ndarray, XM: np.ndarray, y: np.ndarray,
                ends: np.ndarray) -> dict:
    """Per trade: the tercile flags of the 22 continuous features, the two binary features' values, and the two
    models' probability (on v44's and the new features), all from the trades of the years before."""
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression

    nc = len(NF_CONT)
    out = {k: {"skip": np.zeros(2 * nc, bool), "bin": XN[i, nc:].copy(), "p": np.full(len(M44.MODELS), np.nan)}
           for i, k in enumerate(keys)}
    for Y in sorted(set(int(v) for v in years))[1:]:
        tr, te = (years < Y) & (ends < Y), np.flatnonzero(years == Y)
        if tr.sum() < 30 or not len(te):
            continue
        X = XN[:, :nc]
        cuts = np.nanquantile(np.where(tr[:, None], X, np.nan), [1 / 3, 2 / 3], axis=0)
        enough = np.isfinite(X[tr]).sum(axis=0) >= 30
        with np.errstate(invalid="ignore"):
            top, bot = (X[te] > cuts[1]) & enough, (X[te] < cuts[0]) & enough
        med = np.nanmedian(XM[tr], axis=0)
        med = np.where(np.isfinite(med), med, 0.0)
        Xtr = np.where(np.isfinite(XM[tr]), XM[tr], med)
        Xte = np.where(np.isfinite(XM[te]), XM[te], med)
        mu, sd = Xtr.mean(axis=0), Xtr.std(axis=0)
        sd = np.where(sd > 0, sd, 1.0)
        p = np.full((len(te), len(M44.MODELS)), np.nan)
        if len(set(y[tr])) == 2:
            lr = LogisticRegression(max_iter=2000).fit((Xtr - mu) / sd, y[tr])
            p[:, 0] = lr.predict_proba((Xte - mu) / sd)[:, 1]
            gb = GradientBoostingClassifier(max_depth=3, n_estimators=100, random_state=46).fit(Xtr, y[tr])
            p[:, 1] = gb.predict_proba(Xte)[:, 1]
        for r, i in enumerate(te):
            z = out[keys[i]]
            z["skip"][0::2], z["skip"][1::2] = top[r], bot[r]
            z["p"] = p[r]
    for Y in sorted(set(int(v) for v in years))[:1]:  # the first year: no filter acts
        for i in np.flatnonzero(years == Y):
            out[keys[i]]["bin"][:] = np.nan
    return out


def filtered(items: list[dict], f: int) -> list[dict]:
    x = FILTERS[f]
    if x == "none":
        return items
    out = []
    for it in items:
        z = _G["flt"].get(M44._key(it))
        if z is None:
            out.append(it)
            continue
        if x[0] == "terc":
            if z["skip"][2 * x[1] + (x[2] == "bottom")]:
                continue
        elif x[0] == "bin":
            if z["bin"][x[1]] == x[2]:
                continue
        else:
            p = float(z["p"][M44.MODELS.index(x[1])])
            if np.isfinite(p):
                if x[2] == "size":
                    it = {**it, "w": float(it["w"]) * (0.5 + p)}
                elif p < (0.4 if x[2] == "p40" else 0.5):
                    continue
        out.append(it)
    return out


# ---------------------------------------------------------------- the account

def items_for(its: list[dict], metas: list[dict], combo: tuple, half: int | None = None) -> tuple[list, list]:
    """v44's items with the combination's hooks; extra half-spreads on after-hours market entries and on covers
    before the open."""
    tr, ce, sp, tx, px, ex = combo
    exe, stopf, xm, pmx = exe_of(ce, ex), stop_of(sp), texit_of(tx), pmx_of(px)
    out, recs = [], []
    for it, m in zip(its, metas):
        if half is not None and M44.half_of(it["sym"]) != half:
            continue
        delay: int | None = 0
        if m["kind"] == "open" and tr:
            delay = _G["delay"].get((int(it["t"]), int(it["j"])), {}).get(tr, 0)
            if delay is None:
                continue
        rec = R43.replay(it, m, (delay, 1.0, "hold", None, None, 1.0), FILL, PART, EFILL, exe=exe, xmask=xm,
                         stopf=stopf, pmx=pmx)
        if rec is None:
            continue
        c0 = float(it["raw0"]) - float(it["r"][0])
        r = np.array(rec["g"], float)
        r[0] -= c0
        for i, q, k in rec.get("pmx", []):  # the after-hours entries' spread is in their entry price
            x = q * _hs(float(it["price"]))
            r[i] -= x
            rec["G"][i] = rec["G"][i].copy()
            rec["G"][i][k:] -= x
        rec["cost"] = c0 + float(it.get("loc", 0.0))
        recs.append(rec)
        out.append({**it, "r": r, "raw0": rec["g"][0], "i0": rec["u"][0], "nights": rec["nights"],
                    "_rec": len(recs) - 1})
    return out, recs


def book_returns(combo: tuple, f: int, level: float, task: str, half: int | None = None) -> np.ndarray:
    R43.LEVEL = level
    its, metas = R43._G["its"][(float(level), task)]
    items, recs = items_for(its, metas, combo, half)
    return M44.account(filtered(items, f), recs)


# ---------------------------------------------------------------- setup

def setup(args, levels=(LEVEL,), procs: int = 1) -> None:
    M44.setup(args, levels, procs)
    D = R43._G["D"]
    t0 = time.time()
    keys = list(M44._G["sf"])
    with mp.get_context("fork").Pool(procs) as pool:
        _G["ind"] = dict(pool.map(_ind_job, keys, chunksize=16))
    seen: dict = {}
    for lv in levels:
        for task in TASKS:
            for it, m in zip(*R43._G["its"][(float(lv), task)]):
                seen.setdefault(M44._key(it), (it, m["kind"]))
    _G["delay"] = {}
    for (t, j, _), (_, kind) in seen.items():
        if kind == "open" and (t, j) not in _G["delay"]:
            steps = trigger_steps(_G["ind"].get((t, j)))
            _G["delay"][(t, j)] = {tr: delay_of(steps, tr) for tr in range(1, len(TRIGS))}
    fkeys, X44 = M44._G["X"]
    pos = {k: i for i, k in enumerate(fkeys)}
    XN = np.stack([trade_features(seen[k][0], seen[k][1]) for k in fkeys]) if fkeys else np.zeros((0, len(NFEATS)))
    R43.LEVEL = LEVEL
    its, metas = R43._G["its"][(LEVEL, "base")]
    items, _ = M44.items_for(its, metas, 0, 0, 0, 0, 0)
    net = {M44._key(it): float(np.sum(it["r"])) - float(it.get("loc", 0.0)) for it in items}
    last = {M44._key(it): min(int(it["t"]) + len(it["r"]) - 1, len(D["dates"]) - 1) for it in items}
    have = [pos[k] for k in fkeys if k in net]
    yrs = np.array([pd.Timestamp(D["dates"][fkeys[i][0]]).year for i in have], int)
    ends = np.array([pd.Timestamp(D["dates"][last[fkeys[i]]]).year for i in have], int)
    XM = np.hstack([X44, XN])
    _G["flt"] = fit_filters([fkeys[i] for i in have], yrs, XN[have], XM[have],
                            np.array([net[fkeys[i]] > 0 for i in have], int), ends)
    _G["XN"] = (fkeys, XN)
    print(json.dumps({"v46_setup_s": round(time.time() - t0), "with_ind": sum(v is not None for v in _G["ind"].values()),
                      "coverage": {NFEATS[i]: round(float(np.isfinite(XN[:, i]).mean()), 3) for i in range(len(NFEATS))}
                      if len(XN) else {}}), flush=True)


# ---------------------------------------------------------------- the stages

def _unit(job: tuple) -> tuple:
    combo, flts, halves = job
    ys = R43._G["ys"]
    S = np.full((len(flts), len(TASKS), len(ys), 2), np.nan, np.float32)
    H = np.full((2, len(ys), 2), np.nan, np.float32)
    for ti, task in enumerate(TASKS):
        its, metas = R43._G["its"][(LEVEL, task)]
        items, recs = items_for(its, metas, combo)
        for fi, f in enumerate(flts):
            S[fi, ti] = R40.year_stats(M44.account(filtered(items, f), recs)[R43._G["pos"]], R43._G["years"], ys)
    if halves:
        its, metas = R43._G["its"][(LEVEL, "base")]
        for h in (0, 1):
            items, recs = items_for(its, metas, combo, h)
            H[h] = R40.year_stats(M44.account(items, recs)[R43._G["pos"]], R43._G["years"], ys)
    return combo, S, H


def _run(args, jobs: list[tuple], name: str) -> int:
    setup(args, procs=args.procs)
    t0 = time.time()
    with mp.get_context("fork").Pool(args.procs) as pool:
        got = pool.map(_unit, jobs, chunksize=1)
    args.out.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.out / f"{name}_{args.shard}.npz", combos=np.array([g[0] for g in got], np.int16),
                        S=np.stack([g[1] for g in got]) if got else np.zeros((0,)),
                        H=np.stack([g[2] for g in got]) if got else np.zeros((0,)), ys=np.array(R43._G["ys"]))
    n = sum(len(j[1]) for j in jobs)
    print(name, args.shard, len(jobs), "replays", n, "books", f"{(time.time() - t0) / max(n, 1) * args.procs:.3f} "
          "cpu-s a book", flush=True)
    return 0


QUICK_S1 = [0] + [S1.index(tuple(v if i == d else 0 for i in range(len(DIMS)))) for d in range(len(DIMS))
                  for v in sorted({1, len(DIMS[d]) - 1})]


def s1_units(shard: int, shards: int) -> list[int]:
    return (QUICK_S1 if QUICK else list(range(len(S1))))[shard::shards]


def cmd_stage1(args) -> int:
    jobs = [(S1[u], list(range(len(FILTERS))), True) for u in s1_units(args.shard, args.shards)]
    return _run(args, jobs, "s1")


def _read(folder: Path, name: str) -> tuple[dict, list[int]]:
    out, ys = {}, None
    for p in sorted(folder.rglob(f"{name}_*.npz")):
        z = np.load(p)
        if not len(z["combos"]):
            continue
        ys = [int(y) for y in z["ys"]]
        for c, S, H in zip(z["combos"], z["S"], z["H"]):
            out[tuple(int(x) for x in c)] = (S.astype(float), H.astype(float))
    assert ys is not None, f"no {name} parts in {folder}"
    return out, ys


def _rank(cands: list, g: dict, dd: dict, base, k: int) -> list:
    """The k candidates with the highest 2018-2022 log growth among those whose worst 2018-2022 drawdown is no worse
    than the base's, filled by log growth alone."""
    ok = [c for c in cands if np.isfinite(g[c])]
    elig = sorted((c for c in ok if dd[c] >= dd[base] - 1e-12), key=lambda c: -g[c])
    rest = sorted((c for c in ok if c not in elig), key=lambda c: -g[c])
    return (elig + rest)[:k]


def selection(s1: dict, ys: list[int]) -> dict:
    early = np.array([y <= EARLY_END for y in ys])
    g = {c: float(S[0, 0, early, 0].sum()) for c, (S, _) in s1.items()}
    dd = {c: float(S[0, 0, early, 1].min()) for c, (S, _) in s1.items()}
    top = []
    for d in range(len(DIMS)):
        if d == len(DIMS) - 1:
            top.append(list(range(len(DIMS[d]))))
            continue
        cands = [c for c in s1 if c[d] != 0 and all(c[i] == 0 for i in range(len(DIMS)) if i != d)]
        top.append([0] + [c[d] for c in _rank(cands, g, dd, BASE_COMBO, K2)])
    S0 = s1[BASE_COMBO][0]
    gf = {f: float(S0[f, 0, early, 0].sum()) for f in range(len(FILTERS))}
    df = {f: float(S0[f, 0, early, 1].min()) for f in range(len(FILTERS))}
    flts = [0] + _rank(list(range(1, len(FILTERS))), gf, df, 0, KF)
    return {"top": top, "filters": flts}


def cmd_select(args) -> int:
    s1, ys = _read(args.runs, "s1")
    if not QUICK and len(s1) != len(S1):
        raise SystemExit(f"{len(s1)} stage 1 replays of {len(S1)}: shards are missing")
    sel = selection(s1, ys)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "selection.json").write_text(json.dumps(sel), encoding="utf-8")
    print(json.dumps({"top": {DNAMES[d]: [_vname(DIMS[d][v]) for v in vs] for d, vs in enumerate(sel["top"])},
                      "filters": [filter_name(f) for f in sel["filters"]]}, indent=1), flush=True)
    return 0


def s2_combos(sel: dict) -> list[tuple]:
    return [tuple(c) for c in product(*sel["top"])]


def s2_units(sel: dict, shard: int, shards: int) -> list[tuple]:
    u = s2_combos(sel)[shard::shards]
    return u[:2] + u[-1:] if QUICK and len(u) > 2 else u  # the canary: the base, the next and the last (every hook)


def cmd_stage2(args) -> int:
    sel = json.loads((args.sel / "selection.json").read_text(encoding="utf-8"))
    jobs = [(c, sel["filters"], False) for c in s2_units(sel, args.shard, args.shards)]
    return _run(args, jobs, "s2")


def walk_forward(G: np.ndarray, DD: np.ndarray, ys: list[int], base: int = 0) -> dict[int, int]:
    """v43's rule (as v44's): for each year after the first, among the books whose worst yearly drawdown before it
    is no worse than the base's, the highest summed log growth before it."""
    picks = {ys[0]: base}
    for k in range(1, len(ys)):
        g = np.nansum(G[:, :k], axis=1)
        dd = np.nanmin(DD[:, :k], axis=1)
        ok = np.isfinite(G[:, :k]).all(axis=1) & np.isfinite(dd)
        elig = ok & (dd >= dd[base] - 1e-12)
        picks[ys[k]] = int(np.flatnonzero(elig)[np.argmax(g[elig])])
    return picks


def robust(s1: dict, ys: list[int]) -> tuple[list[tuple], dict]:
    """Q2: the stage 1 values that beat the base in all four cells at base costs and over all years at HOT 5%."""
    early = np.array([y <= EARLY_END for y in ys])
    b_S, b_H = s1[BASE_COMBO]
    hot = TASKS.index("hot5")

    def cells(H: np.ndarray) -> list[float]:
        return [float(H[h, m, 0].sum()) for h in (0, 1) for m in (early, ~early)]

    bc, bh = cells(b_H), float(b_S[0, hot, :, 0].sum())
    out = [c for c, (S, H) in s1.items() if c != BASE_COMBO
           and all(a > b for a, b in zip(cells(H), bc)) and float(S[0, hot, :, 0].sum()) > bh]
    gf = [f for f in range(1, len(FILTERS)) if all(float(b_S[f, 0, m, 0].sum()) > float(b_S[0, 0, m, 0].sum())
                                                   for m in (early, ~early))
          and float(b_S[f, hot, :, 0].sum()) > bh]
    best = {}
    for d in range(len(DIMS)):
        mine = [c for c in out if c[d] != 0]
        if mine:
            best[d] = max(mine, key=lambda c: float(s1[c][0][0, 0, :, 0].sum()))[d]
    best_f = max(gf, key=lambda f: float(b_S[f, 0, :, 0].sum())) if gf else 0
    return out, {"combo": tuple(best.get(d, 0) for d in range(len(DIMS))), "filter": best_f, "filters": gf}


def cmd_final(args) -> int:
    s1, ys = _read(args.s1, "s1")
    s2, ys2 = _read(args.s2, "s2")
    assert ys == ys2
    sel = json.loads((args.sel / "selection.json").read_text(encoding="utf-8"))
    combos = s2_combos(sel)
    if not QUICK and len(s2) != len(combos):
        raise SystemExit(f"{len(s2)} stage 2 replays of {len(combos)}: shards are missing")
    flts = sel["filters"]
    books = [(c, f) for c in combos if c in s2 for f in range(len(flts))]
    G = np.array([s2[c][0][fi, 0, :, 0] for c, fi in books])
    DDm = np.array([s2[c][0][fi, 0, :, 1] for c, fi in books])
    assert books[0] == (BASE_COMBO, 0)
    picks = walk_forward(G, DDm, ys)
    pick_books = {y: (books[b][0], flts[books[b][1]]) for y, b in picks.items()}
    rob, rbest = robust(s1, ys)
    q3 = (rbest["combo"], rbest["filter"])
    lv2 = np.r_[E2K, R43.LEVELS]
    setup(args, levels=tuple(float(x) for x in lv2), procs=args.procs)
    years = R43._G["years"]
    idx = R32._sub_idx(R43._G["cal"])
    need = sorted(set(pick_books.values()) | {(BASE_COMBO, 0), q3})
    jobs = [(float(lv), task, b, None) for lv in lv2 for task in TASKS for b in need]
    jobs += [(LEVEL, "base", b, h) for b in need for h in (0, 1)]
    with mp.get_context("fork").Pool(args.procs) as pool:
        got = dict(pool.map(_stream, jobs, chunksize=1))

    def series(task: str, sched: dict | tuple, half: int | None = None) -> np.ndarray:
        lvs = [LEVEL] if half is not None else [float(x) for x in lv2]
        if isinstance(sched, tuple):
            return np.stack([got[(lv, task, sched, half)] for lv in lvs])
        R = np.stack([got[(lv, task, (BASE_COMBO, 0), half)] for lv in lvs]).copy()
        for y, b in sched.items():
            R[:, years == y] = np.stack([got[(lv, task, b, half)] for lv in lvs])[:, years == y]
        return R

    arms = {"base": (BASE_COMBO, 0), "wf": pick_books, "q3": q3}
    res = {t: {a: R43.boot(series(t, s)[1:], idx if t == "base" else {"all": idx["all"]}) for a, s in arms.items()}
           for t in TASKS}
    two = {a: R43.boot(series("base", s), {"all": idx["all"]}, E2K, lv2)["all"] for a, s in arms.items()}
    halves = {(h, a): float(np.nansum(R40.year_stats(series("base", arms[a], h)[0], years, ys)[:, 0]))
              for h in (0, 1) for a in arms}
    A = {t: {a: res[t][a]["all"] for a in arms} for t in TASKS}
    late_wf, late_b = res["base"]["wf"].get("late", {}), res["base"]["base"].get("late", {})
    q1 = bool(A["base"]["wf"]["med"] >= GAIN * A["base"]["base"]["med"] and A["base"]["wf"]["p_ruin"] <= MAX_RUIN
              and A["hot5"]["wf"]["p_ruin"] <= MAX_RUIN and A["high"]["wf"]["med"] >= A["high"]["base"]["med"]
              and all(halves[(h, "wf")] > halves[(h, "base")] for h in (0, 1))
              and late_wf.get("med", -1) >= late_b.get("med", np.inf))
    b = A["base"]["base"]
    check = abs(b["med"] - CHECK[0]) <= 200 and abs(b["p_ruin"] - CHECK[1]) <= 0.002
    write_report(args, s1, ys, sel, G, books, flts, picks, pick_books, rob, rbest, res, two, halves, q1, check)
    return 0


def _stream(job: tuple) -> tuple:
    level, task, (combo, f), half = job
    return job, book_returns(combo, f, level, task, half)[R43._G["pos"]]


def write_report(args, s1, ys, sel, G, books, flts, picks, pick_books, rob, rbest, res, two, halves, q1,
                 check) -> None:
    d = M44.R35._d
    early = np.array([y <= EARLY_END for y in ys])
    names = {"base": "base book", "wf": "walk-forward", "q3": "Q3 robust book"}
    L = ["# v46: the book's trades on one-minute bars, technical analysis of every kind", "",
         f"Stage 1: {len(s1)} replays x {len(FILTERS)} filters; stage 2: {len(G):,} books (x4 cost sets). v43's "
         f"central realism case; {R29.PATHS} one-year bootstrap paths from $5,000; ruin = at or under $1,250.", "",
         f"Check (base book vs v44's {d(CHECK[0])}, {CHECK[1]:.1%}): **{'reproduced' if check else 'NOT reproduced'}**.",
         "", "## Q1. Does the walk-forward book improve the book?", "",
         f"**{q1}** (median >= {GAIN} x the base's, ruin <= 2.5% at base and HOT 5%, high-cost median >= the base's, "
         "log growth better on both symbol halves, 2023+ median >= the base's).", "",
         "| book | costs | median | ruin | p10 | 2018-22 median | 2023+ median |", "|---|---|---|---|---|---|---|"]
    for a in names:
        for t in TASKS:
            s_ = res[t][a]
            L.append(f"| {names[a]} | {t} | {d(s_['all']['med'])} | {s_['all']['p_ruin']:.1%} | {d(s_['all']['p10'])} | "
                     f"{d(s_['early']['med']) if 'early' in s_ else '-'} | {d(s_['late']['med']) if 'late' in s_ else '-'} |")
    L += ["", "Symbol halves ($10,000 level, base costs, summed log growth):", "", "| half | " +
          " | ".join(names.values()) + " |", "|---|---|---|---|"]
    L += [f"| {h} | " + " | ".join(f"{halves[(h, a)]:.2f}" for a in names) + " |" for h in (0, 1)]
    wf_hist = sum(float(G[picks[y], k]) for k, y in enumerate(ys))
    L += ["", f"Historical path at $10,000: walk-forward {wf_hist:.2f} vs base {float(np.nansum(G[0])):.2f} "
          "(summed log growth).", "", "Walk-forward picks:", ""]
    L += [f"- {y}: {combo_name(c)}; filter {filter_name(f)}" for y, (c, f) in pick_books.items()]
    L += ["", "## Stage 2 grid (chosen on 2018-2022)", ""]
    L += [f"- {DNAMES[dd]}: " + ", ".join(_vname(DIMS[dd][v]) for v in vs) for dd, vs in enumerate(sel["top"])]
    L += ["- filters: " + ", ".join(filter_name(f) for f in flts)]
    L += ["", "## Q2. Robust single changes (beat the base in all four cells and at HOT 5%)", ""]
    L += [f"- {combo_name(c)}" for c in rob] or ["none"]
    L += [f"- filter {filter_name(f)}" for f in rbest["filters"]]
    L += ["", f"Q3 book: {combo_name(rbest['combo'])}; filter {filter_name(rbest['filter'])} (in sample).", "",
          "## Q4. From $2,000 (base costs; ruin = at or under $500)", "", "| book | median | ruin | p10 | -50% |",
          "|---|---|---|---|---|"]
    L += [f"| {names[a]} | {d(s_['med'])} | {s_['p_ruin']:.1%} | {d(s_['p10'])} | {s_['p_half']:.1%} |"
          for a, s_ in two.items()]
    b_S, b_H = s1[BASE_COMBO]
    L += ["", "## Stage 1: each value alone (filter none; base costs; summed log growth at $10,000)", "",
          "| dimension | value | all | 2018-22 | 2023+ | half 0 | half 1 | HOT 5% | worst yearly DD |",
          "|---|---|---|---|---|---|---|---|---|"]
    hot = TASKS.index("hot5")
    for c in S1:
        if c not in s1:
            continue
        S, H = s1[c]
        dd = next((i for i, v in enumerate(c) if v), None)
        L.append(f"| {DNAMES[dd] if dd is not None else 'base'} | {_vname(DIMS[dd][c[dd]]) if dd is not None else '-'} | "
                 f"{S[0, 0, :, 0].sum():.2f} | {S[0, 0, early, 0].sum():.2f} | {S[0, 0, ~early, 0].sum():.2f} | "
                 f"{H[0, :, 0].sum():.2f} | {H[1, :, 0].sum():.2f} | {S[0, hot, :, 0].sum():.2f} | {S[0, 0, :, 1].min():.1%} |")
    L += ["", "## Stage 1: filters on the base replay (base costs)", "", "| filter | all | 2018-22 | 2023+ | HOT 5% |",
          "|---|---|---|---|---|"]
    L += [f"| {filter_name(f)} | {b_S[f, 0, :, 0].sum():.2f} | {b_S[f, 0, early, 0].sum():.2f} | "
          f"{b_S[f, 0, ~early, 0].sum():.2f} | {b_S[f, hot, :, 0].sum():.2f} |" for f in range(len(FILTERS))]
    fk, XN = _G["XN"]
    L += ["", "## Feature coverage", "", ", ".join(f"{NFEATS[i]} {float(np.isfinite(XN[:, i]).mean()):.0%}"
                                                   for i in range(len(NFEATS))) if len(XN) else "none", ""]
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "V46_REPORT.md").write_text("\n".join(L), encoding="utf-8")
    summ = {"q1": q1, "check": check, "picks": {str(y): [list(c), f] for y, (c, f) in pick_books.items()},
            "selection": sel, "robust": [list(c) for c in rob], "q3": [list(rbest["combo"]), rbest["filter"]],
            "res": res, "two_k": two, "halves": {f"{h}_{a}": v for (h, a), v in halves.items()}}
    (args.out / "v46_summary.json").write_text(json.dumps(summ, indent=1, default=float), encoding="utf-8")
    print("\n".join(L[:20]), flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("stage1", "stage2"):
        p = sub.add_parser(name)
        p.add_argument("--shard", type=int, required=True)
        p.add_argument("--shards", type=int, required=True)
    sub.choices["stage2"].add_argument("--sel", type=Path, required=True)
    s = sub.add_parser("select")
    s.add_argument("--runs", type=Path, required=True)
    f = sub.add_parser("final")
    for a in ("--s1", "--s2", "--sel"):
        f.add_argument(a, type=Path, required=True)
    for p in sub.choices.values():
        p.add_argument("--procs", type=int, default=4)
        p.add_argument("--choice", type=Path, required=True)
        p.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
        p.add_argument("--report", type=Path, default=Path("outputs/v28w/report"))
        p.add_argument("--data", type=Path, default=Path("outputs/v43"))
        p.add_argument("--v44", type=Path, default=Path("outputs/v44"))
        p.add_argument("--out", type=Path, default=Path("outputs/v46w"))
    args = ap.parse_args()
    return {"stage1": cmd_stage1, "select": cmd_select, "stage2": cmd_stage2, "final": cmd_final}[args.cmd](args)


if __name__ == "__main__":
    sys.argv[0] = "run_v46"
    raise SystemExit(main())
