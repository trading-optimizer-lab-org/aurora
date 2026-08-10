"""Causal, bounded predictive-model kernels for SP500 lanes F141-F150."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

import numpy as np
import pandas as pd
from scipy.special import expit


class PredictiveFeatureEngineError(ValueError):
    """Raised when a predictive model violates its frozen train-only contract."""


_TRAIN_END = pd.Timestamp("2010-12-31")
_EPSILON = np.finfo(float).eps
_APPROVED_FEATURES = ("F003", "F015", "F021", "F032", "F039")
_TEMPORAL_FEATURES = ("F003", "F015", "F021", "F032")


def _validated_panel(
    name: str, frame: pd.DataFrame, value_columns: Sequence[str]
) -> pd.DataFrame:
    required = {"date", "observed_at", "available_at", *value_columns}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise PredictiveFeatureEngineError(
            f"PANEL_COLUMNS_MISSING:{name}:{','.join(missing)}"
        )
    panel = frame.loc[:, list(required)].copy()
    for column in ("date", "observed_at", "available_at"):
        panel[column] = (
            pd.to_datetime(panel[column], errors="coerce")
            .dt.normalize()
            .astype("datetime64[ns]")
        )
    if panel[["date", "observed_at", "available_at"]].isna().any().any():
        raise PredictiveFeatureEngineError(f"INVALID_PANEL_DATE:{name}")
    if panel["date"].gt(_TRAIN_END).any() or panel["available_at"].gt(
        _TRAIN_END
    ).any():
        raise PredictiveFeatureEngineError(f"NON_TRAIN_PANEL:{name}")
    if panel["observed_at"].gt(panel["available_at"]).any() or panel[
        "available_at"
    ].gt(panel["date"]).any():
        raise PredictiveFeatureEngineError(f"NON_CAUSAL_PANEL:{name}")
    if panel["date"].duplicated().any() or not panel["date"].is_monotonic_increasing:
        raise PredictiveFeatureEngineError(f"PANEL_DATES_NOT_ORDERED:{name}")
    for column in value_columns:
        panel[column] = pd.to_numeric(panel[column], errors="coerce").replace(
            [np.inf, -np.inf], np.nan
        )
    if panel[list(value_columns)].isna().any().any():
        raise PredictiveFeatureEngineError(f"INVALID_PANEL_VALUE:{name}")
    return panel.sort_values("date", kind="mergesort").reset_index(drop=True)


def _validated_feature(lane: str, frame: pd.DataFrame) -> pd.DataFrame:
    required = {"date", "observed_at", "available_at", "value"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise PredictiveFeatureEngineError(
            f"FEATURE_COLUMNS_MISSING:{lane}:{','.join(missing)}"
        )
    feature = frame.loc[:, list(required)].copy()
    for column in ("date", "observed_at", "available_at"):
        feature[column] = (
            pd.to_datetime(feature[column], errors="coerce")
            .dt.normalize()
            .astype("datetime64[ns]")
        )
    if feature[["date", "observed_at", "available_at"]].isna().any().any():
        raise PredictiveFeatureEngineError(f"INVALID_FEATURE_DATE:{lane}")
    if feature["date"].gt(_TRAIN_END).any() or feature["available_at"].gt(
        _TRAIN_END
    ).any():
        raise PredictiveFeatureEngineError(f"NON_TRAIN_FEATURE:{lane}")
    if feature["observed_at"].gt(feature["available_at"]).any() or feature[
        "available_at"
    ].gt(feature["date"]).any():
        raise PredictiveFeatureEngineError(f"NON_CAUSAL_FEATURE:{lane}")
    if feature["date"].duplicated().any() or not feature[
        "date"
    ].is_monotonic_increasing:
        raise PredictiveFeatureEngineError(f"FEATURE_DATES_NOT_ORDERED:{lane}")
    feature["value"] = pd.to_numeric(feature["value"], errors="coerce").replace(
        [np.inf, -np.inf], np.nan
    )
    return feature.sort_values("date", kind="mergesort").reset_index(drop=True)


def _spy(panels: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    if "spy" not in panels:
        raise PredictiveFeatureEngineError("PANEL_MISSING:spy")
    return _validated_panel("spy", panels["spy"], ("close", "volume"))


def _asof_panel(
    master: pd.DataFrame,
    name: str,
    panel: pd.DataFrame,
    value_columns: Sequence[str],
) -> tuple[pd.DataFrame, pd.Series]:
    validated = _validated_panel(name, panel, value_columns)
    right = validated.loc[
        :, ["available_at", "observed_at", *value_columns]
    ].rename(columns={"observed_at": "source_observed_at"})
    aligned = pd.merge_asof(
        master[["date"]],
        right.sort_values("available_at"),
        left_on="date",
        right_on="available_at",
        direction="backward",
        allow_exact_matches=True,
    )
    if aligned[list(value_columns)].isna().any().any():
        raise PredictiveFeatureEngineError(f"PANEL_DOES_NOT_COVER_MASTER:{name}")
    return aligned.loc[:, list(value_columns)], pd.to_datetime(
        aligned["source_observed_at"]
    )


def _aligned_features(
    market: pd.DataFrame,
    feature_panels: Mapping[str, pd.DataFrame],
    lane_ids: Sequence[str] = _APPROVED_FEATURES,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    missing = sorted(set(lane_ids) - set(feature_panels))
    if missing:
        raise PredictiveFeatureEngineError(
            f"APPROVED_FEATURES_MISSING:{','.join(missing)}"
        )
    values: dict[str, pd.Series] = {}
    observations: dict[str, pd.Series] = {}
    for lane in lane_ids:
        feature = _validated_feature(lane, feature_panels[lane])
        usable = feature.loc[feature["value"].notna()].copy()
        if usable.empty:
            values[lane] = pd.Series(np.nan, index=market.index, dtype=float)
            observations[lane] = pd.Series(pd.NaT, index=market.index)
            continue
        right = usable[["available_at", "observed_at", "value"]].rename(
            columns={"observed_at": "source_observed_at"}
        )
        aligned = pd.merge_asof(
            market[["date"]],
            right.sort_values("available_at"),
            left_on="date",
            right_on="available_at",
            direction="backward",
            allow_exact_matches=True,
        )
        values[lane] = pd.to_numeric(aligned["value"], errors="coerce")
        observations[lane] = pd.to_datetime(aligned["source_observed_at"])
    return pd.DataFrame(values), pd.DataFrame(observations)


def _max_observed(
    market: pd.DataFrame, observations: pd.DataFrame | Sequence[pd.Series] | None
) -> pd.Series:
    columns = [market["observed_at"].reset_index(drop=True)]
    if isinstance(observations, pd.DataFrame):
        columns.extend(
            pd.to_datetime(observations[column]).reset_index(drop=True)
            for column in observations
        )
    elif observations:
        columns.extend(pd.to_datetime(item).reset_index(drop=True) for item in observations)
    return pd.concat(columns, axis=1).max(axis=1)


def _output(
    market: pd.DataFrame, value: pd.Series | np.ndarray, observed_at: pd.Series
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": market["date"],
            "observed_at": pd.to_datetime(observed_at),
            "available_at": market["date"],
            "value": pd.to_numeric(
                pd.Series(value, index=market.index), errors="coerce"
            ).replace([np.inf, -np.inf], np.nan),
        }
    )


def _positive_int(parameters: Mapping[str, Any], name: str, default: int) -> int:
    value = int(parameters.get(name, default))
    if value < 1:
        raise PredictiveFeatureEngineError(f"INVALID_POSITIVE_PARAMETER:{name}:{value}")
    return value


def _bounded_float(
    parameters: Mapping[str, Any],
    name: str,
    default: float,
    *,
    lower: float,
    upper: float,
    lower_open: bool = False,
) -> float:
    value = float(parameters.get(name, default))
    lower_ok = value > lower if lower_open else value >= lower
    if not np.isfinite(value) or not lower_ok or value > upper:
        raise PredictiveFeatureEngineError(f"INVALID_BOUNDED_PARAMETER:{name}:{value}")
    return value


def _refit_due(dates: pd.Series, index: int, cadence: str, fitted: bool) -> bool:
    if not fitted or cadence == "daily":
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
    raise PredictiveFeatureEngineError(f"UNKNOWN_REFIT:{cadence}")


def _standardize(x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    location = np.mean(x, axis=0)
    scale = np.std(x, axis=0, ddof=0)
    scale = np.where(scale > 1e-12, scale, 1.0)
    return (x - location) / scale, location, scale


def _ridge(design: np.ndarray, target: np.ndarray, ridge: float) -> np.ndarray:
    penalty = np.eye(design.shape[1]) * ridge
    penalty[0, 0] = 0.0
    return np.linalg.pinv(design.T @ design + penalty) @ design.T @ target


def _lags(values: pd.Series | np.ndarray, count: int) -> np.ndarray:
    series = pd.Series(values)
    return np.column_stack(
        [series.shift(lag).to_numpy(dtype=float) for lag in range(count)]
    )


def _returns(market: pd.DataFrame) -> pd.Series:
    return np.log(market["close"]).diff()


def _rolling_model(
    market: pd.DataFrame,
    predictors: np.ndarray,
    targets: np.ndarray,
    *,
    window: int,
    cadence: str,
    fit: Callable[[np.ndarray, np.ndarray], Any],
    predict: Callable[[Any, np.ndarray], Mapping[str, float]],
    statistic: str,
    minimum_valid: int | None = None,
) -> pd.Series:
    output = np.full(len(market), np.nan)
    model: Any = None
    minimum = window if minimum_valid is None else minimum_valid
    for index in range(len(market)):
        if index < window:
            continue
        if _refit_due(market["date"], index, cadence, model is not None):
            start = max(0, index - window)
            x_train = predictors[start:index]
            y_train = targets[start:index]
            target_valid = (
                np.isfinite(y_train).all(axis=1)
                if y_train.ndim > 1
                else np.isfinite(y_train)
            )
            valid = np.isfinite(x_train).all(axis=1) & target_valid
            if int(valid.sum()) >= minimum:
                model = fit(x_train[valid], y_train[valid])
        if model is None or not np.isfinite(predictors[index]).all():
            continue
        statistics = predict(model, predictors[index])
        if statistic not in statistics:
            raise PredictiveFeatureEngineError(
                f"UNKNOWN_MODEL_STATISTIC:{statistic}"
            )
        output[index] = float(statistics[statistic])
    return pd.Series(output, index=market.index)


def _fit_arma(
    x: np.ndarray, y: np.ndarray, *, ma_order: int, ridge: float
) -> Mapping[str, Any]:
    standardized, location, scale = _standardize(x)
    design = np.column_stack((np.ones(len(x)), standardized))
    coefficient = _ridge(design, y, ridge)
    residual = y - design @ coefficient
    if ma_order:
        residual_lags = _lags(residual, ma_order + 1)[:, 1:]
        valid = np.isfinite(residual_lags).all(axis=1)
        augmented = np.column_stack((design[valid], residual_lags[valid]))
        coefficient = _ridge(augmented, y[valid], ridge)
        fitted = augmented @ coefficient
        residual = y[valid] - fitted
        residual_tail = residual[-ma_order:]
    else:
        fitted = design @ coefficient
        residual_tail = np.empty(0)
    variance = max(float(np.var(y, ddof=0)), _EPSILON)
    quality = 1.0 - float(np.mean((y[-len(fitted) :] - fitted) ** 2)) / variance
    return {
        "location": location,
        "scale": scale,
        "coefficient": coefficient,
        "residual_tail": residual_tail,
        "target_scale": np.array([np.sqrt(variance)]),
        "quality": np.array([quality]),
    }


def _predict_arma(model: Mapping[str, Any], row: np.ndarray) -> Mapping[str, float]:
    standardized = (row - model["location"]) / model["scale"]
    design = np.r_[1.0, standardized, model["residual_tail"][::-1]]
    forecast = float(design @ model["coefficient"])
    target_scale = float(model["target_scale"][0])
    innovation = (
        float(model["residual_tail"][-1]) / target_scale
        if len(model["residual_tail"])
        else 0.0
    )
    return {
        "forecast": forecast,
        "forecast_z": forecast / target_scale,
        "innovation": innovation,
        "fit_quality": float(model["quality"][0]),
    }


def _f141(market: pd.DataFrame, parameters: Mapping[str, Any]) -> pd.Series:
    kind = str(parameters.get("kind", "arma"))
    if kind not in {"ar", "arma", "distributed_regression"}:
        raise PredictiveFeatureEngineError(f"F141_UNKNOWN_KIND:{kind}")
    ar_order = _positive_int(parameters, "ar_order", 2)
    ma_order = int(parameters.get("ma_order", 1)) if kind == "arma" else 0
    if ma_order < 0 or ma_order > 5:
        raise PredictiveFeatureEngineError("F141_INVALID_MA_ORDER")
    predictors = [_lags(_returns(market), ar_order)]
    if kind == "distributed_regression":
        volume_lags = _positive_int(parameters, "volume_lags", 2)
        volume_change = np.log(market["volume"]).diff()
        predictors.append(_lags(volume_change, volume_lags))
    x = np.column_stack(predictors)
    target = _returns(market).shift(-1).to_numpy(dtype=float)
    ridge = _bounded_float(
        parameters, "ridge", 0.1, lower=0.0, upper=1000.0
    )
    return _rolling_model(
        market,
        x,
        target,
        window=_positive_int(parameters, "window", 252),
        cadence=str(parameters.get("refit", "quarterly")),
        fit=lambda train_x, train_y: _fit_arma(
            train_x, train_y, ma_order=ma_order, ridge=ridge
        ),
        predict=_predict_arma,
        statistic=str(parameters.get("statistic", "forecast_z")),
        minimum_valid=max(30, _positive_int(parameters, "window", 252) - ar_order),
    )


def _fit_var(
    x: np.ndarray,
    y: np.ndarray,
    *,
    ridge: float,
    error_correction_column: int | None,
) -> Mapping[str, Any]:
    standardized, location, scale = _standardize(x)
    design = np.column_stack((np.ones(len(x)), standardized))
    coefficient = _ridge(design, y, ridge)
    fitted = design @ coefficient
    residual_scale = np.std(y - fitted, axis=0, ddof=0)
    residual_scale = np.where(residual_scale > 1e-12, residual_scale, 1.0)
    return {
        "location": location,
        "scale": scale,
        "coefficient": coefficient,
        "residual_scale": residual_scale,
        "error_column": error_correction_column,
    }


def _fit_vecm(x: np.ndarray, y: np.ndarray, *, ridge: float) -> Mapping[str, Any]:
    base = x[:, :-3]
    levels = x[:, -3:]
    cointegration_design = np.column_stack((np.ones(len(levels)), levels[:, 1:]))
    cointegration = np.linalg.pinv(
        cointegration_design.T @ cointegration_design
    ) @ cointegration_design.T @ levels[:, 0]
    error = levels[:, 0] - cointegration_design @ cointegration
    augmented = np.column_stack((base, error))
    model = dict(
        _fit_var(
            augmented,
            y,
            ridge=ridge,
            error_correction_column=augmented.shape[1] - 1,
        )
    )
    model["cointegration"] = cointegration
    return model


def _predict_var(model: Mapping[str, Any], row: np.ndarray) -> Mapping[str, float]:
    standardized = (row - model["location"]) / model["scale"]
    forecast = np.r_[1.0, standardized] @ model["coefficient"]
    return_forecast = float(forecast[0])
    scale = float(model["residual_scale"][0])
    error_column = model["error_column"]
    error = float(standardized[error_column]) if error_column is not None else 0.0
    common = float(np.mean(standardized[: min(3, len(standardized))]))
    return {
        "return_forecast": return_forecast,
        "forecast_z": return_forecast / scale,
        "common_state": common,
        "error_correction": error,
    }


def _predict_vecm(model: Mapping[str, Any], row: np.ndarray) -> Mapping[str, float]:
    base = row[:-3]
    levels = row[-3:]
    error = float(levels[0] - np.r_[1.0, levels[1:]] @ model["cointegration"])
    return _predict_var(model, np.r_[base, error])


def _f142(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> tuple[pd.Series, pd.Series]:
    if "cboe" not in panels:
        raise PredictiveFeatureEngineError("PANEL_MISSING:cboe")
    cboe, cboe_observed = _asof_panel(
        market, "cboe", panels["cboe"], ("vix_close",)
    )
    variables = pd.DataFrame(
        {
            "return": _returns(market),
            "volume_change": np.log(market["volume"]).diff(),
            "vix_change": np.log(cboe["vix_close"]).diff(),
        }
    )
    lags = _positive_int(parameters, "lags", 2)
    kind = str(parameters.get("kind", "var"))
    if kind not in {"var", "vecm"}:
        raise PredictiveFeatureEngineError(f"F142_UNKNOWN_KIND:{kind}")
    predictors = [_lags(variables[column], lags) for column in variables]
    if kind == "vecm":
        levels = np.column_stack(
            (
                np.log(market["close"]),
                np.log(market["volume"]),
                np.log(cboe["vix_close"]),
            )
        )
        predictors.append(levels)
    x = np.column_stack(predictors)
    target = variables.shift(-1).to_numpy(dtype=float)
    ridge = _bounded_float(
        parameters, "ridge", 0.1, lower=0.0, upper=1000.0
    )
    window = _positive_int(parameters, "window", 252)
    value = _rolling_model(
        market,
        x,
        target,
        window=window,
        cadence=str(parameters.get("refit", "quarterly")),
        fit=(
            (lambda train_x, train_y: _fit_vecm(train_x, train_y, ridge=ridge))
            if kind == "vecm"
            else (
                lambda train_x, train_y: _fit_var(
                    train_x,
                    train_y,
                    ridge=ridge,
                    error_correction_column=None,
                )
            )
        ),
        predict=_predict_vecm if kind == "vecm" else _predict_var,
        statistic=str(parameters.get("statistic", "forecast_z")),
        minimum_valid=max(30, window - lags),
    )
    return value, cboe_observed


@dataclass(frozen=True)
class _FactorModel:
    location: np.ndarray
    scale: np.ndarray
    loadings: np.ndarray
    explained: np.ndarray
    orientation: np.ndarray


def _fit_factor(
    x: np.ndarray,
    returns: np.ndarray,
    *,
    components: int,
    sign_rule: str,
) -> _FactorModel:
    standardized, location, scale = _standardize(x)
    _, singular, right = np.linalg.svd(standardized, full_matrices=False)
    loadings = right[:components].T
    scores = standardized @ loadings
    orientation = np.ones(components)
    for component in range(components):
        if sign_rule == "return_correlation":
            correlation = np.corrcoef(scores[:, component], returns)[0, 1]
            orientation[component] = 1.0 if not np.isfinite(correlation) or correlation >= 0 else -1.0
        elif sign_rule == "trend_anchor":
            orientation[component] = 1.0 if loadings[0, component] >= 0 else -1.0
        else:
            raise PredictiveFeatureEngineError(f"F143_UNKNOWN_SIGN_RULE:{sign_rule}")
    energy = singular * singular
    explained = energy[:components] / max(float(energy.sum()), _EPSILON)
    return _FactorModel(location, scale, loadings, explained, orientation)


def _factor_statistics(model: _FactorModel, row: np.ndarray) -> Mapping[str, float]:
    standardized = (row - model.location) / model.scale
    scores = (standardized @ model.loadings) * model.orientation
    reconstruction = (scores * model.orientation) @ model.loadings.T
    residual = standardized - reconstruction
    common_direction = float(np.mean(np.sign(reconstruction)))
    return {
        "factor_score": float(scores @ np.sqrt(model.explained) / np.sqrt(len(scores))),
        "explained_share": float(model.explained.sum()),
        "common_direction": common_direction,
        "idiosyncratic_dispersion": float(np.sqrt(np.mean(residual * residual))),
    }


def _f143(
    market: pd.DataFrame,
    features: pd.DataFrame,
    parameters: Mapping[str, Any],
) -> pd.Series:
    components = _positive_int(parameters, "components", 2)
    if components > features.shape[1]:
        raise PredictiveFeatureEngineError("F143_TOO_MANY_COMPONENTS")
    x = features.to_numpy(dtype=float)
    known_return = _returns(market).to_numpy(dtype=float)
    output = np.full(len(market), np.nan)
    model: _FactorModel | None = None
    window = _positive_int(parameters, "window", 252)
    cadence = str(parameters.get("refit", "quarterly"))
    statistic = str(parameters.get("statistic", "factor_score"))
    for index in range(len(market)):
        if index < window:
            continue
        if _refit_due(market["date"], index, cadence, model is not None):
            start = index - window
            train_x = x[start:index]
            train_r = known_return[start:index]
            valid = np.isfinite(train_x).all(axis=1) & np.isfinite(train_r)
            if int(valid.sum()) >= max(30, window - 1):
                model = _fit_factor(
                    train_x[valid],
                    train_r[valid],
                    components=components,
                    sign_rule=str(parameters.get("sign_rule", "return_correlation")),
                )
        if model is not None and np.isfinite(x[index]).all():
            statistics = _factor_statistics(model, x[index])
            if statistic not in statistics:
                raise PredictiveFeatureEngineError(f"F143_UNKNOWN_STATISTIC:{statistic}")
            output[index] = statistics[statistic]
    return pd.Series(output, index=market.index)


def _fit_quantile(
    x: np.ndarray, y: np.ndarray, quantile: float, ridge: float
) -> Mapping[str, np.ndarray]:
    standardized, location, scale = _standardize(x)
    design = np.column_stack((np.ones(len(x)), standardized))
    coefficient = _ridge(design, y, ridge)
    penalty = np.eye(design.shape[1]) * ridge
    penalty[0, 0] = 0.0
    for _ in range(40):
        residual = y - design @ coefficient
        asymmetry = np.where(residual >= 0.0, quantile, 1.0 - quantile)
        weights = asymmetry / np.maximum(np.abs(residual), 1e-6)
        weighted = design * weights[:, None]
        updated = np.linalg.pinv(design.T @ weighted + penalty) @ weighted.T @ y
        if np.max(np.abs(updated - coefficient)) < 1e-9:
            coefficient = updated
            break
        coefficient = updated
    return {"location": location, "scale": scale, "coefficient": coefficient}


def _predict_quantile(model: Mapping[str, np.ndarray], row: np.ndarray) -> float:
    standardized = (row - model["location"]) / model["scale"]
    return float(np.r_[1.0, standardized] @ model["coefficient"])


def _fit_quantile_bundle(
    x: np.ndarray,
    y: np.ndarray,
    *,
    tail: float,
    forecast_quantile: float,
    ridge: float,
) -> Mapping[str, Any]:
    quantiles = tuple(sorted({tail, 0.5, 1.0 - tail, forecast_quantile}))
    models = {
        quantile: _fit_quantile(x, y, quantile, ridge) for quantile in quantiles
    }
    return {
        "models": models,
        "tail": tail,
        "forecast_quantile": forecast_quantile,
        "target_scale": max(float(np.std(y, ddof=0)), _EPSILON),
    }


def _quantile_statistics(
    model: Mapping[str, Any], row: np.ndarray
) -> Mapping[str, float]:
    forecasts = {
        quantile: _predict_quantile(fitted, row)
        for quantile, fitted in model["models"].items()
    }
    tail = float(model["tail"])
    low = forecasts[tail]
    median = forecasts[0.5]
    high = forecasts[1.0 - tail]
    ordered_values = np.maximum.accumulate([low, median, high])
    low, median, high = (float(value) for value in ordered_values)
    if 0.0 <= low:
        cdf_zero = 0.0
    elif 0.0 >= high:
        cdf_zero = 1.0
    elif 0.0 <= median:
        cdf_zero = tail + (0.5 - tail) * (0.0 - low) / max(median - low, _EPSILON)
    else:
        cdf_zero = 0.5 + (0.5 - tail) * (0.0 - median) / max(high - median, _EPSILON)
    scale = float(model["target_scale"])
    return {
        "quantile_forecast": forecasts[float(model["forecast_quantile"])] / scale,
        "tail_probability": 0.5 - float(np.clip(cdf_zero, 0.0, 1.0)),
        "interquantile_range": (high - low) / scale,
        "median_skew": (high + low - 2.0 * median) / scale,
    }


def _f144(market: pd.DataFrame, parameters: Mapping[str, Any]) -> pd.Series:
    lags = _positive_int(parameters, "lags", 5)
    x = _lags(_returns(market), lags)
    target = _returns(market).shift(-1).to_numpy(dtype=float)
    tail = _bounded_float(
        parameters, "tail_quantile", 0.1, lower=0.01, upper=0.25
    )
    forecast_quantile = _bounded_float(
        parameters, "forecast_quantile", 0.5, lower=0.05, upper=0.95
    )
    ridge = _bounded_float(
        parameters, "ridge", 0.1, lower=0.0, upper=1000.0
    )
    window = _positive_int(parameters, "window", 252)
    return _rolling_model(
        market,
        x,
        target,
        window=window,
        cadence=str(parameters.get("refit", "quarterly")),
        fit=lambda train_x, train_y: _fit_quantile_bundle(
            train_x,
            train_y,
            tail=tail,
            forecast_quantile=forecast_quantile,
            ridge=ridge,
        ),
        predict=_quantile_statistics,
        statistic=str(parameters.get("statistic", "median_skew")),
        minimum_valid=max(30, window - lags),
    )


def _kernel(
    left: np.ndarray,
    right: np.ndarray,
    *,
    kind: str,
    gamma: float,
    degree: int,
) -> np.ndarray:
    if kind == "linear":
        return left @ right.T
    if kind == "polynomial":
        return np.power(1.0 + gamma * (left @ right.T), degree)
    if kind == "rbf":
        distance = (
            np.sum(left * left, axis=1)[:, None]
            + np.sum(right * right, axis=1)[None, :]
            - 2.0 * (left @ right.T)
        )
        return np.exp(-gamma * np.maximum(distance, 0.0))
    raise PredictiveFeatureEngineError(f"F145_UNKNOWN_KIND:{kind}")


def _fit_lssvm(
    x: np.ndarray,
    y: np.ndarray,
    *,
    kind: str,
    support_vectors: int,
    gamma: float,
    degree: int,
    ridge: float,
) -> Mapping[str, Any]:
    standardized, location, scale = _standardize(x)
    count = min(support_vectors, len(x))
    indices = np.linspace(0, len(x) - 1, count).round().astype(int)
    support = standardized[indices]
    target = y[indices]
    target_mean = float(np.mean(target))
    target_scale = max(float(np.std(y, ddof=0)), _EPSILON)
    kernel = _kernel(support, support, kind=kind, gamma=gamma, degree=degree)
    alpha = np.linalg.pinv(kernel + np.eye(count) * ridge) @ (target - target_mean)
    return {
        "location": location,
        "scale": scale,
        "support": support,
        "alpha": alpha,
        "intercept": target_mean,
        "target_scale": target_scale,
        "kind": kind,
        "gamma": gamma,
        "degree": degree,
    }


def _lssvm_statistics(model: Mapping[str, Any], row: np.ndarray) -> Mapping[str, float]:
    standardized = ((row - model["location"]) / model["scale"]).reshape(1, -1)
    similarities = _kernel(
        standardized,
        model["support"],
        kind=model["kind"],
        gamma=float(model["gamma"]),
        degree=int(model["degree"]),
    )[0]
    contributions = similarities * model["alpha"]
    forecast = float(model["intercept"] + contributions.sum())
    scale = float(model["target_scale"])
    alignment = float(contributions.sum() / max(np.abs(contributions).sum(), _EPSILON))
    return {
        "forecast_z": forecast / scale,
        "direction_score": float(np.tanh(forecast / scale)),
        "kernel_alignment": alignment,
        "support_similarity": float(np.max(np.abs(similarities))),
    }


def _f145(
    market: pd.DataFrame,
    features: pd.DataFrame,
    parameters: Mapping[str, Any],
) -> pd.Series:
    kind = str(parameters.get("kind", "rbf"))
    if kind not in {"linear", "rbf", "polynomial"}:
        raise PredictiveFeatureEngineError(f"F145_UNKNOWN_KIND:{kind}")
    x = features.to_numpy(dtype=float)
    target = _returns(market).shift(-1).to_numpy(dtype=float)
    window = _positive_int(parameters, "window", 252)
    return _rolling_model(
        market,
        x,
        target,
        window=window,
        cadence=str(parameters.get("refit", "quarterly")),
        fit=lambda train_x, train_y: _fit_lssvm(
            train_x,
            train_y,
            kind=kind,
            support_vectors=_positive_int(parameters, "support_vectors", 32),
            gamma=_bounded_float(
                parameters, "gamma", 0.5, lower=0.001, upper=10.0
            ),
            degree=_positive_int(parameters, "degree", 2),
            ridge=_bounded_float(
                parameters, "ridge", 0.1, lower=0.000001, upper=1000.0
            ),
        ),
        predict=_lssvm_statistics,
        statistic=str(parameters.get("statistic", "direction_score")),
    )


def _best_tree_split(
    x: np.ndarray,
    y: np.ndarray,
    features: np.ndarray,
    *,
    kind: str,
    generator: np.random.Generator,
    min_leaf: int,
) -> tuple[int, float] | None:
    best: tuple[float, int, float] | None = None
    for feature in features:
        values = x[:, feature]
        if kind == "extra_trees":
            minimum = float(np.min(values))
            maximum = float(np.max(values))
            if maximum - minimum <= 1e-12:
                continue
            thresholds = generator.uniform(minimum, maximum, size=3)
        else:
            thresholds = np.unique(np.quantile(values, (0.2, 0.4, 0.6, 0.8)))
        for threshold in thresholds:
            left = values <= threshold
            if int(left.sum()) < min_leaf or int((~left).sum()) < min_leaf:
                continue
            loss = 0.0
            for mask in (left, ~left):
                group = y[mask]
                loss += float(np.sum((group - np.mean(group)) ** 2))
            candidate = (loss, int(feature), float(threshold))
            if best is None or candidate < best:
                best = candidate
    return None if best is None else (best[1], best[2])


def _fit_random_tree(
    x: np.ndarray,
    y: np.ndarray,
    *,
    depth: int,
    max_features: int,
    min_leaf: int,
    kind: str,
    generator: np.random.Generator,
) -> Mapping[str, Any]:
    if depth <= 0 or len(y) < 2 * min_leaf or float(np.std(y, ddof=0)) <= 1e-12:
        return {"value": float(np.mean(y)), "count": len(y)}
    selected = np.sort(
        generator.choice(
            x.shape[1], size=min(max_features, x.shape[1]), replace=False
        )
    )
    split = _best_tree_split(
        x,
        y,
        selected,
        kind=kind,
        generator=generator,
        min_leaf=min_leaf,
    )
    if split is None:
        return {"value": float(np.mean(y)), "count": len(y)}
    feature, threshold = split
    left = x[:, feature] <= threshold
    return {
        "feature": feature,
        "threshold": threshold,
        "left": _fit_random_tree(
            x[left],
            y[left],
            depth=depth - 1,
            max_features=max_features,
            min_leaf=min_leaf,
            kind=kind,
            generator=generator,
        ),
        "right": _fit_random_tree(
            x[~left],
            y[~left],
            depth=depth - 1,
            max_features=max_features,
            min_leaf=min_leaf,
            kind=kind,
            generator=generator,
        ),
    }


def _predict_random_tree(node: Mapping[str, Any], row: np.ndarray) -> tuple[float, int]:
    if "value" in node:
        return float(node["value"]), int(node["count"])
    branch = "left" if row[int(node["feature"])] <= float(node["threshold"]) else "right"
    return _predict_random_tree(node[branch], row)


def _fit_forest(
    x: np.ndarray,
    y: np.ndarray,
    *,
    kind: str,
    estimators: int,
    depth: int,
    max_features: int,
    min_leaf: int,
    seed: int,
) -> Mapping[str, Any]:
    standardized, location, scale = _standardize(x)
    trees: list[Mapping[str, Any]] = []
    for estimator in range(estimators):
        generator = np.random.default_rng(seed + len(y) * 1009 + estimator * 7919)
        if kind == "random_forest":
            sample = generator.integers(0, len(y), size=len(y))
            tree_x = standardized[sample]
            tree_y = y[sample]
        else:
            tree_x = standardized
            tree_y = y
        trees.append(
            _fit_random_tree(
                tree_x,
                tree_y,
                depth=depth,
                max_features=max_features,
                min_leaf=min_leaf,
                kind=kind,
                generator=generator,
            )
        )
    return {
        "location": location,
        "scale": scale,
        "trees": trees,
        "target_scale": max(float(np.std(y, ddof=0)), _EPSILON),
        "sample_count": len(y),
    }


def _forest_statistics(model: Mapping[str, Any], row: np.ndarray) -> Mapping[str, float]:
    standardized = (row - model["location"]) / model["scale"]
    predictions: list[float] = []
    supports: list[int] = []
    for tree in model["trees"]:
        prediction, support = _predict_random_tree(tree, standardized)
        predictions.append(prediction)
        supports.append(support)
    values = np.asarray(predictions)
    scale = float(model["target_scale"])
    return {
        "forecast_z": float(np.mean(values) / scale),
        "direction_vote": float(np.mean(np.sign(values))),
        "tree_dispersion": float(np.std(values, ddof=0) / scale),
        "leaf_support": float(np.mean(supports) / model["sample_count"]),
    }


def _f146(
    market: pd.DataFrame,
    features: pd.DataFrame,
    parameters: Mapping[str, Any],
) -> pd.Series:
    kind = str(parameters.get("kind", "extra_trees"))
    if kind not in {"random_forest", "extra_trees"}:
        raise PredictiveFeatureEngineError(f"F146_UNKNOWN_KIND:{kind}")
    x = features.to_numpy(dtype=float)
    target = _returns(market).shift(-1).to_numpy(dtype=float)
    return _rolling_model(
        market,
        x,
        target,
        window=_positive_int(parameters, "window", 252),
        cadence=str(parameters.get("refit", "quarterly")),
        fit=lambda train_x, train_y: _fit_forest(
            train_x,
            train_y,
            kind=kind,
            estimators=_positive_int(parameters, "estimators", 16),
            depth=_positive_int(parameters, "depth", 3),
            max_features=_positive_int(parameters, "max_features", 3),
            min_leaf=_positive_int(parameters, "min_leaf", 10),
            seed=int(parameters.get("seed", 146)),
        ),
        predict=_forest_statistics,
        statistic=str(parameters.get("statistic", "tree_dispersion")),
    )


def _activation(values: np.ndarray, kind: str) -> np.ndarray:
    if kind == "tanh":
        return np.tanh(values)
    if kind == "relu":
        return np.maximum(values, 0.0)
    raise PredictiveFeatureEngineError(f"F147_UNKNOWN_ACTIVATION:{kind}")


def _activation_derivative(values: np.ndarray, kind: str) -> np.ndarray:
    if kind == "tanh":
        activated = np.tanh(values)
        return 1.0 - activated * activated
    if kind == "relu":
        return (values > 0.0).astype(float)
    raise PredictiveFeatureEngineError(f"F147_UNKNOWN_ACTIVATION:{kind}")


def _fit_mlp(
    x: np.ndarray,
    y: np.ndarray,
    *,
    activation: str,
    hidden_units: int,
    epochs: int,
    learning_rate: float,
    ridge: float,
    seed: int,
) -> Mapping[str, Any]:
    standardized, location, scale = _standardize(x)
    target_mean = float(np.mean(y))
    target_scale = max(float(np.std(y, ddof=0)), _EPSILON)
    target = (y - target_mean) / target_scale
    generator = np.random.default_rng(seed + len(y) * 1009)
    hidden_weight = generator.normal(
        0.0, 1.0 / np.sqrt(x.shape[1]), size=(x.shape[1], hidden_units)
    )
    hidden_bias = np.zeros(hidden_units)
    output_weight = generator.normal(0.0, 0.1, size=hidden_units)
    output_bias = 0.0
    for _ in range(epochs):
        preactivation = standardized @ hidden_weight + hidden_bias
        hidden = _activation(preactivation, activation)
        prediction = hidden @ output_weight + output_bias
        error = prediction - target
        output_gradient = hidden.T @ error / len(y) + ridge * output_weight / len(y)
        output_bias_gradient = float(np.mean(error))
        hidden_gradient = (
            error[:, None]
            * output_weight[None, :]
            * _activation_derivative(preactivation, activation)
        )
        hidden_weight_gradient = (
            standardized.T @ hidden_gradient / len(y)
            + ridge * hidden_weight / len(y)
        )
        hidden_bias_gradient = hidden_gradient.mean(axis=0)
        output_weight -= learning_rate * output_gradient
        output_bias -= learning_rate * output_bias_gradient
        hidden_weight -= learning_rate * hidden_weight_gradient
        hidden_bias -= learning_rate * hidden_bias_gradient
    return {
        "location": location,
        "scale": scale,
        "hidden_weight": hidden_weight,
        "hidden_bias": hidden_bias,
        "output_weight": output_weight,
        "output_bias": output_bias,
        "activation": activation,
    }


def _mlp_statistics(model: Mapping[str, Any], row: np.ndarray) -> Mapping[str, float]:
    standardized = (row - model["location"]) / model["scale"]
    hidden = _activation(
        standardized @ model["hidden_weight"] + model["hidden_bias"],
        model["activation"],
    )
    forecast_z = float(hidden @ model["output_weight"] + model["output_bias"])
    return {
        "forecast_z": forecast_z,
        "direction_probability": float(expit(2.0 * forecast_z) - 0.5),
        "hidden_dispersion": float(np.std(hidden, ddof=0)),
        "model_confidence": float(np.tanh(abs(forecast_z))),
    }


def _f147(
    market: pd.DataFrame,
    features: pd.DataFrame,
    parameters: Mapping[str, Any],
) -> pd.Series:
    activation = str(parameters.get("activation", "tanh"))
    if activation not in {"tanh", "relu"}:
        raise PredictiveFeatureEngineError(f"F147_UNKNOWN_ACTIVATION:{activation}")
    x = features.to_numpy(dtype=float)
    target = _returns(market).shift(-1).to_numpy(dtype=float)
    return _rolling_model(
        market,
        x,
        target,
        window=_positive_int(parameters, "window", 252),
        cadence=str(parameters.get("refit", "quarterly")),
        fit=lambda train_x, train_y: _fit_mlp(
            train_x,
            train_y,
            activation=activation,
            hidden_units=_positive_int(parameters, "hidden_units", 12),
            epochs=_positive_int(parameters, "epochs", 50),
            learning_rate=_bounded_float(
                parameters, "learning_rate", 0.02, lower=0.0001, upper=1.0
            ),
            ridge=_bounded_float(
                parameters, "ridge", 0.1, lower=0.0, upper=1000.0
            ),
            seed=int(parameters.get("seed", 147)),
        ),
        predict=_mlp_statistics,
        statistic=str(parameters.get("statistic", "direction_probability")),
    )


def _temporal_sequences(
    market: pd.DataFrame, features: pd.DataFrame, sequence: int
) -> np.ndarray:
    channels = np.column_stack(
        (_returns(market).to_numpy(dtype=float), features.to_numpy(dtype=float))
    )
    output = np.full((len(market), sequence, channels.shape[1]), np.nan)
    for index in range(sequence - 1, len(market)):
        output[index] = channels[index - sequence + 1 : index + 1]
    return output


def _convolution_basis(
    sequences: np.ndarray,
    filters: np.ndarray,
    *,
    dilation: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    count, sequence, _ = sequences.shape
    kernel = filters.shape[2]
    start = (kernel - 1) * dilation
    pooled = np.full((count, len(filters)), np.nan)
    endpoint = np.full_like(pooled, np.nan)
    concentration = np.full(count, np.nan)
    for sample in range(count):
        if not np.isfinite(sequences[sample]).all():
            continue
        activations = []
        for position in range(start, sequence):
            indices = position - np.arange(kernel) * dilation
            window = sequences[sample, indices, :].T
            activations.append(np.tanh(np.sum(filters * window[None, :, :], axis=(1, 2))))
        activation = np.asarray(activations)
        pooled[sample] = activation.mean(axis=0)
        endpoint[sample] = activation[-1]
        concentration[sample] = float(
            np.mean(np.abs(activation[-1]))
            / max(float(np.mean(np.abs(activation))), _EPSILON)
        )
    return pooled, endpoint, concentration


def _fit_tcn(
    sequences: np.ndarray,
    y: np.ndarray,
    *,
    filters_count: int,
    kernel: int,
    dilation: int,
    ridge: float,
    seed: int,
) -> Mapping[str, Any]:
    flat = sequences.reshape(-1, sequences.shape[2])
    location = np.mean(flat, axis=0)
    scale = np.std(flat, axis=0, ddof=0)
    scale = np.where(scale > 1e-12, scale, 1.0)
    standardized = (sequences - location) / scale
    generator = np.random.default_rng(seed)
    filters = generator.normal(
        0.0,
        1.0 / np.sqrt(sequences.shape[2] * kernel),
        size=(filters_count, sequences.shape[2], kernel),
    )
    pooled, endpoint, concentration = _convolution_basis(
        standardized, filters, dilation=dilation
    )
    design_features = np.column_stack((pooled, endpoint))
    design = np.column_stack((np.ones(len(y)), design_features))
    target_mean = float(np.mean(y))
    target_scale = max(float(np.std(y, ddof=0)), _EPSILON)
    target = (y - target_mean) / target_scale
    coefficient = _ridge(design, target, ridge)
    return {
        "location": location,
        "scale": scale,
        "filters": filters,
        "dilation": dilation,
        "coefficient": coefficient,
    }


def _tcn_statistics(model: Mapping[str, Any], row: np.ndarray) -> Mapping[str, float]:
    sequence = ((row - model["location"]) / model["scale"])[None, :, :]
    pooled, endpoint, concentration = _convolution_basis(
        sequence, model["filters"], dilation=int(model["dilation"])
    )
    forecast_z = float(
        np.r_[1.0, pooled[0], endpoint[0]] @ model["coefficient"]
    )
    return {
        "forecast_z": forecast_z,
        "direction_probability": float(expit(2.0 * forecast_z) - 0.5),
        "filter_dispersion": float(np.std(endpoint[0], ddof=0)),
        "temporal_concentration": float(concentration[0] - 1.0),
    }


def _rolling_sequence_model(
    market: pd.DataFrame,
    sequences: np.ndarray,
    target: np.ndarray,
    *,
    window: int,
    cadence: str,
    fit: Callable[[np.ndarray, np.ndarray], Any],
    predict: Callable[[Any, np.ndarray], Mapping[str, float]],
    statistic: str,
) -> pd.Series:
    output = np.full(len(market), np.nan)
    model: Any = None
    for index in range(len(market)):
        if index < window:
            continue
        if _refit_due(market["date"], index, cadence, model is not None):
            start = max(0, index - window)
            train_x = sequences[start:index]
            train_y = target[start:index]
            valid = np.isfinite(train_x).all(axis=(1, 2)) & np.isfinite(train_y)
            if int(valid.sum()) >= max(30, window - sequences.shape[1]):
                model = fit(train_x[valid], train_y[valid])
        if model is None or not np.isfinite(sequences[index]).all():
            continue
        statistics = predict(model, sequences[index])
        if statistic not in statistics:
            raise PredictiveFeatureEngineError(f"UNKNOWN_MODEL_STATISTIC:{statistic}")
        output[index] = statistics[statistic]
    return pd.Series(output, index=market.index)


def _f148(
    market: pd.DataFrame,
    temporal_features: pd.DataFrame,
    parameters: Mapping[str, Any],
) -> pd.Series:
    sequence = _positive_int(parameters, "sequence", 20)
    kernel = _positive_int(parameters, "kernel", 3)
    dilation = _positive_int(parameters, "dilation", 2)
    if (kernel - 1) * dilation >= sequence:
        raise PredictiveFeatureEngineError("F148_KERNEL_EXCEEDS_SEQUENCE")
    sequences = _temporal_sequences(market, temporal_features, sequence)
    target = _returns(market).shift(-1).to_numpy(dtype=float)
    return _rolling_sequence_model(
        market,
        sequences,
        target,
        window=_positive_int(parameters, "window", 252),
        cadence=str(parameters.get("refit", "quarterly")),
        fit=lambda train_x, train_y: _fit_tcn(
            train_x,
            train_y,
            filters_count=_positive_int(parameters, "filters", 4),
            kernel=kernel,
            dilation=dilation,
            ridge=_bounded_float(
                parameters, "ridge", 0.1, lower=0.0, upper=1000.0
            ),
            seed=int(parameters.get("seed", 148)),
        ),
        predict=_tcn_statistics,
        statistic=str(parameters.get("statistic", "forecast_z")),
    )


def _reservoir_weights(
    channels: int,
    units: int,
    *,
    kind: str,
    spectral_radius: float,
    seed: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    generator = np.random.default_rng(seed)
    input_weight = generator.normal(0.0, 1.0 / np.sqrt(channels), size=(units, channels))
    recurrent = generator.normal(0.0, 1.0 / np.sqrt(units), size=(units, units))
    if kind == "reservoir":
        recurrent *= generator.random((units, units)) < 0.2
    elif kind == "small_rnn":
        left, _, right = np.linalg.svd(recurrent, full_matrices=False)
        recurrent = left @ right
    else:
        raise PredictiveFeatureEngineError(f"F149_UNKNOWN_KIND:{kind}")
    radius = float(np.max(np.abs(np.linalg.eigvals(recurrent))))
    if radius > _EPSILON:
        recurrent *= spectral_radius / radius
    bias = generator.normal(0.0, 0.1, size=units)
    return input_weight, recurrent, bias


def _reservoir_states(
    sequences: np.ndarray,
    *,
    input_weight: np.ndarray,
    recurrent: np.ndarray,
    bias: np.ndarray,
    leak: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    final = np.full((len(sequences), len(bias)), np.nan)
    energy = np.full(len(sequences), np.nan)
    alignment = np.full(len(sequences), np.nan)
    for sample, sequence in enumerate(sequences):
        if not np.isfinite(sequence).all():
            continue
        state = np.zeros(len(bias))
        path = []
        for row in sequence:
            candidate = np.tanh(input_weight @ row + recurrent @ state + bias)
            state = (1.0 - leak) * state + leak * candidate
            path.append(state.copy())
        mean_state = np.mean(path, axis=0)
        final[sample] = state
        energy[sample] = float(np.linalg.norm(state) / np.sqrt(len(state)))
        alignment[sample] = float(
            state @ mean_state
            / max(float(np.linalg.norm(state) * np.linalg.norm(mean_state)), _EPSILON)
        )
    return final, energy, alignment


def _fit_reservoir(
    sequences: np.ndarray,
    y: np.ndarray,
    *,
    kind: str,
    units: int,
    spectral_radius: float,
    leak: float,
    ridge: float,
    seed: int,
) -> Mapping[str, Any]:
    flat = sequences.reshape(-1, sequences.shape[2])
    location = np.mean(flat, axis=0)
    scale = np.std(flat, axis=0, ddof=0)
    scale = np.where(scale > 1e-12, scale, 1.0)
    standardized = (sequences - location) / scale
    input_weight, recurrent, bias = _reservoir_weights(
        sequences.shape[2],
        units,
        kind=kind,
        spectral_radius=spectral_radius,
        seed=seed,
    )
    states, _, _ = _reservoir_states(
        standardized,
        input_weight=input_weight,
        recurrent=recurrent,
        bias=bias,
        leak=leak,
    )
    target_mean = float(np.mean(y))
    target_scale = max(float(np.std(y, ddof=0)), _EPSILON)
    coefficient = _ridge(
        np.column_stack((np.ones(len(states)), states)),
        (y - target_mean) / target_scale,
        ridge,
    )
    return {
        "location": location,
        "scale": scale,
        "input_weight": input_weight,
        "recurrent": recurrent,
        "bias": bias,
        "leak": leak,
        "coefficient": coefficient,
    }


def _reservoir_statistics(
    model: Mapping[str, Any], row: np.ndarray
) -> Mapping[str, float]:
    standardized = ((row - model["location"]) / model["scale"])[None, :, :]
    states, energy, alignment = _reservoir_states(
        standardized,
        input_weight=model["input_weight"],
        recurrent=model["recurrent"],
        bias=model["bias"],
        leak=float(model["leak"]),
    )
    forecast_z = float(np.r_[1.0, states[0]] @ model["coefficient"])
    return {
        "forecast_z": forecast_z,
        "direction_probability": float(expit(2.0 * forecast_z) - 0.5),
        "state_energy": float(energy[0]),
        "memory_alignment": float(alignment[0]),
    }


def _f149(
    market: pd.DataFrame,
    temporal_features: pd.DataFrame,
    parameters: Mapping[str, Any],
) -> pd.Series:
    kind = str(parameters.get("kind", "reservoir"))
    if kind not in {"reservoir", "small_rnn"}:
        raise PredictiveFeatureEngineError(f"F149_UNKNOWN_KIND:{kind}")
    sequence = _positive_int(parameters, "sequence", 20)
    sequences = _temporal_sequences(market, temporal_features, sequence)
    target = _returns(market).shift(-1).to_numpy(dtype=float)
    return _rolling_sequence_model(
        market,
        sequences,
        target,
        window=_positive_int(parameters, "window", 252),
        cadence=str(parameters.get("refit", "quarterly")),
        fit=lambda train_x, train_y: _fit_reservoir(
            train_x,
            train_y,
            kind=kind,
            units=_positive_int(parameters, "units", 16),
            spectral_radius=_bounded_float(
                parameters, "spectral_radius", 0.6, lower=0.05, upper=1.5
            ),
            leak=_bounded_float(
                parameters, "leak", 0.5, lower=0.05, upper=1.0
            ),
            ridge=_bounded_float(
                parameters, "ridge", 0.1, lower=0.0, upper=1000.0
            ),
            seed=int(parameters.get("seed", 149)),
        ),
        predict=_reservoir_statistics,
        statistic=str(parameters.get("statistic", "state_energy")),
    )


def _attention_design(
    sequences: np.ndarray, *, temperature: float
) -> tuple[np.ndarray, np.ndarray]:
    design = np.full((len(sequences), sequences.shape[2] * 2), np.nan)
    entropy = np.full(len(sequences), np.nan)
    for sample, sequence in enumerate(sequences):
        if not np.isfinite(sequence).all():
            continue
        query = sequence[-1]
        scores = sequence @ query / np.sqrt(sequence.shape[1]) / temperature
        scores -= float(np.max(scores))
        weights = np.exp(scores)
        weights /= weights.sum()
        context = weights @ sequence
        design[sample] = np.r_[query, context]
        entropy[sample] = float(
            -np.sum(weights * np.log(np.maximum(weights, _EPSILON)))
            / np.log(len(weights))
        )
    return design, entropy


def _gate_value(sequences: np.ndarray, gate: str) -> np.ndarray:
    returns = sequences[:, :, 0]
    volatility = np.std(returns, axis=1, ddof=0)
    trend = np.mean(returns, axis=1)
    if gate == "volatility":
        return volatility
    if gate == "trend":
        return trend
    if gate == "hybrid":
        return volatility + trend
    raise PredictiveFeatureEngineError(f"F150_UNKNOWN_GATE:{gate}")


def _fit_attention_or_moe(
    sequences: np.ndarray,
    y: np.ndarray,
    *,
    kind: str,
    temperature: float,
    experts: int,
    gate: str,
    ridge: float,
) -> Mapping[str, Any]:
    flat = sequences.reshape(-1, sequences.shape[2])
    location = np.mean(flat, axis=0)
    scale = np.std(flat, axis=0, ddof=0)
    scale = np.where(scale > 1e-12, scale, 1.0)
    standardized = (sequences - location) / scale
    target_mean = float(np.mean(y))
    target_scale = max(float(np.std(y, ddof=0)), _EPSILON)
    target = (y - target_mean) / target_scale
    if kind == "attention":
        design, _ = _attention_design(standardized, temperature=temperature)
        coefficient = _ridge(
            np.column_stack((np.ones(len(design)), design)), target, ridge
        )
        return {
            "kind": kind,
            "location": location,
            "scale": scale,
            "temperature": temperature,
            "coefficient": coefficient,
        }
    if kind != "moe":
        raise PredictiveFeatureEngineError(f"F150_UNKNOWN_KIND:{kind}")
    current = standardized[:, -1, :]
    gate_values = _gate_value(standardized, gate)
    thresholds = np.quantile(gate_values, np.linspace(0.0, 1.0, experts + 1)[1:-1])
    labels = np.digitize(gate_values, thresholds)
    coefficients = []
    fallback = _ridge(
        np.column_stack((np.ones(len(current)), current)), target, ridge
    )
    for expert in range(experts):
        selected = labels == expert
        if int(selected.sum()) < current.shape[1] + 2:
            coefficients.append(fallback)
        else:
            coefficients.append(
                _ridge(
                    np.column_stack((np.ones(int(selected.sum())), current[selected])),
                    target[selected],
                    ridge,
                )
            )
    return {
        "kind": kind,
        "location": location,
        "scale": scale,
        "gate": gate,
        "thresholds": thresholds,
        "coefficients": coefficients,
    }


def _attention_or_moe_statistics(
    model: Mapping[str, Any], row: np.ndarray
) -> Mapping[str, float]:
    standardized = ((row - model["location"]) / model["scale"])[None, :, :]
    if model["kind"] == "attention":
        design, entropy = _attention_design(
            standardized, temperature=float(model["temperature"])
        )
        forecast_z = float(np.r_[1.0, design[0]] @ model["coefficient"])
        disagreement = 0.0
        attention_entropy = float(entropy[0])
    else:
        current = standardized[0, -1]
        gate_value = float(_gate_value(standardized, model["gate"])[0])
        expert = int(np.digitize(gate_value, model["thresholds"]))
        predictions = np.asarray(
            [np.r_[1.0, current] @ coefficient for coefficient in model["coefficients"]]
        )
        forecast_z = float(predictions[expert])
        disagreement = float(np.std(predictions, ddof=0))
        attention_entropy = 0.0
    return {
        "forecast_z": forecast_z,
        "direction_probability": float(expit(2.0 * forecast_z) - 0.5),
        "attention_entropy": attention_entropy,
        "expert_disagreement": disagreement,
    }


def _f150(
    market: pd.DataFrame,
    features: pd.DataFrame,
    parameters: Mapping[str, Any],
) -> pd.Series:
    kind = str(parameters.get("kind", "attention"))
    if kind not in {"attention", "moe"}:
        raise PredictiveFeatureEngineError(f"F150_UNKNOWN_KIND:{kind}")
    lookback = _positive_int(parameters, "lookback", 10)
    sequences = _temporal_sequences(market, features, lookback)
    target = _returns(market).shift(-1).to_numpy(dtype=float)
    return _rolling_sequence_model(
        market,
        sequences,
        target,
        window=_positive_int(parameters, "window", 252),
        cadence=str(parameters.get("refit", "quarterly")),
        fit=lambda train_x, train_y: _fit_attention_or_moe(
            train_x,
            train_y,
            kind=kind,
            temperature=_bounded_float(
                parameters, "temperature", 1.0, lower=0.05, upper=10.0
            ),
            experts=_positive_int(parameters, "experts", 3),
            gate=str(parameters.get("gate", "hybrid")),
            ridge=_bounded_float(
                parameters, "ridge", 0.1, lower=0.0, upper=1000.0
            ),
        ),
        predict=_attention_or_moe_statistics,
        statistic=str(parameters.get("statistic", "attention_entropy")),
    )


def evaluate_predictive_lane(
    lane_id: str,
    panels: Mapping[str, pd.DataFrame],
    feature_panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    """Evaluate one frozen lane using only rows known by each decision date."""

    market = _spy(panels)
    if lane_id == "F141":
        value = _f141(market, parameters)
        observed = market["observed_at"]
    elif lane_id == "F142":
        value, cboe_observed = _f142(market, panels, parameters)
        observed = _max_observed(market, [cboe_observed])
    elif lane_id == "F144":
        value = _f144(market, parameters)
        observed = market["observed_at"]
    elif lane_id in {"F143", "F145", "F146", "F147", "F150"}:
        features, feature_observations = _aligned_features(
            market, feature_panels, _APPROVED_FEATURES
        )
        observed = _max_observed(market, feature_observations)
        if lane_id == "F143":
            value = _f143(market, features, parameters)
        elif lane_id == "F145":
            value = _f145(market, features, parameters)
        elif lane_id == "F146":
            value = _f146(market, features, parameters)
        elif lane_id == "F147":
            value = _f147(market, features, parameters)
        else:
            value = _f150(market, features, parameters)
    elif lane_id in {"F148", "F149"}:
        features, feature_observations = _aligned_features(
            market, feature_panels, _TEMPORAL_FEATURES
        )
        observed = _max_observed(market, feature_observations)
        value = (
            _f148(market, features, parameters)
            if lane_id == "F148"
            else _f149(market, features, parameters)
        )
    else:
        raise PredictiveFeatureEngineError(f"UNKNOWN_PREDICTIVE_LANE:{lane_id}")
    return _output(market, value, observed)


_DEFAULT_PARAMETERS: Mapping[str, Mapping[str, Any]] = {
    "F141": {"kind": "arma", "statistic": "forecast_z", "ar_order": 2, "ma_order": 1, "window": 252, "refit": "quarterly", "ridge": 0.1},
    "F142": {"kind": "var", "statistic": "forecast_z", "lags": 2, "window": 252, "refit": "quarterly", "ridge": 0.1},
    "F143": {"statistic": "factor_score", "components": 2, "sign_rule": "return_correlation", "window": 252, "refit": "quarterly"},
    "F144": {"statistic": "median_skew", "lags": 5, "tail_quantile": 0.1, "forecast_quantile": 0.5, "window": 252, "refit": "quarterly", "ridge": 0.1},
    "F145": {"kind": "rbf", "statistic": "direction_score", "support_vectors": 32, "gamma": 0.5, "degree": 2, "window": 252, "refit": "quarterly", "ridge": 0.1},
    "F146": {"kind": "extra_trees", "statistic": "tree_dispersion", "estimators": 16, "depth": 3, "max_features": 3, "min_leaf": 10, "window": 252, "refit": "quarterly", "seed": 146},
    "F147": {"activation": "tanh", "statistic": "direction_probability", "hidden_units": 12, "epochs": 50, "learning_rate": 0.02, "ridge": 0.1, "window": 252, "refit": "quarterly", "seed": 147},
    "F148": {"statistic": "forecast_z", "sequence": 20, "kernel": 3, "dilation": 2, "filters": 4, "ridge": 0.1, "window": 252, "refit": "quarterly", "seed": 148},
    "F149": {"kind": "reservoir", "statistic": "state_energy", "sequence": 20, "units": 16, "spectral_radius": 0.6, "leak": 0.5, "ridge": 0.1, "window": 252, "refit": "quarterly", "seed": 149},
    "F150": {"kind": "attention", "statistic": "attention_entropy", "lookback": 10, "temperature": 1.0, "experts": 3, "gate": "hybrid", "ridge": 0.1, "window": 252, "refit": "quarterly"},
}


def evaluate_predictive_family_batch(
    panels: Mapping[str, pd.DataFrame],
    feature_panels: Mapping[str, pd.DataFrame],
) -> Mapping[str, pd.DataFrame]:
    """Evaluate the ten frozen defaults in stable lane order."""

    return {
        lane: evaluate_predictive_lane(lane, panels, feature_panels, parameters)
        for lane, parameters in _DEFAULT_PARAMETERS.items()
    }


__all__ = [
    "PredictiveFeatureEngineError",
    "evaluate_predictive_family_batch",
    "evaluate_predictive_lane",
]
