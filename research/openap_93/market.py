"""Current market-data reconstructions of pinned OpenAP predictors.

These functions perform no I/O. GitHub workflows bind their tidy inputs to
immutable source artifacts before calling them.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd


class FormulaInputError(ValueError):
    """Raised when an official formula cannot be evaluated honestly."""


def _finite(values: Sequence[float]) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    return array[np.isfinite(array)]


def ols_fit(y: Sequence[float], x: np.ndarray) -> tuple[np.ndarray, float, np.ndarray]:
    """Return OLS coefficients, R-squared and residuals with an intercept."""

    y_array = np.asarray(y, dtype=float)
    x_array = np.asarray(x, dtype=float)
    if x_array.ndim == 1:
        x_array = x_array.reshape(-1, 1)
    if len(y_array) != len(x_array):
        raise FormulaInputError("OLS y and X lengths differ")
    valid = np.isfinite(y_array) & np.isfinite(x_array).all(axis=1)
    y_valid = y_array[valid]
    x_valid = x_array[valid]
    if len(y_valid) <= x_valid.shape[1] + 1:
        raise FormulaInputError("Insufficient finite observations for OLS")
    design = np.column_stack([np.ones(len(x_valid)), x_valid])
    coefficients, _, rank, _ = np.linalg.lstsq(design, y_valid, rcond=None)
    if rank < design.shape[1]:
        raise FormulaInputError("Singular OLS design")
    fitted = design @ coefficients
    residuals = y_valid - fitted
    total = float(np.square(y_valid - y_valid.mean()).sum())
    r_squared = float(1.0 - np.square(residuals).sum() / total) if total > 0 else np.nan
    return coefficients, r_squared, residuals


def compound_lags(values: pd.Series, lags: Sequence[int]) -> float | None:
    """Compound calendar-ordered monthly return lags from the latest row."""

    if not lags or len(values) <= max(lags):
        return None
    selected = pd.to_numeric(values, errors="coerce").iloc[
        [len(values) - 1 - lag for lag in lags]
    ]
    if selected.isna().any():
        return None
    return float(np.prod(1.0 + selected.to_numpy(dtype=float)) - 1.0)


def coskewness_60m(stock_excess: Sequence[float], market_excess: Sequence[float]) -> float | None:
    """Harvey-Siddique systematic coskewness, trailing 60 months, minimum 12."""

    stock = np.asarray(stock_excess, dtype=float)[-60:]
    market = np.asarray(market_excess, dtype=float)[-60:]
    valid = np.isfinite(stock) & np.isfinite(market)
    stock = stock[valid]
    market = market[valid]
    if len(stock) < 12:
        return None
    stock = stock - stock.mean()
    market = market - market.mean()
    denominator = float(np.sqrt(np.mean(stock**2)) * np.mean(market**2))
    if denominator <= 0 or not np.isfinite(denominator):
        return None
    return float(np.mean(stock * market**2) / denominator)


def coskew_acx(stock_returns: Sequence[float], market_returns: Sequence[float]) -> float | None:
    """Ang-Chen-Xing daily coskewness over the supplied trailing-year window."""

    stock = np.asarray(stock_returns, dtype=float)
    market = np.asarray(market_returns, dtype=float)
    valid = np.isfinite(stock) & np.isfinite(market)
    stock = stock[valid]
    market = market[valid]
    if len(stock) < 200:
        return None
    stock = stock - stock.mean()
    market = market - market.mean()
    denominator = float(np.sqrt(np.mean(stock**2)) * np.mean(market**2))
    if denominator <= 0 or not np.isfinite(denominator):
        return None
    return float(np.mean(stock * market**2) / denominator)


def ff3_month_residual_moments(
    stock_excess: Sequence[float],
    mktrf: Sequence[float],
    smb: Sequence[float],
    hml: Sequence[float],
) -> tuple[float | None, float | None]:
    """IdioVol3F and ReturnSkew3F for one month, requiring 15 trading days."""

    y = np.asarray(stock_excess, dtype=float)
    x = np.column_stack([mktrf, smb, hml]).astype(float)
    valid = np.isfinite(y) & np.isfinite(x).all(axis=1)
    if int(valid.sum()) < 15:
        return None, None
    try:
        _, _, residuals = ols_fit(y[valid], x[valid])
    except FormulaInputError:
        return None, None
    if len(residuals) < 3:
        return None, None
    std = float(np.std(residuals, ddof=1))
    centered = residuals - residuals.mean()
    variance = float(np.mean(centered**2))
    skew = float(np.mean(centered**3) / variance**1.5) if variance > 0 else None
    return std, skew


def price_delay_rsq(
    stock_excess: Sequence[float],
    market_excess: Sequence[float],
    *,
    lags: int = 4,
) -> float | None:
    """Hou-Moskowitz D1: 1 - restricted R2 / unrestricted R2."""

    y = np.asarray(stock_excess, dtype=float)
    market = np.asarray(market_excess, dtype=float)
    if len(y) != len(market) or len(y) < 26 + lags:
        return None
    columns = [market]
    for lag in range(1, lags + 1):
        columns.append(np.concatenate([np.full(lag, np.nan), market[:-lag]]))
    unrestricted_x = np.column_stack(columns)
    try:
        _, restricted_r2, _ = ols_fit(y, market)
        _, unrestricted_r2, _ = ols_fit(y, unrestricted_x)
    except FormulaInputError:
        return None
    if not np.isfinite(unrestricted_r2) or abs(unrestricted_r2) < 1e-12:
        return None
    return float(1.0 - restricted_r2 / unrestricted_r2)


def beta_vix(
    stock_excess: Sequence[float],
    market_excess: Sequence[float],
    vix_changes: Sequence[float],
) -> float | None:
    """Current 20-session beta on VIX changes controlling for the market."""

    y = np.asarray(stock_excess, dtype=float)[-20:]
    x = np.column_stack([market_excess, vix_changes]).astype(float)[-20:]
    valid = np.isfinite(y) & np.isfinite(x).all(axis=1)
    if int(valid.sum()) < 15:
        return None
    try:
        coefficients, _, _ = ols_fit(y[valid], x[valid])
    except FormulaInputError:
        return None
    return float(coefficients[2])


def beta_liquidity_ps(
    stock_excess: Sequence[float],
    ps_innovation: Sequence[float],
    mktrf: Sequence[float],
    smb: Sequence[float],
    hml: Sequence[float],
) -> float | None:
    """Pastor-Stambaugh liquidity beta over 60 months, minimum 36."""

    y = np.asarray(stock_excess, dtype=float)[-60:]
    x = np.column_stack([ps_innovation, mktrf, hml, smb]).astype(float)[-60:]
    valid = np.isfinite(y) & np.isfinite(x).all(axis=1)
    if int(valid.sum()) < 36:
        return None
    try:
        coefficients, _, _ = ols_fit(y[valid], x[valid])
    except FormulaInputError:
        return None
    return float(coefficients[1])


def residual_momentum(
    stock_excess: Sequence[float],
    mktrf: Sequence[float],
    smb: Sequence[float],
    hml: Sequence[float],
) -> float | None:
    """Blitz-Huij-Martens current residual momentum from rolling FF3 residuals."""

    y = np.asarray(stock_excess, dtype=float)
    factors = np.column_stack([mktrf, smb, hml]).astype(float)
    if len(y) != len(factors) or len(y) < 47:
        return None
    rolling_residuals: list[float] = []
    for end in range(36, len(y) + 1):
        window_y = y[end - 36 : end]
        window_x = factors[end - 36 : end]
        valid = np.isfinite(window_y) & np.isfinite(window_x).all(axis=1)
        if int(valid.sum()) < 36:
            rolling_residuals.append(np.nan)
            continue
        try:
            coefficients, _, _ = ols_fit(window_y, window_x)
        except FormulaInputError:
            rolling_residuals.append(np.nan)
            continue
        latest_x = np.r_[1.0, window_x[-1]]
        rolling_residuals.append(float(window_y[-1] - latest_x @ coefficients))
    prior = _finite(rolling_residuals[:-1])[-11:]
    if len(prior) < 11:
        return None
    std = float(np.std(prior, ddof=1))
    return float(np.mean(prior) / std) if std > 0 else None


def zero_trade_measure(
    volumes: Sequence[float],
    turnovers: Sequence[float],
    *,
    expected_days: int,
    deflator: float,
) -> float | None:
    """Liu zero-trade measure using actual zero days and turnover adjustment."""

    volume = np.asarray(volumes, dtype=float)
    turnover = np.asarray(turnovers, dtype=float)
    valid = np.isfinite(volume) & np.isfinite(turnover)
    volume = volume[valid]
    turnover = turnover[valid]
    if not len(volume) or len(volume) < expected_days * 0.7:
        return None
    total_turnover = float(turnover.sum())
    adjustment = (1.0 / total_turnover) / deflator if total_turnover > 0 else 0.0
    return float(((volume <= 0).sum() + adjustment) * expected_days / len(volume))

