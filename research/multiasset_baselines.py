"""Published multi-asset allocation strategies, evaluated without tuning.

Every strategy uses the parameters from its source (Faber, Antonacci, Keller,
Moskowitz, Butler et al., Dalio, Browne...). Nothing here is optimised, so the
number of trials stays small and known for the deflated Sharpe ratio.

Conventions
-----------
* ``prices`` is a DataFrame of total-return price indices (one column per
  asset, daily, NaN before an asset exists). ``CASH`` is a synthetic T-bill
  index built from the 3-month T-bill rate.
* Signals are computed at the close of the last trading day of each month and
  applied from the next trading day. Holdings drift between rebalances.
* Every rebalance pays ``cost_bps`` per unit of one-way turnover.
* Data on or after ``LOCKED_START`` must never reach this module; callers
  truncate first and :func:`run_all` asserts it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import norm

from aurora.analytics.metrics_full.drawdown import max_drawdown
from aurora.analytics.metrics_full.risk_adjusted import sharpe_ratio, sortino_ratio
from aurora.deployment.hrp import hrp_allocate

LOCKED_START = pd.Timestamp("2021-01-01")
IN_SAMPLE_END = pd.Timestamp("2010-12-31")
VALIDATION_START = pd.Timestamp("2011-01-01")
VALIDATION_END = pd.Timestamp("2020-12-31")
COST_BPS = 5.0
TRADING_DAYS = 252

Weights = dict[str, float]
StrategyFn = Callable[["MarketView"], "Weights | None"]


@dataclass(frozen=True)
class MarketView:
    """Data visible at one signal date (inclusive), nothing later."""

    daily: pd.DataFrame  # total-return indices up to the signal date
    monthly: pd.DataFrame  # month-end closes up to the signal date

    def has(self, assets: list[str], months: int) -> bool:
        """True when every asset has at least ``months`` + 1 month-end closes."""
        cols = self.monthly.reindex(columns=assets)
        return bool(len(cols) > months and cols.iloc[-(months + 1):].notna().all().all())

    def mom(self, asset: str, months: int) -> float:
        m = self.monthly[asset]
        return float(m.iloc[-1] / m.iloc[-1 - months] - 1.0)

    def sma_ratio(self, asset: str, months: int = 10) -> float:
        m = self.monthly[asset]
        return float(m.iloc[-1] / m.iloc[-months:].mean())

    def vol(self, asset: str, days: int = 60) -> float:
        r = self.daily[asset].pct_change(fill_method=None).iloc[-days:]
        return float(r.std(ddof=1) * np.sqrt(TRADING_DAYS))

    def daily_returns(self, assets: list[str], days: int) -> pd.DataFrame:
        return self.daily[assets].pct_change(fill_method=None).iloc[-days:].dropna()


def keller_13612w(view: MarketView, asset: str) -> float:
    """Keller & Keuning (2017) fast momentum: 12*r1 + 4*r3 + 2*r6 + r12."""
    return (12 * view.mom(asset, 1) + 4 * view.mom(asset, 3)
            + 2 * view.mom(asset, 6) + view.mom(asset, 12))


def _static(weights: Weights) -> StrategyFn:
    assets = list(weights)

    def strategy(view: MarketView) -> Weights | None:
        return dict(weights) if view.has(assets, 0) else None

    return strategy


def inverse_vol(view: MarketView) -> Weights | None:
    assets = ["SPY", "TLT", "GLD", "DBC"]
    if not view.has(assets, 3):
        return None
    inv = {a: 1.0 / view.vol(a, 60) for a in assets}
    total = sum(inv.values())
    return {a: v / total for a, v in inv.items()}


def gtaa5(view: MarketView) -> Weights | None:
    """Faber (2007): five assets, 20% each, held only above the 10-month SMA."""
    assets = ["SPY", "EFA", "IEF", "VNQ", "DBC"]
    if not view.has(assets, 10):
        return None
    w: Weights = {"CASH": 0.0}
    for a in assets:
        if view.sma_ratio(a, 10) > 1.0:
            w[a] = 0.2
        else:
            w["CASH"] += 0.2
    return w


def gtaa_aggressive(view: MarketView) -> Weights | None:
    """Faber top-3: average 1/3/6/12-month momentum, each also above its SMA10."""
    assets = ["SPY", "IWM", "EFA", "EEM", "IEF", "TLT", "LQD", "TIP", "GLD", "DBC", "VNQ"]
    if not view.has(assets, 12):
        return None
    score = {a: np.mean([view.mom(a, k) for k in (1, 3, 6, 12)]) for a in assets}
    top = sorted(assets, key=score.__getitem__, reverse=True)[:3]
    w: Weights = {"CASH": 0.0}
    for a in top:
        if view.sma_ratio(a, 10) > 1.0:
            w[a] = 1 / 3
        else:
            w["CASH"] += 1 / 3
    return w


def gem(view: MarketView) -> Weights | None:
    """Antonacci (2014) Global Equities Momentum, 12-month lookback."""
    if not view.has(["SPY", "EFA", "AGG", "CASH"], 12):
        return None
    if view.mom("SPY", 12) > view.mom("CASH", 12):
        return {"SPY": 1.0} if view.mom("SPY", 12) >= view.mom("EFA", 12) else {"EFA": 1.0}
    return {"AGG": 1.0}


def vaa_g4(view: MarketView) -> Weights | None:
    """Keller & Keuning (2017) VAA-G4, top 1."""
    offensive, defensive = ["SPY", "EFA", "EEM", "AGG"], ["LQD", "IEF", "SHY"]
    if not view.has(offensive + defensive, 12):
        return None
    score = {a: keller_13612w(view, a) for a in offensive + defensive}
    if all(score[a] > 0 for a in offensive):
        return {max(offensive, key=score.__getitem__): 1.0}
    return {max(defensive, key=score.__getitem__): 1.0}


def daa_canary(view: MarketView) -> Weights | None:
    """Keller & Keuning (2018) DAA canary rule, simplified to the VAA-G4 universe.

    Canaries EEM and AGG stand in for VWO and BND (longer history). The share in
    the best defensive asset is (number of canaries with negative 13612W) / 2;
    the rest goes equally to the top-2 offensive assets.
    """
    offensive, defensive, canary = ["SPY", "EFA", "EEM", "AGG"], ["LQD", "IEF", "SHY"], ["EEM", "AGG"]
    if not view.has(offensive + defensive, 12):
        return None
    score = {a: keller_13612w(view, a) for a in offensive + defensive}
    defensive_share = sum(score[c] < 0 for c in canary) / 2
    w: Weights = {}
    if defensive_share > 0:
        w[max(defensive, key=score.__getitem__)] = defensive_share
    for a in sorted(offensive, key=score.__getitem__, reverse=True)[:2]:
        w[a] = w.get(a, 0.0) + (1 - defensive_share) / 2
    return w


def tsmom(view: MarketView) -> Weights | None:
    """Moskowitz, Ooi & Pedersen (2012), long-only: hold assets whose 12-month
    excess return is positive, each sized to 10% annual vol / N, no leverage."""
    assets = ["SPY", "EFA", "EEM", "IEF", "TLT", "GLD", "DBC", "VNQ"]
    if not view.has(assets + ["CASH"], 12):
        return None
    cash_12 = view.mom("CASH", 12)
    w = {a: 0.10 / view.vol(a, 60) / len(assets) for a in assets if view.mom(a, 12) > cash_12}
    total = sum(w.values())
    if total > 1.0:
        w = {a: v / total for a, v in w.items()}
    w["CASH"] = 1.0 - sum(w.values())
    return w


def _min_variance(returns: pd.DataFrame) -> pd.Series:
    cov = returns.cov().to_numpy() * TRADING_DAYS
    n = cov.shape[0]
    res = minimize(lambda x: x @ cov @ x, np.full(n, 1 / n), method="SLSQP",
                   bounds=[(0.0, 1.0)] * n,
                   constraints=({"type": "eq", "fun": lambda x: x.sum() - 1.0},))
    x = np.clip(res.x, 0.0, None)
    return pd.Series(x / x.sum(), index=returns.columns)


def adaptive_asset_allocation(view: MarketView) -> Weights | None:
    """Butler, Philbrick & Gordillo (2012): top 5 by 6-month momentum,
    minimum-variance weights on 60 days of returns."""
    assets = ["SPY", "EFA", "EEM", "IEF", "TLT", "GLD", "DBC", "VNQ"]
    if not view.has(assets, 6):
        return None
    top = sorted(assets, key=lambda a: view.mom(a, 6), reverse=True)[:5]
    return _min_variance(view.daily_returns(top, 60)).to_dict()


def sector_rotation(view: MarketView) -> Weights | None:
    """Top 3 of the 9 original SPDR sectors by 6-month momentum while SPY is
    above its 10-month SMA; otherwise intermediate Treasuries."""
    sectors = ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]
    if not view.has(sectors + ["SPY", "IEF"], 10):
        return None
    if view.sma_ratio("SPY", 10) <= 1.0:
        return {"IEF": 1.0}
    top = sorted(sectors, key=lambda a: view.mom(a, 6), reverse=True)[:3]
    return {a: 1 / 3 for a in top}


def hrp(view: MarketView) -> Weights | None:
    """Lopez de Prado (2016) HRP on one year of daily returns."""
    assets = ["SPY", "EFA", "EEM", "IEF", "TLT", "LQD", "GLD", "DBC", "VNQ"]
    if not view.has(assets, 12):
        return None
    return dict(hrp_allocate(view.daily_returns(assets, TRADING_DAYS)).weights)


STRATEGIES: dict[str, StrategyFn] = {
    "spy_buy_hold": _static({"SPY": 1.0}),
    "sixty_forty": _static({"SPY": 0.6, "IEF": 0.4}),
    "inverse_vol": inverse_vol,
    "gtaa5": gtaa5,
    "gtaa_aggressive": gtaa_aggressive,
    "gem": gem,
    "vaa_g4": vaa_g4,
    "daa_canary": daa_canary,
    "tsmom": tsmom,
    "adaptive_asset_allocation": adaptive_asset_allocation,
    "sector_rotation": sector_rotation,
    "hrp": hrp,
    "all_weather": _static({"SPY": 0.30, "TLT": 0.40, "IEF": 0.15, "GLD": 0.075, "DBC": 0.075}),
    "golden_butterfly": _static({"SPY": 0.2, "IWM": 0.2, "TLT": 0.2, "SHY": 0.2, "GLD": 0.2}),
    "permanent": _static({"SPY": 0.25, "TLT": 0.25, "CASH": 0.25, "GLD": 0.25}),
    "put_write": _static({"PUT": 1.0}),
    "buy_write": _static({"BXM": 1.0}),
}
BENCHMARK = "spy_buy_hold"


def signal_dates(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Last trading day of each month present in ``index``."""
    s = pd.Series(index, index=index)
    return pd.DatetimeIndex(s.groupby(index.to_period("M")).max().to_numpy())


def target_weights(prices: pd.DataFrame, strategy: StrategyFn) -> pd.DataFrame:
    monthly = prices.loc[signal_dates(prices.index)]
    rows: dict[pd.Timestamp, Weights] = {}
    for date in monthly.index:
        w = strategy(MarketView(prices.loc[:date], monthly.loc[:date]))
        if w is not None:
            rows[date] = {k: v for k, v in w.items() if abs(v) > 1e-12}
    return pd.DataFrame.from_dict(rows, orient="index").fillna(0.0)


def simulate(prices: pd.DataFrame, weights: pd.DataFrame,
             cost_bps: float = COST_BPS) -> tuple[pd.Series, pd.Series]:
    """Daily net returns and one-way turnover per rebalance.

    A target set at the close of day ``d`` is traded at that close and earns
    the returns of ``d + 1`` onwards.
    """
    returns = prices.pct_change(fill_method=None).reindex(columns=weights.columns).to_numpy()
    dates = prices.index
    targets = {dates.get_loc(d): w for d, w in zip(weights.index, weights.to_numpy())}
    current: np.ndarray | None = None
    pending: np.ndarray | None = None
    out_idx, out_val, turn_idx, turn_val = [], [], [], []
    for t in range(len(dates)):
        cost = 0.0
        if pending is not None:
            prev = current if current is not None else np.zeros_like(pending)
            turn = float(np.abs(pending - prev).sum() / 2)
            turn_idx.append(dates[t])
            turn_val.append(turn)
            cost = 2 * turn * cost_bps / 1e4
            current, pending = pending, None
        if current is not None:
            held = current != 0.0
            r = np.where(held, returns[t], 0.0)
            if np.isnan(r[held]).any():
                raise ValueError(f"missing return for a held asset on {dates[t].date()}")
            gross = float(current @ r)
            out_idx.append(dates[t])
            out_val.append(gross - cost)
            current = current * (1 + r) / (1 + gross)
        if t in targets:
            pending = targets[t]
    return (pd.Series(out_val, index=pd.DatetimeIndex(out_idx), name="return"),
            pd.Series(turn_val, index=pd.DatetimeIndex(turn_idx), name="turnover"))


def vol_target_overlay(strategy_returns: pd.Series, cash_returns: pd.Series,
                       target: float = 0.10, lookback: int = 63,
                       cost_bps: float = COST_BPS) -> pd.Series:
    """Scale exposure monthly to ``target`` annual vol (capped at 1, rest in cash)
    using the trailing ``lookback`` days of the strategy's own returns."""
    dates = signal_dates(strategy_returns.index)
    scale = pd.Series(np.nan, index=strategy_returns.index)
    for date in dates:
        hist = strategy_returns.loc[:date].iloc[-lookback:]
        if len(hist) == lookback:
            realised = hist.std(ddof=1) * np.sqrt(TRADING_DAYS)
            scale.loc[date] = min(1.0, target / realised) if realised > 0 else 1.0
    applied = scale.ffill().shift(1).dropna()
    cash = cash_returns.reindex(applied.index).fillna(0.0)
    base = strategy_returns.reindex(applied.index)
    # Moving d from the strategy to cash trades both legs, as in simulate().
    cost = 2 * applied.diff().abs().fillna(0.0) * cost_bps / 1e4
    return applied * base + (1 - applied) * cash - cost


def metrics(returns: pd.Series, cash: pd.Series) -> dict[str, float | str | int]:
    r = returns.dropna()
    if len(r) < 2:
        return {"days": len(r)}
    excess = r - cash.reindex(r.index).fillna(0.0)
    years = len(r) / TRADING_DAYS
    cagr = float((1 + r).prod() ** (1 / years) - 1)
    mdd = float(max_drawdown(r.to_numpy()))
    return {
        "start": str(r.index[0].date()),
        "end": str(r.index[-1].date()),
        "days": int(len(r)),
        "cagr": cagr,
        "vol": float(r.std(ddof=1) * np.sqrt(TRADING_DAYS)),
        "sharpe": sharpe_ratio(excess.to_numpy(), ppy=TRADING_DAYS),
        "sortino": sortino_ratio(excess.to_numpy(), ppy=TRADING_DAYS),
        "max_drawdown": mdd,
        "calmar": cagr / abs(mdd) if mdd < 0 else float("nan"),
        "skew": float(excess.skew()),
        "kurtosis": float(excess.kurt()),
    }


def _period(series: pd.Series, start: pd.Timestamp | None, end: pd.Timestamp) -> pd.Series:
    s = series.loc[:end]
    return s.loc[start:] if start is not None else s


def run_all(prices: pd.DataFrame, cost_bps: float = COST_BPS) -> dict:
    """Evaluate every strategy plus the vol-target overlay of the validation winner."""
    if prices.index.max() >= LOCKED_START:
        raise ValueError("locked period data reached the evaluator")
    cash = prices["CASH"].pct_change(fill_method=None)
    results: dict[str, dict] = {}
    daily: dict[str, pd.Series] = {}
    for name, fn in STRATEGIES.items():
        weights = target_weights(prices, fn)
        if weights.empty:
            results[name] = {"skipped": "no data for its assets"}
            continue
        rets, turnover = simulate(prices, weights, cost_bps)
        daily[name] = rets
        results[name] = {
            "in_sample": metrics(_period(rets, None, IN_SAMPLE_END), cash),
            "validation": metrics(_period(rets, VALIDATION_START, VALIDATION_END), cash),
            "avg_turnover_per_rebalance": float(turnover.mean()) if len(turnover) else 0.0,
        }
    # The overlay base is chosen on the in-sample period only, so the
    # validation window plays no part in building the extra trial.
    in_sample_ranked = _rank(results, period="in_sample")
    ranked = _rank(results)
    if in_sample_ranked:
        winner = in_sample_ranked[0]
        overlay = vol_target_overlay(daily[winner], cash, cost_bps=cost_bps)
        name = f"vol_target_10__{winner}"
        daily[name] = overlay
        results[name] = {
            "in_sample": metrics(_period(overlay, None, IN_SAMPLE_END), cash),
            "validation": metrics(_period(overlay, VALIDATION_START, VALIDATION_END), cash),
        }
        ranked = _rank(results)
    n_trials = len(ranked)
    trial_sharpes = [results[n]["validation"]["sharpe"] for n in ranked]
    for name in ranked:
        v = results[name]["validation"]
        v["deflated_sharpe"] = deflated_sharpe(
            v["sharpe"], trial_sharpes, n_periods=v["days"],
            skew=v["skew"], kurtosis=v["kurtosis"] + 3.0)
    return {"n_trials": n_trials, "ranking": ranked, "strategies": results,
            "daily_returns": daily}


def deflated_sharpe(sharpe_ann: float, trial_sharpes_ann: list[float], n_periods: int,
                    skew: float, kurtosis: float, ppy: int = TRADING_DAYS) -> float:
    """Bailey & Lopez de Prado (2014) deflated Sharpe ratio.

    The expected maximum Sharpe under the null is scaled by the dispersion of
    the Sharpes actually observed across the trials (eq. 8 of the paper).
    ``kurtosis`` is raw (3 for a normal distribution).
    """
    sr = sharpe_ann / np.sqrt(ppy)
    trials = np.asarray(trial_sharpes_ann, dtype=float) / np.sqrt(ppy)
    n = len(trials)
    if n < 2 or n_periods < 10:
        return float("nan")
    gamma = np.euler_gamma
    e_max = ((1 - gamma) * norm.ppf(1 - 1 / n) + gamma * norm.ppf(1 - 1 / (n * np.e)))
    sr0 = np.sqrt(trials.var(ddof=1)) * e_max
    denom = 1 - skew * sr + (kurtosis - 1) / 4 * sr ** 2
    if denom <= 0:
        return float("nan")
    return float(norm.cdf((sr - sr0) * np.sqrt(n_periods - 1) / np.sqrt(denom)))


def _rank(results: dict[str, dict], period: str = "validation") -> list[str]:
    """Order by the mean of the ``period`` Sharpe rank and Sortino rank."""
    rows = {k: v[period] for k, v in results.items()
            if period in v and "sharpe" in v[period]}
    if not rows:
        return []
    frame = pd.DataFrame(rows).T[["sharpe", "sortino"]].astype(float)
    score = frame.rank(ascending=False).mean(axis=1)
    return list(score.sort_values(kind="stable").index)
