"""Causal ensemble, model and control kernels for SP500 lanes F051-F060."""

from __future__ import annotations

from itertools import combinations, product
from typing import Any, Callable, Mapping, Sequence

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import expit, ndtr


class ModelFeatureEngineError(ValueError):
    """Raised when a model input is incomplete, non-causal or outside train."""


_TRAIN_END = pd.Timestamp("2010-12-31")

_FEATURE_SETS: Mapping[str, tuple[str, ...]] = {
    "diversified_3": ("F003", "F021", "F032"),
    "diversified_5": ("F003", "F009", "F021", "F032", "F039"),
    "market_5": ("F001", "F003", "F009", "F015", "F021"),
    "macro_5": ("F003", "F032", "F033", "F039", "F049"),
    "breadth_5": ("F003", "F021", "F044", "F046", "F048"),
}

_ENSEMBLE_SETS: Mapping[str, tuple[str, ...]] = {
    "diversified": ("F003", "F021", "F032", "F039", "F046"),
    "trend": ("F001", "F003", "F006", "F044", "F046"),
    "contrarian": ("F009", "F010", "F022", "F039", "F049"),
    "macro": ("F003", "F032", "F033", "F039", "F049"),
}

# Every ensemble component is converted to the common convention
# positive = bullish for SPY before voting.
_BULLISH_ORIENTATION: Mapping[str, float] = {
    "F021": -1.0,
    "F032": -1.0,
    "F033": -1.0,
    "F048": -1.0,
}

_BASE_LANES: Mapping[str, str] = {
    "trend": "F003",
    "reversal": "F009",
    "breakout": "F006",
    "ensemble": "F051",
}

_GATE_LANES: Mapping[str, tuple[str, float]] = {
    "volatility": ("F015", -1.0),
    "vix": ("F021", -1.0),
    "credit": ("F032", -1.0),
    "macro": ("F035", 1.0),
    "liquidity": ("F020", 1.0),
}


def _validated_market(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"date", "observed_at", "available_at", "close"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ModelFeatureEngineError(f"MARKET_COLUMNS_MISSING:{','.join(missing)}")
    market = frame.loc[:, sorted(required)].copy()
    for column in ("date", "observed_at", "available_at"):
        market[column] = (
            pd.to_datetime(market[column], errors="coerce")
            .dt.normalize()
            .astype("datetime64[ns]")
        )
    if market[["date", "observed_at", "available_at"]].isna().any().any():
        raise ModelFeatureEngineError("INVALID_MARKET_DATE")
    if market["date"].gt(_TRAIN_END).any() or market["available_at"].gt(_TRAIN_END).any():
        raise ModelFeatureEngineError("NON_TRAIN_MARKET_ROW")
    if market["available_at"].gt(market["date"]).any():
        raise ModelFeatureEngineError("MARKET_NOT_AVAILABLE_AT_DECISION")
    if market["observed_at"].gt(market["available_at"]).any():
        raise ModelFeatureEngineError("MARKET_OBSERVED_AFTER_AVAILABILITY")
    if market["date"].duplicated().any() or not market["date"].is_monotonic_increasing:
        raise ModelFeatureEngineError("MARKET_DATES_NOT_ORDERED")
    market["close"] = pd.to_numeric(market["close"], errors="coerce")
    if market["close"].isna().any() or market["close"].le(0.0).any():
        raise ModelFeatureEngineError("INVALID_MARKET_CLOSE")
    return market.reset_index(drop=True)


def _validated_feature(lane_id: str, frame: pd.DataFrame) -> pd.DataFrame:
    required = {"date", "observed_at", "available_at", "value"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ModelFeatureEngineError(
            f"FEATURE_COLUMNS_MISSING:{lane_id}:{','.join(missing)}"
        )
    feature = frame.loc[:, sorted(required)].copy()
    for column in ("date", "observed_at", "available_at"):
        feature[column] = (
            pd.to_datetime(feature[column], errors="coerce")
            .dt.normalize()
            .astype("datetime64[ns]")
        )
    if feature[["date", "observed_at", "available_at"]].isna().any().any():
        raise ModelFeatureEngineError(f"INVALID_FEATURE_DATE:{lane_id}")
    if feature["date"].gt(_TRAIN_END).any() or feature["available_at"].gt(_TRAIN_END).any():
        raise ModelFeatureEngineError(f"NON_TRAIN_FEATURE_ROW:{lane_id}")
    if feature["available_at"].gt(feature["date"]).any():
        raise ModelFeatureEngineError(f"FEATURE_NOT_AVAILABLE_AT_DECISION:{lane_id}")
    if feature["observed_at"].gt(feature["available_at"]).any():
        raise ModelFeatureEngineError(f"FEATURE_OBSERVED_AFTER_AVAILABILITY:{lane_id}")
    if feature["date"].duplicated().any() or not feature["date"].is_monotonic_increasing:
        raise ModelFeatureEngineError(f"FEATURE_DATES_NOT_ORDERED:{lane_id}")
    feature["value"] = pd.to_numeric(feature["value"], errors="coerce").replace(
        [np.inf, -np.inf], np.nan
    )
    return feature.reset_index(drop=True)


def _required_ids(
    feature_panels: Mapping[str, pd.DataFrame], lane_ids: Sequence[str]
) -> None:
    missing = sorted(set(lane_ids) - set(feature_panels))
    if missing:
        raise ModelFeatureEngineError(f"FEATURE_PANELS_MISSING:{','.join(missing)}")


def _aligned_features(
    market: pd.DataFrame,
    feature_panels: Mapping[str, pd.DataFrame],
    lane_ids: Sequence[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    _required_ids(feature_panels, lane_ids)
    master = pd.DataFrame({"date": market["date"]})
    values: dict[str, pd.Series] = {}
    observations: dict[str, pd.Series] = {}
    for lane_id in lane_ids:
        feature = _validated_feature(lane_id, feature_panels[lane_id])
        usable = feature.loc[feature["value"].notna()].copy()
        if usable.empty:
            values[lane_id] = pd.Series(np.nan, index=master.index, dtype=float)
            observations[lane_id] = pd.Series(pd.NaT, index=master.index)
            continue
        right = usable.loc[:, ["available_at", "observed_at", "value"]].rename(
            columns={
                "available_at": "source_available_at",
                "observed_at": "source_observed_at",
            }
        )
        aligned = pd.merge_asof(
            master,
            right.sort_values("source_available_at"),
            left_on="date",
            right_on="source_available_at",
            direction="backward",
            allow_exact_matches=True,
        )
        future = aligned["source_available_at"].gt(aligned["date"])
        if future.fillna(False).any():
            raise ModelFeatureEngineError(f"FORWARD_FILLED_FEATURE:{lane_id}")
        values[lane_id] = pd.to_numeric(aligned["value"], errors="coerce")
        observations[lane_id] = pd.to_datetime(aligned["source_observed_at"])
    return pd.DataFrame(values), pd.DataFrame(observations)


def _output(
    market: pd.DataFrame,
    value: pd.Series | np.ndarray,
    observed_at: pd.Series,
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": market["date"],
            "observed_at": pd.to_datetime(observed_at).fillna(market["observed_at"]),
            "available_at": market["date"],
            "value": pd.to_numeric(pd.Series(value, index=market.index), errors="coerce").replace(
                [np.inf, -np.inf], np.nan
            ),
        }
    )


def _max_observation(observations: pd.DataFrame, market: pd.DataFrame) -> pd.Series:
    if observations.empty:
        return market["observed_at"]
    return observations.max(axis=1).fillna(market["observed_at"])


def _feature_set(parameters: Mapping[str, Any]) -> tuple[str, ...]:
    name = str(parameters.get("feature_set", "diversified_5"))
    try:
        return _FEATURE_SETS[name]
    except KeyError as exc:
        raise ModelFeatureEngineError(f"UNKNOWN_FEATURE_SET:{name}") from exc


def _refit_due(dates: pd.Series, index: int, cadence: str, has_model: bool) -> bool:
    if not has_model:
        return True
    if cadence == "daily":
        return True
    if index == 0:
        return True
    current = pd.Timestamp(dates.iloc[index])
    previous = pd.Timestamp(dates.iloc[index - 1])
    if cadence == "weekly":
        return current.to_period("W") != previous.to_period("W")
    if cadence == "monthly":
        return current.to_period("M") != previous.to_period("M")
    if cadence == "quarterly":
        return current.to_period("Q") != previous.to_period("Q")
    if cadence == "annual":
        return current.year != previous.year
    raise ModelFeatureEngineError(f"UNKNOWN_REFIT_CADENCE:{cadence}")


def _standardize_fit(x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    location = np.nanmean(x, axis=0)
    scale = np.nanstd(x, axis=0)
    scale = np.where(scale > 1e-12, scale, 1.0)
    return (x - location) / scale, location, scale


def _rolling_supervised(
    market: pd.DataFrame,
    features: pd.DataFrame,
    *,
    window: int,
    cadence: str,
    fit: Callable[[np.ndarray, np.ndarray], Any],
    predict: Callable[[Any, np.ndarray], float],
) -> pd.Series:
    x = features.to_numpy(dtype=float)
    forward_return = market["close"].pct_change(fill_method=None).shift(-1).to_numpy()
    result = np.full(len(market), np.nan, dtype=float)
    model: Any = None
    for index in range(len(market)):
        if index < window:
            continue
        if _refit_due(market["date"], index, cadence, model is not None):
            start = max(0, index - window)
            train_x = x[start:index]
            train_y = forward_return[start:index]
            valid = np.isfinite(train_y) & np.isfinite(train_x).all(axis=1)
            if int(valid.sum()) == window and np.unique(train_y[valid] > 0.0).size > 1:
                model = fit(train_x[valid], train_y[valid])
        if model is not None and np.isfinite(x[index]).all():
            result[index] = predict(model, x[index])
    return pd.Series(result, index=market.index)


def _f051(
    market: pd.DataFrame,
    feature_panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> tuple[pd.Series, pd.Series]:
    set_name = str(parameters.get("component_set", "diversified"))
    if set_name not in _ENSEMBLE_SETS:
        raise ModelFeatureEngineError(f"UNKNOWN_COMPONENT_SET:{set_name}")
    count = int(parameters.get("components", 5))
    lane_ids = _ENSEMBLE_SETS[set_name][:count]
    if count not in {3, 5} or len(lane_ids) != count:
        raise ModelFeatureEngineError(f"INVALID_COMPONENT_COUNT:{count}")
    values, observations = _aligned_features(market, feature_panels, lane_ids)
    oriented = values.copy()
    for lane_id in lane_ids:
        oriented[lane_id] *= _BULLISH_ORIENTATION.get(lane_id, 1.0)
    votes = np.sign(oriented)
    aggregation = str(parameters.get("aggregation", "majority"))
    if aggregation == "majority":
        value = votes.mean(axis=1, skipna=False)
    elif aggregation == "unanimity":
        positive = votes.eq(1.0).all(axis=1)
        negative = votes.eq(-1.0).all(axis=1)
        value = pd.Series(np.where(positive, 1.0, np.where(negative, -1.0, 0.0)))
        value = value.mask(votes.isna().any(axis=1))
    elif aggregation == "median":
        normalization_window = int(parameters.get("normalization_window", 126))
        normalized = (oriented - oriented.rolling(normalization_window).mean()) / oriented.rolling(
            normalization_window
        ).std(ddof=0).replace(0.0, np.nan)
        value = normalized.median(axis=1, skipna=False)
    elif aggregation == "weighted_vote":
        normalization_window = int(parameters.get("normalization_window", 126))
        volatility = oriented.diff().rolling(normalization_window).std(ddof=0)
        weights = 1.0 / volatility.replace(0.0, np.nan)
        value = (weights * votes).sum(axis=1, min_count=count) / weights.sum(
            axis=1, min_count=count
        )
    else:
        raise ModelFeatureEngineError(f"UNKNOWN_ENSEMBLE_AGGREGATION:{aggregation}")
    return value, _max_observation(observations, market)


def _f052(
    market: pd.DataFrame,
    feature_panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> tuple[pd.Series, pd.Series]:
    base_name = str(parameters.get("base", "trend"))
    gate_name = str(parameters.get("gate", "vix"))
    if base_name not in _BASE_LANES:
        raise ModelFeatureEngineError(f"UNKNOWN_GATE_BASE:{base_name}")
    if gate_name not in _GATE_LANES:
        raise ModelFeatureEngineError(f"UNKNOWN_GATE_STATE:{gate_name}")
    base_lane = _BASE_LANES[base_name]
    gate_lane, orientation = _GATE_LANES[gate_name]
    values, observations = _aligned_features(
        market, feature_panels, (base_lane, gate_lane)
    )
    base = np.sign(values[base_lane])
    gate = np.sign(values[gate_lane] * orientation)
    confirmation = int(parameters.get("confirmation", 1))
    positive = gate.eq(1.0).rolling(confirmation, min_periods=confirmation).sum().eq(
        float(confirmation)
    )
    negative = gate.eq(-1.0).rolling(confirmation, min_periods=confirmation).sum().eq(
        float(confirmation)
    )
    confirmed = pd.Series(
        np.where(positive, 1.0, np.where(negative, -1.0, 0.0)), index=market.index
    ).mask(gate.isna())
    logic = str(parameters.get("logic", "and"))
    if logic == "and":
        value = pd.Series(np.where(confirmed.gt(0.0), base, -1.0), index=market.index)
    elif logic == "or":
        value = pd.Series(
            np.where(base.gt(0.0) | confirmed.gt(0.0), 1.0, -1.0),
            index=market.index,
        )
    elif logic == "override":
        value = confirmed.where(confirmed.ne(0.0), base)
    elif logic == "switch":
        value = base.where(confirmed.ge(0.0), -base)
    else:
        raise ModelFeatureEngineError(f"UNKNOWN_GATE_LOGIC:{logic}")
    value = value.mask(base.isna() | confirmed.isna())
    return value, _max_observation(observations, market)


def _fit_cluster(x: np.ndarray, y: np.ndarray, clusters: int) -> Mapping[str, np.ndarray]:
    standardized, location, scale = _standardize_fit(x)
    direction = np.arange(1.0, standardized.shape[1] + 1.0)
    direction /= np.linalg.norm(direction)
    projection = standardized @ direction
    order = np.argsort(projection, kind="mergesort")
    positions = np.linspace(0, len(order) - 1, clusters + 2).round().astype(int)[1:-1]
    centers = standardized[order[positions]].copy()
    labels = np.zeros(len(standardized), dtype=int)
    for _ in range(40):
        distances = ((standardized[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
        updated_labels = distances.argmin(axis=1)
        updated_centers = centers.copy()
        for state in range(clusters):
            members = standardized[updated_labels == state]
            if len(members):
                updated_centers[state] = members.mean(axis=0)
        if np.array_equal(updated_labels, labels) and np.allclose(updated_centers, centers):
            break
        labels = updated_labels
        centers = updated_centers
    fallback = float(np.mean(y))
    rewards = np.array(
        [float(np.mean(y[labels == state])) if np.any(labels == state) else fallback for state in range(clusters)]
    )
    return {"location": location, "scale": scale, "centers": centers, "rewards": rewards}


def _predict_cluster(model: Mapping[str, np.ndarray], row: np.ndarray) -> float:
    standardized = (row - model["location"]) / model["scale"]
    distances = ((model["centers"] - standardized) ** 2).sum(axis=1)
    return float(model["rewards"][int(distances.argmin())])


def _f053(
    market: pd.DataFrame,
    feature_panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> tuple[pd.Series, pd.Series]:
    lane_ids = _feature_set(parameters)
    features, observations = _aligned_features(market, feature_panels, lane_ids)
    clusters = int(parameters.get("clusters", 3))
    if clusters not in {2, 3, 4}:
        raise ModelFeatureEngineError(f"INVALID_CLUSTER_COUNT:{clusters}")
    value = _rolling_supervised(
        market,
        features,
        window=int(parameters.get("window", 504)),
        cadence=str(parameters.get("refit", "monthly")),
        fit=lambda x, y: _fit_cluster(x, y, clusters),
        predict=_predict_cluster,
    )
    return value, _max_observation(observations, market)


def _fit_markov(
    observations: np.ndarray,
    rewards: np.ndarray,
    states: int,
) -> Mapping[str, np.ndarray]:
    location = np.mean(observations, axis=0)
    scale = np.std(observations, axis=0)
    scale = np.where(scale > 1e-12, scale, 1.0)
    standardized = (observations - location) / scale
    direction = np.ones(standardized.shape[1], dtype=float)
    direction[0] = -1.0
    risk = standardized @ direction / np.sqrt(float(len(direction)))
    thresholds = np.quantile(risk, np.linspace(0.0, 1.0, states + 1)[1:-1])
    labels = np.digitize(risk, thresholds).astype(int)
    transition = np.ones((states, states), dtype=float)
    for left, right in zip(labels[:-1], labels[1:], strict=True):
        transition[left, right] += 1.0
    transition /= transition.sum(axis=1, keepdims=True)
    means = np.zeros(states, dtype=float)
    deviations = np.ones(states, dtype=float)
    state_rewards = np.full(states, float(np.mean(rewards)))
    for state in range(states):
        members = risk[labels == state]
        if len(members):
            means[state] = float(np.mean(members))
            deviations[state] = max(float(np.std(members)), 0.1)
            state_rewards[state] = float(np.mean(rewards[labels == state]))
    prior = np.bincount(labels, minlength=states).astype(float) + 1.0
    prior /= prior.sum()
    return {
        "location": location,
        "scale": scale,
        "direction": direction,
        "transition": transition,
        "means": means,
        "deviations": deviations,
        "rewards": state_rewards,
        "prior": prior,
    }


def _markov_update(
    model: Mapping[str, np.ndarray], row: np.ndarray, prior: np.ndarray
) -> tuple[float, np.ndarray]:
    standardized = (row - model["location"]) / model["scale"]
    risk = float(standardized @ model["direction"] / np.sqrt(float(len(row))))
    predicted = prior @ model["transition"]
    variance = model["deviations"] ** 2
    likelihood = np.exp(-0.5 * (risk - model["means"]) ** 2 / variance) / np.sqrt(
        2.0 * np.pi * variance
    )
    posterior = predicted * likelihood
    total = float(posterior.sum())
    posterior = posterior / total if total > 0.0 else predicted
    expected = float(posterior @ model["rewards"])
    return expected, posterior


def _f054(
    market: pd.DataFrame,
    feature_panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> tuple[pd.Series, pd.Series]:
    lane_ids = ("F015", "F021", "F032")
    features, observations = _aligned_features(market, feature_panels, lane_ids)
    returns = market["close"].pct_change(fill_method=None)
    ar_order = int(parameters.get("ar_order", 1))
    columns = [returns.rename("return")]
    columns.extend(returns.shift(lag).rename(f"return_lag_{lag}") for lag in range(1, ar_order + 1))
    columns.extend(features[lane_id] for lane_id in lane_ids)
    state_features = pd.concat(columns, axis=1)
    x = state_features.to_numpy(dtype=float)
    forward_return = returns.shift(-1).to_numpy()
    result = np.full(len(market), np.nan, dtype=float)
    window = int(parameters.get("window", 756))
    cadence = str(parameters.get("refit", "monthly"))
    states = int(parameters.get("states", 2))
    probability = float(parameters.get("probability", 0.5))
    model: Mapping[str, np.ndarray] | None = None
    posterior: np.ndarray | None = None
    for index in range(len(market)):
        if index < window:
            continue
        if _refit_due(market["date"], index, cadence, model is not None):
            start = index - window
            train_x = x[start:index]
            train_y = forward_return[start:index]
            valid = np.isfinite(train_y) & np.isfinite(train_x).all(axis=1)
            if int(valid.sum()) == window:
                model = _fit_markov(train_x[valid], train_y[valid], states)
                posterior = model["prior"].copy()
        if model is None or posterior is None or not np.isfinite(x[index]).all():
            continue
        expected, posterior = _markov_update(model, x[index], posterior)
        result[index] = expected if float(posterior.max()) >= probability else 0.0
    return pd.Series(result, index=market.index), _max_observation(observations, market)


def _causal_zscore(frame: pd.DataFrame, window: int) -> pd.DataFrame:
    mean = frame.rolling(window, min_periods=window).mean()
    deviation = frame.rolling(window, min_periods=window).std(ddof=0).replace(0.0, np.nan)
    return (frame - mean) / deviation


def _cusum(values: pd.Series, penalty: float, reset: bool) -> pd.Series:
    output = np.full(len(values), np.nan)
    positive = 0.0
    negative = 0.0
    drift = penalty / 10.0
    for index, raw in enumerate(values.to_numpy(dtype=float)):
        if not np.isfinite(raw):
            continue
        positive = max(0.0, positive + raw - drift)
        negative = min(0.0, negative + raw + drift)
        score = positive + negative
        output[index] = np.tanh(score / max(penalty, 1e-9))
        if reset and max(positive, -negative) > penalty:
            positive = 0.0
            negative = 0.0
    return pd.Series(output, index=values.index)


def _page_hinkley(values: pd.Series, penalty: float, reset: bool) -> pd.Series:
    output = np.full(len(values), np.nan)
    count = 0
    mean = 0.0
    upper = lower = 0.0
    min_upper = max_lower = 0.0
    delta = penalty / 20.0
    for index, raw in enumerate(values.to_numpy(dtype=float)):
        if not np.isfinite(raw):
            continue
        count += 1
        mean += (raw - mean) / count
        upper += raw - mean - delta
        lower += raw - mean + delta
        min_upper = min(min_upper, upper)
        max_lower = max(max_lower, lower)
        upward = upper - min_upper
        downward = max_lower - lower
        output[index] = np.tanh((upward - downward) / max(penalty, 1e-9))
        if reset and max(upward, downward) > penalty:
            count = 0
            mean = upper = lower = min_upper = max_lower = 0.0
    return pd.Series(output, index=values.index)


def _segment_cost(prefix: np.ndarray, squares: np.ndarray, left: int, right: int) -> float:
    count = right - left
    if count <= 0:
        return 0.0
    total = prefix[right] - prefix[left]
    return float(squares[right] - squares[left] - total * total / count)


def _causal_pelt(values: pd.Series, window: int, penalty: float) -> pd.Series:
    output = np.full(len(values), np.nan)
    finite_positions = np.flatnonzero(np.isfinite(values.to_numpy(dtype=float)))
    if not len(finite_positions):
        return pd.Series(output, index=values.index)
    raw = values.iloc[finite_positions].to_numpy(dtype=float)
    prefix = np.concatenate(([0.0], np.cumsum(raw)))
    squares = np.concatenate(([0.0], np.cumsum(raw * raw)))
    objective = np.full(len(raw) + 1, np.inf)
    previous = np.zeros(len(raw) + 1, dtype=int)
    objective[0] = -penalty
    minimum_segment = max(4, min(20, window // 5))
    for right in range(1, len(raw) + 1):
        starts = range(max(0, right - window), max(0, right - minimum_segment) + 1)
        options = [
            (objective[left] + _segment_cost(prefix, squares, left, right) + penalty, left)
            for left in starts
            if np.isfinite(objective[left])
        ]
        if not options:
            objective[right] = _segment_cost(prefix, squares, 0, right)
            previous[right] = 0
            continue
        objective[right], previous[right] = min(options, key=lambda item: (item[0], item[1]))
        split = int(previous[right])
        prior_split = int(previous[split]) if split > 0 else 0
        if split > prior_split and right > split:
            left_mean = (prefix[split] - prefix[prior_split]) / (split - prior_split)
            right_mean = (prefix[right] - prefix[split]) / (right - split)
            improvement = max(
                0.0,
                _segment_cost(prefix, squares, prior_split, right)
                - _segment_cost(prefix, squares, prior_split, split)
                - _segment_cost(prefix, squares, split, right),
            )
            output[finite_positions[right - 1]] = np.sign(right_mean - left_mean) * np.tanh(
                improvement / max(penalty, 1e-9)
            )
        else:
            output[finite_positions[right - 1]] = 0.0
    return pd.Series(output, index=values.index)


def _f055(
    market: pd.DataFrame,
    feature_panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> tuple[pd.Series, pd.Series]:
    lane_ids = _FEATURE_SETS["diversified_3"]
    features, observations = _aligned_features(market, feature_panels, lane_ids)
    window = int(parameters.get("window", 252))
    oriented = features.copy()
    oriented["F021"] *= -1.0
    oriented["F032"] *= -1.0
    composite = _causal_zscore(oriented, window).mean(axis=1, skipna=False)
    kind = str(parameters.get("kind", "cusum"))
    penalty = float(parameters.get("penalty", 1.0))
    reset = bool(parameters.get("reset", True))
    if kind == "cusum":
        value = _cusum(composite, penalty, reset)
    elif kind == "page_hinkley":
        value = _page_hinkley(composite, penalty, reset)
    elif kind == "causal_pelt":
        value = _causal_pelt(composite, window, penalty)
    else:
        raise ModelFeatureEngineError(f"UNKNOWN_CHANGE_POINT_KIND:{kind}")
    return value, _max_observation(observations, market)


def _fit_glm(
    x: np.ndarray,
    y: np.ndarray,
    *,
    link: str,
    ridge: float,
) -> Mapping[str, np.ndarray]:
    standardized, location, scale = _standardize_fit(x)
    design = np.column_stack((np.ones(len(standardized)), standardized))
    binary = (y > 0.0).astype(float)

    def objective(beta: np.ndarray) -> tuple[float, np.ndarray]:
        linear = design @ beta
        if link == "logit":
            probability = expit(linear)
            loss = float(np.logaddexp(0.0, linear).sum() - binary @ linear)
            gradient_linear = probability - binary
        elif link == "probit":
            probability = np.clip(ndtr(linear), 1e-9, 1.0 - 1e-9)
            density = np.exp(-0.5 * linear * linear) / np.sqrt(2.0 * np.pi)
            loss = float(
                -(binary * np.log(probability) + (1.0 - binary) * np.log(1.0 - probability)).sum()
            )
            gradient_linear = (probability - binary) * density / (
                probability * (1.0 - probability)
            )
        else:
            raise ModelFeatureEngineError(f"UNKNOWN_GLM_LINK:{link}")
        loss += 0.5 * ridge * float(beta[1:] @ beta[1:])
        gradient = design.T @ gradient_linear
        gradient[1:] += ridge * beta[1:]
        return loss, gradient

    fitted = minimize(
        objective,
        np.zeros(design.shape[1]),
        method="L-BFGS-B",
        jac=True,
        options={"maxiter": 100, "ftol": 1e-10},
    )
    return {
        "location": location,
        "scale": scale,
        "coefficient": np.asarray(fitted.x),
        "link": np.array([0.0 if link == "logit" else 1.0]),
    }


def _predict_glm(model: Mapping[str, np.ndarray], row: np.ndarray) -> float:
    standardized = (row - model["location"]) / model["scale"]
    linear = float(np.r_[1.0, standardized] @ model["coefficient"])
    return float(expit(linear) if model["link"][0] == 0.0 else ndtr(linear))


def _f056(
    market: pd.DataFrame,
    feature_panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> tuple[pd.Series, pd.Series]:
    lane_ids = _feature_set(parameters)
    features, observations = _aligned_features(market, feature_panels, lane_ids)
    model_name = str(parameters.get("model", "logit"))
    if model_name not in {"logit", "probit"}:
        raise ModelFeatureEngineError(f"F056_UNKNOWN_MODEL:{model_name}")
    threshold = float(parameters.get("threshold", 0.5))
    ridge = float(parameters.get("ridge", 1.0))
    probability = _rolling_supervised(
        market,
        features,
        window=int(parameters.get("window", 756)),
        cadence=str(parameters.get("refit", "monthly")),
        fit=lambda x, y: _fit_glm(x, y, link=model_name, ridge=ridge),
        predict=_predict_glm,
    )
    return probability - threshold, _max_observation(observations, market)


def _fit_pls(x: np.ndarray, y: np.ndarray, components: int) -> Mapping[str, np.ndarray]:
    standardized, location, scale = _standardize_fit(x)
    centered_y = (y > 0.0).astype(float)
    y_mean = float(centered_y.mean())
    residual_x = standardized.copy()
    residual_y = centered_y - y_mean
    weights: list[np.ndarray] = []
    loadings: list[np.ndarray] = []
    responses: list[float] = []
    for _ in range(min(components, standardized.shape[1])):
        weight = residual_x.T @ residual_y
        norm = float(np.linalg.norm(weight))
        if norm <= 1e-12:
            break
        weight /= norm
        score = residual_x @ weight
        denominator = float(score @ score)
        if denominator <= 1e-12:
            break
        loading = residual_x.T @ score / denominator
        response = float(score @ residual_y / denominator)
        residual_x -= np.outer(score, loading)
        residual_y -= response * score
        weights.append(weight)
        loadings.append(loading)
        responses.append(response)
    if not weights:
        coefficient = np.zeros(standardized.shape[1])
    else:
        weight_matrix = np.column_stack(weights)
        loading_matrix = np.column_stack(loadings)
        coefficient = weight_matrix @ np.linalg.pinv(loading_matrix.T @ weight_matrix) @ np.asarray(responses)
    return {
        "location": location,
        "scale": scale,
        "coefficient": coefficient,
        "intercept": np.array([y_mean]),
    }


def _predict_pls(model: Mapping[str, np.ndarray], row: np.ndarray) -> float:
    standardized = (row - model["location"]) / model["scale"]
    return float(np.clip(model["intercept"][0] + standardized @ model["coefficient"], 0.0, 1.0))


def _gam_basis(x: np.ndarray, knots: np.ndarray) -> np.ndarray:
    columns = [x]
    for knot_index in range(knots.shape[0]):
        columns.append(np.maximum(0.0, x - knots[knot_index]))
    return np.column_stack(columns)


def _fit_gam(
    x: np.ndarray, y: np.ndarray, knots: int, ridge: float
) -> Mapping[str, np.ndarray]:
    standardized, location, scale = _standardize_fit(x)
    quantiles = np.linspace(0.0, 1.0, knots + 2)[1:-1]
    knot_values = np.quantile(standardized, quantiles, axis=0)
    basis = _gam_basis(standardized, knot_values)
    glm = _fit_glm(basis, y, link="logit", ridge=ridge)
    return {
        "location": location,
        "scale": scale,
        "knots": knot_values,
        "glm_location": glm["location"],
        "glm_scale": glm["scale"],
        "coefficient": glm["coefficient"],
        "link": glm["link"],
    }


def _predict_gam(model: Mapping[str, np.ndarray], row: np.ndarray) -> float:
    standardized = (row - model["location"]) / model["scale"]
    basis = _gam_basis(standardized.reshape(1, -1), model["knots"])[0]
    glm = {
        "location": model["glm_location"],
        "scale": model["glm_scale"],
        "coefficient": model["coefficient"],
        "link": model["link"],
    }
    return _predict_glm(glm, basis)


def _f057(
    market: pd.DataFrame,
    feature_panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> tuple[pd.Series, pd.Series]:
    lane_ids = _feature_set(parameters)
    features, observations = _aligned_features(market, feature_panels, lane_ids)
    model_name = str(parameters.get("model", "pls"))
    if model_name == "pls":
        components = int(parameters.get("components", 2))
        fit = lambda x, y: _fit_pls(x, y, components)
        predict = _predict_pls
    elif model_name == "gam":
        knots = int(parameters.get("knots", 3))
        ridge = float(parameters.get("ridge", 1.0))
        fit = lambda x, y: _fit_gam(x, y, knots, ridge)
        predict = _predict_gam
    else:
        raise ModelFeatureEngineError(f"F057_UNKNOWN_MODEL:{model_name}")
    probability = _rolling_supervised(
        market,
        features,
        window=int(parameters.get("window", 756)),
        cadence=str(parameters.get("refit", "monthly")),
        fit=fit,
        predict=predict,
    )
    return probability - float(parameters.get("threshold", 0.5)), _max_observation(
        observations, market
    )


def _best_split(
    x: np.ndarray, y: np.ndarray, weights: np.ndarray | None = None
) -> tuple[int, float, float]:
    sample_weights = np.ones(len(y)) if weights is None else weights
    best = (0, float(np.median(x[:, 0])), np.inf)
    for feature in range(x.shape[1]):
        thresholds = np.unique(np.quantile(x[:, feature], np.linspace(0.1, 0.9, 9)))
        for threshold in thresholds:
            left = x[:, feature] <= threshold
            if left.sum() < 5 or (~left).sum() < 5:
                continue
            loss = 0.0
            for mask in (left, ~left):
                group_weight = sample_weights[mask]
                group_y = y[mask]
                mean = float(np.average(group_y, weights=group_weight))
                loss += float(np.sum(group_weight * (group_y - mean) ** 2))
            candidate = (feature, float(threshold), loss)
            if candidate[2] < best[2] - 1e-12:
                best = candidate
    return best


def _fit_tree_node(x: np.ndarray, y: np.ndarray, depth: int) -> Mapping[str, Any]:
    if depth <= 0 or len(y) < 20 or np.unique(y > 0.0).size < 2:
        return {"value": float(np.mean(y > 0.0))}
    feature, threshold, loss = _best_split(x, (y > 0.0).astype(float))
    if not np.isfinite(loss):
        return {"value": float(np.mean(y > 0.0))}
    left = x[:, feature] <= threshold
    return {
        "feature": feature,
        "threshold": threshold,
        "left": _fit_tree_node(x[left], y[left], depth - 1),
        "right": _fit_tree_node(x[~left], y[~left], depth - 1),
    }


def _predict_tree_node(node: Mapping[str, Any], row: np.ndarray) -> float:
    if "value" in node:
        return float(node["value"])
    branch = "left" if row[int(node["feature"])] <= float(node["threshold"]) else "right"
    return _predict_tree_node(node[branch], row)


def _fit_tree(x: np.ndarray, y: np.ndarray, depth: int) -> Mapping[str, Any]:
    standardized, location, scale = _standardize_fit(x)
    return {
        "location": location,
        "scale": scale,
        "tree": _fit_tree_node(standardized, y, depth),
    }


def _predict_tree(model: Mapping[str, Any], row: np.ndarray) -> float:
    standardized = (row - model["location"]) / model["scale"]
    return _predict_tree_node(model["tree"], standardized)


def _fit_boosted_stumps(
    x: np.ndarray, y: np.ndarray, estimators: int, learning_rate: float
) -> Mapping[str, Any]:
    standardized, location, scale = _standardize_fit(x)
    labels = np.where(y > 0.0, 1.0, -1.0)
    weights = np.full(len(labels), 1.0 / len(labels))
    stumps: list[tuple[int, float, float, float]] = []
    for _ in range(estimators):
        feature, threshold, _ = _best_split(standardized, labels, weights)
        base = np.where(standardized[:, feature] > threshold, 1.0, -1.0)
        errors = []
        for polarity in (1.0, -1.0):
            prediction = polarity * base
            errors.append((float(weights[prediction != labels].sum()), polarity, prediction))
        error, polarity, prediction = min(errors, key=lambda item: (item[0], -item[1]))
        error = float(np.clip(error, 1e-9, 1.0 - 1e-9))
        if error >= 0.5:
            break
        alpha = learning_rate * 0.5 * np.log((1.0 - error) / error)
        weights *= np.exp(-alpha * labels * prediction)
        weights /= weights.sum()
        stumps.append((feature, threshold, polarity, float(alpha)))
    return {"location": location, "scale": scale, "stumps": stumps}


def _predict_boosted_stumps(model: Mapping[str, Any], row: np.ndarray) -> float:
    standardized = (row - model["location"]) / model["scale"]
    score = 0.0
    total = 0.0
    for feature, threshold, polarity, alpha in model["stumps"]:
        score += alpha * polarity * (1.0 if standardized[feature] > threshold else -1.0)
        total += abs(alpha)
    return float(expit(2.0 * score / total)) if total > 0.0 else 0.5


def _f058(
    market: pd.DataFrame,
    feature_panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> tuple[pd.Series, pd.Series]:
    lane_ids = _feature_set(parameters)
    features, observations = _aligned_features(market, feature_panels, lane_ids)
    model_name = str(parameters.get("model", "tree"))
    if model_name == "tree":
        depth = int(parameters.get("depth", 2))
        fit = lambda x, y: _fit_tree(x, y, depth)
        predict = _predict_tree
    elif model_name == "boosted_stumps":
        estimators = int(parameters.get("estimators", 25))
        learning_rate = float(parameters.get("learning_rate", 0.5))
        fit = lambda x, y: _fit_boosted_stumps(x, y, estimators, learning_rate)
        predict = _predict_boosted_stumps
    else:
        raise ModelFeatureEngineError(f"F058_UNKNOWN_MODEL:{model_name}")
    probability = _rolling_supervised(
        market,
        features,
        window=int(parameters.get("window", 756)),
        cadence=str(parameters.get("refit", "quarterly")),
        fit=fit,
        predict=predict,
    )
    return probability - float(parameters.get("threshold", 0.5)), _max_observation(
        observations, market
    )


def _symbolic_candidates(
    standardized: np.ndarray,
    threshold_quantile: float,
    depth: int,
    logic: str,
) -> list[tuple[tuple[int, ...], tuple[float, ...], str, np.ndarray, np.ndarray]]:
    thresholds = np.quantile(standardized, threshold_quantile, axis=0)
    candidates: list[
        tuple[tuple[int, ...], tuple[float, ...], str, np.ndarray, np.ndarray]
    ] = []
    width = 1 if logic in {"identity", "not"} else max(2, depth)
    width = min(width, standardized.shape[1])
    for selected in combinations(range(standardized.shape[1]), width):
        for directions in product((-1.0, 1.0), repeat=width):
            literals = np.column_stack(
                [
                    directions[position]
                    * (standardized[:, feature] - thresholds[feature])
                    > 0.0
                    for position, feature in enumerate(selected)
                ]
            )
            if logic == "identity":
                prediction = literals[:, 0]
            elif logic == "not":
                prediction = ~literals[:, 0]
            elif logic == "and":
                prediction = np.asarray(literals.all(axis=1), dtype=bool)
            elif logic == "or":
                prediction = np.asarray(literals.any(axis=1), dtype=bool)
            elif logic == "majority":
                prediction = literals.sum(axis=1) > width / 2.0
            elif logic == "score":
                prediction = literals.mean(axis=1) >= 0.5
            else:
                raise ModelFeatureEngineError(f"F059_UNKNOWN_LOGIC:{logic}")
            candidates.append((selected, directions, logic, thresholds, prediction))
    return candidates


def _fit_symbolic(
    x: np.ndarray,
    y: np.ndarray,
    *,
    threshold_quantile: float,
    depth: int,
    logic: str,
) -> Mapping[str, Any]:
    standardized, location, scale = _standardize_fit(x)
    target = y > 0.0
    candidates = _symbolic_candidates(
        standardized, threshold_quantile, depth, logic
    )
    best = max(
        candidates,
        key=lambda item: (
            float((item[4] == target).mean()),
            tuple(-value for value in item[0]),
            item[1],
        ),
    )
    return {
        "location": location,
        "scale": scale,
        "selected": best[0],
        "directions": best[1],
        "logic": best[2],
        "thresholds": best[3],
    }


def _predict_symbolic(model: Mapping[str, Any], row: np.ndarray) -> float:
    standardized = (row - model["location"]) / model["scale"]
    literals = np.array(
        [
            direction
            * (standardized[feature] - model["thresholds"][feature])
            > 0.0
            for feature, direction in zip(
                model["selected"], model["directions"], strict=True
            )
        ]
    )
    logic = model["logic"]
    if logic == "identity":
        state = bool(literals[0])
    elif logic == "not":
        state = not bool(literals[0])
    elif logic == "and":
        state = bool(literals.all())
    elif logic == "or":
        state = bool(literals.any())
    elif logic == "majority":
        state = bool(literals.sum() > len(literals) / 2.0)
    else:
        state = bool(literals.mean() >= 0.5)
    return 1.0 if state else -1.0


def _f059(
    market: pd.DataFrame,
    feature_panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> tuple[pd.Series, pd.Series]:
    lane_ids = _feature_set(parameters)
    features, observations = _aligned_features(market, feature_panels, lane_ids)
    threshold_quantile = float(parameters.get("threshold_quantile", 0.5))
    depth = int(parameters.get("depth", 2))
    logic = str(parameters.get("logic", "and"))
    value = _rolling_supervised(
        market,
        features,
        window=int(parameters.get("window", 756)),
        cadence=str(parameters.get("refit", "quarterly")),
        fit=lambda x, y: _fit_symbolic(
            x,
            y,
            threshold_quantile=threshold_quantile,
            depth=depth,
            logic=logic,
        ),
        predict=_predict_symbolic,
    )
    return value, _max_observation(observations, market)


def _hold_signal(desired: pd.Series, hold: int) -> pd.Series:
    if hold < 1:
        raise ModelFeatureEngineError(f"INVALID_CONTROL_HOLD:{hold}")
    rebalance = pd.Series(False, index=desired.index)
    rebalance.iloc[::hold] = True
    return desired.where(rebalance).ffill()


def _f060(market: pd.DataFrame, parameters: Mapping[str, Any]) -> tuple[pd.Series, pd.Series]:
    close = market["close"]
    returns = close.pct_change(fill_method=None)
    rule = str(parameters.get("rule", "always_long"))
    hold = int(parameters.get("hold", 1))
    if rule == "always_long":
        desired = pd.Series(1.0, index=market.index)
    elif rule == "always_short":
        desired = pd.Series(-1.0, index=market.index)
    elif rule == "sma200":
        average = close.rolling(200, min_periods=200).mean()
        desired = pd.Series(np.where(close >= average, 1.0, -1.0), index=market.index).mask(
            average.isna()
        )
    elif rule == "momentum252":
        momentum = close.pct_change(252, fill_method=None)
        desired = np.sign(momentum).replace(0.0, 1.0)
    elif rule == "rev2":
        desired = -np.sign(close.pct_change(2, fill_method=None)).replace(0.0, 1.0)
    elif rule == "inverse":
        desired = -np.sign(returns).replace(0.0, 1.0)
    elif rule == "block_placebo":
        seed = int(parameters.get("seed", 17))
        blocks = np.arange(len(market), dtype=np.int64) // hold
        state = (blocks * 1103515245 + seed * 12345 + 12345) & 0x7FFFFFFF
        desired = pd.Series(np.where(state % 2 == 0, 1.0, -1.0), index=market.index)
    else:
        raise ModelFeatureEngineError(f"UNKNOWN_CONTROL_RULE:{rule}")
    value = desired if rule == "block_placebo" else _hold_signal(desired, hold)
    return value, market["observed_at"]


def evaluate_model_lane(
    lane_id: str,
    market_frame: pd.DataFrame,
    feature_panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    """Evaluate one exact F051-F060 formula using only information known at date t."""

    market = _validated_market(market_frame)
    if lane_id == "F051":
        value, observed = _f051(market, feature_panels, parameters)
    elif lane_id == "F052":
        value, observed = _f052(market, feature_panels, parameters)
    elif lane_id == "F053":
        value, observed = _f053(market, feature_panels, parameters)
    elif lane_id == "F054":
        value, observed = _f054(market, feature_panels, parameters)
    elif lane_id == "F055":
        value, observed = _f055(market, feature_panels, parameters)
    elif lane_id == "F056":
        value, observed = _f056(market, feature_panels, parameters)
    elif lane_id == "F057":
        value, observed = _f057(market, feature_panels, parameters)
    elif lane_id == "F058":
        value, observed = _f058(market, feature_panels, parameters)
    elif lane_id == "F059":
        value, observed = _f059(market, feature_panels, parameters)
    elif lane_id == "F060":
        value, observed = _f060(market, parameters)
    else:
        raise ModelFeatureEngineError(f"MODEL_LANE_NOT_IMPLEMENTED:{lane_id}")
    return _output(market, value, observed)


__all__ = ["ModelFeatureEngineError", "evaluate_model_lane"]
