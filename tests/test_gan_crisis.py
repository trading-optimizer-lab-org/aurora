"""Tests for CrisisGANGenerator (lazy torch)."""
from __future__ import annotations
import numpy as np
import pytest

from quantforge.core.seed import set_global_seed
from quantforge.validation.gan_crisis import CrisisGANGenerator, TORCH_AVAILABLE

pytestmark = pytest.mark.skipif(not TORCH_AVAILABLE, reason="torch not installed")


@pytest.fixture
def crash_windows():
    set_global_seed(42)
    rng = np.random.default_rng(0)
    n_windows = 12
    seq_len = 10
    # Synthetic crash windows: deeply negative drift + high vol
    return rng.normal(-0.02, 0.03, (n_windows, seq_len))


def test_basic_train_and_sample(crash_windows):
    gan = CrisisGANGenerator(seq_len=10, n_epochs=2, n_samples=5, batch_size=4,
                             latent_dim=4, hidden_dim=8)
    out = gan.run(crash_windows)
    assert out is gan
    assert gan.samples is not None
    assert gan.samples.shape == (5, 10)
    assert len(gan.train_loss_g) == 2
    assert len(gan.train_loss_d) == 2


def test_n_train_windows_set(crash_windows):
    gan = CrisisGANGenerator(seq_len=10, n_epochs=1, n_samples=3, batch_size=4,
                             latent_dim=4, hidden_dim=8)
    gan.run(crash_windows)
    assert gan.n_train_windows == crash_windows.shape[0]


def test_invalid_inputs():
    with pytest.raises(TypeError):
        CrisisGANGenerator(seq_len=5).run([[1, 2, 3, 4, 5]])
    with pytest.raises(ValueError):
        CrisisGANGenerator(seq_len=10).run(np.zeros((3, 5)))
    with pytest.raises(ValueError):
        CrisisGANGenerator(seq_len=5).run(np.zeros(5))
