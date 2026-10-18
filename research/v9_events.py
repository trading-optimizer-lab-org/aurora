"""v9 families 9-10: earnings drift (PEAD) and the earnings announcement premium
on SEC 8-K Item 2.02 filing dates, 2004-2020. Pre-registered in
docs/research/V9_PREREGISTRATION.md.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from aurora.research import v9_common as c

PREDICT_DAYS = 364


def events(x: dict, earnings: dict[str, list[str]]) -> dict[str, np.ndarray]:
    """(column, session row) of every filing date of a panel stock; a date that is not a session maps to the next."""
    pos = {s: i for i, s in enumerate(x["cols"])}
    cols, rows = [], []
    for sym, days in earnings.items():
        if sym in pos and days:
            r = x["dates"].searchsorted(pd.to_datetime(sorted(set(days))))
            r = r[r < len(x["dates"])]
            cols.append(np.full(len(r), pos[sym]))
            rows.append(r)
    if not cols:
        return {"col": np.zeros(0, dtype=int), "row": np.zeros(0, dtype=int)}
    return {"col": np.concatenate(cols).astype(int), "row": np.concatenate(rows).astype(int)}


def _active(T: int, n: int, start: np.ndarray, length: np.ndarray, col: np.ndarray) -> np.ndarray:
    """Boolean (T, n): True on rows start .. start + length - 1 of each event's column."""
    A = np.zeros((T + 1, n), dtype=np.int32)
    ok = (start >= 0) & (start < T) & (length > 0)
    s, e, k = start[ok], np.minimum(start[ok] + length[ok], T), col[ok]
    np.add.at(A, (s, k), 1)
    np.add.at(A, (e, k), -1)
    return np.cumsum(A, axis=0)[:T] > 0


def _book_with_spy(x: dict, W: np.ndarray, spy_w: np.ndarray) -> dict:
    R = np.hstack([x["r_cc"], x["spy_r"][:, None]])
    Wf = np.hstack([W, spy_w[:, None]])
    return c.net_series(*c.book(Wf, R, x["cash"], lag=1), x["cash"], c.COSTS["stock"], x["dates"])


def pead(t: dict, x: dict, ev: dict) -> dict:
    C, spy, rank = x["C"], x["spy"], x["rank"]
    T, n = C.shape
    col, d = ev["col"], ev["row"]
    ok = (d >= 1) & (d + 1 < T)
    col, d = col[ok], d[ok]
    react = C[d + 1, col] / C[d - 1, col] - 1 - (spy[d + 1] / spy[d - 1] - 1)
    in_u = rank[d - 1, col] <= t["U"]
    thr = t["T"] / 100
    start, length = d + t["G"], np.full(len(d), t["D"])
    up, down = in_u & (react > thr), in_u & (react < -thr)
    L = _active(T, n, start[up], length[up], col[up])
    S = _active(T, n, start[down], length[down], col[down])
    both = L & S
    L, S = L & ~both, S & ~both
    nl, ns = L.sum(axis=1), S.sum(axis=1)
    W = 0.5 * L / np.maximum(nl, 1)[:, None]
    if t["M"] == "LS":
        W = W - 0.5 * S / np.maximum(ns, 1)[:, None]
        spy_w = np.where((nl == 0) & (ns > 0), 0.5, 0.0) - np.where((ns == 0) & (nl > 0), 0.5, 0.0)
    else:
        spy_w = np.where(nl > 0, -0.5, 0.0)
    return _book_with_spy(x, W, spy_w)


def eaprem(t: dict, x: dict, ev: dict) -> dict:
    T, n = x["C"].shape
    col, d = ev["col"], ev["row"]
    p = x["dates"].searchsorted(x["dates"][d] + pd.Timedelta(days=PREDICT_DAYS))
    start = p - t["K"]
    ok = (p < T) & (start >= 0)
    col, start, p = col[ok], start[ok], p[ok]
    in_u = x["rank"][start, col] <= t["U"]
    L = _active(T, n, start[in_u], np.full(int(in_u.sum()), t["K"] + t["E"]), col[in_u])
    nl = L.sum(axis=1)
    W = 0.5 * L / np.maximum(nl, 1)[:, None]
    return _book_with_spy(x, W, np.where(nl > 0, -0.5, 0.0))


RUNNERS = {"PEAD": pead, "EAPREM": eaprem}
