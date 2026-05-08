"""Sequence-model Strategy wrapper (QuantForge v1.3 Batch N.4).

Wraps an LSTM, Transformer, or RL agent as a :class:`Strategy`.

Generic over predictor type: any object exposing ``.fit(X, y)`` and ``.predict(X)``
works. Heavy ML deps (torch, stable_baselines3) are imported lazily inside fit/predict
so the module loads even when those libraries are absent.

Walk-forward training: at every ``retrain_every`` bars after ``warmup_bars`` we
refit the underlying model on bars ``[t - train_size, t)`` and use it to
predict bars ``[t, t + retrain_every)``. Threshold rule converts the scalar
prediction at bar i into a {-1, 0, +1} target weight.

Anti-lookahead: features at bar i are computed from prices[:i+1] only; the
model predicting bar i was fitted on bars strictly earlier than t (the chunk
start), so signal[i] never depends on prices[i+1:].

Strategy ABC contract: ``signals()`` returns ``np.ndarray`` of weights in
[-1, 1] with no NaN. Pre-warmup bars are 0 (consistent with sibling strategies
such as OnlineLearner).
"""
from __future__ import annotations

import warnings
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd

from quantforge.strategies.base import Strategy, StrategySpec


# ---------------------------------------------------------------------------
# Default feature builder
# ---------------------------------------------------------------------------

def default_feature_fn(prices: pd.Series) -> pd.DataFrame:
    """Default feature builder: returns at multiple lags + rolling stats.

    Anti-lookahead by construction: every column at index t depends only on
    prices.iloc[:t+1]. Returns a DataFrame aligned to prices.index. Initial
    rows have NaN where the underlying rolling/diff is undefined; callers
    should drop or fillna(0) before passing to a model.
    """
    if isinstance(prices, pd.DataFrame):
        if prices.shape[1] != 1:
            raise ValueError("default_feature_fn expects a Series or single-column DataFrame")
        s = prices.iloc[:, 0]
    else:
        s = prices
    s = s.astype(float)
    ret_1 = s.pct_change()
    ret_5 = s.pct_change(5)
    ret_20 = s.pct_change(20)
    rolling_mean = ret_1.rolling(20, min_periods=1).mean()
    rolling_std = ret_1.rolling(20, min_periods=2).std()
    rolling_max = ret_1.rolling(20, min_periods=1).max()
    rolling_min = ret_1.rolling(20, min_periods=1).min()
    feats = pd.DataFrame(
        {
            "ret_1": ret_1,
            "ret_5": ret_5,
            "ret_20": ret_20,
            "mean_20": rolling_mean,
            "std_20": rolling_std,
            "max_20": rolling_max,
            "min_20": rolling_min,
        },
        index=s.index,
    )
    return feats.fillna(0.0)


# ---------------------------------------------------------------------------
# Mock predictor (testing without torch / sb3)
# ---------------------------------------------------------------------------

class MockPredictor:
    """Deterministic toy predictor used by the test suite.

    fit(X, y): records calls, learns nothing.
    predict(X): returns a scalar per row equal to the mean of the last column
                of each input window (or each row if X is 2-D), passed through
                tanh-like clamping so values stay in [-1, 1].
    """

    def __init__(self, **kwargs: Any) -> None:
        self.fit_calls = 0
        self.last_fit_size = 0
        self._mean = 0.0

    def fit(self, X: np.ndarray, y: np.ndarray) -> "MockPredictor":
        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=float)
        self.fit_calls += 1
        self.last_fit_size = X.shape[0]
        self._mean = float(y.mean()) if y.size else 0.0
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        X = np.asarray(X, dtype=float)
        if X.size == 0:
            return np.zeros((0,), dtype=float)
        if X.ndim == 3:
            # (N, seq_len, n_features) -> mean of last bar across features
            last = X[:, -1, :]
        elif X.ndim == 2:
            last = X
        else:
            last = X.reshape(-1, 1)
        score = last.mean(axis=1) + self._mean
        return np.tanh(score)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _flatten_window(window: np.ndarray) -> np.ndarray:
    """Flatten a (seq_len, n_features) window to a 1-D vector for non-sequence
    predictors (mock, sklearn-style models)."""
    return np.asarray(window, dtype=float).reshape(-1)


def _build_predictor(model_type: str, model_params: dict, predictor_class: Optional[type]) -> Any:
    """Construct an underlying predictor.

    - ``predictor_class`` overrides everything (used in tests).
    - ``model_type='mock'`` -> :class:`MockPredictor`
    - ``model_type='lstm'`` -> lazy import quantforge.ml.lstm.LSTMForecaster
    - ``model_type='transformer'`` -> lazy import quantforge.ml.transformer
    - ``model_type='rl'`` -> RL adapter built lazily; trained inside fit().
    """
    if predictor_class is not None:
        return predictor_class(**(model_params or {}))

    mt = (model_type or "").lower()
    if mt == "mock":
        return MockPredictor(**(model_params or {}))

    if mt == "lstm":
        from quantforge.ml.lstm import LSTMConfig, LSTMForecaster  # lazy
        cfg = LSTMConfig(**(model_params or {}))
        return _LSTMAdapter(LSTMForecaster(cfg), cfg)

    if mt == "transformer":
        from quantforge.ml.transformer import TransformerConfig, TimeSeriesTransformer  # lazy
        cfg = TransformerConfig(**(model_params or {}))
        return _TransformerAdapter(TimeSeriesTransformer(cfg), cfg)

    if mt == "rl":
        return _RLAdapter(model_params or {})

    raise ValueError(f"Unknown model_type={model_type!r}")


class _LSTMAdapter:
    """Adapt :class:`LSTMForecaster` to the (X 2-D, y 1-D) fit/predict shape.

    The wrapper itself reshapes flattened windows back into (N, seq_len, F).
    """

    def __init__(self, forecaster: Any, cfg: Any) -> None:
        self.forecaster = forecaster
        self.cfg = cfg

    def _to_3d(self, X: np.ndarray) -> np.ndarray:
        X = np.asarray(X, dtype=np.float32)
        if X.ndim == 3:
            return X
        seq_len = self.cfg.seq_len
        n = X.shape[0]
        n_features = X.shape[1] // seq_len if X.ndim == 2 else 1
        return X.reshape(n, seq_len, n_features)

    def fit(self, X: np.ndarray, y: np.ndarray) -> "_LSTMAdapter":
        # Rebuild fresh weights per fold to avoid leakage.
        self.forecaster._model = None
        self.forecaster._optim = None
        X_3d = self._to_3d(X)
        # Defensive shape check: the underlying nn.LSTM has its input_size baked
        # into its first weight matrix. If the caller stacked features whose
        # last-axis size disagrees with cfg.input_dim, the underlying fit raises
        # a confusing matmul mismatch. Surface the contract here instead.
        cfg_input_dim = getattr(self.cfg, "input_dim", None)
        if cfg_input_dim is not None and cfg_input_dim != X_3d.shape[-1]:
            raise ValueError(
                f"_LSTMAdapter.fit: cfg.input_dim ({cfg_input_dim}) does not "
                f"match feature last-axis size ({X_3d.shape[-1]}). Update "
                f"model_params['input_dim'] or rebuild the predictor."
            )
        self.forecaster.fit(X_3d, np.asarray(y, dtype=np.float32))
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        return np.asarray(self.forecaster.predict(self._to_3d(X)), dtype=float).reshape(-1)


class _TransformerAdapter:
    """Same idea as :class:`_LSTMAdapter` but for :class:`TimeSeriesTransformer`.

    Predicts the first horizon if the model emits a multi-horizon vector.
    """

    def __init__(self, model: Any, cfg: Any) -> None:
        self.model = model
        self.cfg = cfg

    def _to_3d(self, X: np.ndarray) -> np.ndarray:
        X = np.asarray(X, dtype=np.float32)
        if X.ndim == 3:
            return X
        seq_len = self.cfg.seq_len
        n = X.shape[0]
        n_features = X.shape[1] // seq_len if X.ndim == 2 else 1
        return X.reshape(n, seq_len, n_features)

    def fit(self, X: np.ndarray, y: np.ndarray) -> "_TransformerAdapter":
        y_arr = np.asarray(y, dtype=np.float32)
        if y_arr.ndim == 1:
            y_arr = y_arr.reshape(-1, 1)
        X_3d = self._to_3d(X)
        # Same shape contract as _LSTMAdapter: surface input_dim mismatch
        # explicitly so the failure mode is informative.
        cfg_input_dim = getattr(self.cfg, "input_dim", None)
        if cfg_input_dim is not None and cfg_input_dim != X_3d.shape[-1]:
            raise ValueError(
                f"_TransformerAdapter.fit: cfg.input_dim ({cfg_input_dim}) "
                f"does not match feature last-axis size ({X_3d.shape[-1]}). "
                f"Update model_params['input_dim'] or rebuild the predictor."
            )
        # Rebuild fresh weights per fold to avoid leakage. Mirrors
        # ``_LSTMAdapter.fit`` so walk-forward folds are independent.
        # Prefer an explicit ``reset()`` if the underlying impl exposes one,
        # otherwise reinstantiate the underlying transformer from cfg, falling
        # back to nulling ``_model``/``_optim`` attrs as a last resort.
        if hasattr(self.model, "reset") and callable(self.model.reset):
            self.model.reset()
        else:
            try:
                from quantforge.ml.transformer import TimeSeriesTransformer  # lazy
                self.model = TimeSeriesTransformer(self.cfg)
            except (ImportError, TypeError, ValueError) as exc:
                warnings.warn(
                    f"TimeSeriesTransformer rebuild failed ({exc!r}); "
                    "falling back to nulling _model/_optim attrs.",
                    RuntimeWarning,
                    stacklevel=2,
                )
                if hasattr(self.model, "_model"):
                    self.model._model = None
                if hasattr(self.model, "_optim"):
                    self.model._optim = None
        self.model.fit(X_3d, y_arr)
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        out = np.asarray(self.model.predict(self._to_3d(X)), dtype=float)
        if out.ndim == 2:
            out = out[:, 0]
        return out.reshape(-1)


class _RLAdapter:
    """Wrap a stable-baselines3 PPO / DQN agent as a sequence predictor.

    For each fit() call we build a tiny single-asset TradingEnv from the
    feature window and reward = next-bar return, train the agent for a
    configurable timestep budget, and predict positions on the test window.
    """

    def __init__(self, model_params: dict) -> None:
        self.model_params = dict(model_params)
        self.algo_name = self.model_params.pop("algo", "PPO")
        self.total_timesteps = int(self.model_params.pop("total_timesteps", 1000))
        self.agent: Any = None

    def fit(self, X: np.ndarray, y: np.ndarray) -> "_RLAdapter":
        # Lazy import keeps the module loadable without sb3.
        try:
            from stable_baselines3 import PPO, DQN  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise ImportError(
                "model_type='rl' requires stable_baselines3. "
                "Install with: pip install stable-baselines3"
            ) from e
        from gymnasium import Env, spaces  # type: ignore

        X_arr = np.asarray(X, dtype=np.float32)
        y_arr = np.asarray(y, dtype=np.float32)
        flat = X_arr.reshape(X_arr.shape[0], -1)
        n_features = flat.shape[1]

        class _MiniTradingEnv(Env):  # local class avoids cross-imports
            metadata = {"render_modes": []}

            def __init__(self) -> None:
                super().__init__()
                self.observation_space = spaces.Box(
                    low=-np.inf, high=np.inf, shape=(n_features,), dtype=np.float32
                )
                self.action_space = spaces.Discrete(3)  # short / flat / long
                self._i = 0

            def reset(self, *, seed=None, options=None):
                super().reset(seed=seed)
                self._i = 0
                return flat[0], {}

            def step(self, action):
                pos = float(action) - 1.0  # -1, 0, +1
                ret = float(y_arr[self._i])
                reward = pos * ret
                self._i += 1
                terminated = self._i >= len(flat) - 1
                obs = flat[min(self._i, len(flat) - 1)]
                return obs, reward, terminated, False, {}

        env = _MiniTradingEnv()
        algo_cls = {"PPO": PPO, "DQN": DQN}.get(self.algo_name.upper(), PPO)
        kwargs = dict(self.model_params)
        kwargs.setdefault("policy", "MlpPolicy")
        kwargs.setdefault("verbose", 0)
        self.agent = algo_cls(env=env, **kwargs)
        self.agent.learn(total_timesteps=self.total_timesteps)
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        if self.agent is None:
            return np.zeros((np.asarray(X).shape[0],), dtype=float)
        X_arr = np.asarray(X, dtype=np.float32)
        flat = X_arr.reshape(X_arr.shape[0], -1)
        out = np.empty(flat.shape[0], dtype=float)
        for i, obs in enumerate(flat):
            action, _ = self.agent.predict(obs, deterministic=True)
            out[i] = float(int(action) - 1)  # map {0,1,2} -> {-1,0,+1}
        return out


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------

class SeqModelStrategy(Strategy):
    """Wraps a sequence model (LSTM / Transformer / RL agent) as a Strategy.

    Generic: any object with ``fit(X, y)`` + ``predict(X)`` works. Useful for
    GA-driven model selection without hardcoding a particular implementation.

    Parameters
    ----------
    model_type:
        ``'lstm' | 'transformer' | 'rl' | 'mock'``. Only consulted when
        ``predictor_class`` is None.
    model_params:
        Keyword arguments forwarded to the underlying model constructor.
    feature_fn:
        ``feature_fn(prices: pd.Series) -> pd.DataFrame``. Must respect
        causality: row at time t depends only on prices.iloc[:t+1].
    threshold:
        Prediction -> signal rule: ``+1 if pred > threshold``,
        ``-1 if pred < -threshold``, ``0`` otherwise.
    retrain_every:
        Refit cadence (in bars). The model trained at chunk boundary
        ``t`` is used for predictions in ``[t, t + retrain_every)``.
    warmup_bars:
        Number of leading bars without predictions.
    train_size:
        Bars in the training window. Defaults to ``warmup_bars`` when 0 or None.
    seq_len:
        Sequence length for predictors that consume 3-D windows. When > 1 the
        wrapper builds (N, seq_len, n_features) tensors; for non-sequential
        predictors (mock, sklearn) ``seq_len = 1`` makes each sample one
        feature vector.
    horizon:
        Forecast horizon, in bars, for the supervised target.
    predictor_class:
        Optional explicit constructor; overrides ``model_type``. Used by tests.
    """

    def __init__(
        self,
        model_type: str = "mock",
        model_params: Optional[dict] = None,
        feature_fn: Optional[Callable[[pd.Series], pd.DataFrame]] = None,
        threshold: float = 0.0,
        retrain_every: int = 252,
        warmup_bars: int = 252,
        train_size: Optional[int] = None,
        seq_len: int = 1,
        horizon: int = 1,
        predictor_class: Optional[type] = None,
    ) -> None:
        self.model_type = str(model_type)
        self.model_params = dict(model_params) if model_params else {}
        self.feature_fn = feature_fn if feature_fn is not None else default_feature_fn
        self.threshold = float(threshold)
        retrain_every_i = int(retrain_every)
        if retrain_every_i < 1:
            raise ValueError(
                f"retrain_every must be >= 1; got {retrain_every!r}"
            )
        self.retrain_every = retrain_every_i
        self.warmup_bars = int(warmup_bars)
        # train_size semantics:
        #   - None -> default to warmup_bars (callers commonly want this).
        #   - int > 0 -> use as-is.
        #   - 0 or negative -> rejected; ``train_size=0`` was previously
        #     ambiguous (treated as falsy and silently coerced to warmup_bars)
        #     which masked configuration bugs.
        if train_size is None:
            self.train_size = int(warmup_bars)
        else:
            ts = int(train_size)
            if ts <= 0:
                raise ValueError(
                    f"train_size must be > 0 or None; got {train_size!r}"
                )
            self.train_size = ts
        self.seq_len = int(seq_len)
        horizon_i = int(horizon)
        if horizon_i < 1:
            raise ValueError(
                f"horizon must be >= 1; got {horizon!r}"
            )
        self.horizon = horizon_i
        self.predictor_class = predictor_class

    @classmethod
    def spec(cls) -> StrategySpec:
        return StrategySpec(
            name="SeqModelStrategy",
            params={
                "threshold": 0.0,
                "retrain_every": 252,
                "warmup_bars": 252,
                "seq_len": 1,
                "horizon": 1,
            },
            param_ranges={
                "threshold": (0.0, 0.01),
                "retrain_every": (21, 504),
                "warmup_bars": (63, 504),
                "seq_len": (1, 60),
                "horizon": (1, 10),
            },
        )

    # -- helpers -----------------------------------------------------------

    def _build_features(self, prices: pd.Series) -> pd.DataFrame:
        feats = self.feature_fn(prices)
        if not isinstance(feats, pd.DataFrame):
            raise TypeError("feature_fn must return a DataFrame aligned to prices.index")
        if len(feats) != len(prices):
            raise ValueError(
                f"feature_fn output length ({len(feats)}) must match prices ({len(prices)})"
            )
        # Note: silently zero-filling NaN/inf masks rolling-warmup rows. We
        # still apply the replacement so the array has finite values, but the
        # ``signals()`` walk below skips rows inside the warmup window from
        # the training index so the training-window slice never contains the
        # zeroed warmup rows.
        feats = feats.replace([np.inf, -np.inf], 0.0).fillna(0.0)
        return feats.astype(float)

    def _build_target(self, prices: pd.Series) -> np.ndarray:
        """Forward simple return at ``horizon`` ahead, used as supervised target.

        ``y[i] = (p[i + h] - p[i]) / p[i]`` for valid ``i``; trailing rows
        without an observable target are 0. Earlier docstrings mistakenly
        described this as a log-return; the code computes a simple return.

        ``h = max(1, self.horizon)`` mirrors the ``signals()`` invariant: even
        though ``__init__`` enforces ``horizon >= 1``, this guard keeps the
        target builder consistent with the prediction loop's chunk math.
        """
        p = np.asarray(prices.values, dtype=float)
        n = len(p)
        y = np.zeros(n, dtype=float)
        # ctor enforces horizon >= 1, so no guard needed.
        h = self.horizon
        for i in range(n - h):
            if p[i] == 0:
                y[i] = 0.0
            else:
                y[i] = (p[i + h] - p[i]) / p[i]
        return y

    def _make_window(self, feats: np.ndarray, end_idx: int) -> np.ndarray:
        """Build one input sample ending at ``end_idx`` (inclusive).

        Returns shape ``(seq_len, n_features)`` for sequential predictors
        (seq_len > 1) or the bar-i feature row for non-sequential ones
        (seq_len <= 1).

        If ``end_idx - seq_len + 1 < 0`` we still zero-pad the leading rows
        so the returned tensor shape is stable (callers vstack/stack into
        contiguous arrays). The proper way to AVOID looking at a padded
        window is to keep ``warmup_bars >= seq_len - 1`` so prediction
        indices ``[warmup, warmup+chunk)`` never start below ``seq_len-1``.
        ``signals()`` enforces this invariant by clamping pred indices to
        ``max(t, seq_len - 1)``; training indices already start at
        ``feature_warmup >= seq_len - 1`` for default warmup configurations.
        """
        s = self.seq_len
        if s <= 1:
            return feats[end_idx]
        start = end_idx - s + 1
        if start < 0:
            # Defensive zero-pad. Should never actually trigger given the
            # invariant enforced in signals(); kept as a fallback so the
            # function never raises on edge configs.
            pad = np.zeros((-start, feats.shape[1]), dtype=float)
            window = np.vstack([pad, feats[: end_idx + 1]])
        else:
            window = feats[start : end_idx + 1]
        return window  # 2-D (seq_len, n_features)

    def _stack_windows(self, feats: np.ndarray, idx_iter) -> np.ndarray:
        rows = [self._make_window(feats, i) for i in idx_iter]
        if self.seq_len <= 1:
            return np.vstack(rows)
        return np.stack(rows, axis=0)  # (N, seq_len, n_features)

    def _apply_threshold(self, preds: np.ndarray) -> np.ndarray:
        out = np.zeros_like(preds, dtype=float)
        out[preds > self.threshold] = 1.0
        out[preds < -self.threshold] = -1.0
        return out

    # -- main entry point --------------------------------------------------

    def signals(self, prices: pd.Series) -> np.ndarray:
        """Walk-forward generate {-1, 0, +1} target weights.

        Pre-warmup bars are 0 (Strategy ABC forbids NaN). Within each
        ``retrain_every`` chunk after warmup, the model is fit on
        ``[t - train_size, t)`` and its predictions are converted to weights
        via ``_apply_threshold``.
        """
        if isinstance(prices, pd.DataFrame):
            if prices.shape[1] != 1:
                raise ValueError("SeqModelStrategy expects a Series or single-column frame")
            prices = prices.iloc[:, 0]
        n = len(prices)
        out = np.zeros(n, dtype=float)
        if n <= self.warmup_bars:
            return out

        feats_df = self._build_features(prices)
        feats = feats_df.values.astype(float)
        targets = self._build_target(prices)

        # Warmup floor: rows < feature_warmup may contain zero-filled NaNs
        # from rolling windows (see _build_features). Excluding them from
        # train_idx avoids training on the silently-zeroed warmup region.
        # We use 20 bars as a conservative bound matching default_feature_fn.
        # Also lift the floor to seq_len-1 so _make_window never needs the
        # zero-pad fallback (windows always have a full lookback available).
        feature_warmup = max(20, self.seq_len - 1)

        # ctor enforces all three are >= 1, so no max() guard needed.
        chunk = self.retrain_every
        train_size = self.train_size
        h = self.horizon

        # Effective warmup: enforce warmup_bars >= feature_warmup + seq_len - 1
        # so the FIRST prediction window sits entirely PAST the rolling-feature
        # warmup band. ``feature_warmup`` (=max(20, seq_len-1)) is where the
        # training slice may start, so the first valid prediction needs at
        # least ``seq_len-1`` bars on top of that to avoid pulling
        # zero-filled warmup rows into the prediction window.
        effective_warmup = max(
            self.warmup_bars, feature_warmup + self.seq_len - 1
        )

        t = effective_warmup
        while t < n:
            chunk_end = min(t + chunk, n)
            train_lo = max(0, t - train_size)
            # Training samples must have observable target: end_idx + horizon < t.
            # Also skip the feature warmup region so the training-window
            # feature slice never contains the silently-zeroed warmup rows.
            train_idx = list(range(max(train_lo, feature_warmup), t - h))
            if len(train_idx) < 1:
                t = chunk_end
                continue

            X_train = self._stack_windows(feats, train_idx)
            # Hard assert: after skipping warmup, no NaN should remain in the
            # training-window slice. (We already replace inf/NaN in
            # _build_features, but this guards against future regressions.)
            if not np.all(np.isfinite(X_train)):
                raise AssertionError(
                    "SeqModelStrategy: NaN/inf detected in training-window "
                    "feature slice after warmup skip"
                )
            y_train = np.asarray([targets[i] for i in train_idx], dtype=float)

            predictor = _build_predictor(
                self.model_type, self.model_params, self.predictor_class
            )
            predictor.fit(X_train, y_train)

            pred_idx = list(range(t, chunk_end))
            X_pred = self._stack_windows(feats, pred_idx)
            try:
                preds = np.asarray(predictor.predict(X_pred), dtype=float).reshape(-1)
            except (RuntimeError, ValueError) as exc:
                # Narrow on the failure modes we actually expect from the
                # underlying torch/sklearn-style predictors (shape mismatch,
                # CUDA OOM, ill-conditioned matmul). Surface anything else
                # so genuine bugs aren't hidden behind a zero-fallback.
                warnings.warn(
                    f"SeqModelStrategy: predict() failed at t={t} with "
                    f"{type(exc).__name__}: {exc}; falling back to zero "
                    "weights for this chunk.",
                    RuntimeWarning,
                    stacklevel=2,
                )
                preds = np.zeros(len(pred_idx), dtype=float)
            sigs = self._apply_threshold(preds[: len(pred_idx)])
            out[t:chunk_end] = sigs

            t = chunk_end

        return np.clip(out, -1.0, 1.0)
