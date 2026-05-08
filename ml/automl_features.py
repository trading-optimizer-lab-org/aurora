"""AutoML candidate-feature engineer (QuantForge v2.0 Batch C).

Generates a large pool of candidate features from a price/feature panel and
ranks them by mutual information against a target. SHAP scoring is supported
when ``shap`` is installed (lazy/optional). Returns the top-K features.

Public API:
- ``AutoMLFeatureEngineer``: ``generate(prices) -> DataFrame``,
  ``rank(features, target, method) -> Series``, ``select(prices, target,
  k=20) -> DataFrame``.

Design constraints:
- Anti-lookahead: every rolling stat / lag uses a strict trailing window;
  interactions are pointwise on bar t. No future leakage.
- Lazy sklearn: import only inside ``rank`` so the module is importable
  without scikit-learn installed.
- Lazy shap: only required when ``method='shap'``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd

try:  # optional dep, only used when method='shap' or 'mi'
    import sklearn  # type: ignore
    SKLEARN_AVAILABLE = True
except ImportError:  # pragma: no cover - environment-dependent
    sklearn = None  # type: ignore[assignment]
    SKLEARN_AVAILABLE = False

try:  # optional dep, only used when method='shap'
    import shap  # type: ignore
    SHAP_AVAILABLE = True
except ImportError:  # pragma: no cover - environment-dependent
    shap = None  # type: ignore[assignment]
    SHAP_AVAILABLE = False


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class AutoMLConfig:
    """Knobs for the candidate-feature generator.

    rolling_windows:
        Window sizes for trailing rolling statistics (mean, std, skew, kurt,
        z-score, min-max range).
    lag_steps:
        Lag offsets to apply to the close series.
    pairwise_interactions:
        If True, multiply the top ``interaction_top_k`` univariate features
        pairwise (i*j for i<j).
    interaction_top_k:
        How many univariate features to use for pairwise interactions.
    """

    rolling_windows: Sequence[int] = field(default_factory=lambda: (5, 10, 21, 63))
    lag_steps: Sequence[int] = field(default_factory=lambda: (1, 2, 5, 10))
    pairwise_interactions: bool = True
    interaction_top_k: int = 8


# ---------------------------------------------------------------------------
# Feature engineer
# ---------------------------------------------------------------------------


class AutoMLFeatureEngineer:
    """Generate + rank a large pool of candidate features.

    Workflow:

        eng = AutoMLFeatureEngineer()
        candidates = eng.generate(prices)
        scores = eng.rank(candidates, target, method="mi")
        top_k = eng.select(prices, target, k=20)
    """

    def __init__(self, config: Optional[AutoMLConfig] = None):
        self.config = config if config is not None else AutoMLConfig()

    # ------------------------------------------------------------------ generate

    def generate(self, prices: pd.Series) -> pd.DataFrame:
        """Build candidate features from a single close-price series.

        Returns a DataFrame indexed like ``prices``. Generates roughly
        4 (rolling stats) * |windows| + |lags| + interactions, easily 100+
        features with the default config.
        """
        if not isinstance(prices, pd.Series):
            raise TypeError("prices must be a pandas Series")
        if len(prices) < 5:
            raise ValueError("prices too short to generate features")

        cfg = self.config
        out: dict[str, pd.Series] = {}

        log_ret = np.log(prices).diff()
        out["log_ret"] = log_ret

        for w in cfg.rolling_windows:
            r = log_ret.rolling(w, min_periods=w)
            out[f"mean_{w}"] = r.mean()
            out[f"std_{w}"] = r.std()
            out[f"skew_{w}"] = r.skew()
            out[f"kurt_{w}"] = r.kurt()
            out[f"zscore_{w}"] = (log_ret - r.mean()) / r.std().replace(0.0, np.nan)
            rng = prices.rolling(w, min_periods=w)
            mn, mx = rng.min(), rng.max()
            out[f"range_{w}"] = (mx - mn) / mn.replace(0.0, np.nan)
            out[f"price_pct_rank_{w}"] = prices.rolling(w, min_periods=w).apply(
                lambda x: (np.argsort(np.argsort(x))[-1] + 1) / len(x), raw=True
            )

        for k in cfg.lag_steps:
            out[f"lag_{k}"] = log_ret.shift(k)
            out[f"lag_price_{k}"] = prices.shift(k) / prices - 1.0

        # Composite tech features
        for w in cfg.rolling_windows:
            ema = prices.ewm(span=w, adjust=False).mean()
            out[f"ema_dev_{w}"] = (prices - ema) / ema

        df = pd.DataFrame(out, index=prices.index)

        if cfg.pairwise_interactions:
            # Use a deterministic seed of "interesting" candidates: the lowest
            # variance ones tend to be useless, so we just pick the first
            # interaction_top_k by name to remain reproducible.
            base_cols = [c for c in df.columns if c != "log_ret"][: cfg.interaction_top_k]
            inter: dict[str, pd.Series] = {}
            for i in range(len(base_cols)):
                for j in range(i + 1, len(base_cols)):
                    a, b = base_cols[i], base_cols[j]
                    inter[f"{a}__x__{b}"] = df[a] * df[b]
            if inter:
                df = pd.concat([df, pd.DataFrame(inter, index=prices.index)], axis=1)

        return df

    # ------------------------------------------------------------------ rank

    def rank(
        self,
        features: pd.DataFrame,
        target: pd.Series,
        method: str = "mi",
        random_state: int = 42,
    ) -> pd.Series:
        """Rank features against ``target``. Higher is more informative."""
        if not isinstance(features, pd.DataFrame):
            raise TypeError("features must be a DataFrame")
        if not isinstance(target, pd.Series):
            raise TypeError("target must be a Series")

        joined = features.join(target.rename("__target__"), how="inner").dropna()
        if joined.empty:
            return pd.Series(dtype=float)
        X = joined.drop(columns=["__target__"])
        y = joined["__target__"]

        method = method.lower()
        if method == "mi":
            if not SKLEARN_AVAILABLE:
                raise ImportError(
                    "method='mi' requires scikit-learn. "
                    "Install with: pip install scikit-learn"
                )
            from sklearn.feature_selection import mutual_info_regression

            # mutual_info_regression handles continuous targets.
            scores = mutual_info_regression(
                X.to_numpy(), y.to_numpy(), random_state=random_state
            )
            return pd.Series(scores, index=X.columns).sort_values(ascending=False)

        if method == "shap":
            if not SKLEARN_AVAILABLE:
                raise ImportError("method='shap' needs scikit-learn for the model")
            if not SHAP_AVAILABLE:
                raise ImportError(
                    "method='shap' requires shap. Install with: pip install shap"
                )
            from sklearn.ensemble import RandomForestRegressor

            model = RandomForestRegressor(
                n_estimators=50, max_depth=4, random_state=random_state, n_jobs=1
            )
            model.fit(X, y)
            explainer = shap.TreeExplainer(model)
            sv = explainer.shap_values(X)
            mean_abs = np.abs(sv).mean(axis=0)
            return pd.Series(mean_abs, index=X.columns).sort_values(ascending=False)

        if method == "corr":
            # Pure-numpy fallback that does not require sklearn.
            corrs = X.apply(lambda c: np.abs(c.corr(y)))
            return corrs.sort_values(ascending=False)

        raise ValueError(f"Unknown ranking method: {method!r}")

    # ------------------------------------------------------------------ select

    def select(
        self,
        prices: pd.Series,
        target: pd.Series,
        k: int = 20,
        method: str = "mi",
    ) -> pd.DataFrame:
        """End-to-end: ``generate`` then ``rank`` then keep top-K columns."""
        if k < 1:
            raise ValueError("k must be >= 1")
        candidates = self.generate(prices)
        try:
            scores = self.rank(candidates, target, method=method)
        except ImportError:
            scores = self.rank(candidates, target, method="corr")
        keep = list(scores.head(k).index)
        return candidates[keep]


__all__ = [
    "AutoMLConfig",
    "AutoMLFeatureEngineer",
    "SKLEARN_AVAILABLE",
    "SHAP_AVAILABLE",
]
