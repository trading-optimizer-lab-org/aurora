"""Vol-targeting using GARCH-forecasted volatility.

Smoother position sizing than realized-vol targeting. Uses a 1-step-ahead
GARCH(1,1) variance forecast (via the lazy-imported ``arch`` package) to
compute a vol-target leverage. Falls back to EWMA vol when ``arch`` is
unavailable so this module always returns weights.

Output is a 1-row weight DataFrame on the asset universe; per-asset weight is
proportional to ``target_vol / forecast_vol`` (capped by ``max_leverage``)
then normalised to sum to 1 across assets.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class VolTargetForecastConfig:
    """Configuration for :class:`VolTargetForecaster`."""
    target_annual_vol: float = 0.10
    max_leverage: float = 3.0
    ppy: int = 252                  # periods per year
    garch_p: int = 1
    garch_q: int = 1
    fallback_ewma_lambda: float = 0.94
    lookback: int = 252


@dataclass
class VolTargetForecastResult:
    """Output of :meth:`VolTargetForecaster.allocate`."""
    weights: pd.DataFrame              # 1-row of normalised target weights
    raw_leverage: pd.Series            # per-asset target_vol / forecast_vol
    forecast_vol: pd.Series            # annualised 1-step-ahead vol
    used_garch: bool                   # True if arch path succeeded for >=1 asset


def _ewma_annual_vol(rets: pd.Series, lam: float, ppy: int) -> float:
    """Simple EWMA variance forecast (RiskMetrics-style)."""
    r = np.asarray(rets, dtype=float)
    if len(r) < 2:
        return float("nan")
    var = float(np.var(r, ddof=1))
    for x in r:
        var = lam * var + (1.0 - lam) * (x * x)
    return float(np.sqrt(max(var, 0.0) * ppy))


def _garch_annual_vol(rets: pd.Series, p: int, q: int, ppy: int) -> Optional[float]:
    """One-step-ahead GARCH(p,q) annualised vol; ``None`` if arch missing."""
    try:
        from arch import arch_model
    except ImportError:
        return None
    r = np.asarray(rets, dtype=float)
    if len(r) < 30:
        return None
    try:
        # arch likes percent returns to keep the optimizer well-scaled.
        am = arch_model(r * 100.0, vol="Garch", p=p, q=q, rescale=False)
        res = am.fit(disp="off", show_warning=False)
        fc = res.forecast(horizon=1, reindex=False)
        var_pct = float(fc.variance.iloc[-1, 0])
    except Exception:
        return None
    var_decimal = var_pct / 1e4   # undo the 100x scale
    return float(np.sqrt(max(var_decimal, 0.0) * ppy))


class VolTargetForecaster:
    """Vol-target sizing driven by a GARCH 1-step-ahead variance forecast.

    Args:
        config: :class:`VolTargetForecastConfig`. ``None`` -> defaults.
    """

    def __init__(self, config: Optional[VolTargetForecastConfig] = None):
        self.config = config or VolTargetForecastConfig()
        if self.config.target_annual_vol <= 0:
            raise ValueError("target_annual_vol must be > 0")
        if self.config.max_leverage <= 0:
            raise ValueError("max_leverage must be > 0")

    # --------------------------------------------------------------------- #
    def allocate(self, prices: pd.DataFrame) -> VolTargetForecastResult:
        """Compute vol-targeted weights from forecast vol."""
        if not isinstance(prices, pd.DataFrame):
            raise TypeError("prices must be a pd.DataFrame")
        if prices.shape[1] < 1:
            raise ValueError(f"need >= 1 asset, got {prices.shape[1]}")

        rets = prices.pct_change().dropna().tail(self.config.lookback)
        if len(rets) < 5:
            raise ValueError("need >= 5 return observations")

        used_garch = False
        forecast_vols = {}
        for col in rets.columns:
            v = _garch_annual_vol(
                rets[col], self.config.garch_p,
                self.config.garch_q, self.config.ppy,
            )
            if v is None or not np.isfinite(v) or v <= 0:
                v = _ewma_annual_vol(
                    rets[col], self.config.fallback_ewma_lambda,
                    self.config.ppy,
                )
            else:
                used_garch = True
            forecast_vols[col] = float(v) if np.isfinite(v) and v > 0 else float("nan")

        fv = pd.Series(forecast_vols)
        # Compute per-asset leverage = target / forecast, capped.
        lev = self.config.target_annual_vol / fv.replace(0.0, np.nan)
        lev = lev.fillna(0.0).clip(upper=self.config.max_leverage)

        s = lev.sum()
        if s > 0:
            w = lev / s
        else:
            w = pd.Series(1.0 / len(lev), index=lev.index)

        weights_df = pd.DataFrame(
            [w.reindex(prices.columns).values],
            index=["vol_target"],
            columns=list(prices.columns),
        )
        return VolTargetForecastResult(
            weights=weights_df,
            raw_leverage=lev.reindex(prices.columns),
            forecast_vol=fv.reindex(prices.columns),
            used_garch=used_garch,
        )
