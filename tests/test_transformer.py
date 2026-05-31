"""Tests for time-series Transformer multi-horizon forecaster.

Run: uv run --with torch pytest aurora/tests/test_transformer.py -v

If torch is not installed, all tests are skipped via importorskip.
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd
import pytest

torch = pytest.importorskip("torch")  # noqa: F401  -- skips entire module without torch

from aurora.ml.transformer import (  # noqa: E402
    TimeSeriesTransformer,
    TransformerConfig,
    causal_mask,
    make_multi_horizon_sequences,
    PositionalEncoding,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def small_cfg():
    return TransformerConfig(
        input_dim=4,
        d_model=16,
        n_heads=2,
        num_layers=1,
        dim_feedforward=32,
        dropout=0.0,
        seq_len=8,
        horizons=(1, 3, 5),
        learning_rate=1e-3,
        batch_size=8,
        epochs=2,
        device="cpu",
        seed=123,
    )


@pytest.fixture
def synthetic_features_target():
    rng = np.random.default_rng(0)
    T = 200
    idx = pd.date_range("2021-01-01", periods=T, freq="B")
    X = rng.normal(size=(T, 4)).astype(np.float32)
    feats = pd.DataFrame(X, index=idx, columns=[f"f{i}" for i in range(4)])
    # Target = next-step return-like signal driven by feature 0.
    target = pd.Series(0.5 * X[:, 0] + 0.05 * rng.normal(size=T), index=idx, name="y")
    return feats, target


# ---------------------------------------------------------------------------
# make_multi_horizon_sequences
# ---------------------------------------------------------------------------

def test_make_sequences_shapes(synthetic_features_target):
    feats, target = synthetic_features_target
    seq_len = 8
    horizons = (1, 3, 5)
    X, y = make_multi_horizon_sequences(feats, target, seq_len=seq_len, horizons=horizons)
    assert X.ndim == 3
    assert X.shape[1] == seq_len
    assert X.shape[2] == feats.shape[1]
    assert y.shape == (X.shape[0], len(horizons))
    # min_h=1 so last anchor is T-1-1 = T-2; first = seq_len-1
    expected_n = (len(feats) - 1) - (seq_len - 1)
    assert X.shape[0] == expected_n


def test_no_lookahead(synthetic_features_target):
    feats, target = synthetic_features_target
    seq_len = 8
    horizons = (1, 3, 5)
    X, y = make_multi_horizon_sequences(feats, target, seq_len=seq_len, horizons=horizons)

    feat_arr = feats.to_numpy(dtype=np.float32)
    tgt_arr = target.to_numpy(dtype=np.float32)
    first_anchor = seq_len - 1

    # Sample i corresponds to anchor t = first_anchor + i.
    for i in (0, 1, 7, X.shape[0] - 1):
        t = first_anchor + i
        # Window covers bars [t - seq_len + 1, t], inclusive.
        np.testing.assert_array_equal(X[i], feat_arr[t - seq_len + 1 : t + 1])
        for h_idx, h in enumerate(horizons):
            j = t + h
            if j <= len(target) - 1:
                assert y[i, h_idx] == pytest.approx(tgt_arr[j])
            else:
                assert np.isnan(y[i, h_idx])


def test_make_sequences_validates_horizons():
    feats = pd.DataFrame({"a": [1.0, 2.0, 3.0]})
    target = pd.Series([0.0, 0.0, 0.0])
    with pytest.raises(ValueError):
        make_multi_horizon_sequences(feats, target, seq_len=2, horizons=())
    with pytest.raises(ValueError):
        make_multi_horizon_sequences(feats, target, seq_len=2, horizons=(0, 1))


# ---------------------------------------------------------------------------
# Positional encoding & causal mask
# ---------------------------------------------------------------------------

def test_positional_encoding_shape():
    pe = PositionalEncoding(d_model=16, max_len=64)
    x = torch.zeros(2, 12, 16)
    out = pe(x)
    assert out.shape == (2, 12, 16)
    # Position 0 should differ from position 1 in the encoding.
    assert not torch.allclose(out[0, 0, :], out[0, 1, :])


def test_causal_mask_shape():
    m = causal_mask(5)
    assert m.shape == (5, 5)
    assert m.dtype == torch.bool
    # Strictly upper-triangular: True only above the main diagonal.
    expected = torch.triu(torch.ones(5, 5, dtype=torch.bool), diagonal=1)
    assert torch.equal(m, expected)
    # Diagonal must be False (a position can attend to itself).
    assert not m.diag().any()


# ---------------------------------------------------------------------------
# Transformer forward / fit / predict
# ---------------------------------------------------------------------------

def test_transformer_forward(small_cfg):
    model = TimeSeriesTransformer(small_cfg)
    rng = np.random.default_rng(1)
    X = rng.normal(size=(5, small_cfg.seq_len, small_cfg.input_dim)).astype(np.float32)
    out = model.predict(X)
    assert out.shape == (5, len(small_cfg.horizons))
    assert np.isfinite(out).all()


def test_fit_runs(small_cfg, synthetic_features_target):
    feats, target = synthetic_features_target
    X, y = make_multi_horizon_sequences(
        feats, target, seq_len=small_cfg.seq_len, horizons=small_cfg.horizons
    )
    # Limit to first 80 samples to keep this fast.
    X = X[:80]
    y = y[:80]
    model = TimeSeriesTransformer(small_cfg)
    history = model.fit(X, y)
    assert "train_loss" in history
    assert len(history["train_loss"]) == small_cfg.epochs
    losses = history["train_loss"]
    # Either decreasing across the run or at least finite.
    assert all(np.isfinite(l) for l in losses)
    assert losses[-1] <= losses[0] + 1e-3 or np.isclose(losses[-1], losses[0], atol=1e-2)


def test_predict_shape(small_cfg):
    model = TimeSeriesTransformer(small_cfg)
    rng = np.random.default_rng(2)
    X = rng.normal(size=(11, small_cfg.seq_len, small_cfg.input_dim)).astype(np.float32)
    pred = model.predict(X)
    assert pred.shape == (11, len(small_cfg.horizons))


def test_save_load_roundtrip(tmp_path, small_cfg):
    from dataclasses import replace
    model = TimeSeriesTransformer(small_cfg)
    rng = np.random.default_rng(3)
    X = rng.normal(size=(7, small_cfg.seq_len, small_cfg.input_dim)).astype(np.float32)
    y_pred_before = model.predict(X)

    path = os.path.join(str(tmp_path), "tx.pt")
    model.save(path)

    # Build a second instance with a *different* seed so its random init
    # genuinely differs, then verify load() restores identical predictions.
    other_cfg = replace(small_cfg, seed=999)
    model2 = TimeSeriesTransformer(other_cfg)
    y_pred_diff = model2.predict(X)
    assert not np.allclose(y_pred_diff, y_pred_before)
    # load needs matching architecture, so swap back to the original config
    # for state_dict compatibility (load enforces structural fields only).
    model2 = TimeSeriesTransformer(other_cfg)
    model2.load(path)
    y_pred_after = model2.predict(X)
    np.testing.assert_allclose(y_pred_before, y_pred_after, rtol=1e-5, atol=1e-6)


def test_seed_reproducibility(small_cfg):
    rng = np.random.default_rng(4)
    X = rng.normal(size=(6, small_cfg.seq_len, small_cfg.input_dim)).astype(np.float32)

    a = TimeSeriesTransformer(small_cfg)
    b = TimeSeriesTransformer(small_cfg)
    out_a = a.predict(X)
    out_b = b.predict(X)
    np.testing.assert_allclose(out_a, out_b, rtol=1e-6, atol=1e-7)


# ---------------------------------------------------------------------------
# Audit fix: causal-mask robustness — shuffling future bars cannot change
# predictions for earlier positions inside a sequence (issue #3).
# ---------------------------------------------------------------------------


def test_causal_mask_shuffle_future_invariance(small_cfg):
    """For a fixed model, predicting [bar0..bart..barN] must NOT depend on
    bars[t+1:] inside the sequence.

    Build N independent sequences from the same model. For each sequence we
    feed the original window and a window in which bars after position t are
    permuted. Because the encoder uses a strict upper-triangular causal mask,
    the output at every position k <= t must be identical.

    We can't directly read intermediate states from the wrapper, so we use
    a stand-alone model run and slice the last-position output across two
    seq_len-prefix variants of the sequence.
    """
    import torch
    rng = np.random.default_rng(1234)
    seq_len = small_cfg.seq_len
    model = TimeSeriesTransformer(small_cfg)
    model.model.eval()

    # Build a (1, seq_len, input_dim) sample.
    base = rng.normal(size=(1, seq_len, small_cfg.input_dim)).astype(np.float32)
    base_t = torch.as_tensor(base, dtype=torch.float32, device=model.device)

    # For each prefix length t, the model output computed from the prefix
    # padded with arbitrary future bars must equal the output from the prefix
    # padded with the original future bars — when the head reads the position
    # at t. The wrapper's head reads the LAST position only, so we compare
    # by truncating the input to length t+1 and confirming that both runs of
    # the encoder give identical output at the t-th position. We do this by
    # comparing forward passes on truncated sequences.
    with torch.no_grad():
        # Cycle through interior anchors: t in {2, seq_len // 2, seq_len - 2}.
        anchors = sorted({2, seq_len // 2, seq_len - 2})
        for t in anchors:
            if t < 1 or t >= seq_len:
                continue
            # Two variants: original; shuffle bars [t+1:] randomly.
            shuffled = base.copy()
            future_idx = np.arange(t + 1, seq_len)
            perm = rng.permutation(future_idx)
            shuffled[0, t + 1:, :] = base[0, perm, :]

            shuffled_t = torch.as_tensor(shuffled, dtype=torch.float32,
                                         device=model.device)
            # Slice both inputs to a length-(t+1) window so the wrapper sees
            # the same prefix length, and the prediction reflects only bars
            # [0..t]. (Causal-masking guarantees the t-th position's encoder
            # output ignores positions > t even within the full window, but
            # we cross-check by also running the original full window.)
            # Both runs must therefore match exactly.
            # Pad the head input to seq_len with zeros for prediction shape.
            pad_orig = base.copy()
            pad_orig[0, t + 1:, :] = 0.0
            pad_shuf = shuffled.copy()
            pad_shuf[0, t + 1:, :] = 0.0
            out_orig = model.predict(pad_orig)
            # NOTE: pad_orig and pad_shuf differ only past position t, but
            # the head reads the LAST (seq_len-1) position which DOES depend
            # on later inputs. So we cannot use the wrapper's predict()
            # directly here. Instead, we forward-pass and read the t-th
            # encoder output before the head.
            from aurora.ml.transformer import causal_mask
            x_orig = torch.as_tensor(base, dtype=torch.float32, device=model.device)
            x_shuf = shuffled_t
            h_o = model.model.input_proj(x_orig)
            h_o = model.model.pos_enc(h_o)
            mask_o = causal_mask(h_o.size(1), device=h_o.device)
            enc_o = model.model.encoder(h_o, mask=mask_o)
            h_s = model.model.input_proj(x_shuf)
            h_s = model.model.pos_enc(h_s)
            mask_s = causal_mask(h_s.size(1), device=h_s.device)
            enc_s = model.model.encoder(h_s, mask=mask_s)
            # Encoder output at position t must be invariant.
            torch.testing.assert_close(
                enc_o[0, t, :], enc_s[0, t, :], rtol=1e-5, atol=1e-6
            )
            # Quiet unused
            _ = out_orig


def test_make_sequences_rejects_index_mismatch():
    """Audit fix: target.index must equal features.index up front; reindex
    would silently introduce NaN targets and mask the alignment bug.
    """
    idx_a = pd.date_range("2020-01-01", periods=10, freq="B")
    idx_b = pd.date_range("2020-01-15", periods=10, freq="B")
    feats = pd.DataFrame(np.zeros((10, 2)), index=idx_a, columns=["a", "b"])
    target = pd.Series(np.zeros(10), index=idx_b)
    with pytest.raises(ValueError, match="target.index"):
        make_multi_horizon_sequences(feats, target, seq_len=4, horizons=(1, 2))


def test_positional_encoding_warns_on_odd_d_model():
    """Audit fix: PositionalEncoding emits a UserWarning for d_model < 2 or
    odd d_model so the caller knows the cosine channels are degenerate."""
    import warnings as _w
    with _w.catch_warnings(record=True) as caught:
        _w.simplefilter("always")
        PositionalEncoding(d_model=1, max_len=8)
    user_warnings = [w for w in caught if issubclass(w.category, UserWarning)]
    assert any("d_model < 2" in str(w.message) for w in user_warnings)
    with _w.catch_warnings(record=True) as caught:
        _w.simplefilter("always")
        PositionalEncoding(d_model=5, max_len=8)
    user_warnings = [w for w in caught if issubclass(w.category, UserWarning)]
    assert any("odd" in str(w.message) for w in user_warnings)


def test_save_load_weights_only_secure(tmp_path, small_cfg):
    """Saved transformer checkpoint must reload with weights_only=True
    (audit fix #2)."""
    import torch as _torch
    model = TimeSeriesTransformer(small_cfg)
    rng = np.random.default_rng(5)
    X = rng.normal(size=(7, small_cfg.seq_len, small_cfg.input_dim)).astype(np.float32)
    preds_before = model.predict(X)

    path = os.path.join(str(tmp_path), "tx_secure.pt")
    model.save(path)

    captured: dict = {}
    real_load = _torch.load

    def spy_load(*args, **kwargs):
        captured["weights_only"] = kwargs.get("weights_only", None)
        return real_load(*args, **kwargs)

    _torch.load = spy_load
    try:
        model2 = TimeSeriesTransformer(small_cfg)
        model2.load(path)
    finally:
        _torch.load = real_load

    assert captured.get("weights_only") is True
    preds_after = model2.predict(X)
    np.testing.assert_allclose(preds_before, preds_after, rtol=1e-5, atol=1e-6)
