"""US stocks traded with Minervini / O'Neil style rules, as pre-registered in
docs/research/STOCKS_SEPA_PREREGISTRATION.md.

Every rule, parameter, period and criterion is copied from that document;
change the document first if anything here has to change.

``panel`` is a dict of wide DataFrames (dates x symbols): ``open``, ``high``,
``low``, ``close`` (total-return adjusted), ``volume`` (split adjusted),
``dollar_volume`` and ``real_price`` (the price actually quoted that day).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from aurora.research import multiasset_baselines as mab

WARMUP_START = pd.Timestamp("1993-01-01")
TRAIN_START = pd.Timestamp("1995-01-01")
TRAIN_END = pd.Timestamp("2010-12-31")
VALIDATION_START = pd.Timestamp("2011-01-01")
VALIDATION_END = pd.Timestamp("2020-12-31")
LOCKED_START = pd.Timestamp("2021-01-01")

PPY = 252
COST = 10 / 1e4
UNIVERSE_SIZE = 1000
MIN_PRICE = 10.0
MIN_HISTORY = 260
RS_MIN = 70.0
MONTHLY_SLOTS = 20

CANDIDATES: dict[str, dict] = {
    "template_rs_monthly": {"mode": "monthly"},
    "sepa_breakout": {"mode": "daily", "slots": 10, "stop": 0.08, "target": None},
    "canslim_breakout": {"mode": "daily", "slots": 10, "stop": 0.07, "target": 0.25},
}


def indicators(panel: dict[str, pd.DataFrame], index_close: pd.Series) -> dict[str, pd.DataFrame | pd.Series]:
    close, volume = panel["close"], panel["volume"]
    history = close.notna().cumsum()
    dv50 = panel["dollar_volume"].rolling(50, min_periods=50).mean()
    eligible = (history >= MIN_HISTORY) & (panel["real_price"] >= MIN_PRICE) & dv50.notna()
    universe = eligible & (dv50.where(eligible).rank(axis=1, ascending=False) <= UNIVERSE_SIZE)

    ma50 = close.rolling(50, min_periods=50).mean()
    ma150 = close.rolling(150, min_periods=150).mean()
    ma200 = close.rolling(200, min_periods=200).mean()
    hi252 = close.rolling(252, min_periods=252).max()
    lo252 = close.rolling(252, min_periods=252).min()
    raw_rs = sum(w * (close / close.shift(n) - 1) for w, n in ((2, 63), (1, 126), (1, 189), (1, 252)))
    rs = raw_rs.where(universe).rank(axis=1, pct=True) * 100

    template = (
        universe
        & (close > ma150) & (close > ma200)
        & (ma150 > ma200)
        & (ma200 > ma200.shift(21))
        & (ma50 > ma150) & (ma50 > ma200)
        & (close > ma50)
        & (close >= 1.30 * lo252)
        & (close >= 0.75 * hi252)
        & (rs >= RS_MIN)
    )
    prior_high = close.shift(1).rolling(50, min_periods=50).max()
    prior_volume = volume.shift(1).rolling(50, min_periods=50).mean()
    breakout = (close > prior_high) & (volume >= 1.5 * prior_volume)

    idx = index_close.reindex(close.index).ffill()
    market = idx > idx.rolling(200, min_periods=200).mean()
    return {"universe": universe, "rs": rs, "ma50": ma50, "template": template,
            "breakout": breakout, "market": market}


def _month_ends(index: pd.DatetimeIndex) -> np.ndarray:
    s = pd.Series(index, index=index)
    return s.groupby(index.to_period("M")).transform("max").eq(s).to_numpy()


def run_candidate(panel: dict[str, pd.DataFrame], ind: dict, cash_returns: pd.Series,
                  spec: dict, start: pd.Timestamp = TRAIN_START) -> pd.DataFrame:
    """Daily net return and invested fraction from ``start``.

    Signals at the close of day t are executed at the open of day t+1.
    """
    dates = panel["close"].index
    O, H, L = (panel[k].to_numpy(dtype=float) for k in ("open", "high", "low"))
    C = panel["close"].ffill().to_numpy(dtype=float)
    rs = ind["rs"].to_numpy(dtype=float)
    below_ma50 = (panel["close"] < ind["ma50"]).to_numpy()
    template = ind["template"].to_numpy()
    entry = template & ind["breakout"].to_numpy() if spec["mode"] == "daily" else template
    market = ind["market"].to_numpy()
    month_end = _month_ends(dates)
    cash_r = cash_returns.reindex(dates).fillna(0.0).to_numpy()
    first = int(dates.searchsorted(start))
    slots = spec.get("slots", MONTHLY_SLOTS)

    cash, equity_prev = 1.0, 1.0
    pos: dict[int, dict] = {}
    sells: set[int] = set()
    buys: list[int] = []
    rets, invested = [], []
    for t in range(max(first - 1, 0), len(dates)):
        if t >= first:
            cash *= 1 + cash_r[t]
            for i in list(sells):
                if np.isfinite(O[t, i]):
                    cash += pos.pop(i)["shares"] * O[t, i] * (1 - COST)
                    sells.discard(i)
            for i in buys:
                if not np.isfinite(O[t, i]) or i in pos:
                    continue
                amount = min(equity_prev / slots, cash / (1 + COST))
                if amount <= 0:
                    break
                cash -= amount * (1 + COST)
                px = O[t, i]
                pos[i] = {"shares": amount / px,
                          "stop": px * (1 - spec["stop"]) if spec.get("stop") else None,
                          "target": px * (1 + spec["target"]) if spec.get("target") else None}
            buys = []
            for i in list(pos):
                p = pos[i]
                if i in sells or not np.isfinite(L[t, i]):
                    continue
                fill = None
                if p["stop"] is not None and L[t, i] <= p["stop"]:
                    fill = min(O[t, i], p["stop"])
                elif p["target"] is not None and H[t, i] >= p["target"]:
                    fill = max(O[t, i], p["target"])
                if fill is not None:
                    cash += pos.pop(i)["shares"] * fill * (1 - COST)
            held_value = sum(p["shares"] * C[t, i] for i, p in pos.items())
            equity = cash + held_value
            rets.append(equity / equity_prev - 1)
            invested.append(held_value / equity if equity > 0 else 0.0)
            equity_prev = equity
        # Signals at this close for the next open.
        if spec["mode"] == "daily":
            sells |= {i for i in pos if below_ma50[t, i]}
            if market[t]:
                free = slots - (len(pos) - len(sells))
                cand = np.flatnonzero(entry[t])
                cand = [i for i in cand[np.argsort(-rs[t, cand], kind="stable")] if i not in pos]
                buys = cand[:max(free, 0)]
        elif month_end[t]:
            if market[t]:
                cand = np.flatnonzero(entry[t])
                target = set(cand[np.argsort(-rs[t, cand], kind="stable")][:slots].tolist())
            else:
                target = set()
            sells = {i for i in pos if i not in target}
            buys = sorted(target - set(pos), key=lambda i: -rs[t, i])
    out_idx = dates[first:]
    return pd.DataFrame({"return": rets, "invested": invested}, index=out_idx)


def equal_weight_universe(panel: dict[str, pd.DataFrame], universe: pd.DataFrame,
                          start: pd.Timestamp = TRAIN_START) -> pd.Series:
    """Benchmark: the universe fixed at each month-end, equal weight, no costs."""
    daily = panel["close"].pct_change(fill_method=None)
    members = universe.astype(float)
    members.loc[~_month_ends(universe.index)] = np.nan
    members = members.ffill().shift(1).fillna(0.0).astype(bool)
    return daily.where(members).mean(axis=1).loc[start:].fillna(0.0).rename("return")


def momentum_top_decile(month_close: pd.DataFrame, month_price: pd.DataFrame,
                        nyse: pd.Index) -> pd.Series:
    """Equal-weighted next-month return of the top prior (12-2) decile, French
    style: NYSE breakpoints, real price >= $5, 13 months of history.
    Inputs are indexed by monthly ``PeriodIndex`` (month-end values)."""
    signal = month_close.shift(1) / month_close.shift(12) - 1
    nxt = month_close.shift(-1) / month_close - 1
    ok = signal.notna() & month_close.notna() & (month_price >= 5)
    bp = signal.where(ok)[signal.columns.intersection(nyse)].quantile(0.9, axis=1)
    top = ok & signal.ge(bp, axis=0)
    out = nxt.where(top).mean(axis=1)
    out.index = out.index + 1  # labelled by the holding month
    return out.dropna().rename("local_hi_prior")


def bias_per_month(local: pd.Series, french: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> float:
    both = pd.concat([local, french], axis=1, join="inner").loc[start.to_period("M"):end.to_period("M")]
    return max(0.0, float((both.iloc[:, 0] - both.iloc[:, 1]).mean()))


def adjust(daily: pd.DataFrame, monthly_bias: float) -> pd.Series:
    """Remove the measured monthly bias in proportion to the invested fraction,
    spread evenly over each month's trading days."""
    days = daily.groupby(daily.index.to_period("M"))["return"].transform("size")
    return (daily["return"] - monthly_bias * daily["invested"] / days).rename("return")


def metrics(returns: pd.Series, cash: pd.Series) -> dict:
    m = mab.metrics(returns, cash)
    excess = returns - cash.reindex(returns.index).fillna(0.0)
    m["skew"] = float(excess.skew())
    m["kurtosis"] = float(excess.kurt()) + 3.0
    return m


def criteria(v: dict, spy: dict) -> dict[str, bool]:
    return {
        "monthly Sortino >= 2.0": v["sortino_monthly"] >= 2.0,
        "annualised return above SPY": v["cagr"] > spy["cagr"],
        "max drawdown no deeper than -25%": v["max_drawdown"] >= -0.25,
    }


PERIODS = {"train": (TRAIN_START, TRAIN_END), "validation": (VALIDATION_START, VALIDATION_END)}


def run_study(panel: dict[str, pd.DataFrame], index_close: pd.Series, spy_close: pd.Series,
              cash_index: pd.Series, local_decile: pd.Series, french_decile: pd.Series) -> dict:
    if panel["close"].index.max() >= LOCKED_START:
        raise ValueError("locked period data reached the stocks study")
    dates = panel["close"].index
    cash = cash_index.reindex(dates).ffill().pct_change(fill_method=None).fillna(0.0)
    ind = indicators(panel, index_close)
    bias = {p: bias_per_month(local_decile, french_decile, a, b) for p, (a, b) in PERIODS.items()}
    spy = spy_close.reindex(dates).ffill().pct_change(fill_method=None).loc[TRAIN_START:].fillna(0.0)
    ew = equal_weight_universe(panel, ind["universe"])
    results: dict[str, dict] = {}
    daily: dict[str, pd.Series] = {"spy": spy, "equal_weight_universe": ew}
    for name in ("spy", "equal_weight_universe"):
        results[name] = {p: metrics(daily[name].loc[a:b], cash) for p, (a, b) in PERIODS.items()}
    for name, spec in CANDIDATES.items():
        d = run_candidate(panel, ind, cash, spec)
        daily[name] = d["return"]
        results[name] = {"invested_mean": float(d["invested"].mean())}
        for p, (a, b) in PERIODS.items():
            part = d.loc[a:b]
            results[name][p] = metrics(adjust(part, bias[p]), cash)
            results[name][f"{p}_unadjusted"] = metrics(part["return"], cash)
    trial = [results[n]["validation"]["sharpe"] for n in CANDIDATES]
    for name in CANDIDATES:
        v = results[name]["validation"]
        v["deflated_sharpe"] = mab.deflated_sharpe(
            v["sharpe"], trial, n_periods=v["days"], skew=v["skew"], kurtosis=v["kurtosis"], ppy=PPY)
        results[name]["checks"] = criteria(v, results["spy"]["validation"])
        results[name]["passed"] = all(results[name]["checks"].values())
    return {"results": results, "bias_monthly": bias, "daily_returns": daily}
