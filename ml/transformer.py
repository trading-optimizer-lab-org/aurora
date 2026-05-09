"""Time-series Transformer for multi-horizon return forecasting.

PyTorch encoder-only Transformer with sinusoidal positional encoding and
causal self-attention mask. Produces forecasts at multiple horizons in a
single forward pass via a linear projection head.

Public API:
- TransformerConfig:           dataclass with hyperparameters.
- TimeSeriesTransformer:       fit / predict / save / load wrapper.
- make_multi_horizon_sequences: builds (N, seq_len, n_features) windows and
                                aligned (N, len(horizons)) multi-horizon targets.

Anti-lookahead contract: the input window for sample ``i`` covers bars up to
and including time ``t``. Target ``y[i, h_idx]`` is the value of ``target`` at
``t + horizons[h_idx]``. The encoder uses an upper-triangular causal mask so
attention at position ``k`` cannot read positions ``> k``.

Torch is an optional dependency. Importing this module does not require torch;
top-level guards expose ``TORCH_AVAILABLE``.
"""
from __future__ import annotations

import math
import warnings
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

try:  # optional dep
    import torch
    from torch import nn
    from torch.utils.data import DataLoader, TensorDataset
    TORCH_AVAILABLE = True
except Exception:  # pragma: no cover - exercised when torch missing
    torch = None  # type: ignore[assignment]
    nn = None  # type: ignore[assignment]
    DataLoader = None  # type: ignore[assignment,misc]
    TensorDataset = None  # type: ignore[assignment,misc]
    TORCH_AVAILABLE = False


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class TransformerConfig:
    """Hyperparameters for the time-series Transformer.

    Defaults match a small daily-bar setup: 30 bars of history, 10 features,
    and three horizons (1d / 1w / 1m).
    """
    input_dim: int = 10
    d_model: int = 64
    n_heads: int = 4
    num_layers: int = 2
    dim_feedforward: int = 128
    dropout: float = 0.1
    seq_len: int = 30
    horizons: Tuple[int, ...] = (1, 5, 21)
    learning_rate: float = 1e-4
    batch_size: int = 32
    epochs: int = 30
    device: str = "cpu"
    seed: Optional[int] = 42


# ---------------------------------------------------------------------------
# Sequence builder (anti-lookahead)
# ---------------------------------------------------------------------------

def make_multi_horizon_sequences(
    features: pd.DataFrame,
    target: pd.Series,
    seq_len: int,
    horizons: Tuple[int, ...],
) -> Tuple[np.ndarray, np.ndarray]:
    """Build sliding windows ``X`` and aligned multi-horizon targets ``y``.

    For each anchor index ``t`` such that the window ``[t - seq_len + 1, t]``
    is fully observed and at least one horizon is reachable:

      - ``X[i] = features.iloc[t - seq_len + 1 : t + 1].to_numpy()``
        shape ``(seq_len, n_features)``
      - ``y[i, h_idx] = target.iloc[t + horizons[h_idx]]``
        ``NaN`` if ``t + horizons[h_idx]`` is past the end of ``target``.

    Args:
        features: DataFrame ``(T, n_features)``, indexed monotonically.
        target:   Series ``(T,)`` aligned to ``features``.
        seq_len:  number of historical bars per window (>= 1).
        horizons: forecast horizons ``h >= 1``.

    Returns:
        (X, y) where
            X shape: ``(N, seq_len, n_features)`` float32
            y shape: ``(N, len(horizons))``  float32 with NaN where unobserved.
    """
    if not isinstance(features, pd.DataFrame):
        raise TypeError("features must be a pd.DataFrame")
    if not isinstance(target, pd.Series):
        raise TypeError("target must be a pd.Series")
    if seq_len < 1:
        raise ValueError("seq_len must be >= 1")
    if len(horizons) == 0:
        raise ValueError("horizons must be non-empty")
    if any(h < 1 for h in horizons):
        raise ValueError("horizons must all be >= 1")
    if len(features) != len(target):
        raise ValueError("features and target must have the same length")
    # Reindexing target to features.index would silently introduce NaN if the
    # two indexes drifted apart; require the caller to align them up front.
    if not target.index.equals(features.index):
        raise ValueError(
            "target.index must equal features.index; reindexing would mask "
            "alignment bugs by silently introducing NaN targets."
        )

    feat_arr = features.to_numpy(dtype=np.float32, copy=False)
    tgt_arr = target.to_numpy(dtype=np.float32, copy=False)
    T = len(feat_arr)
    H = len(horizons)

    # anchor t runs from seq_len-1 .. T-1, but we need at least one valid horizon.
    last_anchor = T - 1
    first_anchor = seq_len - 1
    if first_anchor > last_anchor:
        return (
            np.empty((0, seq_len, feat_arr.shape[1]), dtype=np.float32),
            np.empty((0, H), dtype=np.float32),
        )

    # We allow t such that t + min(horizons) <= T-1 so we always have at least
    # one observable horizon. Beyond that, missing horizons are NaN.
    min_h = int(min(horizons))
    last_anchor = min(last_anchor, T - 1 - min_h)
    if last_anchor < first_anchor:
        return (
            np.empty((0, seq_len, feat_arr.shape[1]), dtype=np.float32),
            np.empty((0, H), dtype=np.float32),
        )

    n_samples = last_anchor - first_anchor + 1
    X = np.empty((n_samples, seq_len, feat_arr.shape[1]), dtype=np.float32)
    y: np.ndarray = np.full((n_samples, H), np.nan, dtype=np.float32)

    for i, t in enumerate(range(first_anchor, last_anchor + 1)):
        X[i] = feat_arr[t - seq_len + 1 : t + 1]
        for h_idx, h in enumerate(horizons):
            j = t + int(h)
            if j <= T - 1:
                y[i, h_idx] = tgt_arr[j]
            # else: leave NaN
    return X, y


# ---------------------------------------------------------------------------
# Torch modules (only defined when torch is available)
# ---------------------------------------------------------------------------

if TORCH_AVAILABLE:

    class PositionalEncoding(nn.Module):
        """Sinusoidal positional encoding (Vaswani et al., 2017).

        Forward input/output shape: ``(batch, seq_len, d_model)``.
        """

        def __init__(self, d_model: int, max_len: int = 4096):
            super().__init__()
            if d_model < 1:
                raise ValueError("d_model must be >= 1")
            if d_model < 2:
                warnings.warn(
                    "PositionalEncoding: d_model < 2 produces a sin-only "
                    "encoding with no cosine channel; the transformer will "
                    "still run but positional information is degenerate.",
                    UserWarning,
                    stacklevel=2,
                )
            elif d_model % 2 == 1:
                warnings.warn(
                    "PositionalEncoding: d_model is odd; the cosine channels "
                    "will cover only the even-indexed dimensions and the last "
                    "(odd) channel keeps its zero initialization.",
                    UserWarning,
                    stacklevel=2,
                )
            pe = torch.zeros(max_len, d_model)
            position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
            div_term = torch.exp(
                torch.arange(0, d_model, 2, dtype=torch.float)
                * (-math.log(10000.0) / d_model)
            )
            pe[:, 0::2] = torch.sin(position * div_term)
            if d_model > 1:
                pe[:, 1::2] = torch.cos(position * div_term[: pe[:, 1::2].shape[1]])
            self.register_buffer("pe", pe.unsqueeze(0))  # (1, max_len, d_model)

        def forward(self, x: "torch.Tensor") -> "torch.Tensor":
            seq_len = x.size(1)
            return x + self.pe[:, :seq_len, :]  # type: ignore[index]


    def causal_mask(seq_len: int, device=None) -> "torch.Tensor":
        """Upper-triangular boolean mask used by ``nn.TransformerEncoder``.

        Returns a ``(seq_len, seq_len)`` bool tensor where ``True`` at
        ``(i, j)`` blocks attention from query ``i`` to key ``j > i``.
        """
        m = torch.triu(
            torch.ones(seq_len, seq_len, dtype=torch.bool, device=device),
            diagonal=1,
        )
        return m


    class _TransformerNet(nn.Module):
        """Encoder-only Transformer with multi-horizon linear head."""

        def __init__(self, cfg: TransformerConfig):
            super().__init__()
            self.cfg = cfg
            self.input_proj = nn.Linear(cfg.input_dim, cfg.d_model)
            self.pos_enc = PositionalEncoding(cfg.d_model, max_len=max(cfg.seq_len, 4096))
            enc_layer = nn.TransformerEncoderLayer(
                d_model=cfg.d_model,
                nhead=cfg.n_heads,
                dim_feedforward=cfg.dim_feedforward,
                dropout=cfg.dropout,
                batch_first=True,
                activation="gelu",
            )
            # ``enable_nested_tensor=False`` is required for the fast-path to
            # accept a causal attention mask without raising on torch>=1.11
            # (PyTorch falls back to the slow path otherwise and emits a
            # warning about the mask being incompatible with nested tensors).
            self.encoder = nn.TransformerEncoder(
                enc_layer,
                num_layers=cfg.num_layers,
                enable_nested_tensor=False,
            )
            self.head = nn.Linear(cfg.d_model, len(cfg.horizons))

        def forward(self, x: "torch.Tensor") -> "torch.Tensor":
            # x: (batch, seq_len, input_dim)
            h = self.input_proj(x)
            h = self.pos_enc(h)
            mask = causal_mask(h.size(1), device=h.device)
            # ``is_causal=True`` lets PyTorch use the optimized causal kernel
            # when available; the explicit mask is still passed for older
            # backends that ignore the flag. Both paths agree on the masking
            # pattern (upper-triangular, diagonal=1).
            h = self.encoder(h, mask=mask, is_causal=True)
            last = h[:, -1, :]  # take output at the final (most recent) position
            return self.head(last)  # (batch, H)


# ---------------------------------------------------------------------------
# Public wrapper
# ---------------------------------------------------------------------------

class TimeSeriesTransformer:
    """Sklearn-style wrapper around the encoder-only Transformer.

    Raises ``ImportError`` on construction if torch is not installed.
    """

    def __init__(self, config: TransformerConfig):
        if not TORCH_AVAILABLE:
            raise ImportError(
                "PyTorch is required for TimeSeriesTransformer. "
                "Install with `pip install torch`."
            )
        self.config = config
        # Use a local RNG so we don't pollute the process-wide np.random / torch
        # global state. The torch model init still needs torch.manual_seed for
        # deterministic param init, so we set it via a temporary save/restore.
        self._np_rng = np.random.default_rng(config.seed)
        self._torch_gen = self._build_torch_generator(config.seed)
        self._init_model_under_seed(config)

    @staticmethod
    def _build_torch_generator(seed: Optional[int]) -> "torch.Generator":
        gen = torch.Generator()
        if seed is not None:
            gen.manual_seed(int(seed))
        return gen

    def _init_model_under_seed(self, config: TransformerConfig) -> None:
        """Initialize the model with deterministic param init.

        We capture and restore the global torch RNG state so calling this
        constructor doesn't mutate the global RNG seen by the rest of the
        program.
        """
        self.device = torch.device(config.device)
        if config.seed is None:
            self.model = _TransformerNet(config).to(self.device)
            return
        prev_state = torch.random.get_rng_state()
        cuda_prev = (
            torch.cuda.get_rng_state_all() if torch.cuda.is_available() else None
        )
        try:
            torch.manual_seed(int(config.seed))
            if torch.cuda.is_available():
                torch.cuda.manual_seed_all(int(config.seed))
            self.model = _TransformerNet(config).to(self.device)
        finally:
            torch.random.set_rng_state(prev_state)
            if cuda_prev is not None:
                torch.cuda.set_rng_state_all(cuda_prev)

    @staticmethod
    def _set_seed(seed: Optional[int]) -> None:
        """Deprecated: kept for backwards compat. Does NOT touch global RNG.

        Callers that previously relied on side-effect-based seeding should
        instead use the per-instance ``_np_rng`` and ``_torch_gen`` fields.
        """
        return None

    def _validate_xy(self, X: np.ndarray, y: Optional[np.ndarray] = None) -> None:
        if X.ndim != 3:
            raise ValueError(f"X must be 3D (N, seq_len, input_dim), got shape {X.shape}")
        if X.shape[1] != self.config.seq_len:
            raise ValueError(
                f"X seq_len mismatch: got {X.shape[1]}, expected {self.config.seq_len}"
            )
        if X.shape[2] != self.config.input_dim:
            raise ValueError(
                f"X input_dim mismatch: got {X.shape[2]}, expected {self.config.input_dim}"
            )
        if y is not None:
            H = len(self.config.horizons)
            if y.ndim != 2 or y.shape[1] != H:
                raise ValueError(f"y must be (N, {H}), got shape {y.shape}")
            if y.shape[0] != X.shape[0]:
                raise ValueError("X and y must share the first dimension")

    def fit(self, X: np.ndarray, y: np.ndarray) -> Dict[str, List[float]]:
        """Train the model with masked MSE over multi-horizon targets.

        Args:
            X: shape ``(N, seq_len, input_dim)``.
            y: shape ``(N, len(horizons))``; ``NaN`` entries are masked out
               of the loss.

        Returns:
            ``{"train_loss": [...]}`` per epoch (mean over batches).
        """
        self._validate_xy(X, y)

        x_t = torch.as_tensor(X, dtype=torch.float32)
        y_t = torch.as_tensor(y, dtype=torch.float32)
        mask_t = torch.isfinite(y_t)
        # zero out NaN to keep grads finite; masked out by mask_t in loss.
        y_t = torch.where(mask_t, y_t, torch.zeros_like(y_t))

        ds = TensorDataset(x_t, y_t, mask_t)
        # Reuse the per-instance Generator built in __init__ so DataLoader
        # shuffling is deterministic without polluting the global torch RNG.
        # Re-seeding here would discard the RNG state advanced by previous
        # fit() calls, breaking the contract that successive epochs across
        # consecutive fits draw from the same stream.
        loader = DataLoader(
            ds,
            batch_size=self.config.batch_size,
            shuffle=True,
            drop_last=False,
            generator=self._torch_gen,
            pin_memory=(self.device.type == "cuda"),
        )

        optim = torch.optim.Adam(self.model.parameters(), lr=self.config.learning_rate)
        history: List[float] = []
        self.model.train()
        for _ in range(self.config.epochs):
            losses: List[float] = []
            for xb, yb, mb in loader:
                xb = xb.to(self.device)
                yb = yb.to(self.device)
                mb = mb.to(self.device)
                optim.zero_grad()
                pred = self.model(xb)
                diff2 = (pred - yb) ** 2
                masked = diff2 * mb.float()
                denom = mb.float().sum().clamp_min(1.0)
                loss = masked.sum() / denom
                loss.backward()
                optim.step()
                losses.append(float(loss.detach().cpu()))
            history.append(float(np.mean(losses)) if losses else float("nan"))
        return {"train_loss": history}

    @torch.no_grad() if TORCH_AVAILABLE else (lambda f: f)
    def predict(self, X: np.ndarray) -> np.ndarray:
        """Return forecasts of shape ``(N, len(horizons))``."""
        self._validate_xy(X)
        self.model.eval()
        x_t = torch.as_tensor(X, dtype=torch.float32, device=self.device)
        out = self.model(x_t)
        return out.detach().cpu().numpy()

    def save(self, path: str) -> None:
        """Persist model weights and config to ``path`` (torch ``.pt`` file)."""
        # Build a plain-dict snapshot of the config (no pickled custom classes)
        # so the checkpoint can be loaded with weights_only=True.
        cfg_dict = {}
        for k, v in self.config.__dict__.items():
            if isinstance(v, tuple):
                cfg_dict[k] = list(v)
            else:
                cfg_dict[k] = v
        payload = {
            "state_dict": self.model.state_dict(),
            "config": cfg_dict,
        }
        torch.save(payload, path)

    def load(self, path: str) -> None:
        """Load weights from ``path`` into the existing model.

        Config compatibility is checked on the load-bearing fields.
        """
        # weights_only=True refuses to unpickle arbitrary Python objects,
        # eliminating the RCE risk on a malicious checkpoint.
        payload = torch.load(path, map_location=self.device, weights_only=True)
        cfg_saved = payload.get("config", {})
        for key in (
            "input_dim",
            "d_model",
            "n_heads",
            "num_layers",
            "dim_feedforward",
            "seq_len",
            "horizons",
        ):
            saved = cfg_saved.get(key)
            current = getattr(self.config, key)
            # tuples vs lists: normalize for compare
            if isinstance(saved, list):
                saved = tuple(saved)
            if isinstance(current, list):
                current = tuple(current)
            if saved != current:
                raise ValueError(
                    f"config mismatch on '{key}': saved={saved!r} vs current={current!r}"
                )
        self.model.load_state_dict(payload["state_dict"])
        self.model.to(self.device)


__all__ = [
    "TORCH_AVAILABLE",
    "TransformerConfig",
    "TimeSeriesTransformer",
    "make_multi_horizon_sequences",
]
