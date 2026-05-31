"""Feature importance methods (AFML Ch.8).

Implements:
- MDI: Mean Decrease Impurity (in-sample, tree ensembles)
- MDA: Mean Decrease Accuracy (out-of-sample permutation)
- SFI: Single Feature Importance (one feature in isolation)
"""
from __future__ import annotations
import hashlib
import warnings
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd

from aurora.core.seed import get_seed

try:
    from sklearn.model_selection import KFold, cross_val_score
    from sklearn.metrics import get_scorer
    from sklearn.base import clone
    _SKLEARN_AVAILABLE = True
except ImportError:
    _SKLEARN_AVAILABLE = False


def _stable_seed(*parts: object) -> int:
    """Cross-process-stable 32-bit seed derived from sha256.

    Python's builtin ``hash()`` is salted per process (PEP 456), so
    ``abs(hash(...)) % 2**32`` yields different values across processes and
    breaks reproducibility across re-runs. We use sha256 for a deterministic
    digest, then take the leading 4 bytes as a uint32.
    """
    payload = "|".join(str(p) for p in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:4], "big")


def _require_sklearn() -> None:
    if not _SKLEARN_AVAILABLE:
        raise ImportError(
            "scikit-learn required for feature_importance. "
            "Install with: pip install scikit-learn"
        )


def mean_decrease_impurity(model, feature_names: list[str]) -> pd.DataFrame:
    """MDI from sklearn-style tree ensemble.

    Returns DataFrame with columns ['mean', 'std'] sorted by mean desc.
    For RandomForestRegressor / RandomForestClassifier with n_estimators trees.
    Computed from each tree's feature_importances_ to get cross-tree std.
    """
    _require_sklearn()
    estimators = getattr(model, "estimators_", None)
    if estimators is None:
        raise ValueError(
            "model must be a fitted ensemble with .estimators_ "
            "(e.g., RandomForestRegressor)"
        )

    n_features = len(feature_names)
    imp = np.zeros((len(estimators), n_features))
    for i, tree in enumerate(estimators):
        fi = getattr(tree, "feature_importances_", None)
        if fi is None:
            raise ValueError(f"Estimator {i} missing feature_importances_")
        if len(fi) != n_features:
            raise ValueError(
                f"Estimator {i} has {len(fi)} features, expected {n_features}"
            )
        imp[i, :] = fi

    # Replace zero-importances with NaN for AFML convention (avoid bias from
    # trees that never split on a feature). Then rescale by NaN-mean sum.
    imp_nan = np.where(imp == 0.0, np.nan, imp)
    # All-NaN columns (features never split on) are expected here; suppress the
    # noisy RuntimeWarning and convert NaN aggregates to 0 below.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=RuntimeWarning)
        mean = np.nanmean(imp_nan, axis=0)
        std = np.nanstd(imp_nan, axis=0, ddof=1) if len(estimators) > 1 else np.zeros(n_features)
    # Replace any NaN means (feature never used) with 0
    mean = np.where(np.isnan(mean), 0.0, mean)
    std = np.where(np.isnan(std), 0.0, std)

    df = pd.DataFrame({"mean": mean, "std": std}, index=feature_names)
    df = df.sort_values("mean", ascending=False)
    return df


def _resolve_cv(
    cv_class: Optional[Any],
    cv: int,
    rng_seed: int,
) -> Any:
    """Build the splitter actually used by feature-importance routines.

    Default: a non-shuffled sklearn ``KFold`` so temporal order is preserved
    (NOT a shuffled IID K-Fold, which leaks future information into the
    training set on time-series data). Callers with a proper datetime index
    plus a ``t1`` mapping should pass an instance of
    ``aurora.validation.purged_cv.PurgedKFold`` for purging+embargo.

    Notes:
    - ``cv_class`` may be a splitter instance, a splitter class, or a
      zero-argument callable returning a splitter instance.
    - If a class is passed and its ``__init__`` accepts ``shuffle`` /
      ``random_state``, the seed propagates through.
    """
    if cv_class is None:
        return KFold(n_splits=cv, shuffle=False)
    # Caller-provided
    if isinstance(cv_class, type):
        # Class-style. Try common shuffled-KFold signature first.
        try:
            return cv_class(
                n_splits=cv, shuffle=True, random_state=int(rng_seed % (2**31))
            )
        except TypeError:
            try:
                return cv_class(n_splits=cv)
            except TypeError:
                # Refuse to silently drop the user's ``cv`` value: when the
                # supplied class accepts neither ``n_splits`` nor the
                # shuffled-KFold signature, the requested fold count cannot
                # propagate and the caller would get a CV with a different
                # number of splits than they asked for.
                raise TypeError(
                    "cv_class does not accept 'n_splits' (nor the standard "
                    "shuffled-KFold signature); the user-provided cv="
                    f"{cv} cannot be honored. Pass an instance pre-configured "
                    "with the desired number of splits, or use a class that "
                    "accepts 'n_splits'."
                ) from None
    if callable(cv_class) and not hasattr(cv_class, "split"):
        # A zero-argument factory: same problem as the class-no-n_splits case.
        # The factory cannot accept ``cv`` so honor that contract by raising.
        raise TypeError(
            "cv_class is a zero-argument factory and cannot honor the "
            f"user-provided cv={cv}. Pass an instance pre-configured with "
            "the desired number of splits, or use a class that accepts "
            "'n_splits'."
        )
    return cv_class  # already an instance


def mean_decrease_accuracy(
    model,
    X: pd.DataFrame,
    y: pd.Series,
    cv: int = 5,
    n_repeats: int = 5,
    scoring: str = "neg_mean_squared_error",
    seed_name: str = "mda",
    cv_class: Optional[Any] = None,
) -> pd.DataFrame:
    """MDA via permutation. Out-of-fold permutation per feature.

    For each feature: shuffle column, measure score drop relative to baseline.
    Repeat n_repeats times for stability.

    Args:
        model:        sklearn-compatible estimator (cloned per fold).
        X, y:         features / target frames.
        cv:           number of folds.
        n_repeats:    permutation repeats per fold.
        scoring:      sklearn scorer name.
        seed_name:    seed namespace for reproducibility.
        cv_class:     splitter class or instance to use. Default is a
                      non-shuffled ``KFold`` (time-ordered, no IID shuffle).
                      For time-series with overlapping label horizons, pass
                      ``aurora.validation.purged_cv.PurgedKFold(...)``
                      for full purging + embargo (AFML Ch.7).

    Returns DataFrame ['mean', 'std'] of importance score = baseline - permuted.
    """
    _require_sklearn()

    seed = get_seed()
    if seed is None:
        seed = 0
    # Derive a reproducible seed for this MDA computation (cross-process safe).
    rng_seed = _stable_seed(seed, seed_name)
    rng = np.random.default_rng(rng_seed)

    feat_names = list(X.columns)
    n_features = len(feat_names)
    kf = _resolve_cv(cv_class, cv, rng_seed)
    scorer = get_scorer(scoring)

    # Per (repeat, feature) score-drop.
    drops = np.zeros((n_repeats * cv, n_features))
    row = 0
    for train_idx, test_idx in kf.split(X):
        X_tr = X.iloc[train_idx]
        y_tr = y.iloc[train_idx]
        X_te = X.iloc[test_idx]
        y_te = y.iloc[test_idx]

        est = clone(model)
        est.fit(X_tr, y_tr)
        baseline = scorer(est, X_te, y_te)

        # Permute one feature column at a time on a single shared frame, then
        # restore it. This avoids the per-(repeat, feature) ``X_te.copy()``
        # which on large test folds accounted for most of the wall time.
        # We back the working frame with a writable numpy buffer to allow
        # in-place column overwrite/restore.
        X_te_arr = np.array(X_te.to_numpy(), copy=True)
        X_te_work = pd.DataFrame(
            X_te_arr, index=X_te.index, columns=X_te.columns, copy=False
        )
        n_te = X_te_arr.shape[0]
        for r in range(n_repeats):
            for j, col in enumerate(feat_names):
                perm = rng.permutation(n_te)
                saved = X_te_arr[:, j].copy()
                X_te_arr[:, j] = saved[perm]
                try:
                    permuted = scorer(est, X_te_work, y_te)
                    drops[row + r, j] = baseline - permuted
                finally:
                    X_te_arr[:, j] = saved
        row += n_repeats

    mean = drops.mean(axis=0)
    std = drops.std(axis=0, ddof=1) if drops.shape[0] > 1 else np.zeros(n_features)

    df = pd.DataFrame({"mean": mean, "std": std}, index=feat_names)
    df = df.sort_values("mean", ascending=False)
    return df


def single_feature_importance(
    X: pd.DataFrame,
    y: pd.Series,
    estimator_factory: Callable,
    cv: int = 5,
    scoring: str = "neg_mean_squared_error",
    seed_name: str = "sfi",
    cv_class: Optional[Any] = None,
) -> pd.DataFrame:
    """SFI: train one estimator per feature in isolation, measure CV score.

    Args:
        estimator_factory: callable() -> sklearn-compatible estimator
        cv: K-fold splits.
        cv_class: splitter class or instance. Default is a non-shuffled
            ``KFold`` (time-ordered). For time-series with overlapping label
            horizons, pass ``PurgedKFold(...)`` from
            ``aurora.validation.purged_cv`` for full purging + embargo
            (AFML Ch.7).

    Returns DataFrame ['mean', 'std'] of OOS score per feature.
    """
    _require_sklearn()

    seed = get_seed()
    if seed is None:
        seed = 0
    rng_seed = _stable_seed(seed, seed_name)

    feat_names = list(X.columns)
    means = np.zeros(len(feat_names))
    stds = np.zeros(len(feat_names))

    kf = _resolve_cv(cv_class, cv, rng_seed)
    for j, col in enumerate(feat_names):
        X_j = X[[col]]
        est = estimator_factory()
        # cross_val_score expects the splitter to expose split(); both
        # sklearn KFold and aurora.validation.PurgedKFold do.
        scores = cross_val_score(est, X_j, y, cv=kf, scoring=scoring)
        means[j] = scores.mean()
        stds[j] = scores.std(ddof=1) if len(scores) > 1 else 0.0

    df = pd.DataFrame({"mean": means, "std": stds}, index=feat_names)
    df = df.sort_values("mean", ascending=False)
    return df


def plot_importance(
    importance_df: pd.DataFrame,
    title: str = "Feature Importance",
    output_path: str | None = None,
) -> str | None:
    """Bar chart with error bars. Saves PNG if output_path; returns path or None."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise ImportError(
            "matplotlib required for plot_importance. "
            "Install with: pip install matplotlib"
        ) from exc

    df = importance_df.sort_values("mean", ascending=True)
    fig, ax = plt.subplots(figsize=(8, max(3, 0.35 * len(df) + 1)))
    ax.barh(
        df.index.astype(str),
        df["mean"].to_numpy(),
        xerr=df["std"].to_numpy(),
        color="steelblue",
        ecolor="black",
        capsize=3,
    )
    ax.set_title(title)
    ax.set_xlabel("Importance")
    ax.axvline(0, color="black", linewidth=0.5)
    fig.tight_layout()

    if output_path is not None:
        fig.savefig(output_path, dpi=120)
        plt.close(fig)
        return output_path
    plt.close(fig)
    return None
