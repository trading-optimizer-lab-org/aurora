"""Crypto funding carry, as pre-registered in
docs/research/CRYPTO_CARRY_PREREGISTRATION.md.

Each asset sleeve holds long spot and short perpetual of the same notional
(50% of the sleeve's capital each; the other 50% is USDT margin). Daily
return on sleeve capital is ``N/K * (spot - perp return + funding) - fees/K``.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from aurora.research import crypto_trend as ct
from aurora.research import multiasset_baselines as mab

TRAIN_END = ct.TRAIN_END
VALIDATION_START = ct.VALIDATION_START
VALIDATION_END = ct.VALIDATION_END
LOCKED_START = ct.LOCKED_START

NOTIONAL_SHARE = 0.5
FEE_SPOT = 10 / 1e4
FEE_PERP = 5 / 1e4
SIGNAL_DAYS = 7

CANDIDATES: dict[str, tuple[list[str], str]] = {
    "carry_btc_always": (["BTC"], "always"),
    "carry_btc_positive": (["BTC"], "positive"),
    "carry_btc_eth_positive": (["BTC", "ETH"], "positive"),
}


def active_days(funding: pd.Series, rule: str) -> pd.Series:
    """Target state chosen at each day's close (funding of that day is known);
    ``sleeve_returns`` trades it at that close and holds it the next day."""
    if rule == "always":
        return pd.Series(True, index=funding.index)
    trailing = funding.rolling(SIGNAL_DAYS, min_periods=SIGNAL_DAYS).mean()
    return (trailing > 0).astype(bool)


def sleeve_returns(spot: pd.Series, perp: pd.Series, funding: pd.Series,
                   active: pd.Series) -> pd.Series:
    """Daily return on the capital of one asset sleeve, including fees."""
    s = spot.pct_change(fill_method=None).to_numpy()
    p = perp.pct_change(fill_method=None).to_numpy()
    f = funding.to_numpy()
    on = active.to_numpy()
    capital, notional = 1.0, 0.0
    out = np.zeros(len(s))
    for t in range(1, len(s)):
        pnl = notional * ((s[t] - p[t]) + f[t]) if notional else 0.0
        spot_val, perp_val = notional * (1 + s[t]), notional * (1 + p[t])
        new_capital = capital + pnl
        target = NOTIONAL_SHARE * new_capital if on[t] else 0.0
        fees = FEE_SPOT * abs(target - spot_val) + FEE_PERP * abs(target - perp_val)
        new_capital -= fees
        out[t] = new_capital / capital - 1
        capital, notional = new_capital, target
    return pd.Series(out, index=spot.index, name="return")


def run_one(data: dict[str, pd.DataFrame], name: str) -> pd.Series:
    assets, rule = CANDIDATES[name]
    sleeves = []
    for asset in assets:
        d = data[asset]
        sleeves.append(sleeve_returns(d["spot"], d["perp"], d["funding"], active_days(d["funding"], rule)))
    common = pd.concat(sleeves, axis=1).dropna()
    # Equal capital at the start, then each sleeve drifts: no implicit (and
    # unpaid) daily rebalancing between assets.
    value = (1 + common).cumprod().mean(axis=1)
    return value.pct_change().fillna(value.iloc[0] - 1)


def criteria(v: dict) -> dict[str, bool]:
    return {
        "monthly Sortino >= 2.0": v["sortino_monthly"] >= 2.0,
        "max drawdown no deeper than -10%": v["max_drawdown"] >= -0.10,
        "annualised return above T-bills": v["cagr"] > v["cash_cagr"],
    }


def _metrics(returns: pd.Series, cash: pd.Series) -> dict:
    m = ct.metrics(returns, cash)
    c = cash.reindex(returns.index).fillna(0.0)
    m["cash_cagr"] = float((1 + c).prod() ** (ct.PPY / len(c)) - 1)
    return m


def run_study(data: dict[str, pd.DataFrame], cash: pd.Series) -> dict:
    if max(d.index.max() for d in data.values()) >= LOCKED_START:
        raise ValueError("locked period data reached the carry study")
    results: dict[str, dict] = {}
    daily: dict[str, pd.Series] = {}
    for name in CANDIDATES:
        daily[name] = run_one(data, name)
        results[name] = {
            "train": _metrics(daily[name].loc[:TRAIN_END], cash),
            "validation": _metrics(daily[name].loc[VALIDATION_START:VALIDATION_END], cash),
        }
    trial_sharpes = [results[n]["validation"]["sharpe"] for n in CANDIDATES]
    for name in CANDIDATES:
        v = results[name]["validation"]
        v["deflated_sharpe"] = mab.deflated_sharpe(
            v["sharpe"], trial_sharpes, n_periods=v["days"], skew=v["skew"],
            kurtosis=v["kurtosis"], ppy=ct.PPY)
        results[name]["checks"] = criteria(v)
        results[name]["passed"] = all(results[name]["checks"].values())
    return {"results": results, "daily_returns": daily}
