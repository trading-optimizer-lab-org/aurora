"""Online learning strategy.

Sequential predict-then-update loop using sklearn online learners (SGDClassifier,
SGDRegressor). Anti-lookahead by construction: at bar i we update
the model only on (features[i-1], label_i), where label_i = sign(price[i]/price[i-1] - 1).
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from aurora.strategies.base import Strategy, StrategySpec

try:
    from sklearn.linear_model import SGDClassifier, SGDRegressor
    _SKLEARN_OK = True
except ImportError:
    SGDClassifier = None
    SGDRegressor = None
    _SKLEARN_OK = False


def default_features(prices: pd.Series, i: int, lookback: int = 20) -> np.ndarray:
    """Default feature set: returns at multiple lags + rolling stats.

    Returns 1-D array length 7:
    [ret_1, ret_5, ret_20, mean_20, std_20, max_20, min_20]

    Uses prices[:i+1] only. No lookahead.
    """
    p = prices.values.astype(float) if isinstance(prices, pd.Series) else np.asarray(prices, dtype=float)
    n = len(p)
    if i < lookback:
        return np.zeros(7, dtype=float)
    window = p[i - lookback + 1:i + 1]
    rets = np.diff(window) / window[:-1]
    ret_1 = (p[i] / p[i - 1] - 1.0) if i >= 1 and p[i - 1] != 0 else 0.0
    ret_5 = (p[i] / p[i - 5] - 1.0) if i >= 5 and p[i - 5] != 0 else 0.0
    ret_20 = (p[i] / p[i - 20] - 1.0) if i >= 20 and p[i - 20] != 0 else 0.0
    mean_20 = float(np.mean(rets)) if len(rets) > 0 else 0.0
    std_20 = float(np.std(rets)) if len(rets) > 0 else 0.0
    max_20 = float(np.max(rets)) if len(rets) > 0 else 0.0
    min_20 = float(np.min(rets)) if len(rets) > 0 else 0.0
    out = np.array([ret_1, ret_5, ret_20, mean_20, std_20, max_20, min_20], dtype=float)
    if not np.all(np.isfinite(out)):
        out = np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)
    return out


def default_classifier_factory():
    """Default online classifier: sklearn SGDClassifier with logistic loss."""
    if not _SKLEARN_OK:
        raise ImportError("sklearn required for OnlineLearner. pip install scikit-learn")
    return SGDClassifier(loss="log_loss", learning_rate="constant", eta0=0.01,
                         random_state=42, warm_start=True)


def default_regressor_factory():
    """Default online regressor using sklearn's current PA-style SGD mode."""
    if not _SKLEARN_OK:
        raise ImportError("sklearn required for OnlineLearner. pip install scikit-learn")
    return SGDRegressor(
        loss="epsilon_insensitive",
        penalty=None,
        learning_rate="pa1",
        eta0=1.0,
        random_state=42,
        warm_start=True,
    )


class OnlineLearner(Strategy):
    """Online learning strategy.

    At each bar:
    1. Predict with current model (if fitted)
    2. Translate prediction to position
    3. After realized return at next bar, partial_fit on (features[i-1], label_i)

    No retraining from scratch -- uses incremental SGD-style updates.
    Anti-lookahead: features at i use prices[:i+1], training uses label[i] but only AFTER
    that label is realized (i.e. at bar i we update on bar i-1 features with label_i).

    Args:
        model_factory: callable() -> sklearn online estimator with partial_fit + predict
        feature_fn: callable(prices, i) -> np.array of features for bar i
        warmup: bars to wait before predicting (default 100)
        label_threshold: |return| < threshold -> label 0 (filter noise)
    """

    def __init__(self, model_factory=None, feature_fn=None,
                 warmup: int = 100, label_threshold: float = 0.0,
                 model_kind: str | None = None):
        """Init the online learner.

        Args:
            model_kind: optional explicit override of model type detection.
                One of ``"classifier"`` or ``"regressor"``. When provided,
                the auto-detection in :meth:`signals` is bypassed. Useful
                when wrapping a sklearn ``Pipeline`` whose final estimator
                is hidden behind preprocessing steps and the heuristic-based
                detection cannot peek inside.
        """
        self.model_factory = model_factory if model_factory is not None else default_classifier_factory
        self.feature_fn = feature_fn if feature_fn is not None else default_features
        self.warmup = int(warmup)
        self.label_threshold = float(label_threshold)
        if model_kind is not None and model_kind not in ("classifier", "regressor"):
            raise ValueError(
                f"model_kind must be 'classifier', 'regressor', or None; "
                f"got {model_kind!r}"
            )
        self.model_kind = model_kind

    @classmethod
    def spec(cls) -> StrategySpec:
        # warmup, label_threshold are tunable; model_factory not in GA spec
        return StrategySpec(
            name="OnlineLearner",
            params={"warmup": 100, "label_threshold": 0.0},
            param_ranges={
                "warmup": (50, 500),
                "label_threshold": (0.0, 0.005),
            },
        )

    def _label(self, prices: np.ndarray, i: int) -> int | None:
        """Realized label at bar i: sign(prices[i]/prices[i-1] - 1) above threshold."""
        if i < 1 or prices[i - 1] == 0:
            return None
        r = prices[i] / prices[i - 1] - 1.0
        if abs(r) < self.label_threshold:
            return 0
        return 1 if r > 0 else -1

    def signals(self, prices: pd.Series) -> np.ndarray:
        """Sequential predict-then-update loop."""
        if not _SKLEARN_OK:
            raise ImportError("sklearn required for OnlineLearner. pip install scikit-learn")
        p = prices.values.astype(float) if isinstance(prices, pd.Series) else np.asarray(prices, dtype=float)
        n = len(p)
        out: np.ndarray = np.zeros(n, dtype=float)
        if n <= self.warmup:
            return out

        model = self.model_factory()
        # Pipeline-aware detection: when ``model`` is a sklearn Pipeline the
        # outer class name is "Pipeline" and the type heuristics below would
        # always fall through to the regressor branch. Walk to
        # ``_final_estimator`` so detection sees the real classifier /
        # regressor at the end of the pipeline.
        detect_target = getattr(model, "_final_estimator", model)

        # Detection priority (least brittle first):
        #   0. Explicit override via ``model_kind`` ctor kwarg.
        #   1. Strong type signal: explicit "Regressor" in class name -> regressor.
        #   2. Strong type signal: explicit "Classifier" in class name OR
        #      isinstance(SGDClassifier) OR has classes_ attr -> classifier.
        #   3. Fallback to introspecting partial_fit for a `classes` parameter.
        #      sklearn classifiers accept `classes` on first partial_fit;
        #      sklearn regressors do not. This is the canonical sklearn API
        #      contract but only consulted as a tie-breaker because mocks may
        #      include the kwarg without honoring classifier semantics.
        if self.model_kind is not None:
            is_classifier = self.model_kind == "classifier"
        else:
            cls_name = type(detect_target).__name__
            is_classifier = False
            if "Regressor" in cls_name:
                is_classifier = False
            elif (
                "Classifier" in cls_name
                or hasattr(detect_target, "classes_")
                or (SGDClassifier is not None and isinstance(detect_target, SGDClassifier))
            ):
                is_classifier = True
            else:
                import inspect
                try:
                    sig = inspect.signature(detect_target.partial_fit)
                    if "classes" in sig.parameters:
                        is_classifier = True
                except (TypeError, ValueError, AttributeError):
                    is_classifier = False
        fitted = False
        feat_cache: dict[int, np.ndarray] = {}

        def _get_feat(i: int) -> np.ndarray:
            if i not in feat_cache:
                # feature_fn must use only prices[:i+1]
                feat_cache[i] = self.feature_fn(prices, i)
            return feat_cache[i]

        for i in range(self.warmup, n):
            # 1) Update on previous bar's realized label (anti-lookahead)
            if i > self.warmup:
                lbl = self._label(p, i)
                if lbl is not None:
                    feat_prev = _get_feat(i - 1)
                    X = feat_prev.reshape(1, -1)
                    y = np.array([lbl])
                    if is_classifier:
                        # Classifier: sklearn requires `classes` arg on first partial_fit only.
                        if not fitted:
                            model.partial_fit(X, y, classes=np.array([-1, 0, 1]))
                        else:
                            model.partial_fit(X, y)
                    else:
                        # Regressor: y is signed sign of return; sklearn does NOT take `classes`.
                        y_reg = np.array([float(lbl)])
                        model.partial_fit(X, y_reg)
                    fitted = True

            # 2) Predict for current bar (uses prices[:i+1])
            if fitted:
                feat_i = _get_feat(i)
                X_i = feat_i.reshape(1, -1)
                try:
                    pred = float(model.predict(X_i)[0])
                except Exception:
                    pred = 0.0
                # position: clip to [-1, 1] (sign for classifier, value for regressor)
                if is_classifier:
                    out[i] = float(np.sign(pred))
                else:
                    out[i] = float(np.clip(pred, -1.0, 1.0))

        return np.clip(out, -1.0, 1.0)
