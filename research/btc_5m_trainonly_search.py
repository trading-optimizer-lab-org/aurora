"""Train-only BTC 5m strategy search across five fair methods.

The search contract is intentionally strict:

* train is the only optimization period;
* validation is report-only;
* locked is never read for scoring or selection.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from aurora.core.metrics import compute_metrics
from aurora.core.runtime_paths import base_data_dir
from aurora.data_contracts.timeseries_store import TimeSeriesStore
from aurora.research.crypto_direction_ml import build_crypto_all_features


BTC_5M_PPY = 365 * 24 * 12
METHODS = ("dehb_real", "genetic", "beam", "bandit", "github_ml")
SIZE_GRID = (0.25, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0)
FORBIDDEN_TOKENS = ("locked", "future", "target", "label", "prediction")


@dataclass(frozen=True)
class BTC5mSearchConfig:
    run_id: str = "btc_5m_all_features_5methods_trainonly_1h_180jobs"
    symbol: str = "BTCUSDT"
    library: str = "crypto_5m"
    version: str = "binance_5m_36m"
    external_version: str = "binance_5m_36m_phase12_v2"
    train_start: str = "2023-05-01"
    train_end: str = "2024-04-30 23:55:00+00:00"
    validation_start: str = "2024-05-01"
    validation_end: str = "2025-04-30 23:55:00+00:00"
    locked_start: str = "2025-05-01"
    max_leverage: float = 5.0
    size_grid: tuple[float, ...] = SIZE_GRID
    min_train_trades_per_month: float = 1.0
    max_train_trades_per_month: float | None = None
    max_features_per_candidate: int = 6
    top_rows_per_stage: int = 500
    random_seed: int = 7301501
    min_train_non_null: int = 100
    max_feature_columns: int = 320


def run_stage(
    config: BTC5mSearchConfig,
    *,
    method: str,
    stage: int,
    total_stages: int,
    time_budget_minutes: float,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    if method not in METHODS:
        raise ValueError(f"unknown BTC 5m method: {method}")
    dataset, audit = load_dataset(config)
    seed = int(config.random_seed + stage * 10_000 + _method_offset(method))
    rng = np.random.default_rng(seed)
    start = time.monotonic()
    deadline = start + max(1.0, float(time_budget_minutes) * 60.0)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    iteration = 0

    while time.monotonic() < deadline or iteration == 0:
        specs = _candidate_specs(dataset, config, method=method, stage=stage, total_stages=total_stages, rng=rng, iteration=iteration)
        if not specs:
            break
        for spec in specs:
            if rows and time.monotonic() >= deadline:
                break
            row = evaluate_spec(dataset, config, spec)
            if row["candidate_id"] in seen:
                continue
            seen.add(str(row["candidate_id"]))
            row["method"] = method
            row["stage"] = int(stage)
            row["total_stages"] = int(total_stages)
            row["candidates_evaluated"] = int(len(rows) + 1)
            row["elapsed_seconds"] = float(time.monotonic() - start)
            rows.append(row)
        iteration += 1
        if len(rows) >= max(config.top_rows_per_stage * 4, config.top_rows_per_stage):
            break

    rows = sorted(rows, key=lambda item: float(item.get("train_score", -math.inf)), reverse=True)
    rows = rows[: int(config.top_rows_per_stage)]
    meta = {
        "run_id": config.run_id,
        "method": method,
        "stage": int(stage),
        "total_stages": int(total_stages),
        "rows": len(rows),
        "candidates_unique": len({row["candidate_id"] for row in rows}),
        "time_budget_minutes": float(time_budget_minutes),
        "locked_opened": False,
        "validation_role": "report_only",
        "optimization_period": "train",
        "validation_used_for_selection": False,
    }
    return rows, meta, audit


def load_dataset(config: BTC5mSearchConfig) -> tuple[dict[str, Any], dict[str, Any]]:
    store = TimeSeriesStore(base_data_dir() / "timeseries")
    frame = store.read(config.library, config.symbol, version=config.version)
    frame = _normalize_datetime_index(frame).sort_index()
    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"BTC 5m source missing columns: {sorted(missing)}")
    source = frame[["open", "high", "low", "close", "volume"]].astype(float)
    features = build_crypto_all_features(
        source,
        store=store,
        symbol=config.symbol,
        external_version=config.external_version,
    )
    features = _normalize_datetime_index(features).sort_index()
    _assert_no_forbidden_features(features)

    close = source["close"].astype(float)
    next_returns = close.shift(-1) / close - 1.0
    train_mask = _between(features.index, config.train_start, config.train_end)
    validation_mask = _between(features.index, config.validation_start, config.validation_end)
    locked_mask = features.index >= _ts(config.locked_start)

    selected, dropped = _select_usable_features(
        features.loc[train_mask],
        next_returns.loc[features.index[train_mask]],
        min_train_non_null=int(config.min_train_non_null),
        max_columns=int(config.max_feature_columns),
    )
    if not selected:
        raise ValueError("no usable BTC 5m feature columns after train-only audit")

    train_features = features.loc[train_mask, selected]
    validation_features = features.loc[validation_mask, selected]
    train_returns = next_returns.loc[train_features.index]
    validation_returns = next_returns.loc[validation_features.index]
    train_features, validation_features = _impute_and_standardize(train_features, validation_features)
    train_features, train_returns = _drop_unusable_return_rows(train_features, train_returns)
    validation_features, validation_returns = _drop_unusable_return_rows(validation_features, validation_returns)

    audit = {
        "symbol": config.symbol,
        "library": config.library,
        "version": config.version,
        "external_version": config.external_version,
        "rows_source": int(len(source)),
        "rows_train": int(len(train_features)),
        "rows_validation": int(len(validation_features)),
        "rows_locked_declared": int(np.sum(locked_mask)),
        "feature_columns_raw": int(features.shape[1]),
        "feature_columns_used": int(len(selected)),
        "feature_columns_used_names": list(selected),
        "dropped_features": dropped,
        "locked_opened": False,
        "validation_role": "report_only",
    }
    return {
        "train_x": train_features,
        "valid_x": validation_features,
        "train_returns": train_returns.to_numpy(dtype=np.float64),
        "valid_returns": validation_returns.to_numpy(dtype=np.float64),
        "train_index": pd.DatetimeIndex(train_features.index),
        "valid_index": pd.DatetimeIndex(validation_features.index),
        "feature_names": tuple(selected),
    }, audit


def evaluate_spec(dataset: dict[str, Any], config: BTC5mSearchConfig, spec: dict[str, Any]) -> dict[str, Any]:
    train_scores = _scores_for_spec(dataset["train_x"], dataset["train_returns"], spec)
    valid_scores = _scores_for_spec(dataset["valid_x"], dataset["valid_returns"], spec, fit_payload=spec.get("_fit_payload"))
    train_positions_1x = positions_from_scores(train_scores, threshold=float(spec["threshold"]))
    valid_positions_1x = positions_from_scores(valid_scores, threshold=float(spec["threshold"]))

    train_1x = strategy_metrics(dataset["train_returns"], train_positions_1x, dataset["train_index"], size=1.0)
    size, train_sized = choose_train_size(dataset["train_returns"], train_positions_1x, dataset["train_index"], config)
    valid_sized = strategy_metrics(dataset["valid_returns"], valid_positions_1x, dataset["valid_index"], size=size)
    valid_1x = strategy_metrics(dataset["valid_returns"], valid_positions_1x, dataset["valid_index"], size=1.0)
    fail_reason = train_fail_reason(train_sized, config)
    train_score = train_only_score(train_sized) if fail_reason == "" else -1_000_000.0 + train_only_score(train_sized)
    public_spec = {key: value for key, value in spec.items() if not key.startswith("_")}
    candidate_id = candidate_id_from_spec(public_spec)
    row: dict[str, Any] = {
        "candidate_id": candidate_id,
        "source_method": spec["method"],
        "rule": json.dumps(public_spec, sort_keys=True, default=str),
        "features": ",".join(spec.get("features", ())),
        "feature_count": int(len(spec.get("features", ()))),
        "threshold": float(spec["threshold"]),
        "position_size": float(size),
        "max_leverage": float(config.max_leverage),
        "train_score": float(train_score),
        "verified": fail_reason == "",
        "rejection_reason": fail_reason,
        "locked_opened": False,
        "validation_role": "report_only",
        "validation_used_for_selection": False,
    }
    row.update(_prefix_metrics("train_1x", train_1x))
    row.update(_prefix_metrics("validation_1x", valid_1x))
    row.update(_prefix_metrics("train", train_sized))
    row.update(_prefix_metrics("validation", valid_sized))
    return row


def positions_from_scores(scores: np.ndarray, *, threshold: float) -> np.ndarray:
    arr = np.asarray(scores, dtype=np.float64)
    threshold = abs(float(threshold))
    pos = np.zeros(len(arr), dtype=np.float64)
    pos[arr >= threshold] = 1.0
    pos[arr <= -threshold] = -1.0
    return pos


def choose_train_size(
    next_returns: np.ndarray,
    positions_1x: np.ndarray,
    index: pd.DatetimeIndex,
    config: BTC5mSearchConfig,
) -> tuple[float, dict[str, float]]:
    best_size = 1.0
    best_metrics = strategy_metrics(next_returns, positions_1x, index, size=1.0)
    best_score = train_only_score(best_metrics)
    for size in config.size_grid:
        size = float(size)
        if size > float(config.max_leverage):
            continue
        metrics = strategy_metrics(next_returns, positions_1x, index, size=size)
        if metrics["min_nav"] <= 0.0 or not np.isfinite(metrics["final_nav"]):
            continue
        score = train_only_score(metrics)
        if score > best_score:
            best_score = score
            best_size = size
            best_metrics = metrics
    return best_size, best_metrics


def strategy_metrics(
    next_returns: np.ndarray,
    positions_1x: np.ndarray,
    index: pd.DatetimeIndex,
    *,
    size: float,
) -> dict[str, float]:
    returns = np.asarray(next_returns, dtype=np.float64)
    positions = np.asarray(positions_1x, dtype=np.float64) * float(size)
    strategy = positions * returns
    finite = np.isfinite(strategy)
    strategy = strategy[finite]
    pos = positions[finite]
    idx = pd.DatetimeIndex(index[finite])
    if len(strategy) < 2:
        return _empty_metrics()
    nav = np.cumprod(1.0 + strategy)
    if np.any(nav <= 0.0):
        min_nav = float(np.min(nav))
    else:
        min_nav = float(np.min(nav))
    metrics = compute_metrics(strategy, ppy=BTC_5M_PPY)
    trades = int(np.sum(np.abs(np.diff(pos)) > 1e-12)) if len(pos) > 1 else 0
    months = _months_between(idx)
    months_positive = _positive_month_pct(strategy, idx)
    return {
        "cagr": float(metrics.cagr) / 100.0,
        "sharpe": float(metrics.sharpe),
        "calmar": float(metrics.calmar),
        "max_drawdown": float(metrics.mdd) / 100.0,
        "profit_factor": _profit_factor(strategy),
        "trades": float(trades),
        "trades_per_month": float(trades / months) if months > 0 else 0.0,
        "win_rate": float(metrics.win_rate),
        "final_nav": float(metrics.final_nav),
        "months_positive_pct": float(months_positive),
        "min_nav": min_nav,
    }


def train_only_score(metrics: dict[str, float]) -> float:
    calmar = _finite_or(metrics.get("calmar"), -100.0)
    sharpe = _finite_or(metrics.get("sharpe"), -100.0)
    cagr = _finite_or(metrics.get("cagr"), -1.0)
    pf = min(_finite_or(metrics.get("profit_factor"), 0.0), 10.0)
    mdd_penalty = abs(min(_finite_or(metrics.get("max_drawdown"), 0.0), 0.0))
    return float(calmar + 0.25 * sharpe + 2.0 * cagr + 0.05 * pf - 0.25 * mdd_penalty)


def train_fail_reason(metrics: dict[str, float], config: BTC5mSearchConfig) -> str:
    if metrics["min_nav"] <= 0.0:
        return "train_nav_wipeout"
    if metrics["final_nav"] <= 1.0:
        return "train_final_nav"
    if metrics["profit_factor"] <= 1.0:
        return "train_profit_factor"
    if metrics["trades_per_month"] < float(config.min_train_trades_per_month):
        return "train_too_few_trades"
    if config.max_train_trades_per_month is not None and metrics["trades_per_month"] > float(config.max_train_trades_per_month):
        return "train_too_many_trades"
    return ""


def candidate_id_from_spec(spec: dict[str, Any]) -> str:
    raw = json.dumps(spec, sort_keys=True, default=str, separators=(",", ":"))
    return "btc_5m_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def merge_stage_rows(rows: list[pd.DataFrame]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    merged = pd.concat(rows, ignore_index=True)
    if "candidate_id" not in merged.columns:
        return merged
    merged = merged.sort_values("train_score", ascending=False)
    return merged.drop_duplicates("candidate_id", keep="first").reset_index(drop=True)


def method_summary(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["method", "rows", "unique_candidates", "verified", "verified_per_1000_unique"])
    rows = []
    for method, group in frame.groupby("method", dropna=False):
        unique = int(group["candidate_id"].nunique())
        verified = int(group.get("verified", pd.Series(dtype=bool)).astype(bool).sum())
        rows.append(
            {
                "method": method,
                "rows": int(len(group)),
                "unique_candidates": unique,
                "verified": verified,
                "verified_per_1000_unique": float(verified / unique * 1000.0) if unique else 0.0,
                "top_train_score": float(pd.to_numeric(group["train_score"], errors="coerce").max()),
                "top_validation_sharpe": float(pd.to_numeric(group["validation_sharpe"], errors="coerce").max()),
                "mean_validation_sharpe": float(pd.to_numeric(group["validation_sharpe"], errors="coerce").mean()),
                "locked_opened": False,
            }
        )
    return pd.DataFrame(rows).sort_values("method").reset_index(drop=True)


def _candidate_specs(
    dataset: dict[str, Any],
    config: BTC5mSearchConfig,
    *,
    method: str,
    stage: int,
    total_stages: int,
    rng: np.random.Generator,
    iteration: int,
) -> list[dict[str, Any]]:
    feature_names = tuple(dataset["feature_names"])
    stage_features = tuple(name for idx, name in enumerate(feature_names) if idx % int(total_stages) == int(stage))
    if not stage_features:
        stage_features = feature_names
    if method == "github_ml":
        return _github_ml_specs(dataset, config, method=method, stage=stage, rng=rng, iteration=iteration)
    if method == "beam":
        ranked = _rank_features_by_train_corr(dataset, stage_features)
        return _linear_rule_specs(ranked[: max(8, config.max_features_per_candidate * 8)], config, method, rng, iteration, deterministic=True)
    if method == "bandit":
        ranked = _rank_features_by_train_score(dataset, stage_features)
        return _linear_rule_specs(ranked[: max(12, config.max_features_per_candidate * 10)], config, method, rng, iteration, weighted=True)
    if method == "genetic":
        ranked = _rank_features_by_train_corr(dataset, feature_names)
        pool = tuple(dict.fromkeys((*stage_features, *ranked[:80])))
        return _linear_rule_specs(pool, config, method, rng, iteration, allow_larger=True)
    if method == "dehb_real":
        ranked = _rank_features_by_train_corr(dataset, stage_features)
        pool = tuple(dict.fromkeys((*ranked[:60], *stage_features[:60])))
        return _linear_rule_specs(pool, config, method, rng, iteration, dehb_like=True)
    return []


def _linear_rule_specs(
    feature_pool: tuple[str, ...],
    config: BTC5mSearchConfig,
    method: str,
    rng: np.random.Generator,
    iteration: int,
    *,
    deterministic: bool = False,
    weighted: bool = False,
    allow_larger: bool = False,
    dehb_like: bool = False,
) -> list[dict[str, Any]]:
    if not feature_pool:
        return []
    specs = []
    batch_size = 64
    for idx in range(batch_size):
        if deterministic:
            size = 1 + ((iteration + idx) % max(1, min(3, config.max_features_per_candidate)))
            start = (iteration * batch_size + idx) % len(feature_pool)
            features = tuple(feature_pool[(start + off) % len(feature_pool)] for off in range(size))
        else:
            upper = config.max_features_per_candidate + (2 if allow_larger else 0)
            if dehb_like:
                upper = max(2, min(upper, 4 + iteration % 3))
            size = int(rng.integers(1, max(2, upper + 1)))
            replace = len(feature_pool) < size
            probs = None
            if weighted:
                weights = np.linspace(2.0, 0.5, len(feature_pool), dtype=float)
                probs = weights / weights.sum()
            features = tuple(rng.choice(feature_pool, size=size, replace=replace, p=probs).tolist())
        weights = rng.normal(0.0, 1.0, len(features))
        if deterministic:
            weights = np.ones(len(features), dtype=float) / max(1, len(features))
        threshold = float(rng.choice([0.0, 0.10, 0.20, 0.35, 0.50, 0.75, 1.0]))
        if dehb_like and idx % 3 == 0:
            threshold = float(rng.choice([0.20, 0.35, 0.50]))
        specs.append(
            {
                "method": method,
                "route": "linear_feature_rule",
                "features": tuple(str(item) for item in features),
                "weights": tuple(float(x) for x in weights),
                "threshold": threshold,
                "iteration": int(iteration),
                "engine": method,
            }
        )
    return specs


def _github_ml_specs(
    dataset: dict[str, Any],
    config: BTC5mSearchConfig,
    *,
    method: str,
    stage: int,
    rng: np.random.Generator,
    iteration: int,
) -> list[dict[str, Any]]:
    try:
        from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
        from sklearn.linear_model import LogisticRegression
    except Exception:
        return _linear_rule_specs(tuple(dataset["feature_names"]), config, method, rng, iteration)
    ranked = _rank_features_by_train_corr(dataset, tuple(dataset["feature_names"]))
    offset = (stage * 7 + iteration * 13) % max(1, len(ranked))
    pool = tuple((ranked[offset:] + ranked[:offset])[: min(80, len(ranked))])
    specs = []
    for idx, model_name in enumerate(("logistic", "hist_gradient_boosting", "random_forest")):
        selected = tuple(pool[: min(len(pool), 12 + idx * 8)])
        if not selected:
            continue
        train_x = dataset["train_x"].loc[:, list(selected)].to_numpy(dtype=np.float64)
        y = (np.asarray(dataset["train_returns"], dtype=np.float64) > 0.0).astype(int)
        try:
            if model_name == "logistic":
                model = LogisticRegression(max_iter=300, C=float(rng.choice([0.25, 0.5, 1.0, 2.0])), random_state=int(stage * 100 + iteration))
            elif model_name == "hist_gradient_boosting":
                model = HistGradientBoostingClassifier(max_iter=int(rng.choice([40, 80, 120])), learning_rate=float(rng.choice([0.03, 0.05, 0.08])), random_state=int(stage * 100 + iteration))
            else:
                model = RandomForestClassifier(n_estimators=int(rng.choice([64, 96])), max_depth=int(rng.choice([3, 5, 7])), n_jobs=1, random_state=int(stage * 100 + iteration))
            model.fit(train_x, y)
        except Exception:
            continue
        specs.append(
            {
                "method": method,
                "route": "github_ml_train_only",
                "model": model_name,
                "features": selected,
                "threshold": float(rng.choice([0.0, 0.03, 0.05, 0.08, 0.10])),
                "_fit_payload": model,
                "iteration": int(iteration),
                "engine": method,
            }
        )
    return specs


def _scores_for_spec(
    frame: pd.DataFrame,
    returns: np.ndarray,
    spec: dict[str, Any],
    *,
    fit_payload: Any | None = None,
) -> np.ndarray:
    features = tuple(spec.get("features", ()))
    if fit_payload is not None:
        matrix = frame.loc[:, list(features)].to_numpy(dtype=np.float64)
        proba = fit_payload.predict_proba(matrix)
        return np.asarray(proba[:, 1] - 0.5, dtype=np.float64)
    weights = np.asarray(spec.get("weights", tuple([1.0] * len(features))), dtype=np.float64)
    if len(weights) != len(features):
        weights = np.ones(len(features), dtype=np.float64)
    norm = np.sum(np.abs(weights))
    weights = weights / norm if norm > 1e-12 else np.ones(len(features), dtype=np.float64) / max(1, len(features))
    matrix = frame.loc[:, list(features)].to_numpy(dtype=np.float64)
    return np.dot(matrix, weights)


def _select_usable_features(
    train_features: pd.DataFrame,
    train_returns: pd.Series,
    *,
    min_train_non_null: int,
    max_columns: int,
) -> tuple[tuple[str, ...], dict[str, list[str]]]:
    dropped: dict[str, list[str]] = {"forbidden": [], "too_sparse": [], "constant": []}
    usable = []
    for column in train_features.columns:
        lower = str(column).lower()
        if any(token in lower for token in FORBIDDEN_TOKENS):
            dropped["forbidden"].append(str(column))
            continue
        series = pd.to_numeric(train_features[column], errors="coerce")
        if int(series.notna().sum()) < min_train_non_null:
            dropped["too_sparse"].append(str(column))
            continue
        if float(series.std(skipna=True) or 0.0) <= 1e-12:
            dropped["constant"].append(str(column))
            continue
        usable.append(str(column))
    if len(usable) > max_columns:
        corr_scores = []
        target = pd.to_numeric(train_returns, errors="coerce")
        for column in usable:
            joined = pd.concat([train_features[column], target], axis=1).dropna()
            if len(joined) < min_train_non_null:
                score = 0.0
            else:
                score = abs(float(joined.iloc[:, 0].corr(joined.iloc[:, 1]) or 0.0))
            corr_scores.append((score, column))
        usable = [column for _, column in sorted(corr_scores, reverse=True)[:max_columns]]
    return tuple(usable), dropped


def _impute_and_standardize(train: pd.DataFrame, valid: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    med = train.median(axis=0, skipna=True).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    train_filled = train.replace([np.inf, -np.inf], np.nan).fillna(med).fillna(0.0)
    valid_filled = valid.replace([np.inf, -np.inf], np.nan).fillna(med).fillna(0.0)
    mean = train_filled.mean(axis=0)
    std = train_filled.std(axis=0).replace(0.0, 1.0).fillna(1.0)
    return (train_filled - mean) / std, (valid_filled - mean) / std


def _drop_unusable_return_rows(features: pd.DataFrame, returns: pd.Series) -> tuple[pd.DataFrame, pd.Series]:
    returns = pd.to_numeric(returns, errors="coerce")
    mask = np.isfinite(returns.to_numpy(dtype=np.float64))
    return features.loc[mask], returns.loc[mask]


def _rank_features_by_train_corr(dataset: dict[str, Any], features: tuple[str, ...]) -> list[str]:
    y = pd.Series(dataset["train_returns"], index=dataset["train_x"].index)
    scores = []
    for feature in features:
        series = dataset["train_x"][feature]
        corr = float(series.corr(y) or 0.0)
        scores.append((abs(corr), feature))
    return [feature for _, feature in sorted(scores, reverse=True)]


def _rank_features_by_train_score(dataset: dict[str, Any], features: tuple[str, ...]) -> list[str]:
    returns = np.asarray(dataset["train_returns"], dtype=np.float64)
    scores = []
    for feature in features:
        values = dataset["train_x"][feature].to_numpy(dtype=np.float64)
        pos = positions_from_scores(values, threshold=0.25)
        metrics = strategy_metrics(returns, pos, dataset["train_index"], size=1.0)
        scores.append((train_only_score(metrics), feature))
    return [feature for _, feature in sorted(scores, reverse=True)]


def _assert_no_forbidden_features(features: pd.DataFrame) -> None:
    forbidden = [name for name in features.columns if any(token in str(name).lower() for token in FORBIDDEN_TOKENS)]
    if forbidden:
        raise ValueError(f"BTC 5m features include forbidden columns: {forbidden[:10]}")


def _prefix_metrics(prefix: str, metrics: dict[str, float]) -> dict[str, float]:
    return {f"{prefix}_{key}": value for key, value in metrics.items() if key != "min_nav"}


def _empty_metrics() -> dict[str, float]:
    return {
        "cagr": float("nan"),
        "sharpe": float("nan"),
        "calmar": float("nan"),
        "max_drawdown": float("nan"),
        "profit_factor": 0.0,
        "trades": 0.0,
        "trades_per_month": 0.0,
        "win_rate": 0.0,
        "final_nav": float("nan"),
        "months_positive_pct": 0.0,
        "min_nav": float("nan"),
    }


def _profit_factor(returns: np.ndarray) -> float:
    arr = np.asarray(returns, dtype=np.float64)
    arr = arr[np.isfinite(arr)]
    gains = float(arr[arr > 0.0].sum())
    losses = float(arr[arr < 0.0].sum())
    if abs(losses) > 1e-15:
        return float(gains / abs(losses))
    if gains > 0.0:
        return float("inf")
    return 0.0


def _positive_month_pct(returns: np.ndarray, index: pd.DatetimeIndex) -> float:
    if len(returns) == 0:
        return 0.0
    monthly = pd.Series(returns, index=index).groupby([index.year, index.month]).apply(lambda item: float(np.prod(1.0 + item) - 1.0))
    if len(monthly) == 0:
        return 0.0
    return float((monthly > 0.0).mean())


def _months_between(index: pd.DatetimeIndex) -> float:
    if len(index) < 2:
        return 1.0
    days = max((index.max() - index.min()).total_seconds() / 86400.0, 1.0)
    return max(days / 30.4375, 1e-9)


def _between(index: pd.DatetimeIndex, start: str, end: str) -> np.ndarray:
    return np.asarray((index >= _ts(start)) & (index <= _ts(end)), dtype=bool)


def _ts(value: str) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _normalize_datetime_index(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    idx = pd.DatetimeIndex(out.index)
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    else:
        idx = idx.tz_convert("UTC")
    out.index = idx
    return out


def _finite_or(value: Any, fallback: float) -> float:
    try:
        number = float(value)
    except Exception:
        return fallback
    return number if np.isfinite(number) else fallback


def _method_offset(method: str) -> int:
    return {name: idx * 1_000_000 for idx, name in enumerate(METHODS, start=1)}[method]

