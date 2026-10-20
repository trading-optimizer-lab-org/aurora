"""v14 shared pieces: periods, the seal, costs, portfolio aggregation and the selection statistics.

Pre-registered in docs/research/V14_PREREGISTRATION.md.
"""
from __future__ import annotations

import os
from itertools import combinations, product

import numpy as np
import pandas as pd

DESIGN_START, DESIGN_END = pd.Timestamp("2016-01-04"), pd.Timestamp("2023-06-30")
SEALED_START, SEALED_END = pd.Timestamp("2023-07-01"), pd.Timestamp("2026-10-16")
CRYPTO_START, CRYPTO_END = pd.Timestamp("2018-01-01"), pd.Timestamp("2026-09-30")
WF_YEARS = tuple(range(2018, 2024))
SORTINO_CAP = 20.0
N_BLOCKS = 10
ACCOUNT = 100_000.0
COMMISSION = 0.005  # dollars a share
SCENARIOS = ("low", "mid", "high")
UNLOCK_ENV = "V14_UNLOCK_SEALED"


def last_day() -> pd.Timestamp:
    """The last day any computation may use: the design end, unless the sealed test was explicitly unlocked."""
    return SEALED_END if os.environ.get(UNLOCK_ENV) == "yes-the-owner-asked" else DESIGN_END


def seal(x, end: pd.Timestamp | None = None):
    """Truncate a date-indexed object at the allowed last day."""
    return x.loc[:(end or last_day())]


# ---------------------------------------------------------------- costs

def half_spread(price: np.ndarray, scenario: str) -> np.ndarray:
    p = np.asarray(price, dtype=float)
    hs = np.select([p < 2, p < 5, p < 10, p < 20], [0.0075, 0.004, 0.002, 0.001], 0.0005)
    return hs * {"low": 0.5, "mid": 1.0, "high": 2.0}[scenario]


def stock_cost(price: np.ndarray, scenario: str) -> np.ndarray:
    """Round-trip cost as a fraction of notional: two half-spreads and two commissions."""
    p = np.maximum(np.asarray(price, dtype=float), 0.01)
    return 2 * (half_spread(p, scenario) + COMMISSION / p)


def short_cost(price: np.ndarray, nights: np.ndarray, scenario: str) -> np.ndarray:
    """Locate fee plus overnight borrow for a short, as a fraction of notional."""
    p = np.asarray(price, dtype=float)
    n = np.asarray(nights, dtype=float)
    if scenario == "low":
        return 0.20 / 252 * n
    if scenario == "mid":
        return np.where(p < 10, 0.005, 0.0) + 0.50 / 252 * n
    return np.where(p < 10, 0.015, 0.005) + 1.50 / 252 * n


def shortable_high(price: np.ndarray, shares_out: np.ndarray) -> np.ndarray:
    """The high scenario refuses shorts below $2 or with fewer than 10 million (or unknown) shares outstanding."""
    so = np.asarray(shares_out, dtype=float)
    return (np.asarray(price, dtype=float) >= 2) & np.isfinite(so) & (so >= 10e6)


# ---------------------------------------------------------------- portfolios

def intraday_book(trades: pd.DataFrame, dates: pd.DatetimeIndex, scenario: str, max_pos: int = 5,
                  risk: float = 0.005, cap: float = 0.20) -> tuple[pd.Series, pd.DataFrame]:
    """Same-day trades -> daily returns. ``trades`` columns: date, minute, side (+1/-1), entry, exit, stop, price
    (raw), liq (dollar volume before entry), prio (higher first after the earliest minute), nights, so."""
    if trades.empty:
        return pd.Series(0.0, index=dates), trades
    t = trades.copy()
    if scenario == "high":
        t = t[(t["side"] > 0) | shortable_high(t["price"], t["so"])]
    t = t.sort_values(["date", "minute", "prio"], ascending=[True, True, False])
    t = t.groupby("date", sort=False).head(max_pos).copy()
    dist = (t["entry"] - t["stop"]).abs() / t["entry"]
    w = np.minimum(cap, risk / dist.clip(lower=1e-4))
    w = np.minimum(w, 0.02 * t["liq"].fillna(0.0) / ACCOUNT)
    t["w"] = w
    t["w"] = t["w"] / np.maximum(1.0, t.groupby("date")["w"].transform("sum"))
    gross = t["side"] * (t["exit"] / t["entry"] - 1)
    cost = stock_cost(t["price"], scenario) + np.where(t["side"] < 0, short_cost(t["price"], t["nights"], scenario), 0)
    t["net"] = gross - cost
    daily = (t["w"] * t["net"]).groupby(t["date"]).sum()
    return daily.reindex(dates).fillna(0.0), t


def swing_book(paths: list[tuple], dates: pd.DatetimeIndex, max_open: int = 20) -> pd.Series:
    """Multi-day trades -> daily returns. Each path: (first row with a return, daily net returns from there,
    priority, weight). At most ``max_open`` positions at a time, gross at most 100%; the rest are skipped."""
    out = np.zeros(len(dates))
    gross = np.zeros(len(dates))
    open_until: list[int] = []
    for i0, r, prio, w in sorted(paths, key=lambda p: (p[0], -p[2])):
        open_until = [e for e in open_until if e >= i0]
        n = min(len(r), len(dates) - i0)
        if n <= 0 or w <= 0 or len(open_until) >= max_open or gross[i0:i0 + n].max() + w > 1.0 + 1e-9:
            continue
        out[i0:i0 + n] += w * r[:n]
        gross[i0:i0 + n] += w
        open_until.append(i0 + n - 1)
    return pd.Series(out, index=dates)


# ---------------------------------------------------------------- statistics

def monthly(r: pd.DataFrame) -> pd.DataFrame:
    return (1 + r.fillna(0.0)).groupby(r.index.to_period("M")).prod() - 1


def sortino_cols(M: np.ndarray, cash_m: np.ndarray) -> np.ndarray:
    ex = M - cash_m[:, None]
    n = ex.shape[0]
    if n < 6:
        return np.full(M.shape[1], np.nan)
    dn = np.sqrt(np.sum(np.minimum(ex, 0.0) ** 2, axis=0) / (n - 1))
    mean = ex.mean(axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        s = np.where(dn > 0, mean / dn * np.sqrt(12), np.where(mean > 0, SORTINO_CAP, 0.0))
    return np.minimum(s, SORTINO_CAP)


def sortino(r: pd.Series, cash: pd.Series) -> float:
    M = monthly(r.to_frame())
    cm = monthly(cash.reindex(r.index).fillna(0.0).to_frame())
    return float(sortino_cols(M.to_numpy(), cm.to_numpy()[:, 0])[0])


def score(M: np.ndarray, cash_m: np.ndarray) -> np.ndarray:
    h = M.shape[0] // 2
    return np.minimum(sortino_cols(M[:h], cash_m[:h]), sortino_cols(M[h:], cash_m[h:]))


def neighbours(cfgs: list[dict]) -> list[list[int]]:
    keys = [tuple(sorted(g.items())) for g in cfgs]
    out = []
    for k in keys:
        out.append([j for j, o in enumerate(keys)
                    if len(o) == len(k) and sum(a != b for a, b in zip(k, o)) <= 1])
    return out


def plateau(s: np.ndarray, nb: list[list[int]]) -> np.ndarray:
    return np.array([np.nanmean(s[ix]) if np.isfinite(s[ix]).any() else np.nan for ix in nb])


def walk_forward(R: pd.DataFrame, cash: pd.Series, nb: list[list[int]], start: pd.Timestamp = DESIGN_START,
                 end: pd.Timestamp | None = None) -> tuple[pd.Series, dict]:
    """Yearly choice of the best plateau score on data before each year; the stitched record and the choices."""
    end = end or last_day()
    Mo = monthly(R.loc[start:end])
    cm = monthly(cash.reindex(R.loc[start:end].index).fillna(0.0).to_frame("c"))["c"]
    pieces, picks = [], {}
    for y in range(WF_YEARS[0], end.year + 1):
        train = Mo.index[Mo.index < pd.Period(f"{y}-01", "M")]
        if len(train) < 12:
            continue
        s = plateau(score(Mo.loc[train].to_numpy(), cm.loc[train].to_numpy()), nb)
        if not np.isfinite(s).any():
            continue
        i = int(np.nanargmax(s))
        picks[y] = (R.columns[i], float(s[i]))
        pieces.append(R[R.columns[i]].loc[f"{y}-01-01":min(end, pd.Timestamp(f"{y}-12-31"))])
    return (pd.concat(pieces) if pieces else pd.Series(dtype=float)), picks


def cpcv(R: pd.DataFrame, cash: pd.Series, nb: list[list[int]], start: pd.Timestamp = DESIGN_START,
         end: pd.Timestamp | None = None) -> dict:
    end = end or last_day()
    Mo = monthly(R.loc[start:end])
    cm = monthly(cash.reindex(R.loc[start:end].index).fillna(0.0).to_frame("c"))["c"].to_numpy()
    M = Mo.to_numpy()
    blocks = np.array_split(np.arange(len(M)), N_BLOCKS)
    test_s, ranks = [], []
    for tr in combinations(range(N_BLOCKS), N_BLOCKS // 2):
        tr_rows = np.concatenate([blocks[b] for b in tr])
        te_rows = np.concatenate([blocks[b] for b in range(N_BLOCKS) if b not in tr])
        s = plateau(score(M[tr_rows], cm[tr_rows]), nb)
        if not np.isfinite(s).any():
            continue
        i = int(np.nanargmax(s))
        te = sortino_cols(M[te_rows], cm[te_rows])
        valid = te[np.isfinite(te)]
        if not len(valid):
            continue
        test_s.append(float(te[i]))
        ranks.append(float((valid < te[i]).sum() + 0.5 * (valid == te[i]).sum()) / len(valid))
    ra, ta = np.array(ranks), np.array(test_s)
    if not len(ra):
        return {"splits": 0, "pbo": np.nan}
    return {"splits": len(ra), "pbo": float((ra < 0.5).mean()), "test_median": float(np.nanmedian(ta)),
            "test_p10": float(np.nanpercentile(ta, 10)), "test_p90": float(np.nanpercentile(ta, 90))}


def grid(dims: dict) -> list[dict]:
    return [dict(zip(dims, v)) for v in product(*dims.values())]
