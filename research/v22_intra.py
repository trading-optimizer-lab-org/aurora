"""v22: technical analysis on the minute bars of small-cap event days. Pre-registered in
docs/research/V22_PREREGISTRATION.md.

Indicators on the session's one-minute closes (EMAs with spans multiplied by 1, 3 or 5 stand in for longer bars):
EMA crosses, VWAP bands (VWAP +- k volume-weighted deviations), RSI extremes, MACD crosses and flags. Entries at the
signal bar's close (the next bar is the entry bar) or, for flags, at the break of the flag; stops, exits and costs
are v19's, plus indicator exits (the cross back, a touch of VWAP, RSI back to 50, the MACD cross back).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from aurora.research import v14_intraday as vi
from aurora.research import v19_grid as v19
from aurora.research import v20_grid as v20
from aurora.research import v22_ta as ta

SCOPES = ("gapup", "runner", "gapdown")
INTRA_DIMS = {
    "IE_EMA": {"pair": ("5/13", "9/20", "20/50"), "mult": (1, 3, 5), "side": ("long", "short"), "scope": SCOPES,
               "after": (15, 60), "exit": ("crossback", "close", "d3", "next_open"), "stop": ("swing", "pct10", "pct20"),
               "band": ta.B3},
    "IV_VWAPBAND": {"k": (1.0, 1.5, 2.0, 3.0), "mode": ("revert", "break"), "side": ("long", "short"), "scope": SCOPES,
                    "after": (15, 60), "exit": ("tovwap", "close", "d3", "next_open"), "stop": ("ext", "pct10", "pct20"),
                    "band": ta.B3},
    "IR_RSI1M": {"n": (7, 14), "lvl": (80, 90), "side": ("long", "short"), "scope": SCOPES, "confirm": ("none", "turn"),
                 "exit": ("rsi50", "close", "d3", "next_open"), "stop": ("ext", "pct10", "pct20"), "band": ta.B3},
    "IM_MACD": {"set": ("12/26/9", "5/35/5"), "signal": ("cross", "zero"), "side": ("long", "short"), "scope": SCOPES,
                "after": (15, 60), "exit": ("opp", "close", "d3", "next_open"), "stop": ("swing", "pct10", "pct20"),
                "band": ta.B3},
    "IF_FLAG": {"pole": (0.10, 0.20, 0.40), "retrace": (0.38, 0.50, 0.62), "side": ("long", "short"), "scope": SCOPES,
                "exit": ("close", "r2", "trail20", "d3", "next_open"), "stop": ("flag", "pct10", "pct20"),
                "band": ta.B3},
}
MASK_EXITS = ("crossback", "tovwap", "rsi50", "opp")


def scope_mask(c: pd.DataFrame, scope: str, band: str) -> pd.Series:
    col = {"gapup": "s_gap_up", "runner": "s_runner", "gapdown": "s_gap_down"}[scope]
    return v20.in_band(c["open"], band) & c[col]


def candidates(store: vi.Store, g: dict) -> pd.Index:
    return store.cands.index[scope_mask(store.cands, g["scope"], g["band"]).to_numpy()]


def pool_by_day(store: vi.Store, g: dict) -> dict:
    s = scope_mask(store.cands, g["scope"], g["band"]).to_numpy()
    out: dict = {}
    for k, d in zip(store.cands.index[s], store.cands.loc[s, "date"]):
        out.setdefault(pd.Timestamp(d), []).append(k)
    return out


def _ema(x: np.ndarray, span: float) -> np.ndarray:
    return pd.Series(x).ewm(span=span, adjust=False).mean().to_numpy()


def _rsi(c: np.ndarray, n: int) -> np.ndarray:
    d = np.diff(c, prepend=c[0])
    up = pd.Series(np.clip(d, 0, None)).ewm(alpha=1 / n, adjust=False).mean().to_numpy()
    dn = pd.Series(np.clip(-d, 0, None)).ewm(alpha=1 / n, adjust=False).mean().to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(dn > 0, 100 - 100 / (1 + up / dn), 100.0)


def _vwap_dev(b: tuple, line: np.ndarray) -> np.ndarray:
    c, v, vw = b[4], b[5], b[6]
    px = np.where(np.isfinite(vw) & (vw > 0), vw, c)
    cv = np.cumsum(v)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.sqrt(np.maximum(np.cumsum(v * (px - line) ** 2) / np.maximum(cv, 1e-9), 0.0))


def _lines(family: str, g: dict, b: tuple, line: np.ndarray) -> dict:
    c = b[4]
    if family == "IE_EMA":
        f, s = (int(x) * g["mult"] for x in g["pair"].split("/"))
        return {"fast": _ema(c, f), "slow": _ema(c, s)}
    if family == "IM_MACD":
        f, s, sg = (int(x) for x in g["set"].split("/"))
        mc = _ema(c, 5 * f) - _ema(c, 5 * s)  # on five-minute-equivalent spans
        return {"macd": mc, "sig": _ema(mc, 5 * sg)}
    if family == "IR_RSI1M":
        return {"rsi": _rsi(c, g["n"])}
    if family == "IV_VWAPBAND":
        return {"dev": _vwap_dev(b, line)}
    return {}


def _up(a, b) -> np.ndarray:
    return (a > b) & np.r_[False, (a <= b)[:-1]] if isinstance(b, np.ndarray) else (a > b) & np.r_[False, a[:-1] <= b]


def _dn(a, b) -> np.ndarray:
    return (a < b) & np.r_[False, (a >= b)[:-1]] if isinstance(b, np.ndarray) else (a < b) & np.r_[False, a[:-1] >= b]


def risen(h: np.ndarray, pc: float) -> np.ndarray:
    """Whether the bars before each one have already risen 40% above the prior close."""
    return np.r_[-np.inf, np.maximum.accumulate(h)[:-1]] >= 1.4 * pc


def entry(family: str, g: dict, side: int, b: tuple, line: np.ndarray, L: dict,
          pc: float = np.nan, live: np.ndarray | None = None) -> tuple[int, float, float]:
    """(entry bar, entry price, flag extreme or nan). A runner (a day that rises 40% above the prior close) is only
    traded once it has risen 40% (v22b: the scope is defined by the day's high, so earlier entries would know it),
    by the bars before the entry bar (v22c: a break inside the bar that made the rise would know it too)."""
    m, o, h, lo, c = b[0], b[1], b[2], b[3], b[4]
    n = len(c)
    if live is None:
        live = (m >= g.get("after", 5)) & (m <= vi.LAST_ENTRY)
        if g.get("scope") == "runner":
            live &= risen(h, pc)

    def at_close(mask):  # a signal known at a bar's close is filled at the next bar's open (v22b)
        j = vi.first_true(mask & live, 0)
        return (j + 1, float(o[j + 1]), np.nan) if 0 <= j < n - 1 else (-1, np.nan, np.nan)

    if family == "IE_EMA":
        return at_close(_up(L["fast"], L["slow"]) if side > 0 else _dn(L["fast"], L["slow"]))
    if family == "IM_MACD":
        if g["signal"] == "cross":
            return at_close(_up(L["macd"], L["sig"]) if side > 0 else _dn(L["macd"], L["sig"]))
        return at_close(_up(L["macd"], 0.0) if side > 0 else _dn(L["macd"], 0.0))
    if family == "IR_RSI1M":
        r = L["rsi"]
        x = (r <= 100 - g["lvl"]) if side > 0 else (r >= g["lvl"])
        if g["confirm"] == "turn":
            x &= (c > np.r_[np.inf, c[:-1]]) if side > 0 else (c < np.r_[-np.inf, c[:-1]])
        return at_close(x)
    if family == "IV_VWAPBAND":
        band = g["k"] * L["dev"]
        if g["mode"] == "revert":
            x = (c < line - band) if side > 0 else (c > line + band)
        else:
            x = (c > line + band) if side > 0 else (c < line - band)
        return at_close(x & (L["dev"] > 0))
    if family == "IF_FLAG":
        # a pole: a move of at least ``pole`` within 15 bars; then a pullback of at most ``retrace`` of it over 3-10
        # bars without a new extreme; the entry at the break of the pullback's extreme
        ext_run = np.maximum.accumulate(h) if side > 0 else np.minimum.accumulate(lo)
        base15 = (pd.Series(lo).rolling(16, min_periods=1).min() if side > 0 else
                  pd.Series(h).rolling(16, min_periods=1).max()).to_numpy()
        top_arr = h if side > 0 else lo
        with np.errstate(invalid="ignore", divide="ignore"):
            poles = np.flatnonzero((top_arr == ext_run) & ((top_arr / base15 - 1) * side >= g["pole"]) &
                                   (m <= vi.LAST_ENTRY) & (np.arange(n) >= 15) & (np.arange(n) < n - 4))
        for p in poles:
            base, top = float(base15[p]), float(top_arr[p])
            for q in range(p + 3, min(p + 11, n - 1)):
                seg_h, seg_l = h[p + 1:q + 1], lo[p + 1:q + 1]
                if (seg_h.max() > top) if side > 0 else (seg_l.min() < top):
                    break
                depth = (top - seg_l.min()) / (top - base) if side > 0 else (seg_h.max() - top) / (base - top)
                if depth > g["retrace"]:
                    break
                lvl = seg_h.max() if side > 0 else seg_l.min()
                k = q + 1
                if live[k] and ((h[k] > lvl) if side > 0 else (lo[k] < lvl)):  # v22c: on a live bar only
                    ext = float(seg_l.min()) if side > 0 else float(seg_h.max())
                    return k, v19._past(side, float(o[k]), float(lvl), float(h[k] if side > 0 else lo[k])), ext
        return -1, np.nan, np.nan
    raise KeyError(family)


def exit_mask(family: str, g: dict, side: int, b: tuple, line: np.ndarray, L: dict) -> np.ndarray | None:
    ex = g["exit"]
    if ex == "crossback":
        return (L["fast"] < L["slow"]) if side > 0 else (L["fast"] > L["slow"])
    if ex == "opp":
        return (L["macd"] < L["sig"]) if side > 0 else (L["macd"] > L["sig"])
    if ex == "rsi50":
        return (L["rsi"] >= 50) if side > 0 else (L["rsi"] <= 50)
    if ex == "tovwap":
        return (b[2] >= line) if side > 0 else (b[3] <= line)
    return None


def mask_row(D: dict, cd: pd.Series, b: tuple, line: np.ndarray, side: int, j: int, e: float, stop: float,
             xm: np.ndarray, rule: str, prio: float) -> dict:
    """A same-day trade left at the first bar after the entry where ``xm`` holds (at VWAP for tovwap, else at that
    bar's close), unless the stop comes first; at the session's close otherwise."""
    m, o, h, lo, c = b[0], b[1], b[2], b[3], b[4]
    n = len(c)
    hit = vi.first_true((h >= stop) if side < 0 else (lo <= stop), j)
    if rule == "tovwap":  # a resting limit at the VWAP of the bar before (v22b)
        prev = np.r_[np.nan, line[:-1]]
        xm = (h >= prev) if side > 0 else (lo <= prev)
    k = vi.first_true(xm, j + 1)
    if hit >= 0 and (k < 0 or hit <= k):
        ext = float(h[hit]) if side < 0 else float(lo[hit])
        px, kk = (v19._slip(stop, ext) if hit == j else v19._past(-side, float(o[hit]), stop, ext)), hit
    elif k >= 0 and rule == "tovwap":
        lvl = float(line[k - 1])
        px, kk = (max(float(o[k]), lvl) if side > 0 else min(float(o[k]), lvl)), k
    elif k >= 0:  # an exit signal at a bar's close is filled at the next bar's open (v22b)
        px, kk = (float(o[k + 1]), k + 1) if k + 1 < n else (float(c[k]), k)
    else:
        px, kk = float(c[-1]), n - 1
    v, vw = b[5], b[6]
    pv = np.where(np.isfinite(vw) & (vw > 0), vw, c)
    return {"date": cd["date"], "t": int(cd["t"]), "symbol": cd["symbol"], "minute": int(m[j]), "side": side,
            "entry": e, "stop": stop, "price": float(cd["open"]),
            "liq": float(cd["pmv"]) + float(np.sum(pv[:j] * v[:j])), "prio": prio, "so": float(cd.get("so", np.nan)),
            "rets": np.array([side * (px - e) / e]), "nights": 0, "rule": rule, "opens": 0, "xmin": int(m[kk]),
            "leg_in": 1, "leg_out": 2 if kk == len(c) - 1 else 1}


def _stop(g: dict, side: int, b: tuple, j: int, e: float, cd: pd.Series, flag_ext: float) -> float:
    st = g["stop"]
    if st.startswith("pct"):
        return e * (1 - side * int(st[3:]) / 100)
    if st == "flag":
        return flag_ext
    if st == "ext":
        return v19.stop_of("hod" if side < 0 else "lod", side, b, j, e, cd)
    a = max(j - 10, 0)  # swing: the extreme of the ten bars before the entry
    if j <= a:
        return np.nan
    return float(b[2][a:j].max()) if side < 0 else float(b[3][a:j].min())


def make_trade(D: dict, family: str, g: dict, side: int, cd: pd.Series, b: tuple, line: np.ndarray, L: dict, j: int,
               e: float, stop: float, prio: float) -> dict:
    if g["exit"] in MASK_EXITS:
        return mask_row(D, cd, b, line, side, j, e, stop, exit_mask(family, g, side, b, line, L), g["exit"], prio)
    return v19.trade_row(D, cd, b, line, side, j, e, stop, g["exit"], prio)


def intraday_trades(store: vi.Store, D: dict, family: str, g: dict) -> pd.DataFrame:
    side = 1 if g["side"] == "long" else -1
    rows = []
    for k in candidates(store, g):
        cd = store.cands.loc[k]
        b = store.bars(k)
        if len(b[0]) < 30:
            continue
        line = vi.vwap(b[4], b[5], b[6])
        L = _lines(family, g, b, line)
        j, e, ext = entry(family, g, side, b, line, L, float(cd["pc"]))
        if j < 0 or not np.isfinite(e) or e <= 0:
            continue
        if side < 0:
            j, e = vi._ssr_fill(j, b, float(cd["pc"]), e)
            if j < 0:
                continue
        stop = _stop(g, side, b, j, e, cd, ext)
        if not np.isfinite(stop) or (stop - e) * side >= 0:
            continue
        rows.append(make_trade(D, family, g, side, cd, b, line, L, j, e, stop, abs(float(cd["gap"]))))
    return pd.DataFrame(rows, columns=v19.COLS)


def intraday_placebo(store: vi.Store, D: dict, family: str, g: dict, real: pd.DataFrame, rng: np.random.Generator,
                     by_day: dict) -> pd.DataFrame:
    rows = []
    for r in real.itertuples(index=False):
        ch = by_day.get(pd.Timestamp(r.date), [])
        if not ch:
            continue
        k = int(rng.choice(ch))
        cd = store.cands.loc[k]
        b = store.bars(k)
        if len(b[0]) < 30:
            continue
        j = int(np.searchsorted(b[0], r.minute))
        if j >= len(b[0]) or b[0][j] > vi.LAST_ENTRY + 30:
            continue
        e = float(b[1][j])
        stop = e * (1 - r.side * abs(r.entry - r.stop) / r.entry)
        line = vi.vwap(b[4], b[5], b[6])
        rows.append(make_trade(D, family, g, int(r.side), cd, b, line, _lines(family, g, b, line), j, e, stop,
                               float(r.prio)))
    return pd.DataFrame(rows, columns=v19.COLS)
