"""Tests for FederatedTrainer (FedAvg, ridge backend)."""
from __future__ import annotations

import numpy as np
import pytest

from quantforge.experimental.federated_learning import (
    ClientData,
    FederatedTrainer,
    TORCH_AVAILABLE,
)


def _make_client(rng: np.random.Generator, n: int, true_w: np.ndarray) -> ClientData:
    X = rng.normal(0.0, 1.0, (n, true_w.size))
    y = X @ true_w + rng.normal(0.0, 0.05, n)
    return ClientData(X=X, y=y)


def test_fedavg_recovers_true_weights():
    rng = np.random.default_rng(0)
    true_w = np.array([1.0, -2.0, 0.5])
    clients = [_make_client(rng, 200, true_w) for _ in range(4)]
    trainer = FederatedTrainer(n_features=3, rounds=10, ridge_lambda=1e-4)
    w = trainer.fit(clients)
    np.testing.assert_allclose(w, true_w, atol=0.1)


def test_fedavg_predict_shape():
    rng = np.random.default_rng(1)
    true_w = np.array([0.5, -0.5])
    clients = [_make_client(rng, 50, true_w) for _ in range(2)]
    trainer = FederatedTrainer(n_features=2, rounds=2)
    trainer.fit(clients)
    X = rng.normal(0.0, 1.0, (10, 2))
    y_hat = trainer.predict(X)
    assert y_hat.shape == (10,)


def test_fedavg_rejects_mismatched_features():
    trainer = FederatedTrainer(n_features=3, rounds=1)
    bad = ClientData(X=np.zeros((5, 4)), y=np.zeros(5))
    with pytest.raises(ValueError):
        trainer.fit([bad])


def test_fedavg_rejects_empty_client_list():
    trainer = FederatedTrainer(n_features=2, rounds=1)
    with pytest.raises(ValueError):
        trainer.fit([])


def test_torch_backend_requires_torch_install():
    if TORCH_AVAILABLE:
        # If torch is available we can construct without error.
        FederatedTrainer(n_features=2, backend="torch")
    else:
        with pytest.raises(ImportError):
            FederatedTrainer(n_features=2, backend="torch")
