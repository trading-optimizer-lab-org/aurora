"""v14 position families on ETFs, volatility, the calendar and crypto: C18 (index part), D23-D26, E27-E30.
Pre-registered in docs/research/V14_PREREGISTRATION.md. Every rule returns a daily position matrix decided on
the prior close (or earlier), so the placebo can shift it in time.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

ETF_COST, CRYPTO_COST = 0.0002, 0.0015
SECTORS = ("XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY", "XLRE", "XLC")

MACRO_DIMS = {
    "C18_IDXNIGHT": {"inst": ("SPY", "QQQ", "IWM"), "after": (0.0, -0.01, -0.02)},
    "D23_VIXTERM": {"ratio": (0.90, 0.95, 1.00), "vix20": (True, False), "hedge": (False, True)},
    "D24_FOMC": {"inst": ("SPY", "QQQ"), "to": ("close", "1400")},
    "D24_TOM": {"before": (1, 4)},
    "D25_MONTHEND": {"lead": (0.02, 0.04), "pair": (True, False)},
    "D26_SECTORS": {"top": (2, 3), "look": (63, 126, 252), "trend": (True, False)},
    "E27_CTREND": {"signal": ("ens", "m14", "m28", "m56"), "n": (10, 30)},
    "E28_CXMOM": {"top": (3, 5, 10), "look": (7, 14, 28), "btc": (True, False)},
    "E29_CHOURLY": {"look": (24, 72, 168), "every": (4, 24)},
    "E30_WEEKEND": {"days": ("weekend", "weekdays")},
    "E30_FUNDING": {"thr": (0.0003, 0.0005), "to": ("cash", "short")},
}


def returns_from_positions(pos: pd.DataFrame, rets: pd.DataFrame, cost: float) -> pd.Series:
    """Daily portfolio return of positions held over each day (decided before it), less turnover costs."""
    pos = pos.reindex(columns=rets.columns).fillna(0.0)
    turn = pos.diff().abs().sum(axis=1).fillna(pos.abs().sum(axis=1))
    return (pos * rets.fillna(0.0)).sum(axis=1) - cost * turn


def shift_positions(pos: pd.DataFrame, k: int) -> pd.DataFrame:
    """The placebo: the same positions moved ``k`` rows later, wrapping around."""
    return pd.DataFrame(np.roll(pos.to_numpy(), k, axis=0), index=pos.index, columns=pos.columns)


# ---------------------------------------------------------------- ETF and calendar

def idx_night(X: dict, g: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Buy the close, sell the next open. Returns (positions, returns) with the overnight return on the next row."""
    o, c = X["etf_open"][g["inst"]], X["etf_close"][g["inst"]]
    night = (o / c.shift(1) - 1 - 2 * ETF_COST).to_frame(g["inst"])  # bought and sold every night
    day = c.pct_change(fill_method=None)
    sig = (day <= g["after"]) if g["after"] < 0 else pd.Series(True, index=c.index)
    pos = sig.shift(1).fillna(False).astype(float).to_frame(g["inst"])
    return pos, night


def vix_term(X: dict, g: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    ratio = X["vix"] / X["vix3m"]
    on = ratio < g["ratio"]
    if g["vix20"]:
        on &= X["vix"] < 20
    pos = pd.DataFrame({"SVXY": on.astype(float)})
    if g["hedge"]:
        pos["VIXY"] = (ratio > 1.05).astype(float)
    pos = pos.shift(1).reindex(X["dates"]).fillna(0.0)
    return pos, X["etf_ret"][list(pos.columns)]


def fomc(X: dict, g: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    days = X["dates"].isin(X["fomc"])
    pos = pd.DataFrame({g["inst"]: days.astype(float)}, index=X["dates"])
    if g["to"] == "close":
        return pos, X["etf_ret"][[g["inst"]]]
    r = X["to1400"][g["inst"]].reindex(X["dates"]).fillna(0.0).to_frame(g["inst"])
    return pos, r


def tom(X: dict, g: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    d = X["dates"]
    month = d.to_period("M")
    pos_in_month = pd.Series(np.arange(len(d)), index=d).groupby(month).rank(method="first").astype(int)
    from_end = pd.Series(np.arange(len(d)), index=d).groupby(month).rank(ascending=False, method="first").astype(int)
    # held over the last ``before`` days of a month and the first 3 of the next
    held = (from_end <= g["before"]) | (pos_in_month <= 3)
    return pd.DataFrame({"SPY": held.astype(float).to_numpy()}, index=d), X["etf_ret"][["SPY"]]


def month_end(X: dict, g: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    d = X["dates"]
    c = X["etf_close"][["SPY", "TLT"]]
    month = d.to_period("M")
    from_end = pd.Series(np.arange(len(d)), index=d).groupby(month).rank(ascending=False, method="first").astype(int)
    prior_end = c.groupby(month).last().shift(1)
    mtd = c / prior_end.reindex(month).to_numpy() - 1
    lead = mtd["SPY"] - mtd["TLT"]
    decide = from_end == 6  # the close five sessions before the month's last one
    sig = pd.Series(np.where(decide & (lead > g["lead"]), -1.0, np.where(decide & (lead < -g["lead"]), 1.0, np.nan)),
                    index=d)
    sig = sig.where(decide).groupby(month).ffill().where(from_end <= 5).fillna(0.0)
    # +1: SPY lags (long SPY, short TLT); -1: SPY leads (short SPY, long TLT)
    if g["pair"]:
        pos = pd.DataFrame({"SPY": 0.5 * sig, "TLT": -0.5 * sig}, index=d)
    else:
        pos = pd.DataFrame({"SPY": sig.clip(lower=0), "TLT": (-sig).clip(lower=0)}, index=d)
    return pos, X["etf_ret"][["SPY", "TLT"]]


def sectors(X: dict, g: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    c = X["etf_close"][[s for s in SECTORS if s in X["etf_close"]]]
    mom = c / c.shift(g["look"]) - 1
    month = c.index.to_period("M")
    last = pd.Series(c.index, index=c.index).groupby(month).transform("max") == pd.Series(c.index, index=c.index)
    rank = mom.rank(axis=1, ascending=False)
    pick = (rank <= g["top"]).astype(float).div(g["top"])
    if g["trend"]:
        spy = X["etf_close"]["SPY"]
        pick = pick.mul((spy > spy.rolling(200, min_periods=200).mean()).astype(float), axis=0)
    pos = pick.where(last).ffill().shift(1).fillna(0.0)
    return pos, X["etf_ret"][list(c.columns)]


# ---------------------------------------------------------------- crypto (calendar days, UTC)

def liquid(Y: dict) -> pd.DataFrame:
    return (Y["qv"].rolling(30, min_periods=20).median() >= 10e6).shift(1).fillna(False)


def ctrend(Y: dict, g: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    c, ret = Y["close"], Y["ret"]
    rank = Y["qv"].rolling(30, min_periods=20).median().shift(1).where(liquid(Y)).rank(axis=1, ascending=False)
    top = rank <= g["n"]
    if g["signal"] == "ens":
        sig = sum((c > c.rolling(n, min_periods=n).mean()).astype(float) for n in (20, 50, 100)) / 3
    else:
        n = int(g["signal"][1:])
        cash = Y["cash"].rolling(n, min_periods=n).apply(lambda x: np.prod(1 + x) - 1, raw=True)
        sig = (c / c.shift(n) - 1).gt(cash, axis=0).astype(float)
    vol = ret.rolling(30, min_periods=20).std() * np.sqrt(365)
    size = np.minimum(1.0, 0.30 / vol) / g["n"]
    pos = (sig * size).where(top, 0.0).shift(1).fillna(0.0)
    return pos, ret


def cxmom(Y: dict, g: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    c, ret = Y["close"], Y["ret"]
    mom = (c / c.shift(g["look"]) - 1).where(liquid(Y))
    pick = (mom.rank(axis=1, ascending=False) <= g["top"]).astype(float).div(g["top"])
    if g["btc"]:
        b = c["BTCUSDT"]
        pick = pick.mul((b > b.rolling(50, min_periods=50).mean()).astype(float), axis=0)
    monday = pd.Series(c.index.dayofweek == 0, index=c.index)
    pos = pick.where(monday).ffill().shift(1).fillna(0.0)
    return pos, ret


def chourly(Y: dict, g: dict, shift_days: int = 0) -> pd.Series:
    """Hourly BTC and ETH, half each, held while the trailing return is positive; daily (UTC) net returns.
    ``shift_days`` moves the positions later (the placebo)."""
    out = []
    for s in ("BTCUSDT", "ETHUSDT"):
        c = Y["hourly"][s]
        r = c.pct_change(fill_method=None)
        sig = (c / c.shift(g["look"]) - 1 > 0).astype(float)
        hours = pd.Series(np.arange(len(c)) % g["every"] == 0, index=c.index)
        pos = sig.where(hours).ffill().shift(1).fillna(0.0)
        if shift_days:
            pos = pd.Series(np.roll(pos.to_numpy(), 24 * shift_days), index=pos.index)
        net = pos * r.fillna(0.0) - CRYPTO_COST * pos.diff().abs().fillna(0.0)
        out.append(0.5 * net)
    total = out[0].add(out[1], fill_value=0.0)
    return (1 + total).groupby(total.index.normalize()).prod() - 1


def weekend(Y: dict, g: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    d = Y["close"].index
    wk = d.dayofweek  # the daily bar of day d covers d 00:00-24:00 UTC
    held = np.isin(wk, (5, 6, 0)) if g["days"] == "weekend" else np.isin(wk, (1, 2, 3, 4))
    return pd.DataFrame({"BTCUSDT": held.astype(float)}, index=d), Y["ret"][["BTCUSDT"]]


def funding(Y: dict, g: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Half BTC, half ETH, dropped for 3 days after the 3-day mean funding (per 8 hours) exceeds ``thr``: to cash or
    to a short perpetual, which earns minus the price change plus the funding (three payments a day)."""
    f = Y["funding"]
    hot = f.rolling(3, min_periods=3).mean() > g["thr"]
    off = hot.astype(float).rolling(3, min_periods=1).max().shift(1).fillna(0.0) > 0
    ret = Y["ret"][list(f.columns)].reindex(f.index)
    pos = pd.DataFrame(np.where(off, 0.0, 0.5), index=f.index, columns=f.columns)
    rets = ret.copy()
    if g["to"] == "short":
        for col in f.columns:
            pos[col + "_SHORT"] = np.where(off[col], 0.5, 0.0)
            rets[col + "_SHORT"] = -ret[col] + 3 * f[col]
    return pos, rets


RULES = {"C18_IDXNIGHT": (idx_night, "etf"), "D23_VIXTERM": (vix_term, "etf"), "D24_FOMC": (fomc, "etf"),
         "D24_TOM": (tom, "etf"), "D25_MONTHEND": (month_end, "etf"), "D26_SECTORS": (sectors, "etf"),
         "E27_CTREND": (ctrend, "crypto"), "E28_CXMOM": (cxmom, "crypto"), "E30_WEEKEND": (weekend, "crypto"),
         "E30_FUNDING": (funding, "crypto")}


def run(family: str, g: dict, X: dict, Y: dict, shift: int = 0) -> pd.Series:
    """Daily net returns of one configuration (crypto on calendar days); ``shift`` > 0 gives a placebo."""
    if family == "E29_CHOURLY":
        return chourly(Y, g, shift)
    fn, kind = RULES[family]
    pos, rets = fn(X if kind == "etf" else Y, g)
    if shift:
        pos = shift_positions(pos, shift)
    return returns_from_positions(pos, rets.reindex(pos.index), ETF_COST if kind == "etf" else CRYPTO_COST)
