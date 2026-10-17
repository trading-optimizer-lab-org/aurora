"""Crypto trend following, as pre-registered in
docs/research/CRYPTO_TREND_PREREGISTRATION.md.

Every rule, universe, period and criterion below is copied from that document;
change the document first if anything here has to change.
"""
from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

from aurora.analytics.metrics_full.risk_adjusted import sharpe_ratio, sortino_ratio
from aurora.research import multiasset_baselines as mab

TRAIN_END = pd.Timestamp("2021-12-31")
VALIDATION_START = pd.Timestamp("2022-01-01")
VALIDATION_END = pd.Timestamp("2023-12-31")
LOCKED_START = pd.Timestamp("2024-01-01")

PPY = 365
COST_BPS = 30.0
TARGET_VOL = 0.30
VOL_DAYS = 30
MIN_HISTORY = 200
REBALANCE_WEEKDAY = 6  # Sunday

CORE = ["BTC", "ETH"]
ALTS = ["BTC", "ETH", "LTC", "BCH", "LINK", "DOGE"]

Signal = Callable[[pd.DataFrame, pd.Series], pd.DataFrame]


def ma_ensemble(close: pd.DataFrame, cash: pd.Series) -> pd.DataFrame:
    votes = [(close > close.rolling(n, min_periods=n).mean()).astype(float) for n in (20, 50, 100)]
    return sum(votes) / len(votes)


def tsmom_28(close: pd.DataFrame, cash: pd.Series) -> pd.DataFrame:
    asset_ret = close / close.shift(28) - 1
    cash_ret = cash / cash.shift(28) - 1
    return asset_ret.gt(cash_ret, axis=0).astype(float)


def donchian_20_10(close: pd.DataFrame, cash: pd.Series) -> pd.DataFrame:
    """Enter on a 20-day high close, exit on a 10-day low close (causal state)."""
    high = close.rolling(20, min_periods=20).max()
    low = close.rolling(10, min_periods=10).min()
    out = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    for asset in close.columns:
        held = False
        c, h, lo = close[asset].to_numpy(), high[asset].to_numpy(), low[asset].to_numpy()
        state = np.zeros(len(c))
        for t in range(len(c)):
            if not held and c[t] >= h[t]:
                held = True
            elif held and c[t] <= lo[t]:
                held = False
            state[t] = 1.0 if held else 0.0
        out[asset] = state
    return out


CANDIDATES: dict[str, tuple[Signal, list[str]]] = {
    "ma_ensemble": (ma_ensemble, CORE),
    "tsmom_28": (tsmom_28, CORE),
    "donchian_20_10": (donchian_20_10, CORE),
    "ma_ensemble_alts": (ma_ensemble, ALTS),
}
BENCHMARK = "btc_buy_hold"


def rebalance_dates(index: pd.DatetimeIndex, weekday: int | None = REBALANCE_WEEKDAY) -> pd.DatetimeIndex:
    """Fixed weekday (Monday=0 ... Sunday=6), or every day when ``weekday`` is None."""
    return index if weekday is None else index[index.weekday == weekday]


def target_weights(prices: pd.DataFrame, signal: Signal, universe: list[str],
                   weekday: int | None = REBALANCE_WEEKDAY) -> pd.DataFrame:
    close = prices[universe]
    raw = signal(close, prices["CASH"])
    vol = close.pct_change(fill_method=None).rolling(VOL_DAYS).std(ddof=1) * np.sqrt(PPY)
    size = np.minimum(1.0, TARGET_VOL / vol) / len(universe)
    available = close.notna().cumsum() >= MIN_HISTORY
    w = (raw * size).where(available, 0.0).fillna(0.0)
    total = w.sum(axis=1)
    w = w.div(total.clip(lower=1.0), axis=0)
    w["CASH"] = 1.0 - w.sum(axis=1)
    started = available.any(axis=1)
    dates = rebalance_dates(prices.index, weekday)
    return w.loc[dates.intersection(started[started].index)]


def benchmark_weights(prices: pd.DataFrame, weekday: int | None = REBALANCE_WEEKDAY) -> pd.DataFrame:
    available = prices["BTC"].notna().cumsum() >= MIN_HISTORY
    dates = rebalance_dates(prices.index, weekday).intersection(available[available].index)
    return pd.DataFrame({"BTC": 1.0}, index=dates[:1])


def drawdown_from_start(returns: pd.Series) -> float:
    equity = pd.concat([pd.Series([1.0]), (1 + returns).cumprod().reset_index(drop=True)])
    return float((equity / equity.cummax() - 1).min())


def metrics(returns: pd.Series, cash: pd.Series) -> dict[str, float | str]:
    r = returns.dropna()
    excess = (r - cash.reindex(r.index).fillna(0.0)).to_numpy()
    years = len(r) / PPY
    return {
        "start": str(r.index[0].date()), "end": str(r.index[-1].date()),
        "cagr": float((1 + r).prod() ** (1 / years) - 1),
        "vol": float(r.std(ddof=1) * np.sqrt(PPY)),
        "sharpe": sharpe_ratio(excess, ppy=PPY),
        "sortino": sortino_ratio(excess, ppy=PPY),
        "max_drawdown": drawdown_from_start(r),
        "days": int(len(r)),
        "skew": float(pd.Series(excess).skew()),
        "kurtosis": float(pd.Series(excess).kurt()) + 3.0,
        **mab._monthly_metrics(r, cash),
    }


def run_one(prices: pd.DataFrame, name: str, cost_bps: float = COST_BPS,
            weekday: int | None = REBALANCE_WEEKDAY) -> pd.Series:
    if name == BENCHMARK:
        weights = benchmark_weights(prices, weekday)
    else:
        signal, universe = CANDIDATES[name]
        weights = target_weights(prices, signal, universe, weekday)
    returns, _ = mab.simulate(prices, weights, cost_bps, untraded=("CASH",))
    return returns


def _periods(returns: pd.Series, cash: pd.Series) -> dict[str, dict]:
    return {
        "train": metrics(returns.loc[:TRAIN_END], cash),
        "validation": metrics(returns.loc[VALIDATION_START:VALIDATION_END], cash),
    }


def criteria(candidate: dict, benchmark: dict) -> dict[str, bool]:
    return {
        "monthly Sortino >= 2.0": candidate["sortino_monthly"] >= 2.0,
        "monthly Sortino above BTC buy and hold": candidate["sortino_monthly"] > benchmark["sortino_monthly"],
        "max drawdown no deeper than half of BTC's":
            abs(candidate["max_drawdown"]) <= abs(benchmark["max_drawdown"]) / 2,
    }


def run_study(prices: pd.DataFrame) -> dict:
    if prices.index.max() >= LOCKED_START:
        raise ValueError("locked period data reached the crypto study")
    cash = prices["CASH"].pct_change(fill_method=None).fillna(0.0)
    results: dict[str, dict] = {}
    daily: dict[str, pd.Series] = {}
    for name in [BENCHMARK, *CANDIDATES]:
        daily[name] = run_one(prices, name)
        results[name] = _periods(daily[name], cash)
    bench_val = results[BENCHMARK]["validation"]
    trial_sharpes = [results[n]["validation"]["sharpe"] for n in CANDIDATES]
    for name in CANDIDATES:
        v = results[name]["validation"]
        v["deflated_sharpe"] = mab.deflated_sharpe(
            v["sharpe"], trial_sharpes, n_periods=v["days"], skew=v["skew"],
            kurtosis=v["kurtosis"], ppy=PPY)
        results[name]["checks"] = criteria(v, bench_val)
        results[name]["passed"] = all(results[name]["checks"].values())
        results[name]["robustness"] = {
            **{f"weekday_{d}": metrics(run_one(prices, name, weekday=d)
                                       .loc[VALIDATION_START:VALIDATION_END], cash)["sortino_monthly"]
               for d in (2, 4)},
            "daily": metrics(run_one(prices, name, weekday=None)
                             .loc[VALIDATION_START:VALIDATION_END], cash)["sortino_monthly"],
            **{f"cost_{c:g}bps": metrics(run_one(prices, name, cost_bps=c)
                                         .loc[VALIDATION_START:VALIDATION_END], cash)["sortino_monthly"]
               for c in (15.0, 60.0)},
        }
    return {"results": results, "daily_returns": daily}
