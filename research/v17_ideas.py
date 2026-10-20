"""v17 families: liquid-stock gap fades and bounces, earnings gaps, more small-cap fades, offering-day and halt
trades, index gap fades, VIX spikes, weekly reversals. Pre-registered in docs/research/V17_PREREGISTRATION.md.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from aurora.research import v14_core as core
from aurora.research import v14_intraday as vi
from aurora.research import v14_macro as vm
from aurora.research import v15_ah as v15

INTRA_DIMS = {
    "N1_LIQFADE": {"gap": (0.04, 0.08), "exit": ("close", "vwap")},
    "N2_LIQBOUNCE": {"gap": (-0.04, -0.08), "exit": ("close", "vwap")},
    "N3_EARNGO": {"gap": (0.04, 0.08), "exit": ("close", "vwap")},
    "N4_OPENFADE": {"gap": (0.50, 1.00), "stop": (0.30, 0.60)},
    "N5_LATEFADE": {"gap": (0.30, 0.50)},
    "N6_PMFADE": {"gap": (0.30, 0.50), "drop": (0.10, 0.20)},
    "N7_OFFERDAY": {"gap": (-0.20, -0.30)},
    "N8_HALTDOWN": {"side": (1, -1)},
}
INDEX_DIMS = {"N9_IDXGAP": {"inst": ("SPY", "IWM"), "thr": (0.005, 0.01), "exit": ("close", "fill")}}
MACRO_DIMS = {"N10_VIXSPIKE": {"rise": (0.20, 0.30), "hold": (5, 10)},
              "N12_SECTORREV": {"top": (1, 2)}}
WEEKLY_DIMS = {"N11_WEEKREV": {"price": (5.0, 10.0), "sides": ("long", "ls")}}


def scope(store: vi.Store, family: str) -> pd.Series:
    c = store.cands
    band = (c["open"] >= 1) & (c["open"] <= 20)
    if family in ("N1_LIQFADE", "N2_LIQBOUNCE", "N3_EARNGO"):
        return c["s_in_play"]
    if family == "N7_OFFERDAY":
        return band & c["s_gap_down"]
    if family == "N8_HALTDOWN":
        return band & (c["s_gap_up"] | c["s_runner"])
    return band & c["s_gap_up"]


def candidates(store: vi.Store, family: str, g: dict) -> pd.Index:
    c = store.cands
    s = scope(store, family)
    if family == "N1_LIQFADE":
        s = s & (c["gap"] >= g["gap"]) & ~c["news"]
    elif family == "N2_LIQBOUNCE":
        s = s & (c["gap"] <= g["gap"]) & ~c["news"]
    elif family == "N3_EARNGO":
        s = s & c["earn"] & (c["gap"].abs() >= g["gap"])
    elif family in ("N4_OPENFADE", "N5_LATEFADE"):
        s = s & (c["gap"] >= g["gap"]) & ~c["news"]
    elif family == "N6_PMFADE":
        s = s & (c["gap"] >= g["gap"]) & ~c["news"] & (c["open"] <= c["pmh"] * (1 - g["drop"]))
    elif family == "N7_OFFERDAY":
        s = s & (c["gap"] <= g["gap"]) & c["offer"]
    return c.index[s.to_numpy()]


def _entry(family: str, g: dict, b: tuple, cd: pd.Series) -> tuple[int, int, float, float, str]:
    m, o, h, lo, c = b[0], b[1], b[2], b[3], b[4]
    none = (0, -1, np.nan, np.nan, "close")
    if family == "N1_LIQFADE":
        j, entry, _ = vi.entry_orb(b, 5, -1)
        return (-1, j, entry, float(h[:j].max()), g["exit"]) if j > 0 else none
    if family == "N2_LIQBOUNCE":
        j, entry, stop = vi.entry_orb(b, 5, 1)
        return (1, j, entry, stop, g["exit"]) if j >= 0 else none
    if family == "N3_EARNGO":
        side = 1 if cd["gap"] > 0 else -1
        j, entry, stop = vi.entry_orb(b, 5, side)
        return (side, j, entry, stop, g["exit"]) if j >= 0 else none
    if family == "N4_OPENFADE":
        return -1, 0, float(o[0]), float(o[0]) * (1 + g["stop"]), "close"
    if family == "N5_LATEFADE":
        hi5, lo5, first = vi.opening_range(m, h, lo, 5)
        upto = int(np.searchsorted(m, 30))
        if first == 0 or upto <= first or lo[first:upto].min() < lo5:
            return none
        j, entry, _ = vi.entry_orb(b, 30, -1)
        return (-1, j, entry, float(h[:j].max()), "close") if j > 0 else none
    if family == "N6_PMFADE":
        return -1, 0, float(o[0]), float(cd["pmh"]), "close"
    if family == "N7_OFFERDAY":
        j, entry, stop = vi.entry_orb(b, 5, -1)
        return (-1, j, entry, stop, "close") if j >= 0 else none
    if family == "N8_HALTDOWN":
        gaps = np.flatnonzero(np.diff(m) >= 6)
        for k in gaps:
            before = int(np.searchsorted(m, m[k] - 5))
            if c[before] > 0 and c[k] / c[before] - 1 <= -0.10 and m[k + 1] <= vi.LAST_ENTRY:
                above = o[k + 1] > c[k]
                if (g["side"] > 0 and above) or (g["side"] < 0 and not above):
                    return g["side"], k + 1, float(o[k + 1]), float(c[k]), "close"
                return none
        return none
    raise KeyError(family)


def intraday_trades(store: vi.Store, family: str, g: dict) -> pd.DataFrame:
    rows = []
    for k in candidates(store, family, g):
        cd = store.cands.loc[k]
        b = store.bars(k)
        if len(b[0]) < 10:
            continue
        side, j, entry, stop, mode = _entry(family, g, b, cd)
        if j < 0 or not np.isfinite(entry) or not np.isfinite(stop) or (stop - entry) * side >= 0:
            continue
        if side < 0:
            j, entry = vi._ssr_fill(j, b, float(cd["pc"]), entry)
            if j < 0 or (stop - entry) * side >= 0:
                continue
        line = vi.vwap(b[4], b[5], b[6])
        ex, _ = vi.run_exit(side, j, entry, stop, mode, b, line)
        r = vi._row(cd, side, j, entry, stop, ex, b, abs(float(cd["gap"])))
        r["mode"] = mode
        rows.append(r)
    cols = ["date", "symbol", "minute", "side", "entry", "exit", "stop", "price", "liq", "prio", "nights", "so",
            "mode"]
    return pd.DataFrame(rows, columns=cols)


def pool_by_day(store: vi.Store, family: str) -> dict:
    s = scope(store, family).to_numpy()
    out: dict = {}
    for k, d in zip(store.cands.index[s], store.cands.loc[s, "date"]):
        out.setdefault(pd.Timestamp(d), []).append(k)
    return out


# ---------------------------------------------------------------- index gap fade

def idx_gap(index: dict, g: dict) -> tuple[pd.Series, pd.Series]:
    """(direction, gross return of the trade) per day."""
    d_, r_ = {}, {}
    for day, (pc, b) in sorted(index[g["inst"]].items()):
        m, o, h, lo, c = b[0], b[1], b[2], b[3], b[4]
        if len(m) < 300 or not np.isfinite(pc) or pc <= 0:
            continue
        gap = float(o[0]) / pc - 1
        if abs(gap) < g["thr"]:
            d_[day], r_[day] = 0.0, 0.0
            continue
        side = -np.sign(gap)
        ex = float(c[-1])
        if g["exit"] == "fill":
            hit = vi.first_true((h >= pc) if side > 0 else (lo <= pc), 0)
            if hit >= 0:
                ex = pc
        d_[day], r_[day] = float(side), float(side * (ex / float(o[0]) - 1))
    return pd.Series(d_), pd.Series(r_)


# ---------------------------------------------------------------- macro and weekly

def vix_spike(X: dict, g: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    vix = X["vix"].reindex(X["dates"]).ffill()
    sig = (vix / vix.shift(1) - 1 >= g["rise"]).astype(float)
    held = sig.rolling(g["hold"], min_periods=1).max().shift(1).fillna(0.0)
    return pd.DataFrame({"SPY": held}), X["etf_ret"][["SPY"]]


def sector_rev(X: dict, g: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    cols = [s for s in vm.SECTORS if s in X["etf_close"]]
    c = X["etf_close"][cols]
    wret = c / c.shift(5) - 1
    week = c.index.to_period("W")
    last = pd.Series(c.index, index=c.index).groupby(week).transform("max") == pd.Series(c.index, index=c.index)
    pick = (wret.rank(axis=1, ascending=True) <= g["top"]).astype(float).div(g["top"])
    pos = pick.where(last).ffill().shift(1).fillna(0.0)
    return pos, X["etf_ret"][cols]


MACRO_RULES = {"N10_VIXSPIKE": vix_spike, "N12_SECTORREV": sector_rev}


def macro(family: str, g: dict, X: dict, shift: int = 0) -> pd.Series:
    pos, rets = MACRO_RULES[family](X, g)
    if shift:
        pos = vm.shift_positions(pos, shift)
    return vm.returns_from_positions(pos, rets.reindex(pos.index), vm.ETF_COST)


def week_rev(D: dict, E: dict, g: dict, table: dict, spread: float, rng: np.random.Generator | None = None) -> pd.Series:
    C, P, dates = D["C"], D["P"], D["dates"]
    r1 = np.vstack([np.full((1, C.shape[1]), np.nan), C[1:] / C[:-1] - 1])
    news5 = pd.DataFrame(E["NEWS"]).rolling(5, min_periods=1).max().to_numpy() > 0
    wk = pd.Series(np.arange(len(dates)), index=dates).groupby(dates.to_period("W")).max().to_numpy()
    out = np.zeros(len(dates))
    for a, b in zip(wk[:-1], wk[1:]):
        wret = C[a] / C[max(a - 5, 0)] - 1
        ok = (P[a] >= g["price"]) & (D["DV"][a] >= 20e6) & D["valid"][a] & ~news5[a] & np.isfinite(wret)
        if ok.sum() < 50:
            continue
        idx = np.flatnonzero(ok)
        order = idx[np.argsort(wret[idx])]
        k = max(1, len(order) // 10)
        longs, shorts = order[:k][:20], order[-k:][-20:]
        if g["sides"] == "long":
            shorts = shorts[:0]
        if rng is not None:
            longs = rng.choice(idx, len(longs), replace=False)
            shorts = rng.choice(idx, len(shorts), replace=False) if len(shorts) else shorts
        for side, names in ((1, longs), (-1, shorts)):
            if not len(names):
                continue
            px = np.maximum(P[a, names], 0.01)
            cost = 2 * (core.half_spread(px, "mid") * spread + core.COMMISSION / px)
            w = np.full(len(names), 0.05)
            if side < 0:
                pav, fee = v15.lookup(table, px, D["SO"][a, names])
                w = w * pav
                cost = cost + fee / 100 / 360 * 7
            # P&L on the price at the rebalance: positions are not resized within the holding period
            rr = np.nan_to_num((C[a + 1:b + 1][:, names] - C[a:b][:, names]) / C[a, names], nan=0.0)
            out[a + 1:b + 1] += side * (rr * w).sum(axis=1)
            out[a + 1] -= float((w * cost).sum())
    return pd.Series(out, index=dates)
