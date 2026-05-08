"""Hedge Fund Benchmark.

Compare a strategy's returns against a panel of hedge-fund factor returns:

    Mkt-RF  -- excess market
    SMB     -- size
    HML     -- value
    RMW     -- profitability
    CMA     -- investment
    MOM     -- momentum
    BAB     -- betting-against-beta
    QMJ     -- quality minus junk

Style attribution: regress strategy returns on the factor panel and report
the OLS coefficients (betas), the alpha, and the in-sample R^2.

The factor returns are user-supplied as a DataFrame indexed by date with
each factor as a column. If the strategy's returns are higher-frequency
than the factor panel, the caller is responsible for aligning beforehand.

If a real factor panel is unavailable, ``synthetic_factor_returns`` returns
a deterministic synthetic panel for tests.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
import pandas as pd


FACTOR_NAMES = ("Mkt-RF", "SMB", "HML", "RMW", "CMA", "MOM", "BAB", "QMJ")


@dataclass
class StyleAttributionReport:
    alpha: float
    betas: dict[str, float]
    r_squared: float
    n_obs: int
    residuals_std: float
    factor_names: list[str] = field(default_factory=list)


def synthetic_factor_returns(n: int, seed: int = 42,
                             start: str = "2020-01-01") -> pd.DataFrame:
    """Generate a deterministic synthetic factor panel.

    Returns are drawn from independent N(0, 1bp) per factor, so any tested
    strategy will have realistic but uncorrelated factor regressors.
    """
    rng = np.random.default_rng(seed)
    data = {}
    for f in FACTOR_NAMES:
        data[f] = rng.normal(0.0002, 0.01, n)
    idx = pd.date_range(start, periods=n, freq="B")
    return pd.DataFrame(data, index=idx)


def _ols_regress(y: np.ndarray, X: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    """Plain OLS via lstsq. Returns (coefficients, residuals, r_squared)."""
    coef, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
    pred = X @ coef
    resid = y - pred
    ss_res = float(np.sum(resid ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return coef, resid, r2


class HedgeFundBenchmark:
    """OLS style attribution against a hedge-fund factor panel."""

    def __init__(self, factors: pd.DataFrame | None = None):
        if factors is None:
            factors = synthetic_factor_returns(n=500)
        if not isinstance(factors, pd.DataFrame):
            raise TypeError("factors must be a pandas DataFrame")
        if factors.empty:
            raise ValueError("factors DataFrame is empty")
        self.factors = factors

    def attribute(self, strategy_returns: pd.Series) -> StyleAttributionReport:
        """Run style attribution on aligned strategy_returns."""
        if not isinstance(strategy_returns, pd.Series):
            raise TypeError("strategy_returns must be a pandas Series")
        s = strategy_returns.dropna()
        if s.empty:
            raise ValueError("strategy_returns has no finite samples")
        common = self.factors.index.intersection(s.index)
        if len(common) < len(self.factors.columns) + 2:
            raise ValueError(
                f"need at least {len(self.factors.columns) + 2} aligned "
                f"observations for attribution; got {len(common)}"
            )
        y = s.loc[common].values.astype(float)
        F = self.factors.loc[common].values.astype(float)
        # Add intercept column (alpha)
        X = np.hstack([np.ones((len(y), 1)), F])
        coef, resid, r2 = _ols_regress(y, X)
        alpha = float(coef[0])
        betas = {name: float(coef[i + 1])
                 for i, name in enumerate(self.factors.columns)}
        return StyleAttributionReport(
            alpha=alpha,
            betas=betas,
            r_squared=float(r2),
            n_obs=len(y),
            residuals_std=float(np.std(resid, ddof=1)) if len(resid) > 1 else 0.0,
            factor_names=list(self.factors.columns),
        )

    def compare(self, strategy_returns: pd.Series) -> dict[str, float]:
        """Headline comparison: strategy vs each factor's mean and Sharpe."""
        if not isinstance(strategy_returns, pd.Series):
            raise TypeError("strategy_returns must be a pandas Series")
        s = strategy_returns.dropna()
        common = self.factors.index.intersection(s.index)
        out: dict[str, float] = {}
        if s.std(ddof=1) > 0:
            out["strategy_sharpe_ann"] = float(
                s.mean() / s.std(ddof=1) * np.sqrt(252)
            )
        else:
            out["strategy_sharpe_ann"] = 0.0
        out["strategy_mean"] = float(s.mean())
        for col in self.factors.columns:
            f = self.factors[col].loc[common]
            if f.std(ddof=1) > 0:
                out[f"{col}_sharpe_ann"] = float(f.mean() / f.std(ddof=1) * np.sqrt(252))
            else:
                out[f"{col}_sharpe_ann"] = 0.0
        return out
