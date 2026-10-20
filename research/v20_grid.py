"""v20: small caps, a wide overnight grid under realistic costs. Pre-registered in docs/research/V20_PREREGISTRATION.md.

The engine is v19's (``v19_grid``: triggers, stops, exits that can be held for days, paths on the entry price, R3
costs, books); v20 adds finer price bands, more triggers, holds, stops, exits and filters, and five daily families.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from aurora.research import v14_intraday as vi
from aurora.research import v14_swing as vs
from aurora.research import v19_grid as v19

B4 = ("1-2", "2-5", "5-10", "10-20")

INTRA_DIMS = {
    "GF_GAPFADE": {"gap": (0.15, 0.20, 0.30, 0.40, 0.50, 0.75, 1.00), "band": B4,
                   "trig": ("open", "orl1", "orl5", "orl15", "orl30", "orl60", "vwaploss", "t15", "t30", "t60", "t120"),
                   "stop": ("hod", "pct10", "pct20", "pct30", "pct50"),
                   "exit": ("close", "r2", "trail20", "next_open", "d2", "d3", "d4", "d5", "d7")},
    "GX_GAPFILTER": {"gap": (0.30, 0.50), "band": ("1-2", "2-5", "5-20"), "news": ("any", "none"),
                     "pmv": (0.0, 1e6, 5e6), "float": ("any", "<10M", ">=10M"), "trig": ("orl15", "vwaploss", "t30"),
                     "exit": ("next_open", "d3", "d5")},
    "RF_RUNFADE": {"up": (0.40, 0.60, 0.80, 1.20),
                   "trig": ("lowerhigh", "vwaploss", "hodfail", "backside", "t120", "t180", "t240"), "band": B4,
                   "stop": ("hod", "pct20", "pct30"), "exit": ("close", "next_open", "d3", "d5")},
    "D2_DAY2FADE": {"day1": (0.50, 1.00, 2.00), "trig": ("open", "orl5", "orl15", "orl30", "vwaploss", "t30"),
                    "band": B4, "stop": ("hod", "pct20", "pct30"), "exit": ("close", "next_open", "d3", "d5")},
    "PM_PMFADE": {"gap": (0.30, 0.60), "drop": (0.05, 0.10, 0.20), "trig": ("open", "orl1", "orl5", "orl15"),
                  "stop": ("pmh", "pct20"), "exit": ("close", "next_open", "d3", "d5"), "band": B4},
    "GD_GAPDOWN": {"side": ("short", "long"), "gap": (-0.20, -0.35, -0.50), "trig": ("or5", "or15", "vwap", "t30"),
                   "band": B4, "stop": ("ext", "pct10", "pct20"), "exit": ("close", "next_open", "d3")},
    "LG_GAPGO": {"gap": (0.20, 0.40, 0.80), "trig": ("orh1", "orh5", "orh15", "pmhbreak", "vwapreclaim", "hod13"),
                 "band": B4, "stop": ("lod", "pct10", "pct20"), "exit": ("close", "trail20", "next_open", "d3", "d5")},
}
DAILY_DIMS = {
    "RU_RUNUP": {"rise": (0.5, 1.0, 1.5, 2.0, 3.0, 5.0), "window": (1, 3, 5, 20),
                 "trig": ("open", "lowclose", "redclose", "close_c", "gapdown"), "hold": (2, 3, 5, 10, 20, 30),
                 "stop": (0.25, 0.50, 1.00, "none"), "exit": ("time", "target30", "target50", "strength", "trail30")},
    "NS_NIGHTSHORT": {"gap": (0.20, 0.30, 0.50, 1.00), "drop": (0.0, 0.05, 0.10, 0.20), "loc": ("any", "low25"),
                      "exit": ("next_open", "next_close", "close2", "close3", "close5"), "band": B4,
                      "stop": ("none", 0.30)},
    "EV_EVENTSHORT": {"event": ("offer_spike", "rsplit", "deficiency", "offering"), "hold": (3, 5, 10, 20, 40),
                      "stop": (0.25, 0.50, "none"), "exit": ("time", "target30", "target50"), "band": ("1-5", "5-20")},
    "CB_CRASHLONG": {"fall": (0.25, 0.40, 0.60), "news": ("any", "none"),
                     "trig": ("close_c", "open", "greenclose", "highclose"), "hold": (1, 2, 3, 5, 10),
                     "stop": (0.20, 0.50, "none"), "exit": ("time", "target20", "weak"), "band": ("1-5", "5-20")},
    "MO_MOMOLONG": {"up": (0.20, 0.50, 1.00), "trig": ("open", "redclose", "highclose"), "hold": (3, 5, 10, 20, 40),
                    "stop": (0.10, 0.20, 0.30), "exit": ("time", "trail20", "ma10"), "band": ("1-5", "5-20")},
}
SHORT = {"GF_GAPFADE", "GX_GAPFILTER", "RF_RUNFADE", "D2_DAY2FADE", "PM_PMFADE", "RU_RUNUP", "NS_NIGHTSHORT",
         "EV_EVENTSHORT"}


def side_of(family: str, g: dict) -> int:
    if family == "GD_GAPDOWN":
        return -1 if g["side"] == "short" else 1
    return -1 if family in SHORT else 1


def in_band(price, band: str | None):
    """$lo-$hi, the top inclusive at $20 (as v18's high band); None = $1-$20."""
    lo, hi = (1.0, 20.0) if band is None else (float(x) for x in band.split("-"))
    return (price >= lo) & ((price <= hi) if hi >= 20 else (price < hi))


# ---------------------------------------------------------------- intraday

def scope(c: pd.DataFrame, family: str, band: str) -> pd.Series:
    price = in_band(c["open"], band)
    if family == "RF_RUNFADE":
        return price & (c["s_runner"] | c["s_gap_up"])
    if family == "D2_DAY2FADE":
        return price & c["s_day2"]
    if family == "GD_GAPDOWN":
        return price & c["s_gap_down"]
    return price & c["s_gap_up"]


def candidates(store: vi.Store, family: str, g: dict) -> pd.Index:
    c = store.cands
    s = scope(c, family, g["band"])
    if family in ("GF_GAPFADE", "GX_GAPFILTER", "LG_GAPGO"):
        s &= c["gap"] >= g["gap"]
    elif family == "D2_DAY2FADE":
        s &= c["day1"] >= g["day1"]
    elif family == "PM_PMFADE":
        s &= (c["gap"] >= g["gap"]) & (c["open"] <= c["pmh"] * (1 - g["drop"]))
    elif family == "GD_GAPDOWN":
        s &= c["gap"] <= g["gap"]
    if family == "GX_GAPFILTER":
        if g["news"] == "none":
            s &= ~c["news"]
        s &= c["pmv"] >= g["pmv"]
        so = c["so"]
        if g["float"] == "<10M":
            s &= np.isfinite(so) & (so < 10e6)
        elif g["float"] == ">=10M":
            s &= np.isfinite(so) & (so >= 10e6)
    return c.index[s.to_numpy()]


def pool_by_day(store: vi.Store, family: str, band: str) -> dict:
    s = scope(store.cands, family, band).to_numpy()
    out: dict = {}
    for k, d in zip(store.cands.index[s], store.cands.loc[s, "date"]):
        out.setdefault(pd.Timestamp(d), []).append(k)
    return out


def _trig_stop(family: str, g: dict, side: int) -> tuple[str, str]:
    trig, stop = g["trig"], g.get("stop", "pct20")
    if family == "GD_GAPDOWN":
        trig = {"or5": "orl5" if side < 0 else "orh5", "or15": "orl15" if side < 0 else "orh15",
                "vwap": "vwaploss" if side < 0 else "vwapreclaim", "t30": "t30"}[trig]
        stop = ("hod" if side < 0 else "lod") if stop == "ext" else stop
    return trig, stop


def entry(family: str, g: dict, side: int, trig: str, b: tuple, line: np.ndarray, cd: pd.Series) -> tuple[int, float]:
    h = b[2]
    ok = np.ones(len(h), bool)
    if family == "RF_RUNFADE":
        ok = np.maximum.accumulate(h) >= float(cd["pc"]) * (1 + g["up"])
    if trig == "pmhbreak":
        pmh = float(cd["pmh"])
        if not np.isfinite(pmh):
            return v19.NOT
        j = vi.first_true((h > pmh) & ok & (b[0] <= vi.LAST_ENTRY), 0)
        return (j, v19._past(1, float(b[1][j]), pmh, float(h[j]))) if j >= 0 else v19.NOT
    return v19.trigger(trig, side, b, line, ok)


def intraday_trades(store: vi.Store, D: dict, family: str, g: dict) -> pd.DataFrame:
    side = side_of(family, g)
    trig, stop_rule = _trig_stop(family, g, side)
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
        stop = v19.stop_of(stop_rule, side, b, j, e, cd)
        if not np.isfinite(stop) or (stop - e) * side >= 0:
            continue
        rows.append(v19.trade_row(D, cd, b, line, side, j, e, stop, g["exit"], abs(float(cd["gap"]))))
    return pd.DataFrame(rows, columns=v19.COLS)


# ---------------------------------------------------------------- daily

def daily_specs(D: dict, E: dict, family: str, g: dict) -> list:
    """Setups use the setup day's close, range, volume and 20-day dollar volume (known at that close); events use
    the prior day's price and dollar volume."""
    O, H, L, C, P = D["O"], D["H"], D["L"], D["C"], D["P"]
    prev = vs._shift(C, 1)
    side = side_of(family, g)
    with np.errstate(invalid="ignore", divide="ignore"):
        base = (D["DV"] >= 1e6) & D["valid"] & in_band(P, g.get("band"))
        if family == "RU_RUNUP":
            w = g["window"]
            low = prev if w == 1 else pd.DataFrame(C).rolling(w, min_periods=max(2, w // 2)).min().shift(1).to_numpy()
            rise = C / low - 1
            return v19._once_specs(v19._setup_trigger(D, (rise >= g["rise"]) & base, rise, g["trig"]), side, g,
                                   g["hold"])
        if family == "CB_CRASHLONG":
            r1 = C / prev - 1
            news = ~E["NEWS"] if g["news"] == "none" else np.ones_like(base)
            return v19._once_specs(v19._setup_trigger(D, (r1 <= -g["fall"]) & news & base, -r1, g["trig"]), side, g,
                                   g["hold"])
        if family == "MO_MOMOLONG":
            r1 = C / prev - 1
            V = E["V"]
            vol20 = pd.DataFrame(V).rolling(20, min_periods=10).mean().shift(1).to_numpy()
            S = (r1 >= g["up"]) & ((C - L) >= 0.75 * (H - L)) & (V >= 3 * vol20) & base
            return v19._once_specs(v19._setup_trigger(D, S, r1, g["trig"]), side, g, g["hold"])
        if family == "NS_NIGHTSHORT":
            S = (O >= prev * (1 + g["gap"])) & (C <= O * (1 - g["drop"])) & base
            if g["loc"] == "low25":
                S &= (C - L) <= 0.25 * (H - L)
            hold, rule = {"next_open": (1, "open1"), "next_close": (1, "time"), "close2": (2, "time"),
                          "close3": (3, "time"), "close5": (5, "time")}[g["exit"]]
            stop = np.nan if g["stop"] == "none" else float(g["stop"])
            gap = O / prev - 1
            return [v19.Spec(int(j), int(t), "close", side, hold, stop, np.nan, np.nan, rule, float(gap[t, j]))
                    for t, j in zip(*np.nonzero(S)) if t + 1 < C.shape[0]]
    if family == "EV_EVENTSHORT":
        ok = in_band(D["P1"], g["band"]) & (D["DV1"] >= 1e6) & D["valid1"]
        T = C.shape[0]
        ev = g["event"]
        if ev == "offer_spike":
            rows = list(E["offer_spike"])
        elif ev == "rsplit":
            rows = [(t, j) for t, j, ratio in E["rsplit"] if ratio >= 5]
        else:
            tab = D["events"]["delist" if ev == "deficiency" else "offering"]
            rows = list(zip(tab["t"].to_numpy(), tab["j"].to_numpy()))
        rows = [(int(t), int(j), "open", 0.0) for t, j in rows if t < T and ok[t, j]]
        return v19._once_specs(rows, side, g, g["hold"])
    raise KeyError(family)


def daily_placebo(D: dict, specs: list, rng: np.random.Generator, band: str | None) -> list:
    """Each real trade moved to a random symbol of its price band (prior close, $1M of dollar volume) on its entry
    row, with the same entry kind, side and exit terms."""
    ok = in_band(D["P1"], band) & (D["DV1"] >= 1e6) & D["valid1"]
    out = []
    for s in specs:
        cols = np.flatnonzero(ok[s.t])
        if len(cols):
            out.append(v19.Spec(int(rng.choice(cols)), s.t, s.kind, s.side, s.hold, s.stop, s.target, s.trail, s.rule,
                                s.prio))
    return out
