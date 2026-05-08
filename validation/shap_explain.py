"""SHAP feature importance wrapper for ML strategies.

Computes Shapley values for tree-based or kernel-based models so the trader
can audit per-prediction feature importance. Lazy shap import: if shap is
not installed, falls back to a permutation-importance estimator that
returns mean absolute decrease in prediction when a column is shuffled.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, List, Optional
import numpy as np
import pandas as pd

try:
    import shap as _shap  # type: ignore
    SHAP_AVAILABLE = True
except ImportError:  # pragma: no cover
    _shap = None  # type: ignore
    SHAP_AVAILABLE = False


def _permutation_importance(model, X: np.ndarray, n_repeats: int = 5,
                            seed: int = 42) -> np.ndarray:
    """Mean absolute change in prediction when each column is shuffled.

    Returns a 2-D array (n_samples, n_features) of per-row contributions
    approximated as |delta prediction| spread uniformly across the row.
    """
    rng = np.random.default_rng(seed)
    n, d = X.shape
    base_pred = np.asarray(model.predict(X)).reshape(-1)
    contrib = np.zeros((n, d), dtype=float)
    for j in range(d):
        deltas_j = np.zeros(n)
        for _ in range(n_repeats):
            X_perm = X.copy()
            perm_idx = rng.permutation(n)
            X_perm[:, j] = X[perm_idx, j]
            pj = np.asarray(model.predict(X_perm)).reshape(-1)
            deltas_j += np.abs(pj - base_pred)
        contrib[:, j] = deltas_j / float(n_repeats)
    return contrib


@dataclass
class SHAPExplainer:
    explainer_type: str = "auto"  # "auto", "tree", "kernel", "permutation"
    n_background: int = 100
    seed: int = 42
    shap_values: Optional[np.ndarray] = None  # (n_samples, n_features)
    feature_importances: Optional[np.ndarray] = None  # (n_features,) mean |shap|
    feature_names: List[str] = field(default_factory=list)
    n_samples: int = 0
    n_features: int = 0
    used_fallback: bool = False

    def _resolve_explainer(self, model, X_bg: np.ndarray):
        """Pick an explainer when explainer_type == 'auto'."""
        klass = type(model).__name__
        # Tree-based hints (sklearn / xgboost / lightgbm)
        tree_hints = (
            "RandomForest", "GradientBoosting", "ExtraTrees",
            "DecisionTree", "XGB", "LGBM", "CatBoost",
        )
        if any(h in klass for h in tree_hints):
            return _shap.TreeExplainer(model)
        return _shap.KernelExplainer(model.predict, X_bg)

    def run(self, model, X: np.ndarray,
            X_background: Optional[np.ndarray] = None,
            feature_names: Optional[List[str]] = None) -> "SHAPExplainer":
        if not isinstance(X, np.ndarray):
            X = np.asarray(X, dtype=float)
        if X.ndim != 2:
            raise ValueError("X must be 2-D")
        if not hasattr(model, "predict"):
            raise TypeError("model must expose .predict(X)")

        n, d = X.shape
        self.n_samples = int(n)
        self.n_features = int(d)
        if feature_names is None:
            feature_names = [f"f{i}" for i in range(d)]
        if len(feature_names) != d:
            raise ValueError("feature_names length must match X.shape[1]")
        self.feature_names = list(feature_names)

        if X_background is None:
            n_bg = min(self.n_background, n)
            rng = np.random.default_rng(self.seed)
            idx = rng.choice(n, size=n_bg, replace=False)
            X_background = X[idx]

        # Try shap if available, otherwise fall back to permutation importance.
        if SHAP_AVAILABLE and self.explainer_type != "permutation":
            try:
                if self.explainer_type == "auto":
                    explainer = self._resolve_explainer(model, X_background)
                elif self.explainer_type == "tree":
                    explainer = _shap.TreeExplainer(model)
                elif self.explainer_type == "kernel":
                    explainer = _shap.KernelExplainer(model.predict, X_background)
                else:
                    raise ValueError(f"unknown explainer_type {self.explainer_type}")
                vals = explainer.shap_values(X)
                # shap can return list-of-arrays for multiclass; collapse to 2-D
                if isinstance(vals, list):
                    vals = vals[0]
                vals = np.asarray(vals)
                if vals.ndim != 2:
                    vals = vals.reshape(n, d)
                self.shap_values = vals
            except Exception:  # pragma: no cover - shap may fail on odd models
                self.shap_values = _permutation_importance(model, X, seed=self.seed)
                self.used_fallback = True
        else:
            self.shap_values = _permutation_importance(model, X, seed=self.seed)
            self.used_fallback = True

        self.feature_importances = np.mean(np.abs(self.shap_values), axis=0)
        return self
