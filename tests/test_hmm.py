"""Tests for quantforge.regime.hmm — Gaussian HMM regime detection."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

# Skip the entire module when hmmlearn isn't installed; quantforge.regime.hmm
# raises ImportError at module load time without it.
pytest.importorskip("hmmlearn")

from quantforge.regime.hmm import (  # noqa: E402
    GaussianHMM,
    HMMResult,
    detect_regime_change,
    regime_conditional_metrics,
)


# ---------- fixtures ---------------------------------------------------------


@pytest.fixture
def two_regime_returns() -> pd.Series:
    """Synthetic 2-regime series: bear (mean<0, vol high) then bull (mean>0, vol low)."""
    rng = np.random.default_rng(123)
    n_bear, n_bull = 250, 250
    bear = rng.normal(loc=-0.005, scale=0.020, size=n_bear)
    bull = rng.normal(loc=0.003, scale=0.008, size=n_bull)
    arr = np.concatenate([bear, bull])
    idx = pd.date_range("2020-01-01", periods=len(arr), freq="B")
    return pd.Series(arr, index=idx, name="ret")


@pytest.fixture
def fitted_hmm(two_regime_returns) -> GaussianHMM:
    return GaussianHMM(n_states=2, n_iter=100, seed=42).fit(two_regime_returns)


# ---------- core fit / state ordering ----------------------------------------


def test_fit_synthetic_2_regime(two_regime_returns):
    """HMM should recover 2 regimes from synthetic data."""
    hmm = GaussianHMM(n_states=2, seed=42).fit(two_regime_returns)
    res = hmm.result(two_regime_returns)
    assert isinstance(res, HMMResult)
    assert res.n_states == 2
    assert res.transition_matrix.shape == (2, 2)
    assert len(res.state_means) == 2
    # state means should diverge meaningfully (bear << bull)
    assert res.state_means[1] - res.state_means[0] > 0.003
    # log-likelihood should be finite
    assert np.isfinite(res.log_likelihood)


def test_state_means_ordered(fitted_hmm, two_regime_returns):
    """State 0 must have lower mean than state 1 (deterministic ordering)."""
    res = fitted_hmm.result(two_regime_returns)
    assert res.state_means[0] < res.state_means[1]


# ---------- predict / predict_proba ------------------------------------------


def test_predict_returns_series(fitted_hmm, two_regime_returns):
    """predict() returns pd.Series of integer states aligned to input index."""
    states = fitted_hmm.predict(two_regime_returns)
    assert isinstance(states, pd.Series)
    assert len(states) == len(two_regime_returns)
    assert states.index.equals(two_regime_returns.index)
    assert pd.api.types.is_integer_dtype(states)
    assert set(states.unique()).issubset({0, 1})


def test_predict_proba_rows_sum_to_one(fitted_hmm, two_regime_returns):
    probs = fitted_hmm.predict_proba(two_regime_returns)
    assert isinstance(probs, pd.DataFrame)
    assert probs.shape == (len(two_regime_returns), 2)
    row_sums = probs.sum(axis=1).to_numpy()
    np.testing.assert_allclose(row_sums, 1.0, atol=1e-8)
    # all probs in [0, 1]
    assert (probs.to_numpy() >= -1e-12).all()
    assert (probs.to_numpy() <= 1.0 + 1e-12).all()


def test_predict_proba_rejects_non_series(fitted_hmm, two_regime_returns):
    """List/np input would silently fall back to RangeIndex and break
    downstream alignment with the input timestamps; the HMM must refuse
    non-Series inputs at predict_proba entry.
    """
    arr = two_regime_returns.to_numpy()
    with pytest.raises(TypeError, match="pandas Series"):
        fitted_hmm.predict_proba(arr)
    with pytest.raises(TypeError, match="pandas Series"):
        fitted_hmm.predict_proba(arr.tolist())


def test_transition_matrix_rows_sum_to_one(fitted_hmm, two_regime_returns):
    res = fitted_hmm.result(two_regime_returns)
    row_sums = res.transition_matrix.sum(axis=1)
    np.testing.assert_allclose(row_sums, 1.0, atol=1e-8)


# ---------- regime conditional metrics ---------------------------------------


def test_regime_conditional_metrics_columns(fitted_hmm, two_regime_returns):
    states = fitted_hmm.predict(two_regime_returns)
    df = regime_conditional_metrics(two_regime_returns, states, ppy=252)
    assert isinstance(df, pd.DataFrame)
    assert {"sharpe", "cagr", "mdd", "n"}.issubset(df.columns)
    assert df.index.name == "state"
    assert len(df) == 2
    # bear (state 0) sharpe should be well below bull (state 1)
    assert df.loc[0, "sharpe"] < df.loc[1, "sharpe"]


# ---------- detect_regime_change ---------------------------------------------


def test_detect_regime_change():
    """Build synthetic posteriors with a clean flip; >0.7 threshold flags it."""
    n = 20
    p = np.zeros((n, 2))
    p[:10, 0] = 0.95
    p[:10, 1] = 0.05
    p[10:, 0] = 0.05
    p[10:, 1] = 0.95
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    df = pd.DataFrame(p, index=idx, columns=["state_0", "state_1"])
    flags = detect_regime_change(df, threshold=0.7)
    assert isinstance(flags, pd.Series)
    assert flags.dtype == bool
    assert flags.sum() == 1
    assert flags.iloc[10]  # transition exactly at index 10
    assert not flags.iloc[0]  # never flag first bar


def test_detect_regime_change_threshold_blocks_low_confidence():
    """If new-state prob is below threshold, no transition flagged."""
    n = 6
    p = np.array([
        [0.9, 0.1],
        [0.9, 0.1],
        [0.9, 0.1],
        [0.45, 0.55],  # flipped argmax but low confidence
        [0.45, 0.55],
        [0.45, 0.55],
    ])
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    df = pd.DataFrame(p, index=idx, columns=["state_0", "state_1"])
    flags = detect_regime_change(df, threshold=0.7)
    assert flags.sum() == 0


# ---------- reproducibility --------------------------------------------------


def test_seed_reproducibility(two_regime_returns):
    """Same seed → identical state assignments."""
    a = GaussianHMM(n_states=2, seed=7).fit(two_regime_returns)
    b = GaussianHMM(n_states=2, seed=7).fit(two_regime_returns)
    sa = a.predict(two_regime_returns).to_numpy()
    sb = b.predict(two_regime_returns).to_numpy()
    np.testing.assert_array_equal(sa, sb)
    # transition matrices identical too
    np.testing.assert_allclose(
        a.result(two_regime_returns).transition_matrix,
        b.result(two_regime_returns).transition_matrix,
        atol=1e-12,
    )


def test_hmm_early_stop_converges(two_regime_returns):
    """A loose tol with a generous n_iter cap should converge well before n_iter.

    The result.n_iter is the number of EM iterations actually run; with a
    permissive tol (1e-2) on a clean 2-regime synthetic series, EM should
    stop early with converged=True before hitting the iteration cap.
    """
    pytest.importorskip("hmmlearn")
    hmm = GaussianHMM(n_states=2, n_iter=500, tol=1e-2, seed=42).fit(
        two_regime_returns
    )
    res = hmm.result(two_regime_returns)
    assert res.converged is True
    assert 0 < res.n_iter < 500
    assert np.isfinite(res.log_likelihood)


def test_hmm_tol_validation():
    """tol must be strictly positive."""
    pytest.importorskip("hmmlearn")
    with pytest.raises(ValueError):
        GaussianHMM(n_states=2, tol=0.0)
    with pytest.raises(ValueError):
        GaussianHMM(n_states=2, tol=-1e-3)


def test_hmm_predict_proba_aligns_with_input_index(two_regime_returns):
    """predict_proba must align with the *input* index even when the input
    contains NaN bars that ``_as_obs`` drops.
    """
    pytest.importorskip("hmmlearn")
    r = two_regime_returns.copy()
    r.iloc[5] = np.nan
    r.iloc[100] = np.nan
    hmm = GaussianHMM(n_states=2, seed=0).fit(r)
    probs = hmm.predict_proba(r)
    # output index must equal the input index (NaNs preserved as NaN rows)
    assert list(probs.index) == list(r.index)
    # the rows at the dropped positions must be NaN
    assert probs.iloc[5].isna().all()
    assert probs.iloc[100].isna().all()
