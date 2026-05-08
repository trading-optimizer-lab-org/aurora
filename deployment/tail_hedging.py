"""Tail-hedging overlay using OTM put options.

Sizes a put-option overlay to cap drawdown subject to a configurable budget
expressed as % of NAV per period. Computes Black-Scholes prices and Greeks
for the put leg so the caller can plug into a P&L / margin engine.

Output is a 1-row DataFrame on the asset universe whose entries are the put
NOTIONAL (in % of NAV) allocated to a hedge on each underlying. Holdings on
the underlying itself are unchanged here; this is an overlay, not a sleeve
allocator.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

import math
import numpy as np
import pandas as pd


SQRT_2PI = math.sqrt(2.0 * math.pi)


# --------------------------------------------------------------------------- #
# Black-Scholes helpers                                                       #
# --------------------------------------------------------------------------- #
def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / SQRT_2PI


def black_scholes_put(
    spot: float, strike: float, ttm: float, sigma: float, r: float = 0.0,
) -> dict:
    """Return Black-Scholes put price + Greeks (delta, gamma, vega, theta).

    Uses cont. compounding, no dividends. ``ttm`` in years.
    """
    if spot <= 0 or strike <= 0 or ttm <= 0 or sigma <= 0:
        return {
            "price": max(strike - spot, 0.0),
            "delta": -1.0 if spot < strike else 0.0,
            "gamma": 0.0,
            "vega": 0.0,
            "theta": 0.0,
        }
    sqrt_t = math.sqrt(ttm)
    d1 = (math.log(spot / strike) + (r + 0.5 * sigma * sigma) * ttm) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    disc = math.exp(-r * ttm)
    price = strike * disc * _norm_cdf(-d2) - spot * _norm_cdf(-d1)
    delta = _norm_cdf(d1) - 1.0
    gamma = _norm_pdf(d1) / (spot * sigma * sqrt_t)
    vega = spot * _norm_pdf(d1) * sqrt_t
    theta = (
        -(spot * _norm_pdf(d1) * sigma) / (2.0 * sqrt_t)
        + r * strike * disc * _norm_cdf(-d2)
    )
    return {
        "price": float(price), "delta": float(delta), "gamma": float(gamma),
        "vega": float(vega), "theta": float(theta),
    }


@dataclass
class TailHedgeConfig:
    """Configuration for :class:`TailHedgingOverlay`."""
    budget_pct_nav: float = 0.01      # max premium spent per period (1% of NAV)
    moneyness: float = 0.90           # OTM strike = spot * moneyness
    days_to_expiry: int = 30
    risk_free_rate: float = 0.0
    sigma_lookback: int = 60          # bars for realised vol estimate
    ppy: int = 252


@dataclass
class TailHedgeResult:
    """Output of :meth:`TailHedgingOverlay.allocate`."""
    weights: pd.DataFrame             # 1-row, columns = assets, value = put notional %
    put_prices: pd.Series             # per-asset BS price
    put_greeks: pd.DataFrame          # per-asset delta/gamma/vega/theta
    premium_spent: float              # total premium / NAV (<= budget)


class TailHedgingOverlay:
    """OTM put overlay sized to a premium budget.

    Args:
        config: :class:`TailHedgeConfig`. ``None`` -> defaults.
    """

    def __init__(self, config: Optional[TailHedgeConfig] = None):
        self.config = config or TailHedgeConfig()
        if not (0 < self.config.budget_pct_nav <= 1):
            raise ValueError("budget_pct_nav must be in (0, 1]")
        if not (0 < self.config.moneyness < 1):
            raise ValueError("moneyness must be in (0, 1) for OTM puts")
        if self.config.days_to_expiry <= 0:
            raise ValueError("days_to_expiry must be > 0")

    # --------------------------------------------------------------------- #
    def _realized_vol(self, prices: pd.Series) -> float:
        rets = prices.pct_change().dropna().tail(self.config.sigma_lookback)
        if len(rets) < 2:
            return float("nan")
        return float(rets.std(ddof=1) * math.sqrt(self.config.ppy))

    # --------------------------------------------------------------------- #
    def allocate(
        self,
        prices: pd.DataFrame,
        underlying_weights: Optional[pd.Series] = None,
    ) -> TailHedgeResult:
        """Compute put overlay sized to ``budget_pct_nav``.

        Args:
            prices: TxN price DataFrame.
            underlying_weights: per-asset weight in the underlying portfolio,
                used to allocate budget proportionally. Defaults to equal.
        """
        if not isinstance(prices, pd.DataFrame):
            raise TypeError("prices must be a pd.DataFrame")
        if prices.shape[1] < 1:
            raise ValueError("need >= 1 asset")

        assets = list(prices.columns)
        if underlying_weights is None:
            uw = pd.Series(1.0 / len(assets), index=assets)
        else:
            uw = underlying_weights.reindex(assets).fillna(0.0)
            s = uw.sum()
            if s > 0:
                uw = uw / s

        ttm = self.config.days_to_expiry / 365.0
        spot = prices.iloc[-1]
        prices_out, greek_rows = {}, {}
        for a in assets:
            sigma = self._realized_vol(prices[a])
            if not np.isfinite(sigma) or sigma <= 0:
                sigma = 0.20
            bs = black_scholes_put(
                spot=float(spot[a]),
                strike=float(spot[a]) * self.config.moneyness,
                ttm=ttm, sigma=sigma, r=self.config.risk_free_rate,
            )
            prices_out[a] = bs["price"]
            greek_rows[a] = {k: bs[k] for k in ("delta", "gamma", "vega", "theta")}

        # Allocate budget proportional to underlying weight; per-asset
        # premium = budget * uw[a]. Notional % is premium / put_price * spot.
        premium = self.config.budget_pct_nav * uw
        notionals = {}
        spent = 0.0
        for a in assets:
            p = prices_out[a]
            if p <= 0:
                notionals[a] = 0.0
                continue
            n_contracts = float(premium[a] / p) if p > 0 else 0.0
            # Notional as % of NAV = (n_contracts * spot) / NAV. The caller
            # holds NAV implicit; we report relative to NAV by tracking the
            # premium fraction already in budget_pct_nav.
            notionals[a] = float(n_contracts * spot[a])
            spent += float(premium[a])

        weights_df = pd.DataFrame(
            [pd.Series(notionals).reindex(assets).values],
            index=["put_overlay"],
            columns=assets,
        )
        greeks_df = pd.DataFrame(greek_rows).T
        return TailHedgeResult(
            weights=weights_df,
            put_prices=pd.Series(prices_out),
            put_greeks=greeks_df,
            premium_spent=float(min(spent, self.config.budget_pct_nav)),
        )
