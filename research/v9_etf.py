"""v9 families 11-14: ETF time-series and cross-sectional momentum, weekly ETF
reversal and calendar effects. Pre-registered in docs/research/V9_PREREGISTRATION.md.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from aurora.research import v9_common as c

RISK = ["SPY", "EFA", "EEM", "TLT", "IEF", "GLD", "SLV", "DBC", "USO", "UUP", "FXE", "FXY", "VNQ"]
SECT = ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]
BROAD = RISK + SECT + ["QQQ", "IWM", "DIA", "VGK", "EWJ", "SHY", "LQD", "HYG", "TIP", "UNG", "DBA", "FXB", "FXA", "FXC"]
SETS = {"RISK": RISK, "SECT": SECT, "BROAD": BROAD}
ALL_ETFS = sorted(set(BROAD))
VOL_TARGET, MAX_GROSS, MIN_ASSETS = 0.10, 2.0, 3
BLEND = (21, 63, 126, 252)


def context(opens: pd.DataFrame, closes: pd.DataFrame, x: dict) -> dict:
    """ETF arrays on the panel calendar (``x`` is the daily context: dates, cash, month and week rows)."""
    dates = x["dates"]
    o = opens.reindex(index=dates, columns=ALL_ETFS)
    cl = closes.reindex(index=dates, columns=ALL_ETFS)
    r = cl.pct_change(fill_method=None)
    vol = r.rolling(63, min_periods=50).std() * np.sqrt(c.PPY)
    return {"cols": ALL_ETFS, "cl": cl, "r": r.to_numpy(), "r_on": (o / cl.shift(1) - 1).to_numpy(),
            "r_id": (cl / o - 1).to_numpy(), "vol": vol.to_numpy(),
            "avail": ((cl.notna().cumsum() >= c.MIN_HISTORY) & vol.notna() & cl.notna()).to_numpy()}


def _set_mask(e: dict, name: str) -> np.ndarray:
    return np.isin(np.array(e["cols"]), SETS[name])


def _out(x: dict, W: np.ndarray, R: np.ndarray, lag: int = 1, turn: np.ndarray | None = None) -> dict:
    return c.net_series(*c.book(W, R, x["cash"], lag=lag, turn=turn), x["cash"], c.COSTS["etf"], x["dates"])


def _ret(cl: pd.DataFrame, L: int) -> np.ndarray:
    return (cl / cl.shift(L) - 1).to_numpy()


def tsmom(t: dict, x: dict, e: dict) -> dict:
    rows = x["month_rows"] if t["R"] == "M" else x["week_rows"]
    looks = BLEND if t["L"] == "BLEND" else (int(t["L"]),)
    sigs = []
    for L in looks:
        ret = _ret(e["cl"], L)
        sigs.append(np.sign(ret) if t["K"] == "SIGN" else np.clip(ret / (e["vol"] * np.sqrt(L / c.PPY)), -1, 1))
    sig = np.mean(sigs, axis=0)[rows]
    avail = (e["avail"] & _set_mask(e, t["SET"]))[rows] & ~np.isnan(sig)
    n = avail.sum(axis=1)
    w = np.where(avail, sig * VOL_TARGET / np.sqrt(np.maximum(n, 1))[:, None] / e["vol"][rows], 0.0)
    gross = np.abs(w).sum(axis=1)
    w = w * np.minimum(1.0, MAX_GROSS / np.where(gross > 0, gross, 1))[:, None]
    w[n < MIN_ASSETS] = 0.0
    return _out(x, c.monthly(w, rows, len(x["dates"])), e["r"])


def _rank_book(score: np.ndarray, avail: np.ndarray, n: int, long_only: bool) -> np.ndarray:
    """Long the n best scores, short the n worst (each leg 0.5), or the n best at 1/n each."""
    W = np.zeros_like(score)
    for k in range(len(score)):
        idx = np.flatnonzero(avail[k] & ~np.isnan(score[k]))
        if len(idx) < max(MIN_ASSETS, n if long_only else 2 * n):
            continue
        order = idx[np.argsort(score[k, idx], kind="stable")]
        if long_only:
            W[k, order[-n:]] = 1.0 / n
        else:
            W[k, order[-n:]] = 0.5 / n
            W[k, order[:n]] = -0.5 / n
    return W


def xsetf(t: dict, x: dict, e: dict) -> dict:
    rows = x["month_rows"]
    score = _ret(e["cl"], t["L"])[rows]
    W = _rank_book(score, (e["avail"] & _set_mask(e, t["SET"]))[rows], t["K"], t["M"] == "LONG")
    return _out(x, c.monthly(W, rows, len(x["dates"])), e["r"])


def etfrev(t: dict, x: dict, e: dict) -> dict:
    rows = x["week_rows"]
    score = -_ret(e["cl"], t["L"])[rows]
    W = _rank_book(score, (e["avail"] & _set_mask(e, t["SET"]))[rows], t["K"], False)
    return _out(x, c.monthly(W, rows, len(x["dates"])), e["r"])


def _month_position(dates: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray]:
    """1-based session number from the start and from the end of its month."""
    s = pd.Series(np.arange(len(dates)), index=dates)
    g = s.groupby(dates.to_period("M"))
    return (g.cumcount() + 1).to_numpy(), (g.cumcount(ascending=False) + 1).to_numpy()


def pre_holiday(dates: pd.DatetimeIndex) -> np.ndarray:
    """Sessions followed by a weekday without a session."""
    nxt = np.append(dates[1:].to_numpy(), np.datetime64("NaT"))
    weekday_after = (dates + pd.offsets.BDay(1)).to_numpy()
    out = nxt > weekday_after
    out[-1] = False
    return out


def season(t: dict, x: dict, e: dict) -> dict:
    dates, T = x["dates"], len(x["dates"])
    j = e["cols"].index(t["I"])
    cl = e["cl"][t["I"]].to_numpy()
    have = ~np.isnan(cl)
    tradable = have & np.append(have[1:], False) & e["avail"][:, j]
    kind = t["E"]
    if kind in ("ON", "ID"):
        W = np.where(tradable, 1.0, 0.0)[:, None]
        R = (e["r_on"] if kind == "ON" else e["r_id"])[:, [j]]
        return _out(x, W, R, turn=2 * W[:, 0])
    if kind == "PREHOL":
        target = pre_holiday(dates)
    else:
        a, b = (int(v) for v in kind[3:].split("-"))
        first, last = _month_position(dates)
        target = (first <= b) | (last <= a)
    hold_next = np.append(target[1:], False)  # weights at close t earn session t + 1
    W = np.where(hold_next & tradable, 1.0, 0.0)[:, None]
    return _out(x, W, e["r"][:, [j]])


RUNNERS = {"TSMOM": tsmom, "XSETF": xsetf, "ETFREV": etfrev, "SEASON": season}
