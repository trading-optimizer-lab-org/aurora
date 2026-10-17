"""Robustness checks for the All Weather + VAA-G4 blend, without the locked period.

Five checks, all on data before 2021-01-01:

1. Costs: 5, 10, 20 and 40 bps per unit of turnover.
2. Rebalance day: month end, and the 7th, 15th and 22nd of each month.
3. Stability: monthly Sortino over rolling 36-month windows.
4. Uncertainty: stationary block bootstrap of monthly excess returns.
5. Parameters: VAA momentum score (13612W, equal-weight 1/3/6/12, 12m, 6m)
   crossed with the All Weather share (40%, 50%, 60%).

None of these variants is a candidate for selection: they only show how much
the baseline result depends on arbitrary choices.
"""
from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

from aurora.research import multiasset_baselines as mab

BASE_COST_BPS = 5.0
ROLLING_MONTHS = 36

SCORES: dict[str, Callable[[mab.MarketView, str], float]] = {
    "13612w": mab.keller_13612w,
    "13612u": lambda v, a: float(np.mean([v.mom(a, k) for k in (1, 3, 6, 12)])),
    "12m": lambda v, a: v.mom(a, 12),
    "6m": lambda v, a: v.mom(a, 6),
}


def aw_vaa(score: str = "13612w", aw_share: float = 0.5) -> mab.StrategyFn:
    vaa = mab.make_vaa_g4(SCORES[score])
    all_weather = mab.STRATEGIES["all_weather"]

    def strategy(view: mab.MarketView) -> mab.Weights | None:
        a, b = all_weather(view), vaa(view)
        if a is None or b is None:
            return None
        out = {k: aw_share * v for k, v in a.items()}
        for k, v in b.items():
            out[k] = out.get(k, 0.0) + (1 - aw_share) * v
        return out

    return strategy


def run(prices: pd.DataFrame, strategy: mab.StrategyFn, cost_bps: float = BASE_COST_BPS,
        day: int | None = None) -> pd.Series:
    dates = mab.signal_dates(prices.index, day)
    weights = mab.target_weights(prices, strategy, dates)
    returns, _ = mab.simulate(prices, weights, cost_bps)
    return returns


def monthly_excess(returns: pd.Series, cash: pd.Series) -> pd.Series:
    return mab._monthly(returns) - mab._monthly(cash.reindex(returns.index).fillna(0.0))


def sortino_of_monthly(excess: pd.Series) -> float:
    downside = np.sqrt((np.minimum(excess, 0.0) ** 2).sum() / (len(excess) - 1))
    return mab._sortino_from(float(excess.mean()), float(downside))


def summary(returns: pd.Series, cash: pd.Series) -> dict[str, float]:
    out: dict[str, float] = {}
    for label, start, end in (("is", None, mab.IN_SAMPLE_END),
                              ("val", mab.VALIDATION_START, mab.VALIDATION_END)):
        r = mab._period(returns, start, end)
        out[f"{label}_sortino_monthly"] = sortino_of_monthly(monthly_excess(r, cash))
    full = returns.loc[:mab.VALIDATION_END]
    equity = (1 + full).cumprod()
    out["max_drawdown"] = float((equity / equity.cummax() - 1).min())
    out["start"] = str(full.index[0].date())
    return out


def rolling_sortino(excess: pd.Series, window: int = ROLLING_MONTHS) -> pd.Series:
    return excess.rolling(window).apply(sortino_of_monthly, raw=False).dropna()


def block_bootstrap_sortino(excess: pd.Series, n: int = 5000, block: int = 6,
                            seed: int = 0) -> dict[str, float]:
    """Stationary bootstrap (Politis & Romano 1994) with mean block length ``block``."""
    x = excess.to_numpy()
    size = len(x)
    rng = np.random.default_rng(seed)
    stats = np.empty(n)
    for i in range(n):
        idx = np.empty(size, dtype=int)
        idx[0] = rng.integers(size)
        for t in range(1, size):
            idx[t] = rng.integers(size) if rng.random() < 1 / block else (idx[t - 1] + 1) % size
        stats[i] = sortino_of_monthly(pd.Series(x[idx]))
    finite = stats[np.isfinite(stats)]
    return {"p05": float(np.percentile(finite, 5)), "p50": float(np.percentile(finite, 50)),
            "p95": float(np.percentile(finite, 95)), "share_ge_2": float((finite >= 2).mean())}


def run_robustness(prices: pd.DataFrame, bootstrap_draws: int = 5000) -> dict:
    if prices.index.max() >= mab.LOCKED_START:
        raise ValueError("locked period data reached the robustness checks")
    cash = prices["CASH"].pct_change(fill_method=None)
    base = run(prices, aw_vaa())
    out: dict = {"baseline": summary(base, cash)}
    out["costs"] = {f"{c:g}bps": summary(run(prices, aw_vaa(), cost_bps=c), cash)
                    for c in (5.0, 10.0, 20.0, 40.0)}
    out["rebalance_day"] = {"month_end": out["baseline"],
                            **{f"day_{d}": summary(run(prices, aw_vaa(), day=d), cash)
                               for d in (7, 15, 22)}}
    roll = rolling_sortino(monthly_excess(base, cash))
    out["rolling_36m"] = {"windows": int(len(roll)), "min": float(roll.min()),
                          "median": float(roll.median()), "max": float(roll.max()),
                          "share_ge_2": float((roll >= 2).mean()),
                          "share_ge_1": float((roll >= 1).mean()),
                          "worst_window_end": str(roll.idxmin())}
    out["bootstrap"] = {
        label: block_bootstrap_sortino(
            monthly_excess(mab._period(base, start, end), cash), n=bootstrap_draws)
        for label, start, end in (("is", None, mab.IN_SAMPLE_END),
                                  ("val", mab.VALIDATION_START, mab.VALIDATION_END))
    }
    out["parameters"] = {f"{score}__aw{int(share * 100)}": summary(run(prices, aw_vaa(score, share)), cash)
                         for score in SCORES for share in (0.4, 0.5, 0.6)}
    return out
