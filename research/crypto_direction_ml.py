"""BTC/crypto 5m next-bar direction search with optional tabular ML models."""
from __future__ import annotations

import importlib
import json
import random
import time
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from aurora.core.runtime_paths import base_data_dir
from aurora.data_contracts.timeseries_store import TimeSeriesStore
CRYPTO_5M_COLUMNS = ("open", "high", "low", "close", "volume")
FORBIDDEN_COLUMN_TOKENS = ("locked", "future", "label", "target", "prediction")
DEFAULT_FEATURE_WINDOWS = (1, 2, 3, 6, 12, 24, 48, 96)
PRICE_RETURN_WINDOWS = (1, 2, 3, 6, 12, 24, 48, 96, 288, 864, 2016)
TREND_WINDOWS = (12, 48, 288, 2016)
VOLATILITY_WINDOWS = (12, 48, 288, 2016)
TARGET_HORIZONS = (1, 3, 6, 12)
EXTERNAL_CRYPTO_FEATURE_BACKLOG = (
    "funding_rate",
    "open_interest",
    "long_short_ratio",
    "taker_buy_sell_ratio",
    "basis_spot_perp",
    "perp_premium",
    "liquidations_long",
    "liquidations_short",
    "orderbook_imbalance",
    "bid_ask_spread",
    "depth_1pct_bid",
    "depth_1pct_ask",
    "btc_dominance",
    "ethbtc_return",
    "total_crypto_market_cap",
    "stablecoin_supply_change",
    "exchange_netflow_btc",
    "miner_reserve_change",
    "fear_greed_index",
    "dxy_return",
    "nasdaq_return",
    "gold_return",
    "us_10y_yield_change",
)


class OptionalModelMissing(RuntimeError):
    """Raised when a requested optional ML model is not installed."""


@dataclass(frozen=True)
class CryptoDirectionMLConfig:
    run_id: str
    symbol: str = "BTCUSDT"
    library: str = "crypto_5m"
    version: str = "binance_5m_36m"
    models: tuple[str, ...] = ("lightgbm", "xgboost")
    workers: int = 6
    target_accuracy: float = 0.55
    train_fraction: float = 0.60
    validation_fraction: float = 0.20
    seed: int = 42
    max_candidates: int = 24
    run_root: str | None = None
    no_locked: bool = True
    top_n: int = 25


@dataclass(frozen=True)
class CryptoDirectionMLRegimeConfig(CryptoDirectionMLConfig):
    partitions: tuple[str, ...] = ("hour_3", "hour_6", "volume_2", "range_2", "trend_2")
    feature_sets: tuple[str, ...] = ("all", "short_price", "medium_price", "volume_candle", "no_calendar")
    min_bucket_rows: int = 250


@dataclass(frozen=True)
class CryptoDirectionSignalSearchConfig(CryptoDirectionMLConfig):
    horizons: tuple[int, ...] = (1, 2, 3, 6, 12)
    move_threshold_bps: tuple[float, ...] = (0.0, 2.0, 5.0, 10.0, 15.0)
    confidence_thresholds: tuple[float, ...] = (0.50, 0.52, 0.53, 0.54, 0.55, 0.57, 0.60)
    hour_windows: tuple[str, ...] = ("all", "utc_00_08", "utc_08_16", "utc_16_24")
    sides: tuple[str, ...] = ("up", "down", "both")
    feature_sets: tuple[str, ...] = ("all", "short_price", "medium_price", "volume_candle", "no_calendar")
    min_train_signals: int = 1_000
    min_validation_signals: int = 300
    max_model_candidates: int = 24


@dataclass(frozen=True)
class DirectionAccuracyMetrics:
    prediction_count: int
    accuracy: float
    up_accuracy: float | None
    down_accuracy: float | None
    actual_up_rate: float
    predicted_up_rate: float
    first_half_accuracy: float | None
    second_half_accuracy: float | None
    stability_accuracy: float
    confusion: dict[str, int]
    hourly_accuracy: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SignalRuleMetrics:
    signal_count: int
    precision: float
    coverage: float
    average_signed_return: float
    first_half_precision: float | None
    second_half_precision: float | None
    stability_precision: float
    long_signals: int
    short_signals: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CryptoDirectionCandidate:
    candidate_id: str
    model: str
    params: dict[str, Any]
    polarity: str
    train_metrics: DirectionAccuracyMetrics
    validation_metrics: DirectionAccuracyMetrics | None
    feature_count: int
    rule: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "model": self.model,
            "params": self.params,
            "polarity": self.polarity,
            "train_metrics": self.train_metrics.to_dict(),
            "validation_metrics": None
            if self.validation_metrics is None
            else self.validation_metrics.to_dict(),
            "feature_count": self.feature_count,
            "rule": self.rule,
        }


@dataclass(frozen=True)
class CryptoDirectionSignalCandidate:
    candidate_id: str
    model: str
    params: dict[str, Any]
    train_metrics: SignalRuleMetrics
    validation_metrics: SignalRuleMetrics | None
    feature_count: int
    rule: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "model": self.model,
            "params": self.params,
            "train_metrics": self.train_metrics.to_dict(),
            "validation_metrics": None
            if self.validation_metrics is None
            else self.validation_metrics.to_dict(),
            "feature_count": self.feature_count,
            "rule": self.rule,
        }


@dataclass(frozen=True)
class CryptoDirectionMLReport:
    status: str
    locked_opened: bool
    validation_used_for_selection: bool
    objective_met: bool
    run_id: str
    output_dir: str
    symbol: str
    library: str
    version: str
    models: tuple[str, ...]
    workers: int
    train_period: tuple[str, str]
    validation_period: tuple[str, str]
    locked_period: tuple[str, str]
    rows_train: int
    rows_validation: int
    rows_locked: int
    used_columns: tuple[str, ...]
    feature_count: int
    candidates_evaluated: int
    baselines_train: dict[str, float]
    baselines_validation: dict[str, float]
    best_train: CryptoDirectionCandidate | None
    objective_candidates: tuple[CryptoDirectionCandidate, ...]
    top: tuple[CryptoDirectionCandidate, ...]
    route_errors: tuple[str, ...] = tuple()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "locked_opened": self.locked_opened,
            "validation_used_for_selection": self.validation_used_for_selection,
            "objective_met": self.objective_met,
            "run_id": self.run_id,
            "output_dir": self.output_dir,
            "symbol": self.symbol,
            "library": self.library,
            "version": self.version,
            "models": list(self.models),
            "workers": self.workers,
            "train_period": self.train_period,
            "validation_period": self.validation_period,
            "locked_period": self.locked_period,
            "rows_train": self.rows_train,
            "rows_validation": self.rows_validation,
            "rows_locked": self.rows_locked,
            "used_columns": list(self.used_columns),
            "feature_count": self.feature_count,
            "candidates_evaluated": self.candidates_evaluated,
            "baselines_train": self.baselines_train,
            "baselines_validation": self.baselines_validation,
            "best_train": None if self.best_train is None else self.best_train.to_dict(),
            "objective_candidates": [
                candidate.to_dict() for candidate in self.objective_candidates
            ],
            "top": [candidate.to_dict() for candidate in self.top],
            "route_errors": list(self.route_errors),
        }


@dataclass(frozen=True)
class CryptoDirectionSignalSearchReport:
    status: str
    locked_opened: bool
    validation_used_for_selection: bool
    objective_met: bool
    run_id: str
    output_dir: str
    symbol: str
    library: str
    version: str
    models: tuple[str, ...]
    workers: int
    train_period: tuple[str, str]
    validation_period: tuple[str, str]
    locked_period: tuple[str, str]
    rows_train: int
    rows_validation: int
    rows_locked: int
    used_columns: tuple[str, ...]
    candidates_evaluated: int
    best_train: CryptoDirectionSignalCandidate | None
    objective_candidates: tuple[CryptoDirectionSignalCandidate, ...]
    top: tuple[CryptoDirectionSignalCandidate, ...]
    route_errors: tuple[str, ...] = tuple()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "locked_opened": self.locked_opened,
            "validation_used_for_selection": self.validation_used_for_selection,
            "objective_met": self.objective_met,
            "run_id": self.run_id,
            "output_dir": self.output_dir,
            "symbol": self.symbol,
            "library": self.library,
            "version": self.version,
            "models": list(self.models),
            "workers": self.workers,
            "train_period": self.train_period,
            "validation_period": self.validation_period,
            "locked_period": self.locked_period,
            "rows_train": self.rows_train,
            "rows_validation": self.rows_validation,
            "rows_locked": self.rows_locked,
            "used_columns": list(self.used_columns),
            "candidates_evaluated": self.candidates_evaluated,
            "best_train": None if self.best_train is None else self.best_train.to_dict(),
            "objective_candidates": [
                candidate.to_dict() for candidate in self.objective_candidates
            ],
            "top": [candidate.to_dict() for candidate in self.top],
            "route_errors": list(self.route_errors),
        }


def run_crypto_direction_ml(config: CryptoDirectionMLConfig) -> CryptoDirectionMLReport:
    if not config.no_locked:
        raise ValueError("crypto-direction-ml v1 requires --no-locked")
    if config.workers < 1:
        raise ValueError("workers must be >= 1")
    if config.max_candidates < 1:
        raise ValueError("max-candidates must be >= 1")
    requested_models = tuple(_normalise_model_name(model) for model in config.models)
    _ensure_optional_models_available(requested_models)

    output_dir = _output_dir(config)
    output_dir.mkdir(parents=True, exist_ok=True)
    status_path = output_dir / "status.json"
    progress_path = output_dir / "progress.jsonl"
    candidates_path = output_dir / "candidates.jsonl"
    best_path = output_dir / "best_candidates.json"
    best_md_path = output_dir / "best_candidates.md"
    train_pred_path = output_dir / "predictions_train.parquet"
    validation_pred_path = output_dir / "predictions_validation.parquet"
    feature_importance_path = output_dir / "feature_importance.json"
    stderr_path = output_dir / "stderr.log"
    for path in (
        status_path,
        progress_path,
        candidates_path,
        best_path,
        best_md_path,
        train_pred_path,
        validation_pred_path,
        feature_importance_path,
        stderr_path,
    ):
        if path.exists():
            path.unlink()
    stderr_path.write_text("", encoding="utf-8")
    started = time.perf_counter()
    _write_json(status_path, _status_payload(config, output_dir, "running"))

    try:
        frame = load_crypto_direction_frame(
            config.symbol,
            library=config.library,
            version=config.version,
        )
        features = build_crypto_direction_features(frame)
        dataset = build_direction_dataset(features, frame["close"])
        train, validation, locked = split_direction_dataset(dataset, config)
        if len(train) < 100 or len(validation) < 50:
            raise ValueError("not enough rows after feature alignment")

        feature_columns = tuple(
            column for column in dataset.columns if column not in {"target_up", "next_return"}
        )
        specs = _candidate_specs(config, requested_models)
        candidates: list[CryptoDirectionCandidate] = []
        objective_candidates: list[CryptoDirectionCandidate] = []
        route_errors: list[str] = []
        successful_routes: list[dict[str, Any]] = []
        best_seen: CryptoDirectionCandidate | None = None
        best_predictions: tuple[pd.DataFrame, pd.DataFrame] | None = None
        best_importance: dict[str, Any] = {}

        x_train = train[list(feature_columns)].astype(float)
        y_train = train["target_up"].to_numpy(dtype=int)
        x_validation = validation[list(feature_columns)].astype(float)
        y_validation = validation["target_up"].to_numpy(dtype=int)
        x_train = _fill_matrix(x_train)
        x_validation = _fill_matrix(x_validation)
        baselines_train = direction_baselines(y_train, train.index)
        baselines_validation = direction_baselines(y_validation, validation.index)

        for index, spec in enumerate(specs, start=1):
            try:
                model = _fit_model(spec, x_train, y_train, workers=config.workers)
                train_proba = _predict_proba_up(model, spec["model"], x_train)
                validation_proba = _predict_proba_up(model, spec["model"], x_validation)
                polarity, train_pred = _best_train_polarity(train_proba, y_train)
                validation_pred = _apply_polarity(validation_proba, polarity)
                train_metrics = direction_accuracy_metrics(
                    train_pred,
                    y_train,
                    train.index,
                )
                validation_metrics = direction_accuracy_metrics(
                    validation_pred,
                    y_validation,
                    validation.index,
                )
                candidate = CryptoDirectionCandidate(
                    candidate_id=f"crypto-direction-{index:04d}",
                    model=str(spec["model"]),
                    params=dict(spec["params"]),
                    polarity=polarity,
                    train_metrics=train_metrics,
                    validation_metrics=validation_metrics,
                    feature_count=len(feature_columns),
                    rule=(
                        f"{spec['model']} predicts next BTC 5m direction; "
                        f"{'invert probabilities' if polarity == 'inverted' else 'use raw probabilities'}"
                    ),
                )
                candidates.append(candidate)
                successful_routes.append({
                    "candidate": candidate,
                    "train_proba": train_proba,
                    "validation_proba": validation_proba,
                })
                _append_jsonl(candidates_path, candidate.to_dict())
                if _passes_objective(
                    candidate,
                    config,
                    validation_metrics,
                    baselines_validation,
                ):
                    objective_candidates.append(candidate)
                if best_seen is None or _candidate_sort_key(candidate) > _candidate_sort_key(best_seen):
                    best_seen = candidate
                    best_predictions = (
                        _prediction_frame(train.index, y_train, train_proba, train_pred, polarity),
                        _prediction_frame(
                            validation.index,
                            y_validation,
                            validation_proba,
                            validation_pred,
                            polarity,
                        ),
                    )
                    best_importance = _feature_importance(model, feature_columns)
            except Exception as exc:
                route_errors.append(f"{spec['model']} candidate {index} failed: {exc}")
            if index == 1 or index % 5 == 0 or index == len(specs):
                top_now = sorted(candidates, key=_candidate_sort_key, reverse=True)[: config.top_n]
                _append_jsonl(progress_path, {
                    "event": "progress",
                    "candidates_evaluated": index,
                    "elapsed_seconds": time.perf_counter() - started,
                    "best_train_accuracy": None
                    if not top_now
                    else top_now[0].train_metrics.accuracy,
                    "best_validation_accuracy": None
                    if not top_now or top_now[0].validation_metrics is None
                    else top_now[0].validation_metrics.accuracy,
                    "objective_candidates_found": len(objective_candidates),
                    "updated_at_utc": _now(),
                })

        ensemble_specs = _ensemble_specs(successful_routes)
        for ensemble_name, train_proba, validation_proba, sources in ensemble_specs:
            polarity, train_pred = _best_train_polarity(train_proba, y_train)
            validation_pred = _apply_polarity(validation_proba, polarity)
            train_metrics = direction_accuracy_metrics(train_pred, y_train, train.index)
            validation_metrics = direction_accuracy_metrics(
                validation_pred,
                y_validation,
                validation.index,
            )
            candidate = CryptoDirectionCandidate(
                candidate_id=f"crypto-direction-{len(candidates) + 1:04d}",
                model=ensemble_name,
                params={"sources": sources},
                polarity=polarity,
                train_metrics=train_metrics,
                validation_metrics=validation_metrics,
                feature_count=len(feature_columns),
                rule=(
                    f"{ensemble_name} combines LightGBM and XGBoost; "
                    f"{'invert probabilities' if polarity == 'inverted' else 'use raw probabilities'}"
                ),
            )
            candidates.append(candidate)
            _append_jsonl(candidates_path, candidate.to_dict())
            if _passes_objective(candidate, config, validation_metrics, baselines_validation):
                objective_candidates.append(candidate)
            if best_seen is None or _candidate_sort_key(candidate) > _candidate_sort_key(best_seen):
                best_seen = candidate
                best_predictions = (
                    _prediction_frame(train.index, y_train, train_proba, train_pred, polarity),
                    _prediction_frame(
                        validation.index,
                        y_validation,
                        validation_proba,
                        validation_pred,
                        polarity,
                    ),
                )
                best_importance = {"ensemble_sources": sources}
        if ensemble_specs:
            top_now = sorted(candidates, key=_candidate_sort_key, reverse=True)[: config.top_n]
            _append_jsonl(progress_path, {
                "event": "ensembles",
                "candidates_evaluated": len(candidates),
                "elapsed_seconds": time.perf_counter() - started,
                "best_train_accuracy": None
                if not top_now
                else top_now[0].train_metrics.accuracy,
                "best_validation_accuracy": None
                if not top_now or top_now[0].validation_metrics is None
                else top_now[0].validation_metrics.accuracy,
                "objective_candidates_found": len(objective_candidates),
                "updated_at_utc": _now(),
            })

        top = tuple(sorted(candidates, key=_candidate_sort_key, reverse=True)[: config.top_n])
        best_train = top[0] if top else None
        if best_train is not None and best_predictions is not None:
            _write_parquet(train_pred_path, best_predictions[0])
            _write_parquet(validation_pred_path, best_predictions[1])
            _write_json(feature_importance_path, best_importance)
        objective_met = bool(objective_candidates)
        report = CryptoDirectionMLReport(
            status="objective_met" if objective_met else "completed",
            locked_opened=False,
            validation_used_for_selection=False,
            objective_met=objective_met,
            run_id=config.run_id,
            output_dir=str(output_dir),
            symbol=config.symbol,
            library=config.library,
            version=config.version,
            models=requested_models,
            workers=config.workers,
            train_period=_period_tuple(train),
            validation_period=_period_tuple(validation),
            locked_period=_period_tuple(locked),
            rows_train=len(train),
            rows_validation=len(validation),
            rows_locked=len(locked),
            used_columns=CRYPTO_5M_COLUMNS,
            feature_count=len(feature_columns),
            candidates_evaluated=len(candidates),
            baselines_train=baselines_train,
            baselines_validation=baselines_validation,
            best_train=best_train,
            objective_candidates=tuple(objective_candidates),
            top=top,
            route_errors=tuple(route_errors),
        )
        _write_json(best_path, report.to_dict())
        best_md_path.write_text(report_to_markdown(report), encoding="utf-8")
        _write_json(status_path, report.to_dict() | {
            "completed_at_utc": _now(),
            "elapsed_seconds": time.perf_counter() - started,
        })
        return report
    except Exception:
        error = traceback.format_exc()
        stderr_path.write_text(error, encoding="utf-8")
        _write_json(status_path, {
            "status": "error",
            "locked_opened": False,
            "validation_used_for_selection": False,
            "run_id": config.run_id,
            "error": error,
            "updated_at_utc": _now(),
        })
        raise


def run_crypto_direction_ml_regime_search(
    config: CryptoDirectionMLRegimeConfig,
) -> CryptoDirectionMLReport:
    if not config.no_locked:
        raise ValueError("crypto-direction-ml-regime v1 requires --no-locked")
    if config.workers < 1:
        raise ValueError("workers must be >= 1")
    if config.max_candidates < 1:
        raise ValueError("max-candidates must be >= 1")
    requested_models = tuple(_normalise_model_name(model) for model in config.models)
    _ensure_optional_models_available(requested_models)

    output_dir = _output_dir_regime(config)
    output_dir.mkdir(parents=True, exist_ok=True)
    status_path = output_dir / "status.json"
    progress_path = output_dir / "progress.jsonl"
    candidates_path = output_dir / "candidates.jsonl"
    best_path = output_dir / "best_candidates.json"
    best_md_path = output_dir / "best_candidates.md"
    train_pred_path = output_dir / "predictions_train.parquet"
    validation_pred_path = output_dir / "predictions_validation.parquet"
    feature_importance_path = output_dir / "feature_importance.json"
    stderr_path = output_dir / "stderr.log"
    for path in (
        status_path,
        progress_path,
        candidates_path,
        best_path,
        best_md_path,
        train_pred_path,
        validation_pred_path,
        feature_importance_path,
        stderr_path,
    ):
        if path.exists():
            path.unlink()
    stderr_path.write_text("", encoding="utf-8")
    started = time.perf_counter()
    _write_json(status_path, _status_payload(config, output_dir, "running") | {
        "regime_search": True,
        "partitions": list(config.partitions),
        "feature_sets": list(config.feature_sets),
    })

    try:
        frame = load_crypto_direction_frame(
            config.symbol,
            library=config.library,
            version=config.version,
        )
        features = build_crypto_direction_features(frame)
        dataset = build_direction_dataset(features, frame["close"])
        train, validation, locked = split_direction_dataset(dataset, config)
        if len(train) < 100 or len(validation) < 50:
            raise ValueError("not enough rows after feature alignment")

        all_feature_columns = tuple(
            column for column in dataset.columns if column not in {"target_up", "next_return"}
        )
        y_train = train["target_up"].to_numpy(dtype=int)
        y_validation = validation["target_up"].to_numpy(dtype=int)
        baselines_train = direction_baselines(y_train, train.index)
        baselines_validation = direction_baselines(y_validation, validation.index)
        base_specs = _candidate_specs(
            CryptoDirectionMLConfig(
                run_id=config.run_id,
                models=requested_models,
                max_candidates=max(config.max_candidates, 1),
                seed=config.seed,
            ),
            requested_models,
        )

        candidates: list[CryptoDirectionCandidate] = []
        objective_candidates: list[CryptoDirectionCandidate] = []
        route_errors: list[str] = []
        best_seen: CryptoDirectionCandidate | None = None
        best_predictions: tuple[pd.DataFrame, pd.DataFrame] | None = None
        best_importance: dict[str, Any] = {}
        candidate_number = 0

        for partition in config.partitions:
            full_masks = build_regime_masks(dataset, partition, reference=train)
            train_masks = {name: mask.loc[train.index] for name, mask in full_masks.items()}
            validation_masks = {
                name: mask.loc[validation.index] for name, mask in full_masks.items()
            }
            for feature_set in config.feature_sets:
                feature_columns = select_feature_columns(all_feature_columns, feature_set)
                if not feature_columns:
                    route_errors.append(f"{partition}/{feature_set} skipped: no feature columns")
                    continue
                for spec in base_specs:
                    if candidate_number >= config.max_candidates:
                        break
                    candidate_number += 1
                    try:
                        train_proba = np.full(len(train), np.nan, dtype=np.float64)
                        validation_proba = np.full(len(validation), np.nan, dtype=np.float64)
                        bucket_importance: dict[str, Any] = {}
                        bucket_rows: dict[str, int] = {}
                        for bucket, train_mask in train_masks.items():
                            train_positions = np.flatnonzero(train_mask.to_numpy(dtype=bool))
                            validation_positions = np.flatnonzero(
                                validation_masks[bucket].to_numpy(dtype=bool)
                            )
                            if len(train_positions) < config.min_bucket_rows:
                                raise ValueError(
                                    f"bucket {bucket} has only {len(train_positions)} train rows"
                                )
                            y_bucket = y_train[train_positions]
                            if len(set(y_bucket.tolist())) < 2:
                                raise ValueError(f"bucket {bucket} has only one class")
                            x_bucket = _fill_matrix(
                                train.iloc[train_positions][list(feature_columns)].astype(float)
                            )
                            model = _fit_model(
                                spec,
                                x_bucket,
                                y_bucket,
                                workers=config.workers,
                            )
                            train_proba[train_positions] = _predict_proba_up(
                                model,
                                spec["model"],
                                _fill_matrix(
                                    train.iloc[train_positions][list(feature_columns)].astype(float)
                                ),
                            )
                            if len(validation_positions):
                                validation_proba[validation_positions] = _predict_proba_up(
                                    model,
                                    spec["model"],
                                    _fill_matrix(
                                        validation.iloc[validation_positions][
                                            list(feature_columns)
                                        ].astype(float)
                                    ),
                                )
                            bucket_importance[bucket] = _feature_importance(
                                model,
                                feature_columns,
                            )
                            bucket_rows[bucket] = int(len(train_positions))
                        if np.isnan(train_proba).any() or np.isnan(validation_proba).any():
                            raise ValueError("regime candidate did not cover every row")
                        polarity, train_pred = _best_train_polarity(train_proba, y_train)
                        validation_pred = _apply_polarity(validation_proba, polarity)
                        train_metrics = direction_accuracy_metrics(
                            train_pred,
                            y_train,
                            train.index,
                        )
                        validation_metrics = direction_accuracy_metrics(
                            validation_pred,
                            y_validation,
                            validation.index,
                        )
                        candidate = CryptoDirectionCandidate(
                            candidate_id=f"crypto-regime-{candidate_number:04d}",
                            model=str(spec["model"]),
                            params={
                                "partition": partition,
                                "feature_set": feature_set,
                                "model_params": dict(spec["params"]),
                                "bucket_rows": bucket_rows,
                            },
                            polarity=polarity,
                            train_metrics=train_metrics,
                            validation_metrics=validation_metrics,
                            feature_count=len(feature_columns),
                            rule=(
                                f"{spec['model']} specialists by {partition} using "
                                f"{feature_set}; "
                                f"{'invert probabilities' if polarity == 'inverted' else 'use raw probabilities'}"
                            ),
                        )
                        candidates.append(candidate)
                        _append_jsonl(candidates_path, candidate.to_dict())
                        if _passes_objective(
                            candidate,
                            config,
                            validation_metrics,
                            baselines_validation,
                        ):
                            objective_candidates.append(candidate)
                        if best_seen is None or _candidate_sort_key(candidate) > _candidate_sort_key(best_seen):
                            best_seen = candidate
                            best_predictions = (
                                _prediction_frame(
                                    train.index,
                                    y_train,
                                    train_proba,
                                    train_pred,
                                    polarity,
                                ),
                                _prediction_frame(
                                    validation.index,
                                    y_validation,
                                    validation_proba,
                                    validation_pred,
                                    polarity,
                                ),
                            )
                            best_importance = bucket_importance
                    except Exception as exc:
                        route_errors.append(
                            f"{partition}/{feature_set}/{spec['model']} candidate "
                            f"{candidate_number} failed: {exc}"
                        )
                    if candidate_number == 1 or candidate_number % 5 == 0:
                        top_now = sorted(candidates, key=_candidate_sort_key, reverse=True)[: config.top_n]
                        _append_jsonl(progress_path, {
                            "event": "progress",
                            "candidates_evaluated": candidate_number,
                            "elapsed_seconds": time.perf_counter() - started,
                            "best_train_accuracy": None
                            if not top_now
                            else top_now[0].train_metrics.accuracy,
                            "best_validation_accuracy": None
                            if not top_now or top_now[0].validation_metrics is None
                            else top_now[0].validation_metrics.accuracy,
                            "objective_candidates_found": len(objective_candidates),
                            "updated_at_utc": _now(),
                        })
                if candidate_number >= config.max_candidates:
                    break
            if candidate_number >= config.max_candidates:
                break

        top = tuple(sorted(candidates, key=_candidate_sort_key, reverse=True)[: config.top_n])
        best_train = top[0] if top else None
        if best_train is not None and best_predictions is not None:
            _write_parquet(train_pred_path, best_predictions[0])
            _write_parquet(validation_pred_path, best_predictions[1])
            _write_json(feature_importance_path, best_importance)
        objective_met = bool(objective_candidates)
        report = CryptoDirectionMLReport(
            status="objective_met" if objective_met else "completed",
            locked_opened=False,
            validation_used_for_selection=False,
            objective_met=objective_met,
            run_id=config.run_id,
            output_dir=str(output_dir),
            symbol=config.symbol,
            library=config.library,
            version=config.version,
            models=requested_models,
            workers=config.workers,
            train_period=_period_tuple(train),
            validation_period=_period_tuple(validation),
            locked_period=_period_tuple(locked),
            rows_train=len(train),
            rows_validation=len(validation),
            rows_locked=len(locked),
            used_columns=CRYPTO_5M_COLUMNS,
            feature_count=len(all_feature_columns),
            candidates_evaluated=len(candidates),
            baselines_train=baselines_train,
            baselines_validation=baselines_validation,
            best_train=best_train,
            objective_candidates=tuple(objective_candidates),
            top=top,
            route_errors=tuple(route_errors),
        )
        _write_json(best_path, report.to_dict())
        best_md_path.write_text(report_to_markdown(report), encoding="utf-8")
        _write_json(status_path, report.to_dict() | {
            "regime_search": True,
            "partitions": list(config.partitions),
            "feature_sets": list(config.feature_sets),
            "completed_at_utc": _now(),
            "elapsed_seconds": time.perf_counter() - started,
        })
        return report
    except Exception:
        error = traceback.format_exc()
        stderr_path.write_text(error, encoding="utf-8")
        _write_json(status_path, {
            "status": "error",
            "locked_opened": False,
            "validation_used_for_selection": False,
            "run_id": config.run_id,
            "error": error,
            "updated_at_utc": _now(),
        })
        raise


def run_crypto_direction_signal_search(
    config: CryptoDirectionSignalSearchConfig,
) -> CryptoDirectionSignalSearchReport:
    if not config.no_locked:
        raise ValueError("crypto-direction-signal-search v1 requires --no-locked")
    requested_models = tuple(_normalise_model_name(model) for model in config.models)
    _ensure_optional_models_available(requested_models)
    output_dir = _output_dir_signal(config)
    output_dir.mkdir(parents=True, exist_ok=True)
    status_path = output_dir / "status.json"
    progress_path = output_dir / "progress.jsonl"
    candidates_path = output_dir / "candidates.jsonl"
    best_path = output_dir / "best_candidates.json"
    best_md_path = output_dir / "best_candidates.md"
    train_signal_path = output_dir / "signals_train.parquet"
    validation_signal_path = output_dir / "signals_validation.parquet"
    feature_importance_path = output_dir / "feature_importance.json"
    stderr_path = output_dir / "stderr.log"
    for path in (
        status_path,
        progress_path,
        candidates_path,
        best_path,
        best_md_path,
        train_signal_path,
        validation_signal_path,
        feature_importance_path,
        stderr_path,
    ):
        if path.exists():
            path.unlink()
    stderr_path.write_text("", encoding="utf-8")
    started = time.perf_counter()
    _write_json(status_path, _status_payload(config, output_dir, "running") | {
        "signal_search": True,
        "horizons": list(config.horizons),
        "move_threshold_bps": list(config.move_threshold_bps),
    })

    try:
        frame = load_crypto_direction_frame(
            config.symbol,
            library=config.library,
            version=config.version,
        )
        features = build_crypto_direction_features(frame)
        candidates: list[CryptoDirectionSignalCandidate] = []
        objective_candidates: list[CryptoDirectionSignalCandidate] = []
        route_errors: list[str] = []
        best_seen: CryptoDirectionSignalCandidate | None = None
        best_signal_frames: tuple[pd.DataFrame, pd.DataFrame] | None = None
        best_importance: dict[str, Any] = {}
        first_train: pd.DataFrame | None = None
        first_validation: pd.DataFrame | None = None
        first_locked: pd.DataFrame | None = None

        for horizon in config.horizons:
            dataset = build_signal_dataset(features, frame["close"], horizon=int(horizon))
            train, validation, locked = split_direction_dataset(dataset, config)
            if first_train is None:
                first_train, first_validation, first_locked = train, validation, locked
            all_feature_columns = tuple(
                column
                for column in dataset.columns
                if column not in {"target_up", "future_return", "next_return"}
            )
            base_specs = _candidate_specs(
                CryptoDirectionMLConfig(
                    run_id=config.run_id,
                    models=requested_models,
                    max_candidates=max(config.max_model_candidates, 1),
                    seed=config.seed + int(horizon),
                ),
                requested_models,
            )
            y_train = train["target_up"].to_numpy(dtype=int)
            y_validation = validation["target_up"].to_numpy(dtype=int)
            for feature_set in config.feature_sets:
                feature_columns = select_feature_columns(all_feature_columns, feature_set)
                if not feature_columns:
                    route_errors.append(f"horizon {horizon}/{feature_set} skipped: no columns")
                    continue
                x_train = _fill_matrix(train[list(feature_columns)].astype(float))
                x_validation = _fill_matrix(validation[list(feature_columns)].astype(float))
                for spec in base_specs:
                    try:
                        model = _fit_model(spec, x_train, y_train, workers=config.workers)
                        train_proba = _predict_proba_up(model, spec["model"], x_train)
                        validation_proba = _predict_proba_up(
                            model,
                            spec["model"],
                            x_validation,
                        )
                        for side in config.sides:
                            for move_bps in config.move_threshold_bps:
                                for confidence in config.confidence_thresholds:
                                    for hour_window in config.hour_windows:
                                        train_metrics = evaluate_signal_rule(
                                            train_proba,
                                            train["future_return"].to_numpy(dtype=float),
                                            train.index,
                                            side=side,
                                            confidence_threshold=float(confidence),
                                            move_threshold_bps=float(move_bps),
                                            hour_window=hour_window,
                                        )
                                        if train_metrics.signal_count < config.min_train_signals:
                                            continue
                                        validation_metrics = evaluate_signal_rule(
                                            validation_proba,
                                            validation["future_return"].to_numpy(dtype=float),
                                            validation.index,
                                            side=side,
                                            confidence_threshold=float(confidence),
                                            move_threshold_bps=float(move_bps),
                                            hour_window=hour_window,
                                        )
                                        if (
                                            validation_metrics.signal_count
                                            < config.min_validation_signals
                                        ):
                                            continue
                                        candidate = CryptoDirectionSignalCandidate(
                                            candidate_id=(
                                                f"crypto-signal-{len(candidates) + 1:05d}"
                                            ),
                                            model=str(spec["model"]),
                                            params={
                                                "horizon": int(horizon),
                                                "feature_set": feature_set,
                                                "side": side,
                                                "confidence_threshold": float(confidence),
                                                "move_threshold_bps": float(move_bps),
                                                "hour_window": hour_window,
                                                "model_params": dict(spec["params"]),
                                            },
                                            train_metrics=train_metrics,
                                            validation_metrics=validation_metrics,
                                            feature_count=len(feature_columns),
                                            rule=(
                                                f"{spec['model']} horizon {horizon}; "
                                                f"{side} signals at confidence >= {confidence:.2f}; "
                                                f"move >= {move_bps:g} bps; {hour_window}"
                                            ),
                                        )
                                        candidates.append(candidate)
                                        _append_jsonl(candidates_path, candidate.to_dict())
                                        if _passes_signal_objective(candidate, config):
                                            objective_candidates.append(candidate)
                                        if (
                                            best_seen is None
                                            or _signal_candidate_sort_key(candidate)
                                            > _signal_candidate_sort_key(best_seen)
                                        ):
                                            best_seen = candidate
                                            best_signal_frames = (
                                                _signal_frame(
                                                    train.index,
                                                    train_proba,
                                                    train["future_return"].to_numpy(dtype=float),
                                                    side=side,
                                                    confidence_threshold=float(confidence),
                                                    move_threshold_bps=float(move_bps),
                                                    hour_window=hour_window,
                                                ),
                                                _signal_frame(
                                                    validation.index,
                                                    validation_proba,
                                                    validation["future_return"].to_numpy(dtype=float),
                                                    side=side,
                                                    confidence_threshold=float(confidence),
                                                    move_threshold_bps=float(move_bps),
                                                    hour_window=hour_window,
                                                ),
                                            )
                                            best_importance = _feature_importance(
                                                model,
                                                feature_columns,
                                            )
                                        if len(candidates) >= config.max_candidates:
                                            break
                                    if len(candidates) >= config.max_candidates:
                                        break
                                if len(candidates) >= config.max_candidates:
                                    break
                            if len(candidates) >= config.max_candidates:
                                break
                    except Exception as exc:
                        route_errors.append(
                            f"horizon {horizon}/{feature_set}/{spec['model']} failed: {exc}"
                        )
                    if len(candidates) == 1 or len(candidates) % 100 == 0:
                        top_now = sorted(
                            candidates,
                            key=_signal_candidate_sort_key,
                            reverse=True,
                        )[: config.top_n]
                        _append_jsonl(progress_path, {
                            "event": "progress",
                            "candidates_evaluated": len(candidates),
                            "elapsed_seconds": time.perf_counter() - started,
                            "best_train_precision": None
                            if not top_now
                            else top_now[0].train_metrics.precision,
                            "best_validation_precision": None
                            if not top_now or top_now[0].validation_metrics is None
                            else top_now[0].validation_metrics.precision,
                            "objective_candidates_found": len(objective_candidates),
                            "updated_at_utc": _now(),
                        })
                    if len(candidates) >= config.max_candidates:
                        break
                if len(candidates) >= config.max_candidates:
                    break
            if len(candidates) >= config.max_candidates:
                break

        top = tuple(
            sorted(candidates, key=_signal_candidate_sort_key, reverse=True)[: config.top_n]
        )
        best_train = top[0] if top else None
        if best_train is not None and best_signal_frames is not None:
            _write_parquet(train_signal_path, best_signal_frames[0])
            _write_parquet(validation_signal_path, best_signal_frames[1])
            _write_json(feature_importance_path, best_importance)
        objective_met = bool(objective_candidates)
        report = CryptoDirectionSignalSearchReport(
            status="objective_met" if objective_met else "completed",
            locked_opened=False,
            validation_used_for_selection=False,
            objective_met=objective_met,
            run_id=config.run_id,
            output_dir=str(output_dir),
            symbol=config.symbol,
            library=config.library,
            version=config.version,
            models=requested_models,
            workers=config.workers,
            train_period=_period_tuple(first_train if first_train is not None else pd.DataFrame()),
            validation_period=_period_tuple(
                first_validation if first_validation is not None else pd.DataFrame()
            ),
            locked_period=_period_tuple(first_locked if first_locked is not None else pd.DataFrame()),
            rows_train=0 if first_train is None else len(first_train),
            rows_validation=0 if first_validation is None else len(first_validation),
            rows_locked=0 if first_locked is None else len(first_locked),
            used_columns=CRYPTO_5M_COLUMNS,
            candidates_evaluated=len(candidates),
            best_train=best_train,
            objective_candidates=tuple(objective_candidates),
            top=top,
            route_errors=tuple(route_errors),
        )
        _write_json(best_path, report.to_dict())
        best_md_path.write_text(signal_report_to_markdown(report), encoding="utf-8")
        _write_json(status_path, report.to_dict() | {
            "signal_search": True,
            "horizons": list(config.horizons),
            "move_threshold_bps": list(config.move_threshold_bps),
            "confidence_thresholds": list(config.confidence_thresholds),
            "completed_at_utc": _now(),
            "elapsed_seconds": time.perf_counter() - started,
        })
        return report
    except Exception:
        error = traceback.format_exc()
        stderr_path.write_text(error, encoding="utf-8")
        _write_json(status_path, {
            "status": "error",
            "locked_opened": False,
            "validation_used_for_selection": False,
            "run_id": config.run_id,
            "error": error,
            "updated_at_utc": _now(),
        })
        raise


def load_crypto_direction_frame(
    symbol: str = "BTCUSDT",
    *,
    library: str = "crypto_5m",
    version: str = "binance_5m_36m",
) -> pd.DataFrame:
    store = TimeSeriesStore(base_data_dir() / "timeseries")
    source = store.read(library=library, symbol=symbol, version=version)
    columns = {str(column) for column in source.columns}
    forbidden = [
        column
        for column in columns
        if any(token in column.lower() for token in FORBIDDEN_COLUMN_TOKENS)
    ]
    if forbidden:
        raise ValueError(f"crypto-direction-ml source has forbidden columns: {sorted(forbidden)}")
    unknown = columns - set(CRYPTO_5M_COLUMNS)
    if unknown:
        raise ValueError(f"crypto-direction-ml source has unsupported columns: {sorted(unknown)}")
    missing = set(CRYPTO_5M_COLUMNS) - columns
    if missing:
        raise ValueError(f"crypto-direction-ml source missing columns: {sorted(missing)}")
    frame = source[list(CRYPTO_5M_COLUMNS)].copy()
    frame.index = pd.to_datetime(frame.index, utc=True)
    frame = frame.sort_index()
    frame = frame[~frame.index.duplicated(keep="last")]
    for column in frame.columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.dropna(subset=list(CRYPTO_5M_COLUMNS))


def _active_windows(frame: pd.DataFrame, windows: tuple[int, ...]) -> tuple[int, ...]:
    n_rows = len(frame)
    return tuple(int(window) for window in windows if n_rows > int(window) * 2)


def _add_if_present(out: pd.DataFrame, target: str, source: str) -> None:
    if source in out.columns:
        out[target] = out[source]


def _true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    previous_close = close.shift(1)
    ranges = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1)


def _rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / float(period), adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / float(period), adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def _adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0.0), up_move, 0.0),
        index=high.index,
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0.0), down_move, 0.0),
        index=high.index,
    )
    atr = _true_range(high, low, close).ewm(
        alpha=1.0 / float(period),
        adjust=False,
        min_periods=period,
    ).mean()
    plus_di = 100.0 * plus_dm.ewm(
        alpha=1.0 / float(period),
        adjust=False,
        min_periods=period,
    ).mean() / atr.replace(0.0, np.nan)
    minus_di = 100.0 * minus_dm.ewm(
        alpha=1.0 / float(period),
        adjust=False,
        min_periods=period,
    ).mean() / atr.replace(0.0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
    return dx.ewm(alpha=1.0 / float(period), adjust=False, min_periods=period).mean()


def _latest_store_frame(
    store: TimeSeriesStore,
    library: str,
    symbol: str,
) -> pd.DataFrame | None:
    try:
        versions = store.list_versions(library, symbol)
        if not versions:
            return None
        return store.read(library, symbol, version=versions[-1])
    except (FileNotFoundError, KeyError, ValueError):
        return None


def _numeric_series(frame: pd.DataFrame, preferred: tuple[str, ...]) -> pd.Series | None:
    for column in preferred:
        if column in frame.columns:
            return frame[column].astype(float)
    numeric = frame.select_dtypes(include=[np.number])
    if numeric.empty:
        return None
    return numeric.iloc[:, 0].astype(float)


def _causal_daily_indexed(series: pd.Series) -> pd.Series:
    daily = series.copy()
    index = pd.DatetimeIndex(daily.index)
    if index.tz is None:
        index = index.tz_localize("UTC")
    else:
        index = index.tz_convert("UTC")
    daily.index = index.normalize()
    return daily.sort_index()


def _align_daily_feature_to_5m(
    index: pd.DatetimeIndex,
    series: pd.Series,
    *,
    kind: str,
) -> pd.Series:
    daily = _causal_daily_indexed(series)
    if kind == "return":
        feature = daily.pct_change()
    elif kind == "change":
        feature = daily.diff()
    else:
        raise ValueError(f"unsupported external feature kind: {kind}")
    # Use yesterday's completed daily value. No same-day close leakage.
    feature = feature.shift(1)
    target_index = pd.DatetimeIndex(index)
    if target_index.tz is None:
        target_index = target_index.tz_localize("UTC")
    else:
        target_index = target_index.tz_convert("UTC")
    return feature.reindex(target_index, method="ffill")


def _daily_return_feature(
    store: TimeSeriesStore,
    library: str,
    symbol: str,
    index: pd.DatetimeIndex,
) -> pd.Series | None:
    frame = _latest_store_frame(store, library, symbol)
    if frame is None:
        return None
    series = _numeric_series(frame, ("close", "adj_close", "value"))
    if series is None:
        return None
    return _align_daily_feature_to_5m(index, series, kind="return")


def _daily_change_feature(
    store: TimeSeriesStore,
    library: str,
    symbol: str,
    index: pd.DatetimeIndex,
) -> pd.Series | None:
    frame = _latest_store_frame(store, library, symbol)
    if frame is None:
        return None
    series = _numeric_series(frame, ("value", "close", "adj_close"))
    if series is None:
        return None
    return _align_daily_feature_to_5m(index, series, kind="change")


def build_crypto_phase12_external_features(
    frame: pd.DataFrame,
    *,
    store: TimeSeriesStore | None = None,
    symbol: str = "BTCUSDT",
    external_version: str | None = None,
) -> pd.DataFrame:
    """Build external crypto features with causal daily lag where data exists.

    Missing external histories stay as explicit NaN columns; the function never
    invents funding, orderbook, liquidation, or on-chain data.
    """
    out = pd.DataFrame(index=frame.index)
    for column in EXTERNAL_CRYPTO_FEATURE_BACKLOG:
        out[column] = np.nan

    feature_store = store or TimeSeriesStore(base_data_dir() / "timeseries")
    index = pd.DatetimeIndex(frame.index)

    stored_external = _latest_store_frame(
        feature_store,
        "crypto_5m_external",
        symbol,
    ) if external_version is None else None
    if external_version is not None:
        try:
            stored_external = feature_store.read(
                "crypto_5m_external",
                symbol,
                version=external_version,
            )
        except (FileNotFoundError, KeyError, ValueError):
            stored_external = None
    if stored_external is not None:
        aligned = stored_external.reindex(index)
        for column in EXTERNAL_CRYPTO_FEATURE_BACKLOG:
            if column in aligned.columns:
                out[column] = aligned[column].astype(float)

    btc_daily = _latest_store_frame(feature_store, "crypto_daily", "BTCUSDT")
    eth_daily = _latest_store_frame(feature_store, "crypto_daily", "ETHUSDT")
    if btc_daily is not None and eth_daily is not None:
        btc_close = _numeric_series(btc_daily, ("close", "adj_close", "value"))
        eth_close = _numeric_series(eth_daily, ("close", "adj_close", "value"))
        if btc_close is not None and eth_close is not None:
            ratio = _causal_daily_indexed(eth_close) / _causal_daily_indexed(
                btc_close
            ).replace(0.0, np.nan)
            out["ethbtc_return"] = _align_daily_feature_to_5m(
                index,
                ratio,
                kind="return",
            )

    external_specs = {
        "dxy_return": ("fx_daily", "DXY", "return"),
        "nasdaq_return": ("prices_daily", "QQQ", "return"),
        "gold_return": ("prices_daily", "GLD", "return"),
        "us_10y_yield_change": ("macro_daily", "DGS10", "change"),
    }
    for column, (library, symbol, kind) in external_specs.items():
        if kind == "return":
            aligned = _daily_return_feature(feature_store, library, symbol, index)
        else:
            aligned = _daily_change_feature(feature_store, library, symbol, index)
        if aligned is not None:
            out[column] = aligned

    return out.replace([np.inf, -np.inf], np.nan)


def build_crypto_direction_features(frame: pd.DataFrame) -> pd.DataFrame:
    close = frame["close"].astype(float)
    open_ = frame["open"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    volume = frame["volume"].astype(float)
    candle_range = (high - low).replace(0.0, np.nan)
    safe_close = close.replace(0.0, np.nan)
    safe_low = low.replace(0.0, np.nan)
    returns_1 = close.pct_change()
    log_close = np.log(safe_close)
    out = pd.DataFrame(index=frame.index)

    for window in _active_windows(frame, PRICE_RETURN_WINDOWS):
        ret = close / close.shift(window) - 1.0
        out[f"ret_{window}"] = ret
        out[f"momentum_{window}"] = ret
        out[f"direction_{window}"] = np.where(close.diff(window) > 0.0, 1.0, -1.0)
        out[f"range_mean_{window}"] = (high / safe_low - 1.0).rolling(window).mean()
        out[f"distance_high_{window}"] = close / high.rolling(window).max() - 1.0
        out[f"distance_low_{window}"] = close / low.rolling(window).min() - 1.0

    out["log_ret_1"] = log_close.diff()
    out["close_to_open"] = close / open_.replace(0.0, np.nan) - 1.0
    out["high_low_range"] = high / safe_low - 1.0
    out["close_position_in_bar"] = (close - low) / candle_range
    out["body"] = out["close_to_open"]
    out["range"] = out["high_low_range"]
    out["close_position"] = out["close_position_in_bar"]
    out["upper_wick"] = (high - np.maximum(open_, close)) / candle_range
    out["lower_wick"] = (np.minimum(open_, close) - low) / candle_range

    for window in _active_windows(frame, TREND_WINDOWS):
        sma = close.rolling(window).mean()
        ema = close.ewm(span=window, adjust=False, min_periods=window).mean()
        out[f"sma_{window}"] = sma
        out[f"ema_{window}"] = ema
        out[f"price_vs_sma_{window}"] = close / sma.replace(0.0, np.nan) - 1.0
        out[f"trend_slope_{window}"] = (
            close / close.shift(window).replace(0.0, np.nan) - 1.0
        ) / float(window)
    if {"ema_12", "ema_48"} <= set(out.columns):
        out["ema_cross_12_48"] = out["ema_12"] / out["ema_48"].replace(0.0, np.nan) - 1.0
    if {"ema_48", "ema_288"} <= set(out.columns):
        out["ema_cross_48_288"] = out["ema_48"] / out["ema_288"].replace(0.0, np.nan) - 1.0

    for window in _active_windows(frame, VOLATILITY_WINDOWS):
        out[f"realized_vol_{window}"] = returns_1.rolling(window).std()
        out[f"parkinson_vol_{window}"] = (
            (np.log(high / safe_low) ** 2).rolling(window).mean() / (4.0 * np.log(2.0))
        ) ** 0.5
        downside = returns_1.where(returns_1 < 0.0, 0.0)
        upside = returns_1.where(returns_1 > 0.0, 0.0)
        out[f"downside_vol_{window}"] = downside.rolling(window).std()
        out[f"upside_vol_{window}"] = upside.rolling(window).std()
    if {"realized_vol_12", "realized_vol_288"} <= set(out.columns):
        out["vol_ratio_12_288"] = out["realized_vol_12"] / out["realized_vol_288"].replace(0.0, np.nan)
    if {"realized_vol_48", "realized_vol_2016"} <= set(out.columns):
        out["vol_ratio_48_2016"] = out["realized_vol_48"] / out["realized_vol_2016"].replace(0.0, np.nan)

    true_range = _true_range(high, low, close)
    out["atr_14"] = true_range.rolling(14).mean()
    if len(frame) > 288 * 2:
        out["atr_288"] = true_range.rolling(288).mean()

    for window in _active_windows(frame, (288, 2016)):
        rolling_high = high.rolling(window).max()
        rolling_low = low.rolling(window).min()
        out[f"rolling_max_{window}"] = rolling_high
        out[f"rolling_min_{window}"] = rolling_low
        out[f"drawdown_{window}"] = close / rolling_high.replace(0.0, np.nan) - 1.0
        out[f"distance_to_high_{window}"] = out[f"drawdown_{window}"]
        out[f"distance_to_low_{window}"] = close / rolling_low.replace(0.0, np.nan) - 1.0
        out[f"breakout_high_{window}"] = (close >= rolling_high.shift(1)).astype(float)
        out[f"breakdown_low_{window}"] = (close <= rolling_low.shift(1)).astype(float)

    out["volume"] = volume
    out["dollar_volume"] = close * volume
    for window in _active_windows(frame, (12, 48, 96, 288)):
        vol_mean = volume.rolling(window).mean().replace(0.0, np.nan)
        vol_std = volume.rolling(window).std().replace(0.0, np.nan)
        dollar_volume = out["dollar_volume"]
        dollar_mean = dollar_volume.rolling(window).mean()
        dollar_std = dollar_volume.rolling(window).std().replace(0.0, np.nan)
        out[f"volume_relative_{window}"] = volume / vol_mean - 1.0
        out[f"volume_change_{window}"] = volume / volume.shift(window).replace(0.0, np.nan) - 1.0
        out[f"volume_z_{window}"] = (volume - vol_mean) / vol_std
        out[f"volume_momentum_{window}"] = out[f"volume_change_{window}"]
        out[f"dollar_volume_z_{window}"] = (dollar_volume - dollar_mean) / dollar_std
    if {"volume_relative_12", "volume_relative_288"} <= set(out.columns):
        out["volume_ratio_12_288"] = (
            volume.rolling(12).mean() / volume.rolling(288).mean().replace(0.0, np.nan)
        )
    if len(frame) > 288 * 2:
        out["price_volume_corr_288"] = returns_1.rolling(288).corr(volume.pct_change())

    out["hl_spread_proxy"] = (high - low) / safe_close
    out["abs_return_per_volume"] = returns_1.abs() / volume.replace(0.0, np.nan)
    if len(frame) > 288 * 2:
        out["amihud_288"] = out["abs_return_per_volume"].rolling(288).mean()
        out["kyle_proxy_288"] = returns_1.rolling(288).cov(volume.diff()) / volume.diff().rolling(288).var()
    out["range_volume_ratio"] = out["high_low_range"] / volume.replace(0.0, np.nan)
    out["volume_shock_with_price_move"] = out.get("volume_z_288", out.get("volume_z_48", 0.0)) * returns_1.abs()
    out["illiquidity_spike"] = (
        out.get("amihud_288", out["abs_return_per_volume"])
        > out.get("amihud_288", out["abs_return_per_volume"]).rolling(288).quantile(0.95)
    ).astype(float)

    out["rsi_14"] = _rsi(close, 14)
    out["rsi_48"] = _rsi(close, 48)
    ema_12 = close.ewm(span=12, adjust=False, min_periods=12).mean()
    ema_26 = close.ewm(span=26, adjust=False, min_periods=26).mean()
    macd = ema_12 - ema_26
    out["macd_12_26_9"] = macd
    out["macd_signal_12_26_9"] = macd.ewm(span=9, adjust=False, min_periods=9).mean()
    mid_20 = close.rolling(20).mean()
    std_20 = close.rolling(20).std().replace(0.0, np.nan)
    out["bollinger_z_20"] = (close - mid_20) / std_20
    out["bollinger_width_20"] = (4.0 * std_20) / mid_20.replace(0.0, np.nan)
    out["stochastic_14"] = (close - low.rolling(14).min()) / (
        high.rolling(14).max() - low.rolling(14).min()
    ).replace(0.0, np.nan)
    typical = (high + low + close) / 3.0
    cci_mean = typical.rolling(20).mean()
    cci_mad = typical.rolling(20).apply(
        lambda values: float(np.mean(np.abs(values - np.mean(values)))),
        raw=True,
    ).replace(0.0, np.nan)
    out["cci_20"] = (typical - cci_mean) / (0.015 * cci_mad)
    out["adx_14"] = _adx(high, low, close, 14)

    index = pd.DatetimeIndex(frame.index)
    hour = index.hour.to_numpy(dtype=float)
    dow = index.dayofweek.to_numpy(dtype=float)
    out["hour_utc"] = hour
    out["day_of_week"] = dow
    out["hour_sin"] = np.sin(2.0 * np.pi * hour / 24.0)
    out["hour_cos"] = np.cos(2.0 * np.pi * hour / 24.0)
    out["dow_sin"] = np.sin(2.0 * np.pi * dow / 7.0)
    out["dow_cos"] = np.cos(2.0 * np.pi * dow / 7.0)
    out["is_weekend"] = (dow >= 5).astype(float)
    out["is_monday_utc"] = (dow == 0).astype(float)
    out["is_friday_utc"] = (dow == 4).astype(float)
    out["asia_session"] = ((hour >= 0) & (hour < 8)).astype(float)
    out["europe_session"] = ((hour >= 7) & (hour < 16)).astype(float)
    out["us_session"] = ((hour >= 13) & (hour < 22)).astype(float)
    out["session_overlap_eu_us"] = ((hour >= 13) & (hour < 16)).astype(float)
    out["month_end"] = index.is_month_end.astype(float)
    out["quarter_end"] = index.is_quarter_end.astype(float)

    _add_if_present(out, "ret_1h", "ret_12")
    _add_if_present(out, "ret_4h", "ret_48")
    _add_if_present(out, "ret_1d", "ret_288")
    _add_if_present(out, "trend_1h", "price_vs_sma_12")
    _add_if_present(out, "trend_4h", "price_vs_sma_48")
    _add_if_present(out, "trend_1d", "price_vs_sma_288")
    _add_if_present(out, "vol_1h", "realized_vol_12")
    _add_if_present(out, "vol_4h", "realized_vol_48")
    _add_if_present(out, "vol_1d", "realized_vol_288")
    _add_if_present(out, "volume_z_1h", "volume_z_12")
    _add_if_present(out, "volume_z_1d", "volume_z_288")
    if {"ret_24", "realized_vol_288"} <= set(out.columns):
        out["regime_trend_up"] = (out["ret_24"] > 0.0).astype(float)
        out["regime_high_vol"] = (
            out["realized_vol_288"] > out["realized_vol_288"].rolling(2016).median()
        ).astype(float)

    out = out.replace([np.inf, -np.inf], np.nan)
    return out


def build_crypto_all_features(
    frame: pd.DataFrame,
    *,
    store: TimeSeriesStore | None = None,
    symbol: str = "BTCUSDT",
    external_version: str | None = None,
) -> pd.DataFrame:
    """Build OHLCV features plus all explicit phase-12 external columns."""
    base = build_crypto_direction_features(frame)
    external = build_crypto_phase12_external_features(
        frame,
        store=store,
        symbol=symbol,
        external_version=external_version,
    )
    return base.join(external)


def build_crypto_5m_targets(
    frame: pd.DataFrame,
    *,
    horizons: tuple[int, ...] = TARGET_HORIZONS,
) -> pd.DataFrame:
    close = frame["close"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    out = pd.DataFrame(index=frame.index)
    for horizon in horizons:
        horizon = int(horizon)
        if horizon < 1:
            raise ValueError("target horizon must be >= 1")
        future_return = close.shift(-horizon) / close.replace(0.0, np.nan) - 1.0
        out[f"future_ret_{horizon}"] = future_return
        out[f"future_direction_{horizon}"] = (future_return > 0.0).astype(int)
    if 12 in tuple(int(h) for h in horizons):
        out["future_max_up_12"] = (
            high.shift(-1).rolling(12).max().shift(-11) / close.replace(0.0, np.nan) - 1.0
        )
        out["future_max_down_12"] = (
            low.shift(-1).rolling(12).min().shift(-11) / close.replace(0.0, np.nan) - 1.0
        )
        future_vol = close.pct_change().rolling(288).std().replace(0.0, np.nan)
        out["future_risk_adjusted_ret_12"] = out["future_ret_12"] / future_vol
    return out.replace([np.inf, -np.inf], np.nan)


def build_direction_dataset(features: pd.DataFrame, close: pd.Series) -> pd.DataFrame:
    target = (close.shift(-1) > close).astype(int)
    next_return = close.shift(-1) / close - 1.0
    joined = features.join(target.rename("target_up")).join(next_return.rename("next_return"))
    joined = joined.replace([np.inf, -np.inf], np.nan)
    joined = joined.dropna(subset=["target_up", "next_return"])
    feature_columns = [column for column in joined.columns if column not in {"target_up", "next_return"}]
    joined[feature_columns] = joined[feature_columns].replace([np.inf, -np.inf], np.nan)
    return joined.dropna(subset=feature_columns)


def build_signal_dataset(
    features: pd.DataFrame,
    close: pd.Series,
    *,
    horizon: int,
) -> pd.DataFrame:
    if int(horizon) < 1:
        raise ValueError("horizon must be >= 1")
    future_return = close.shift(-int(horizon)) / close - 1.0
    target = (future_return > 0.0).astype(int)
    joined = features.join(target.rename("target_up")).join(
        future_return.rename("future_return")
    )
    joined = joined.replace([np.inf, -np.inf], np.nan)
    joined = joined.dropna(subset=["target_up", "future_return"])
    feature_columns = [
        column for column in joined.columns if column not in {"target_up", "future_return"}
    ]
    joined[feature_columns] = joined[feature_columns].replace([np.inf, -np.inf], np.nan)
    return joined.dropna(subset=feature_columns)


def split_direction_dataset(
    dataset: pd.DataFrame,
    config: CryptoDirectionMLConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if not 0.0 < config.train_fraction < 1.0:
        raise ValueError("train_fraction must be between 0 and 1")
    if not 0.0 < config.validation_fraction < 1.0:
        raise ValueError("validation_fraction must be between 0 and 1")
    if config.train_fraction + config.validation_fraction >= 1.0:
        raise ValueError("train_fraction + validation_fraction must be < 1")
    n = len(dataset)
    train_end = int(n * config.train_fraction)
    validation_end = int(n * (config.train_fraction + config.validation_fraction))
    return dataset.iloc[:train_end], dataset.iloc[train_end:validation_end], dataset.iloc[validation_end:]


def select_feature_columns(
    all_feature_columns: tuple[str, ...],
    feature_set: str,
) -> tuple[str, ...]:
    feature_set = str(feature_set).strip().lower()
    if feature_set == "all":
        return tuple(all_feature_columns)
    if feature_set == "no_calendar":
        return tuple(
            column
            for column in all_feature_columns
            if not column.startswith(("hour_", "dow_"))
        )
    if feature_set == "short_price":
        prefixes = (
            "ret_1",
            "ret_2",
            "ret_3",
            "ret_6",
            "direction_1",
            "direction_2",
            "direction_3",
            "direction_6",
            "distance_high_1",
            "distance_high_2",
            "distance_high_3",
            "distance_high_6",
            "distance_low_1",
            "distance_low_2",
            "distance_low_3",
            "distance_low_6",
            "range_mean_1",
            "range_mean_2",
            "range_mean_3",
            "range_mean_6",
        )
        extras = {"body", "range", "close_position", "upper_wick", "lower_wick"}
        return tuple(
            column
            for column in all_feature_columns
            if column in extras or column.startswith(prefixes)
        )
    if feature_set == "medium_price":
        prefixes = (
            "ret_12",
            "ret_24",
            "ret_48",
            "ret_96",
            "direction_12",
            "direction_24",
            "direction_48",
            "direction_96",
            "distance_high_12",
            "distance_high_24",
            "distance_high_48",
            "distance_high_96",
            "distance_low_12",
            "distance_low_24",
            "distance_low_48",
            "distance_low_96",
            "range_mean_12",
            "range_mean_24",
            "range_mean_48",
            "range_mean_96",
        )
        return tuple(column for column in all_feature_columns if column.startswith(prefixes))
    if feature_set == "volume_candle":
        prefixes = ("volume_", "hour_", "dow_")
        extras = {"body", "range", "close_position", "upper_wick", "lower_wick"}
        return tuple(
            column
            for column in all_feature_columns
            if column in extras or column.startswith(prefixes)
        )
    raise ValueError(f"unknown crypto direction feature set: {feature_set}")


def build_regime_masks(
    dataset: pd.DataFrame,
    partition: str,
    *,
    reference: pd.DataFrame | None = None,
) -> dict[str, pd.Series]:
    partition = str(partition).strip().lower()
    reference = dataset if reference is None else reference
    index = pd.DatetimeIndex(dataset.index)
    if partition == "all":
        return {"all": pd.Series(True, index=dataset.index)}
    if partition == "hour_3":
        hours = pd.Series(index.hour, index=dataset.index)
        return {
            "utc_00_08": (hours >= 0) & (hours < 8),
            "utc_08_16": (hours >= 8) & (hours < 16),
            "utc_16_24": (hours >= 16) & (hours < 24),
        }
    if partition == "hour_6":
        hours = pd.Series(index.hour, index=dataset.index)
        return {
            "utc_00_06": (hours >= 0) & (hours < 6),
            "utc_06_12": (hours >= 6) & (hours < 12),
            "utc_12_18": (hours >= 12) & (hours < 18),
            "utc_18_24": (hours >= 18) & (hours < 24),
        }
    if partition == "volume_2":
        column = "volume_relative_48"
        threshold = float(reference[column].median())
        values = dataset[column]
        return {
            "volume_low": values <= threshold,
            "volume_high": values > threshold,
        }
    if partition == "range_2":
        column = "range_mean_12"
        threshold = float(reference[column].median())
        values = dataset[column]
        return {
            "range_low": values <= threshold,
            "range_high": values > threshold,
        }
    if partition == "trend_2":
        values = dataset["ret_24"]
        return {
            "trend_down": values <= 0.0,
            "trend_up": values > 0.0,
        }
    raise ValueError(f"unknown crypto direction regime partition: {partition}")


def direction_accuracy_metrics(
    predictions: np.ndarray,
    actual: np.ndarray,
    index: pd.DatetimeIndex,
) -> DirectionAccuracyMetrics:
    pred = np.asarray(predictions, dtype=int)
    y = np.asarray(actual, dtype=int)
    if len(y) == 0:
        return DirectionAccuracyMetrics(
            prediction_count=0,
            accuracy=0.0,
            up_accuracy=None,
            down_accuracy=None,
            actual_up_rate=0.0,
            predicted_up_rate=0.0,
            first_half_accuracy=None,
            second_half_accuracy=None,
            stability_accuracy=0.0,
            confusion={"tp": 0, "tn": 0, "fp": 0, "fn": 0},
            hourly_accuracy={},
        )
    hit = pred == y
    split = max(len(y) // 2, 1)
    first_half = float(hit[:split].mean()) if split else None
    second_half = float(hit[split:].mean()) if len(y) > split else None
    hours = pd.Index(index).hour
    hourly = {
        str(int(hour)): float(hit[np.asarray(hours == hour)].mean())
        for hour in sorted(set(int(value) for value in hours))
        if bool(np.any(np.asarray(hours == hour)))
    }
    predicted_up = pred == 1
    predicted_down = ~predicted_up
    return DirectionAccuracyMetrics(
        prediction_count=int(len(y)),
        accuracy=float(hit.mean()),
        up_accuracy=float(hit[predicted_up].mean()) if predicted_up.any() else None,
        down_accuracy=float(hit[predicted_down].mean()) if predicted_down.any() else None,
        actual_up_rate=float((y == 1).mean()),
        predicted_up_rate=float(predicted_up.mean()),
        first_half_accuracy=first_half,
        second_half_accuracy=second_half,
        stability_accuracy=min(
            first_half if first_half is not None else 0.0,
            second_half if second_half is not None else 0.0,
        ),
        confusion={
            "tp": int(np.sum((pred == 1) & (y == 1))),
            "tn": int(np.sum((pred == 0) & (y == 0))),
            "fp": int(np.sum((pred == 1) & (y == 0))),
            "fn": int(np.sum((pred == 0) & (y == 1))),
        },
        hourly_accuracy=hourly,
    )


def direction_baselines(actual: np.ndarray, index: pd.DatetimeIndex) -> dict[str, float]:
    y = np.asarray(actual, dtype=int)
    if len(y) == 0:
        return {
            "random_accuracy": 0.5,
            "always_up_accuracy": 0.0,
            "previous_direction_accuracy": 0.0,
            "inverse_previous_direction_accuracy": 0.0,
        }
    previous = np.roll(y, 1)
    previous[0] = 1
    return {
        "random_accuracy": 0.5,
        "always_up_accuracy": float((y == 1).mean()),
        "previous_direction_accuracy": float((previous == y).mean()),
        "inverse_previous_direction_accuracy": float((1 - previous == y).mean()),
    }


def evaluate_signal_rule(
    proba: np.ndarray,
    future_return: np.ndarray,
    index: pd.DatetimeIndex,
    *,
    side: str,
    confidence_threshold: float,
    move_threshold_bps: float,
    hour_window: str,
) -> SignalRuleMetrics:
    frame = _signal_frame(
        index,
        proba,
        future_return,
        side=side,
        confidence_threshold=confidence_threshold,
        move_threshold_bps=move_threshold_bps,
        hour_window=hour_window,
    )
    signals = frame[frame["signal"] != "none"]
    if signals.empty:
        return SignalRuleMetrics(
            signal_count=0,
            precision=0.0,
            coverage=0.0,
            average_signed_return=0.0,
            first_half_precision=None,
            second_half_precision=None,
            stability_precision=0.0,
            long_signals=0,
            short_signals=0,
        )
    hit = signals["hit"].to_numpy(dtype=bool)
    split_time = index[int(len(index) / 2)] if len(index) else None
    if split_time is None:
        first = signals
        second = signals.iloc[0:0]
    else:
        first = signals[signals.index < split_time]
        second = signals[signals.index >= split_time]
    first_precision = float(first["hit"].mean()) if not first.empty else None
    second_precision = float(second["hit"].mean()) if not second.empty else None
    return SignalRuleMetrics(
        signal_count=int(len(signals)),
        precision=float(hit.mean()),
        coverage=float(len(signals) / max(len(index), 1)),
        average_signed_return=float(signals["signed_return"].mean()),
        first_half_precision=first_precision,
        second_half_precision=second_precision,
        stability_precision=min(
            first_precision if first_precision is not None else 0.0,
            second_precision if second_precision is not None else 0.0,
        ),
        long_signals=int((signals["signal"] == "up").sum()),
        short_signals=int((signals["signal"] == "down").sum()),
    )


def report_to_markdown(report: CryptoDirectionMLReport) -> str:
    lines = [
        "# Crypto Direction ML",
        "",
        f"Run ID: `{report.run_id}`",
        f"Status: `{report.status}`",
        f"Locked opened: `{report.locked_opened}`",
        f"Objective met: `{report.objective_met}`",
        f"Models: `{', '.join(report.models)}`",
        f"Candidates evaluated: `{report.candidates_evaluated}`",
        "",
        "| Rank | Candidate | Model | Polarity | Train Acc | Valid Acc | Train Stable | Valid Stable |",
        "|---:|---|---|---|---:|---:|---:|---:|",
    ]
    for rank, candidate in enumerate(report.top, start=1):
        valid = candidate.validation_metrics
        lines.append(
            f"| {rank} | {candidate.candidate_id} | {candidate.model} | {candidate.polarity} | "
            f"{candidate.train_metrics.accuracy * 100:.2f}% | "
            f"{'' if valid is None else f'{valid.accuracy * 100:.2f}%'} | "
            f"{candidate.train_metrics.stability_accuracy * 100:.2f}% | "
            f"{'' if valid is None else f'{valid.stability_accuracy * 100:.2f}%'} |"
        )
    if report.objective_candidates:
        lines.extend(["", "## Objective Candidates", ""])
        for candidate in report.objective_candidates:
            valid = candidate.validation_metrics
            lines.append(
                f"- `{candidate.candidate_id}`: train "
                f"{candidate.train_metrics.accuracy * 100:.2f}%, validation "
                f"{0.0 if valid is None else valid.accuracy * 100:.2f}%"
            )
    if report.route_errors:
        lines.extend(["", "## Route errors", ""])
        lines.extend(f"- {error}" for error in report.route_errors)
    return "\n".join(lines) + "\n"


def signal_report_to_markdown(report: CryptoDirectionSignalSearchReport) -> str:
    lines = [
        "# Crypto Direction Signal Search",
        "",
        f"Run ID: `{report.run_id}`",
        f"Status: `{report.status}`",
        f"Locked opened: `{report.locked_opened}`",
        f"Objective met: `{report.objective_met}`",
        f"Candidates evaluated: `{report.candidates_evaluated}`",
        "",
        "| Rank | Candidate | Model | Train Precision | Valid Precision | Train Signals | Valid Signals | Rule |",
        "|---:|---|---|---:|---:|---:|---:|---|",
    ]
    for rank, candidate in enumerate(report.top, start=1):
        valid = candidate.validation_metrics
        lines.append(
            f"| {rank} | {candidate.candidate_id} | {candidate.model} | "
            f"{candidate.train_metrics.precision * 100:.2f}% | "
            f"{'' if valid is None else f'{valid.precision * 100:.2f}%'} | "
            f"{candidate.train_metrics.signal_count} | "
            f"{'' if valid is None else valid.signal_count} | "
            f"{candidate.rule} |"
        )
    if report.objective_candidates:
        lines.extend(["", "## Objective Candidates", ""])
        for candidate in report.objective_candidates:
            valid = candidate.validation_metrics
            lines.append(
                f"- `{candidate.candidate_id}`: train "
                f"{candidate.train_metrics.precision * 100:.2f}%, validation "
                f"{0.0 if valid is None else valid.precision * 100:.2f}%"
            )
    if report.route_errors:
        lines.extend(["", "## Route errors", ""])
        lines.extend(f"- {error}" for error in report.route_errors)
    return "\n".join(lines) + "\n"


def _candidate_specs(
    config: CryptoDirectionMLConfig,
    requested_models: tuple[str, ...],
) -> list[dict[str, Any]]:
    rng = random.Random(config.seed)
    specs: list[dict[str, Any]] = []
    model_templates = {
        "lightgbm": [
            {"n_estimators": 120, "learning_rate": 0.05, "num_leaves": 15, "max_depth": 3},
            {"n_estimators": 240, "learning_rate": 0.03, "num_leaves": 31, "max_depth": 5},
            {"n_estimators": 320, "learning_rate": 0.02, "num_leaves": 31, "max_depth": -1},
            {
                "n_estimators": 160,
                "learning_rate": 0.03,
                "num_leaves": 7,
                "max_depth": 2,
                "min_child_samples": 200,
                "subsample": 0.8,
                "colsample_bytree": 0.8,
            },
            {
                "n_estimators": 260,
                "learning_rate": 0.015,
                "num_leaves": 15,
                "max_depth": 4,
                "min_child_samples": 120,
                "subsample": 0.9,
                "colsample_bytree": 0.9,
                "reg_lambda": 1.0,
            },
            {
                "n_estimators": 420,
                "learning_rate": 0.01,
                "num_leaves": 31,
                "max_depth": 5,
                "min_child_samples": 80,
                "subsample": 0.8,
                "colsample_bytree": 0.8,
                "reg_alpha": 0.1,
                "reg_lambda": 2.0,
            },
        ],
        "xgboost": [
            {"n_estimators": 120, "learning_rate": 0.05, "max_depth": 3, "subsample": 0.8},
            {"n_estimators": 240, "learning_rate": 0.03, "max_depth": 4, "subsample": 0.8},
            {"n_estimators": 320, "learning_rate": 0.02, "max_depth": 5, "subsample": 0.9},
            {
                "n_estimators": 160,
                "learning_rate": 0.03,
                "max_depth": 2,
                "subsample": 0.8,
                "colsample_bytree": 0.8,
                "min_child_weight": 20,
            },
            {
                "n_estimators": 260,
                "learning_rate": 0.015,
                "max_depth": 4,
                "subsample": 0.9,
                "colsample_bytree": 0.9,
                "min_child_weight": 10,
                "reg_lambda": 1.0,
            },
            {
                "n_estimators": 420,
                "learning_rate": 0.01,
                "max_depth": 5,
                "subsample": 0.8,
                "colsample_bytree": 0.8,
                "min_child_weight": 5,
                "reg_alpha": 0.1,
                "reg_lambda": 2.0,
            },
        ],
        "logistic": [
            {"C": 0.01},
            {"C": 0.02},
            {"C": 0.05},
            {"C": 0.10},
            {"C": 0.20},
            {"C": 0.50},
        ],
    }
    for model in requested_models:
        for params in model_templates[model]:
            for balanced in (False, True):
                item = dict(params)
                item["balanced"] = balanced
                item["seed"] = rng.randint(1, 2_000_000_000)
                specs.append({"model": model, "params": item})
    return specs[: int(config.max_candidates)]


def _ensemble_specs(
    successful_routes: list[dict[str, Any]],
) -> list[tuple[str, np.ndarray, np.ndarray, list[str]]]:
    by_model: dict[str, CryptoDirectionCandidate] = {}
    payload_by_id: dict[str, dict[str, Any]] = {}
    for payload in successful_routes:
        candidate = payload["candidate"]
        if not isinstance(candidate, CryptoDirectionCandidate):
            continue
        current = by_model.get(candidate.model)
        if current is None or _candidate_sort_key(candidate) > _candidate_sort_key(current):
            by_model[candidate.model] = candidate
            payload_by_id[candidate.candidate_id] = payload
    if "lightgbm" not in by_model or "xgboost" not in by_model:
        return []

    lightgbm = by_model["lightgbm"]
    xgboost = by_model["xgboost"]
    lightgbm_payload = payload_by_id[lightgbm.candidate_id]
    xgboost_payload = payload_by_id[xgboost.candidate_id]
    train_a = np.asarray(lightgbm_payload["train_proba"], dtype=np.float64)
    train_b = np.asarray(xgboost_payload["train_proba"], dtype=np.float64)
    validation_a = np.asarray(lightgbm_payload["validation_proba"], dtype=np.float64)
    validation_b = np.asarray(xgboost_payload["validation_proba"], dtype=np.float64)
    sources = [lightgbm.candidate_id, xgboost.candidate_id]
    average_train = (train_a + train_b) / 2.0
    average_validation = (validation_a + validation_b) / 2.0
    vote_train = ((train_a >= 0.5).astype(float) + (train_b >= 0.5).astype(float)) / 2.0
    vote_validation = (
        (validation_a >= 0.5).astype(float) + (validation_b >= 0.5).astype(float)
    ) / 2.0
    return [
        ("ensemble_average", average_train, average_validation, sources),
        ("ensemble_vote", vote_train, vote_validation, sources),
    ]


def _fit_model(spec: dict[str, Any], x_train: Any, y_train: np.ndarray, *, workers: int):
    model = str(spec["model"])
    params = dict(spec["params"])
    seed = int(params.pop("seed", 42))
    balanced = bool(params.pop("balanced", False))
    if len(set(np.asarray(y_train, dtype=int).tolist())) < 2:
        raise ValueError("train labels contain only one class")
    if model == "lightgbm":
        module = importlib.import_module("lightgbm")
        clf = module.LGBMClassifier(
            objective="binary",
            random_state=seed,
            n_jobs=max(1, int(workers)),
            class_weight="balanced" if balanced else None,
            verbosity=-1,
            **params,
        )
    elif model == "xgboost":
        module = importlib.import_module("xgboost")
        clf = module.XGBClassifier(
            objective="binary:logistic",
            random_state=seed,
            n_jobs=max(1, int(workers)),
            eval_metric="logloss",
            scale_pos_weight=_scale_pos_weight(y_train) if balanced else 1.0,
            **params,
        )
    elif model == "logistic":
        linear_model = importlib.import_module("sklearn.linear_model")
        pipeline = importlib.import_module("sklearn.pipeline")
        preprocessing = importlib.import_module("sklearn.preprocessing")
        clf = pipeline.make_pipeline(
            preprocessing.StandardScaler(),
            linear_model.LogisticRegression(
                max_iter=1000,
                random_state=seed,
                class_weight="balanced" if balanced else None,
                **params,
            ),
        )
    else:
        raise ValueError(f"unknown crypto direction model: {model}")
    clf.fit(x_train, y_train)
    return clf


def _predict_proba_up(model: Any, model_name: str, x_predict: Any) -> np.ndarray:
    proba = model.predict_proba(x_predict)
    if proba.ndim != 2 or proba.shape[1] < 2:
        raise ValueError(f"{model_name} did not return binary probabilities")
    return np.asarray(proba[:, 1], dtype=np.float64)


def _best_train_polarity(proba: np.ndarray, actual: np.ndarray) -> tuple[str, np.ndarray]:
    raw = (np.asarray(proba) >= 0.5).astype(int)
    inverted = 1 - raw
    raw_acc = float((raw == actual).mean())
    inverted_acc = float((inverted == actual).mean())
    if inverted_acc > raw_acc:
        return "inverted", inverted
    return "raw", raw


def _apply_polarity(proba: np.ndarray, polarity: str) -> np.ndarray:
    raw = (np.asarray(proba) >= 0.5).astype(int)
    return 1 - raw if str(polarity) == "inverted" else raw


def _prediction_frame(
    index: pd.DatetimeIndex,
    actual: np.ndarray,
    proba: np.ndarray,
    prediction: np.ndarray,
    polarity: str,
) -> pd.DataFrame:
    out = pd.DataFrame(index=index)
    out["actual_up"] = np.asarray(actual, dtype=int)
    out["prob_up"] = np.asarray(proba, dtype=float)
    out["predicted_up"] = np.asarray(prediction, dtype=int)
    out["hit"] = out["actual_up"] == out["predicted_up"]
    out["polarity"] = polarity
    return out


def _signal_frame(
    index: pd.DatetimeIndex,
    proba: np.ndarray,
    future_return: np.ndarray,
    *,
    side: str,
    confidence_threshold: float,
    move_threshold_bps: float,
    hour_window: str,
) -> pd.DataFrame:
    proba_arr = np.asarray(proba, dtype=float)
    returns = np.asarray(future_return, dtype=float)
    side = str(side).strip().lower()
    if side not in {"up", "down", "both"}:
        raise ValueError(f"unknown signal side: {side}")
    threshold = float(confidence_threshold)
    if threshold < 0.5 or threshold > 1.0:
        raise ValueError("confidence_threshold must be between 0.5 and 1.0")
    move_threshold = float(move_threshold_bps) / 10_000.0
    hour_mask = _hour_window_mask(pd.DatetimeIndex(index), hour_window)
    signal = np.full(len(proba_arr), "none", dtype=object)
    if side in {"up", "both"}:
        signal[(proba_arr >= threshold) & hour_mask] = "up"
    if side in {"down", "both"}:
        signal[(proba_arr <= (1.0 - threshold)) & hour_mask] = "down"
    out = pd.DataFrame(index=index)
    out["prob_up"] = proba_arr
    out["future_return"] = returns
    out["signal"] = signal
    out["confidence"] = np.where(signal == "down", 1.0 - proba_arr, proba_arr)
    out["hit"] = np.where(
        signal == "up",
        returns > move_threshold,
        np.where(signal == "down", returns < -move_threshold, False),
    )
    out["signed_return"] = np.where(
        signal == "up",
        returns,
        np.where(signal == "down", -returns, 0.0),
    )
    out["hour_window"] = hour_window
    out["move_threshold_bps"] = float(move_threshold_bps)
    out["confidence_threshold"] = threshold
    return out


def _hour_window_mask(index: pd.DatetimeIndex, hour_window: str) -> np.ndarray:
    item = str(hour_window).strip().lower()
    if item == "all":
        return np.ones(len(index), dtype=bool)
    if not item.startswith("utc_"):
        raise ValueError(f"unknown hour window: {hour_window}")
    parts = item.removeprefix("utc_").split("_")
    if len(parts) != 2:
        raise ValueError(f"unknown hour window: {hour_window}")
    start = int(parts[0])
    end = int(parts[1])
    hours = np.asarray(pd.Index(index).hour, dtype=int)
    if start <= end:
        return (hours >= start) & (hours < end)
    return (hours >= start) | (hours < end)


def _passes_objective(
    candidate: CryptoDirectionCandidate,
    config: CryptoDirectionMLConfig,
    validation_metrics: DirectionAccuracyMetrics,
    validation_baselines: dict[str, float],
) -> bool:
    baseline = max(validation_baselines.values()) if validation_baselines else 0.5
    return (
        candidate.train_metrics.accuracy >= float(config.target_accuracy)
        and validation_metrics.accuracy >= float(config.target_accuracy)
        and validation_metrics.accuracy > baseline
    )


def _passes_signal_objective(
    candidate: CryptoDirectionSignalCandidate,
    config: CryptoDirectionSignalSearchConfig,
) -> bool:
    validation = candidate.validation_metrics
    return (
        validation is not None
        and candidate.train_metrics.precision >= float(config.target_accuracy)
        and validation.precision >= float(config.target_accuracy)
        and candidate.train_metrics.signal_count >= int(config.min_train_signals)
        and validation.signal_count >= int(config.min_validation_signals)
    )


def _candidate_sort_key(candidate: CryptoDirectionCandidate) -> tuple[float, float, int]:
    return (
        candidate.train_metrics.accuracy,
        candidate.train_metrics.stability_accuracy,
        candidate.train_metrics.prediction_count,
    )


def _signal_candidate_sort_key(
    candidate: CryptoDirectionSignalCandidate,
) -> tuple[float, float, int, float]:
    return (
        candidate.train_metrics.precision,
        candidate.train_metrics.stability_precision,
        candidate.train_metrics.signal_count,
        candidate.train_metrics.average_signed_return,
    )


def _feature_importance(model: Any, feature_columns: tuple[str, ...]) -> dict[str, Any]:
    values = getattr(model, "feature_importances_", None)
    if values is None:
        return {}
    pairs = sorted(
        zip(feature_columns, [float(value) for value in values], strict=False),
        key=lambda item: item[1],
        reverse=True,
    )
    return {"top": [{"feature": name, "importance": value} for name, value in pairs[:50]]}


def _ensure_optional_models_available(models: tuple[str, ...]) -> None:
    missing: list[str] = []
    for model in models:
        package = {
            "lightgbm": "lightgbm",
            "xgboost": "xgboost",
            "logistic": "sklearn.linear_model",
        }[model]
        try:
            importlib.import_module(package)
        except Exception:
            missing.append(model)
    if missing:
        raise OptionalModelMissing(
            "Missing optional crypto direction ML dependencies: "
            f"{', '.join(missing)}. Install with: pip install lightgbm xgboost scikit-learn"
        )


def _normalise_model_name(model: str) -> str:
    item = str(model).strip().lower()
    aliases = {"lgbm": "lightgbm", "xgb": "xgboost", "logreg": "logistic"}
    item = aliases.get(item, item)
    if item not in {"lightgbm", "xgboost", "logistic"}:
        raise ValueError(f"unknown crypto direction model: {model}")
    return item


def _scale_pos_weight(y_train: np.ndarray) -> float:
    y = np.asarray(y_train, dtype=int)
    positives = max(float(np.sum(y == 1)), 1.0)
    negatives = max(float(np.sum(y == 0)), 1.0)
    return negatives / positives


def _fill_matrix(values: Any) -> Any:
    if isinstance(values, pd.DataFrame):
        return values.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    arr = np.asarray(values, dtype=np.float64)
    return np.where(np.isfinite(arr), arr, 0.0)


def _period_tuple(frame: pd.DataFrame) -> tuple[str, str]:
    if frame.empty:
        return ("", "")
    return (str(pd.Timestamp(frame.index.min())), str(pd.Timestamp(frame.index.max())))


def _output_dir(config: CryptoDirectionMLConfig) -> Path:
    root = Path(config.run_root) if config.run_root else base_data_dir() / "agent_loop"
    return root / config.run_id / "crypto_direction_ml"


def _output_dir_regime(config: CryptoDirectionMLRegimeConfig) -> Path:
    root = Path(config.run_root) if config.run_root else base_data_dir() / "agent_loop"
    return root / config.run_id / "crypto_direction_ml_regime"


def _output_dir_signal(config: CryptoDirectionSignalSearchConfig) -> Path:
    root = Path(config.run_root) if config.run_root else base_data_dir() / "agent_loop"
    return root / config.run_id / "crypto_direction_signal_search"


def _status_payload(
    config: CryptoDirectionMLConfig,
    output_dir: Path,
    status: str,
) -> dict[str, Any]:
    return {
        "status": status,
        "locked_opened": False,
        "validation_used_for_selection": False,
        "run_id": config.run_id,
        "output_dir": str(output_dir),
        "symbol": config.symbol,
        "library": config.library,
        "version": config.version,
        "models": list(config.models),
        "target_accuracy": config.target_accuracy,
        "updated_at_utc": _now(),
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, default=str) + "\n")


def _write_parquet(path: Path, frame: pd.DataFrame) -> None:
    frame.to_parquet(path, engine="pyarrow", compression="snappy")


def _now() -> str:
    return pd.Timestamp.now(tz="UTC").isoformat()


__all__ = [
    "CryptoDirectionMLConfig",
    "CryptoDirectionMLRegimeConfig",
    "CryptoDirectionMLReport",
    "CryptoDirectionSignalSearchConfig",
    "CryptoDirectionSignalSearchReport",
    "OptionalModelMissing",
    "build_regime_masks",
    "build_crypto_all_features",
    "build_crypto_direction_features",
    "build_crypto_phase12_external_features",
    "build_crypto_5m_targets",
    "build_direction_dataset",
    "build_signal_dataset",
    "direction_accuracy_metrics",
    "direction_baselines",
    "evaluate_signal_rule",
    "load_crypto_direction_frame",
    "report_to_markdown",
    "run_crypto_direction_ml",
    "run_crypto_direction_ml_regime_search",
    "run_crypto_direction_signal_search",
    "select_feature_columns",
    "signal_report_to_markdown",
    "split_direction_dataset",
]
