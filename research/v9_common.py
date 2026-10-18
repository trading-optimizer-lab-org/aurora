"""v9 common pieces: the trial list, universes, long-short books, costs and
evaluation. Pre-registered in docs/research/V9_PREREGISTRATION.md.
"""
from __future__ import annotations

from itertools import product

import numpy as np
import pandas as pd

from aurora.research import combination as cb
from aurora.research import stock_catalog as sc
from aurora.research import stock_catalog_v7 as v7

F32 = np.float32
PPY = sc.PPY
COSTS = {"stock": (5, 2, 10), "etf": (2, 1, 5), "none": (0,)}  # bps per unit of turnover, main cost first
BORROW = 0.01  # a year on short notional held overnight
MIN_NAMES = 20
MIN_HISTORY = 252
INTRA_START, INTRA_END = pd.Timestamp("2016-01-01"), pd.Timestamp("2020-12-31")
PERIODS = {
    "daily": {"train": (sc.TRAIN_START, sc.TRAIN_END), "validation": (sc.VALIDATION_START, sc.VALIDATION_END),
              "v1": (sc.VALIDATION_START, pd.Timestamp("2015-12-31")),
              "v2": (pd.Timestamp("2016-01-01"), sc.VALIDATION_END)},
    "intraday": {"p1": (INTRA_START, pd.Timestamp("2018-12-31")), "p2": (pd.Timestamp("2019-01-01"), INTRA_END),
                 "all": (INTRA_START, INTRA_END)},
}
SELECT = {"daily": "train", "intraday": "p1"}
JUDGE = {"daily": "validation", "intraday": "p2"}
DSR_PERIOD = {"daily": "validation", "intraday": "all"}
DAILY_FAMILIES = ("REV", "ON", "PAIRS", "INDMOM", "XSMOM", "LOWVOL", "HI52", "MAX")
EVENT_FAMILIES = ("PEAD", "EAPREM")
ETF_FAMILIES = ("TSMOM", "XSETF", "ETFREV", "SEASON")
INTRA_FAMILIES = ("VWAPREV", "GAP", "INTRAREV", "INTRAPER", "MKTINTRA")
BRAKE_BASES = ("INTRADAY_EQ", "ALL13_EQ", "EP_EARN", "EP_NEWS", "BO_TOP3", "DAILY_RP")


def _t(family: str, group: str, kind: str, costs: str, **p) -> dict:
    name = family + "_" + "_".join(f"{k}{v}" for k, v in p.items())
    return {"name": name, "family": family, "group": group, "kind": kind, "costs": costs, **p}


def _grid(out: list[dict], family: str, group: str, kind: str, costs: str, keys: tuple[str, ...], *values) -> None:
    for combo in product(*values):
        out.append(_t(family, group, kind, costs, **dict(zip(keys, combo))))


def trials() -> list[dict]:
    out: list[dict] = []
    d, m = ("daily", "daily", "stock"), ("mixed", "daily", "stock")
    _grid(out, "REV", *d, ("L", "N", "Q", "H", "U", "X"), (1, 2, 3, 5, 10, 21), ("RAW", "IND", "SEC", "MKT"),
          (10, 20, 30), (1, 2, 5), (200, 500, 1000), ("C", "O"))
    _grid(out, "ON", *d, ("L", "LEG", "N", "Q", "U", "W"), (5, 10, 21, 63, 126), ("ON", "ID", "BOTH"), ("RAW", "IND"),
          (10, 20), (200, 500, 1000), ("EQ", "IV"))
    _grid(out, "PAIRS", *d, ("F", "Z", "P", "S", "U"), (126, 252), ("1.0", "1.5", "2.0", "2.5"), (10, 20, 50, 100),
          ("IND", "SEC", "ALL"), (500, 1000))
    for G, ns in (("IND", (1, 3, 5, 10)), ("SEC", (1, 2, 3))):
        _grid(out, "INDMOM", *d, ("G", "M", "S", "K", "H", "U"), (G,), (1, 3, 6, 12), (0, 1), ns, (1, 3), (500, 1000))
    _grid(out, "XSMOM", *d, ("L", "S", "Q", "N", "H", "U"), (21, 63, 126, 252), (0, 21), (10, 20, 30), ("RAW", "IND"),
          (1, 3), (500, 1000))
    _grid(out, "LOWVOL", *d, ("M", "W", "Q", "HG", "U"), ("VOL", "BETA"), (21, 63, 252), (10, 20, 30),
          ("DOLLAR", "BETA"), (500, 1000))
    _grid(out, "HI52", *d, ("W", "Q", "N", "H", "U"), (126, 252), (10, 20, 30), ("RAW", "IND"), (1, 6), (500, 1000))
    _grid(out, "MAX", *d, ("W", "K", "Q", "N", "U"), (21, 63), (1, 5), (10, 20), ("RAW", "IND"), (500, 1000))
    _grid(out, "PEAD", *m, ("T", "D", "G", "U", "M"), (2, 4, 6, 10), (5, 10, 21, 42, 63), (1, 2), (500, 1000, 1500),
          ("LS", "LONG"))
    _grid(out, "EAPREM", *m, ("K", "E", "U"), (1, 3, 5, 10), (0, 1, 3), (500, 1000))
    e = ("mixed", "daily", "etf")
    _grid(out, "TSMOM", *e, ("L", "K", "SET", "R"), (21, 63, 126, 252, "BLEND"), ("SIGN", "SCALED"),
          ("RISK", "SECT", "BROAD"), ("M", "W"))
    _grid(out, "XSETF", *e, ("L", "K", "SET", "M"), (21, 63, 126, 252), (1, 2, 3), ("RISK", "SECT", "BROAD"),
          ("LS", "LONG"))
    _grid(out, "ETFREV", *e, ("L", "K", "SET"), (1, 5), (1, 2, 3), ("SECT", "BROAD"))
    _grid(out, "SEASON", *e, ("E", "I"), ("TOM1-3", "TOM2-3", "TOM1-1", "TOM4-4", "PREHOL"), ("SPY", "QQQ", "IWM", "TLT"))
    _grid(out, "SEASON", *e, ("E", "I"), ("ON", "ID"), ("SPY", "QQQ", "IWM", "TLT", "DIA"))
    i = ("mixed", "intraday", "stock")
    _grid(out, "VWAPREV", *i, ("C", "A", "Q", "P", "N", "U"), (30, 60), ("ADR", "RAW"), (5, 10, 20),
          (15, 30, 60, "CLOSE"), ("RAW", "IND"), (200, 500))
    _grid(out, "GAP", *i, ("B", "D", "E", "X", "U"), ("0.5-1", "1-2", "2-4", "4-8"), ("FADE", "FOLLOW"),
          (945, 1000, 1030), (1100, 1200, 1400, "CLOSE"), (200, 500))
    _grid(out, "INTRAREV", *i, ("T", "W", "N", "Q", "P", "U"), (1030, 1130, 1230, 1330, 1430, 1500), ("OPEN", "L30"),
          ("RAW", "IND"), (10, 20), (30, 60, "CLOSE"), (200, 500))
    _grid(out, "INTRAPER", *i, ("L", "S", "Q", "U"), (5, 10, 20), ("ALL", "FIRST", "LAST"), (10, 20), (200, 500))
    _grid(out, "MKTINTRA", "mixed", "intraday", "etf", ("I", "SIG", "TR", "F"), ("SPY", "QQQ", "IWM", "DIA"),
          ("PC1000", "PC1530", "OP1000"), (1530, 1545), ("ALL", "BIG"))
    for B in BRAKE_BASES:
        _grid(out, "BRAKE", "mixed", "daily" if B == "DAILY_RP" else "intraday", "none", ("B", "M", "X"), (B,),
              ("MONTH", "ROLL"), ("0.5", "1", "2", "3"))
    return out


def shard_trials(group: str, shard: int, n_shards: int) -> list[dict]:
    """Round robin over the group's trials, so every shard gets a mix of families."""
    return [t for t in trials() if t["group"] == group][shard::n_shards]


# ---------------------------------------------------------------- universes and signals

def universe_ranks(C: pd.DataFrame, V: pd.DataFrame) -> pd.DataFrame:
    """Rank by 50-session average dollar volume among stocks priced >= $5 with 252 sessions of history (1 = largest)."""
    dv50 = (C * V).rolling(50, min_periods=50).mean()
    ok = (C.notna().cumsum() >= MIN_HISTORY) & (C >= 5) & dv50.notna()
    return dv50.where(ok).rank(axis=1, ascending=False)


def group_codes(labels: pd.Series) -> np.ndarray:
    codes, _ = pd.factorize(labels.fillna("__none__"))
    codes = codes.astype(np.int32)
    codes[labels.isna().to_numpy()] = -1
    return codes


def demean(S: np.ndarray, members: np.ndarray, codes: np.ndarray) -> np.ndarray:
    """S minus its mean over the member stocks of the same group; NaN outside members or without a group."""
    X = np.where(members, S, np.nan)
    out = np.full_like(X, np.nan)
    for g in np.unique(codes[codes >= 0]):
        idx = np.flatnonzero(codes == g)
        sub = X[:, idx]
        cnt = np.sum(~np.isnan(sub), axis=1)
        mean = np.where(cnt > 0, np.nansum(sub, axis=1) / np.maximum(cnt, 1), np.nan)
        out[:, idx] = sub - mean[:, None]
    return out


def ls_weights(S: np.ndarray, members: np.ndarray, q: float, scale: np.ndarray | None = None,
               min_names: int = MIN_NAMES) -> np.ndarray:
    """Long the top q of S, short the bottom q, among members with a signal; each leg 0.5 of capital, equal
    weight or proportional to ``scale``. Rows with fewer than ``min_names`` signals stay flat."""
    X = np.where(members, S, np.nan)
    n = np.sum(~np.isnan(X), axis=1)
    pct = pd.DataFrame(X).rank(axis=1, pct=True).to_numpy()
    longs, shorts = pct > 1 - q, pct <= q
    base = np.ones_like(X) if scale is None else np.nan_to_num(scale, nan=0.0, posinf=0.0, neginf=0.0)
    wl, ws = np.where(longs, base, 0.0), np.where(shorts, base, 0.0)
    sl, ss = wl.sum(axis=1, keepdims=True), ws.sum(axis=1, keepdims=True)
    W = 0.5 * wl / np.where(sl > 0, sl, 1) - 0.5 * ws / np.where(ss > 0, ss, 1)
    W[(n < min_names) | (sl[:, 0] == 0) | (ss[:, 0] == 0)] = 0.0
    return W


def overlap(W: np.ndarray, h: int) -> np.ndarray:
    """Average of the last h portfolios."""
    if h == 1:
        return W
    return pd.DataFrame(W).rolling(h, min_periods=1).mean().to_numpy()


def monthly(W_rows: np.ndarray, rows: np.ndarray, T: int, h: int = 1) -> np.ndarray:
    """Portfolios formed on ``rows`` (e.g. month ends), averaged over the last h, held until the next formation."""
    Wm = overlap(W_rows, h)
    k = np.searchsorted(rows, np.arange(T), side="right") - 1
    out = np.zeros((T, W_rows.shape[1]))
    ok = k >= 0
    out[ok] = Wm[k[ok]]
    return out


# ---------------------------------------------------------------- books and costs

def book(W: np.ndarray, R: np.ndarray, cash: np.ndarray, lag: int = 1, excess: bool = True,
         turn: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """P&L over T-bills of weights decided at row t that earn R at row t + lag, the turnover and the short notional
    (both charged at row t + lag). NaN returns count as zero."""
    T = len(W)
    Wn = np.nan_to_num(W)
    Rx = np.nan_to_num(R - cash[:, None]) if excess else np.nan_to_num(R)
    pnl, tv, sh = np.zeros(T), np.zeros(T), np.zeros(T)
    pnl[lag:] = np.einsum("ij,ij->i", Wn[:-lag], Rx[lag:])
    if turn is None:
        turn = np.abs(np.diff(Wn, axis=0, prepend=np.zeros((1, Wn.shape[1])))).sum(axis=1)
    tv[lag:] = turn[:-lag]
    sh[lag:] = np.clip(-Wn[:-lag], 0, None).sum(axis=1)
    return pnl, tv, sh


def net_series(pnl: np.ndarray, turn: np.ndarray, short: np.ndarray, cash: np.ndarray, costs: tuple,
               dates: pd.DatetimeIndex, borrow: bool = True) -> dict[int, pd.Series]:
    """Net daily returns at each cost, NaN before the first position (a book that never trades is all NaN)."""
    active = np.flatnonzero((turn > 0) | (pnl != 0))
    out = {}
    for bps in costs:
        r = cash + pnl - bps / 1e4 * turn - (BORROW / PPY * short if borrow else 0.0)
        s = pd.Series(r, index=dates)
        out[bps] = s.iloc[active[0]:] if active.size else s.iloc[0:0]
    return out


# ---------------------------------------------------------------- evaluation

def evaluate(r: pd.Series, cash: pd.Series, periods: dict) -> dict:
    row: dict = {}
    for p, (a, b) in periods.items():
        x = r.loc[a:b].dropna()
        if len(x) < 60:
            continue
        m = sc.metrics(x, cash)
        row.update({f"{p}_{k}": m.get(k, np.nan) for k in v7.PORT_KEYS})
        row[f"{p}_total"] = float((1 + x).prod() - 1)
        row[f"{p}_worst_day"] = float(x.min())
        row.update({f"{p}_{k}": v for k, v in cb.monthly_stats(x).items()})
    return row


def trial_row(t: dict, series: dict[int, pd.Series], cash: pd.Series) -> dict:
    """Full metrics at the main cost, Sortino and CAGR per period at the sensitivity costs."""
    periods = PERIODS[t["kind"]]
    costs = COSTS[t["costs"]]
    row = {"name": t["name"], "family": t["family"], "kind": t["kind"], **evaluate(series[costs[0]], cash, periods)}
    for bps in costs[1:]:
        for p, (a, b) in periods.items():
            x = series[bps].loc[a:b].dropna()
            if len(x) >= 60:
                m = sc.metrics(x, cash)
                row[f"s{bps}_{p}_sortino_monthly"] = m.get("sortino_monthly", np.nan)
                row[f"s{bps}_{p}_cagr"] = m.get("cagr", np.nan)
    return row
