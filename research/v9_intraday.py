"""v9 families 15-19: intraday books on Alpaca 15-minute bars (regular hours,
2016-2020). Pre-registered in docs/research/V9_PREREGISTRATION.md.

Bar b covers 9:30 + 15b to 9:45 + 15b minutes (b = 0..25). A signal at the close
of bar s is traded at the open of bar s + 1; exits at the close of a bar.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from aurora.research import v9_common as c

SLOTS = 26
UNIVERSE = 500
ETFS = ["SPY", "QQQ", "IWM", "DIA"]


def bar_ending(hhmm: int) -> int:
    """Index of the bar that ends at hh:mm."""
    minutes = (hhmm // 100) * 60 + hhmm % 100 - (9 * 60 + 30)
    return minutes // 15 - 1


def bar_starting(hhmm: int) -> int:
    return bar_ending(hhmm) + 1


def context(bars: dict, x: dict) -> dict:
    """``bars``: days, symbols and (day, bar, symbol) arrays o, c, v, vw from the cache; ``x``: the daily context."""
    days = pd.DatetimeIndex(bars["days"])
    syms = [str(s) for s in bars["symbols"]]
    prow = x["dates"].get_indexer(days)
    if (prow < 1).any():
        raise ValueError("intraday days missing from the panel calendar")
    pcol = x["cols"].get_indexer(syms)
    o = bars["o"].astype(np.float32)
    cl = pd.DataFrame(bars["c"].transpose(1, 0, 2).reshape(SLOTS, -1)).ffill().to_numpy()
    cl = cl.reshape(SLOTS, len(days), len(syms)).transpose(1, 0, 2).astype(np.float32)
    v = np.nan_to_num(bars["v"].astype(float))
    pv = np.cumsum(np.nan_to_num(bars["vw"].astype(float)) * v, axis=1)
    cv = np.cumsum(v, axis=1)
    vwap = np.where(cv > 0, pv / np.where(cv > 0, cv, 1), np.nan).astype(np.float32)
    stock = pcol >= 0

    def from_panel(A: np.ndarray, rows: np.ndarray) -> np.ndarray:
        out = np.full((len(days), len(syms)), np.nan)
        out[:, stock] = A[rows][:, pcol[stock]]
        return out

    H, L = x["H"], x["L"]
    adr = pd.DataFrame(H / L - 1).rolling(20, min_periods=20).mean().to_numpy()
    codes = np.full(len(syms), -1, dtype=np.int32)
    codes[stock] = x["ind"][pcol[stock]]
    return {"days": days, "syms": syms, "o": o, "c": cl, "vwap": vwap, "cash": x["cash"][prow],
            "rank": from_panel(x["rank"].astype(float), prow - 1), "adr": from_panel(adr, prow - 1),
            "gap": from_panel(x["O"], prow) / from_panel(x["C"], prow - 1) - 1, "ind": codes,
            "etf": {s: syms.index(s) for s in ETFS if s in syms}}


def _members(e: dict, U: int, b_in: int, b_out: int) -> np.ndarray:
    return (e["rank"] <= U) & ~np.isnan(e["o"][:, b_in]) & ~np.isnan(e["c"][:, b_out])


def _leg_return(e: dict, W: np.ndarray, b_in: int, b_out: int) -> tuple[np.ndarray, np.ndarray]:
    ret = e["c"][:, b_out].astype(float) / e["o"][:, b_in].astype(float) - 1
    return np.einsum("ij,ij->i", np.nan_to_num(W), np.nan_to_num(ret)), 2 * np.abs(np.nan_to_num(W)).sum(axis=1)


def _out(e: dict, pnl: np.ndarray, turn: np.ndarray, costs: str = "stock") -> dict:
    return c.net_series(pnl, turn, np.zeros_like(pnl), e["cash"], c.COSTS[costs], e["days"], borrow=False)


def _neutral(S: np.ndarray, m: np.ndarray, e: dict, N: str) -> np.ndarray:
    return c.demean(S, m, e["ind"]) if N == "IND" else S


def _exit(b_in: int, hold) -> int:
    return SLOTS - 1 if hold == "CLOSE" else min(SLOTS - 1, b_in + int(hold) // 15 - 1)


def vwaprev(t: dict, e: dict) -> dict:
    checks = [s for s in range(1, SLOTS - 2) if ((s + 1) * 15 - 30) % t["C"] == 0]  # 10:00, then every C minutes
    share = 1.0 if t["P"] != "CLOSE" and int(t["P"]) <= t["C"] else 1.0 / len(checks)
    pnl, turn = np.zeros(len(e["days"])), np.zeros(len(e["days"]))
    for s in checks:
        b_in = s + 1
        b_out = _exit(b_in, t["P"])
        m = _members(e, t["U"], b_in, b_out) & ~np.isnan(e["vwap"][:, s])
        dev = e["c"][:, s] / e["vwap"][:, s] - 1
        if t["A"] == "ADR":
            dev = dev / e["adr"]
        W = c.ls_weights(_neutral(-dev, m, e, t["N"]), m, t["Q"] / 100) * share
        p, tv = _leg_return(e, W, b_in, b_out)
        pnl, turn = pnl + p, turn + tv
    return _out(e, pnl, turn)


def gap(t: dict, e: dict) -> dict:
    lo, hi = (float(v) / 100 for v in t["B"].split("-"))
    b_in = bar_starting(t["E"])
    b_out = SLOTS - 1 if t["X"] == "CLOSE" else bar_ending(t["X"])
    m = _members(e, t["U"], b_in, b_out)
    g = e["gap"]
    down, up = m & (g <= -lo) & (g >= -hi), m & (g >= lo) & (g <= hi)
    longs, shorts = (down, up) if t["D"] == "FADE" else (up, down)
    nl, ns = longs.sum(axis=1), shorts.sum(axis=1)
    W = 0.5 * longs / np.maximum(nl, 1)[:, None] - 0.5 * shorts / np.maximum(ns, 1)[:, None]
    j = e["etf"]["SPY"]
    W[:, j] += np.where((nl == 0) & (ns > 0), 0.5, 0.0) - np.where((ns == 0) & (nl > 0), 0.5, 0.0)
    return _out(e, *_leg_return(e, W, b_in, b_out))


def intrarev(t: dict, e: dict) -> dict:
    s = bar_ending(t["T"])
    b_in = s + 1
    b_out = _exit(b_in, t["P"])
    m = _members(e, t["U"], b_in, b_out)
    base = e["o"][:, 0] if t["W"] == "OPEN" else e["c"][:, s - 2]
    ret = e["c"][:, s] / base - 1
    W = c.ls_weights(_neutral(-ret, m, e, t["N"]), m, t["Q"] / 100)
    return _out(e, *_leg_return(e, W, b_in, b_out))


def intraper(t: dict, e: dict) -> dict:
    half = range(SLOTS // 2)
    slots = {"ALL": list(half), "FIRST": [0], "LAST": [SLOTS // 2 - 1]}[t["S"]]
    pnl, turn = np.zeros(len(e["days"])), np.zeros(len(e["days"]))
    for j in slots:
        b_in, b_out = 2 * j, 2 * j + 1
        start = e["o"][:, 0] if j == 0 else e["c"][:, 2 * j - 1]
        past = pd.DataFrame(e["c"][:, b_out] / start - 1).rolling(t["L"], min_periods=t["L"]).mean().shift(1)
        m = _members(e, t["U"], b_in, b_out)
        W = c.ls_weights(past.to_numpy(), m, t["Q"] / 100)
        p, tv = _leg_return(e, W, b_in, b_out)
        pnl, turn = pnl + p, turn + tv
    return _out(e, pnl, turn)


def mktintra(t: dict, e: dict) -> dict:
    j = e["etf"][t["I"]]
    o, cl = e["o"][:, :, j].astype(float), e["c"][:, :, j].astype(float)
    prev = np.append(np.nan, cl[:-1, SLOTS - 1])
    sig = {"PC1000": cl[:, 1] / prev - 1, "PC1530": cl[:, 23] / prev - 1, "OP1000": cl[:, 1] / o[:, 0] - 1}[t["SIG"]]
    b_in = bar_starting(t["TR"])
    pos = np.sign(np.nan_to_num(sig))
    if t["F"] == "BIG":
        med = pd.Series(np.abs(sig)).rolling(60, min_periods=60).median().shift(1).to_numpy()
        pos = np.where(np.abs(sig) > med, pos, 0.0)
    ret = cl[:, SLOTS - 1] / o[:, b_in] - 1
    pos = np.where(np.isnan(ret), 0.0, pos)
    return _out(e, pos * np.nan_to_num(ret), 2 * np.abs(pos), costs="etf")


RUNNERS = {"VWAPREV": vwaprev, "GAP": gap, "INTRAREV": intrarev, "INTRAPER": intraper, "MKTINTRA": mktintra}
