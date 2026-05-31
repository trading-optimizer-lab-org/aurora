"""LSTM return forecaster (Aurora v1.3 Batch N.1).

Lightweight PyTorch LSTM for next-bar return prediction with:
  * sliding-window sequence construction (anti-lookahead).
  * walk-forward retraining for out-of-sample evaluation.
  * save/load roundtrip.
  * lazy torch import so the module loads without torch installed.

Design follows aurora.ml convention: lazy/optional heavy deps, dict-style
fit() history, numpy in / numpy out for inference.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional, Tuple, Any

import numpy as np
import pandas as pd

try:  # lazy availability flag
    import torch
    import torch.nn as _nn
    TORCH_AVAILABLE = True
except ImportError:  # pragma: no cover - environment dependent
    torch = None  # type: ignore
    _nn = None  # type: ignore
    TORCH_AVAILABLE = False


def _require_torch() -> None:
    if not TORCH_AVAILABLE:
        raise ImportError(
            "aurora.ml.lstm requires torch. Install with: "
            "uv add torch  (or: pip install torch)"
        )


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class LSTMConfig:
    """Hyper-parameters for :class:`LSTMForecaster`."""

    input_dim: int = 10
    hidden_dim: int = 32
    num_layers: int = 2
    dropout: float = 0.1
    seq_len: int = 20
    horizon: int = 1
    learning_rate: float = 1e-3
    batch_size: int = 64
    epochs: int = 20
    device: str = "cpu"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "LSTMConfig":
        return cls(**d)


# ---------------------------------------------------------------------------
# Sequence construction (no torch needed)
# ---------------------------------------------------------------------------

def make_sequences(
    features: pd.DataFrame,
    target: pd.Series,
    seq_len: int,
    horizon: int = 1,
) -> Tuple[np.ndarray, np.ndarray, pd.Index]:
    """Build sliding-window supervised tensors.

    For each valid time t, the sample is:
        X[i] = features.iloc[t - seq_len + 1 : t + 1]   # bars up to and including t
        y[i] = target.iloc[t + horizon]                  # target horizon bars ahead

    Anti-lookahead: X uses information up to bar t inclusive; y is at t+horizon.

    Parameters
    ----------
    features : (T, F) DataFrame
    target   : (T,) Series, aligned with features.index
    seq_len  : lookback window length
    horizon  : forecast horizon (>=1)

    Returns
    -------
    X            : np.ndarray, shape (N, seq_len, F)
    y            : np.ndarray, shape (N,)
    valid_index  : pd.Index of length N. valid_index[i] is the timestamp at the
                   *end* of the input window (time t), i.e. the bar from which
                   the prediction is made. The matching target timestamp is
                   features.index[t + horizon].
    """
    if seq_len < 1:
        raise ValueError("seq_len must be >= 1")
    if horizon < 1:
        raise ValueError("horizon must be >= 1")
    if len(features) != len(target):
        raise ValueError("features and target must have the same length")
    if not features.index.equals(target.index):
        raise ValueError("features.index must equal target.index")

    feats = features.to_numpy(dtype=np.float32, copy=False)
    tgt = target.to_numpy(dtype=np.float32, copy=False)
    T = feats.shape[0]
    n_features = feats.shape[1] if feats.ndim == 2 else 1

    # last valid t is such that t+horizon < T, and t-seq_len+1 >= 0
    first_t = seq_len - 1
    last_t = T - 1 - horizon
    if last_t < first_t:
        empty_X = np.empty((0, seq_len, n_features), dtype=np.float32)
        empty_y = np.empty((0,), dtype=np.float32)
        return empty_X, empty_y, features.index[:0]

    n = last_t - first_t + 1
    X = np.empty((n, seq_len, n_features), dtype=np.float32)
    y = np.empty((n,), dtype=np.float32)
    end_indices = []
    for i, t in enumerate(range(first_t, last_t + 1)):
        X[i] = feats[t - seq_len + 1 : t + 1]
        y[i] = tgt[t + horizon]
        end_indices.append(t)

    valid_index = features.index[end_indices]
    return X, y, valid_index


# ---------------------------------------------------------------------------
# Model + Forecaster
# ---------------------------------------------------------------------------

def _build_module(config: LSTMConfig):
    """Build the underlying nn.Module. Requires torch."""
    _require_torch()

    class _LSTMRegressor(_nn.Module):
        def __init__(self, cfg: LSTMConfig):
            super().__init__()
            self.cfg = cfg
            # nn.LSTM applies dropout only between layers when num_layers >= 2.
            lstm_dropout = cfg.dropout if cfg.num_layers > 1 else 0.0
            self.lstm = _nn.LSTM(
                input_size=cfg.input_dim,
                hidden_size=cfg.hidden_dim,
                num_layers=cfg.num_layers,
                batch_first=True,
                dropout=lstm_dropout,
            )
            self.head = _nn.Linear(cfg.hidden_dim, 1)

        def forward(self, x):  # x: (B, seq_len, input_dim)
            out, _ = self.lstm(x)
            last = out[:, -1, :]  # (B, hidden_dim)
            return self.head(last)  # (B, 1)

    return _LSTMRegressor(config)


class LSTMForecaster:
    """Thin wrapper around an LSTM regressor for return prediction.

    Usage
    -----
    >>> cfg = LSTMConfig(input_dim=5, seq_len=20, epochs=5)
    >>> fc = LSTMForecaster(cfg)
    >>> hist = fc.fit(X_train, y_train)
    >>> preds = fc.predict(X_test)
    """

    def __init__(self, config: LSTMConfig):
        self.config = config
        self._model: Any = None
        self._optim: Any = None

    # ----- internals -----

    def _build(self) -> None:
        _require_torch()
        # Respect global seed if set.
        try:
            from aurora.core.seed import get_seed
            s = get_seed()
            if s is not None:
                torch.manual_seed(int(s))
        except ImportError:
            pass
        self._model = _build_module(self.config).to(self.config.device)
        self._optim = torch.optim.Adam(
            self._model.parameters(), lr=self.config.learning_rate
        )

    # ----- public API -----

    def fit(self, X: np.ndarray, y: np.ndarray) -> dict:
        """Train the LSTM. Returns dict with 'train_loss' (list of per-epoch means)."""
        _require_torch()
        from torch.utils.data import DataLoader, TensorDataset  # local import
        if self._model is None:
            self._build()

        device = torch.device(self.config.device)
        # Keep the source tensors on CPU; DataLoader streams batches to device.
        X_t = torch.as_tensor(X, dtype=torch.float32)
        y_t = torch.as_tensor(y, dtype=torch.float32).reshape(-1, 1)

        n = X_t.shape[0]
        if n == 0:
            return {"train_loss": []}
        bs = max(1, min(self.config.batch_size, n))
        loss_fn = _nn.MSELoss()

        # Deterministic shuffling for the DataLoader.
        try:
            from aurora.core.seed import get_seed
            seed_val = get_seed()
        except ImportError:
            seed_val = None
        gen = torch.Generator()
        if seed_val is not None:
            gen.manual_seed(int(seed_val))
        else:
            gen.manual_seed(0)

        ds = TensorDataset(X_t, y_t)
        loader = DataLoader(
            ds,
            batch_size=bs,
            shuffle=True,
            drop_last=False,
            generator=gen,
            pin_memory=(device.type == "cuda"),
        )

        history = []
        self._model.train()
        for _ in range(self.config.epochs):
            epoch_losses = []
            for xb, yb in loader:
                xb = xb.to(device, non_blocking=True)
                yb = yb.to(device, non_blocking=True)
                self._optim.zero_grad()
                pred = self._model(xb)
                loss = loss_fn(pred, yb)
                loss.backward()
                self._optim.step()
                epoch_losses.append(float(loss.detach().cpu().item()))
            history.append(float(np.mean(epoch_losses)))

        return {"train_loss": history}

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Return shape-(N,) numpy array of predictions."""
        _require_torch()
        if self._model is None:
            raise RuntimeError("Model not initialised. Call fit() or load() first.")
        self._model.eval()
        X_t = torch.as_tensor(X, dtype=torch.float32, device=self.config.device)
        if X_t.shape[0] == 0:
            return np.empty((0,), dtype=np.float32)
        with torch.no_grad():
            out = self._model(X_t)
        return out.detach().cpu().numpy().reshape(-1)

    def save(self, path: str) -> None:
        _require_torch()
        if self._model is None:
            raise RuntimeError("Cannot save: model has not been built.")
        # Save state_dict + plain dict config (no pickled custom classes) so
        # that load() can use weights_only=True safely.
        torch.save(
            {
                "config": dict(self.config.to_dict()),
                "state_dict": self._model.state_dict(),
            },
            path,
        )

    def load(self, path: str) -> None:
        _require_torch()
        # weights_only=True refuses to unpickle arbitrary objects, eliminating
        # the RCE risk on malicious checkpoints.
        ckpt = torch.load(path, map_location=self.config.device, weights_only=True)
        # Preserve the CURRENT instance's device choice. The checkpoint may have
        # been saved on a CUDA host while we are loading on CPU (or vice versa).
        # Override the loaded ``device`` field with the caller's current value
        # so subsequent .to(...) calls land on the correct backend.
        loaded_device = self.config.device
        cfg = LSTMConfig.from_dict(ckpt["config"])
        cfg.device = loaded_device
        self.config = cfg
        self._build()
        self._model.load_state_dict(ckpt["state_dict"])
        self._model.to(self.config.device)


# ---------------------------------------------------------------------------
# Walk-forward training
# ---------------------------------------------------------------------------

def walk_forward_train(
    forecaster: LSTMForecaster,
    features: pd.DataFrame,
    target: pd.Series,
    train_size: int = 252 * 3,
    test_size: int = 63,
    step: int = 63,
) -> pd.DataFrame:
    """Rolling walk-forward training.

    For each fold, fit on `train_size` consecutive bars and predict the next
    `test_size` bars. Slide the window forward by `step` bars and repeat.

    The forecaster instance is rebuilt (fresh weights) at each fold to avoid
    leaking information across folds.

    Returns
    -------
    pd.DataFrame indexed by the prediction timestamp with columns:
        - prediction : model output
        - target     : realised target value
        - fold       : 0-based fold index
    """
    _require_torch()
    cfg = forecaster.config
    seq_len = cfg.seq_len
    horizon = cfg.horizon

    if not features.index.equals(target.index):
        raise ValueError("features.index must equal target.index")
    # Duplicated timestamps would silently break the test-window slicing
    # below (positions inferred from a non-unique index can map to multiple
    # rows). Reject up front so the caller can de-duplicate explicitly.
    if not features.index.is_unique:
        raise ValueError(
            "features.index must be unique for walk_forward_train; "
            "duplicated timestamps break positional slicing of the test window."
        )

    T = len(features)
    rows = []
    fold = 0
    start = 0
    while start + train_size + test_size <= T:
        train_feat = features.iloc[start : start + train_size]
        train_tgt = target.iloc[start : start + train_size]

        # Test window must include `seq_len - 1` warm-up bars from inside the
        # train window so the first test sequence ends at the first true test
        # bar. We use bars [start + train_size - seq_len + 1, start + train_size + test_size).
        test_lo = start + train_size - seq_len + 1
        test_hi = start + train_size + test_size  # exclusive
        test_feat = features.iloc[test_lo:test_hi]
        test_tgt = target.iloc[test_lo:test_hi]

        X_tr, y_tr, _ = make_sequences(train_feat, train_tgt, seq_len, horizon)
        X_te, y_te, idx_te = make_sequences(test_feat, test_tgt, seq_len, horizon)

        if X_tr.shape[0] == 0 or X_te.shape[0] == 0:
            start += step
            fold += 1
            continue

        # Fresh model per fold.
        forecaster._model = None
        forecaster._optim = None
        forecaster.fit(X_tr, y_tr)
        preds = forecaster.predict(X_te)

        # ``idx_te`` is a contiguous run of ``test_feat`` index values starting
        # at the (seq_len - 1)-th row of ``test_feat`` (positional, by
        # ``make_sequences``). Convert directly to features-relative integer
        # positions and add ``horizon`` to land on the prediction-target bar.
        # We do not call ``features.index.get_loc(ts)`` per ts: that lookup is
        # quadratic on duplicated indexes and we already enforce uniqueness
        # above, but the positional path is also strictly faster.
        first_te_pos_in_features = test_lo + (seq_len - 1)
        n_te = len(idx_te)
        pred_positions = np.arange(
            first_te_pos_in_features + horizon,
            first_te_pos_in_features + horizon + n_te,
            dtype=int,
        )
        pred_timestamps = features.index[pred_positions]
        for ts, p, yv in zip(pred_timestamps, preds, y_te):
            rows.append({"timestamp": ts, "prediction": float(p), "target": float(yv), "fold": fold})

        start += step
        fold += 1

    if not rows:
        return pd.DataFrame(columns=["prediction", "target", "fold"])
    df = pd.DataFrame(rows).set_index("timestamp")
    return df
