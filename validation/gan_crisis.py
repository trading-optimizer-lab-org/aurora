"""GAN-based novel crisis scenario generator.

Trains a small conditional GAN on historical crash windows; samples generate
novel synthetic crisis return paths whose statistical signature (vol, skew,
kurtosis, drawdown) is consistent with training crashes but the exact sequence
is novel.

Lazy torch import; if torch is unavailable, run() raises ImportError.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional
import numpy as np
import pandas as pd

try:
    import torch
    import torch.nn as _nn
    TORCH_AVAILABLE = True
except ImportError:  # pragma: no cover
    torch = None
    _nn = None
    TORCH_AVAILABLE = False


def _require_torch() -> None:
    if not TORCH_AVAILABLE:
        raise ImportError(
            "quantforge.validation.gan_crisis requires torch. "
            "Install with: pip install torch"
        )


@dataclass
class CrisisGANGenerator:
    seq_len: int = 30
    latent_dim: int = 8
    hidden_dim: int = 32
    n_epochs: int = 50
    batch_size: int = 16
    learning_rate: float = 1e-3
    n_samples: int = 100
    device: str = "cpu"
    seed: int = 42
    samples: Optional[np.ndarray] = None  # shape (n_samples, seq_len)
    train_loss_g: List[float] = field(default_factory=list)
    train_loss_d: List[float] = field(default_factory=list)
    n_train_windows: int = 0

    def _build_generator(self):
        return _nn.Sequential(
            _nn.Linear(self.latent_dim, self.hidden_dim),
            _nn.LeakyReLU(0.2),
            _nn.Linear(self.hidden_dim, self.hidden_dim),
            _nn.LeakyReLU(0.2),
            _nn.Linear(self.hidden_dim, self.seq_len),
            _nn.Tanh(),
        )

    def _build_discriminator(self):
        return _nn.Sequential(
            _nn.Linear(self.seq_len, self.hidden_dim),
            _nn.LeakyReLU(0.2),
            _nn.Linear(self.hidden_dim, self.hidden_dim),
            _nn.LeakyReLU(0.2),
            _nn.Linear(self.hidden_dim, 1),
            _nn.Sigmoid(),
        )

    def run(self, crisis_windows: np.ndarray) -> "CrisisGANGenerator":
        """Train on crisis windows shape (n_windows, seq_len), sample novel scenarios.

        crisis_windows: 2-D float array. Each row is one historical crash
            return window of length seq_len.
        """
        _require_torch()
        if not isinstance(crisis_windows, np.ndarray):
            raise TypeError("crisis_windows must be np.ndarray")
        if crisis_windows.ndim != 2:
            raise ValueError("crisis_windows must be 2-D")
        if crisis_windows.shape[1] != self.seq_len:
            raise ValueError(
                f"crisis_windows.shape[1] ({crisis_windows.shape[1]}) "
                f"!= seq_len ({self.seq_len})"
            )
        if crisis_windows.shape[0] < 1:
            raise ValueError("need >=1 training window")

        torch.manual_seed(self.seed)
        np.random.seed(self.seed)

        # Scale windows to [-1, 1] using Tanh-friendly bounds
        max_abs = float(np.max(np.abs(crisis_windows))) + 1e-9
        x = crisis_windows / max_abs

        device = torch.device(self.device)
        gen = self._build_generator().to(device)
        disc = self._build_discriminator().to(device)
        opt_g = torch.optim.Adam(gen.parameters(), lr=self.learning_rate)
        opt_d = torch.optim.Adam(disc.parameters(), lr=self.learning_rate)
        bce = _nn.BCELoss()

        x_tensor = torch.tensor(x, dtype=torch.float32, device=device)
        n = x_tensor.shape[0]
        bs = min(self.batch_size, n)
        self.n_train_windows = n

        for epoch in range(self.n_epochs):
            perm = torch.randperm(n, device=device)
            for i in range(0, n, bs):
                idx = perm[i:i + bs]
                real = x_tensor[idx]
                cur_bs = real.shape[0]

                # Train discriminator
                opt_d.zero_grad()
                z = torch.randn(cur_bs, self.latent_dim, device=device)
                fake = gen(z).detach()
                d_real = disc(real)
                d_fake = disc(fake)
                loss_d = bce(d_real, torch.ones_like(d_real)) + \
                         bce(d_fake, torch.zeros_like(d_fake))
                loss_d.backward()
                opt_d.step()

                # Train generator
                opt_g.zero_grad()
                z = torch.randn(cur_bs, self.latent_dim, device=device)
                fake = gen(z)
                d_fake = disc(fake)
                loss_g = bce(d_fake, torch.ones_like(d_fake))
                loss_g.backward()
                opt_g.step()

            self.train_loss_d.append(float(loss_d.item()))
            self.train_loss_g.append(float(loss_g.item()))

        # Sample
        gen.eval()
        with torch.no_grad():
            z = torch.randn(self.n_samples, self.latent_dim, device=device)
            samples = gen(z).cpu().numpy()
        self.samples = samples * max_abs
        return self
