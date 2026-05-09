"""Denoising-diffusion scenario generator for return paths.

Implements a small Denoising Diffusion Probabilistic Model (DDPM) on a panel
of historical returns. Once trained, ``sample(n_paths, horizon)`` produces
synthetic forward return scenarios that respect the empirical distribution
shape (e.g. fat tails) better than a Gaussian baseline.

Architecture: 1D MLP-based denoiser over the *horizon-window* representation.
The "image" we denoise is a flattened ``(horizon * n_assets)`` vector.

Lazy torch dependency.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

try:
    import torch
    from torch import nn
    TORCH_AVAILABLE = True
except ImportError:  # pragma: no cover
    torch = None
    nn = None
    TORCH_AVAILABLE = False


def _require_torch() -> None:
    if not TORCH_AVAILABLE:
        raise ImportError(
            "aurora.ml.diffusion_scenarios requires torch. "
            "Install with: pip install torch"
        )


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class DiffusionConfig:
    horizon: int = 5
    n_assets: int = 1
    hidden_dim: int = 64
    n_steps: int = 20  # number of diffusion timesteps
    beta_start: float = 1e-4
    beta_end: float = 2e-2
    learning_rate: float = 1e-3
    epochs: int = 50
    batch_size: int = 32
    seed: int = 42


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_beta_schedule(cfg: DiffusionConfig) -> np.ndarray:
    return np.linspace(cfg.beta_start, cfg.beta_end, cfg.n_steps).astype(np.float32)


def _build_denoiser(cfg: DiffusionConfig):
    _require_torch()

    class _Denoiser(nn.Module):
        def __init__(self, c: DiffusionConfig):
            super().__init__()
            self.D = c.horizon * c.n_assets
            self.fc1 = nn.Linear(self.D + 1, c.hidden_dim)  # +1 for time embedding
            self.fc2 = nn.Linear(c.hidden_dim, c.hidden_dim)
            self.fc3 = nn.Linear(c.hidden_dim, self.D)

        def forward(self, x: "torch.Tensor", t_norm: "torch.Tensor") -> "torch.Tensor":
            # x: (B, D), t_norm: (B, 1) in [0, 1]
            h = torch.cat([x, t_norm], dim=-1)
            h = torch.relu(self.fc1(h))
            h = torch.relu(self.fc2(h))
            return self.fc3(h)

    return _Denoiser(cfg)


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


class DiffusionScenarioGenerator:
    """Tiny DDPM over windowed return panels.

    Workflow::

        gen = DiffusionScenarioGenerator(DiffusionConfig(horizon=5, n_assets=2))
        gen.fit(historical_returns)             # shape (T, n_assets)
        sims = gen.sample(n_paths=200)          # shape (200, horizon, n_assets)
    """

    def __init__(self, config: Optional[DiffusionConfig] = None):
        _require_torch()
        self.config = config if config is not None else DiffusionConfig()
        if self.config.horizon < 1:
            raise ValueError("horizon must be >= 1")
        if self.config.n_assets < 1:
            raise ValueError("n_assets must be >= 1")
        torch.manual_seed(self.config.seed)
        self._denoiser = _build_denoiser(self.config)
        self._betas_np = _make_beta_schedule(self.config)
        self._alphas_np = 1.0 - self._betas_np
        self._alphas_cumprod_np = np.cumprod(self._alphas_np)
        self._fitted = False
        # Keep training-data scale so we can recover absolute returns.
        self._mean: Optional[np.ndarray] = None
        self._std: Optional[np.ndarray] = None

    # ------------------------------------------------------------------ helpers

    def _make_windows(self, returns: np.ndarray) -> np.ndarray:
        """Slide a (horizon, n_assets) window along ``returns``."""
        if returns.ndim == 1:
            returns = returns.reshape(-1, 1)
        T, n = returns.shape
        h = self.config.horizon
        if T < h + 1:
            raise ValueError(
                f"need at least {h + 1} bars; got {T}"
            )
        if n != self.config.n_assets:
            raise ValueError(
                f"n_assets mismatch: config says {self.config.n_assets}, data has {n}"
            )
        n_windows = T - h + 1
        windows = np.zeros((n_windows, h, n), dtype=np.float32)
        for i in range(n_windows):
            windows[i] = returns[i : i + h]
        return windows

    # ------------------------------------------------------------------ fit

    def fit(self, returns: np.ndarray) -> dict:
        """Train the denoiser by predicting injected noise."""
        if not isinstance(returns, np.ndarray):
            raise TypeError("returns must be a numpy array")
        windows = self._make_windows(returns)            # (N, H, A)
        N, H, A = windows.shape
        self._mean = windows.reshape(-1, A).mean(axis=0)
        self._std = windows.reshape(-1, A).std(axis=0)
        # avoid divide-by-zero for constant assets
        std_safe = np.where(self._std < 1e-9, 1.0, self._std)
        normed = (windows - self._mean) / std_safe       # (N, H, A)
        flat = normed.reshape(N, -1)                     # (N, D)
        D = flat.shape[1]

        opt = torch.optim.Adam(self._denoiser.parameters(), lr=self.config.learning_rate)
        loss_fn = nn.MSELoss()
        history: dict[str, list[float]] = {"loss": []}
        x_all = torch.from_numpy(flat.astype(np.float32))
        alphas_cum = torch.from_numpy(self._alphas_cumprod_np)

        self._denoiser.train()
        for _ in range(self.config.epochs):
            perm = torch.randperm(N)
            epoch_loss = 0.0
            n_batches = 0
            for start in range(0, N, self.config.batch_size):
                idx = perm[start : start + self.config.batch_size]
                x0 = x_all[idx]
                B = x0.shape[0]
                t = torch.randint(0, self.config.n_steps, (B,))
                a_bar = alphas_cum[t].unsqueeze(-1)         # (B, 1)
                noise = torch.randn_like(x0)
                x_t = torch.sqrt(a_bar) * x0 + torch.sqrt(1.0 - a_bar) * noise
                t_norm = (t.float() / max(self.config.n_steps - 1, 1)).unsqueeze(-1)
                pred = self._denoiser(x_t, t_norm)
                loss = loss_fn(pred, noise)
                opt.zero_grad()
                loss.backward()
                opt.step()
                epoch_loss += float(loss.item())
                n_batches += 1
            history["loss"].append(epoch_loss / max(n_batches, 1))
        self._fitted = True
        return history

    # ------------------------------------------------------------------ sample

    def sample(self, n_paths: int = 100) -> np.ndarray:
        """Run reverse-diffusion to draw ``n_paths`` synthetic return windows."""
        if not self._fitted:
            raise RuntimeError("call fit() first")
        if n_paths < 1:
            raise ValueError("n_paths must be >= 1")
        cfg = self.config
        H, A = cfg.horizon, cfg.n_assets
        D = H * A
        betas = torch.from_numpy(self._betas_np)
        alphas = torch.from_numpy(self._alphas_np)
        alphas_cum = torch.from_numpy(self._alphas_cumprod_np)

        x = torch.randn(n_paths, D)
        self._denoiser.eval()
        with torch.no_grad():
            for t_idx in range(cfg.n_steps - 1, -1, -1):
                t_norm = torch.full((n_paths, 1), t_idx / max(cfg.n_steps - 1, 1))
                noise_pred = self._denoiser(x, t_norm)
                a_bar_t = alphas_cum[t_idx]
                a_t = alphas[t_idx]
                mean_factor = 1.0 / torch.sqrt(a_t)
                noise_factor = (1.0 - a_t) / torch.sqrt(1.0 - a_bar_t + 1e-8)
                x = mean_factor * (x - noise_factor * noise_pred)
                if t_idx > 0:
                    z = torch.randn_like(x)
                    sigma = torch.sqrt(betas[t_idx])
                    x = x + sigma * z
        normed = x.cpu().numpy().reshape(n_paths, H, A)
        out = normed * self._std + self._mean
        return out

    # ------------------------------------------------------------------ scenarios

    def sample_crisis(self, n_paths: int = 50, vol_multiplier: float = 3.0) -> np.ndarray:
        """Crisis scenarios: amplify std to simulate stressed regimes."""
        if vol_multiplier <= 0:
            raise ValueError("vol_multiplier must be > 0")
        baseline = self.sample(n_paths=n_paths)
        # Re-center on the empirical mean and inflate dispersion.
        if self._mean is None or self._std is None:
            return baseline
        return (baseline - self._mean) * vol_multiplier + self._mean


__all__ = [
    "TORCH_AVAILABLE",
    "DiffusionConfig",
    "DiffusionScenarioGenerator",
]
