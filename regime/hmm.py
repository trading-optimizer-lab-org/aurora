"""Gaussian HMM regime detection (Hamilton 1989 style).

Wraps hmmlearn.GaussianHMM. Sorts states by mean return ascending so state 0 is
always the lowest-return regime and state K-1 the highest. Reproducible via
seed (delegates to numpy RandomState through hmmlearn).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from aurora.core.metrics import compute_metrics

try:
    from hmmlearn.hmm import GaussianHMM as _SkGaussianHMM  # type: ignore
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "hmmlearn is required for quantforge.regime.hmm. "
        "Install with: uv add hmmlearn"
    ) from exc


@dataclass
class HMMResult:
    """Container for fitted HMM diagnostics."""

    n_states: int
    states: pd.Series
    state_probs: pd.DataFrame
    transition_matrix: np.ndarray
    state_means: np.ndarray
    state_vols: np.ndarray
    log_likelihood: float
    n_iter: int
    converged: bool


# ----------------------------- helpers ---------------------------------------


def _as_obs(returns: pd.Series) -> tuple[np.ndarray, pd.Index]:
    """Coerce returns Series to (N,1) float array, drop NaN, return index."""
    s = pd.Series(returns).astype(float).dropna()
    if len(s) < 10:
        raise ValueError(f"Need >= 10 observations to fit HMM, got {len(s)}")
    return s.to_numpy().reshape(-1, 1), s.index


# ----------------------------- main class ------------------------------------


class GaussianHMM:
    """Gaussian HMM for return regimes.

    Args:
        n_states: number of regimes (2 = bull/bear, 3 = bull/neutral/bear).
        n_iter: max EM iterations.
        tol: convergence tolerance. EM stops early when the log-likelihood
            improvement between consecutive iterations falls below this value.
            Default 1e-4.
        covariance_type: 'diag' | 'full' | 'spherical' | 'tied'.
        seed: random seed for hmmlearn initialization.

    After fit(), states are reordered by mean return ascending so:
        state 0 = lowest-return regime, state K-1 = highest-return regime.
    """

    def __init__(
        self,
        n_states: int = 2,
        n_iter: int = 100,
        tol: float = 1e-4,
        covariance_type: str = "diag",
        seed: int = 42,
    ):
        if n_states < 2:
            raise ValueError("n_states must be >= 2")
        if tol <= 0.0:
            raise ValueError("tol must be > 0")
        self.n_states = int(n_states)
        self.n_iter = int(n_iter)
        self.tol = float(tol)
        self.covariance_type = covariance_type
        self.seed = int(seed)

        self._model: _SkGaussianHMM | None = None
        self._order: np.ndarray | None = None  # raw_state -> sorted_state
        self._fitted = False

    # ---- internal ------------------------------------------------------------

    def _build(self) -> _SkGaussianHMM:
        return _SkGaussianHMM(
            n_components=self.n_states,
            covariance_type=self.covariance_type,
            n_iter=self.n_iter,
            tol=self.tol,
            random_state=self.seed,
            init_params="stmc",
            params="stmc",
        )

    def _check_fitted(self) -> None:
        if not self._fitted or self._model is None or self._order is None:
            raise RuntimeError("HMM not fitted. Call fit() first.")

    def _sorted_means_vols(self) -> tuple[np.ndarray, np.ndarray]:
        """Return (means, vols) in sorted-state order."""
        assert self._model is not None and self._order is not None
        raw_means = self._model.means_.flatten()
        # covars_ shape depends on covariance_type; flatten to per-state variance
        cv = np.asarray(self._model.covars_)
        if cv.ndim == 3:  # (n_states, 1, 1) for diag/full with 1D obs
            raw_vars = cv.reshape(self.n_states, -1).mean(axis=1)
        else:
            raw_vars = cv.flatten()[: self.n_states]
        raw_vols = np.sqrt(np.maximum(raw_vars, 0.0))
        return raw_means[self._order], raw_vols[self._order]

    def _sorted_transition(self) -> np.ndarray:
        """Reorder transition matrix rows/cols by sorted state index."""
        assert self._model is not None and self._order is not None
        T = np.asarray(self._model.transmat_)
        return T[np.ix_(self._order, self._order)]

    def _map_states(self, raw_states: np.ndarray) -> np.ndarray:
        """Map raw hmmlearn labels to sorted-state labels.

        ``self._order`` is a permutation produced by ``np.argsort`` on the
        raw means: ``self._order[sorted_idx] == raw_idx``. The inverse
        permutation (``raw_idx -> sorted_idx``) is exactly
        ``np.argsort(self._order)`` — vectorized, O(K log K) — so we
        replace the previous explicit O(K^2)-ish python loop.
        """
        assert self._order is not None
        inv = np.argsort(self._order)
        return inv[raw_states]

    # ---- public API ----------------------------------------------------------

    def fit(self, returns: pd.Series) -> "GaussianHMM":
        """Fit HMM via EM. Sorts states by mean return ascending."""
        X, _ = _as_obs(returns)
        model = self._build()
        model.fit(X)
        # sort states by mean return ascending: state 0 = lowest mean
        means = model.means_.flatten()
        order = np.argsort(means)  # raw indices in sorted-mean order
        self._model = model
        self._order = order
        self._fitted = True
        return self

    def predict(self, returns: pd.Series) -> pd.Series:
        """Most likely state sequence (Viterbi).

        Requires a ``pd.Series`` for the same reason as
        :meth:`predict_proba`: the returned Series is reindexed back to
        the caller's full index so dropped NaN bars surface as NaN
        instead of silently shrinking the output. Lists / arrays would
        lose timestamp alignment.
        """
        self._check_fitted()
        assert self._model is not None
        if not isinstance(returns, pd.Series):
            raise TypeError(
                "predict requires a pandas Series input so the returned "
                "states can be aligned on the caller's DatetimeIndex; "
                f"got {type(returns).__name__}"
            )
        X, idx = _as_obs(returns)
        raw = self._model.predict(X)
        sorted_states = self._map_states(raw)
        out = pd.Series(sorted_states.astype(float), index=idx, name="state")
        # Reindex to the caller-supplied index so dropped NaNs surface as
        # NaN (state cannot be assigned for those bars), mirroring the
        # symmetry contract documented on ``predict_proba``.
        return out.reindex(returns.index)

    def predict_proba(self, returns: pd.Series) -> pd.DataFrame:
        """Posterior P(state_k | obs) per bar.

        Requires a ``pd.Series`` so the returned DataFrame can be aligned
        on the caller's DatetimeIndex. Lists / NumPy arrays would silently
        fall back to a default ``RangeIndex(len)`` which loses the
        timestamp alignment downstream callers depend on; we raise
        ``TypeError`` instead of producing misleading output.

        Returns a DataFrame aligned with the *input* index (NaN at bars
        dropped during ``_as_obs`` due to NaN returns) so callers can
        merge with the original price series without index drift.
        """
        self._check_fitted()
        assert self._model is not None and self._order is not None
        if not isinstance(returns, pd.Series):
            raise TypeError(
                "predict_proba requires a pandas Series input so the "
                "returned probabilities can be aligned on the caller's "
                f"DatetimeIndex; got {type(returns).__name__}"
            )
        X, idx = _as_obs(returns)
        raw_probs = self._model.predict_proba(X)  # (T, n_states) raw order
        sorted_probs = raw_probs[:, self._order]
        cols = [f"state_{k}" for k in range(self.n_states)]
        df = pd.DataFrame(sorted_probs, index=idx, columns=cols)
        # Reindex to the caller-supplied index so dropped NaNs surface as
        # NaN in the output instead of silently shrinking the result.
        return df.reindex(returns.index)

    def result(self, returns: pd.Series) -> HMMResult:
        """Full HMMResult with all diagnostics."""
        self._check_fitted()
        assert self._model is not None
        X, _ = _as_obs(returns)
        states = self.predict(returns)
        probs = self.predict_proba(returns)
        means, vols = self._sorted_means_vols()
        trans = self._sorted_transition()
        ll = float(self._model.score(X))
        n_iter = int(getattr(self._model.monitor_, "iter", 0))
        converged = bool(getattr(self._model.monitor_, "converged", False))
        return HMMResult(
            n_states=self.n_states,
            states=states,
            state_probs=probs,
            transition_matrix=trans,
            state_means=means,
            state_vols=vols,
            log_likelihood=ll,
            n_iter=n_iter,
            converged=converged,
        )


# ----------------------------- diagnostics ----------------------------------


def regime_conditional_metrics(
    returns: pd.Series,
    states: pd.Series,
    ppy: int = 252,
) -> pd.DataFrame:
    """Compute Sharpe / CAGR / MDD per regime state.

    Args:
        returns: pd.Series of returns aligned with states.
        states: pd.Series of integer state labels.
        ppy: periods per year for annualization.

    Returns:
        DataFrame indexed by state with columns: n, sharpe, cagr, mdd.
    """
    r = pd.Series(returns).astype(float)
    s = pd.Series(states).astype(int)
    df = pd.concat([r.rename("ret"), s.rename("state")], axis=1).dropna()
    rows = []
    for k, grp in df.groupby("state"):
        arr = grp["ret"].to_numpy()
        if len(arr) < 2:
            rows.append({"state": int(k), "n": len(arr),
                         "sharpe": 0.0, "cagr": 0.0, "mdd": 0.0})
            continue
        m = compute_metrics(arr, ppy=ppy)
        rows.append({
            "state": int(k),
            "n": int(len(arr)),
            "sharpe": float(m.sharpe),
            "cagr": float(m.cagr),
            "mdd": float(m.mdd),
        })
    return pd.DataFrame(rows).set_index("state").sort_index()


def detect_regime_change(
    state_probs: pd.DataFrame,
    threshold: float = 0.7,
) -> pd.Series:
    """Identify regime transitions where P(new_state) > threshold.

    A transition is flagged on bar t when:
      - argmax(P_t) != argmax(P_{t-1})
      - max(P_t) > threshold

    Args:
        state_probs: DataFrame of posterior probs per bar (cols = states).
        threshold: minimum confidence on new state to flag a transition.

    Returns:
        bool Series aligned with state_probs.index. True at transition bars.
    """
    if not 0.0 < threshold <= 1.0:
        raise ValueError("threshold must be in (0, 1]")
    p = state_probs.to_numpy()
    if p.shape[0] < 2:
        return pd.Series(False, index=state_probs.index, name="regime_change")
    argmax = np.argmax(p, axis=1)
    pmax = p.max(axis=1)
    changed = np.zeros(p.shape[0], dtype=bool)
    changed[1:] = (argmax[1:] != argmax[:-1]) & (pmax[1:] > threshold)
    return pd.Series(changed, index=state_probs.index, name="regime_change")
