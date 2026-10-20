"""v19: small caps, entry x exit grids. Pre-registered in docs/research/V19_PREREGISTRATION.md.

Intraday families select candidates of the v14 minute store, enter on a trigger, set a stop and leave by an exit
rule; three exit rules carry the position overnight or for days on the daily bars. Daily families enter after a
setup and a trigger and leave by a holding period, a stop, a target, a trailing stop or a rule. Every trade is a path
of daily returns measured on its entry price, costed with v15's R1 terms (middle half-spreads x a multiple, $0.005 a
share, a short weighted by its calibrated availability and charged its borrow fee per night) and booked with at most
20 open positions and a gross exposure of at most 100%.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from aurora.research import v14_core as core
from aurora.research import v14_intraday as vi
from aurora.research import v14_swing as vs
from aurora.research import v15_ah as v15
from aurora.research import v18_rules as v18

BANDS = ("low", "high")
K_AFTER = 5  # sessions after a daily setup in which its trigger may fire
ONCE = 20  # a symbol enters a multi-day family at most once in this many sessions
NOT = (-1, np.nan)

INTRA_DIMS = {
    "XS1_GAPFADE": {"gap": (0.20, 0.30, 0.50, 1.00), "band": BANDS,
                    "trig": ("open", "orl1", "orl5", "orl15", "orl30", "vwaploss", "t30", "t60"),
                    "stop": ("hod", "pct20"),
                    "exit": ("close", "vwap", "t60", "r2", "trail20", "fill", "next_open", "d3")},
    "XS2_RUNFADE": {"up": (0.40, 0.80), "trig": ("lowerhigh", "vwaploss", "hodfail", "backside", "t120"),
                    "band": BANDS, "stop": ("hod", "pct20"),
                    "exit": ("close", "vwap", "r2", "trail20", "next_open", "d3")},
    "XS3_DAY2FADE": {"day1": (0.50, 1.00), "trig": ("open", "orl5", "orl15", "vwaploss", "t30"), "band": BANDS,
                     "stop": ("hod", "pct20"), "exit": ("close", "vwap", "trail20", "next_open", "d3", "d5")},
    "XS4_PMFADE": {"gap": (0.30, 0.60), "drop": (0.05, 0.10, 0.20), "trig": ("open", "orl1", "orl5"),
                   "stop": ("pmh", "hod"), "exit": ("close", "vwap", "r2", "next_open", "d3"), "band": BANDS},
    "XL1_GAPGO": {"gap": (0.20, 0.40, 0.80), "band": BANDS,
                  "trig": ("orh1", "orh5", "orh15", "pmhbreak", "vwapreclaim", "hod13"),
                  "stop": ("lod", "pct10"), "exit": ("close", "vwap", "trail10", "trail20", "next_open", "d3", "d5")},
    "XL2_GAPDOWNLONG": {"gap": (-0.20, -0.35), "band": BANDS, "trig": ("orh5", "orh15", "vwapreclaim", "t30"),
                        "stop": ("lod", "pct10"), "exit": ("close", "vwap", "fill", "next_open", "d3")},
}
DAILY_DIMS = {
    "DS1_RUNUP": {"rise": (0.5, 1.0, 2.0, 3.0), "window": (1, 5, 20),
                  "trig": ("open", "lowclose", "redclose", "redclose_c", "gapdown"), "hold": (3, 10, 20),
                  "stop": (0.25, 0.50, 1.00, "none"), "exit": ("time", "target50", "strength")},
    "DS2_EVENTSHORT": {"event": ("offer_spike", "rsplit", "deficiency", "offering"), "hold": (5, 10, 20, 60),
                       "stop": (0.25, 0.50, "none"), "exit": ("time", "target50")},
    "DL1_CRASHBOUNCE": {"fall": (0.30, 0.50), "news": ("any", "none"), "trig": ("open", "greenclose", "highclose"),
                        "hold": (1, 3, 5, 10), "stop": (0.20, 0.50, "none"), "exit": ("time", "target30", "weak")},
    "DL2_MOMO": {"up": (0.20, 0.50), "trig": ("open", "redclose", "highclose"), "hold": (5, 10, 20, 40),
                 "stop": (0.10, 0.20, 0.30), "exit": ("time", "trail20", "ma10")},
    "ON1_NIGHTSHORT": {"setup": ("gapfail30", "gapfail50", "weak50", "weak100", "run200red"),
                       "exit": ("next_open", "next_close", "close2", "close3"), "band": BANDS, "stop": ("none", 0.30)},
    "ON2_NIGHTLONG": {"setup": ("strong20", "strong30", "strong50", "crash20", "crash40"),
                      "exit": ("next_open", "next_close", "close3"), "band": BANDS},
}
CARRY = {"next_open": 1, "d2": 1, "d3": 2, "d4": 3, "d5": 4, "d7": 6}  # sessions held after the entry day

# Cost model: "r1" (v15-v18: price-tier half-spreads, $0.005 a share, the IBKR cells as they are) or "r3" (the
# realistic model of the v19 amendment: measured half-spreads, 1.5x at the open, IBKR tiered commissions and the
# SEC and FINRA sale fees, borrow fees doubled with a 100% floor and availability x0.8). SLIP: a stop-type fill
# (a breakout entry at a level, a stop or trailing exit) is filled this far from the level towards the bar's
# extreme beyond it; limit-type fills (targets, the prior close) are not slipped.
MODEL = "r1"
SLIP = 0.0
R3_HALF = ((2, 0.0048), (5, 0.0036), (10, 0.0033), (np.inf, 0.0037))  # v19 cost study, mean of 20,820 legs
R3_OPEN, R3_COMM, R3_SEC, R3_TAF = 1.5, 0.0065, 0.0000278, 0.000166


def set_costs(model: str, slip: float) -> None:
    global MODEL, SLIP
    MODEL, SLIP = model, slip


def _slip(level: float, extreme: float) -> float:
    return level + SLIP * (extreme - level)


def _past(direction: int, o: float, level: float, extreme: float) -> float:
    """Fill of a stop-type order at ``level`` hit by a price moving up (direction +1, ``extreme`` the bar's high)
    or down (-1, the bar's low) in a bar that opens at ``o``: the open if it is already beyond the level, else the
    slipped level."""
    if (o >= level) if direction > 0 else (o <= level):
        return o
    return _slip(level, extreme)


def side_of(family: str) -> int:
    return -1 if family[:2] in ("XS", "DS", "ON") and family != "ON2_NIGHTLONG" else 1


# ---------------------------------------------------------------- intraday: selection

def scope(c: pd.DataFrame, family: str, band: str) -> pd.Series:
    price = v18.band_of(c["open"], band)
    if family == "XS2_RUNFADE":
        return price & (c["s_runner"] | c["s_gap_up"])
    if family == "XS3_DAY2FADE":
        return price & c["s_day2"]
    if family == "XL2_GAPDOWNLONG":
        return price & c["s_gap_down"]
    return price & c["s_gap_up"]


def candidates(store: vi.Store, family: str, g: dict) -> pd.Index:
    c = store.cands
    s = scope(c, family, g["band"])
    if family in ("XS1_GAPFADE", "XL1_GAPGO"):
        s &= c["gap"] >= g["gap"]
    elif family == "XS3_DAY2FADE":
        s &= c["day1"] >= g["day1"]
    elif family == "XS4_PMFADE":
        s &= (c["gap"] >= g["gap"]) & (c["open"] <= c["pmh"] * (1 - g["drop"]))
    elif family == "XL2_GAPDOWNLONG":
        s &= c["gap"] <= g["gap"]
    return c.index[s.to_numpy()]


def pool_by_day(store: vi.Store, family: str, band: str) -> dict:
    s = scope(store.cands, family, band).to_numpy()
    out: dict = {}
    for k, d in zip(store.cands.index[s], store.cands.loc[s, "date"]):
        out.setdefault(pd.Timestamp(d), []).append(k)
    return out


# ---------------------------------------------------------------- intraday: entries, stops, exits

def _low5(lo: np.ndarray) -> np.ndarray:
    """Lowest low of the five bars before each bar (nan for the first five)."""
    out = np.full(len(lo), np.nan)
    if len(lo) > 5:
        out[5:] = np.lib.stride_tricks.sliding_window_view(lo, 5)[:-1].min(axis=1)
    return out


def trigger(name: str, side: int, b: tuple, line: np.ndarray, ok: np.ndarray) -> tuple[int, float]:
    """(entry bar, entry price). Entries at a level or an open are filled in that bar; entries at a bar's close
    return the next bar as the entry bar, so that bar's own range cannot stop them out."""
    m, o, h, lo, c = b[0], b[1], b[2], b[3], b[4]
    n = len(c)
    live = ok & (m <= vi.LAST_ENTRY)

    def at_close(mask):
        j = vi.first_true(mask & live, 0)
        return (j + 1, float(c[j])) if 0 <= j < n - 1 else NOT

    if name == "open":
        return (0, float(o[0])) if live[0] else NOT
    if name[:3] in ("orl", "orh"):
        hi, low, first = vi.opening_range(m, h, lo, int(name[3:]))
        if first == 0 or not np.isfinite(hi):
            return NOT
        if side < 0:
            j = vi.first_true((lo < low) & live, first)
            return (j, _past(-1, float(o[j]), low, float(lo[j]))) if j >= 0 else NOT
        j = vi.first_true((h > hi) & live, first)
        return (j, _past(1, float(o[j]), hi, float(h[j]))) if j >= 0 else NOT
    if name[0] == "t" and name[1:].isdigit():
        j = v18._at(m, int(name[1:]))
        if j < 1 or not live[j]:
            return NOT
        return (j, float(o[j])) if (o[j] - line[j - 1]) * side > 0 else NOT
    if name == "vwaploss":
        prior_above = np.r_[False, np.maximum.accumulate(c > line)[:-1]]
        return at_close((m >= 15) & prior_above & (c < line))
    if name == "vwapreclaim":
        a = c > line
        three = a & np.r_[False, a[:-1]] & np.r_[False, False, a[:-2]]
        was_below = np.r_[False, False, False, np.maximum.accumulate(c < line)[:-3]]
        return at_close((m >= 15) & three & was_below)
    if name == "lowerhigh":
        return at_close((m >= 30) & (h < np.r_[np.inf, h[:-1]]) & (c < np.r_[-np.inf, lo[:-1]]))
    if name == "hodfail":
        runmax = np.maximum.accumulate(h)
        j0 = vi.first_true((m >= 60) & live & (h > np.r_[np.inf, runmax[:-1]]), 1)
        if j0 < 0:
            return NOT
        return at_close((np.arange(n) > j0) & (c < _low5(lo)))
    if name == "backside":
        runmax = np.maximum.accumulate(h)
        hi_at = np.maximum.accumulate(np.where(h >= runmax, np.arange(n), 0))
        return at_close((m - m[hi_at] >= 30) & (c <= 0.85 * runmax) & (c < _low5(lo)))
    if name == "pmhbreak":
        return NOT  # needs the premarket high: handled in ``entry``
    if name == "hod13":
        k = int(np.searchsorted(m, 210))
        if k < 1 or k >= n:
            return NOT
        hod = float(h[:k].max())
        j = vi.first_true((h > hod) & live & (m <= 360), k)
        return (j, _past(1, float(o[j]), hod, float(h[j]))) if j >= 0 else NOT
    raise KeyError(name)


def entry(family: str, g: dict, b: tuple, line: np.ndarray, cd: pd.Series) -> tuple[int, float]:
    side = side_of(family)
    h = b[2]
    ok = np.ones(len(h), bool)
    if family == "XS2_RUNFADE":
        ok = np.maximum.accumulate(h) >= float(cd["pc"]) * (1 + g["up"])
    if g["trig"] == "pmhbreak":
        pmh = float(cd["pmh"])
        if not np.isfinite(pmh):
            return NOT
        j = vi.first_true((h > pmh) & ok & (b[0] <= vi.LAST_ENTRY), 0)
        return (j, _past(1, float(b[1][j]), pmh, float(h[j]))) if j >= 0 else NOT
    return trigger(g["trig"], side, b, line, ok)


def stop_of(rule: str, side: int, b: tuple, j: int, e: float, cd: pd.Series) -> float:
    """hod / lod: the session's extreme before the entry bar (at the open: the premarket high for a short if above
    the open, else 20%; 10% for a long); pmh: the premarket high; pctX: X% from the entry."""
    if rule.startswith("pct"):
        return e * (1 - side * int(rule[3:]) / 100)
    if rule == "pmh":
        return float(cd["pmh"])
    if j > 0:
        return float(b[2][:j].max()) if side < 0 else float(b[3][:j].min())
    if side < 0:
        pmh = float(cd["pmh"])
        return pmh if np.isfinite(pmh) and pmh > e else e * 1.20
    return e * 0.90


def session_exit(side: int, j: int, e: float, stop: float, rule: str, b: tuple, line: np.ndarray,
                 pc: float) -> tuple[float, bool]:
    px, held, _ = exit_bar(side, j, e, stop, rule, b, line, pc)
    return px, held


def exit_bar(side: int, j: int, e: float, stop: float, rule: str, b: tuple, line: np.ndarray,
             pc: float) -> tuple[float, bool, int]:
    """(exit price, still open at the close, exit bar). A stop is always live; when a stop and a target or a trailing level
    are reached in the same bar, the stop is taken."""
    m, o, h, lo, c = b[0], b[1], b[2], b[3], b[4]
    hit = vi.first_true((h >= stop) if side < 0 else (lo <= stop), j)

    def stop_px(k: int, level: float) -> float:
        extreme = float(h[k]) if side < 0 else float(lo[k])  # a short's stop is hit by a rise, a long's by a fall
        if k == j:
            return _slip(level, extreme)
        return _past(-side, float(o[k]), level, extreme)

    if rule in ("close",) + tuple(CARRY):
        if hit >= 0:
            return stop_px(hit, stop), False, hit
        return float(c[-1]), rule != "close", len(c) - 1
    if rule in ("vwap", "fill"):
        if rule == "vwap":  # the first close beyond VWAP five or more minutes after the entry
            other = vi.first_true((m >= m[j] + 5) & ((c > line) if side < 0 else (c < line)), j + 1)
        else:  # the prior close is reached
            other = vi.first_true((lo <= pc) if side < 0 else (h >= pc), j + 1)
        if hit >= 0 and (other < 0 or hit <= other):
            return stop_px(hit, stop), False, hit
        if other >= 0:
            return (float(c[other]) if rule == "vwap" else float(pc)), False, other
        return float(c[-1]), False, len(c) - 1
    if rule[0] == "t" and rule[1:].isdigit():
        k = vi.first_true(m >= m[j] + int(rule[1:]), j)
        if hit >= 0 and (k < 0 or hit <= k):
            return stop_px(hit, stop), False, hit
        return (float(c[k]), False, k) if k >= 0 else (float(c[-1]), False, len(c) - 1)
    if rule[0] == "r" and rule[1:].isdigit():
        tgt = e + side * int(rule[1:]) * abs(e - stop)
        th = vi.first_true((lo <= tgt) if side < 0 else (h >= tgt), j)
        if hit >= 0 and (th < 0 or hit <= th):
            return stop_px(hit, stop), False, hit
        if th >= 0:
            return (min(float(o[th]), tgt) if side < 0 else max(float(o[th]), tgt)), False, th
        return float(c[-1]), False, len(c) - 1
    if rule.startswith("trail"):
        x = int(rule[5:]) / 100
        if side < 0:
            ext = np.minimum.accumulate(lo[j:])
            eff = np.minimum(stop, np.r_[np.inf, ext[:-1] * (1 + x)])
            k = vi.first_true(h[j:] >= eff, 0)
        else:
            ext = np.maximum.accumulate(h[j:])
            eff = np.maximum(stop, np.r_[-np.inf, ext[:-1] * (1 - x)])
            k = vi.first_true(lo[j:] <= eff, 0)
        if k < 0:
            return float(c[-1]), False, len(c) - 1
        return stop_px(j + k, float(eff[k])), False, j + k
    raise KeyError(rule)


def carry(D: dict, t: int, col: int, side: int, e: float, px: float, stop: float, rule: str) -> list[float]:
    """Daily returns after the entry day for the overnight and multi-day exits (daily bars on the entry day's raw
    scale; the stop stays live on the daily highs or lows; the next-open exit has no stop)."""
    O, H, L, C, F, new = D["O"], D["H"], D["L"], D["C"], D["F"], D["new"]
    f = F[t, col]
    out, prev = [], px
    for u in range(t + 1, min(len(D["dates"]), t + 1 + CARRY[rule])):
        if new[u, col] or not np.isfinite(C[u, col]) or not np.isfinite(f) or f <= 0:
            break
        o, h, lo, c = O[u, col] / f, H[u, col] / f, L[u, col] / f, C[u, col] / f
        o = o if np.isfinite(o) else c
        if rule == "next_open":
            out.append(side * (o - prev) / e)
            break
        if (h >= stop) if side < 0 else (lo <= stop):
            q = _past(-side, o, stop, h if side < 0 else lo)
            out.append(side * (q - prev) / e)
            break
        out.append(side * (c - prev) / e)
        prev = c
    return out


def trade_row(D: dict, cd: pd.Series, b: tuple, line: np.ndarray, side: int, j: int, e: float, stop: float,
              rule: str, prio: float) -> dict:
    px, held, k = exit_bar(side, j, e, stop, rule, b, line, float(cd["pc"]))
    rets = [side * (px - e) / e]
    if held:
        rets += carry(D, int(cd["t"]), int(cd["j"]), side, e, px, stop, rule)
    m, c, v, vw = b[0], b[4], b[5], b[6]
    pv = np.where(np.isfinite(vw) & (vw > 0), vw, c)
    return {"date": cd["date"], "t": int(cd["t"]), "symbol": cd["symbol"], "minute": int(m[j]), "side": side,
            "entry": e, "stop": stop, "price": float(cd["open"]),
            "liq": float(cd["pmv"]) + float(np.sum(pv[:j] * v[:j])), "prio": prio, "so": float(cd.get("so", np.nan)),
            "rets": np.array(rets), "nights": len(rets) - 1, "rule": rule,
            "opens": int(j == 0 and e == float(b[1][0])) + int(rule == "next_open" and len(rets) == 2),
            "xmin": -1 if held else int(m[k])}


COLS = ["date", "t", "symbol", "minute", "side", "entry", "stop", "price", "liq", "prio", "so", "rets", "nights",
        "rule", "opens", "xmin"]


def intraday_trades(store: vi.Store, D: dict, family: str, g: dict) -> pd.DataFrame:
    side = side_of(family)
    rows = []
    for k in candidates(store, family, g):
        cd = store.cands.loc[k]
        b = store.bars(k)
        if len(b[0]) < 10:
            continue
        line = vi.vwap(b[4], b[5], b[6])
        j, e = entry(family, g, b, line, cd)
        if j < 0 or not np.isfinite(e) or e <= 0:
            continue
        if side < 0:
            j, e = vi._ssr_fill(j, b, float(cd["pc"]), e)
            if j < 0:
                continue
        stop = stop_of(g["stop"], side, b, j, e, cd)
        if not np.isfinite(stop) or (stop - e) * side >= 0:
            continue
        rows.append(trade_row(D, cd, b, line, side, j, e, stop, g["exit"], abs(float(cd["gap"]))))
    return pd.DataFrame(rows, columns=COLS)


def intraday_placebo(store: vi.Store, D: dict, real: pd.DataFrame, rng: np.random.Generator,
                     by_day: dict) -> pd.DataFrame:
    """Each real trade moved to a random candidate of the family's scope and band that day: same minute (at that
    bar's open), side, stop distance and exit rule."""
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
        rows.append(trade_row(D, cd, b, line, int(r.side), j, e, stop, r.rule, float(r.prio)))
    return pd.DataFrame(rows, columns=COLS)


# ---------------------------------------------------------------- books

def book_paths(paths: list[tuple], dates: pd.DatetimeIndex, max_open: int = 20) -> tuple[pd.Series, np.ndarray]:
    """``core.swing_book`` that also says which paths it took."""
    out, gross = np.zeros(len(dates)), np.zeros(len(dates))
    taken = np.zeros(len(paths), bool)
    open_until: list[int] = []
    for i in sorted(range(len(paths)), key=lambda q: (paths[q][0], -paths[q][2])):
        i0, r, _, w = paths[i]
        open_until = [x for x in open_until if x >= i0]
        n = min(len(r), len(dates) - i0)
        if n <= 0 or w <= 0 or len(open_until) >= max_open or gross[i0:i0 + n].max() + w > 1.0 + 1e-9:
            continue
        out[i0:i0 + n] += w * r[:n]
        gross[i0:i0 + n] += w
        open_until.append(i0 + n - 1)
        taken[i] = True
    return pd.Series(out, index=dates), taken


def _costs(price: np.ndarray, so: np.ndarray, side: np.ndarray, nights: np.ndarray, opens: np.ndarray, table: dict,
           spread: float, fee_mult: float, gross: bool) -> tuple[np.ndarray, np.ndarray]:
    """(cost as a fraction of notional, availability weight) per trade; ``opens`` counts the legs traded at an
    open (0, 1 or 2)."""
    px = np.maximum(np.asarray(price, float), 0.01)
    p_av, fee = v15.lookup(table, px, np.asarray(so, float))
    if MODEL == "r3":
        p_av, fee = p_av * 0.8, np.maximum(2 * fee, 100.0)
    short = np.asarray(side) < 0
    avail = np.where(short, p_av, 1.0)
    if gross:
        return np.zeros(len(px)), avail
    if MODEL == "r3":
        hs = np.select([px < a for a, _ in R3_HALF[:-1]], [v for _, v in R3_HALF[:-1]], R3_HALF[-1][1])
        legs = 2 + (R3_OPEN - 1) * np.asarray(opens, float)
        cost = hs * spread * legs + 2 * np.minimum(R3_COMM / px, 0.01) + R3_SEC + R3_TAF / px
    else:
        cost = 2 * (core.half_spread(px, "mid") * spread + core.COMMISSION / px)
    return cost + np.where(short, fee * fee_mult / 100 / 360 * np.asarray(nights, float), 0.0), avail


def intra_book(trades: pd.DataFrame, dates: pd.DatetimeIndex, table: dict, spread: float, fee_mult: float = 1.0,
               gross: bool = False) -> tuple[pd.Series, list, np.ndarray]:
    """v14 intraday sizing (0.5% risk to the stop, 20% cap, 2% of the dollar volume before entry, the first five
    trades a day by minute) with every trade booked as a path."""
    if trades.empty:
        return pd.Series(0.0, index=dates), [], np.zeros(0, bool)
    t = trades.sort_values(["date", "minute", "prio"], ascending=[True, True, False])
    t = t.groupby("date", sort=False).head(5)
    e, s = t["entry"].to_numpy(float), t["stop"].to_numpy(float)
    dist = np.abs(e - s) / e
    w = np.minimum(np.minimum(0.20, 0.005 / np.maximum(dist, 1e-4)), 0.02 * np.nan_to_num(t["liq"].to_numpy(float))
                   / core.ACCOUNT)
    cost, avail = _costs(t["price"].to_numpy(), t["so"].to_numpy(), t["side"].to_numpy(), t["nights"].to_numpy(),
                         t["opens"].to_numpy(), table, spread, fee_mult, gross)
    paths = []
    for i, (i0, r, pr) in enumerate(zip(t["t"].to_numpy(), t["rets"], t["prio"].to_numpy(float))):
        rr = np.array(r, float)
        rr[0] -= cost[i]
        paths.append((int(i0), rr, float(pr), float(w[i] * avail[i])))
    series, taken = book_paths(paths, dates)
    return series, paths, taken


@dataclass
class Spec:
    j: int
    t: int
    kind: str  # "open" (enters at the open of row t) or "close" (at the close of row t)
    side: int
    hold: int  # sessions held; for "close" entries the sessions after row t
    stop: float  # fraction against the entry, nan for none
    target: float  # fraction in favour, nan for none
    trail: float  # fraction from the best close since entry, nan for none
    rule: str  # "time", "strength" (short: a close above the prior high), "weak" (long: a close below the prior
    #            low), "ma10" (long: a close below the 10-day average), "open1" (out at the next open)
    prio: float


def path19(D: dict, s: Spec, table: dict, spread: float, fee_mult: float = 1.0, gross: bool = False,
           w_max: float = 0.05) -> tuple[int, np.ndarray, float, float] | None:
    """(first row with a return, daily net returns on the entry price, priority, weight) of one trade."""
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
    stop = entry * (1 + side * -s.stop) if np.isfinite(s.stop) else np.nan
    tgt = entry * (1 + side * s.target) if np.isfinite(s.target) else np.nan
    best, prev, rets = entry, entry, []
    for u in range(first, last + 1):
        if new[u, j] and (u > first or s.kind == "close"):
            break
        o, h, lo, c = O[u, j], H[u, j], L[u, j], C[u, j]
        if not np.isfinite(c):
            break
        o = o if np.isfinite(o) else c
        if s.rule == "open1":
            rets.append(side * (o - prev) / entry)
            break
        eff = stop
        if np.isfinite(s.trail) and u > first:
            lvl = best * (1 + side * -s.trail)
            eff = lvl if not np.isfinite(eff) else (min(eff, lvl) if side < 0 else max(eff, lvl))
        opened = u == first and s.kind == "open"
        if np.isfinite(eff) and ((h >= eff) if side < 0 else (lo <= eff)):
            extreme = h if side < 0 else lo
            px = _slip(eff, extreme) if opened else _past(-side, o, eff, extreme)
            rets.append(side * (px - prev) / entry)
            break
        if np.isfinite(tgt) and ((lo <= tgt) if side < 0 else (h >= tgt)):
            px = tgt if opened else (min(o, tgt) if side < 0 else max(o, tgt))
            rets.append(side * (px - prev) / entry)
            break
        rets.append(side * (c - prev) / entry)
        prev = c
        best = min(best, c) if side < 0 else max(best, c)
        if u > 0 and ((s.rule == "strength" and c > H[u - 1, j]) or (s.rule == "weak" and c < L[u - 1, j])):
            break
        if s.rule == "ma10" and u >= 9 and c < np.nanmean(C[u - 9:u + 1, j]):
            break
    if not rets:
        return None
    r = np.array(rets)
    nights = max(len(r) - (0 if s.kind == "close" else 1), 0)
    w = min(w_max, 0.01 * D["DV1"][t, j] / core.ACCOUNT) if np.isfinite(D["DV1"][t, j]) else 0.0
    opens = int(s.kind == "open") + int(s.rule == "open1")
    cost, avail = _costs(np.array([raw]), np.array([D["SO"][t, j]]), np.array([side]), np.array([nights]),
                         np.array([opens]), table, spread, fee_mult, gross)
    if not gross and side < 0 and s.kind == "open" and t > 0 and entry <= 0.9 * C[t - 1, j]:
        cost = cost + vs.SSR_EXTRA
    r[0] -= cost[0]
    return first, r, s.prio, w * float(avail[0])


def daily_book(D: dict, specs: list[Spec], table: dict, spread: float, fee_mult: float = 1.0,
               gross: bool = False) -> tuple[pd.Series, list, np.ndarray]:
    paths = [p for s in specs if (p := path19(D, s, table, spread, fee_mult, gross)) is not None]
    series, taken = book_paths(paths, D["dates"])
    return series, paths, taken


def trade_stats(paths: list, taken: np.ndarray, dates: pd.DatetimeIndex) -> dict:
    """Per entry year: [trades taken, sum of their net returns, winners, worst net return]."""
    years: dict[str, list] = {}
    for (i0, r, _, _), tk in zip(paths, taken):
        if not tk:
            continue
        net = float(np.sum(r))
        a = years.setdefault(str(dates[i0].year), [0, 0.0, 0, 0.0])
        a[0] += 1
        a[1] += net
        a[2] += int(net > 0)
        a[3] = min(a[3], net)
    return {"years": years}


# ---------------------------------------------------------------- daily specs

def _recent(mask: np.ndarray, val: np.ndarray, k: int = K_AFTER) -> tuple[np.ndarray, np.ndarray]:
    """Whether a setup happened in the k rows before each row, and the largest setup value among them."""
    v = pd.DataFrame(np.where(mask, val, np.nan)).rolling(k, min_periods=1).max().shift(1).to_numpy()
    return np.isfinite(v), v


def _exit_terms(g: dict) -> tuple[float, float, float, str]:
    stop = np.nan if g.get("stop", "none") == "none" else float(g["stop"])
    ex = g.get("exit", "time")
    target = int(ex[6:]) / 100 if ex.startswith("target") else np.nan
    trail = int(ex[5:]) / 100 if ex.startswith("trail") else np.nan
    rule = ex if ex in ("strength", "weak", "ma10", "open1") else "time"
    return stop, target, trail, rule


def _setup_trigger(D: dict, S: np.ndarray, val: np.ndarray, trig: str) -> list[tuple[int, int, str, float]]:
    """(entry row, column, kind, priority) of the trades of a setup mask and a trigger."""
    O, H, L, C = D["O"], D["H"], D["L"], D["C"]
    T = C.shape[0]
    with np.errstate(invalid="ignore"):
        if trig == "open":
            return [(t + 1, j, "open", float(val[t, j])) for t, j in zip(*np.nonzero(S)) if t + 1 < T]
        if trig == "close_c":  # at the setup day's own close
            return [(t, j, "close", float(val[t, j])) for t, j in zip(*np.nonzero(S)) if t + 1 < T]
        R, rv = _recent(S, val)
        cond = {"lowclose": C < vs._shift(L, 1), "redclose": C < O, "redclose_c": C < O,
                "greenclose": C > O, "highclose": C > vs._shift(H, 1),
                "gapdown": O <= 0.95 * vs._shift(C, 1)}[trig]
        tt, jj = np.nonzero(R & cond)
    if trig == "redclose_c":
        return [(t, j, "close", float(rv[t, j])) for t, j in zip(tt, jj)]
    if trig == "gapdown":
        return [(t, j, "open", float(rv[t, j])) for t, j in zip(tt, jj)]
    return [(t + 1, j, "open", float(rv[t, j])) for t, j in zip(tt, jj) if t + 1 < T]


def _once_specs(rows: list, side: int, g: dict, hold: int) -> list[Spec]:
    if not rows:
        return []
    t = np.array([r[0] for r in rows])
    j = np.array([r[1] for r in rows])
    keep = vs._once(t, j, ONCE)
    stop, target, trail, rule = _exit_terms(g)
    return [Spec(int(r[1]), int(r[0]), r[2], side, hold, stop, target, trail, rule, r[3])
            for r, k in zip(rows, keep) if k]


def daily_specs(D: dict, E: dict, family: str, g: dict) -> list[Spec]:
    """Setups use the setup day's close, range, volume and dollar volume, all known at that close; trades enter at
    the next open or later, except the overnight families, which enter at that close."""
    O, H, L, C, P = D["O"], D["H"], D["L"], D["C"], D["P"]
    prev = vs._shift(C, 1)
    base = (D["DV"] >= 1e6) & D["valid"]
    with np.errstate(invalid="ignore", divide="ignore"):
        if family == "DS1_RUNUP":
            w = g["window"]
            low = prev if w == 1 else pd.DataFrame(C).rolling(w, min_periods=max(2, w // 2)).min().shift(1).to_numpy()
            rise = C / low - 1
            S = (rise >= g["rise"]) & v18._band_arr(P, None) & base
            return _once_specs(_setup_trigger(D, S, rise, g["trig"]), -1, g, g["hold"])
        if family == "DL1_CRASHBOUNCE":
            r1 = C / prev - 1
            news = ~E["NEWS"] if g["news"] == "none" else np.ones_like(base)
            S = (r1 <= -g["fall"]) & news & v18._band_arr(P, None) & base
            return _once_specs(_setup_trigger(D, S, -r1, g["trig"]), 1, g, g["hold"])
        if family == "DL2_MOMO":
            r1 = C / prev - 1
            V = E["V"]
            v20 = pd.DataFrame(V).rolling(20, min_periods=10).mean().shift(1).to_numpy()
            S = (r1 >= g["up"]) & ((C - L) >= 0.75 * (H - L)) & (V >= 3 * v20) & v18._band_arr(P, None) & base
            return _once_specs(_setup_trigger(D, S, r1, g["trig"]), 1, g, g["hold"])
        if family in ("ON1_NIGHTSHORT", "ON2_NIGHTLONG"):
            r1 = C / prev - 1
            st = g["setup"]
            if st.startswith("gapfail"):
                cond = (O >= prev * (1 + int(st[7:]) / 100)) & (C <= O * 0.90)
            elif st.startswith("weak"):
                cond = (r1 >= int(st[4:]) / 100) & ((C - L) <= 0.25 * (H - L))
            elif st.startswith("strong"):
                cond = (r1 >= int(st[6:]) / 100) & ((C - L) >= 0.90 * (H - L))
            elif st.startswith("crash"):
                cond = r1 <= -int(st[5:]) / 100
            else:  # run200red
                low5 = pd.DataFrame(C).rolling(5, min_periods=3).min().shift(1).to_numpy()
                cond = (C >= 3.0 * low5) & (C < O)
            S = cond & v18._band_arr(P, g["band"]) & base
            side = side_of(family)
            hold, rule = {"next_open": (1, "open1"), "next_close": (1, "time"), "close2": (2, "time"),
                          "close3": (3, "time")}[g["exit"]]
            stop = np.nan if g.get("stop", "none") == "none" else float(g["stop"])
            T = C.shape[0]
            return [Spec(int(j), int(t), "close", side, hold, stop, np.nan, np.nan, rule, float(abs(r1[t, j])))
                    for t, j in zip(*np.nonzero(S)) if t + 1 < T]
    if family == "DS2_EVENTSHORT":
        ok = v18._band_arr(D["P1"], None) & (D["DV1"] >= 1e6) & D["valid1"]
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
        return _once_specs(rows, -1, g, g["hold"])
    raise KeyError(family)


def daily_placebo(D: dict, specs: list[Spec], rng: np.random.Generator, band: str | None) -> list[Spec]:
    """Each real trade moved to a random symbol of the price band (prior close, $1M of dollar volume) on its entry
    row, with the same entry kind, side and exit terms."""
    ok = v18._band_arr(D["P1"], band) & (D["DV1"] >= 1e6) & D["valid1"]
    out = []
    for s in specs:
        cols = np.flatnonzero(ok[s.t])
        if len(cols):
            out.append(Spec(int(rng.choice(cols)), s.t, s.kind, s.side, s.hold, s.stop, s.target, s.trail, s.rule,
                            s.prio))
    return out
