"""Internal numpy/pandas vectorized triage backend.

This is the *default* backend the :class:`~quantforge.triage.engine.TriageEngine`
falls back to when ``vectorbt`` is unavailable. It pre-computes signals
per variant in batch via numpy broadcasting and then computes returns
under a flat-bps cost model.

Triage cost model
-----------------
Triage uses a *deliberately simplified* cost model: a flat ``cost_bps``
charge per turnover unit and a flat ``slippage_bps`` charge per
turnover unit, both deducted from the gross return. This is NOT the
official engine's cost model. It exists to give triage a fast,
reproducible PnL signal that correlates well with the official engine's
metrics on the same window. Anything that survives triage MUST be re-run
on :func:`quantforge.core.engine.run_backtest` for promotion.

The math
--------
For a single asset with weights ``w[t]`` in [-1, 1] and per-bar returns
``r[t]``:

    gross[t] = w[t-1] * r[t]                                   (anti-lookahead shift)
    turnover[t] = abs(w[t] - w[t-1])
    cost[t] = (cost_bps + slippage_bps) * 1e-4 * turnover[t]
    net[t] = gross[t] - cost[t]

For a multi-asset universe, the same formula is applied independently
per asset and then *averaged* across assets to produce a portfolio
return. Triage does not solve a constrained portfolio optimization; it
gives every asset equal weight at the strategy's chosen sign.
"""
from __future__ import annotations

from typing import Iterable, Sequence

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Strategy importer (lightweight; no factory dependency)
# ---------------------------------------------------------------------------


def _import_strategy(qualified: str):
    """Import a fully-qualified ``pkg.mod.Class`` path."""
    if "." not in qualified:
        raise ImportError(
            f"strategy_class={qualified!r} is not a fully-qualified path"
        )
    import importlib
    mod_path, _, attr = qualified.rpartition(".")
    mod = importlib.import_module(mod_path)
    if not hasattr(mod, attr):
        raise ImportError(f"{mod_path} has no attribute {attr!r}")
    return getattr(mod, attr)


# ---------------------------------------------------------------------------
# Signal computation
# ---------------------------------------------------------------------------


def compute_signals_batch(
    prices: pd.DataFrame,
    variants: Sequence,  # Sequence[StrategyVariant]
) -> np.ndarray:
    """Compute signals for each variant against every column of ``prices``.

    The strategy class itself is invoked per variant in a Python loop --
    instantiating arbitrary strategy classes cannot be vectorized
    safely. The pnl/metric stages (where most cycles are spent for large
    batches) ARE vectorized below.

    Args:
        prices: DataFrame with a DatetimeIndex and one or more asset
            columns. Each variant's strategy is invoked once per asset
            column.
        variants: sequence of :class:`~quantforge.triage.variants.StrategyVariant`.

    Returns:
        ``np.ndarray`` of shape ``(n_variants, n_time, n_assets)`` and
        dtype ``float64``. Values lie in ``[-1, 1]``; warm-up bars
        (NaN signals) are coerced to 0.
    """
    if not isinstance(prices, pd.DataFrame):
        raise TypeError("prices must be a pd.DataFrame with a DatetimeIndex")
    if not isinstance(prices.index, pd.DatetimeIndex):
        raise TypeError("prices.index must be a DatetimeIndex")

    n_time, n_assets = prices.shape
    n_var = len(variants)
    out = np.zeros((n_var, n_time, n_assets), dtype=np.float64)
    if n_var == 0 or n_time == 0 or n_assets == 0:
        return out

    asset_cols = list(prices.columns)
    for vi, variant in enumerate(variants):
        cls = _import_strategy(variant.strategy_class)
        # Tolerate strategy ctors that reject unknown kwargs by passing
        # only the params we have. Raising here is a hard fail -- the
        # variant is malformed.
        strat = cls(**dict(variant.params or {}))
        for ai, col in enumerate(asset_cols):
            ser = prices[col].astype(float)
            sig = np.asarray(strat.signals(ser), dtype=np.float64)
            if sig.shape[0] != n_time:
                raise ValueError(
                    f"strategy {variant.strategy_class} returned {sig.shape[0]} "
                    f"signals for {n_time} bars on {col!r}"
                )
            # Coerce NaN -> 0 and clip to [-1, 1] so the downstream pnl
            # computation cannot overflow the cost model.
            sig = np.where(np.isfinite(sig), sig, 0.0)
            np.clip(sig, -1.0, 1.0, out=sig)
            out[vi, :, ai] = sig
    return out


# ---------------------------------------------------------------------------
# PnL computation
# ---------------------------------------------------------------------------


def compute_pnl_batch(
    prices: pd.DataFrame,
    signals: np.ndarray,
    *,
    cost_bps: float = 5.0,
    slippage_bps: float = 1.0,
) -> np.ndarray:
    """Compute per-variant net portfolio returns under a flat cost model.

    Args:
        prices: same DataFrame used for :func:`compute_signals_batch`.
        signals: ``(n_variants, n_time, n_assets)`` array as returned by
            :func:`compute_signals_batch`.
        cost_bps: flat round-trip cost in basis points per unit turnover.
        slippage_bps: flat slippage in basis points per unit turnover.

    Returns:
        ``np.ndarray`` of shape ``(n_variants, n_time)``; entry ``[v, t]``
        is the net portfolio return for variant ``v`` on bar ``t``.
        ``returns[v, 0]`` is always ``0.0`` (no PnL on the first bar).
    """
    if signals.ndim != 3:
        raise ValueError(
            f"signals must have shape (n_variants, n_time, n_assets); "
            f"got {signals.shape}"
        )
    n_var, n_time, n_assets = signals.shape
    if n_time == 0 or n_assets == 0:
        return np.zeros((n_var, n_time), dtype=np.float64)

    p = prices.values.astype(np.float64)
    if p.shape != (n_time, n_assets):
        raise ValueError(
            f"prices shape {p.shape} != signals time/asset dims "
            f"({n_time}, {n_assets})"
        )

    # Per-asset returns (n_time, n_assets); first bar 0.
    asset_rets = np.zeros_like(p)
    asset_rets[1:] = p[1:] / p[:-1] - 1.0
    # Anti-lookahead: signal at bar t-1 applies to return of bar t.
    # Construct shifted signals; first bar treated as 0 weight for everyone.
    shifted = np.zeros_like(signals)
    shifted[:, 1:, :] = signals[:, :-1, :]

    gross = shifted * asset_rets[None, :, :]                          # (V, T, A)

    # Turnover per variant per bar: |w[t] - w[t-1]| summed over assets.
    diff = np.zeros_like(signals)
    diff[:, 1:, :] = np.abs(signals[:, 1:, :] - signals[:, :-1, :])
    turnover = diff.sum(axis=2)                                       # (V, T)
    cost_rate = (float(cost_bps) + float(slippage_bps)) * 1e-4
    cost = cost_rate * turnover                                       # (V, T)

    # Average across assets (equal-weight portfolio under triage's
    # simplifying assumption). For a single-asset universe this is a
    # no-op divide-by-1.
    portfolio_gross = gross.mean(axis=2)                              # (V, T)
    return portfolio_gross - cost


# ---------------------------------------------------------------------------
# Metric batch
# ---------------------------------------------------------------------------


def _per_variant_metrics(
    rets: np.ndarray,
    *,
    ppy: int = 252,
) -> dict:
    """Return scalar metrics for a single variant's per-bar returns.

    The triage metric set is a deliberate subset of the official engine's
    metrics: sharpe, cagr, max-drawdown, n_trades, win_rate. Anything
    finer (sortino, deflated sharpe, profit factor, ...) is left to the
    official engine.
    """
    r = np.asarray(rets, dtype=np.float64)
    finite = r[np.isfinite(r)]
    if finite.size < 2:
        return {
            "sharpe": float("nan"),
            "cagr": float("nan"),
            "max_dd": float("nan"),
            "n_trades": 0,
            "win_rate": float("nan"),
        }

    nav = np.cumprod(1.0 + finite)
    final = float(nav[-1])
    years = max(finite.size / float(ppy), 1.0 / float(ppy))
    if final > 0:
        cagr = float(final ** (1.0 / years)) - 1.0
    elif final <= 0:
        cagr = -1.0
    else:
        cagr = 0.0

    cummax = np.maximum.accumulate(nav)
    dd = (nav - cummax) / cummax
    max_dd = float(dd.min()) if dd.size else 0.0

    std = float(finite.std(ddof=0))
    mean = float(finite.mean())
    if std > 0:
        sharpe = (mean / std) * np.sqrt(float(ppy))
    else:
        sharpe = 0.0

    # n_trades counted as nonzero return bars (a proxy; the official
    # engine counts position changes). The triage threshold is conservative
    # (default min_trades=30) so the proxy is good enough for screening.
    n_trades = int(np.sum(np.abs(finite) > 1e-9))
    win_rate = float(np.mean(finite > 0)) if finite.size else 0.0

    return {
        "sharpe": float(sharpe),
        "cagr": float(cagr),
        "max_dd": float(max_dd),
        "n_trades": int(n_trades),
        "win_rate": float(win_rate),
    }


def compute_metrics_batch(
    rets: np.ndarray,
    *,
    ppy: int = 252,
) -> list[dict]:
    """Return a list[dict] of triage metrics, one entry per variant.

    Args:
        rets: ``(n_variants, n_time)`` per-variant returns from
            :func:`compute_pnl_batch`.
        ppy: periods per year for annualization.

    Returns:
        List of length ``n_variants``, each a dict with the keys
        ``sharpe``, ``cagr``, ``max_dd``, ``n_trades``, ``win_rate``.
    """
    if rets.ndim == 1:
        rets = rets[None, :]
    return [_per_variant_metrics(rets[v], ppy=ppy) for v in range(rets.shape[0])]


__all__ = [
    "compute_signals_batch",
    "compute_pnl_batch",
    "compute_metrics_batch",
]
