"""Markov regime-switching mean strategy (Hamilton 1989).

Wraps statsmodels.tsa.regime_switching.MarkovRegression for robust EM fitting.
Falls back to manual EM if statsmodels unavailable.

Model:
    r_t = mu_{S_t} + sigma_{S_t} * eps_t
    S_t ~ Markov chain with transition matrix P

After fit(), regimes are reordered ascending by mean so:
    regime 0 = lowest mean (bearish), regime K-1 = highest mean (bullish).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from aurora.core.logging import get_logger

_log = get_logger("regime.markov_switching")

try:
    from statsmodels.tsa.regime_switching.markov_regression import (
        MarkovRegression as _SmMarkovRegression,
    )
    _HAS_STATSMODELS = True
except ImportError:  # pragma: no cover
    _SmMarkovRegression = None  # type: ignore
    _HAS_STATSMODELS = False


# ----------------------------- result container -----------------------------


@dataclass
class MarkovSwitchResult:
    """Container for fitted Markov-switching diagnostics."""

    n_regimes: int
    regime_means: np.ndarray
    regime_vols: np.ndarray
    transition_matrix: np.ndarray
    smoothed_probs: pd.DataFrame
    filtered_probs: pd.DataFrame
    most_likely_regime: pd.Series
    log_likelihood: float


# ----------------------------- helpers -------------------------------------


def _as_returns(returns: pd.Series) -> tuple[np.ndarray, pd.Index]:
    """Coerce returns Series to 1D float array, drop NaN, return clean index."""
    s = pd.Series(returns).astype(float).dropna()
    if len(s) < 20:
        raise ValueError(
            f"Need >= 20 observations to fit MarkovSwitching, got {len(s)}"
        )
    return s.to_numpy(), s.index


def _prices_to_returns(prices: pd.Series) -> pd.Series:
    """Convert prices to log returns (NaN at first bar)."""
    p = pd.Series(prices).astype(float)
    return np.log(p / p.shift(1))


# --------------------- manual EM fallback -----------------------------------


class DegenerateRegimeError(RuntimeError):
    """Raised when the EM fit collapses (regime weight too small or
    log-likelihood non-monotone) so callers can distinguish a numerical
    failure from a clean fit.
    """


def _manual_em_fit(
    obs: np.ndarray,
    n_regimes: int,
    switching_variance: bool,
    n_iter: int,
    seed: int,
    min_effective_sample_size: float = 0.01,
) -> dict:
    """Manual Hamilton-filter EM for Gaussian Markov-switching mean model.

    Used when statsmodels is unavailable. Returns dict with:
        means, vars, transition, filtered, smoothed, log_likelihood.

    Aborts via :class:`DegenerateRegimeError` when:
    - the per-iteration log-likelihood trajectory is non-monotone (drops by
      more than a small numerical tolerance), which typically indicates a
      collapsed regime; or
    - any regime's effective sample size ``min(weights) / T`` is below
      ``min_effective_sample_size`` (default 1%).
    """
    rng = np.random.default_rng(seed)
    T = len(obs)
    K = int(n_regimes)

    # init: spread means across data quantiles, common variance
    qs = np.linspace(0.1, 0.9, K)
    means = np.quantile(obs, qs).astype(float)
    var_global = float(np.var(obs))
    if var_global <= 0.0:
        var_global = 1e-8
    if switching_variance:
        variances = np.full(K, var_global, dtype=float) * (
            1.0 + 0.1 * rng.standard_normal(K)
        )
        variances = np.clip(variances, 1e-12, None)
    else:
        variances = np.full(K, var_global, dtype=float)
    P = np.full((K, K), 1.0 / K)
    pi = np.full(K, 1.0 / K)

    def _gauss_density(x: np.ndarray, mu: np.ndarray, var: np.ndarray) -> np.ndarray:
        z = (x[:, None] - mu[None, :]) ** 2 / var[None, :]
        return np.exp(-0.5 * z) / np.sqrt(2.0 * np.pi * var[None, :])

    log_lik_old = -np.inf
    log_lik_trajectory: list[float] = []
    for _ in range(int(n_iter)):
        dens = _gauss_density(obs, means, variances)  # (T, K)
        dens = np.clip(dens, 1e-300, None)

        # Hamilton filter (forward)
        filt = np.zeros((T, K))
        scale = np.zeros(T)
        pred = pi.copy()
        for t in range(T):
            num = pred * dens[t]
            s = num.sum()
            if s <= 0.0:
                s = 1e-300
            filt[t] = num / s
            scale[t] = s
            pred = filt[t] @ P

        log_lik = float(np.sum(np.log(np.clip(scale, 1e-300, None))))
        # Track trajectory for monotonicity check below. EM is guaranteed to
        # produce a non-decreasing log-likelihood; a drop signals numerical
        # failure (e.g., a collapsed regime).
        if log_lik_trajectory:
            prev = log_lik_trajectory[-1]
            if log_lik < prev - 1e-6 * max(1.0, abs(prev)):
                raise DegenerateRegimeError(
                    f"EM log-likelihood dropped from {prev:.6g} to "
                    f"{log_lik:.6g}; regime collapsed"
                )
        log_lik_trajectory.append(log_lik)

        # Kim smoother (backward)
        smooth = np.zeros((T, K))
        smooth[-1] = filt[-1]
        for t in range(T - 2, -1, -1):
            pred_next = filt[t] @ P
            pred_next = np.clip(pred_next, 1e-300, None)
            ratio = smooth[t + 1] / pred_next
            smooth[t] = filt[t] * (P @ ratio)
            ssum = smooth[t].sum()
            if ssum > 0:
                smooth[t] /= ssum

        # joint p(S_t=i, S_{t+1}=j | data) for transition update
        joint = np.zeros((T - 1, K, K))
        for t in range(T - 1):
            pred_next = filt[t] @ P
            pred_next = np.clip(pred_next, 1e-300, None)
            ratio = smooth[t + 1] / pred_next
            num = filt[t][:, None] * P * ratio[None, :]
            denom = num.sum()
            if denom > 0:
                joint[t] = num / denom

        # M-step
        weights = smooth.sum(axis=0)  # (K,)
        # Effective sample size guard: a regime with vanishing weight has
        # collapsed and its mean/variance estimates are uninformative.
        ess_ratio = float(weights.min() / max(T, 1))
        if ess_ratio < float(min_effective_sample_size):
            raise DegenerateRegimeError(
                f"effective sample size for weakest regime "
                f"{ess_ratio:.4f} below threshold "
                f"{min_effective_sample_size:.4f}"
            )
        weights = np.clip(weights, 1e-12, None)
        new_means = (smooth * obs[:, None]).sum(axis=0) / weights
        if switching_variance:
            sq = (obs[:, None] - new_means[None, :]) ** 2
            new_var = (smooth * sq).sum(axis=0) / weights
        else:
            sq = (obs[:, None] - new_means[None, :]) ** 2
            pooled = float((smooth * sq).sum() / weights.sum())
            new_var = np.full(K, pooled, dtype=float)
        new_var = np.clip(new_var, 1e-12, None)
        trans_num = joint.sum(axis=0)
        trans_den = trans_num.sum(axis=1, keepdims=True)
        trans_den = np.clip(trans_den, 1e-12, None)
        new_P = trans_num / trans_den
        new_pi = smooth[0]

        means, variances, P, pi = new_means, new_var, new_P, new_pi

        if abs(log_lik - log_lik_old) < 1e-6:
            break
        log_lik_old = log_lik

    return {
        "means": means,
        "vars": variances,
        "transition": P,
        "filtered": filt,
        "smoothed": smooth,
        "log_likelihood": log_lik,
    }


# ----------------------------- main class -----------------------------------


class MarkovSwitchingMean:
    """Markov-switching mean model with K regimes.

    r_t = mu_{S_t} + sigma_{S_t} * eps_t, S_t ~ Markov chain.

    Args:
        n_regimes: number of regimes (default 2 = bear/bull).
        switching_variance: True if vol differs across regimes.
        n_iter: max EM iterations.
        seed: random seed.
    """

    def __init__(
        self,
        n_regimes: int = 2,
        switching_variance: bool = True,
        n_iter: int = 100,
        seed: int = 42,
    ):
        if n_regimes < 2:
            raise ValueError("n_regimes must be >= 2")
        self.n_regimes = int(n_regimes)
        self.switching_variance = bool(switching_variance)
        self.n_iter = int(n_iter)
        self.seed = int(seed)

        self._fitted = False
        self._index: pd.Index | None = None
        self._order: np.ndarray | None = None  # raw_idx -> sorted_idx
        self._means: np.ndarray | None = None
        self._vols: np.ndarray | None = None
        self._transition: np.ndarray | None = None
        self._filtered: np.ndarray | None = None
        self._smoothed: np.ndarray | None = None
        self._log_likelihood: float = 0.0

    # ---- internals ----------------------------------------------------------

    def _check_fitted(self) -> None:
        if not self._fitted:
            raise RuntimeError("MarkovSwitchingMean not fitted. Call fit() first.")

    def _fit_statsmodels(self, obs: np.ndarray) -> None:
        """Fit via statsmodels MarkovRegression."""
        # Snapshot/restore the global numpy RNG so seeding for reproducible
        # fits doesn't leak into the caller's RNG state. statsmodels'
        # MarkovRegression.fit() relies on np.random for search_reps; we
        # need determinism scoped to this call only.
        _rng_state = np.random.get_state()
        try:
            np.random.seed(self.seed)
            model = _SmMarkovRegression(
                endog=obs,
                k_regimes=self.n_regimes,
                trend="c",
                switching_variance=self.switching_variance,
            )
            try:
                res = model.fit(maxiter=self.n_iter, disp=False)
            except Exception as first_exc:
                # First attempt failed — log the original exception so the
                # fallback retry isn't silent. Build a *fresh* MarkovRegression
                # because statsmodels may leave partial fitter state on the
                # original instance, which causes the second fit() to operate
                # on stale internals.
                _log.warning(
                    "markov_fit_first_attempt_failed",
                    extra={"kv": {"err": repr(first_exc)}},
                )
                model = _SmMarkovRegression(
                    endog=obs,
                    k_regimes=self.n_regimes,
                    trend="c",
                    switching_variance=self.switching_variance,
                )
                res = model.fit(
                    maxiter=self.n_iter,
                    disp=False,
                    search_reps=3,
                )
        finally:
            np.random.set_state(_rng_state)

        # extract regime means (constants) and variances
        K = self.n_regimes
        raw_means = np.zeros(K, dtype=float)
        raw_vars = np.zeros(K, dtype=float)
        for k in range(K):
            raw_means[k] = float(res.params.get(f"const[{k}]", 0.0))
            if self.switching_variance:
                raw_vars[k] = float(res.params.get(f"sigma2[{k}]", 1e-8))
            else:
                raw_vars[k] = float(res.params.get("sigma2", 1e-8))
        raw_vars = np.clip(raw_vars, 1e-12, None)
        raw_vols = np.sqrt(raw_vars)

        # transition matrix from regime_transition (shape varies by statsmodels version).
        # Robust to version differences: only require the array to be 3-D and
        # the last axis to enumerate observations (or a single static slice).
        rt = np.asarray(res.regime_transition)
        if len(rt.shape) == 3:
            # (k_regimes, k_regimes, nobs) for time-varying;
            # static -> take first slice along the last axis.
            raw_trans = rt[..., 0]
        else:
            raw_trans = rt
        raw_trans = np.asarray(raw_trans, dtype=float)
        # statsmodels columns sum to 1 (column-stochastic); we want row-stochastic
        # P[i,j] = P(S_t = j | S_{t-1} = i)
        col_sums = raw_trans.sum(axis=0)
        if np.allclose(col_sums, 1.0, atol=1e-3):
            raw_trans = raw_trans.T
        # renormalize rows
        row_sums = raw_trans.sum(axis=1, keepdims=True)
        row_sums = np.clip(row_sums, 1e-12, None)
        raw_trans = raw_trans / row_sums

        # filtered + smoothed marginal probs (statsmodels emits either
        # (T, K) or (K, T) depending on version). Pin to (T, K) by
        # comparing axis 0 to the actual observation length so the
        # K == T degenerate case is resolved without ambiguity.
        fp = np.asarray(res.filtered_marginal_probabilities)
        sp = np.asarray(res.smoothed_marginal_probabilities)
        if fp.shape[0] != len(obs):
            fp = fp.T
            sp = sp.T

        # sort regimes ascending by mean
        order = np.argsort(raw_means)
        self._order = order
        self._means = raw_means[order]
        self._vols = raw_vols[order]
        self._transition = raw_trans[np.ix_(order, order)]
        self._filtered = fp[:, order]
        self._smoothed = sp[:, order]
        self._log_likelihood = float(res.llf)

    def _fit_manual(self, obs: np.ndarray) -> None:
        """Fit via manual EM fallback."""
        out = _manual_em_fit(
            obs,
            self.n_regimes,
            self.switching_variance,
            self.n_iter,
            self.seed,
        )
        raw_means = out["means"]
        raw_vols = np.sqrt(np.clip(out["vars"], 1e-12, None))
        order = np.argsort(raw_means)
        self._order = order
        self._means = raw_means[order]
        self._vols = raw_vols[order]
        self._transition = out["transition"][np.ix_(order, order)]
        self._filtered = out["filtered"][:, order]
        self._smoothed = out["smoothed"][:, order]
        self._log_likelihood = float(out["log_likelihood"])

    # ---- public API ---------------------------------------------------------

    def fit(self, returns: pd.Series) -> "MarkovSwitchingMean":
        """Fit Markov-switching model. Sorts regimes by mean ascending.

        statsmodels failures fall back to the manual EM implementation, but
        ``DegenerateRegimeError`` is allowed to propagate because the
        manual fallback can produce the exact same degeneracy and would
        only mask the real problem. We catch only:

        - ``ValueError``           — bad inputs / convergence flips
        - ``np.linalg.LinAlgError`` — singular covariance / non-PD matrices
        - ``RuntimeError``         — statsmodels' own convergence error
        """
        obs, idx = _as_returns(returns)
        self._index = idx

        if _HAS_STATSMODELS:
            try:
                self._fit_statsmodels(obs)
            except DegenerateRegimeError:
                raise
            except (ValueError, np.linalg.LinAlgError, RuntimeError) as exc:
                _log.warning(
                    "statsmodels Markov fit failed (%s); "
                    "falling back to manual EM",
                    exc,
                )
                self._fit_manual(obs)
        else:
            self._fit_manual(obs)

        self._fitted = True
        return self

    def filtered_probs(self) -> pd.DataFrame:
        """Real-time regime probability (uses only past data)."""
        self._check_fitted()
        assert self._filtered is not None and self._index is not None
        cols = [f"regime_{k}" for k in range(self.n_regimes)]
        return pd.DataFrame(self._filtered, index=self._index, columns=cols)

    def smoothed_probs(self) -> pd.DataFrame:
        """Backward-smoothed regime probability (uses full data)."""
        self._check_fitted()
        assert self._smoothed is not None and self._index is not None
        cols = [f"regime_{k}" for k in range(self.n_regimes)]
        return pd.DataFrame(self._smoothed, index=self._index, columns=cols)

    def filter_step(self, last_filtered: np.ndarray, obs: float) -> np.ndarray:
        """One-step-ahead Hamilton filter update.

        Given the previous filtered probability vector ``last_filtered``
        (shape ``(K,)``) and a new return observation ``obs``, returns the
        updated filtered probability for the next bar without running EM.

        Use to generate live regime signals between full refits — keeps
        the bar-to-bar signal moving instead of clamping to the value at
        the last refit window's tail.
        """
        self._check_fitted()
        assert (
            self._transition is not None
            and self._means is not None
            and self._vols is not None
        )
        K = self.n_regimes
        if last_filtered.shape != (K,):
            raise ValueError(
                f"last_filtered must have shape ({K},), got {last_filtered.shape}"
            )
        # Predict one step: pi_pred = last @ P
        pred = last_filtered @ self._transition
        var = (self._vols ** 2)
        var = np.clip(var, 1e-12, None)
        # Gaussian likelihood per regime
        z = (obs - self._means) ** 2 / var
        dens = np.exp(-0.5 * z) / np.sqrt(2.0 * np.pi * var)
        dens = np.clip(dens, 1e-300, None)
        num = pred * dens
        s = float(num.sum())
        # Numerical underflow fallback: when ``num`` is the all-zeros
        # vector (every regime's likelihood times prior is zero in
        # float64 — happens for extreme outliers far from every regime
        # mean), normalizing by ``1e-300`` produces a NaN/Inf vector
        # that poisons every subsequent step. Fall back to ``pred`` when
        # available, else uniform 1/K, so the filter keeps a valid
        # probability simplex.
        if s <= 0.0 or not np.isfinite(s):
            pred_sum = float(pred.sum())
            if pred_sum > 0.0 and np.isfinite(pred_sum):
                return pred / pred_sum
            return np.full(K, 1.0 / K, dtype=float)
        return num / s

    def result(self) -> MarkovSwitchResult:
        """Full diagnostics container."""
        self._check_fitted()
        assert (
            self._means is not None
            and self._vols is not None
            and self._transition is not None
            and self._smoothed is not None
            and self._filtered is not None
            and self._index is not None
        )
        smoothed_df = self.smoothed_probs()
        filtered_df = self.filtered_probs()
        most_likely = pd.Series(
            np.argmax(self._smoothed, axis=1).astype(int),
            index=self._index,
            name="regime",
        )
        return MarkovSwitchResult(
            n_regimes=self.n_regimes,
            regime_means=self._means.copy(),
            regime_vols=self._vols.copy(),
            transition_matrix=self._transition.copy(),
            smoothed_probs=smoothed_df,
            filtered_probs=filtered_df,
            most_likely_regime=most_likely,
            log_likelihood=self._log_likelihood,
        )


# ----------------------------- signal helpers -------------------------------


def regime_filter_signal(
    prices: pd.Series,
    model: MarkovSwitchingMean,
    bullish_regime: int = 1,
) -> np.ndarray:
    """Generate +1 (long) when filtered_proba(bullish_regime) > 0.5, else 0.

    Timing contract (close-on-close)
    --------------------------------
    The Hamilton filter at bar ``i`` already conditions on ``return[i] =
    log(close[i] / close[i-1])`` — i.e. the bar's CLOSE has been
    observed. The returned array is aligned to ``prices.index`` so that
    ``out[i]`` represents the desired position once close[i] has
    printed. **Backtest engines that fill at the SAME-bar close (the
    mark used for ``return[i+1]``) must therefore shift this signal by
    one bar before applying it** — otherwise the position taken at
    close[i] earns ``return[i]`` whose computation included the same
    close, leaking the bar into the decision. Backtest engines that fill
    at the NEXT bar's open can use the array as-is.

    This function does NOT shift internally so callers retain control
    over the fill model; in doubt, call ``np.roll(out, 1); out[0] = 0``
    or apply a ``.shift(1)`` on a Series wrapper before signal-to-trade
    conversion.

    Anti-lookahead: uses ONLY filtered probs (not smoothed) so bar i
    decision uses data through bar i.

    Args:
        prices: pd.Series of prices, length N.
        model: a fitted MarkovSwitchingMean (must have been .fit()).
        bullish_regime: regime index treated as long-favorable. Default K-1.

    Returns:
        np.ndarray of length len(prices), values in {0.0, 1.0}.
    """
    if not getattr(model, "_fitted", False):
        raise RuntimeError("model must be fitted before generating signals")
    if bullish_regime < 0 or bullish_regime >= model.n_regimes:
        raise ValueError(
            f"bullish_regime must be in [0, {model.n_regimes - 1}], got {bullish_regime}"
        )
    fp = model.filtered_probs()  # indexed by returns index
    p_bull = fp.iloc[:, bullish_regime]

    # align to prices: returns index is shifted vs prices because returns drop bar 0.
    out = pd.Series(0.0, index=prices.index)
    aligned = p_bull.reindex(prices.index).fillna(0.0)
    out.loc[aligned > 0.5] = 1.0
    return out.to_numpy(dtype=float)


def regime_switching_strategy(
    prices: pd.Series,
    n_regimes: int = 2,
    refit_every: int = 252,
) -> np.ndarray:
    """End-to-end: fit MS, generate signals. Refits every N bars to avoid stale model.

    Timing contract (close-on-close)
    --------------------------------
    At bar ``i`` the function computes ``r_i = log(close[i] / close[i-1])``
    and updates the filter with this NEW observation — so ``out[i]``
    encodes the desired position assuming close[i] has just printed.
    Backtest engines whose fill model marks the position at close[i] (and
    earns ``return[i+1]``) can use the array as-is. Backtest engines whose
    fill model uses close[i] both as the trigger AND as the fill price
    must apply ``.shift(1)`` before consuming the array, otherwise the
    bar's close leaks into its own decision. Same caveat as
    :func:`regime_filter_signal`.

    Anti-lookahead: at bar i, model uses only prices[:i] for refit; the
    inter-refit filter step at bar i uses ``r_i`` derived from
    close[i-1] and close[i].

    Args:
        prices: pd.Series of prices, length N.
        n_regimes: number of regimes.
        refit_every: bars between refits.

    Returns:
        np.ndarray of length len(prices), values in {0.0, 1.0}.
    """
    p = pd.Series(prices).astype(float)
    N = len(p)
    out = np.zeros(N, dtype=float)
    refit = max(int(refit_every), 20)

    # need at least ~60 returns to fit reliably
    min_warmup = max(60, refit)
    if N <= min_warmup + 1:
        return out

    last_model: MarkovSwitchingMean | None = None
    last_fit_at = -1
    last_filtered: np.ndarray | None = None  # last bar's filtered prob vector
    bullish_regime = n_regimes - 1

    for i in range(min_warmup, N):
        # refit when due (or first time)
        if last_model is None or (i - last_fit_at) >= refit:
            past_prices = p.iloc[:i]  # strictly past — anti-lookahead
            past_returns = _prices_to_returns(past_prices).dropna()
            if len(past_returns) < 30:
                continue
            try:
                m = MarkovSwitchingMean(n_regimes=n_regimes)
                m.fit(past_returns)
                last_model = m
                last_fit_at = i
                # Initialize the running filtered prob from the last bar
                # of the fit window.
                fp = m.filtered_probs()
                if fp.empty:
                    last_filtered = None
                else:
                    last_filtered = fp.iloc[-1].to_numpy(dtype=float)
            except Exception:
                # leave signal at zero; try again next refit
                continue

        if last_model is None or last_filtered is None:
            continue

        # Between refits, advance the filter one bar at a time using the new
        # observation r_i = log(p_i / p_{i-1}). This keeps the regime
        # probability current instead of clamping to the value computed at
        # the last refit window's tail.
        prev_price = float(p.iloc[i - 1])
        cur_price = float(p.iloc[i])
        if prev_price > 0.0 and cur_price > 0.0:
            obs = float(np.log(cur_price / prev_price))
            try:
                last_filtered = last_model.filter_step(last_filtered, obs)
            except Exception:
                # numerical hiccup — fall through with previous filter state
                pass

        p_bull_last = float(last_filtered[bullish_regime])
        out[i] = 1.0 if p_bull_last > 0.5 else 0.0

    return out
