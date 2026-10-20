"""v21: small caps, a five-times-larger grid with new ideas under realistic costs. Pre-registered in
docs/research/V21_PREREGISTRATION.md.

On v19's engine (``v19_grid``) and v20's bands (``v20_grid``). New here: a market regime filter (IWM's 20-session
return before the day), two entries (a close below the day's open after 10:00; a fall back below the premarket high
after breaking it), close-based stops, an exit at the first close against the position, a split exit (half at the
close, half after three sessions), twenty candidate filters, and two daily families (a long after a collapsed run, a
short at the open of the day after a big day).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from aurora.research import v14_intraday as vi
from aurora.research import v14_swing as vs
from aurora.research import v19_grid as v19
from aurora.research import v20_grid as v20

B4 = v20.B4
REG = ("any", "iwm_up", "iwm_down")
FILTERS = ("none", "news_none", "news_yes", "pmv1M", "pmv5M", "float_lt10M", "float_ge10M", "rv5_3", "rv5_10",
           "runs60_0", "runs60_2", "shelf30", "offer", "earn", "sr_hi", "sr_lo", "off_hi", "off_lo", "cat_none",
           "cat_801")

INTRA_DIMS = {
    "GA_GAPFADE": {"gap": (0.20, 0.30, 0.40, 0.50, 0.75, 1.00, 1.50), "band": B4,
                   "trig": ("open", "orl5", "orl15", "orl30", "vwaploss", "t30", "t60", "belowopen", "pmhfail"),
                   "stop": ("hod", "pct20", "pct30", "pct50", "cpct30", "cpct50"),
                   "exit": ("close", "next_open", "d2", "d3", "d5", "d7", "half3", "g5"), "regime": REG},
    "GB_GAPFILTER": {"gap": (0.30, 0.50), "band": ("1-2", "2-5", "5-20"), "filt": FILTERS,
                     "trig": ("orl15", "vwaploss", "t30", "belowopen"), "stop": ("pct20", "cpct30"),
                     "exit": ("next_open", "d3", "d5", "g5"), "regime": REG},
    "RB_RUNFADE": {"up": (0.40, 0.60, 0.80, 1.20, 2.00),
                   "trig": ("lowerhigh", "vwaploss", "hodfail", "backside", "t120", "t180", "t240", "belowopen"),
                   "band": B4, "stop": ("hod", "pct20", "pct30", "cpct30"),
                   "exit": ("close", "next_open", "d3", "d5", "half3", "g5"), "regime": REG},
    "DB_DAY2FADE": {"day1": (0.50, 1.00, 2.00), "trig": ("open", "orl5", "orl15", "orl30", "vwaploss", "t30",
                                                          "belowopen"),
                    "band": B4, "stop": ("hod", "pct20", "pct30", "cpct30"),
                    "exit": ("close", "next_open", "d3", "d5", "g5"), "regime": REG},
    "PB_PMFADE": {"gap": (0.30, 0.60), "drop": (0.05, 0.10, 0.20), "trig": ("open", "orl1", "orl5", "orl15", "pmhfail"),
                  "stop": ("pmh", "pct20", "cpct30"), "exit": ("close", "next_open", "d3", "d5", "g5"), "band": B4,
                  "regime": REG},
    "GE_GAPDOWN": {"side": ("short", "long"), "gap": (-0.20, -0.35, -0.50), "trig": ("or5", "or15", "vwap", "t30"),
                   "band": B4, "stop": ("ext", "pct10", "pct20"), "exit": ("close", "next_open", "d3", "d5"),
                   "regime": REG},
    "LB_GAPGO": {"gap": (0.20, 0.40, 0.80), "trig": ("orh1", "orh5", "orh15", "pmhbreak", "vwapreclaim", "hod13"),
                 "band": B4, "stop": ("lod", "pct10", "pct20"), "exit": ("close", "trail20", "next_open", "d3", "d5"),
                 "regime": REG},
}
DAILY_DIMS = {
    "RV_RUNUP": {"rise": (0.5, 1.0, 2.0, 3.0, 5.0), "window": (1, 3, 5, 20),
                 "trig": ("open", "lowclose", "redclose", "close_c", "gapdown"), "hold": (3, 5, 10, 20),
                 "stop": (0.50, 1.00, "c50", "none"), "exit": ("time", "target30", "target50", "strength", "green"),
                 "vol": ("any", "x3"), "regime": REG},
    "NT_NIGHTSHORT": {"gap": (0.20, 0.30, 0.50, 1.00), "drop": (0.0, 0.05, 0.10, 0.20), "loc": ("any", "low25"),
                      "exit": ("next_open", "next_close", "close2", "close3", "close5", "green5"), "band": B4,
                      "stop": ("none", 0.30), "regime": REG},
    "EW_EVENTSHORT": {"event": ("offer_spike", "rsplit", "deficiency", "offering"), "hold": (3, 5, 10, 20, 40),
                      "stop": (0.25, 0.50, "none"), "exit": ("time", "target30", "target50", "green"),
                      "band": ("1-5", "5-20"), "regime": REG},
    "CC_CRASHLONG": {"fall": (0.25, 0.40, 0.60), "news": ("any", "none"),
                     "trig": ("close_c", "open", "greenclose", "highclose"), "hold": (1, 2, 3, 5, 10),
                     "stop": (0.20, 0.50, "none"), "exit": ("time", "target20", "weak"), "band": ("1-5", "5-20"),
                     "regime": REG},
    "MP_MOMOLONG": {"up": (0.20, 0.50, 1.00), "trig": ("open", "redclose", "highclose"), "hold": (3, 5, 10, 20, 40),
                    "stop": (0.10, 0.20, 0.30), "exit": ("time", "trail20", "ma10"), "band": ("1-5", "5-20"),
                    "regime": REG},
    "DK_DEADCATLONG": {"peak": (2.0, 3.0, 5.0), "fall": (0.50, 0.70), "trig": ("open", "greenclose", "highclose"),
                       "hold": (1, 3, 5, 10), "stop": (0.20, 0.30, "none"), "exit": ("time", "target20", "target50"),
                       "band": ("1-5", "5-20"), "regime": REG},
    "RX_DAY2GAP": {"day1": (0.30, 0.50, 1.00), "gap2": (0.0, 0.10, 0.20), "hold": (1, 2, 3, 5, 10),
                   "stop": (0.25, 0.50, "c50", "none"), "exit": ("time", "target30", "strength", "green"), "band": B4,
                   "regime": REG},
}
SHORT = {"GA_GAPFADE", "GB_GAPFILTER", "RB_RUNFADE", "DB_DAY2FADE", "PB_PMFADE", "RV_RUNUP", "NT_NIGHTSHORT",
         "EW_EVENTSHORT", "RX_DAY2GAP"}
_R: dict = {}


def side_of(family: str, g: dict) -> int:
    if family == "GE_GAPDOWN":
        return -1 if g["side"] == "short" else 1
    return -1 if family in SHORT else 1


def set_regime(X: dict, dates: pd.DatetimeIndex) -> None:
    """IWM's return over the 20 sessions before each day (known before its open): up if positive."""
    close = X["etf_close"]["IWM"] if "IWM" in X["etf_close"] else (1 + X["etf_ret"]["IWM"].fillna(0.0)).cumprod()
    r20 = (close.shift(1) / close.shift(21) - 1).reindex(dates).ffill().to_numpy()
    with np.errstate(invalid="ignore"):
        _R.update({"any": np.ones(len(dates), bool), "iwm_up": r20 > 0, "iwm_down": r20 <= 0})


def regime(name: str, n: int | None = None) -> np.ndarray:
    return _R[name] if n is None else _R[name][:n]


# ---------------------------------------------------------------- intraday

def scope(c: pd.DataFrame, family: str, band: str) -> pd.Series:
    price = v20.in_band(c["open"], band)
    if family == "RB_RUNFADE":
        return price & (c["s_runner"] | c["s_gap_up"])
    if family == "DB_DAY2FADE":
        return price & c["s_day2"]
    if family == "GE_GAPDOWN":
        return price & c["s_gap_down"]
    return price & c["s_gap_up"]


def _filter(c: pd.DataFrame, f: str) -> pd.Series:
    so, sr, off = c["so"], c["sr_prev"], c["off_prev"]
    m = {"none": True, "news_none": ~c["news"], "news_yes": c["news"], "pmv1M": c["pmv"] >= 1e6,
         "pmv5M": c["pmv"] >= 5e6, "float_lt10M": np.isfinite(so) & (so < 10e6),
         "float_ge10M": np.isfinite(so) & (so >= 10e6), "rv5_3": c["rv5"] >= 3, "rv5_10": c["rv5"] >= 10,
         "runs60_0": c["runs60"] == 0, "runs60_2": c["runs60"] >= 2, "shelf30": c["shelf30"], "offer": c["offer"],
         "earn": c["earn"], "sr_hi": sr >= 0.6, "sr_lo": sr <= 0.4, "off_hi": off >= 0.6, "off_lo": off <= 0.4,
         "cat_none": c["catalyst"] == "none", "cat_801": c["catalyst"] == "8.01"}[f]
    return pd.Series(m, index=c.index) if isinstance(m, bool) else m.fillna(False).astype(bool)


def candidates(store: vi.Store, family: str, g: dict) -> pd.Index:
    c = store.cands
    s = scope(c, family, g["band"])
    if family in ("GA_GAPFADE", "GB_GAPFILTER", "LB_GAPGO"):
        s &= c["gap"] >= g["gap"]
    elif family == "DB_DAY2FADE":
        s &= c["day1"] >= g["day1"]
    elif family == "PB_PMFADE":
        s &= (c["gap"] >= g["gap"]) & (c["open"] <= c["pmh"] * (1 - g["drop"]))
    elif family == "GE_GAPDOWN":
        s &= c["gap"] <= g["gap"]
    if family == "GB_GAPFILTER":
        s &= _filter(c, g["filt"])
    s &= regime(g["regime"])[c["t"].to_numpy(int)]
    return c.index[s.to_numpy()]


def pool_by_day(store: vi.Store, family: str, band: str) -> dict:
    s = scope(store.cands, family, band).to_numpy()
    out: dict = {}
    for k, d in zip(store.cands.index[s], store.cands.loc[s, "date"]):
        out.setdefault(pd.Timestamp(d), []).append(k)
    return out


def entry(family: str, g: dict, side: int, trig: str, b: tuple, line: np.ndarray, cd: pd.Series) -> tuple[int, float]:
    m, o, h, c = b[0], b[1], b[2], b[4]
    n = len(c)
    ok = np.ones(n, bool)
    if family == "RB_RUNFADE":
        ok = np.maximum.accumulate(h) >= float(cd["pc"]) * (1 + g["up"])
    live = ok & (m <= vi.LAST_ENTRY)

    def at_close(mask):
        j = vi.first_true(mask & live, 0)
        return (j + 1, float(c[j])) if 0 <= j < n - 1 else v19.NOT

    if trig == "belowopen":  # the first close below the day's open from 10:00
        return at_close((m >= 30) & (c < o[0]))
    if trig == "pmhfail":  # back below the premarket high after trading above it
        pmh = float(cd["pmh"])
        if not np.isfinite(pmh):
            return v19.NOT
        was_above = np.r_[False, np.maximum.accumulate(h > pmh)[:-1]]
        return at_close((m >= 5) & was_above & (c < pmh))
    return v20.entry(family if family != "RB_RUNFADE" else "RF_RUNFADE", g, side, trig, b, line, cd)


def _trig_stop(family: str, g: dict, side: int) -> tuple[str, str]:
    return v20._trig_stop("GD_GAPDOWN" if family == "GE_GAPDOWN" else family, g, side)


def make_row(D: dict, cd: pd.Series, b: tuple, line: np.ndarray, side: int, j: int, e: float, stop: float,
             close_based: bool, rule: str, prio: float) -> dict:
    """One trade; a close-based stop is checked on closes only (``stop`` is then its level and the sizing distance);
    half3 closes half at the session's close and holds half to the third session's close."""
    lvl = stop if close_based else np.nan
    if rule != "half3":
        r = v19.trade_row(D, cd, b, line, side, j, e, stop, rule, prio, lvl)
    else:
        a = v19.trade_row(D, cd, b, line, side, j, e, stop, "close", prio, lvl)
        r = v19.trade_row(D, cd, b, line, side, j, e, stop, "d3", prio, lvl)
        ra, rb = a["rets"], r["rets"]
        n = max(len(ra), len(rb))
        r["rets"] = 0.5 * np.pad(ra, (0, n - len(ra))) + 0.5 * np.pad(rb, (0, n - len(rb)))
        r["nights"] = 0.5 * r["nights"]
        r["rule"] = "half3"
    r["ckind"] = int(close_based)
    return r


COLS = v19.COLS + ["ckind"]


def intraday_trades(store: vi.Store, D: dict, family: str, g: dict) -> pd.DataFrame:
    side = side_of(family, g)
    trig, stop_rule = _trig_stop(family, g, side)
    close_based = stop_rule.startswith("cpct")
    rows = []
    for k in candidates(store, family, g):
        cd = store.cands.loc[k]
        b = store.bars(k)
        if len(b[0]) < 10:
            continue
        line = vi.vwap(b[4], b[5], b[6])
        j, e = entry(family, g, side, trig, b, line, cd)
        if j < 0 or not np.isfinite(e) or e <= 0:
            continue
        if side < 0:
            j, e = vi._ssr_fill(j, b, float(cd["pc"]), e)
            if j < 0:
                continue
        stop = e * (1 - side * int(stop_rule[4:]) / 100) if close_based else v19.stop_of(stop_rule, side, b, j, e, cd)
        if not np.isfinite(stop) or (stop - e) * side >= 0:
            continue
        rows.append(make_row(D, cd, b, line, side, j, e, stop, close_based, g["exit"], abs(float(cd["gap"]))))
    return pd.DataFrame(rows, columns=COLS)


def intraday_placebo(store: vi.Store, D: dict, real: pd.DataFrame, rng: np.random.Generator,
                     by_day: dict) -> pd.DataFrame:
    """Each real trade moved to a random candidate of the family's scope and band that day: same minute (at that
    bar's open), side, stop distance and kind, and exit rule."""
    rows = []
    for r in real.itertuples(index=False):
        ch = by_day.get(pd.Timestamp(r.date), [])
        if not ch:
            continue
        k = int(rng.choice(ch))
        cd = store.cands.loc[k]
        b = store.bars(k)
        if len(b[0]) < 10:
            continue
        j = int(np.searchsorted(b[0], r.minute))
        if j >= len(b[0]) or b[0][j] > vi.LAST_ENTRY + 30:
            continue
        e = float(b[1][j])
        stop = e * (1 - r.side * abs(r.entry - r.stop) / r.entry)
        line = vi.vwap(b[4], b[5], b[6])
        rows.append(make_row(D, cd, b, line, int(r.side), j, e, stop, bool(r.ckind), r.rule, float(r.prio)))
    return pd.DataFrame(rows, columns=COLS)


# ---------------------------------------------------------------- daily

def _specs(rows: list, side: int, g: dict, hold: int, once: bool = True) -> list:
    if not rows:
        return []
    t = np.array([r[0] for r in rows])
    j = np.array([r[1] for r in rows])
    keep = vs._once(t, j, v19.ONCE) if once else np.ones(len(rows), bool)
    stop_v = g.get("stop", "none")
    cstop = 0.5 if stop_v == "c50" else np.nan
    gg = {**g, "stop": "none" if stop_v == "c50" else stop_v}
    stop, target, trail, rule = v19._exit_terms(gg)
    return [v19.Spec(int(r[1]), int(r[0]), r[2], side, hold, stop, target, trail, rule, r[3], cstop)
            for r, k in zip(rows, keep) if k]


def daily_specs(D: dict, E: dict, family: str, g: dict) -> list:
    """Setups use the setup day's close, range, volume and 20-day dollar volume (known at that close) and the regime
    known before that day; events use the prior day's price and dollar volume."""
    O, H, L, C, P = D["O"], D["H"], D["L"], D["C"], D["P"]
    T = C.shape[0]
    prev = vs._shift(C, 1)
    side = side_of(family, g)
    reg = regime(g["regime"], T)[:, None]
    with np.errstate(invalid="ignore", divide="ignore"):
        base = (D["DV"] >= 1e6) & D["valid"] & v20.in_band(P, g.get("band")) & reg
        r1 = C / prev - 1
        if family == "RV_RUNUP":
            w = g["window"]
            low = prev if w == 1 else pd.DataFrame(C).rolling(w, min_periods=max(2, w // 2)).min().shift(1).to_numpy()
            rise = C / low - 1
            S = (rise >= g["rise"]) & base
            if g["vol"] == "x3":
                V = E["V"]
                S &= V >= 3 * pd.DataFrame(V).rolling(20, min_periods=10).mean().shift(1).to_numpy()
            return _specs(v19._setup_trigger(D, S, rise, g["trig"]), side, g, g["hold"])
        if family == "CC_CRASHLONG":
            news = ~E["NEWS"] if g["news"] == "none" else np.ones_like(base)
            return _specs(v19._setup_trigger(D, (r1 <= -g["fall"]) & news & base, -r1, g["trig"]), side, g, g["hold"])
        if family == "MP_MOMOLONG":
            V = E["V"]
            vol20 = pd.DataFrame(V).rolling(20, min_periods=10).mean().shift(1).to_numpy()
            S = (r1 >= g["up"]) & ((C - L) >= 0.75 * (H - L)) & (V >= 3 * vol20) & base
            return _specs(v19._setup_trigger(D, S, r1, g["trig"]), side, g, g["hold"])
        if family == "DK_DEADCATLONG":
            hi20 = pd.DataFrame(C).rolling(20, min_periods=10).max().to_numpy()
            low_before = pd.DataFrame(C).rolling(20, min_periods=10).min().shift(20).to_numpy()
            S = (hi20 >= (1 + g["peak"]) * low_before) & (C <= (1 - g["fall"]) * hi20) & base
            return _specs(v19._setup_trigger(D, S, hi20 / low_before - 1, g["trig"]), side, g, g["hold"])
        if family == "RX_DAY2GAP":
            S = (r1 >= g["day1"]) & base
            tt, jj = np.nonzero(S)
            rows = [(int(t + 1), int(j), "open", float(r1[t, j])) for t, j in zip(tt, jj)
                    if t + 1 < T and O[t + 1, j] >= C[t, j] * (1 + g["gap2"])]
            return _specs(rows, side, g, g["hold"])
        if family == "NT_NIGHTSHORT":
            S = (O >= prev * (1 + g["gap"])) & (C <= O * (1 - g["drop"])) & base
            if g["loc"] == "low25":
                S &= (C - L) <= 0.25 * (H - L)
            hold, rule = {"next_open": (1, "open1"), "next_close": (1, "time"), "close2": (2, "time"),
                          "close3": (3, "time"), "close5": (5, "time"), "green5": (5, "green")}[g["exit"]]
            stop = np.nan if g["stop"] == "none" else float(g["stop"])
            gap = O / prev - 1
            return [v19.Spec(int(j), int(t), "close", side, hold, stop, np.nan, np.nan, rule, float(gap[t, j]))
                    for t, j in zip(*np.nonzero(S)) if t + 1 < T]
    if family == "EW_EVENTSHORT":
        ok = v20.in_band(D["P1"], g["band"]) & (D["DV1"] >= 1e6) & D["valid1"] & reg
        ev = g["event"]
        if ev == "offer_spike":
            rows = list(E["offer_spike"])
        elif ev == "rsplit":
            rows = [(t, j) for t, j, ratio in E["rsplit"] if ratio >= 5]
        else:
            tab = D["events"]["delist" if ev == "deficiency" else "offering"]
            rows = list(zip(tab["t"].to_numpy(), tab["j"].to_numpy()))
        rows = [(int(t), int(j), "open", 0.0) for t, j in rows if t < T and ok[t, j]]
        return _specs(rows, side, g, g["hold"])
    raise KeyError(family)


def daily_placebo(D: dict, specs: list, rng: np.random.Generator, band: str | None) -> list:
    ok = v20.in_band(D["P1"], band) & (D["DV1"] >= 1e6) & D["valid1"]
    out = []
    for s in specs:
        cols = np.flatnonzero(ok[s.t])
        if len(cols):
            out.append(v19.Spec(int(rng.choice(cols)), s.t, s.kind, s.side, s.hold, s.stop, s.target, s.trail, s.rule,
                                s.prio, s.cstop))
    return out
