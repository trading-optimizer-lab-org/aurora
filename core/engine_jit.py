"""Numba JIT-accelerated hot paths for QuantForge backtest engine.

Same semantics as core.engine + core.costs + indicator loops in strategies.library,
but with @njit on the inner numerical kernels. Falls back to pure-numpy when
numba is not available so the module is importable in any environment.

Equivalence: results from `run_backtest_jit` must match `run_backtest` to 1e-9
on identical inputs (see tests/test_jit.py).

Hot paths replaced:
- apply_costs_jit          -> replaces costs.apply_costs scalar logic
- compute_sma_jit          -> replaces ma_cross cumsum loop
- compute_rsi_jit          -> replaces rsi_meanrev Wilder loop
- compute_max_min_jit      -> replaces donchian rolling max/min
- compute_realized_vol_jit -> rolling std (used by voltarget wrappers)
"""
from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Callable
import numpy as np
import pandas as pd

_logger = logging.getLogger(__name__)

# numba optional — fall back to pure-numpy decorators if missing
try:
    from numba import njit
    NUMBA_AVAILABLE = True
except ImportError:  # pragma: no cover
    NUMBA_AVAILABLE = False

    def njit(*args, **kwargs):
        """No-op decorator when numba not available. Returns the function unchanged."""
        # support both @njit and @njit(cache=True) usage
        if len(args) == 1 and callable(args[0]) and not kwargs:
            return args[0]

        def deco(fn):
            return fn

        return deco


from aurora.core.costs import CostModel, ZERO_costs
from aurora.core.metrics import compute_metrics


# ---------- pure kernels (njit) ----------------------------------------------


@njit(cache=True)
def apply_costs_jit(weights: np.ndarray, returns: np.ndarray,
                    commission_bps: float, spread_bps: float,
                    slippage_bps: float, borrow_rate_annual: float,
                    slippage_mult: float = 2.0) -> np.ndarray:
    """JIT version of costs.apply_costs.

    Mirrors the formula in costs.py exactly:
        net[1:]      = weights[:-1] * returns[1:]
        delta_w[t]   = |weights[t] - weights[t-1]|  (delta_w[0] = |weights[0]|)
        per_trade_bps = commission_bps + 2*spread_bps + slippage_mult*slippage_bps
        net          -= delta_w * per_trade_bps / 1e4
        net[t]       -= max(-weights[t-1], 0) * borrow_rate_annual / 252
                        (borrow accrues on position carried INTO bar t, not
                        the position established at end of bar t).

    slippage_mult defaults to 2.0 (round-trip with full instant fill, matching
    costs.CostModel.per_trade_bps with partial_fill_factor=1.0). Pass a larger
    value (2.0/factor) to model partial-fill regimes.
    """
    T = weights.shape[0]
    net = np.zeros(T)
    if T < 2:
        return net

    per_trade = (commission_bps + 2.0 * spread_bps + slippage_mult * slippage_bps) / 1e4
    daily_borrow = borrow_rate_annual / 252.0

    # gross strategy return
    for t in range(1, T):
        net[t] = weights[t - 1] * returns[t]

    # turnover-based costs (delta_w with prepend=0)
    prev = 0.0
    for t in range(T):
        dw = weights[t] - prev
        if dw < 0.0:
            dw = -dw
        net[t] -= dw * per_trade
        prev = weights[t]

    # short borrow on position CARRIED INTO each bar (weights[t-1])
    for t in range(1, T):
        w_prev = weights[t - 1]
        if w_prev < 0.0:
            net[t] -= (-w_prev) * daily_borrow

    return net


@njit(cache=True)
def compute_sma_jit(prices: np.ndarray, n: int) -> np.ndarray:
    """Simple moving average via running window sum. NaN for index < n-1."""
    T = prices.shape[0]
    out = np.full(T, np.nan)
    if n <= 0 or T < n:
        return out
    s = 0.0
    for i in range(n):
        s += prices[i]
    out[n - 1] = s / n
    for i in range(n, T):
        s += prices[i] - prices[i - n]
        out[i] = s / n
    return out


@njit(cache=True)
def compute_rsi_jit(prices: np.ndarray, n: int) -> np.ndarray:
    """Wilder RSI. Matches rsi_meanrev._rsi semantics:
       - first n diffs seed the average gain/loss (simple mean)
       - subsequent updates use the Wilder smoothing using diff[i-1]
       - rsi[i] for i >= n; nan otherwise
       - if avg_loss == 0, rsi = 100.0
    """
    T = prices.shape[0]
    rsi = np.full(T, np.nan)
    if n <= 0:
        return rsi
    if T < n + 1:
        return rsi

    # diffs of length T-1; diff[k] = prices[k+1] - prices[k]
    # seed: mean of first n diffs (k=0..n-1)
    sum_g = 0.0
    sum_l = 0.0
    for k in range(n):
        d = prices[k + 1] - prices[k]
        if d > 0.0:
            sum_g += d
        elif d < 0.0:
            sum_l += -d
    ag = sum_g / n
    al = sum_l / n

    for i in range(n, T):
        if i > n:
            d_prev = prices[i] - prices[i - 1]  # diff[i-1]
            g_prev = d_prev if d_prev > 0.0 else 0.0
            l_prev = -d_prev if d_prev < 0.0 else 0.0
            ag = (ag * (n - 1) + g_prev) / n
            al = (al * (n - 1) + l_prev) / n
        if al == 0.0:
            rsi[i] = 100.0
        else:
            rsi[i] = 100.0 - 100.0 / (1.0 + ag / al)
    return rsi


@njit(cache=True)
def compute_max_min_jit(prices: np.ndarray, n: int):
    """Trailing max and min over a window of size n strictly preceding index i.
       i.e. roll_max[i] = max(prices[i-n:i]), defined for i >= n; NaN otherwise.
       Matches the slicing donchian.py uses.
    """
    T = prices.shape[0]
    roll_max = np.full(T, np.nan)
    roll_min = np.full(T, np.nan)
    if n <= 0 or T <= n:
        return roll_max, roll_min
    for i in range(n, T):
        mx = prices[i - n]
        mn = prices[i - n]
        for k in range(i - n + 1, i):
            v = prices[k]
            if v > mx:
                mx = v
            if v < mn:
                mn = v
        roll_max[i] = mx
        roll_min[i] = mn
    return roll_max, roll_min


@njit(cache=True)
def compute_realized_vol_jit(returns: np.ndarray, window: int) -> np.ndarray:
    """Rolling standard deviation (population, ddof=0) with NaN for i < window-1.
       Used by voltarget wrappers.

       Uses ddof=0 (population std), matching pandas.rolling().std(ddof=0).
       For sample std (ddof=1), multiply result by sqrt(n/(n-1)).
    """
    T = returns.shape[0]
    out = np.full(T, np.nan)
    if window <= 1 or T < window:
        return out
    # initial sums
    s = 0.0
    s2 = 0.0
    for k in range(window):
        v = returns[k]
        s += v
        s2 += v * v
    mean = s / window
    var = s2 / window - mean * mean
    if var < 0.0:
        var = 0.0
    out[window - 1] = np.sqrt(var)
    for i in range(window, T):
        old = returns[i - window]
        new = returns[i]
        s += new - old
        s2 += new * new - old * old
        mean = s / window
        var = s2 / window - mean * mean
        if var < 0.0:
            var = 0.0
        out[i] = np.sqrt(var)
    return out


# ---------- numpy fallbacks (used when numba unavailable or as reference) -----


def apply_costs_np(weights, returns, costs: CostModel) -> np.ndarray:
    """Pure-numpy reference (same as costs.apply_costs).

    Borrow charge applies to the position CARRIED INTO each bar
    (i.e. weights[t-1]) so it stays consistent with the gross
    return formula net[1:] = weights[:-1] * returns[1:].
    """
    weights = np.asarray(weights, dtype=float)
    returns = np.asarray(returns, dtype=float)
    T = len(weights)
    net = np.zeros(T)
    if T < 2:
        return net
    net[1:] = weights[:-1] * returns[1:]
    delta_w = np.abs(np.diff(weights, prepend=0.0))
    net = net - delta_w * (costs.per_trade_bps() / 1e4)
    short_carried = np.zeros(T)
    short_carried[1:] = np.abs(np.minimum(weights[:-1], 0.0))
    net = net - short_carried * (costs.borrow_rate_annual / 252.0)
    return net


# ---------- public wrappers ---------------------------------------------------


def apply_costs_fast(weights, returns, costs: CostModel,
                     slippage_mult: float = 2.0) -> np.ndarray:
    """Fast cost-application wrapper. Routes to JIT when available, else numpy.

    slippage_mult defaults to 2.0 (full instant fill). Caller can pass
    2.0/partial_fill_factor to inflate slippage for partial-fill regimes
    (matches costs.CostModel.per_trade_bps).
    """
    if NUMBA_AVAILABLE:
        w = np.ascontiguousarray(np.asarray(weights, dtype=np.float64))
        r = np.ascontiguousarray(np.asarray(returns, dtype=np.float64))
        return apply_costs_jit(
            w, r,
            float(costs.commission_bps), float(costs.spread_bps),
            float(costs.slippage_bps), float(costs.borrow_rate_annual),
            float(slippage_mult),
        )
    return apply_costs_np(weights, returns, costs)


def sma_fast(prices, n: int) -> np.ndarray:
    p = np.ascontiguousarray(np.asarray(prices, dtype=np.float64))
    return compute_sma_jit(p, int(n))


def rsi_fast(prices, n: int) -> np.ndarray:
    p = np.ascontiguousarray(np.asarray(prices, dtype=np.float64))
    return compute_rsi_jit(p, int(n))


def max_min_fast(prices, n: int):
    p = np.ascontiguousarray(np.asarray(prices, dtype=np.float64))
    return compute_max_min_jit(p, int(n))


def realized_vol_fast(returns, window: int) -> np.ndarray:
    r = np.ascontiguousarray(np.asarray(returns, dtype=np.float64))
    return compute_realized_vol_jit(r, int(window))


# ---------- backtest entrypoint ----------------------------------------------


@dataclass
class BacktestResultJit:
    metrics: object
    nav: np.ndarray
    rets: np.ndarray
    weights: np.ndarray
    timestamps: np.ndarray
    slippage_rejections: int = 0  # count of orders rejected by the slippage model

    @property
    def calmar(self): return self.metrics.calmar
    @property
    def sharpe(self): return self.metrics.sharpe
    @property
    def cagr(self): return self.metrics.cagr
    @property
    def mdd(self): return self.metrics.mdd


def run_backtest_jit(prices, signal_fn: Callable, costs: CostModel = ZERO_costs,
                     ppy: int = 252,
                     slippage_model=None,
                     daily_volume=None,
                     portfolio_value: float = 1.0,
                     partial_fill_factor: float = 1.0,
                     **strategy_kwargs) -> BacktestResultJit:
    """JIT-accelerated backtest entrypoint. Mirrors core.engine.run_backtest
    but routes the cost/return loop through apply_costs_jit when available.

    When ``slippage_model`` is provided, falls back to the non-JIT
    ``run_backtest`` path so size-dependent slippage logic stays consistent
    with the canonical engine. The result is repacked into ``BacktestResultJit``
    so callers see a uniform return type.

    ``partial_fill_factor`` (default 1.0) inflates the slippage component for
    partial-fill regimes (forwarded to ``apply_costs_fast`` as
    ``slippage_mult=2.0/factor``).
    """
    if not isinstance(prices, pd.Series):
        raise TypeError("prices must be pd.Series with DatetimeIndex")
    if not isinstance(prices.index, pd.DatetimeIndex):
        raise TypeError("prices index must be DatetimeIndex")

    # Slippage model path: delegate to engine.run_backtest to avoid duplicating
    # the size-dependent slippage logic. Repackage the result.
    if slippage_model is not None:
        from aurora.core.engine import run_backtest
        res = run_backtest(
            prices, signal_fn, costs=costs, ppy=ppy,
            slippage_model=slippage_model,
            daily_volume=daily_volume,
            portfolio_value=portfolio_value,
            partial_fill_factor=partial_fill_factor,
            **strategy_kwargs,
        )
        return BacktestResultJit(
            metrics=res.metrics,
            nav=res.nav,
            rets=res.rets,
            weights=res.weights,
            timestamps=res.timestamps,
            slippage_rejections=res.slippage_rejections,
        )

    p = prices.values.astype(float)
    weights = np.asarray(signal_fn(prices, **strategy_kwargs), dtype=float)
    if len(weights) != len(p):
        raise ValueError(f"signal length {len(weights)} != prices length {len(p)}")
    # NaN-aware validation BEFORE the magnitude check; otherwise np.abs(NaN)
    # silently passes the |w| <= 1 filter and poisons the cost loop.
    if not np.all(np.isfinite(weights)):
        raise ValueError("non-finite weights")
    if np.any(np.abs(weights) > 1.0 + 1e-9):
        raise ValueError(
            f"signal weights must be in [-1, 1], got max abs {np.abs(weights).max()}"
        )
    # Match engine.py: clip to exact [-1, 1] so downstream consumers see no
    # 1e-9 overflow leakage. Mirrors the validation+clip pattern in engine.py.
    weights = np.clip(weights, -1.0, 1.0)

    asset_rets = np.zeros(len(p))
    asset_rets[1:] = p[1:] / p[:-1] - 1.0

    net_rets = apply_costs_fast(weights, asset_rets, costs,
                                slippage_mult=2.0 / max(partial_fill_factor, 1e-3))
    # Zero out first-bar return BEFORE cumprod so nav[0] is exactly 1.0.
    # apply_costs_jit legitimately charges bar-0 turnover even though there's no
    # carried position, so net_rets[0] is typically non-zero. Silent zeroing.
    if len(net_rets) > 0 and net_rets[0] != 0.0:
        net_rets = net_rets.copy()
        net_rets[0] = 0.0
    nav = np.cumprod(1.0 + net_rets)

    metrics = compute_metrics(net_rets[1:], ppy=ppy)
    return BacktestResultJit(
        metrics=metrics,
        nav=nav,
        rets=net_rets,
        weights=weights,
        timestamps=prices.index.values,
        slippage_rejections=0,
    )
