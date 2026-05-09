"""Tests for quantforge.ml.lstm (Batch N.1).

Run: uv run --with torch pytest quantforge/tests/test_lstm.py -v
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd
import pytest

torch = pytest.importorskip("torch")

from aurora.ml.lstm import (
    LSTMConfig,
    LSTMForecaster,
    make_sequences,
    walk_forward_train,
    TORCH_AVAILABLE,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _synthetic_panel(n_bars: int = 200, n_features: int = 5, seed: int = 42):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2020-01-01", periods=n_bars, freq="B")
    feats = pd.DataFrame(
        rng.standard_normal((n_bars, n_features)).astype(np.float32),
        index=idx,
        columns=[f"f{i}" for i in range(n_features)],
    )
    # target weakly tied to first feature so loss can decrease.
    target = pd.Series(
        (0.4 * feats["f0"].to_numpy() + 0.05 * rng.standard_normal(n_bars)).astype(np.float32),
        index=idx,
        name="ret",
    )
    return feats, target


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

def test_make_sequences_shape():
    """100 bars, seq_len=20, horizon=1 -> X (80, 20, n_features)."""
    feats, target = _synthetic_panel(n_bars=100, n_features=5)
    X, y, vidx = make_sequences(feats, target, seq_len=20, horizon=1)
    assert X.shape == (80, 20, 5)
    assert y.shape == (80,)
    assert len(vidx) == 80


def test_make_sequences_no_lookahead():
    """Sequence at index i ends at bar t = i + seq_len - 1, target is at t+horizon.

    Verifies anti-lookahead: X[i] only contains bars up to t inclusive, and y[i]
    is the target at t+horizon.
    """
    n_bars = 60
    seq_len = 10
    horizon = 2
    feats, target = _synthetic_panel(n_bars=n_bars, n_features=3)

    X, y, vidx = make_sequences(feats, target, seq_len=seq_len, horizon=horizon)

    # First valid t = seq_len - 1 = 9; last valid t = n_bars - 1 - horizon = 57.
    assert vidx[0] == feats.index[seq_len - 1]
    assert vidx[-1] == feats.index[n_bars - 1 - horizon]

    feats_np = feats.to_numpy(dtype=np.float32)
    tgt_np = target.to_numpy(dtype=np.float32)

    for i in range(len(vidx)):
        t = seq_len - 1 + i
        # X[i] must equal feats[t-seq_len+1 .. t] (inclusive both ends).
        np.testing.assert_array_equal(X[i], feats_np[t - seq_len + 1 : t + 1])
        # y[i] is target at t+horizon, never beyond.
        assert y[i] == tgt_np[t + horizon]
        # The window's last bar is at time t — never exceeds t.
        last_bar_idx = feats.index.get_loc(vidx[i])
        assert last_bar_idx == t


def test_lstm_forward():
    """Forward pass returns shape (batch, 1)."""
    cfg = LSTMConfig(input_dim=5, hidden_dim=16, num_layers=2, seq_len=10, epochs=1)
    fc = LSTMForecaster(cfg)
    fc._build()
    x = torch.randn(7, cfg.seq_len, cfg.input_dim)
    out = fc._model(x)
    assert out.shape == (7, 1)


def test_lstm_fit_runs():
    """Loss generally decreases on a synthetic learnable signal."""
    feats, target = _synthetic_panel(n_bars=300, n_features=4, seed=1)
    cfg = LSTMConfig(
        input_dim=4,
        hidden_dim=16,
        num_layers=1,
        seq_len=10,
        epochs=5,
        batch_size=32,
        learning_rate=5e-3,
    )
    X, y, _ = make_sequences(feats, target, seq_len=cfg.seq_len, horizon=1)
    fc = LSTMForecaster(cfg)
    history = fc.fit(X, y)
    assert "train_loss" in history
    assert len(history["train_loss"]) == cfg.epochs
    # Final loss should be less than initial (with some tolerance).
    assert history["train_loss"][-1] < history["train_loss"][0]


def test_lstm_predict_shape():
    """predict() returns 1D numpy array of length N."""
    feats, target = _synthetic_panel(n_bars=120, n_features=4)
    cfg = LSTMConfig(input_dim=4, hidden_dim=8, num_layers=1, seq_len=10, epochs=2)
    X, y, _ = make_sequences(feats, target, seq_len=cfg.seq_len, horizon=1)
    fc = LSTMForecaster(cfg)
    fc.fit(X, y)
    preds = fc.predict(X)
    assert isinstance(preds, np.ndarray)
    assert preds.shape == (X.shape[0],)
    assert preds.dtype.kind == "f"


def test_save_load_roundtrip(tmp_path):
    """Trained model survives save -> load with identical predictions."""
    feats, target = _synthetic_panel(n_bars=120, n_features=4, seed=7)
    cfg = LSTMConfig(input_dim=4, hidden_dim=8, num_layers=1, seq_len=10, epochs=2)
    X, y, _ = make_sequences(feats, target, seq_len=cfg.seq_len, horizon=1)

    fc = LSTMForecaster(cfg)
    fc.fit(X, y)
    preds_before = fc.predict(X)

    path = str(tmp_path / "lstm.pt")
    fc.save(path)

    fc2 = LSTMForecaster(LSTMConfig(input_dim=4, seq_len=10))  # different hparams; load overrides
    fc2.load(path)
    preds_after = fc2.predict(X)

    np.testing.assert_allclose(preds_before, preds_after, atol=1e-6)


def test_walk_forward_dataframe():
    """walk_forward_train returns a DataFrame with a prediction column."""
    feats, target = _synthetic_panel(n_bars=400, n_features=3, seed=11)
    cfg = LSTMConfig(
        input_dim=3,
        hidden_dim=8,
        num_layers=1,
        seq_len=10,
        epochs=2,
        batch_size=32,
        learning_rate=5e-3,
    )
    fc = LSTMForecaster(cfg)
    df = walk_forward_train(fc, feats, target, train_size=200, test_size=50, step=50)
    assert isinstance(df, pd.DataFrame)
    assert "prediction" in df.columns
    assert "target" in df.columns
    assert "fold" in df.columns
    assert len(df) > 0
    # All prediction timestamps must be inside the original index.
    assert df.index.isin(feats.index).all()


def test_seed_reproducibility():
    """Same global seed -> identical predictions across two fresh fits."""
    from aurora.core.seed import set_global_seed

    feats, target = _synthetic_panel(n_bars=180, n_features=4, seed=3)
    cfg = LSTMConfig(
        input_dim=4,
        hidden_dim=8,
        num_layers=1,
        seq_len=10,
        epochs=3,
        batch_size=16,
        learning_rate=1e-3,
    )
    X, y, _ = make_sequences(feats, target, seq_len=cfg.seq_len, horizon=1)

    set_global_seed(123)
    fc1 = LSTMForecaster(cfg)
    fc1.fit(X, y)
    p1 = fc1.predict(X)

    set_global_seed(123)
    fc2 = LSTMForecaster(cfg)
    fc2.fit(X, y)
    p2 = fc2.predict(X)

    np.testing.assert_allclose(p1, p2, atol=1e-6)


def test_torch_available_flag():
    """Module exposes a TORCH_AVAILABLE bool."""
    assert isinstance(TORCH_AVAILABLE, bool)


def test_walk_forward_rejects_duplicated_index():
    """walk_forward_train must reject features with duplicated timestamps."""
    feats, target = _synthetic_panel(n_bars=120, n_features=3, seed=5)
    # Duplicate the second timestamp.
    bad_idx = feats.index.tolist()
    bad_idx[2] = bad_idx[1]
    bad_feats = feats.set_axis(pd.Index(bad_idx))
    bad_target = target.set_axis(pd.Index(bad_idx))
    cfg = LSTMConfig(
        input_dim=3,
        hidden_dim=4,
        num_layers=1,
        seq_len=5,
        epochs=1,
        batch_size=8,
    )
    fc = LSTMForecaster(cfg)
    with pytest.raises(ValueError, match="unique"):
        walk_forward_train(
            fc, bad_feats, bad_target, train_size=60, test_size=20, step=20
        )


def test_walk_forward_pred_timestamps_match_positional_slice():
    """Audit fix: prediction timestamps come from positional slicing of
    features.index, not from a per-ts ``features.index.get_loc`` lookup. The
    two paths must agree on a unique, monotonic index.
    """
    feats, target = _synthetic_panel(n_bars=300, n_features=2, seed=8)
    cfg = LSTMConfig(
        input_dim=2,
        hidden_dim=4,
        num_layers=1,
        seq_len=8,
        epochs=1,
        batch_size=16,
        learning_rate=5e-3,
    )
    fc = LSTMForecaster(cfg)
    df = walk_forward_train(fc, feats, target, train_size=150, test_size=40, step=40)
    # Every prediction timestamp must be in the original features.index, and
    # must be reachable via a positional offset from the test-window start.
    assert df.index.isin(feats.index).all()
    assert df.index.is_monotonic_increasing
    assert df.index.is_unique


def test_save_load_weights_only_secure(tmp_path):
    """Saved checkpoints must reload with weights_only=True (audit fix #2).

    Verifies (a) load returns identical predictions and (b) the load() call
    path uses weights_only=True (i.e. cannot deserialize arbitrary pickled
    classes; we patch torch.load to detect the kwarg).
    """
    feats, target = _synthetic_panel(n_bars=120, n_features=4, seed=11)
    cfg = LSTMConfig(input_dim=4, hidden_dim=8, num_layers=1, seq_len=10, epochs=2)
    X, y, _ = make_sequences(feats, target, seq_len=cfg.seq_len, horizon=1)

    fc = LSTMForecaster(cfg)
    fc.fit(X, y)
    preds_before = fc.predict(X)
    path = str(tmp_path / "lstm_secure.pt")
    fc.save(path)

    # Patch torch.load to capture kwargs and verify weights_only=True is used.
    captured: dict = {}
    real_load = torch.load

    def spy_load(*args, **kwargs):
        captured["weights_only"] = kwargs.get("weights_only", None)
        return real_load(*args, **kwargs)

    torch.load = spy_load
    try:
        fc2 = LSTMForecaster(LSTMConfig(input_dim=4, seq_len=10))
        fc2.load(path)
    finally:
        torch.load = real_load

    assert captured.get("weights_only") is True
    preds_after = fc2.predict(X)
    np.testing.assert_allclose(preds_before, preds_after, atol=1e-6)
