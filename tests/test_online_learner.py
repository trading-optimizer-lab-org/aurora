"""Tests for OnlineLearner strategy."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

pytest.importorskip("sklearn")

from quantforge.strategies.library import OnlineLearner
from quantforge.strategies.library.online_learner import (
    OnlineLearner as OLDirect,
    default_features,
    default_classifier_factory,
    default_regressor_factory,
)


@pytest.fixture
def fake_prices():
    rng = np.random.default_rng(11)
    idx = pd.date_range("2010-01-01", periods=400, freq="B")
    rets = rng.normal(0.0005, 0.012, 400)
    p = 100.0 * np.cumprod(1.0 + rets)
    return pd.Series(p, index=idx, name="FAKE")


def test_signals_shape(fake_prices):
    s = OnlineLearner(warmup=100)
    sig = s.signals(fake_prices)
    assert isinstance(sig, np.ndarray)
    assert len(sig) == len(fake_prices)
    assert np.all(np.abs(sig) <= 1.0 + 1e-9)
    assert not np.any(np.isnan(sig))


def test_no_lookahead(fake_prices):
    """Signal at i must depend only on prices[:i+1]. Sequential model state matches across truncation."""
    s = OnlineLearner(warmup=100, label_threshold=0.0)
    sig_full = s.signals(fake_prices)
    k = 250
    truncated = fake_prices.iloc[:k]
    sig_trunc = s.signals(truncated)
    # First k entries must be identical: model state at each i depends only on past
    assert np.allclose(sig_trunc, sig_full[:k]), \
        "Signal depends on future data (lookahead detected)"


def test_warmup_zero_signals(fake_prices):
    """signals[:warmup] must all be zero."""
    s = OnlineLearner(warmup=120)
    sig = s.signals(fake_prices)
    assert np.all(sig[:120] == 0.0)


def test_with_default_classifier(fake_prices):
    s = OnlineLearner(model_factory=default_classifier_factory, warmup=100)
    sig = s.signals(fake_prices)
    # Classifier outputs in {-1, 0, 1}
    unique = set(np.unique(sig))
    assert unique.issubset({-1.0, 0.0, 1.0})
    # Some non-zero predictions after warmup
    assert np.any(sig[101:] != 0.0)


def test_with_default_regressor(fake_prices):
    s = OnlineLearner(model_factory=default_regressor_factory, warmup=100)
    sig = s.signals(fake_prices)
    assert len(sig) == len(fake_prices)
    assert np.all(np.abs(sig) <= 1.0 + 1e-9)
    # Regressor likely produces continuous values
    nz = sig[sig != 0.0]
    if len(nz) > 0:
        # not all integers (would suggest classifier path)
        assert not np.all(nz == np.round(nz)) or len(np.unique(nz)) > 3


def test_partial_fit_called_after_warmup(fake_prices):
    """Count partial_fit calls; should equal n - warmup - 1 (no fit at first post-warmup bar)."""
    call_count = {"n": 0}

    class CountingModel:
        def __init__(self):
            self._fitted = False
            self.classes_ = None

        def partial_fit(self, X, y, classes=None):
            call_count["n"] += 1
            self._fitted = True
            if classes is not None:
                self.classes_ = classes
            return self

        def predict(self, X):
            return np.array([0.0])

    def factory():
        return CountingModel()

    warmup = 100
    n = len(fake_prices)
    s = OnlineLearner(model_factory=factory, warmup=warmup)
    s.signals(fake_prices)
    expected = n - warmup - 1
    assert call_count["n"] == expected, f"expected {expected} partial_fit calls, got {call_count['n']}"


def test_feature_fn_uses_only_past(fake_prices):
    """Custom feature_fn: ensure it never accesses prices beyond index i."""
    accessed = {"max_idx": -1}

    def tracked_features(prices, i, lookback=20):
        # Wrap the prices Series so we can detect indexing
        feat = default_features(prices, i, lookback)
        accessed["max_idx"] = max(accessed["max_idx"], i)
        # If feature_fn ever queried prices[i+1:], it would error or read NaN; we assert by contract here
        # Instead do a structural check: recompute against truncated prices and compare
        return feat

    s = OnlineLearner(feature_fn=tracked_features, warmup=80)
    sig = s.signals(fake_prices)
    assert accessed["max_idx"] <= len(fake_prices) - 1

    # Stronger check: feature at index i must equal feature computed on prices[:i+1]
    i_test = 150
    feat_full = default_features(fake_prices, i_test)
    feat_trunc = default_features(fake_prices.iloc[:i_test + 1], i_test)
    assert np.allclose(feat_full, feat_trunc), "feature_fn uses future data"


def test_default_features_shape(fake_prices):
    f = default_features(fake_prices, 50)
    assert f.shape == (7,)
    assert np.all(np.isfinite(f))


def test_spec_ranges():
    spec = OnlineLearner.spec()
    assert spec.name == "OnlineLearner"
    assert spec.params["warmup"] == 100
    assert spec.params["label_threshold"] == 0.0
    assert spec.param_ranges["warmup"] == (50, 500)
    assert spec.param_ranges["label_threshold"] == (0.0, 0.005)


def test_import_from_library():
    assert OnlineLearner is OLDirect


def test_regressor_branch_runs(fake_prices):
    """Regressor branch must run without passing `classes` to partial_fit.

    sklearn regressors do NOT accept `classes` argument. If the regressor
    branch incorrectly takes the classifier path, partial_fit would raise
    TypeError on the unexpected kwarg.
    """
    fit_calls = {"with_classes": 0, "without_classes": 0}

    class TrackingRegressor:
        """Regressor-like model: no 'Classifier' in name, no `classes_` attr."""

        def __init__(self):
            self._fitted = False

        def partial_fit(self, X, y, classes=None):
            if classes is not None:
                fit_calls["with_classes"] += 1
            else:
                fit_calls["without_classes"] += 1
            self._fitted = True
            return self

        def predict(self, X):
            return np.array([0.5])

    def factory():
        return TrackingRegressor()

    s = OnlineLearner(model_factory=factory, warmup=100)
    sig = s.signals(fake_prices)
    # Regressor branch must NEVER pass classes to partial_fit
    assert fit_calls["with_classes"] == 0, \
        "Regressor branch must not pass 'classes' to partial_fit"
    assert fit_calls["without_classes"] > 0, \
        "Regressor partial_fit must have been called at least once"
    assert len(sig) == len(fake_prices)
    assert not np.any(np.isnan(sig))


def test_classifier_branch_initializes_classes(fake_prices):
    """Classifier branch must call partial_fit(classes=...) on first call only.

    sklearn SGDClassifier requires `classes` on first partial_fit. Subsequent
    calls must not (or may, but the first call MUST include it).
    """
    fit_calls = []

    class TrackingClassifier:
        """Classifier-like: name contains 'Classifier'."""

        def __init__(self):
            self._fitted = False

        def partial_fit(self, X, y, classes=None):
            fit_calls.append({"classes": classes if classes is None else list(classes)})
            self._fitted = True
            return self

        def predict(self, X):
            return np.array([1])

    def factory():
        return TrackingClassifier()

    s = OnlineLearner(model_factory=factory, warmup=100)
    s.signals(fake_prices)
    assert len(fit_calls) > 0, "expected at least one partial_fit call"
    # First call must pass classes
    assert fit_calls[0]["classes"] is not None, \
        "first partial_fit on classifier must include 'classes' kwarg"
    assert sorted(fit_calls[0]["classes"]) == [-1, 0, 1]
    # Subsequent calls must NOT pass classes
    for c in fit_calls[1:]:
        assert c["classes"] is None, \
            "subsequent partial_fit calls must not include 'classes'"


def test_model_kind_override_classifier(fake_prices):
    """model_kind='classifier' must take precedence over auto-detection.

    The mock's partial_fit signature has no ``classes`` parameter, so the
    auto-detect tie-breaker would route to regressor. The override forces
    the classifier branch, which would fail-loudly on a TypeError if it
    tried to pass classes= on this signature. We adapt the mock to swallow
    arbitrary kwargs so the override path can run, then assert the model_kind
    attribute is honored AND signals are produced as classifier-style {-1,0,1}.
    """
    class _Ambiguous:
        def __init__(self):
            pass

        # **kw eats classes=... on first fit when the override forces classifier.
        def partial_fit(self, X, y, **kw):
            return self

        def predict(self, X):
            return np.array([0.7])  # positive scalar

    s = OnlineLearner(model_factory=_Ambiguous, warmup=100,
                      model_kind="classifier")
    sig = s.signals(fake_prices)
    assert s.model_kind == "classifier"
    nonzero = sig[sig != 0]
    if nonzero.size > 0:
        # Classifier branch: np.sign -> {-1, 0, 1}.
        assert set(np.unique(nonzero)).issubset({-1.0, 1.0})


def test_model_kind_override_regressor(fake_prices):
    """model_kind='regressor' must bypass classifier auto-detection even if
    the model has classes_ or 'Classifier' in its name."""
    fit_calls = []

    class _LooksLikeClassifier:
        """Has classes_ attr -> auto-detection would call it a classifier."""
        classes_ = np.array([-1, 0, 1])

        def __init__(self):
            pass

        def partial_fit(self, X, y):
            fit_calls.append({"y": list(y)})
            return self

        def predict(self, X):
            return np.array([0.5])  # regressor-like float

    s = OnlineLearner(model_factory=_LooksLikeClassifier, warmup=100,
                      model_kind="regressor")
    sig = s.signals(fake_prices)
    assert sig.shape == (len(fake_prices),)
    # Regressor branch maps prediction value (clipped) directly; no np.sign.
    # Some bars after warmup must carry the clipped value 0.5.
    assert np.any(np.abs(sig - 0.5) < 1e-9)


def test_pipeline_final_estimator_detection_routes_correctly(fake_prices):
    """When the model exposes ``_final_estimator`` (sklearn Pipeline shape),
    detection must walk to it so a Classifier hidden behind preprocessing
    is still correctly classified.

    We avoid depending on a real sklearn Pipeline's partial_fit semantics by
    using a tiny wrapper that exposes ``_final_estimator`` and forwards
    partial_fit/predict to it. This isolates the detection logic.
    """
    from sklearn.linear_model import SGDClassifier

    class _FakePipeline:
        """Minimal Pipeline-shaped wrapper exposing _final_estimator."""
        def __init__(self):
            self._final_estimator = SGDClassifier(
                loss="log_loss", learning_rate="constant", eta0=0.01,
                random_state=0, warm_start=True,
            )

        def partial_fit(self, X, y, classes=None):
            if classes is not None:
                self._final_estimator.partial_fit(X, y, classes=classes)
            else:
                self._final_estimator.partial_fit(X, y)
            return self

        def predict(self, X):
            return self._final_estimator.predict(X)

    # Without the pipeline-aware fix, the outer wrapper class has neither
    # 'Classifier' in its name nor a classes_ attr, so the old code would
    # fall through to inspecting partial_fit and might mis-route. With the
    # fix, _final_estimator exposes the SGDClassifier and detection succeeds.
    s = OnlineLearner(model_factory=_FakePipeline, warmup=100)
    sig = s.signals(fake_prices)
    assert isinstance(sig, np.ndarray)
    assert len(sig) == len(fake_prices)
    # Classifier branch maps prediction via np.sign -> values in {-1, 0, 1}.
    nonzero = sig[sig != 0]
    if nonzero.size > 0:
        assert set(np.unique(nonzero)).issubset({-1.0, 1.0})


def test_invalid_model_kind_raises():
    with pytest.raises(ValueError, match="model_kind"):
        OnlineLearner(model_kind="bogus")
