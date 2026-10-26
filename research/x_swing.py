"""US stocks traded with momentum swing rules from X traders, as pre-registered in
docs/research/X_SWING_PREREGISTRATION.md.

Every rule, parameter, period and criterion is copied from that document; change the document first if anything
here has to change. Data, universe, survivorship adjustment and metrics are the SEPA study's
(``aurora.research.stocks_sepa``).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from aurora.research import multiasset_baselines as mab
from aurora.research import stocks_sepa as ss

RISK = 0.005
POS_CAP = 0.20
ADR_MIN = 0.04
IND_MIN = 50.0
IND_MEMBERS = 3
MIN_VOLUME = 100_000
CANDIDATES: dict[str, dict] = {}
for _name, _entry, _exit in (("b1_hold5", "b1", "hold5"), ("b1_ma20", "b1", "ma20"), ("b2_ma20", "b2", "ma20"),
                             ("b3_quick", "b3", "quick")):
    CANDIDATES[_name] = {"entry": _entry, "exit": _exit, "industry": False}
    CANDIDATES[f"{_name}_ind"] = {"entry": _entry, "exit": _exit, "industry": True}


def _ema(x: pd.DataFrame, n: int) -> pd.DataFrame:
    return x.ewm(span=n, adjust=False, min_periods=n).mean()


def industry_strength(rs: pd.DataFrame, universe: pd.DataFrame, industry: pd.Series) -> pd.DataFrame:
    """Each stock's industry percentile (0-100) of the median RS of the industry's universe stocks (3 or more)."""
    med = {}
    for ind, cols in industry.dropna().groupby(industry.dropna()).groups.items():
        cols = [c for c in cols if c in rs.columns]
        if not cols:
            continue
        u = universe[cols]
        m = rs[cols].where(u).median(axis=1)
        med[ind] = m.where(u.sum(axis=1) >= IND_MEMBERS)
    if not med:
        return pd.DataFrame(np.nan, index=rs.index, columns=rs.columns)
    pct = pd.DataFrame(med).rank(axis=1, pct=True) * 100
    out = pd.DataFrame(np.nan, index=rs.index, columns=rs.columns)
    for c in rs.columns:
        ind = industry.get(c)
        if isinstance(ind, str) and ind in pct.columns:
            out[c] = pct[ind]
    return out


def indicators(panel: dict[str, pd.DataFrame], index_close: pd.Series, industry: pd.Series) -> dict:
    base = ss.indicators(panel, index_close)
    close, high, low, volume = panel["close"], panel["high"], panel["low"], panel["volume"]
    e = {n: _ema(close, n) for n in (8, 9, 20, 21, 50)}
    rising = {n: e[n] > e[n].shift(5) for n in e}
    adr = (high / low - 1).rolling(20, min_periods=20).mean()
    vol50 = volume.rolling(50, min_periods=50).mean()
    rng = high - low
    pos_in_range = (close - low) / rng.where(rng > 0)
    idx = index_close.reindex(close.index).ffill()
    market = idx.rolling(10, min_periods=10).mean() > idx.rolling(20, min_periods=20).mean()

    hh7 = high.shift(1).rolling(7, min_periods=7).max()
    ll7 = low.shift(1).rolling(7, min_periods=7).min()
    held7 = (close >= e[20]).astype(float).shift(1).rolling(7, min_periods=7).min() == 1
    b1 = ((e[8] > e[20]) & (e[20] > e[50]) & rising[8] & rising[20] & rising[50] & held7
          & (hh7 / ll7 - 1 <= 3 * adr.shift(1)) & (close > hh7) & (rng > rng.shift(1)) & (pos_in_range >= 0.79)
          & ((close - low) / close <= 2.5 * adr))
    b2 = ((e[9] > e[21]) & rising[9] & rising[21] & (close > e[50])
          & (low.shift(1) <= e[9].shift(1)) & (close.shift(1) >= e[21].shift(1)) & (volume.shift(1) < vol50.shift(1))
          & (close > high.shift(1)))
    b3 = ((close / close.shift(1) - 1 >= 0.04) & (volume > volume.shift(1)) & (volume >= MIN_VOLUME)
          & ((high / low - 1).shift(1) <= adr.shift(1)) & (volume.shift(1) <= vol50.shift(1))
          & (close.shift(1) > e[21].shift(1)))
    stops = {"b1": low, "b2": low.shift(1), "b3": low}
    common = base["universe"] & (adr >= ADR_MIN)
    return {"universe": base["universe"], "rs": base["rs"], "market": market, "common": common,
            "entries": {"b1": b1, "b2": b2, "b3": b3}, "stops": stops, "sma20": close.rolling(20, min_periods=20).mean(),
            "ema9": e[9], "industry": industry_strength(base["rs"], base["universe"], industry)}


def signal_matrix(ind: dict, spec: dict) -> np.ndarray:
    ok = ind["entries"][spec["entry"]] & ind["common"]
    if spec["industry"]:
        ok = ok & (ind["industry"] >= IND_MIN)
    m = ind["market"].to_numpy()
    return ok.fillna(False).to_numpy(bool) & m[:, None]


def run_candidate(panel: dict[str, pd.DataFrame], ind: dict, cash_returns: pd.Series, spec: dict,
                  start: pd.Timestamp = ss.TRAIN_START) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Daily net return and invested fraction from ``start``, and the closed trades (entry date, return)."""
    dates = panel["close"].index
    O, L = (panel[k].to_numpy(dtype=float) for k in ("open", "low"))
    C_raw = panel["close"].to_numpy(dtype=float)
    C = panel["close"].ffill().to_numpy(dtype=float)
    rs = ind["rs"].to_numpy(dtype=float)
    stop_px = ind["stops"][spec["entry"]].to_numpy(dtype=float)
    sma20, ema9 = ind["sma20"].to_numpy(dtype=float), ind["ema9"].to_numpy(dtype=float)
    sig = signal_matrix(ind, spec)
    cash_r = cash_returns.reindex(dates).fillna(0.0).to_numpy()
    first = int(dates.searchsorted(start))
    rule = spec["exit"]

    cash, equity_prev = 1.0, 1.0
    pos: dict[int, dict] = {}
    rets, invested, trades = [], [], []

    def sell(i: int, frac: float, px: float) -> None:
        nonlocal cash
        p = pos[i]
        sh = p["shares"] * frac
        cash += sh * px * (1 - ss.COST)
        p["proceeds"] += sh * px * (1 - ss.COST)
        p["shares"] -= sh
        if p["shares"] <= 1e-12:
            trades.append((dates[p["t0"]], p["proceeds"] / p["cost"] - 1))
            del pos[i]

    for t in range(first, len(dates)):
        cash *= 1 + cash_r[t]
        for i in list(pos):
            p = pos[i]
            if not np.isfinite(C_raw[t, i]):
                continue
            p["n"] += 1
            if np.isfinite(L[t, i]) and L[t, i] <= p["stop"]:
                o = O[t, i] if np.isfinite(O[t, i]) else p["stop"]
                sell(i, 1.0, min(o, p["stop"]))
                continue
            c = C_raw[t, i]
            if rule == "hold5":
                if p["n"] >= 5:
                    sell(i, 1.0, c)
            elif rule == "ma20":
                if c < sma20[t, i]:
                    sell(i, 1.0, c)
            else:
                if not p["half"] and p["n"] == 3 and c <= p["entry"]:
                    sell(i, 1.0, c)
                    continue
                if not p["half"] and c >= p["entry"] + 2 * p["R"]:
                    sell(i, 0.5, c)
                    p["half"], p["stop"] = True, p["entry"]
                if p["half"] and i in pos and c < ema9[t, i]:
                    sell(i, 1.0, c)
        held = sum(p["shares"] * C[t, i] for i, p in pos.items())
        equity = cash + held
        cand = np.flatnonzero(sig[t])
        for i in cand[np.argsort(-np.nan_to_num(rs[t, cand], nan=-1.0), kind="stable")]:
            i = int(i)
            entry, stop = C_raw[t, i], stop_px[t, i]
            if i in pos or not (np.isfinite(entry) and np.isfinite(stop)) or stop >= entry or stop <= 0:
                continue
            amount = min(RISK * equity / ((entry - stop) / entry), POS_CAP * equity, cash / (1 + ss.COST))
            if amount <= 0:
                break
            cash -= amount * (1 + ss.COST)
            pos[i] = {"shares": amount / entry, "entry": entry, "stop": stop, "R": entry - stop, "n": 0,
                      "half": False, "t0": t, "cost": amount * (1 + ss.COST), "proceeds": 0.0}
        held = sum(p["shares"] * C[t, i] for i, p in pos.items())
        equity = cash + held
        rets.append(equity / equity_prev - 1)
        invested.append(held / equity if equity > 0 else 0.0)
        equity_prev = equity
    daily = pd.DataFrame({"return": rets, "invested": invested}, index=dates[first:])
    return daily, pd.DataFrame(trades, columns=["date", "return"])


def yearly(r: pd.Series) -> pd.Series:
    return (1 + r).groupby(r.index.year).prod() - 1


def trade_stats(trades: pd.DataFrame, a: pd.Timestamp, b: pd.Timestamp) -> dict:
    t = trades[(trades["date"] >= a) & (trades["date"] <= b)]
    years = max((b - a).days / 365.25, 1e-9)
    return {"trades_per_year": float(len(t) / years), "win_rate": float((t["return"] > 0).mean()) if len(t) else 0.0,
            "mean_trade": float(t["return"].mean()) if len(t) else 0.0}


def run_study(panel: dict[str, pd.DataFrame], industry: pd.Series, index_close: pd.Series, spy_close: pd.Series,
              cash_index: pd.Series, local_decile: pd.Series, french_decile: pd.Series) -> dict:
    if panel["close"].index.max() >= ss.LOCKED_START:
        raise ValueError("locked period data reached the swing study")
    dates = panel["close"].index
    cash = cash_index.reindex(dates).ffill().pct_change(fill_method=None).fillna(0.0)
    ind = indicators(panel, index_close, industry)
    bias = {p: ss.bias_per_month(local_decile, french_decile, a, b) for p, (a, b) in ss.PERIODS.items()}
    spy = spy_close.reindex(dates).ffill().pct_change(fill_method=None).loc[ss.TRAIN_START:].fillna(0.0)
    results: dict[str, dict] = {"spy": {p: ss.metrics(spy.loc[a:b], cash) for p, (a, b) in ss.PERIODS.items()}}
    daily: dict[str, pd.Series] = {"spy": spy}
    years: dict[str, dict] = {}
    for name, spec in CANDIDATES.items():
        d, trades = run_candidate(panel, ind, cash, spec)
        daily[name] = d["return"]
        results[name] = {"invested_mean": float(d["invested"].mean())}
        for p, (a, b) in ss.PERIODS.items():
            part = d.loc[a:b]
            results[name][p] = ss.metrics(ss.adjust(part, bias[p]), cash)
            results[name][f"{p}_unadjusted"] = ss.metrics(part["return"], cash)
            results[name][f"{p}_trades"] = trade_stats(trades, a, b)
        years[name] = {int(y): float(v) for y, v in yearly(d["return"]).items()}
    trial = [results[n]["validation"]["sharpe"] for n in CANDIDATES]
    for name in CANDIDATES:
        v = results[name]["validation"]
        v["deflated_sharpe"] = mab.deflated_sharpe(
            v["sharpe"], trial, n_periods=v["days"], skew=v["skew"], kurtosis=v["kurtosis"], ppy=ss.PPY)
        results[name]["checks"] = ss.criteria(v, results["spy"]["validation"])
        results[name]["passed"] = all(results[name]["checks"].values())
    return {"results": results, "bias_monthly": bias, "daily_returns": daily, "yearly": years}
