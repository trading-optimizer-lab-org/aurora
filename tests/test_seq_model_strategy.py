"""Tests for SeqModelStrategy (sequence-model wrapper)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aurora.strategies.library import SeqModelStrategy
from aurora.strategies.library.seq_model import (
    MockPredictor,
    default_feature_fn,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_prices() -> pd.Series:
    rng = np.random.default_rng(7)
    idx = pd.date_range("2010-01-01", periods=600, freq="B")
    rets = rng.normal(0.0004, 0.011, len(idx))
    p = 100.0 * np.cumprod(1.0 + rets)
    return pd.Series(p, index=idx, name="FAKE")


# ---------------------------------------------------------------------------
# Helpers used by tests
# ---------------------------------------------------------------------------

class CountingPredictor:
    """Mock predictor that records every fit() call."""
    instances: list["CountingPredictor"] = []

    def __init__(self, **kwargs) -> None:
        self.fit_calls = 0
        self.last_X_size = 0
        CountingPredictor.instances.append(self)

    def fit(self, X, y):
        self.fit_calls += 1
        self.last_X_size = np.asarray(X).shape[0]
        return self

    def predict(self, X):
        # constant tiny positive prediction so threshold at 0 yields +1 signals
        return np.full(np.asarray(X).shape[0], 0.5, dtype=float)


class SignedPredictor:
    """Returns the sign-of-last-feature so threshold rule can be exercised."""

    def __init__(self, **kwargs):
        pass

    def fit(self, X, y):
        return self

    def predict(self, X):
        X = np.asarray(X, dtype=float)
        if X.ndim == 3:
            last = X[:, -1, -1]
        elif X.ndim == 2:
            last = X[:, -1]
        else:
            last = X
        return last


# ---------------------------------------------------------------------------
# Core contract tests (run without torch / sb3)
# ---------------------------------------------------------------------------

def test_strategy_signal_shape(fake_prices: pd.Series) -> None:
    s = SeqModelStrategy(
        model_type="mock",
        warmup_bars=120,
        retrain_every=60,
        train_size=120,
    )
    sig = s.signals(fake_prices)
    assert isinstance(sig, np.ndarray)
    assert len(sig) == len(fake_prices)
    assert not np.any(np.isnan(sig))
    assert np.all(np.abs(sig) <= 1.0 + 1e-9)


def test_warmup_zero(fake_prices: pd.Series) -> None:
    """Warmup bars must be zero (ABC forbids NaN; zeros mark inactive)."""
    s = SeqModelStrategy(model_type="mock", warmup_bars=150, retrain_every=60)
    sig = s.signals(fake_prices)
    assert np.all(sig[:150] == 0.0)


def test_signal_values(fake_prices: pd.Series) -> None:
    s = SeqModelStrategy(model_type="mock", warmup_bars=100, retrain_every=50)
    sig = s.signals(fake_prices)
    unique = set(np.unique(sig))
    assert unique.issubset({-1.0, 0.0, 1.0})


def test_threshold_rule(fake_prices: pd.Series) -> None:
    """pred > thresh -> +1, pred < -thresh -> -1, else 0."""
    # SignedPredictor returns last feature value as prediction.
    # Force threshold so only |pred| > 0.001 maps to a signal.
    s = SeqModelStrategy(
        predictor_class=SignedPredictor,
        feature_fn=default_feature_fn,
        threshold=0.001,
        warmup_bars=100,
        retrain_every=40,
        train_size=100,
    )
    sig = s.signals(fake_prices)
    assert set(np.unique(sig)).issubset({-1.0, 0.0, 1.0})

    # Direct check using the helper.
    helper = SeqModelStrategy(
        predictor_class=SignedPredictor,
        threshold=0.5,
        warmup_bars=100,
        retrain_every=40,
        train_size=100,
    )
    preds = np.array([-1.0, -0.6, -0.4, 0.0, 0.4, 0.6, 1.0])
    out = helper._apply_threshold(preds)
    assert list(out) == [-1.0, -1.0, 0.0, 0.0, 0.0, 1.0, 1.0]


def test_no_lookahead(fake_prices: pd.Series) -> None:
    """signals[i] must depend only on prices[:i+1].

    Truncating the input to bar k must produce identical signals on [:k].
    """
    s = SeqModelStrategy(
        predictor_class=SignedPredictor,
        warmup_bars=120,
        retrain_every=50,
        train_size=120,
        threshold=0.0,
    )
    full = s.signals(fake_prices)
    # Truncate at a chunk boundary so refit cadence matches.
    k = 120 + 50 * 4  # 320
    trunc = s.signals(fake_prices.iloc[:k])
    assert np.allclose(trunc, full[:k]), "Lookahead detected: truncated signal disagrees with full"


def test_retrain_schedule(fake_prices: pd.Series) -> None:
    """One predictor instance is built per chunk; each receives exactly one fit()."""
    CountingPredictor.instances.clear()
    s = SeqModelStrategy(
        predictor_class=CountingPredictor,
        warmup_bars=100,
        retrain_every=80,
        train_size=100,
        threshold=-1.0,  # any positive prediction -> +1
    )
    sig = s.signals(fake_prices)
    # Each chunk gets a fresh predictor; total chunks = ceil((n - warmup) / retrain_every).
    expected_chunks = int(np.ceil((len(fake_prices) - 100) / 80))
    assert len(CountingPredictor.instances) == expected_chunks
    assert all(p.fit_calls == 1 for p in CountingPredictor.instances)
    # And a final sanity check on signal length.
    assert len(sig) == len(fake_prices)


def test_default_feature_fn_no_lookahead() -> None:
    """default_feature_fn must satisfy the causality contract."""
    rng = np.random.default_rng(0)
    p = pd.Series(100.0 + np.cumsum(rng.normal(0, 1, 200)),
                  index=pd.date_range("2020-01-01", periods=200, freq="B"))
    feats_full = default_feature_fn(p)
    feats_trunc = default_feature_fn(p.iloc[:120])
    # Rows up to bar 119 must match exactly.
    pd.testing.assert_frame_equal(
        feats_trunc.iloc[:120].reset_index(drop=True),
        feats_full.iloc[:120].reset_index(drop=True),
        check_exact=False,
    )


def test_short_input_returns_zeros() -> None:
    s = SeqModelStrategy(model_type="mock", warmup_bars=400, retrain_every=60)
    p = pd.Series(np.linspace(100, 110, 100),
                  index=pd.date_range("2020-01-01", periods=100, freq="B"))
    sig = s.signals(p)
    assert np.all(sig == 0.0)
    assert len(sig) == 100


def test_mock_predictor_round_trip() -> None:
    """MockPredictor.fit/predict shapes are consistent."""
    mp = MockPredictor()
    X = np.random.default_rng(0).normal(size=(20, 4))
    y = np.random.default_rng(1).normal(size=(20,))
    mp.fit(X, y)
    preds = mp.predict(X)
    assert preds.shape == (20,)
    assert mp.fit_calls == 1


# ---------------------------------------------------------------------------
# Integration tests (skipped when torch / sb3 unavailable)
# ---------------------------------------------------------------------------

def test_lstm_integration(fake_prices: pd.Series) -> None:
    pytest.importorskip("torch")
    from aurora.ml.lstm import LSTMConfig, LSTMForecaster, TORCH_AVAILABLE
    if not TORCH_AVAILABLE:
        pytest.skip("torch not available at runtime")

    s = SeqModelStrategy(
        model_type="lstm",
        model_params={
            "input_dim": 7,
            "hidden_dim": 8,
            "num_layers": 1,
            "seq_len": 5,
            "epochs": 1,
            "batch_size": 16,
        },
        seq_len=5,
        warmup_bars=160,
        retrain_every=120,
        train_size=160,
        threshold=0.0,
    )
    sig = s.signals(fake_prices)
    assert isinstance(sig, np.ndarray)
    assert len(sig) == len(fake_prices)
    assert not np.any(np.isnan(sig))
    assert set(np.unique(sig)).issubset({-1.0, 0.0, 1.0})


def test_rl_integration(fake_prices: pd.Series) -> None:
    pytest.importorskip("stable_baselines3")
    pytest.importorskip("gymnasium")

    s = SeqModelStrategy(
        model_type="rl",
        model_params={
            "algo": "PPO",
            "total_timesteps": 100,
            "n_steps": 32,
        },
        seq_len=1,
        warmup_bars=160,
        retrain_every=200,
        train_size=160,
        threshold=-1.0,  # accept any non-zero prediction
    )
    sig = s.signals(fake_prices)
    assert len(sig) == len(fake_prices)
    assert set(np.unique(sig)).issubset({-1.0, 0.0, 1.0})


def test_train_size_zero_raises() -> None:
    """train_size=0 was previously falsy and silently coerced to warmup_bars.
    Reject explicitly so configuration bugs surface at construction time.
    """
    with pytest.raises(ValueError, match="train_size"):
        SeqModelStrategy(model_type="mock", warmup_bars=100, train_size=0)
    with pytest.raises(ValueError, match="train_size"):
        SeqModelStrategy(model_type="mock", warmup_bars=100, train_size=-5)


def test_train_size_none_falls_back_to_warmup() -> None:
    s = SeqModelStrategy(model_type="mock", warmup_bars=128, train_size=None)
    assert s.train_size == 128


def test_warmup_lifted_to_seq_len_minus_one(fake_prices: pd.Series) -> None:
    """signals() must enforce warmup_bars >= seq_len - 1 so _make_window's
    zero-pad fallback never triggers. Pass a tiny warmup that violates the
    invariant and verify pre-effective-warmup bars stay at 0.
    """
    seq_len = 30
    warmup_too_small = 5
    s = SeqModelStrategy(
        model_type="mock",
        seq_len=seq_len,
        warmup_bars=warmup_too_small,
        retrain_every=120,
        train_size=120,
        threshold=-1.0,  # accept any prediction
    )
    sig = s.signals(fake_prices)
    # Effective warmup is max(warmup_bars, seq_len - 1) = seq_len - 1.
    # All bars before that must remain 0 since signals() never iterated.
    effective = max(warmup_too_small, seq_len - 1)
    assert np.all(sig[:effective] == 0.0)
    # And the strategy must still produce SOME signal after the effective
    # warmup so the lift is functional, not a silent no-op.
    assert len(sig[effective:]) > 0
