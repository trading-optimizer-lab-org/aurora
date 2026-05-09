"""Backtest core engine.

Runs Strategy.signals() output through cost model, returns Metrics + NAV.
Numba-accelerated where possible.

CRITICAL: signal at bar i applies to return of bar i+1. Anti-lookahead enforced
at engine level by shifting signals forward in apply_costs().
"""
from __future__ import annotations
import logging
import warnings
from dataclasses import dataclass
from typing import Callable, Optional
import numpy as np
import pandas as pd

from aurora.core.costs import CostModel, ZERO_costs, apply_costs
from aurora.core.metrics import Metrics, compute_metrics
from aurora.core.slippage import SlippageModel

_logger = logging.getLogger(__name__)

# R46: one-shot warning so an operator does not silently backtest under
# unrealistic ZERO_costs and then run live with the same expectations.
_ZERO_COSTS_WARNED = False


def _maybe_warn_zero_costs(costs: CostModel,
                           acknowledge_zero_costs: bool) -> None:
    """Emit a one-shot UserWarning when ZERO_costs is the active cost model.

    Suppressed when:
    - ``acknowledge_zero_costs=True`` is passed explicitly (caller knows).
    - The active cost model is anything other than the singleton
      ``ZERO_costs`` (e.g. a custom CostModel with all zeros still
      warns -- see below).

    The check uses identity (``is``) against the canonical ``ZERO_costs``
    singleton AND a value check on every component, so a user who builds
    ``CostModel()`` from scratch (all defaults zero) ALSO trips the
    warning. The intent is "you have no costs in this run", not "you
    used the literal ZERO_costs name".
    """
    global _ZERO_COSTS_WARNED
    if acknowledge_zero_costs or _ZERO_COSTS_WARNED:
        return
    is_zero = (
        costs is ZERO_costs
        or (
            costs.commission_bps == 0.0
            and costs.spread_bps == 0.0
            and costs.slippage_bps == 0.0
            and costs.borrow_rate_annual == 0.0
            and costs.min_commission_usd == 0.0
            and costs.fixed_per_trade_usd == 0.0
        )
    )
    if not is_zero:
        return
    _ZERO_COSTS_WARNED = True
    warnings.warn(
        "run_backtest invoked with a zero-cost model. Backtest results "
        "will be unrealistically optimistic. Pass a real CostModel for "
        "any decision that influences live trading, or pass "
        "acknowledge_zero_costs=True to suppress this warning. "
        "(R46: one-shot per process.)",
        UserWarning,
        stacklevel=3,
    )


@dataclass
class BacktestResult:
    metrics: Metrics
    nav: np.ndarray
    rets: np.ndarray
    weights: np.ndarray
    timestamps: np.ndarray  # datetime index as np.datetime64
    slippage_rejections: int = 0  # count of orders rejected by the slippage model

    @property
    def calmar(self): return self.metrics.calmar
    @property
    def sharpe(self): return self.metrics.sharpe
    @property
    def cagr(self): return self.metrics.cagr
    @property
    def mdd(self): return self.metrics.mdd


def run_backtest(prices, signal_fn: Callable, costs: CostModel = ZERO_costs,
                 ppy: int = 252, slippage_model: Optional[SlippageModel] = None,
                 daily_volume: Optional[float] = None,
                 portfolio_value: float = 1.0,
                 partial_fill_factor: float = 1.0,
                 acknowledge_zero_costs: bool = False,
                 **strategy_kwargs) -> BacktestResult:
    """Run a single-asset backtest.

    Args:
        prices: pd.Series of prices (close), DatetimeIndex
        signal_fn: callable signal_fn(prices, **kwargs) -> np.array of weights in [-1, 1]
                   MUST not look ahead (only use prices[:i+1] when computing signal[i])
        costs: CostModel
        ppy: periods/year (252 daily, 12 monthly, etc.)
        slippage_model: optional size-dependent slippage on top of costs.slippage_bps.
                        Charges extra bps per turnover event using order_size = |dW| *
                        portfolio_value and the supplied daily_volume (dollars).
                        Orders rejected by the model (NaN impact) fall back to no extra.
        daily_volume: synthetic ADV in dollars used for slippage calc. Required if
                      slippage_model is provided.
        portfolio_value: notional NAV used to translate weight delta into dollars
                         (default 1.0 -> turnover treated as fraction of NAV).
        partial_fill_factor: forwarded to ``apply_costs``. Default 1.0 (full
                             instant fill). Lower values inflate the slippage
                             component for partial-fill regimes.
        **strategy_kwargs: passed to signal_fn

    Returns:
        BacktestResult with metrics + arrays
    """
    if not isinstance(prices, pd.Series):
        raise TypeError("prices must be pd.Series with DatetimeIndex")
    if not isinstance(prices.index, pd.DatetimeIndex):
        raise TypeError("prices index must be DatetimeIndex")
    if slippage_model is not None and (daily_volume is None or daily_volume <= 0):
        raise ValueError("slippage_model requires positive daily_volume")

    _maybe_warn_zero_costs(costs, acknowledge_zero_costs)

    p = prices.values.astype(float)
    weights = np.asarray(signal_fn(prices, **strategy_kwargs), dtype=float)
    if len(weights) != len(p):
        raise ValueError(f"signal length {len(weights)} != prices length {len(p)}")

    # NaN-aware validation BEFORE the magnitude check; otherwise np.abs(NaN)
    # silently passes the |w| <= 1 filter and poisons the cost loop.
    if not np.all(np.isfinite(weights)):
        raise ValueError("non-finite weights")
    # Validate weights bounds with a small tolerance for floating-point round-off,
    # then CLIP to exact [-1, 1] so all downstream consumers see weights that
    # satisfy |w| <= 1 exactly (no 1e-9 overflow leaking through).
    if np.any(np.abs(weights) > 1.0 + 1e-9):
        raise ValueError(f"signal weights must be in [-1, 1], got max abs {np.abs(weights).max()}")
    weights = np.clip(weights, -1.0, 1.0)

    # asset returns
    asset_rets = np.zeros(len(p))
    asset_rets[1:] = p[1:] / p[:-1] - 1.0

    # apply constant-bps costs first (handles weight shift internally)
    net_rets = apply_costs(weights, asset_rets, costs,
                           partial_fill_factor=partial_fill_factor)

    # size-dependent slippage: per-bar extra bps proportional to |delta_w|.
    # Pass time_of_day as a fraction in [0, 1] across the day for slippage
    # models that accept it (e.g. VolumeShareSlippage). Models that do not
    # accept the kwarg are called without it.
    rejections = 0
    if slippage_model is not None:
        assert daily_volume is not None
        adv = float(daily_volume)
        delta_w = np.abs(np.diff(weights, prepend=0.0))
        extra = np.zeros(len(weights))
        ts_index = prices.index
        for i in range(len(weights)):
            dw = float(delta_w[i])
            if dw <= 0.0:
                continue
            order_dollars = dw * float(portfolio_value)
            ts_i = ts_index[i]
            tod = float(ts_i.hour * 3600 + ts_i.minute * 60 + ts_i.second) / 86400.0
            try:
                try:
                    bps = slippage_model.impact_bps(
                        order_dollars, adv, time_of_day=tod,
                    )
                except TypeError:
                    # Model does not accept time_of_day; fall back to positional call.
                    bps = slippage_model.impact_bps(order_dollars, adv)
            except (ValueError, ArithmeticError, OverflowError) as exc:
                rejections += 1
                _logger.warning(
                    "slippage rejection at bar %d (dw=%.4f, $%.2f): %s; using base price",
                    i, dw, order_dollars, exc,
                )
                _logger.debug("slippage rejection traceback", exc_info=True)
                continue
            if bps is None or (isinstance(bps, float) and bps != bps):
                # None or NaN -> reject; track + warn but keep base price
                rejections += 1
                _logger.warning(
                    "slippage rejection at bar %d (dw=%.4f, $%.2f): model returned %s; using base price",
                    i, dw, order_dollars, bps,
                )
                continue
            extra[i] = dw * (bps / 1e4)
        net_rets = net_rets - extra

    # Zero out first-bar return BEFORE cumprod so nav[0] is exactly 1.0.
    # apply_costs legitimately charges bar-0 turnover (= |weights[0]| * per_trade_bps)
    # even though there's no carried position, so net_rets[0] is typically non-zero.
    # Silent zeroing (mirrors engine_multi.py:282) — no warning.
    if len(net_rets) > 0 and net_rets[0] != 0.0:
        net_rets = net_rets.copy()
        net_rets[0] = 0.0
    nav = np.cumprod(1.0 + net_rets)

    metrics = compute_metrics(net_rets[1:], ppy=ppy)
    return BacktestResult(
        metrics=metrics,
        nav=nav,
        rets=net_rets,
        weights=weights,
        timestamps=prices.index.values,
        slippage_rejections=rejections,
    )


def run_backtest_window(prices, signal_fn, start, end, costs=ZERO_costs, ppy=252, **kw):
    """Backtest restricted to date range.

    Slices ``prices`` to ``[start, end]`` FIRST, then calls ``signal_fn`` on the
    slice (so the signal has no visibility into bars outside the window). This
    is the correct OOS isolation behavior for walk-forward and lockbox runs:
    every bar before ``start`` and after ``end`` is invisible to the strategy.

    Note: warm-up indicators (e.g. SMA(252)) computed inside ``signal_fn`` will
    spend the first lookback bars producing NaN/zero weights since they cannot
    see history before ``start``. Callers needing pre-window warm-up must
    extend ``start`` accordingly.
    """
    sub = prices[(prices.index >= pd.Timestamp(start)) & (prices.index <= pd.Timestamp(end))]
    return run_backtest(sub, signal_fn, costs=costs, ppy=ppy, **kw)


def run_multi_asset(price_dict, weight_fn, costs_dict=None, ppy=252,
                    partial_fill_factor: float = 1.0):
    """Multi-asset backtest. Strategy returns dict[symbol] -> weight series.

    Args:
        price_dict: dict[symbol] -> pd.Series of prices
        weight_fn: callable(price_dict) -> dict[symbol] -> np.array weights
        costs_dict: dict[symbol] -> CostModel (default ZERO for missing)
        partial_fill_factor: forwarded to ``apply_costs`` for each symbol.
                             Default 1.0 (full instant fill).

    Returns:
        BacktestResult. Note that ``weights`` here has shape (T, N) where
        N is the number of symbols and T is the number of common bars
        (column-stacked along axis=1 per symbol order in ``price_dict``).
        Single-asset runs return weights shape (T,). The stacked layout
        keeps row alignment with ``timestamps``/``rets``/``nav``.
        ``slippage_rejections`` is always 0 on this path: size-dependent
        slippage is not applied per-symbol; pass a ``slippage_model`` only
        through ``run_backtest`` if you need it.
    """
    weights = weight_fn(price_dict)
    syms = list(price_dict.keys())
    # align all to common index
    common_idx = None
    for s in syms:
        idx = price_dict[s].index
        common_idx = idx if common_idx is None else common_idx.intersection(idx)
    if common_idx is None:
        raise ValueError("price_dict must contain at least one symbol")
    if len(common_idx) < 20:
        raise ValueError(f"insufficient overlapping bars: {len(common_idx)}")

    rets_per_sym = {}
    aligned_weights = {}
    for s in syms:
        p = price_dict[s].reindex(common_idx).values.astype(float)
        ar = np.zeros(len(p)); ar[1:] = p[1:] / p[:-1] - 1.0
        # Reindex weights to align with common_idx (mirrors MultiAssetEngine._align).
        w_arr = np.asarray(weights[s]).astype(float)
        w_full = pd.Series(w_arr, index=price_dict[s].index)
        w = w_full.reindex(common_idx).fillna(0.0).values
        aligned_weights[s] = w
        c = (costs_dict or {}).get(s, ZERO_costs)
        rets_per_sym[s] = apply_costs(w, ar, c,
                                      partial_fill_factor=partial_fill_factor)

    # equal-weight aggregation across symbols (caller responsibility to size)
    net = np.zeros(len(common_idx))
    for s in syms:
        net += rets_per_sym[s]
    # if total |weight| > 1 across symbols, scale down (gross leverage cap = 1)
    # Note: assumes weights sum properly; caller can pass leverage logic in weight_fn

    if len(net) > 0 and net[0] != 0.0:
        _logger.warning(
            "run_multi_asset net[0]=%.6e is non-zero; zeroing to avoid first-bar PnL leak",
            net[0],
        )
        net = net.copy()
        net[0] = 0.0
    nav = np.cumprod(1.0 + net)
    metrics = compute_metrics(net[1:], ppy=ppy)
    # Stack weights as (T, N) along axis=1 so row index aligns with timestamps,
    # rets, and nav. Single-asset run_backtest returns shape (T,). Use the
    # weights already reindexed to common_idx so shape always matches T.
    weights_stacked = np.column_stack([aligned_weights[s] for s in syms])
    return BacktestResult(metrics, nav, net, weights_stacked,
                         common_idx.values, slippage_rejections=0)
