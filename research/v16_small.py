"""v16 small-cap families. Pre-registered in docs/research/V16_PREREGISTRATION.md.

Intraday families run on the v14 minute store (``vi.Store``) and are costed with v15's R1 book; daily families
run on the v14 daily arrays ``D`` plus the v16 extras ``E`` (raw volume, off-exchange share, short ratio, news
flags, reverse splits, offerings after spikes).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from aurora.research import v14_core as core
from aurora.research import v14_intraday as vi
from aurora.research import v14_swing as vs
from aurora.research import v15_ah as v15

B8 = {"entry": "orl5", "exit": "close"}
INTRA_DIMS = {
    "S1_B8NEWS": {"gap": (0.30, 0.50), "pmv": (250e3, 1e6), "news": (True, False)},
    "S2_B8SHELF": {"gap": (0.30, 0.50), "shelf": (True, False)},
    "S3_B8FIRST": {"gap": (0.30, 0.50), "repeat": (False, True)},
    "S4_PARABOLIC": {"ext": (0.30, 0.50), "exit": ("vwaptouch", "close")},
    "S5_BACKSIDE": {"drop": (0.15, 0.25), "hod": (90, 389)},
    "S6_GAPDOWN": {"gap": (-0.20, -0.35), "pmv": (250e3, 1e6)},
    "L1_NEWSGO": {"gap": (0.20, 0.40), "orb": (1, 5), "exit": ("close", "vwap")},
    "L2_PANIC": {"drop": (0.20, 0.35), "exit": ("close", "vwap")},
    "L3_R2G": {"within": (30, 120), "exit": ("close", "vwap")},
    "L4_MICROPB": {"gap": (0.20, 0.40), "exit": ("close", "vwap")},
    "L5_PMHOD": {"gap": (0.20, 0.40), "pmv": (250e3, 1e6)},
}
DAILY_DIMS = {
    "S7_DAY2FADE": {"gap": (0.30, 0.50), "hold": (1, 3)},
    "S8_RETAIL": {"off": (0.60, 0.75), "hold": (5, 10)},
    "S9_OFFERSPIKE": {"hold": (20, 60), "stop": (np.nan, 1.0)},
    "S10_RSPLIT": {"ratio": (5, 10), "hold": (20, 60)},
    "S11_DEFICIENCY": {"hold": (60, 120)},
    "L8_NEWSDRIFT": {"move": (0.10, 0.20), "sides": ("long", "ls")},
}
WEEKLY_DIMS = {
    "L6_MAXREV": {"price": (2.0, 5.0), "sides": ("long", "ls")},
    "L7_SHORTRATIO": {"sides": ("long", "ls")},
}


# ---------------------------------------------------------------- intraday

def scope(store: vi.Store, family: str) -> pd.Series:
    c = store.cands
    band = (c["open"] >= 1) & (c["open"] <= 20)
    if family == "S6_GAPDOWN":
        return band & c["s_gap_down"]
    if family in ("L2_PANIC", "L3_R2G"):
        return band & c["s_day2"]
    return band & (c["s_gap_up"] | c["s_runner"])


def candidates(store: vi.Store, family: str, g: dict) -> pd.Index:
    c = store.cands
    s = scope(store, family)
    if family in ("S1_B8NEWS", "S2_B8SHELF", "S3_B8FIRST"):
        s = s & c["s_gap_up"] & (c["gap"] >= g["gap"]) & (c["pmv"] >= g.get("pmv", 250e3))
        flag = {"S1_B8NEWS": ("news", g.get("news")), "S2_B8SHELF": ("shelf", g.get("shelf")),
                "S3_B8FIRST": ("repeat", g.get("repeat"))}[family]
        s = s & (c[flag[0]] == flag[1])
    elif family == "S6_GAPDOWN":
        s = s & (c["gap"] <= g["gap"]) & (c["pmv"] >= g["pmv"])
    elif family == "L1_NEWSGO":
        s = s & c["s_gap_up"] & (c["gap"] >= g["gap"]) & c["news"] & (c["pmv"] >= 250e3)
    elif family in ("L4_MICROPB", "L5_PMHOD"):
        s = s & c["s_gap_up"] & (c["gap"] >= g["gap"]) & (c["pmv"] >= g.get("pmv", 250e3))
    elif family == "L3_R2G":
        s = s & (c["open"] < c["pc"])
    return c.index[s.to_numpy()]


def exit16(side: int, i: int, entry: float, stop: float, mode: str, b: tuple, line: np.ndarray) -> float:
    """``vi.run_exit`` plus "vwaptouch": cover at VWAP the first time a later bar reaches it."""
    if mode != "vwaptouch":
        return vi.run_exit(side, i, entry, stop, mode, b, line)[0]
    h, lo = b[2], b[3]
    hit = vi.first_true((h >= stop) if side < 0 else (lo <= stop), i)
    touch = vi.first_true((lo <= line) if side < 0 else (h >= line), i + 1)
    if hit >= 0 and (touch < 0 or hit <= touch):
        return vi.run_exit(side, i, entry, stop, "close", b, line)[0]
    if touch >= 0:
        return float(line[touch])
    return float(b[4][-1])


def _entry(family: str, g: dict, b: tuple, line: np.ndarray, cd: pd.Series) -> tuple[int, int, float, float, str]:
    """(side, entry bar, entry price, stop, exit mode); entry bar -1 when there is no trade."""
    m, o, h, lo, c = b[0], b[1], b[2], b[3], b[4]
    none = (0, -1, np.nan, np.nan, "close")
    if family in ("S1_B8NEWS", "S2_B8SHELF", "S3_B8FIRST"):
        j, entry, _ = vi.entry_orb(b, 5, -1)
        return (-1, j, entry, float(h[:j].max()), "close") if j > 0 else none
    if family == "S6_GAPDOWN":
        j, entry, stop = vi.entry_orb(b, 5, -1)
        return (-1, j, entry, stop, "close") if j >= 0 else none
    if family == "L1_NEWSGO":
        j, entry, stop = vi.entry_orb(b, g["orb"], 1)
        return (1, j, entry, stop, g["exit"]) if j >= 0 else none
    if family == "S4_PARABOLIC":
        ext = (h >= line * (1 + g["ext"])) & (m >= 30) & (m <= vi.LAST_ENTRY)
        j0 = vi.first_true(ext, 0)
        if j0 < 0:
            return none
        for j in range(max(j0 + 1, 1), len(c)):
            if m[j] > vi.LAST_ENTRY:
                break
            if h[j] < h[j - 1] and c[j] < lo[j - 1]:
                return -1, j, float(c[j]), float(h[:j + 1].max()), g["exit"]
        return none
    if family == "S5_BACKSIDE":
        hod_i = int(np.argmax(h[m <= vi.LAST_ENTRY])) if (m <= vi.LAST_ENTRY).any() else -1
        if hod_i < 0 or m[hod_i] > g["hod"]:
            return none
        hod = float(h[hod_i])
        d = vi.first_true(lo <= hod * (1 - g["drop"]), hod_i + 1)
        if d < 0:
            return none
        for j in range(d + 5, len(c)):
            if m[j] > vi.LAST_ENTRY:
                break
            if c[j] < lo[j - 5:j].min() and h[d:j].max() < hod:
                return -1, j, float(c[j]), float(h[d:j + 1].max()), "close"
        return none
    if family == "L2_PANIC":
        early = m < 60
        if not early.any():
            return none
        k = int(np.argmin(np.where(early, lo, np.inf)))
        if lo[k] > o[0] * (1 - g["drop"]):
            return none
        for j in range(k + 1, len(c)):
            if m[j] > vi.LAST_ENTRY:
                break
            if c[j] > h[j - 1]:
                return 1, j, float(c[j]), float(lo[k:j + 1].min()), g["exit"]
        return none
    if family == "L3_R2G":
        pc = float(cd["pc"])
        j = vi.first_true((c > pc) & (m < g["within"]), 1)
        if j < 0:
            return none
        return 1, j, float(c[j]), float(lo[:j + 1].min()), g["exit"]
    if family == "L4_MICROPB":
        green = c > o
        for j in range(4, len(c)):
            if m[j] >= 30:
                break
            # j: the bar that breaks the last red bar's high; red bars j-r..j-1 (1-3), green run before them
            for r in (1, 2, 3):
                s = j - r
                if s < 3 or not (~green[s:j]).all():
                    continue
                if not green[s - 3:s].all() or h[s - 1] < h[:s].max():
                    continue
                run_lo, run_hi = float(lo[s - 3]), float(h[s - 1])
                if lo[s:j].min() < (run_lo + run_hi) / 2 or h[j] <= h[j - 1]:
                    continue
                entry = max(float(h[j - 1]), float(o[j]))
                return 1, j, entry, float(lo[s:j].min()), g["exit"]
        return none
    if family == "L5_PMHOD":
        k = int(np.searchsorted(m, 270))
        if k >= len(m) or c[k - 1 if k > 0 else 0] <= o[0]:
            return none
        hod = float(h[:k].max())
        j = vi.first_true((h > hod) & (m <= 360), k)
        if j < 0:
            return none
        entry = max(hod, float(o[j]))
        stop = float(line[j - 1])
        return (1, j, entry, stop, "close") if stop < entry else none
    raise KeyError(family)


def intraday_trades(store: vi.Store, family: str, g: dict) -> pd.DataFrame:
    rows = []
    for k in candidates(store, family, g):
        cd = store.cands.loc[k]
        b = store.bars(k)
        if len(b[0]) < 10:
            continue
        line = vi.vwap(b[4], b[5], b[6])
        side, j, entry, stop, mode = _entry(family, g, b, line, cd)
        if j < 0 or not np.isfinite(entry) or not np.isfinite(stop) or (stop - entry) * side >= 0:
            continue
        if side < 0:
            j, entry = vi._ssr_fill(j, b, float(cd["pc"]), entry)
            if j < 0 or (stop - entry) * side >= 0:
                continue
        ex = exit16(side, j, entry, stop, mode, b, line)
        r = vi._row(cd, side, j, entry, stop, ex, b, float(cd["gap"]))
        r["mode"] = mode
        rows.append(r)
    cols = ["date", "symbol", "minute", "side", "entry", "exit", "stop", "price", "liq", "prio", "nights", "so",
            "mode"]
    return pd.DataFrame(rows, columns=cols)


def intraday_placebo(store: vi.Store, family: str, real: pd.DataFrame, rng: np.random.Generator,
                     by_day: dict) -> pd.DataFrame:
    rows = []
    for _, r in real.iterrows():
        ch = by_day.get(pd.Timestamp(r["date"]), [])
        if not ch:
            continue
        k = int(rng.choice(ch))
        cd = store.cands.loc[k]
        b = store.bars(k)
        if len(b[0]) < 10:
            continue
        j = int(np.searchsorted(b[0], r["minute"]))
        if j >= len(b[0]) or b[0][j] > vi.LAST_ENTRY + 30:
            continue
        entry = float(b[1][j])
        dist = abs(r["entry"] - r["stop"]) / r["entry"]
        stop = entry * (1 - r["side"] * dist)
        ex = exit16(int(r["side"]), j, entry, stop, r["mode"], b, vi.vwap(b[4], b[5], b[6]))
        row = vi._row(cd, int(r["side"]), j, entry, stop, ex, b, float(r["prio"]))
        row["mode"] = r["mode"]
        rows.append(row)
    return pd.DataFrame(rows, columns=real.columns)


def pool_by_day(store: vi.Store, family: str) -> dict:
    s = scope(store, family).to_numpy()
    out: dict = {}
    for k, d in zip(store.cands.index[s], store.cands.loc[s, "date"]):
        out.setdefault(pd.Timestamp(d), []).append(k)
    return out


# ---------------------------------------------------------------- daily

def daily_specs(D: dict, E: dict, family: str, g: dict) -> tuple[list, float, int]:
    """(specs, weight per position, max open)."""
    O, C, P = D["O"], D["C"], D["P"]
    T = C.shape[0]
    r1 = np.full_like(C, np.nan)
    r1[1:] = C[1:] / C[:-1] - 1
    band = (P >= 1) & (P <= 20) & (D["DV"] >= 1e6) & D["valid"]
    out = []
    if family == "S7_DAY2FADE":
        prev = np.vstack([np.full((1, C.shape[1]), np.nan), C[:-1]])
        cond = (O / prev - 1 >= g["gap"]) & (C <= O * 0.90) & band
        for t, j in zip(*np.nonzero(cond)):
            if t + 1 < T:
                out.append(vs.Spec(int(j), int(t + 1), "open", -1, g["hold"], 0.30, float(O[t, j] / prev[t, j] - 1)))
        return out, 0.05, 20
    if family == "S8_RETAIL":
        V = E["V"]
        v20 = pd.DataFrame(V).rolling(20, min_periods=10).mean().shift(1).to_numpy()
        cond = (E["OFF"] >= g["off"]) & (r1 >= 0.30) & (V >= 5 * v20) & band
        for t, j in zip(*np.nonzero(cond)):
            if t + 1 < T:
                out.append(vs.Spec(int(j), int(t + 1), "open", -1, g["hold"], 0.50, float(r1[t, j])))
        return out, 0.05, 20
    if family == "S9_OFFERSPIKE":
        for t, j in E["offer_spike"]:
            if t < T:
                out.append(vs.Spec(int(j), int(t), "open", -1, g["hold"], g["stop"], 0.0))
        return out, 0.02, 40
    if family == "S10_RSPLIT":
        for t, j, ratio in E["rsplit"]:
            if ratio >= g["ratio"] and t < T:
                out.append(vs.Spec(int(j), int(t), "open", -1, g["hold"], np.nan, float(ratio)))
        return out, 0.02, 40
    if family == "S11_DEFICIENCY":
        ev = D["events"]["delist"]
        for t, j in zip(ev["t"].to_numpy(), ev["j"].to_numpy()):
            if t < T:
                out.append(vs.Spec(int(j), int(t), "open", -1, g["hold"], np.nan, 0.0))
        return out, 0.02, 40
    if family == "L8_NEWSDRIFT":
        liquid = (P >= 1) & (D["DV"] >= 1e6) & D["valid"] & E["NEWS"]
        for t, j in zip(*np.nonzero(liquid & (r1 >= g["move"]))):
            if t + 1 < T:
                out.append(vs.Spec(int(j), int(t + 1), "open", 1, 5, np.nan, float(r1[t, j])))
        if g["sides"] == "ls":
            for t, j in zip(*np.nonzero(liquid & (r1 <= -g["move"]))):
                if t + 1 < T:
                    out.append(vs.Spec(int(j), int(t + 1), "open", -1, 5, np.nan, float(-r1[t, j])))
        return out, 0.05, 20
    raise KeyError(family)


def daily_pool(D: dict, family: str) -> np.ndarray:
    P, DV = D["P1"], D["DV1"]
    if family == "L8_NEWSDRIFT":
        return (P >= 1) & (DV >= 1e6) & D["valid1"]
    return (P >= 1) & (P <= 20) & (DV >= 1e6) & D["valid1"]


def daily_book(D: dict, sp: list, table: dict, spread: float, weight: float, max_open: int) -> pd.Series:
    """The swing book under v15's R1 costs."""
    look = (spread, lambda px, so: v15.lookup(table, px, so))
    paths = [p for s in sp if (p := vs.path(D, s, "mid", w_max=weight, r1=look)) is not None]
    return core.swing_book(paths, D["dates"], max_open=max_open)


# ---------------------------------------------------------------- weekly

def weekly(D: dict, E: dict, family: str, g: dict, table: dict, spread: float,
           rng: np.random.Generator | None = None) -> pd.Series:
    """Weekly portfolios: chosen at the week's last close, held over the next week; ``rng`` gives the placebo
    (the same number of names drawn at random from the universe)."""
    C, P, dates = D["C"], D["P"], D["dates"]
    r1 = np.vstack([np.full((1, C.shape[1]), np.nan), C[1:] / C[:-1] - 1])
    wk = pd.Series(np.arange(len(dates)), index=dates).groupby(dates.to_period("W")).max().to_numpy()
    out = np.zeros(len(dates))
    for a, b in zip(wk[:-1], wk[1:]):
        uni = (P[a] >= g.get("price", 2.0)) & (D["DV"][a] >= 1e6) & D["valid"][a]
        if family == "L6_MAXREV":
            mx = np.nanmax(r1[max(a - 20, 0):a + 1], axis=0)
            wret = C[a] / C[max(a - 5, 0)] - 1
            ok = uni & np.isfinite(mx) & np.isfinite(wret)
            if ok.sum() < 50:
                continue
            top = ok & (mx >= np.nanpercentile(mx[ok], 90))
            idx = np.flatnonzero(top)
            order = idx[np.argsort(wret[idx])]
            k = max(1, len(order) // 5)
            longs, shorts = order[:k][:20], order[-k:][-20:]
        else:
            sr = E["SR5"][a]
            ok = uni & np.isfinite(sr)
            if ok.sum() < 50:
                continue
            idx = np.flatnonzero(ok)
            order = idx[np.argsort(sr[idx])]
            k = max(1, len(order) // 10)
            longs, shorts = order[:k][:20], order[-k:][-20:]
        if g["sides"] == "long":
            shorts = shorts[:0]
        if rng is not None:
            pool = np.flatnonzero(ok)
            longs = rng.choice(pool, len(longs), replace=False) if len(pool) >= len(longs) else longs
            shorts = rng.choice(pool, len(shorts), replace=False) if len(pool) >= len(shorts) else shorts
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
