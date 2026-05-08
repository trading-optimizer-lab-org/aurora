"""Alphalens-style factor analysis.

Reference: https://github.com/quantopian/alphalens

Factor model
------------
This module implements **single-factor evaluation** in the alphalens style:
each call takes one user-supplied `factor` series (e.g. value, momentum,
quality, custom alpha signal) and a price/forward-returns series, and reports
IC, quantile-spread, and turnover diagnostics for that factor.

It does **not** ship a hard-coded multi-factor model such as Fama-French
3-factor (Mkt-RF, SMB, HML), Carhart 4-factor (+ Momentum), or
Fama-French 5-factor (+ RMW, CMA). Multi-factor *attribution* (regressing
returns on a custom factor matrix and reporting alpha/betas) is provided by
:func:`quantforge.analytics.attribution.attribution_by_factor`, which
accepts an arbitrary `factor_returns_dict` so the caller can pass any
combination of Mkt-RF, SMB, HML, Momentum, Quality, or custom factor
returns.

Functions:
    information_coefficient: factor vs forward returns correlation (IC)
    quantile_spread: bin factor into quantiles, compute long-short spread
    factor_returns: factor portfolio returns under different weighting
    factor_turnover: mean abs change in factor rank
    factor_autocorrelation: factor autocorrelation across lags
    factor_summary_table: all-in-one summary for multiple periods

Single-asset adaptation: time-series binning/ranking instead of
cross-sectional. Cross-sectional support kept where APIs allow MultiIndex
(date, asset) inputs but the primary path tested here is single-asset.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------

@dataclass
class ICResult:
    daily_ic: pd.Series
    mean_ic: float
    ic_std: float
    ic_ir: float            # information ratio (mean / std)
    t_stat: float
    p_value: float


@dataclass
class QuantileSpreadResult:
    period_returns: pd.DataFrame  # quantile x period_offset matrix
    spread_returns: pd.Series      # top quantile - bottom quantile
    cum_spread: pd.Series
    sharpe: float
    n_quantiles: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_multi_index(s: pd.Series) -> bool:
    return isinstance(s.index, pd.MultiIndex) and s.index.nlevels >= 2


def _align(factor: pd.Series, other: pd.Series) -> tuple[pd.Series, pd.Series]:
    df = pd.concat([factor.rename("f"), other.rename("o")], axis=1).dropna()
    return df["f"], df["o"]


def _forward_returns_from_prices(prices: pd.Series, period: int) -> pd.Series:
    """next-`period`-bar simple return aligned to t (i.e. r_{t->t+period})."""
    fwd = prices.shift(-period) / prices - 1.0
    return fwd


# ---------------------------------------------------------------------------
# Information Coefficient
# ---------------------------------------------------------------------------

def information_coefficient(factor: pd.Series,
                            forward_returns: pd.Series,
                            method: str = "spearman") -> ICResult:
    """Cross-sectional or time-series IC depending on index shape.

    For MultiIndex (date, asset): compute IC per date across assets.
    For single-asset (DatetimeIndex): time-series rank correlation
    via expanding window (single sample) -- daily_ic is a 1-element
    series at the last date with the full-sample IC.

    Args:
        factor: pd.Series of factor values
        forward_returns: pd.Series of forward returns
        method: 'spearman' | 'pearson'

    Returns:
        ICResult with daily IC + statistics.
    """
    if method not in ("spearman", "pearson"):
        raise ValueError(f"method must be 'spearman' or 'pearson', got {method!r}")
    corr_fn = stats.spearmanr if method == "spearman" else stats.pearsonr

    f, r = _align(factor, forward_returns)
    if len(f) < 3:
        raise ValueError(f"insufficient overlapping observations: {len(f)}")

    if _is_multi_index(factor) and _is_multi_index(forward_returns):
        df = pd.concat([f.rename("f"), r.rename("r")], axis=1)
        date_level = df.index.names[0] or "level_0"
        ic_per_date = {}
        for d, sub in df.groupby(level=0):
            if len(sub) < 3:
                continue
            try:
                c, _ = corr_fn(sub["f"].values, sub["r"].values)
            except Exception:
                c = np.nan
            ic_per_date[d] = c
        daily_ic = pd.Series(ic_per_date, name="ic").sort_index()
        daily_ic.index.name = date_level
    else:
        # Single-asset time-series: rolling/window IC across the series.
        # Use a windowed rank correlation so we get a daily series rather
        # than a single scalar. Default window: min(60, len(f)//4) bars.
        w = max(20, min(60, len(f) // 4))
        if method == "pearson":
            x = f
            y = r
            x_mean = x.rolling(w).mean()
            y_mean = y.rolling(w).mean()
            # ddof=0 std (population) to match E[XY]-E[X]E[Y] cov below;
            # otherwise perfect correlation comes out at (n-1)/n instead of 1.
            x_std = x.rolling(w).std(ddof=0)
            y_std = y.rolling(w).std(ddof=0)
            cov = (x * y).rolling(w).mean() - x_mean * y_mean
            denom = x_std * y_std
            daily_ic = (cov / denom.replace(0.0, np.nan)).dropna()
        else:
            # Spearman: rank WITHIN each rolling window to avoid leaking
            # future information from a global rank. Manual loop because
            # pandas rolling does not natively support per-window rank
            # correlation across two series.
            f_arr = f.values.astype(float)
            r_arr = r.values.astype(float)
            n_obs = len(f_arr)
            ic_vals = np.full(n_obs, np.nan, dtype=float)
            for end in range(w - 1, n_obs):
                fw = f_arr[end - w + 1: end + 1]
                rw = r_arr[end - w + 1: end + 1]
                rf_w = pd.Series(fw).rank().values
                rr_w = pd.Series(rw).rank().values
                rf_std = rf_w.std(ddof=0)
                rr_std = rr_w.std(ddof=0)
                if rf_std == 0 or rr_std == 0:
                    continue
                ic_vals[end] = (
                    ((rf_w * rr_w).mean() - rf_w.mean() * rr_w.mean())
                    / (rf_std * rr_std)
                )
            daily_ic = pd.Series(ic_vals, index=f.index).dropna()
        daily_ic.name = "ic"

    daily_ic = daily_ic.replace([np.inf, -np.inf], np.nan).dropna()
    if len(daily_ic) == 0:
        return ICResult(daily_ic=daily_ic, mean_ic=np.nan, ic_std=np.nan,
                        ic_ir=np.nan, t_stat=np.nan, p_value=np.nan)

    mean_ic = float(daily_ic.mean())
    ic_std = float(daily_ic.std(ddof=1)) if len(daily_ic) > 1 else 0.0
    ic_ir = mean_ic / ic_std if ic_std > 0 else np.nan
    n = len(daily_ic)
    if ic_std > 0 and n > 1:
        # In the single-asset path ``daily_ic`` is a *rolling* window
        # statistic, so consecutive entries are highly autocorrelated.
        # A naive t-test treating each entry as i.i.d. would understate
        # standard errors. Use a Newey-West HAC correction with a
        # truncation lag tied to the rolling window size to deflate the
        # t-statistic for serial dependence. In the multi-index path the
        # IC is computed cross-sectionally per date, so HAC is still a
        # safe (slightly conservative) choice.
        ic = daily_ic.values.astype(float) - mean_ic
        # Bartlett kernel; lag = floor(4*(N/100)^(2/9)) per Newey-West 1994.
        L = int(np.floor(4.0 * (n / 100.0) ** (2.0 / 9.0)))
        L = max(L, 1)
        gamma0 = float(np.dot(ic, ic) / n)
        var_hac = gamma0
        for k in range(1, min(L, n - 1) + 1):
            w = 1.0 - k / (L + 1.0)
            gamma_k = float(np.dot(ic[:-k], ic[k:]) / n)
            var_hac += 2.0 * w * gamma_k
        var_hac = max(var_hac, 0.0)
        # Std-error of the mean under HAC: sqrt(var_hac / n).
        se_mean = float(np.sqrt(var_hac / n)) if var_hac > 0.0 else 0.0
        if se_mean > 0.0:
            t_stat = mean_ic / se_mean
            p_value = 2.0 * (1.0 - stats.t.cdf(abs(t_stat), df=n - 1))
        else:
            # HAC variance collapsed (e.g. perfect autocorrelation, or all
            # IC values numerically identical). Returning ``t=inf, p=NaN``
            # would imply the mean-IC is significant under degenerate
            # variance, which is misleading. Instead, treat the test as
            # uninformative: ``t_stat = 0.0, p_value = 1.0``. This is the
            # least-information-bearing outcome and lets downstream
            # significance gates fail closed.
            t_stat = 0.0
            p_value = 1.0
    else:
        # Degenerate case (e.g. perfect correlation -> std=0). Fall back to
        # the full-sample correlation p-value so callers still get signal.
        try:
            _, p_full = corr_fn(f.values, r.values)
            p_value = float(p_full)
        except Exception:
            p_value = np.nan
        t_stat = np.inf if mean_ic != 0 else 0.0

    return ICResult(
        daily_ic=daily_ic,
        mean_ic=mean_ic,
        ic_std=ic_std,
        ic_ir=ic_ir,
        t_stat=float(t_stat),
        p_value=float(p_value),
    )


# ---------------------------------------------------------------------------
# Quantile spread
# ---------------------------------------------------------------------------

def _qcut_safe(x: pd.Series, q: int) -> pd.Series:
    """qcut that falls back to rank-based binning when ties cause errors."""
    try:
        return pd.qcut(x, q, labels=False, duplicates="drop")
    except ValueError:
        ranks = x.rank(method="first", pct=True)
        bins = np.minimum((ranks * q).astype(int), q - 1)
        return bins


def quantile_spread(factor: pd.Series,
                    prices: pd.Series,
                    n_quantiles: int = 5,
                    forward_periods=(1, 5, 20)) -> QuantileSpreadResult:
    """Bin factor into quantiles, compute long-short spread.

    Single-asset path: bin time-series factor values; for each bin and each
    forward period compute mean forward return of bars assigned to that bin.
    Spread = mean(return | top bin) - mean(return | bottom bin), per bar,
    realized as: at bar t, if factor in top bin -> +1; bottom bin -> -1;
    else 0; using period=1 for the spread time series.
    """
    forward_periods = tuple(forward_periods)
    f, p = _align(factor, prices)
    if len(f) < n_quantiles * 5:
        raise ValueError(
            f"need at least {n_quantiles * 5} obs for {n_quantiles} quantiles, got {len(f)}"
        )
    bins = _qcut_safe(f, n_quantiles)
    bins.name = "q"
    actual_q = int(bins.dropna().nunique())
    if actual_q < 2:
        raise ValueError(f"factor produced only {actual_q} quantile(s); cannot form spread")

    # Build period-returns matrix: rows = quantile, cols = period offset.
    period_data = {}
    for period in forward_periods:
        fwd = _forward_returns_from_prices(p, period)
        df = pd.concat([bins.rename("q"), fwd.rename("r")], axis=1).dropna()
        means = df.groupby("q")["r"].mean()
        period_data[period] = means
    period_returns = pd.DataFrame(period_data)
    period_returns.index.name = "quantile"

    # Spread time series uses period=1 (or shortest available period).
    base_period = min(forward_periods)
    fwd1 = _forward_returns_from_prices(p, base_period)
    df1 = pd.concat([bins.rename("q"), fwd1.rename("r")], axis=1).dropna()
    top = actual_q - 1
    bot = 0
    sig = pd.Series(0.0, index=df1.index)
    sig[df1["q"] == top] = 1.0
    sig[df1["q"] == bot] = -1.0
    spread_returns = (sig * df1["r"]).rename("spread")

    # Sharpe of spread (annualized assuming daily / period in bars).
    if spread_returns.std(ddof=1) > 0 and len(spread_returns) > 1:
        sharpe = float(
            spread_returns.mean() / spread_returns.std(ddof=1)
            * np.sqrt(252.0 / base_period)
        )
    else:
        sharpe = 0.0

    cum_spread = (1.0 + spread_returns).cumprod() - 1.0

    return QuantileSpreadResult(
        period_returns=period_returns,
        spread_returns=spread_returns,
        cum_spread=cum_spread,
        sharpe=sharpe,
        n_quantiles=actual_q,
    )


# ---------------------------------------------------------------------------
# Factor returns
# ---------------------------------------------------------------------------

def factor_returns(factor: pd.Series,
                   prices: pd.Series,
                   weight_method: str = "long_short_demeaned") -> pd.Series:
    """Construct factor portfolio returns.

    weight_method:
        'long_short_demeaned': weight = factor - factor.mean(), L1 normalized
        'top_bottom': long top quintile, short bottom quintile (equal weight)
        'equal_weight': sign(factor) only
    """
    f, p = _align(factor, prices)
    fwd1 = _forward_returns_from_prices(p, 1)

    if weight_method == "long_short_demeaned":
        demeaned = f - f.mean()
        l1 = demeaned.abs().sum()
        if l1 == 0:
            weights = pd.Series(0.0, index=f.index)
        else:
            weights = demeaned / l1
    elif weight_method == "top_bottom":
        if len(f) < 25:
            raise ValueError(f"need at least 25 obs for top/bottom quintile, got {len(f)}")
        bins = _qcut_safe(f, 5)
        actual_q = int(bins.dropna().nunique())
        weights = pd.Series(0.0, index=f.index)
        weights[bins == (actual_q - 1)] = 1.0
        weights[bins == 0] = -1.0
        l1 = weights.abs().sum()
        if l1 > 0:
            weights = weights / l1
    elif weight_method == "equal_weight":
        weights = np.sign(f)
        l1 = weights.abs().sum()
        if l1 > 0:
            weights = weights / l1
    else:
        raise ValueError(f"unknown weight_method: {weight_method!r}")

    rets = (weights * fwd1).dropna().rename("factor_return")
    return rets


# ---------------------------------------------------------------------------
# Turnover and autocorrelation
# ---------------------------------------------------------------------------

def factor_turnover(factor: pd.Series, periods=(1, 5, 20)) -> pd.Series:
    """Mean absolute change in factor rank (percentile) over given periods."""
    f = factor.dropna()
    pct_rank = f.rank(pct=True)
    out = {}
    for p in periods:
        diff = (pct_rank - pct_rank.shift(p)).abs().dropna()
        out[p] = float(diff.mean()) if len(diff) > 0 else np.nan
    s = pd.Series(out, name="turnover")
    s.index.name = "period"
    return s


def factor_autocorrelation(factor: pd.Series, lags: int = 5) -> pd.Series:
    """Autocorrelation of factor over lags 1..lags (inclusive)."""
    if lags < 1:
        raise ValueError(f"lags must be >= 1, got {lags}")
    f = factor.dropna()
    if len(f) < lags + 2:
        raise ValueError(f"need at least {lags + 2} obs, got {len(f)}")
    out = {lag: float(f.autocorr(lag=lag)) for lag in range(1, lags + 1)}
    s = pd.Series(out, name="autocorrelation")
    s.index.name = "lag"
    return s


# ---------------------------------------------------------------------------
# Summary table
# ---------------------------------------------------------------------------

def factor_summary_table(factor: pd.Series,
                         prices: pd.Series,
                         forward_periods=(1, 5, 20)) -> pd.DataFrame:
    """All-in-one summary: IC, IC_IR, p-value, quantile-spread Sharpe, turnover."""
    forward_periods = tuple(forward_periods)
    rows = {}
    turnover = factor_turnover(factor, periods=forward_periods)
    # Quantile-spread can fail on degenerate inputs (constant factor, too few
    # samples, all-NaN cols). Treat as a soft failure: emit NaN spread/sharpe
    # rather than blowing up the whole summary, so IC and turnover still
    # surface.
    try:
        qs = quantile_spread(factor, prices, n_quantiles=5,
                             forward_periods=forward_periods)
    except Exception:
        qs = None
    for period in forward_periods:
        fwd = _forward_returns_from_prices(prices, period)
        try:
            ic = information_coefficient(factor, fwd, method="spearman")
            mean_ic = ic.mean_ic
            ic_ir = ic.ic_ir
            p_value = ic.p_value
        except ValueError:
            mean_ic = ic_ir = p_value = np.nan
        # Quantile spread: each col of period_returns is a period; long-short
        # is top - bottom mean for that period.
        if qs is None:
            ls_period = np.nan
        else:
            col = qs.period_returns.get(period)
            if col is not None and len(col) >= 2:
                ls_period = float(col.iloc[-1] - col.iloc[0])
            else:
                ls_period = np.nan
        rows[period] = {
            "ic_mean": mean_ic,
            "ic_ir": ic_ir,
            "ic_p_value": p_value,
            "quantile_spread": ls_period,
            "turnover": float(turnover.get(period, np.nan)),
        }
    df = pd.DataFrame(rows).T
    df.index.name = "period"
    df["spread_sharpe"] = qs.sharpe if qs is not None else np.nan
    return df
