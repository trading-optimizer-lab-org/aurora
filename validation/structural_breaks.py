"""Structural break tests: Chow, CUSUM, SADF.

References:
    Chow, G.C. (1960). Tests of Equality Between Sets of Coefficients in Two Linear Regressions.
    Brown, R.L., Durbin, J., Evans, J.M. (1975). Techniques for Testing the Constancy of
        Regression Relationships over Time.
    Phillips, P.C.B., Shi, S., Yu, J. (2015). Testing for Multiple Bubbles: Historical
        Episodes of Exuberance and Collapse in the S&P 500.
    Lopez de Prado, M. (2018). Advances in Financial Machine Learning, Ch. 17 & Ch. 2 sec. 5.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------

@dataclass
class ChowResult:
    breakpoint: int
    f_stat: float
    p_value: float
    rss_full: float
    rss_split: float

    @property
    def has_break(self) -> bool:
        return self.p_value < 0.05


@dataclass
class CUSUMResult:
    test_stats: pd.Series          # CUSUM stat over time
    break_dates: pd.DatetimeIndex  # dates where stat exceeded threshold
    threshold: float

    @property
    def has_break(self) -> bool:
        return len(self.break_dates) > 0


@dataclass
class SADFResult:
    sadf_series: pd.Series
    break_date: Optional[pd.Timestamp]
    critical_value: float

    @property
    def has_break(self) -> bool:
        return self.break_date is not None


# ---------------------------------------------------------------------------
# Chow test
# ---------------------------------------------------------------------------

def chow_test(returns: pd.Series, breakpoint: int) -> ChowResult:
    """Chow test for structural break at known breakpoint.

    Tests whether the constant-mean model has the same intercept before and
    after the breakpoint index. Uses the standard F-statistic:

        F = ((RSS_p - (RSS_1 + RSS_2)) / k) / ((RSS_1 + RSS_2) / (n - 2k))

    with k=1 regressor (constant) and n total observations.
    """
    if not isinstance(returns, pd.Series):
        raise TypeError("returns must be a pandas Series")
    y = returns.dropna().to_numpy(dtype=float)
    n = y.size
    k = 1
    # Tighter lower bound: each side of the breakpoint must have enough
    # observations to estimate its mean (and the lag structure if any).
    lags = 0  # constant-mean Chow uses no lagged regressors here.
    lower = max(2, lags + 1)
    if not (lower <= breakpoint < n - 1):
        raise ValueError(
            f"breakpoint must be in [{lower}, n-2]; got {breakpoint} for n={n}"
        )
    # Pooled (no break) constant-mean model: mean = mean(y).
    mu_full = y.mean()
    rss_full = float(np.sum((y - mu_full) ** 2))

    y1, y2 = y[:breakpoint], y[breakpoint:]
    rss1 = float(np.sum((y1 - y1.mean()) ** 2))
    rss2 = float(np.sum((y2 - y2.mean()) ** 2))
    rss_split = rss1 + rss2

    df_num = k
    df_den = n - 2 * k
    if df_den <= 0 or rss_split <= 0:
        return ChowResult(
            breakpoint=breakpoint, f_stat=float("nan"), p_value=float("nan"),
            rss_full=rss_full, rss_split=rss_split,
        )
    numer = (rss_full - rss_split) / df_num
    denom = rss_split / df_den
    # Numerical guard: rounding can push numer slightly negative when there is
    # truly no break.
    f_stat = max(numer / denom, 0.0)
    p_value = float(stats.f.sf(f_stat, df_num, df_den))
    return ChowResult(
        breakpoint=breakpoint, f_stat=float(f_stat), p_value=p_value,
        rss_full=rss_full, rss_split=rss_split,
    )


# ---------------------------------------------------------------------------
# CUSUM filter (Lopez de Prado AFML Ch.2 sec. 2.5)
# ---------------------------------------------------------------------------

def cusum_filter(returns: pd.Series, threshold: float = 0.05) -> CUSUMResult:
    """Symmetric CUSUM filter for structural breaks (event-based).

    Maintains two running sums S_pos (>=0) and S_neg (<=0). When either
    exceeds the threshold in absolute terms, an event is logged and the
    corresponding sum is reset to zero.

    Args:
        returns: log returns series.
        threshold: abs value the cumulative sum must exceed to trigger.

    Returns:
        CUSUMResult with per-bar test stat (max(|S_pos|, |S_neg|)) and the
        index of detected events.
    """
    if not isinstance(returns, pd.Series):
        raise TypeError("returns must be a pandas Series")
    if threshold <= 0:
        raise ValueError("threshold must be positive")

    s_pos = 0.0
    s_neg = 0.0
    stats_arr = np.zeros(len(returns), dtype=float)
    event_idx: list = []

    values = returns.to_numpy(dtype=float)
    for i, r in enumerate(values):
        if not np.isfinite(r):
            stats_arr[i] = max(abs(s_pos), abs(s_neg))
            continue
        s_pos = max(0.0, s_pos + r)
        s_neg = min(0.0, s_neg + r)
        stats_arr[i] = max(abs(s_pos), abs(s_neg))
        if s_neg < -threshold:
            event_idx.append(returns.index[i])
            s_neg = 0.0
        elif s_pos > threshold:
            event_idx.append(returns.index[i])
            s_pos = 0.0

    test_stats = pd.Series(stats_arr, index=returns.index, name="cusum")
    if len(event_idx) > 0:
        break_dates = pd.DatetimeIndex(event_idx) if isinstance(
            returns.index, pd.DatetimeIndex
        ) else pd.Index(event_idx)
    else:
        break_dates = pd.DatetimeIndex([]) if isinstance(
            returns.index, pd.DatetimeIndex
        ) else pd.Index([])
    return CUSUMResult(test_stats=test_stats, break_dates=break_dates,
                       threshold=float(threshold))


# ---------------------------------------------------------------------------
# SADF test (Phillips-Shi-Yu 2015)
# ---------------------------------------------------------------------------

def _adf_t_stat(y: np.ndarray, lags: int, model: str) -> float:
    """Augmented Dickey-Fuller t-stat on the lagged level coefficient.

    Regression: dY_t = alpha [+ beta * t] + rho * Y_{t-1} + sum_i gamma_i dY_{t-i} + e_t
    Null hypothesis rho = 0; ADF stat is t-stat on rho. Higher (more positive)
    rho => more explosive behaviour, which is the SADF supremum direction.
    """
    n = y.size
    if n <= lags + 2:
        return float("nan")
    dy = np.diff(y)                       # length n-1
    y_lag = y[:-1]                        # length n-1
    start = lags                          # need 'lags' lagged differences
    target = dy[start:]                   # dependent var
    rows = target.size
    if rows <= 0:
        return float("nan")

    # Build design matrix.
    cols = [np.ones(rows)]
    if model == "linear":
        cols.append(np.arange(rows, dtype=float))
    elif model != "constant":
        raise ValueError(f"model must be 'constant' or 'linear', got {model!r}")
    cols.append(y_lag[start:])            # the rho column
    rho_col_idx = len(cols) - 1
    for j in range(1, lags + 1):
        cols.append(dy[start - j: start - j + rows])

    X = np.column_stack(cols)
    if X.shape[0] <= X.shape[1]:
        return float("nan")

    # OLS.
    beta, *_ = np.linalg.lstsq(X, target, rcond=None)
    resid = target - X @ beta
    dof = X.shape[0] - X.shape[1]
    if dof <= 0:
        return float("nan")
    sigma2 = float(resid @ resid) / dof
    try:
        XtX_inv = np.linalg.inv(X.T @ X)
    except np.linalg.LinAlgError:
        return float("nan")
    var_beta = sigma2 * XtX_inv[rho_col_idx, rho_col_idx]
    if var_beta <= 0 or not np.isfinite(var_beta):
        return float("nan")
    return float(beta[rho_col_idx] / np.sqrt(var_beta))


def sadf_test(prices: pd.Series, lags: int = 5, min_window: int = 60,
              model: str = "constant",
              crit_values: Optional[dict] = None,
              early_stop: bool = False) -> SADFResult:
    """Supremum Augmented Dickey-Fuller test (Phillips-Shi-Yu 2015).

    For each end-point t >= min_window, run ADF on every sub-sample
    [s : t+1] for s in [0, t - min_window] and take the supremum of the
    resulting t-stats. Higher SADF indicates explosive / bubble regime.

    .. warning::
        The default 95% critical values (1.49 for ``constant``, 1.95 for
        ``linear``) are taken from Phillips-Shi-Yu 2015 Table 1 for **T = 200**.
        For materially different sample sizes (e.g. T < 100 or T > 1000)
        these defaults are inaccurate — pass ``crit_values`` to override
        them with values appropriate to the actual ``T``.

    Args:
        prices: log price series.
        lags: AR lags in the ADF specification.
        min_window: minimum sub-sample size.
        model: 'constant' or 'linear' regression specification.
        crit_values: optional override mapping ``{"constant": float,
            "linear": float}``. Either or both keys may be supplied.
        early_stop: when True, terminate the rolling SADF as soon as the
            statistic exceeds the chosen critical value at any end-point.
            Subsequent end-points are left as NaN. Useful when the caller
            only needs the FIRST break date and runtime is dominated by the
            inner ADF sub-sample sweep. Default False (legacy behaviour:
            compute SADF for every end-point).

    Returns:
        SADFResult with rolling SADF stat (NaN during warm-up) and the first
        date the stat crosses the chosen critical value.
    """
    if not isinstance(prices, pd.Series):
        raise TypeError("prices must be a pandas Series")
    if min_window < lags + 5:
        raise ValueError("min_window must be > lags + 5")
    # pos_map below would silently collapse duplicate index entries to the
    # last-seen position, mis-aligning sadf values with their dates.
    if not prices.index.is_unique:
        raise ValueError("prices.index must be unique")

    y_full = prices.dropna().to_numpy(dtype=float)
    n = y_full.size
    sadf = np.full(len(prices), np.nan, dtype=float)

    # Map dropna index back to original positions.
    valid_index = prices.dropna().index
    pos_map = {idx: i for i, idx in enumerate(prices.index)}
    valid_positions = [pos_map[i] for i in valid_index]

    # 95% asymptotic critical values from Phillips-Shi-Yu 2015 Table 1 at
    # T = 200. Override via ``crit_values`` for materially different sample
    # sizes — the defaults are not accurate at T < 100 or T > 1000.
    crit_constant = 1.49
    crit_linear = 1.95
    if crit_values is not None:
        if not isinstance(crit_values, dict):
            raise TypeError("crit_values must be a dict")
        if "constant" in crit_values:
            crit_constant = float(crit_values["constant"])
        if "linear" in crit_values:
            crit_linear = float(crit_values["linear"])
    critical = crit_linear if model == "linear" else crit_constant

    for t in range(min_window, n):
        sub_stats: list[float] = []
        # Slide start point so each sub-sample length >= min_window.
        for s in range(0, t - min_window + 1):
            sub = y_full[s: t + 1]
            stat = _adf_t_stat(sub, lags=lags, model=model)
            if np.isfinite(stat):
                sub_stats.append(stat)
        if sub_stats:
            cur_max = max(sub_stats)
            sadf[valid_positions[t]] = cur_max
            if early_stop and cur_max > critical:
                # Stop the outer end-point sweep; remaining bars stay NaN.
                # Caller only needs the first break date in this mode.
                break

    sadf_series = pd.Series(sadf, index=prices.index, name="sadf")
    break_date: Optional[pd.Timestamp] = None
    crossing = sadf_series.dropna()[sadf_series.dropna() > critical]
    if len(crossing) > 0:
        break_date = crossing.index[0]
    return SADFResult(sadf_series=sadf_series, break_date=break_date,
                      critical_value=float(critical))
