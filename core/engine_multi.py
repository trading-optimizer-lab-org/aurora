"""Multi-asset native engine.

Portfolio backtest over dict[symbol -> prices] + dict[symbol -> weights].
Per-asset CostModel, gross/net leverage caps, attribution, cross-asset correlations.

CRITICAL: signal at bar i applies to return of bar i+1 (same convention as engine.py).
Anti-lookahead enforced inside apply_costs() via weights[:-1] * returns[1:] shift.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import numpy as np
import pandas as pd

from aurora.core.costs import CostModel, ZERO_costs, apply_costs
from aurora.core.metrics import Metrics, compute_metrics


@dataclass
class MultiAssetResult:
    """Result of a multi-asset portfolio backtest."""
    metrics: Metrics                              # portfolio-level metrics
    nav: np.ndarray                               # portfolio NAV (T,)
    rets: np.ndarray                              # portfolio net returns (T,)
    weights: np.ndarray                           # rescaled weights matrix (T, N)
    raw_weights: np.ndarray                       # original input weights (T, N)
    symbols: list                                 # ordered list of symbols
    timestamps: np.ndarray                        # common DatetimeIndex as np.datetime64
    per_asset_attribution: dict                   # symbol -> total contribution to portfolio return
    per_asset_rets: dict                          # symbol -> per-bar net contribution series
    correlation_matrix: pd.DataFrame              # NxN correlation of asset raw returns
    gross_leverage: np.ndarray                    # sum |w| per bar after rescale
    net_leverage: np.ndarray                      # sum w per bar after rescale
    rescale_factor: np.ndarray                    # per-bar scaling applied (1.0 = none)

    @property
    def calmar(self): return self.metrics.calmar
    @property
    def sharpe(self): return self.metrics.sharpe
    @property
    def cagr(self): return self.metrics.cagr
    @property
    def mdd(self): return self.metrics.mdd


class MultiAssetEngine:
    """Portfolio backtest. Per-asset weights, gross/net leverage caps, attribution.

    Conventions:
    - signals shifted i-1 -> i inside apply_costs() (anti-lookahead)
    - gross leverage cap applied per-bar; if sum(|w|) > cap, all weights rescaled
    - net leverage cap applied per-bar; if |sum(w)| > cap, weights rescaled
    - both caps applied; the tighter rescale wins (min factor)
    - per-asset CostModel applied independently after rescale

    Weight bounds:
        Individual weight values must be in [-1, 1] BEFORE leverage rescaling.
        These per-asset weights are PRE-LEVERAGE-CAP signal magnitudes, not final
        positions. The gross/net leverage caps are applied across all assets and
        may rescale all weights uniformly (see _apply_leverage_caps()).
    """

    def __init__(
        self,
        gross_leverage_cap: float = 1.0,
        net_leverage_cap: float = 2.0,
        align_calendar: str = "intersection",
    ):
        if gross_leverage_cap <= 0:
            raise ValueError(f"gross_leverage_cap must be > 0, got {gross_leverage_cap}")
        if net_leverage_cap <= 0:
            raise ValueError(f"net_leverage_cap must be > 0, got {net_leverage_cap}")
        if align_calendar not in ("intersection", "union_ffill", "us_equity"):
            raise ValueError(
                f"align_calendar must be 'intersection', 'union_ffill', or "
                f"'us_equity'; got {align_calendar!r}"
            )
        self.gross_leverage_cap = float(gross_leverage_cap)
        self.net_leverage_cap = float(net_leverage_cap)
        self.align_calendar = align_calendar

    def _align(self, price_dict: dict, weight_dict: dict) -> tuple:
        """Align all symbols to a common DatetimeIndex.

        The ``align_calendar`` setting on the engine controls the alignment
        policy:

        - ``'intersection'`` (default): keep only bars present in every
          symbol's price index. Original behavior. Risks losing weekends or
          holidays for mixed equity + crypto universes.
        - ``'union_ffill'``: build the union of all indices and forward-fill
          missing prices/weights per asset. Recommended when combining 24/7
          markets (crypto) with US equities so weekend bars are preserved.
        - ``'us_equity'``: use NYSE trading days from
          ``pandas_market_calendars`` if installed, else fall back to
          intersection. Restricts to the equity calendar regardless of feed.
        """
        if not price_dict:
            raise ValueError("price_dict empty")
        if set(price_dict.keys()) != set(weight_dict.keys()):
            raise ValueError(
                f"price_dict keys {set(price_dict.keys())} != "
                f"weight_dict keys {set(weight_dict.keys())}"
            )
        symbols = sorted(price_dict.keys())

        # validate index types up-front
        for s in symbols:
            ps = price_dict[s]
            if not isinstance(ps, pd.Series):
                raise TypeError(f"price_dict[{s}] must be pd.Series")
            if not isinstance(ps.index, pd.DatetimeIndex):
                raise TypeError(f"price_dict[{s}].index must be DatetimeIndex")

        common_idx = self._build_common_index(symbols, price_dict)

        if common_idx is None or len(common_idx) < 20:
            raise ValueError(
                f"insufficient overlapping bars: {0 if common_idx is None else len(common_idx)}"
            )

        T = len(common_idx)
        N = len(symbols)
        prices_mat = np.zeros((T, N), dtype=float)
        weights_mat = np.zeros((T, N), dtype=float)

        for j, s in enumerate(symbols):
            p_series = price_dict[s].reindex(common_idx)
            if self.align_calendar == "union_ffill":
                p_series = p_series.ffill()
            p_aligned = p_series.values.astype(float)
            if np.any(np.isnan(p_aligned)):
                raise ValueError(f"NaN in aligned prices for {s}")
            prices_mat[:, j] = p_aligned

            w = np.asarray(weight_dict[s], dtype=float)
            # weight series must align with original price series, then re-index to common
            w_full = pd.Series(w, index=price_dict[s].index)
            w_series = w_full.reindex(common_idx)
            if self.align_calendar == "union_ffill":
                w_series = w_series.ffill().fillna(0.0)
            w_aligned = w_series.values.astype(float)
            if np.any(np.isnan(w_aligned)):
                raise ValueError(f"NaN in aligned weights for {s}")
            # Per-asset weights are PRE-LEVERAGE-CAP signal magnitudes in [-1, 1].
            # Final positions may be rescaled uniformly by the gross/net leverage
            # caps in _apply_leverage_caps().
            if np.any(np.abs(w_aligned) > 1.0 + 1e-9):
                raise ValueError(
                    f"weights for {s} must be in [-1, 1], got max abs "
                    f"{np.abs(w_aligned).max():.4f}"
                )
            weights_mat[:, j] = w_aligned

        return symbols, common_idx, prices_mat, weights_mat

    def _build_common_index(self, symbols: list, price_dict: dict) -> pd.DatetimeIndex:
        """Build the common DatetimeIndex per the ``align_calendar`` policy."""
        if self.align_calendar == "intersection":
            common_idx = None
            for s in symbols:
                idx = price_dict[s].index
                common_idx = idx if common_idx is None else common_idx.intersection(idx)
            return common_idx

        if self.align_calendar == "union_ffill":
            common_idx = None
            for s in symbols:
                idx = price_dict[s].index
                common_idx = idx if common_idx is None else common_idx.union(idx)
            return common_idx

        if self.align_calendar == "us_equity":
            try:
                import pandas_market_calendars as mcal
            except ImportError:
                # fall back to intersection if pandas_market_calendars missing
                common_idx = None
                for s in symbols:
                    idx = price_dict[s].index
                    common_idx = idx if common_idx is None else common_idx.intersection(idx)
                return common_idx
            # build NYSE trading-day index spanning all symbol date ranges
            starts = [price_dict[s].index.min() for s in symbols]
            ends = [price_dict[s].index.max() for s in symbols]
            start = min(starts)
            end = max(ends)
            nyse = mcal.get_calendar("NYSE")
            sched = nyse.schedule(start_date=start.date(), end_date=end.date())
            return pd.DatetimeIndex(sched.index)

        raise ValueError(f"unknown align_calendar: {self.align_calendar!r}")

    def _apply_leverage_caps(self, weights_mat: np.ndarray) -> tuple:
        """Apply gross + net leverage caps per bar. Returns (rescaled, factor)."""
        gross = np.sum(np.abs(weights_mat), axis=1)
        net = np.sum(weights_mat, axis=1)

        gross_factor = np.where(
            gross > self.gross_leverage_cap,
            self.gross_leverage_cap / np.maximum(gross, 1e-12),
            1.0,
        )
        net_factor = np.where(
            np.abs(net) > self.net_leverage_cap,
            self.net_leverage_cap / np.maximum(np.abs(net), 1e-12),
            1.0,
        )
        factor = np.minimum(gross_factor, net_factor)

        rescaled = weights_mat * factor[:, None]
        return rescaled, factor

    def run(
        self,
        price_dict: dict,
        weight_dict: dict,
        costs_dict: Optional[dict] = None,
        ppy: int = 252,
        attribution_method: str = "additive",
        partial_fill_factor: float = 1.0,
    ) -> MultiAssetResult:
        """Run multi-asset portfolio backtest.

        Args:
            price_dict: dict[symbol -> pd.Series of prices, DatetimeIndex]
            weight_dict: dict[symbol -> np.array of target weights in [-1, 1]]
            costs_dict: dict[symbol -> CostModel], default ZERO_costs each
            ppy: periods per year (252 daily, 12 monthly)
            attribution_method: how to compute per-asset contribution to total
                portfolio return.

                - ``'additive'`` (default, original behavior): sum of per-bar
                  net contributions across the path. This matches the
                  continuously-rebalanced approximation but ignores compounding
                  with the rest of the portfolio.
                - ``'compound'``: per-asset contribution accounting for the
                  multiplicative interaction of the asset's bar-level net
                  return with the rest of the portfolio's compounding NAV.
                  Computed as ``sum(per_bar_contrib_j * NAV_{t-1})`` where
                  NAV uses the full portfolio path. The sum across assets
                  equals the portfolio's total compounded gain
                  (NAV_T - NAV_0), so the attributions decompose the actual
                  realized PnL exactly.
            partial_fill_factor: forwarded to ``apply_costs`` for each asset.
                Default 1.0 (full instant fill).

        Returns:
            MultiAssetResult with portfolio metrics, attribution, correlations
        """
        if attribution_method not in ("additive", "compound"):
            raise ValueError(
                f"attribution_method must be 'additive' or 'compound', "
                f"got {attribution_method!r}"
            )
        symbols, common_idx, prices_mat, raw_weights = self._align(price_dict, weight_dict)
        T, N = prices_mat.shape

        # Validate non-positive prices before computing returns. Division by 0
        # would produce inf/-inf/nan and corrupt downstream NAV silently.
        if np.any(prices_mat <= 0):
            raise ValueError("non-positive prices")

        # asset returns (raw, before costs)
        asset_rets = np.zeros((T, N), dtype=float)
        asset_rets[1:, :] = prices_mat[1:, :] / prices_mat[:-1, :] - 1.0

        # apply leverage caps
        rescaled_weights, rescale_factor = self._apply_leverage_caps(raw_weights)

        # per-asset cost-deducted returns. Note: apply_costs charges a per-bar
        # turnover cost on bar 0 = |weights[0]| * per_trade_bps even though
        # the first bar has no carried position. Doing per-asset apply_costs
        # then zeroing portfolio_rets[0] after summing would lose the bar-0
        # turnover charge unequally across attribution; we zero each per-asset
        # net_j[0] BEFORE attribution so the first-bar leak is removed
        # consistently and per-asset attribution stays internally consistent.
        costs_dict = costs_dict or {}
        per_asset_rets = {}
        per_bar_contrib = np.zeros((T, N), dtype=float)
        for j, s in enumerate(symbols):
            cm = costs_dict.get(s, ZERO_costs)
            net_j = apply_costs(rescaled_weights[:, j], asset_rets[:, j], cm,
                                partial_fill_factor=partial_fill_factor)
            if T > 0:
                net_j[0] = 0.0  # no return AND no cost on bar 0 (no carry)
            per_asset_rets[s] = net_j
            per_bar_contrib[:, j] = net_j

        # portfolio aggregate net returns
        portfolio_rets = per_bar_contrib.sum(axis=1)
        # portfolio_rets[0] is now exactly 0 from the per-asset zeroing above.
        nav = np.cumprod(1.0 + portfolio_rets)

        # per-asset attribution
        if attribution_method == "additive":
            # original behavior: sum of per-bar net contributions (additive in
            # continuously-rebalanced portfolio approximation).
            attribution = {
                s: float(per_bar_contrib[:, j].sum())
                for j, s in enumerate(symbols)
            }
        else:
            # compound: weight each bar's per-asset contribution by the
            # portfolio NAV at the START of the bar (NAV_{t-1}). The sum across
            # assets is sum_t (sum_j contrib_jt) * nav_{t-1} = sum_t r_t * nav_{t-1}
            # = NAV_T - NAV_0, so the per-asset attributions exactly decompose
            # the realized portfolio PnL through the full rebalance path.
            prev_nav = np.empty(T, dtype=float)
            prev_nav[0] = 1.0
            if T > 1:
                prev_nav[1:] = nav[:-1]
            attribution = {
                s: float((per_bar_contrib[:, j] * prev_nav).sum())
                for j, s in enumerate(symbols)
            }

        # cross-asset correlation of raw asset returns over backtest (skip first bar = 0)
        corr_df = pd.DataFrame(asset_rets[1:, :], columns=symbols).corr()

        # post-rescale leverage tracking
        gross_leverage = np.sum(np.abs(rescaled_weights), axis=1)
        net_leverage = np.sum(rescaled_weights, axis=1)

        metrics = compute_metrics(portfolio_rets[1:], ppy=ppy)

        return MultiAssetResult(
            metrics=metrics,
            nav=nav,
            rets=portfolio_rets,
            weights=rescaled_weights,
            raw_weights=raw_weights,
            symbols=symbols,
            timestamps=common_idx.values,
            per_asset_attribution=attribution,
            per_asset_rets=per_asset_rets,
            correlation_matrix=corr_df,
            gross_leverage=gross_leverage,
            net_leverage=net_leverage,
            rescale_factor=rescale_factor,
        )
