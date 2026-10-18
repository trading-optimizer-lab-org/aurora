"""v9 families 1-8: daily market-neutral stock books on the survivors panel,
1995-2020. Pre-registered in docs/research/V9_PREREGISTRATION.md.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from aurora.research import stock_catalog as sc
from aurora.research import stock_catalog_v5 as v5
from aurora.research import v9_common as c

KEEP_RANK = 1500  # columns ever in the top 1500 by dollar volume are kept
WINDOWS = (21, 63, 252)


def lagged(A: np.ndarray, k: int) -> np.ndarray:
    """A shifted down k rows (the value k rows earlier), NaN on top."""
    out = np.full_like(A, np.nan)
    if k < len(A):
        out[k:] = A[:-k]
    return out


def context(panel: dict, spy_close: pd.Series, symbols: pd.DataFrame, cash_index: pd.Series) -> dict:
    """Shared arrays for every daily family (built once, before the worker processes fork)."""
    ranks = c.universe_ranks(panel["close"], panel["volume"])
    keep = ranks.columns[(ranks <= KEEP_RANK).any()]
    dates = panel["close"].index
    C = panel["close"][keep].to_numpy(float)
    O = panel["open"][keep].to_numpy(float)
    H = panel["high"][keep].to_numpy(float)
    L = panel["low"][keep].to_numpy(float)
    C1, O1 = lagged(C, 1), lagged(O, 1)
    cash = cash_index.reindex(dates).ffill().pct_change(fill_method=None).fillna(0.0)
    spy = spy_close.reindex(dates).ffill()
    spy_r = spy.pct_change(fill_method=None).fillna(0.0)
    r_cc = C / C1 - 1
    rdf = pd.DataFrame(r_cc, index=dates)
    x = {"dates": dates, "cols": keep, "C": C, "O": O, "H": H, "L": L, "r_cc": r_cc, "r_on": O / C1 - 1,
         "r_id": C / O - 1, "r_oo": O / O1 - 1, "rank": ranks[keep].to_numpy(np.float32), "cash": cash.to_numpy(),
         "cash_s": cash, "spy": spy.to_numpy(), "spy_r": spy_r.to_numpy(),
         "ind": c.group_codes(symbols["industry"].reindex(keep)), "sec": c.group_codes(symbols["sector"].reindex(keep)),
         "month_rows": np.flatnonzero(v5.month_ends(dates)), "week_rows": np.flatnonzero(sc.week_ends(dates))}
    Y = rdf * 0 + spy_r.to_numpy()[:, None]  # SPY's return on the days the stock has one
    for w in WINDOWS:
        k = int(0.8 * w)
        mx, my = rdf.rolling(w, min_periods=k).mean(), Y.rolling(w, min_periods=k).mean()
        cov = (rdf * Y).rolling(w, min_periods=k).mean() - mx * my
        var = (Y * Y).rolling(w, min_periods=k).mean() - my * my
        x[f"vol{w}"] = (rdf.rolling(w, min_periods=k).std() * np.sqrt(c.PPY)).to_numpy(np.float32)
        x[f"beta{w}"] = (cov / var.where(var > 0)).to_numpy(np.float32)
    return x


def members(x: dict, U: int) -> np.ndarray:
    return x["rank"] <= U


def _neutral(S: np.ndarray, m: np.ndarray, x: dict, N: str) -> np.ndarray:
    if N in ("IND", "SEC"):
        return c.demean(S, m, x["ind" if N == "IND" else "sec"])
    return S


def _out(x: dict, pnl, tv, sh, costs: str = "stock") -> dict:
    return c.net_series(pnl, tv, sh, x["cash"], c.COSTS[costs], x["dates"])


def rev(t: dict, x: dict) -> dict:
    C, L = x["C"], t["L"]
    ret = C / lagged(C, L) - 1
    if t["N"] == "MKT":
        spy_l = x["spy"] / lagged(x["spy"][:, None], L)[:, 0] - 1
        ret = ret - x["beta252"] * spy_l[:, None]
    m = members(x, t["U"])
    W = c.overlap(c.ls_weights(_neutral(-ret, m, x, t["N"]), m, t["Q"] / 100), t["H"])
    if t["X"] == "C":
        return _out(x, *c.book(W, x["r_cc"], x["cash"], lag=1))
    return _out(x, *c.book(W, x["r_oo"], x["cash"], lag=2))


def overnight(t: dict, x: dict) -> dict:
    m = members(x, t["U"])
    S = pd.DataFrame(x["r_on"]).rolling(t["L"], min_periods=t["L"]).mean().to_numpy()
    with np.errstate(divide="ignore"):
        scale = 1 / x["vol63"].astype(float) if t["W"] == "IV" else None
    W = c.ls_weights(_neutral(S, m, x, t["N"]), m, t["Q"] / 100, scale)
    gross = np.abs(W).sum(axis=1)
    p_on, tv, sh = c.book(W, x["r_on"], x["cash"], lag=1, excess=False, turn=2 * gross)
    p_id, _, _ = c.book(-W, x["r_id"], x["cash"], lag=1, excess=False, turn=2 * gross)
    leg = t["LEG"]
    if leg == "ON":
        return _out(x, p_on, tv, sh)
    if leg == "ID":
        return _out(x, p_id, tv, np.zeros_like(sh))
    return _out(x, 0.5 * (p_on + p_id), tv, 0.5 * sh)


def _formation_rows(dates: pd.DatetimeIndex) -> np.ndarray:
    s = pd.Series(np.arange(len(dates)), index=dates)
    first = s.groupby(dates.to_period("M")).min()
    return np.array([r for p, r in first.items() if p.month in (1, 7)], dtype=int)


def pairs(t: dict, x: dict) -> dict:
    F, z, n, scope = t["F"], float(t["Z"]), t["P"], t["S"]
    C, T = x["C"], len(x["dates"])
    m_all = members(x, t["U"])
    W = np.zeros_like(C)
    rows = _formation_rows(x["dates"])
    for k, f in enumerate(rows):
        if f - F < 0:
            continue
        end = min(f + 125, (rows[k + 1] - 1) if k + 1 < len(rows) else T - 1)
        form = C[f - F:f]
        cand = np.flatnonzero(m_all[f - 1] & ~np.isnan(form).any(axis=0))
        if len(cand) < 2:
            continue
        P = form[:, cand] / form[0, cand]
        sq = (P ** 2).sum(axis=0)
        ssd = sq[:, None] + sq[None, :] - 2 * P.T @ P
        bad = np.tril(np.ones_like(ssd, dtype=bool))
        if scope != "ALL":
            codes = x["ind" if scope == "IND" else "sec"][cand]
            bad |= (codes[:, None] != codes[None, :]) | (codes[:, None] < 0)
        ssd[bad] = np.inf
        flat = np.flatnonzero(np.isfinite(ssd))
        if flat.size == 0:
            continue
        best = flat[np.argsort(ssd.ravel()[flat], kind="stable")[:n]]
        i, j = np.unravel_index(best, ssd.shape)
        sig = (P[:, i] - P[:, j]).std(axis=0, ddof=1)
        ci, cj = cand[i], cand[j]
        trade = pd.DataFrame(C[f - 1:end + 1][:, np.concatenate([ci, cj])]).ffill().to_numpy()
        npair = len(ci)
        spread = trade[:, :npair] / trade[0, :npair] - trade[:, npair:] / trade[0, npair:]
        pos = np.zeros(npair)
        w = 1 / (2 * n)
        for d in range(1, len(spread)):
            s_t = spread[d]
            pos[((pos == 1) & (s_t >= 0)) | ((pos == -1) & (s_t <= 0))] = 0
            pos[(pos == 0) & (s_t > z * sig)] = -1
            pos[(pos == 0) & (s_t < -z * sig)] = 1
            row = f - 1 + d
            if row == end:
                pos[:] = 0
            pos[np.isnan(s_t)] = 0
            np.add.at(W[row], ci, pos * w)
            np.add.at(W[row], cj, -pos * w)
    return _out(x, *c.book(W, x["r_cc"], x["cash"], lag=1))


def indmom(t: dict, x: dict) -> dict:
    C, rows, T = x["C"], x["month_rows"], len(x["dates"])
    codes = x["ind" if t["G"] == "IND" else "sec"]
    look, skip, n = 21 * t["M"], 21 * t["S"], t["K"]
    m_all = members(x, t["U"])
    Wr = np.zeros((len(rows), C.shape[1]))
    groups = np.unique(codes[codes >= 0])
    for k, r in enumerate(rows):
        if r - look - skip < 0:
            continue
        ret = C[r - skip] / C[r - skip - look] - 1
        mem = m_all[r] & ~np.isnan(ret)
        stats = []
        for g in groups:
            idx = np.flatnonzero(mem & (codes == g))
            if len(idx) >= 5:
                stats.append((float(ret[idx].mean()), int(g)))
        if len(stats) < 2 * n:
            continue
        stats.sort()
        lo, hi = [g for _, g in stats[:n]], [g for _, g in stats[-n:]]
        lm, sm = mem & np.isin(codes, hi), mem & np.isin(codes, lo)
        Wr[k, lm] = 0.5 / lm.sum()
        Wr[k, sm] = -0.5 / sm.sum()
    W = c.monthly(Wr, rows, T, t["H"])
    return _out(x, *c.book(W, x["r_cc"], x["cash"], lag=1))


def _monthly_ls(x: dict, S_rows: np.ndarray, t: dict, N: str, H: int, scale: np.ndarray | None = None) -> np.ndarray:
    rows = x["month_rows"]
    m = members(x, t["U"])[rows]
    Wr = c.ls_weights(_neutral(S_rows, m, x, N), m, t["Q"] / 100, scale)
    return c.monthly(Wr, rows, len(x["dates"]), H)


def xsmom(t: dict, x: dict) -> dict:
    C, rows = x["C"], x["month_rows"]
    S = (lagged(C, t["S"]) / lagged(C, t["S"] + t["L"]) - 1)[rows] if t["S"] else (C / lagged(C, t["L"]) - 1)[rows]
    W = _monthly_ls(x, S, t, t["N"], t["H"])
    return _out(x, *c.book(W, x["r_cc"], x["cash"], lag=1))


def lowvol(t: dict, x: dict) -> dict:
    rows = x["month_rows"]
    meas = x[f"{'vol' if t['M'] == 'VOL' else 'beta'}{t['W']}"].astype(float)
    m = members(x, t["U"])[rows]
    Wr = c.ls_weights(-meas[rows], m, t["Q"] / 100)
    if t["HG"] == "BETA":
        beta = np.nan_to_num(x[f"beta{t['W']}"].astype(float)[rows], nan=1.0)
        lw, sw = np.clip(Wr, 0, None), np.clip(-Wr, 0, None)
        bl = np.clip((lw * beta).sum(axis=1) / 0.5, 0.1, None)
        bs = np.clip((sw * beta).sum(axis=1) / 0.5, 0.1, None)
        kl, ks = 1 / bl, 1 / bs
        Wr = (lw * (2 * kl / (kl + ks))[:, None] - sw * (2 * ks / (kl + ks))[:, None])
    W = c.monthly(Wr, rows, len(x["dates"]), 1)
    return _out(x, *c.book(W, x["r_cc"], x["cash"], lag=1))


def hi52(t: dict, x: dict) -> dict:
    hi = pd.DataFrame(x["H"]).rolling(t["W"], min_periods=t["W"]).max().to_numpy()
    S = (x["C"] / hi)[x["month_rows"]]
    W = _monthly_ls(x, S, t, t["N"], t["H"])
    return _out(x, *c.book(W, x["r_cc"], x["cash"], lag=1))


def maxret(t: dict, x: dict) -> dict:
    rows, r, Wn, K = x["month_rows"], x["r_cc"], t["W"], t["K"]
    S = np.full((len(rows), r.shape[1]), np.nan)
    for k, row in enumerate(rows):
        if row - Wn + 1 < 1:
            continue
        win = r[row - Wn + 1:row + 1]
        valid = (~np.isnan(win)).sum(axis=0)
        top = -np.sort(-np.where(np.isnan(win), -np.inf, win), axis=0)[:K]
        S[k] = np.where(valid >= 0.8 * Wn, -top.mean(axis=0), np.nan)
    W = _monthly_ls(x, S, t, t["N"], 1)
    return _out(x, *c.book(W, x["r_cc"], x["cash"], lag=1))


RUNNERS = {"REV": rev, "ON": overnight, "PAIRS": pairs, "INDMOM": indmom, "XSMOM": xsmom, "LOWVOL": lowvol,
           "HI52": hi52, "MAX": maxret}
