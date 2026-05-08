"""Bayesian rolling regression for alpha estimation.

Model
-----
For each rolling window of size W, fit
    r_strategy[t] = alpha + beta * r_benchmark[t] + e[t],   e[t] ~ N(0, sigma^2)

with normal priors on (alpha, beta) and conjugate normal-normal update.

Posterior
---------
Given a window of W observations and Gaussian priors, the posterior for
theta = [alpha, beta]^T is normal with covariance and mean

    V_post = (V_prior^-1 + (X^T X) / sigma^2)^-1
    m_post = V_post @ (V_prior^-1 @ m_prior + (X^T y) / sigma^2)

where X has rows [1, r_benchmark[t]] and y = r_strategy[t].

If observation_noise (sigma) is not provided, we estimate it inside each
window from the OLS residual std (with a small floor to avoid division by
zero on degenerate windows).

Outputs
-------
``BayesAlphaResult`` carries the full rolling posterior bands plus the
overall posterior estimate (the last window) and a t-stat
(overall_alpha_mean / overall_alpha_std).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats


__all__ = [
    "BayesAlphaModel",
    "BayesAlphaResult",
    "bayesian_rolling_alpha",
    "alpha_significance_test",
    "cumulative_alpha",
    "plot_alpha_bands",
]


@dataclass
class BayesAlphaResult:
    """Container with rolling posterior estimates.

    All series are aligned to the input index and are NaN for the first
    ``window - 1`` bars (no full window available).
    """

    alpha_mean: pd.Series
    alpha_std: pd.Series
    beta_mean: pd.Series
    beta_std: pd.Series
    alpha_ci_lower: pd.Series
    alpha_ci_upper: pd.Series
    overall_alpha_mean: float
    overall_alpha_std: float
    overall_t_stat: float


def _bayes_update(
    x: np.ndarray,
    y: np.ndarray,
    prior_mean: np.ndarray,
    prior_cov: np.ndarray,
    obs_var: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Conjugate normal-normal posterior for theta = [alpha, beta].

    Args:
        x: benchmark returns inside the window, shape (W,).
        y: strategy returns inside the window, shape (W,).
        prior_mean: shape (2,).
        prior_cov: shape (2, 2).
        obs_var: residual variance sigma^2 (must be > 0).

    Returns:
        (post_mean, post_cov), each shape (2,) and (2, 2).
    """
    X = np.column_stack([np.ones_like(x), x])  # (W, 2)
    XtX = X.T @ X
    Xty = X.T @ y

    prior_prec = np.linalg.inv(prior_cov)
    post_prec = prior_prec + XtX / obs_var
    post_cov = np.linalg.inv(post_prec)
    post_mean = post_cov @ (prior_prec @ prior_mean + Xty / obs_var)
    return post_mean, post_cov


def bayesian_rolling_alpha(
    strategy_returns: pd.Series,
    benchmark_returns: pd.Series,
    window: int = 60,
    prior_alpha_mean: float = 0.0,
    prior_alpha_std: float = 0.01,
    prior_beta_mean: float = 1.0,
    prior_beta_std: float = 0.5,
    observation_noise: Optional[float] = None,
) -> BayesAlphaResult:
    """Rolling Bayesian regression: r_strategy = alpha + beta * r_benchmark + e.

    A normal prior on (alpha, beta) is updated with each window using a
    normal observation model. Returns rolling posterior mean and std for
    both alpha and beta plus a 95% credible interval for alpha.

    Args:
        strategy_returns: strategy return series.
        benchmark_returns: benchmark return series. Must align with
            ``strategy_returns`` on the index.
        window: rolling window length (number of observations).
        prior_alpha_mean: prior mean on alpha (per-period scale).
        prior_alpha_std: prior std on alpha (per-period scale).
        prior_beta_mean: prior mean on beta.
        prior_beta_std: prior std on beta.
        observation_noise: residual std sigma. If None, estimated per
            window from OLS residuals (floor 1e-8).

    Returns:
        BayesAlphaResult with rolling posterior bands.
    """
    if window < 2:
        raise ValueError("window must be >= 2")
    # Prior covariance is built as ``diag([prior_alpha_std**2,
    # prior_beta_std**2])``. Zero or negative std collapses the prior
    # variance, which makes ``np.linalg.inv(prior_cov)`` either raise on
    # the singular matrix or, worse, silently produce non-finite values
    # that poison every rolling posterior. Reject up front.
    if not (float(prior_alpha_std) > 0.0):
        raise ValueError(
            f"prior_alpha_std must be > 0, got {prior_alpha_std!r}"
        )
    if not (float(prior_beta_std) > 0.0):
        raise ValueError(
            f"prior_beta_std must be > 0, got {prior_beta_std!r}"
        )

    s = strategy_returns.astype(float)
    b = benchmark_returns.astype(float)
    df = pd.concat([s, b], axis=1, join="inner").dropna()
    df.columns = ["s", "b"]

    if len(df) < window:
        raise ValueError(
            f"need at least {window} aligned observations, got {len(df)}"
        )

    idx = df.index
    n = len(df)

    prior_mean = np.array([prior_alpha_mean, prior_beta_mean], dtype=float)
    prior_cov = np.diag([prior_alpha_std**2, prior_beta_std**2])

    alpha_mean = np.full(n, np.nan)
    alpha_std = np.full(n, np.nan)
    beta_mean = np.full(n, np.nan)
    beta_std = np.full(n, np.nan)

    s_arr = df["s"].to_numpy()
    b_arr = df["b"].to_numpy()

    for end in range(window, n + 1):
        start = end - window
        x = b_arr[start:end]
        y = s_arr[start:end]

        if observation_noise is None:
            # Estimate sigma from OLS residual std inside the window.
            X = np.column_stack([np.ones_like(x), x])
            try:
                ols, *_ = np.linalg.lstsq(X, y, rcond=None)
                resid = y - X @ ols
                sigma = float(resid.std(ddof=1)) if len(resid) > 1 else 0.0
            except np.linalg.LinAlgError:
                # Singular X^T X (e.g., constant benchmark inside the
                # window): we cannot recover regression residuals, so use
                # the marginal standard deviation of y as an upper bound on
                # the residual std. Using y.std() / sqrt(n) (the standard
                # error of the mean) drastically *understates* sigma, which
                # makes the posterior wildly overconfident.
                n_obs = len(y)
                if n_obs > 1:
                    sigma = float(y.std(ddof=1))
                else:
                    sigma = 0.0
            # Data-scaled floor so very high-magnitude returns don't end up
            # with an artificially tiny sigma when residuals happen to collapse
            # toward zero (e.g. flat regression inside the window).
            sigma = max(sigma, max(1e-8, 1e-3 * float(np.abs(y).max())))
            obs_var = sigma * sigma
        else:
            obs_var = float(observation_noise) ** 2

        post_mean, post_cov = _bayes_update(x, y, prior_mean, prior_cov, obs_var)
        i = end - 1
        alpha_mean[i] = post_mean[0]
        beta_mean[i] = post_mean[1]
        alpha_std[i] = np.sqrt(max(post_cov[0, 0], 0.0))
        beta_std[i] = np.sqrt(max(post_cov[1, 1], 0.0))

    z = stats.norm.ppf(0.975)
    alpha_ci_lower = alpha_mean - z * alpha_std
    alpha_ci_upper = alpha_mean + z * alpha_std

    last = n - 1
    overall_alpha_mean = float(alpha_mean[last])
    overall_alpha_std = float(alpha_std[last])
    overall_t_stat = (
        overall_alpha_mean / overall_alpha_std
        if overall_alpha_std > 1e-12
        else 0.0
    )

    return BayesAlphaResult(
        alpha_mean=pd.Series(alpha_mean, index=idx, name="alpha_mean"),
        alpha_std=pd.Series(alpha_std, index=idx, name="alpha_std"),
        beta_mean=pd.Series(beta_mean, index=idx, name="beta_mean"),
        beta_std=pd.Series(beta_std, index=idx, name="beta_std"),
        alpha_ci_lower=pd.Series(alpha_ci_lower, index=idx, name="alpha_ci_lower"),
        alpha_ci_upper=pd.Series(alpha_ci_upper, index=idx, name="alpha_ci_upper"),
        overall_alpha_mean=overall_alpha_mean,
        overall_alpha_std=overall_alpha_std,
        overall_t_stat=float(overall_t_stat),
    )


class BayesAlphaModel:
    """Thin class wrapper over :func:`bayesian_rolling_alpha`.

    Provides a sklearn-style ``fit`` interface for callers that prefer a
    model object over a free function. Holds prior + window parameters
    on the instance and stashes the latest :class:`BayesAlphaResult` on
    ``result_`` after :meth:`fit`.
    """

    def __init__(
        self,
        window: int = 60,
        prior_alpha_mean: float = 0.0,
        prior_alpha_std: float = 0.01,
        prior_beta_mean: float = 1.0,
        prior_beta_std: float = 0.5,
        observation_noise: Optional[float] = None,
    ) -> None:
        self.window = window
        self.prior_alpha_mean = prior_alpha_mean
        self.prior_alpha_std = prior_alpha_std
        self.prior_beta_mean = prior_beta_mean
        self.prior_beta_std = prior_beta_std
        self.observation_noise = observation_noise
        self.result_: Optional[BayesAlphaResult] = None

    def fit(
        self,
        strategy_returns: pd.Series,
        benchmark_returns: pd.Series,
    ) -> BayesAlphaResult:
        """Run :func:`bayesian_rolling_alpha` with the configured priors."""
        self.result_ = bayesian_rolling_alpha(
            strategy_returns,
            benchmark_returns,
            window=self.window,
            prior_alpha_mean=self.prior_alpha_mean,
            prior_alpha_std=self.prior_alpha_std,
            prior_beta_mean=self.prior_beta_mean,
            prior_beta_std=self.prior_beta_std,
            observation_noise=self.observation_noise,
        )
        return self.result_


def alpha_significance_test(
    result: BayesAlphaResult,
    threshold: float = 0.0,
) -> pd.Series:
    """Per-bar P(alpha > threshold) under the rolling posterior.

    Uses the normal posterior CDF: 1 - Phi((threshold - mean) / std).
    NaN where the rolling estimate is NaN.
    """
    mean = result.alpha_mean
    std = result.alpha_std
    z = (threshold - mean) / std.replace(0.0, np.nan)
    prob = 1.0 - pd.Series(stats.norm.cdf(z.to_numpy()), index=mean.index)
    prob = prob.where(~mean.isna(), other=np.nan)
    prob.name = "alpha_prob_gt_threshold"
    return prob


def cumulative_alpha(result: BayesAlphaResult) -> pd.Series:
    """Cumulative alpha (compounded posterior mean).

    Treats ``alpha_mean[t]`` as a per-period excess return and returns
    ``cumprod(1 + alpha_mean) - 1`` over non-NaN bars; NaN where the
    rolling alpha is NaN.
    """
    a = result.alpha_mean.copy()
    valid = ~a.isna()
    cum = pd.Series(np.nan, index=a.index, name="cumulative_alpha")
    if valid.any():
        cum.loc[valid] = np.cumprod(1.0 + a.loc[valid].to_numpy()) - 1.0
    return cum


def plot_alpha_bands(
    result: BayesAlphaResult,
    output_path: Optional[str] = None,
) -> Optional[str]:
    """Plot rolling alpha mean + 95% CI bands.

    Returns the saved path when ``output_path`` is provided, else None.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    mean = result.alpha_mean
    lo = result.alpha_ci_lower
    hi = result.alpha_ci_upper

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(mean.index, mean.to_numpy(), color="#1f77b4", label="alpha (posterior mean)")
    ax.fill_between(
        mean.index,
        lo.to_numpy(),
        hi.to_numpy(),
        color="#1f77b4",
        alpha=0.2,
        label="95% CI",
    )
    ax.axhline(0.0, color="black", linewidth=0.8, linestyle="--")
    ax.set_title("Rolling Bayesian alpha (posterior mean +/- 95% CI)")
    ax.set_xlabel("date")
    ax.set_ylabel("alpha (per period)")
    ax.legend(loc="best")
    fig.tight_layout()

    if output_path is None:
        plt.close(fig)
        return None

    fig.savefig(output_path, dpi=120)
    plt.close(fig)
    return output_path
