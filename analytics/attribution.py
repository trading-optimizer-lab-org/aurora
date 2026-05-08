"""Performance attribution.

Decomposes portfolio / strategy returns by source:
- by_strategy: contribution of each strategy in a meta-portfolio (from AllocatorResult).
- by_factor:   factor-model decomposition (OLS or non-negative constrained least-squares).
- by_time:     per-regime performance (groupby on regime label series).
- brinson:     classic Brinson 1985 single-period allocation/selection/interaction.

References:
- Brinson, Hood, Beebower (1985), "Determinants of Portfolio Performance".
- pyfolio (Quantopian) — single-factor and rolling-attribution patterns.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import math
import numpy as np
import pandas as pd
from scipy import optimize


# --------------------------------------------------------------------------- #
# Result container                                                            #
# --------------------------------------------------------------------------- #
@dataclass
class AttributionResult:
    """Output of any attribution_* function.

    Attributes:
        method: short tag, e.g. 'by_strategy', 'factor_ols', 'by_time', 'brinson'.
        contributions: per-row metrics (rows = category, cols = metric).
        summary: aggregate per category (1-D series).
        total: scalar total (sum of summary, or alpha for factor models).
    """
    method: str
    contributions: pd.DataFrame
    summary: pd.Series
    total: float


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #
def _safe_sharpe(r: np.ndarray, ppy: int) -> float:
    """Annualized Sharpe; 0 if std too small or insufficient data."""
    if r.size < 2:
        return 0.0
    mu = float(r.mean())
    sd = float(r.std(ddof=1))
    if sd <= 1e-12:
        return 0.0
    return (mu / sd) * math.sqrt(ppy)


def _safe_mdd(r: np.ndarray) -> float:
    """Max drawdown of a returns series (negative number)."""
    if r.size < 2:
        return 0.0
    nav = np.cumprod(1.0 + r)
    cummax = np.maximum.accumulate(nav)
    dd = (nav - cummax) / np.maximum(cummax, 1e-12)
    return float(dd.min())


# --------------------------------------------------------------------------- #
# 1. Strategy attribution                                                     #
# --------------------------------------------------------------------------- #
def attribution_by_strategy(allocator_result, ppy: int = 252) -> AttributionResult:
    """Per-strategy contribution to a meta-portfolio.

    Args:
        allocator_result: any object with the AllocatorResult duck-type:
            - per_strategy_attribution: dict[name -> float] (total contribution sum)
            - per_strategy_returns:     dict[name -> 1-D array of per-bar contributions]
            - (optional) weights:       (T, N) ndarray
            - (optional) strategy_names: list of names ordered as cols of weights
        ppy: periods per year for Sharpe annualization.

    Returns:
        AttributionResult with:
            contributions: DataFrame[strategy_name -> {total_return, sharpe, mdd, weight_avg}]
            summary:       Series of total contributions
            total:         sum of contributions (= portfolio cumulative arith return)
    """
    # Explicit runtime check — duck-type protocol for AllocatorResult.
    # Required attributes: per_strategy_attribution (mapping name -> float),
    #                      per_strategy_returns     (mapping name -> 1-D array).
    # Optional attributes: weights (T x N ndarray), strategy_names (list[str]).
    required = ("per_strategy_attribution", "per_strategy_returns")
    missing = [a for a in required if not hasattr(allocator_result, a)]
    if missing:
        raise TypeError(
            f"attribution_by_strategy: allocator_result is missing required "
            f"attribute(s) {missing}. Expected an AllocatorResult-like object "
            f"with `per_strategy_attribution: dict[str, float]` and "
            f"`per_strategy_returns: dict[str, np.ndarray]` "
            f"(optional: weights, strategy_names). "
            f"Got type {type(allocator_result).__name__}."
        )
    contrib_dict = dict(allocator_result.per_strategy_attribution)
    rets_dict = {k: np.asarray(v, dtype=float)
                 for k, v in allocator_result.per_strategy_returns.items()}

    names = list(contrib_dict.keys())

    # weight averages, if available
    weight_avg = {n: float("nan") for n in names}
    weights = getattr(allocator_result, "weights", None)
    strat_names = getattr(allocator_result, "strategy_names", None)
    if weights is not None and strat_names is not None:
        weights = np.asarray(weights, dtype=float)
        if weights.ndim == 2 and weights.shape[1] == len(strat_names):
            for j, n in enumerate(strat_names):
                if n in weight_avg:
                    weight_avg[n] = float(weights[:, j].mean())

    rows = []
    for n in names:
        r = rets_dict.get(n, np.zeros(0, dtype=float))
        rows.append({
            "total_return": float(contrib_dict[n]),
            "sharpe":       _safe_sharpe(r, ppy),
            "mdd":          _safe_mdd(r),
            "weight_avg":   weight_avg[n],
        })

    df = pd.DataFrame(rows, index=names)
    summary = df["total_return"].copy()
    return AttributionResult(
        method="by_strategy",
        contributions=df,
        summary=summary,
        total=float(summary.sum()),
    )


# --------------------------------------------------------------------------- #
# 2. Factor attribution                                                       #
# --------------------------------------------------------------------------- #
def attribution_by_factor(returns: pd.Series,
                          factor_returns_dict: dict,
                          method: str = "ols") -> AttributionResult:
    """Factor decomposition: regress strategy returns on factor returns.

    OLS:
        r_t = alpha + sum_k beta_k * f_{k,t} + eps_t
        attribution_k = beta_k * mean(f_k) * T  (total contribution over the sample)

    Constrained:
        Same model but beta_k >= 0 (non-negative least squares), no intercept fit.
        alpha is then defined as mean(r) - sum_k beta_k * mean(f_k), reported in `total`.

    Args:
        returns: pd.Series of strategy returns (DatetimeIndex preferred).
        factor_returns_dict: dict[factor_name -> pd.Series].
        method: 'ols' (with intercept) or 'constrained' (NNLS, no negative betas).

    Returns:
        AttributionResult with:
            contributions: DataFrame[factor_name -> {beta, t_stat, attribution, r_squared_partial}]
            summary:       Series of factor attributions
            total:         alpha (intercept * T for OLS, or implied alpha for constrained)
    """
    if method not in ("ols", "constrained"):
        raise ValueError(f"unknown method: {method}, valid: ols | constrained")
    if not isinstance(returns, pd.Series):
        raise TypeError("returns must be pd.Series")
    if not factor_returns_dict:
        raise ValueError("factor_returns_dict is empty")

    # Align everything on the strategy returns index
    aligned = pd.DataFrame({"y": returns})
    for k, fs in factor_returns_dict.items():
        if not isinstance(fs, pd.Series):
            raise TypeError(f"factor_returns_dict[{k}] must be pd.Series")
        aligned[k] = fs
    aligned = aligned.dropna()
    if len(aligned) < 5:
        raise ValueError(f"too few aligned bars: {len(aligned)} (need >= 5)")

    factor_names = [k for k in factor_returns_dict.keys()]
    y = aligned["y"].values.astype(float)
    F = aligned[factor_names].values.astype(float)
    T = len(y)
    K = len(factor_names)

    if method == "ols":
        # Design matrix with intercept
        X = np.column_stack([np.ones(T), F])
        # Least-squares solution
        coef, *_ = np.linalg.lstsq(X, y, rcond=None)
        alpha = float(coef[0])
        betas = coef[1:].astype(float)

        resid = y - X @ coef
        rss = float(resid @ resid)
        tss = float(((y - y.mean()) ** 2).sum())
        r2_full = 1.0 - rss / tss if tss > 1e-18 else 0.0

        # Standard errors: sigma^2 * (X^T X)^-1
        dof = max(T - (K + 1), 1)
        sigma2 = rss / dof
        try:
            xtx_inv = np.linalg.inv(X.T @ X)
            se = np.sqrt(np.maximum(np.diag(xtx_inv) * sigma2, 0.0))
        except np.linalg.LinAlgError:
            se = np.full(K + 1, np.nan)
        t_stats = np.where(se[1:] > 1e-18, betas / np.maximum(se[1:], 1e-18), 0.0)

        # Partial R^2 per factor: drop column k, refit, see R^2 drop
        partial_r2 = np.zeros(K)
        for j in range(K):
            cols = [0] + [1 + i for i in range(K) if i != j]
            X_red = X[:, cols]
            coef_red, *_ = np.linalg.lstsq(X_red, y, rcond=None)
            resid_red = y - X_red @ coef_red
            rss_red = float(resid_red @ resid_red)
            r2_red = 1.0 - rss_red / tss if tss > 1e-18 else 0.0
            partial_r2[j] = max(r2_full - r2_red, 0.0)

        # Attribution = beta_k * sum(f_k_t) (total contribution over the sample)
        f_sums = F.sum(axis=0)
        attribution = betas * f_sums

        rows = {
            "beta":               betas,
            "t_stat":             t_stats,
            "attribution":        attribution,
            "r_squared_partial":  partial_r2,
        }
        df = pd.DataFrame(rows, index=factor_names)
        summary = df["attribution"].copy()
        total = alpha * T  # intercept contribution over the sample
        return AttributionResult(
            method="factor_ols",
            contributions=df,
            summary=summary,
            total=float(total),
        )

    # Constrained / NNLS: beta >= 0, no intercept in the fit
    coef, _ = optimize.nnls(F, y)
    betas = coef.astype(float)
    resid = y - F @ betas
    rss = float(resid @ resid)
    tss = float(((y - y.mean()) ** 2).sum())
    r2_full = 1.0 - rss / tss if tss > 1e-18 else 0.0

    dof = max(T - K, 1)
    sigma2 = rss / dof
    try:
        ftf_inv = np.linalg.inv(F.T @ F)
        se = np.sqrt(np.maximum(np.diag(ftf_inv) * sigma2, 0.0))
    except np.linalg.LinAlgError:
        se = np.full(K, np.nan)
    t_stats = np.where(se > 1e-18, betas / np.maximum(se, 1e-18), 0.0)
    # Boundary betas (NNLS clamped at zero) violate the OLS asymptotics
    # that justify treating ``beta / se`` as a t-statistic. Flag those
    # cells as NaN so downstream callers don't read significance into a
    # boundary solution.
    boundary_mask = np.isclose(betas, 0.0)
    t_stats = np.where(boundary_mask, np.nan, t_stats)

    partial_r2 = np.zeros(K)
    for j in range(K):
        cols = [i for i in range(K) if i != j]
        if not cols:
            partial_r2[j] = r2_full
            continue
        F_red = F[:, cols]
        coef_red, _ = optimize.nnls(F_red, y)
        resid_red = y - F_red @ coef_red
        rss_red = float(resid_red @ resid_red)
        r2_red = 1.0 - rss_red / tss if tss > 1e-18 else 0.0
        partial_r2[j] = max(r2_full - r2_red, 0.0)

    f_sums = F.sum(axis=0)
    attribution = betas * f_sums

    df = pd.DataFrame(
        {
            "beta":               betas,
            "t_stat":             t_stats,
            "attribution":        attribution,
            "r_squared_partial":  partial_r2,
        },
        index=factor_names,
    )
    summary = df["attribution"].copy()
    # Implied alpha = total return not explained by factor exposures
    implied_alpha_total = float(y.sum() - attribution.sum())
    return AttributionResult(
        method="factor_constrained",
        contributions=df,
        summary=summary,
        total=implied_alpha_total,
    )


# --------------------------------------------------------------------------- #
# 3. Time / regime attribution                                                #
# --------------------------------------------------------------------------- #
def attribution_by_time(returns: pd.Series,
                        regime_labels: pd.Series,
                        ppy: int = 252) -> AttributionResult:
    """Group returns by regime label and report per-regime stats.

    Args:
        returns: pd.Series of returns (DatetimeIndex preferred).
        regime_labels: pd.Series of regime label per timestep
                       (e.g. 'bull' / 'bear', or arbitrary categorical).
        ppy: periods per year for Sharpe annualization.

    Returns:
        AttributionResult with:
            contributions: DataFrame[regime -> {n, total_return, mean_return, sharpe, mdd, share}]
            summary:       Series of total returns per regime
            total:         total cumulative arith return across all bars
    """
    if not isinstance(returns, pd.Series):
        raise TypeError("returns must be pd.Series")
    if not isinstance(regime_labels, pd.Series):
        raise TypeError("regime_labels must be pd.Series")

    df = pd.concat([returns.rename("y"), regime_labels.rename("regime")], axis=1).dropna()
    if df.empty:
        raise ValueError("no overlapping bars between returns and regime_labels")

    grand_total = float(df["y"].sum())
    rows = {}
    # ``observed=True`` keeps groupby from emitting empty groups for unused
    # categorical levels (which would surface as NaN-filled rows downstream)
    # and silences the pandas FutureWarning about the default flipping.
    for regime, sub in df.groupby("regime", observed=True):
        r = sub["y"].values.astype(float)
        n = int(r.size)
        total_r = float(r.sum())
        rows[regime] = {
            "n":            n,
            "total_return": total_r,
            "mean_return":  float(r.mean()) if n else 0.0,
            "sharpe":       _safe_sharpe(r, ppy),
            "mdd":          _safe_mdd(r),
            "share":        total_r / grand_total if abs(grand_total) > 1e-18 else 0.0,
        }

    contrib = pd.DataFrame.from_dict(rows, orient="index")
    contrib.index.name = "regime"
    summary = contrib["total_return"].copy()
    return AttributionResult(
        method="by_time",
        contributions=contrib,
        summary=summary,
        total=grand_total,
    )


# --------------------------------------------------------------------------- #
# 4. Brinson single-period attribution                                        #
# --------------------------------------------------------------------------- #
def brinson_attribution(weights: pd.DataFrame,
                        benchmark_weights: pd.DataFrame,
                        returns: pd.DataFrame,
                        portfolio_returns: Optional[pd.DataFrame] = None) -> AttributionResult:
    """Brinson (1985) single-period attribution.

    Decomposes excess return r_p - r_b into per-category effects. The
    allocation effect is taken relative to the period benchmark return so
    the per-period contributions sum to ``(w_p - w_b) . (r_b - r_b_total)``,
    which is unbiased to a uniform shift in benchmark returns:

        r_b_total_t  = sum_j w_b_t_j * r_b_t_j
        allocation_i = (w_p_i - w_b_i) * (r_b_i - r_b_total)
        selection_i  = w_b_i * (r_p_i - r_b_i)
        interaction_i = (w_p_i - w_b_i) * (r_p_i - r_b_i)

    Args:
        weights:            DataFrame[time, category] portfolio weights.
        benchmark_weights:  same shape — benchmark weights.
        returns:            DataFrame[time, category] benchmark category
                            returns (r_b_i).
        portfolio_returns:  DataFrame[time, category] portfolio realized
                            category returns (r_p_i). When omitted the
                            decomposition reduces to *allocation only*: the
                            ``selection`` and ``interaction`` columns are
                            included as zeros for backward compatibility but
                            cannot be interpreted as a true selection effect.

    Returns:
        AttributionResult with:
            contributions: DataFrame[category -> {allocation, selection, interaction, total}]
            summary:       Series of total per-category effect (alloc + sel + inter)
            total:         total excess return = sum of total per-category effects
            method:        ``"brinson"`` when ``portfolio_returns`` provided,
                           otherwise ``"brinson_allocation_only"``.
    """
    if not isinstance(weights, pd.DataFrame):
        raise TypeError("weights must be pd.DataFrame")
    if not isinstance(benchmark_weights, pd.DataFrame):
        raise TypeError("benchmark_weights must be pd.DataFrame")
    if not isinstance(returns, pd.DataFrame):
        raise TypeError("returns must be pd.DataFrame")
    if portfolio_returns is not None and not isinstance(portfolio_returns, pd.DataFrame):
        raise TypeError("portfolio_returns must be pd.DataFrame")

    # Align indices and columns
    common_cols = sorted(
        set(weights.columns) & set(benchmark_weights.columns) & set(returns.columns)
    )
    if portfolio_returns is not None:
        common_cols = sorted(set(common_cols) & set(portfolio_returns.columns))
    if not common_cols:
        raise ValueError("no shared categories across weights / benchmark / returns")
    common_idx = weights.index.intersection(benchmark_weights.index).intersection(returns.index)
    if portfolio_returns is not None:
        common_idx = common_idx.intersection(portfolio_returns.index)
    if len(common_idx) == 0:
        raise ValueError("no shared timestamps across weights / benchmark / returns")

    w_p = weights.loc[common_idx, common_cols].values.astype(float)
    w_b = benchmark_weights.loc[common_idx, common_cols].values.astype(float)
    r_b = returns.loc[common_idx, common_cols].values.astype(float)

    method = "brinson"
    if portfolio_returns is not None:
        r_p = portfolio_returns.loc[common_idx, common_cols].values.astype(float)
    else:
        # Allocation-only decomposition. With r_p == r_b, selection and
        # interaction collapse to zero by construction; flag this in the
        # method tag so downstream callers can warn.
        r_p = r_b
        method = "brinson_allocation_only"

    # Per-period benchmark return r_b_total_t = sum_j w_b_t_j * r_b_t_j.
    # Subtracting it from r_b in the allocation term centres the bench
    # return per period so a uniform shift in benchmark returns does not
    # leak into the allocation effect; instead, only the active weight
    # tilt against the average benchmark return is captured.
    r_b_total = (w_b * r_b).sum(axis=1)
    alloc = (w_p - w_b) * (r_b - r_b_total[:, None])
    selection = w_b * (r_p - r_b)
    interaction = (w_p - w_b) * (r_p - r_b)

    alloc_sum = alloc.sum(axis=0)
    sel_sum = selection.sum(axis=0)
    inter_sum = interaction.sum(axis=0)
    total_sum = alloc_sum + sel_sum + inter_sum

    df = pd.DataFrame(
        {
            "allocation":  alloc_sum,
            "selection":   sel_sum,
            "interaction": inter_sum,
            "total":       total_sum,
        },
        index=common_cols,
    )
    summary = df["total"].copy()
    return AttributionResult(
        method=method,
        contributions=df,
        summary=summary,
        total=float(summary.sum()),
    )


# --------------------------------------------------------------------------- #
# 5. Annualization helper                                                     #
# --------------------------------------------------------------------------- #
def annualized_attribution(daily_attribution: pd.Series, ppy: int = 252) -> float:
    """Annualize a per-bar attribution series.

    Treats the input as additive per-bar contributions (linear, not geometric):
        annualized = mean(daily_attribution) * ppy

    Args:
        daily_attribution: pd.Series of per-bar attribution values.
        ppy: periods per year (default 252).

    Returns:
        Annualized attribution as a float.
    """
    if not isinstance(daily_attribution, pd.Series):
        raise TypeError("daily_attribution must be pd.Series")
    arr = daily_attribution.dropna().values.astype(float)
    if arr.size == 0:
        return 0.0
    return float(arr.mean() * ppy)
