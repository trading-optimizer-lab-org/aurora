"""Out-of-distribution (OOD) market state detector.

Combines two complementary anomaly scores on a feature matrix:
  * Mahalanobis distance vs the training feature distribution.
  * Isolation Forest score (sklearn).

Returns per-row OOD flags and continuous scores. Useful to gate live trading
when the current market state diverges from the regime the strategy was
trained on.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest


@dataclass
class OODDetector:
    contamination: float = 0.05  # IsolationForest contamination
    mahalanobis_quantile: float = 0.95  # quantile of training Mahalanobis dist
    n_estimators: int = 100
    seed: int = 42
    train_mean: Optional[np.ndarray] = None
    train_cov_inv: Optional[np.ndarray] = None
    mahalanobis_threshold: float = 0.0
    iso_forest: Optional[IsolationForest] = None
    test_mahalanobis: Optional[np.ndarray] = None
    test_iso_score: Optional[np.ndarray] = None
    test_ood_flags: Optional[np.ndarray] = None
    n_features: int = 0
    n_train: int = 0
    n_test: int = 0

    def _fit(self, X_train: np.ndarray) -> None:
        self.train_mean = X_train.mean(axis=0)
        cov = np.cov(X_train, rowvar=False, ddof=1)
        # Regularize for invertibility
        if cov.ndim == 0:
            cov = np.array([[float(cov) + 1e-6]])
        else:
            cov = cov + 1e-6 * np.eye(cov.shape[0])
        self.train_cov_inv = np.linalg.pinv(cov)

        # Threshold from training Mahalanobis distribution
        d_train = self._mahalanobis(X_train)
        self.mahalanobis_threshold = float(np.quantile(d_train, self.mahalanobis_quantile))

        self.iso_forest = IsolationForest(
            n_estimators=self.n_estimators,
            contamination=self.contamination,
            random_state=self.seed,
        )
        self.iso_forest.fit(X_train)

    def _mahalanobis(self, X: np.ndarray) -> np.ndarray:
        diff = X - self.train_mean
        # squared Mahalanobis: (x-mu)^T S^-1 (x-mu)
        left = diff @ self.train_cov_inv
        d2 = np.einsum("ij,ij->i", left, diff)
        d2 = np.maximum(d2, 0.0)
        return np.sqrt(d2)

    def run(self, X_train: np.ndarray, X_test: np.ndarray) -> "OODDetector":
        if not isinstance(X_train, np.ndarray):
            X_train = np.asarray(X_train, dtype=float)
        if not isinstance(X_test, np.ndarray):
            X_test = np.asarray(X_test, dtype=float)
        if X_train.ndim == 1:
            X_train = X_train.reshape(-1, 1)
        if X_test.ndim == 1:
            X_test = X_test.reshape(-1, 1)
        if X_train.shape[1] != X_test.shape[1]:
            raise ValueError("X_train and X_test must have same n_features")
        if len(X_train) < 5:
            raise ValueError("need >=5 training rows")
        if not (0.0 < self.contamination < 0.5):
            raise ValueError("contamination must be in (0, 0.5)")
        if not (0.5 < self.mahalanobis_quantile < 1.0):
            raise ValueError("mahalanobis_quantile must be in (0.5, 1.0)")

        self.n_features = int(X_train.shape[1])
        self.n_train = int(X_train.shape[0])
        self.n_test = int(X_test.shape[0])

        self._fit(X_train)

        m = self._mahalanobis(X_test)
        # IsolationForest: predict returns -1 for anomaly, 1 for inlier;
        # decision_function: higher = more normal.
        # ``_fit`` (called above) populated self.iso_forest.
        assert self.iso_forest is not None
        iso_pred = self.iso_forest.predict(X_test)
        iso_score = self.iso_forest.decision_function(X_test)

        flag_maha = m > self.mahalanobis_threshold
        flag_iso = iso_pred == -1
        # Combine: OOD if EITHER flags it (logical OR).
        flags = flag_maha | flag_iso

        self.test_mahalanobis = m
        self.test_iso_score = iso_score
        self.test_ood_flags = flags
        return self

    def ood_fraction(self) -> float:
        """Fraction of test rows flagged as OOD."""
        if self.test_ood_flags is None:
            return 0.0
        return float(np.mean(self.test_ood_flags))
