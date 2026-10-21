"""v25: short-only small caps on one-minute bars, the mirror of v24. Pre-registered in
docs/research/V25_PREREGISTRATION.md.

Two kinds of family:
- v23's level, daily-level and indicator families, short side, with v23's own short rules (exact) on the scopes v23
  did not have (DD_DAILY, SR_SHORT, X*).
- v24's own families run on the reciprocal price 1/p (a fall of p is a rise of 1/p, a support a resistance): every
  long rule's mirror image. The bars, VWAP and the day's facts are mirrored (the premarket high becomes the
  premarket low, the 20-day high the 20-day low, ...); the entry bars that may be taken (runner risen 40%, inplay
  from 09:35) are the real ones; the entry, its stop and target are mapped back to real prices. Percentages apply in
  the mirror (a 10% fall of 1/p is an 11.1% rise of p). D2_FADE keeps the real prior day (up 20/50/100%): the day-2
  fade rather than the continuation after a crash.
Exits are taken on the real bars with the short side (v19, v22, v23 and v24 rules); shorts take the short-sale
restriction (v14's up-close fill) and R4's borrow availability and fees.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from aurora.research import v14_intraday as vi
from aurora.research import v19_grid as v19
from aurora.research import v22_intra as v22i
from aurora.research import v23_ta1m as v23
from aurora.research import v24_long1m as v24

B3 = v24.B3
SHORT_SETUPS = ("break_dn", "fail_up", "retest_dn")
DAILY25 = ("h20", "h60", "h252", "l20", "l60", "l252", "sma20d", "sma50d", "sma200d")

INTRA_DIMS: dict[str, dict] = {
    "DD_DAILY": {**v24.INTRA_DIMS["DL_DAILY"], "level": DAILY25, "setup": SHORT_SETUPS},
    "SR_SHORT": {**v24.INTRA_DIMS["SR_LONG"], "setup": SHORT_SETUPS},
}
V23S = {"XV_VWAP": "VW_VWAP", "XE_EMA": "EM_EMA", "XO_OSC": "OS_OSC", "XM_MACD": "MD_MACD", "XQ_SQUEEZE": "SQ_SQUEEZE",
        "XP_PATTERN": "PT_PATTERN", "XC_CANDLE": "CD_CANDLE", "XX_CLIMAX": "VC_CLIMAX", "XR_ORB": "OR_ORB"}
for _key, _fam in V23S.items():
    _d: dict = dict(v23.INTRA_DIMS[_fam])  # type: ignore[call-overload]
    _d["scope"] = v24.NEW_SC
    for _k in ("side", "cside"):
        if _k in _d:
            _d[_k] = ("short",)
    if _fam == "VW_VWAP":
        _d["setup"] = ("loss", "reject", "revert_hi", "break_lo")
    elif _fam == "PT_PATTERN":
        _d["pattern"] = ("double_top", "desc_triangle", "bear_flag")
    elif _fam == "VC_CLIMAX":
        _d["candle"] = ("upwick", "bigdown")
    INTRA_DIMS[_key] = _d
MIRROR = {"SB_INPLAY": "SP_INPLAY", "NL_NOISE": "NB_NOISE", "LL_LATE": "LH_LATE", "PL_POWER": "PH_POWER",
          "MB_MICRO": "MP_MICRO", "AS_ABCD": "AB_ABCD", "HS_HALT": "HR_HALT", "MP_MORNPOP": "MD_MORNDIP",
          "GR_GREEN2RED": "RG_RED2GREEN", "GU_GAPFILL": "GF_GAPFILL", "D2_FADE": "D2_GO", "IS_IND": "IX_IND",
          "PS_PATTERN": "PX_PATTERN", "CS_CANDLE": "CK_CANDLE", "BT_BLOWOFF": "WO_WASH", "HD_GRAIL": "HG_GRAIL",
          "TD_TREND": "TS_TREND"}
SCOPES = {  # the mirrored rules' natural universes (v24's, with the up and down scopes swapped where they mirror)
    "NL_NOISE": ("liquid", "mover_dn", "gapdown", "inplay"),
    "LL_LATE": ("liquid", "mover_dn", "gapdown", "mover_up"),
    "PL_POWER": ("liquid", "mover_dn", "gapdown", "gapup"),
    "MB_MICRO": ("gapdown", "mover_dn", "liquid", "gapup", "runner"),
    "AS_ABCD": ("gapdown", "mover_dn", "liquid", "gapup", "runner"),
    "MP_MORNPOP": ("gapup", "runner", "mover_up", "gapdown", "mover_dn"),
    "GR_GREEN2RED": ("liquid", "mover_up", "gapup"),
    "GU_GAPFILL": ("liquid", "mover_up", "gapup"),
    "D2_FADE": ("day2", "liquid", "mover_up", "mover_dn"),
}
for _key, _fam in MIRROR.items():
    INTRA_DIMS[_key] = {**v24.INTRA_DIMS[_fam], **({"scope": SCOPES[_key]} if _key in SCOPES else {})}
KEYS = v24.KEYS + ("l252", "green2")


def base_family(family: str) -> str:
    if family in ("SR_SHORT", "DD_DAILY"):
        return "SR_LEVEL"
    return V23S.get(family, MIRROR.get(family, family))


# ---------------------------------------------------------------- facts and mirrors

def prepare(stores: dict, D: dict) -> None:
    """v24's facts plus the 252-day low and two up days in a row (the mirrors of the 252-day high and two red days)."""
    v24.prepare(stores, D)
    L, C, F = D["L"], D["C"], D["F"]
    for st in stores.values():
        c = st.cands
        t, j = c["t"].to_numpy(int), c["j"].to_numpy(int)
        l252, green2 = np.full(len(c), np.nan), np.full(len(c), np.nan)
        for col, rows in c.groupby("j").indices.items():
            lo, cl = np.asarray(L[:, col], float), np.asarray(C[:, col], float)
            tt = t[rows]
            prev = np.maximum(tt - 1, 0)
            l252[rows] = v24._trail(lo, 252, "min")[prev] / F[tt, col]
            c1, c2, c3 = cl[prev], cl[np.maximum(tt - 2, 0)], cl[np.maximum(tt - 3, 0)]
            with np.errstate(invalid="ignore"):
                green2[rows] = ((c1 > c2) & (c2 > c3)).astype(float)
        c["l252"], c["green2"] = l252, green2
        st.cols = {k: c[k].to_numpy() for k in KEYS + ("off", "n") if k in c}


def _inv(x) -> float:
    x = float(x)
    return 1.0 / x if np.isfinite(x) and x > 0 else np.nan


def mirror_bars(b: tuple) -> tuple:
    m, o, h, lo, c, v, vw = b
    with np.errstate(divide="ignore", invalid="ignore"):
        return m, 1.0 / o, 1.0 / lo, 1.0 / h, 1.0 / c, v, 1.0 / vw


def mirror_cd(cd: dict, family: str) -> dict:
    """The day's facts in the mirror: prices inverted, highs and lows swapped, ATR as a fraction of the price kept."""
    out = dict(cd)
    pc = float(cd["pc"])
    out["open"], out["pc"] = _inv(cd["open"]), _inv(pc)
    out["gap"] = out["open"] / out["pc"] - 1
    for hi, lo in (("pmh", "pml"), ("pdh", "pdl"), ("h5", "l5"), ("h20", "l20"), ("h60", "l60")):
        out[hi], out[lo] = _inv(cd[lo]), _inv(cd[hi])
    out["h252"] = _inv(cd["l252"])
    for k in ("sma20d", "sma50d", "sma200d"):
        out[k] = _inv(cd[k])
    out["atr14"] = float(cd["atr14"]) / (pc * pc) if pc > 0 else np.nan
    for k in ("ret60", "day1"):
        x = float(cd[k])
        out[k] = 1 / (1 + x) - 1 if np.isfinite(x) and x > -1 else np.nan
    out["day1_loc"] = 1 - float(cd["day1_loc"])
    out["red2"] = cd["green2"]
    if family == "D2_FADE":  # the day after a big up day, faded
        out["day1"], out["day1_loc"] = cd["day1"], cd["day1_loc"]
    return out


def levels(cd: dict) -> dict:
    lv = v24.levels(cd)
    lv["l252"] = float(cd["l252"])
    return lv


def live_real(family: str, g: dict, b: tuple, cd: dict) -> np.ndarray:
    return v24.live_mask(MIRROR[family], g, b, cd)


# ---------------------------------------------------------------- signals, stops, exits

def signal(family: str, g: dict, b: tuple, line: np.ndarray, cd: dict, lv: dict) -> tuple:
    """(entry bar, entry price, stop reference above it, target height below it, mirror) on real prices; ``mirror``
    = (bars, VWAP, facts, entry, reference, target) in the mirror for the stop, or None for v23's families."""
    if family in ("SR_SHORT", "DD_DAILY") or family in V23S:
        j, e, ref, tgt = v23.signal(base_family(family), g, -1, b, line, cd, lv)
        return j, e, ref, tgt, None
    b2, line2, cd2 = mirror_bars(b), 1.0 / line, mirror_cd(cd, family)
    j, e2, ref2, tgt2 = v24.signal(MIRROR[family], g, b2, line2, cd2, v24.levels(cd2),
                                   live=live_real(family, g, b, cd))
    if j < 0 or not np.isfinite(e2) or e2 <= 0:
        return -1, np.nan, np.nan, np.nan, None
    e = 1.0 / e2
    tgt = e - 1.0 / (e2 + tgt2) if np.isfinite(tgt2) and tgt2 > 0 else np.nan
    return j, e, _inv(ref2), tgt, (b2, line2, cd2, e2, ref2, tgt2)


def stop_of(family: str, g: dict, b: tuple, j: int, e: float, ref: float, tgt: float, mirror) -> float:
    if mirror is None:
        return v23._stop(g, -1, b, j, e, ref, tgt)
    b2, _, cd2, _, ref2, tgt2 = mirror
    return _inv(v24.stop_of(MIRROR[family], g, b2, j, 1.0 / e, ref2, tgt2, cd2))


def make_trade(D: dict, family: str, g: dict, cd: dict, b: tuple, line: np.ndarray, lv: dict, j: int, e: float,
               stop: float, tgt: float, prio: float) -> dict:
    ex = g["exit"]
    if ex in v24.SPECIAL:
        return v24.special(D, cd, b, line, j, e, stop, ex, prio, side=-1)
    if ex in v24.TARGETS:
        t = (float(cd["open"]) + float(cd["pc"])) / 2 if ex == "half" else float(cd["open"])
        return v23.target_row(D, cd, b, line, -1, j, e, stop, t if t < e else np.nan, ex, prio)
    if ex in v24.MASKS:
        xm = np.zeros(len(b[0]), bool)
        if ex in ("opp", "bound"):  # the mirrored long exit: the short's own cover signal
            xm = v24.exit_mask(MIRROR[family], g, mirror_bars(b), 1.0 / line, mirror_cd(cd, family))
        return v22i.mask_row(D, cd, b, line, -1, j, e, stop, xm, ex, prio)
    return v23.make_trade(D, base_family(family), g, -1, cd, b, line, lv, j, e, stop, tgt, prio)


def trades(stores: dict, D: dict, family: str, g: dict) -> pd.DataFrame:
    rows = []
    for nm, idx in v24.candidates(stores, g):
        st = stores[nm]
        for i in idx:
            cd = v24.row(st, int(i))
            b = v24.bars(st, int(i))
            if len(b[0]) < 30:
                continue
            line = vi.vwap(b[4], b[5], b[6])
            lv = levels(cd)
            j, e, ref, tgt, mirror = signal(family, g, b, line, cd, lv)
            if j < 0 or not np.isfinite(e) or e <= 0:
                continue
            j, e = vi._ssr_fill(j, b, float(cd["pc"]), e)  # 10% or more under the prior close: an up-close minute
            if j < 0:
                continue
            stop = stop_of(family, g, b, j, e, ref, tgt, mirror)
            if not np.isfinite(stop) or stop <= e:
                continue
            rows.append(make_trade(D, family, g, cd, b, line, lv, j, e, stop, tgt, abs(float(cd["gap"]))))
    return pd.DataFrame(rows, columns=v19.COLS)


def placebo(stores: dict, by_day: dict, D: dict, family: str, g: dict, real: pd.DataFrame,
            rng: np.random.Generator) -> pd.DataFrame:
    """v24's placebo for shorts: each real trade moved to a random candidate of its scope and band that day, same
    minute (that bar's open), stop distance and exit."""
    rows = []
    for r in real.itertuples(index=False):
        ch = by_day.get(pd.Timestamp(r.date), [])
        if not ch:
            continue
        nm, i = ch[int(rng.integers(len(ch)))]
        st = stores[nm]
        cd = v24.row(st, i)
        b = v24.bars(st, i)
        if len(b[0]) < 30:
            continue
        j = int(np.searchsorted(b[0], r.minute))
        if j >= len(b[0]) or b[0][j] > vi.LAST_ENTRY + 30:
            continue
        e = float(b[1][j])
        stop = e * (1 + abs(r.entry - r.stop) / r.entry)
        line = vi.vwap(b[4], b[5], b[6])
        rows.append(make_trade(D, family, g, cd, b, line, levels(cd), j, e, stop, 2 * abs(r.entry - r.stop),
                               float(r.prio)))
    return pd.DataFrame(rows, columns=v19.COLS)
