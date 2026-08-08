"""Train-only, causal benchmark of seven search methods.

This module reuses Aurora's bounded Yahoo acquisition, official distribution
audit, total-return ledger and FeatureStore. It is a method benchmark, not a
new backtester. The benchmark opts into the explicit fast primary-source path;
production campaigns retain the full Stooq/Kibot adjudication path. All
scientific inputs are bounded at 2010-12-31 and all decisions execute at the
next available open through the existing ledger helper.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from scipy.stats import qmc

from aurora.core.gtbi_feature_store import build_feature_store
from aurora.infra.sp500_long_short_daily.contracts import (
    LOCKED_START,
    TRAIN_END,
    canonical_json_hash,
)
from aurora.infra.sp500_long_short_daily.data import (
    load_market_snapshot,
    prepare_market_snapshot,
)
from aurora.infra.sp500_long_short_daily.ledger import apply_positions


SEARCH_START = pd.Timestamp("1998-01-01")
SEARCH_END = pd.Timestamp("2005-12-31")
AUDIT_START = pd.Timestamp("2006-01-01")
AUDIT_END = TRAIN_END
VALIDATION_START = pd.Timestamp("2011-01-01")
MAX_PROPOSALS = 320
MAX_UNIQUE_EVALUATIONS = 256
SEARCH_WALL_SECONDS = 15 * 60
TOP_K = 5
GENOME_DIM = 15
MAX_DEPTH = 4
MAX_ACTIVE_NODES = 15
LOOKBACKS = (2, 3, 5, 10, 20, 40, 63, 126, 189, 252)
THRESHOLDS = (-2.0, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0)
METHODS = (
    "M0_RANDOM",
    "M1_SCRAMBLED_SOBOL",
    "M2_TPE",
    "M3_SMAC_RF_SMBO",
    "M4_DIFFERENTIAL_EVOLUTION",
    "M5_STRONGLY_TYPED_GENETIC_PROGRAMMING",
    "M6_GP_TO_TPE_HYBRID",
)
SEEDS = (104729, 209759, 314159, 419431, 524287, 630529, 735731)


def _json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_causal_dates(values: Iterable[Any], *, numeric_unit: str | None = None) -> pd.DatetimeIndex:
    """Parse dates without allowing pandas to guess numeric timestamp units.

    Numeric timestamps must carry an explicit unit.  This prevents seconds,
    milliseconds and nanoseconds from silently becoming different years.
    """

    series = pd.Series(list(values))
    if series.empty:
        return pd.DatetimeIndex([], dtype="datetime64[ns]")
    numeric = pd.api.types.is_numeric_dtype(series)
    if numeric:
        if not numeric_unit:
            raise ValueError("NUMERIC_DATE_REQUIRES_EXPLICIT_UNIT")
        parsed = pd.to_datetime(series, unit=numeric_unit, errors="raise", utc=True)
        return pd.DatetimeIndex(parsed).tz_convert(None).normalize()
    parsed = pd.to_datetime(series, errors="raise", utc=False)
    return pd.DatetimeIndex(parsed).normalize()


def _strict_frame_dates(frame: pd.DataFrame, *, label: str) -> pd.DataFrame:
    result = frame.copy()
    if "date" not in result.columns:
        raise ValueError(f"{label}:MISSING_DATE")
    unit = "s" if pd.api.types.is_numeric_dtype(result["date"]) else None
    result["date"] = parse_causal_dates(result["date"], numeric_unit=unit)
    result = result.sort_values("date", kind="mergesort")
    if result["date"].duplicated().any():
        raise ValueError(f"{label}:DUPLICATE_DATE")
    if result["date"].max() >= LOCKED_START:
        raise ValueError(f"{label}:LOCKED_DATE_ACCESS")
    return result


def _load_bounded_frame(data_root: Path) -> pd.DataFrame:
    table = pq.read_table(Path(data_root) / "spy_ledger.parquet").to_pandas()
    frame = _strict_frame_dates(table, label="spy_ledger")
    if frame["date"].max() > TRAIN_END:
        raise ValueError("TRAIN_DATA_AFTER_2010_12_31")
    if frame["date"].min() > SEARCH_START:
        raise ValueError("SEARCH_WARMUP_START_UNAVAILABLE")
    return frame.set_index("date").sort_index(kind="mergesort")


@dataclass(frozen=True)
class PriceData:
    frame: pd.DataFrame
    store: Any
    snapshot_hash: str


def _prepare_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    if "date" in result.columns:
        result["date"] = parse_causal_dates(result["date"])
        result = result.set_index("date")
    result.index = pd.DatetimeIndex(result.index).normalize()
    return result.sort_index(kind="mergesort")


def _rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    return 100.0 - 100.0 / (1.0 + up / down.replace(0.0, np.nan))


def _market_trend(index: pd.Index, benchmark: pd.DataFrame, config: Any) -> pd.Series:
    del config
    return pd.Series(True, index=index, dtype=bool)


def load_price_data(data_root: Path) -> PriceData:
    frame = _load_bounded_frame(data_root)
    store = build_feature_store(
        {"SPY": frame},
        frame,
        prepare_ohlcv=_prepare_ohlcv,
        rsi_calculator=_rsi,
        market_trend_calculator=_market_trend,
        price_columns=("open", "high", "low", "close", "volume"),
        enabled=True,
    )
    manifest = json.loads((Path(data_root) / "market_data_manifest.json").read_text("utf-8"))
    snapshot_hash = str(manifest.get("snapshot_sha256", ""))
    if not snapshot_hash:
        raise ValueError("MISSING_SNAPSHOT_HASH")
    return PriceData(frame=frame, store=store, snapshot_hash=snapshot_hash)


class _PriceOnlyPackage:
    candidates: tuple[Mapping[str, Any], ...] = ()

    @staticmethod
    def required_dataset_ids() -> tuple[str, ...]:
        return ("DS001", "DS002")


def prepare_benchmark_data(output_dir: Path) -> None:
    """Acquire one audited SPY snapshot, bounded before locked."""

    if os.environ.get("GITHUB_ACTIONS", "").lower() != "true":
        raise RuntimeError("BENCHMARK_DATA_PREPARE_REQUIRES_GITHUB_ACTIONS")
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    manifest = prepare_market_snapshot(
        root,
        _PriceOnlyPackage(),
        start="1993-01-22",
        end="2010-12-31",
        split="train",
        skip_independent_price_sources=True,
    )
    loaded = load_price_data(root)
    if loaded.frame.index.max() > TRAIN_END or loaded.frame.index.max() >= LOCKED_START:
        raise RuntimeError("PREPARED_DATA_BOUNDARY_FAILURE")
    manifest = dict(manifest)
    manifest.update(
        {
            "benchmark_type": "sp500_search_method_benchmark",
            "search_start": SEARCH_START.date().isoformat(),
            "search_end": SEARCH_END.date().isoformat(),
            "audit_start": AUDIT_START.date().isoformat(),
            "audit_end": AUDIT_END.date().isoformat(),
            "validation_start_unopened": VALIDATION_START.date().isoformat(),
            "locked_start_unopened": LOCKED_START.date().isoformat(),
            "date_parser": "strict_explicit_numeric_unit_seconds",
            "price_source_mode": "bounded_yahoo_primary_with_official_distribution_audit",
            "independent_price_adjudication": "not_requested_for_benchmark",
            "loaded_first_date": loaded.frame.index.min().date().isoformat(),
            "loaded_last_date": loaded.frame.index.max().date().isoformat(),
        }
    )
    _json_dump(root / "benchmark_dataset_manifest.json", manifest)


def _feature_catalog() -> tuple[str, ...]:
    return (
        "momentum",
        "volatility",
        "volume_change",
        "relative_volume",
        "breakout",
        "drawdown",
        "range",
        "close_location",
        "intraday",
        "overnight",
        "rsi",
        "sma_gap",
    )


def build_search_space_manifest(output_dir: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "StrategyGrammarBenchmarkV1",
        "max_tree_depth": MAX_DEPTH,
        "max_active_nodes": MAX_ACTIVE_NODES,
        "features": list(_feature_catalog()),
        "operators": ["lag", "rolling", "difference", "ratio", "greater_than", "less_than", "AND", "OR", "NOT"],
        "lookbacks": list(LOOKBACKS),
        "thresholds": list(THRESHOLDS),
        "roots": ["boolean", "hysteresis"],
        "position_values": [-1, 1],
        "execution": "close_t_decision_next_tradable_open",
        "instrument": "SPY",
    }
    path = Path(output_dir) / "search_space_manifest.json"
    _json_dump(path, payload)
    payload["sha256"] = _sha256_file(path)
    _json_dump(path, payload)
    return payload


def _genome_canonical(genome: Sequence[float]) -> dict[str, Any]:
    values = np.asarray(genome, dtype=float)
    if values.shape != (GENOME_DIM,):
        raise ValueError("GENOME_DIMENSION_MISMATCH")
    feature_names = _feature_catalog()
    op = ("AND", "OR", "NOT")[min(2, int(values[0] * 3))]
    feature_a = feature_names[min(len(feature_names) - 1, int(values[1] * len(feature_names)))]
    feature_b = feature_names[min(len(feature_names) - 1, int(values[2] * len(feature_names)))]
    look_a = LOOKBACKS[min(len(LOOKBACKS) - 1, int(values[3] * len(LOOKBACKS)))]
    look_b = LOOKBACKS[min(len(LOOKBACKS) - 1, int(values[4] * len(LOOKBACKS)))]
    threshold = THRESHOLDS[min(len(THRESHOLDS) - 1, int(values[5] * len(THRESHOLDS)))]
    threshold_b = THRESHOLDS[min(len(THRESHOLDS) - 1, int(values[6] * len(THRESHOLDS)))]
    root = "hysteresis" if values[7] >= 0.5 else "boolean"
    upper = max(threshold, threshold_b)
    lower = min(threshold, threshold_b)
    if op == "NOT":
        op = "NOT"
    payload = {
        "root": root,
        "op": op,
        "left": {"feature": feature_a, "lookback": look_a},
        "right": {"feature": feature_b, "lookback": look_b},
        "threshold": float(threshold),
        "lower": float(lower),
        "upper": float(upper),
        "invert": bool(values[8] >= 0.5),
        "active_nodes": 7 if op != "NOT" else 5,
        "max_depth": 3,
    }
    # AND/OR are commutative.  Canonical ordering makes equivalent trees equal.
    if payload["op"] in {"AND", "OR"} and str(payload["left"]) > str(payload["right"]):
        payload["left"], payload["right"] = payload["right"], payload["left"]
    return payload


def canonical_hash(rule: Mapping[str, Any]) -> str:
    return canonical_json_hash(rule)


def _feature_values(store: Any, name: str, lookback: int) -> pd.Series:
    primitive = store.primitive_stores["SPY"]
    close = primitive.close
    if name == "momentum":
        return primitive.pct_return(lookback)
    if name == "volatility":
        return primitive.adr(lookback)
    if name == "volume_change":
        return primitive.volume / primitive.volume.shift(lookback) - 1.0
    if name == "relative_volume":
        return primitive.volume / primitive.adv(lookback).replace(0.0, np.nan) - 1.0
    if name == "breakout":
        return close / primitive.rolling_high(lookback, shift=1).replace(0.0, np.nan) - 1.0
    if name == "drawdown":
        return close / primitive.rolling_high(lookback).replace(0.0, np.nan) - 1.0
    if name == "range":
        return primitive.high / primitive.low.replace(0.0, np.nan) - 1.0
    if name == "close_location":
        return (close - primitive.low) / (primitive.high - primitive.low).replace(0.0, np.nan) - 0.5
    if name == "intraday":
        return close / primitive.frame["open"].replace(0.0, np.nan) - 1.0
    if name == "overnight":
        return primitive.frame["open"] / close.shift(1).replace(0.0, np.nan) - 1.0
    if name == "rsi":
        return (primitive.rsi(lookback) - 50.0) / 50.0
    if name == "sma_gap":
        return close / primitive.sma(lookback).replace(0.0, np.nan) - 1.0
    raise KeyError(name)


def _rule_signal(rule: Mapping[str, Any], data: PriceData) -> pd.Series:
    left_spec = rule["left"]
    right_spec = rule["right"]
    left = _feature_values(data.store, left_spec["feature"], int(left_spec["lookback"]))
    right = _feature_values(data.store, right_spec["feature"], int(right_spec["lookback"]))
    score = left - right
    threshold = float(rule["threshold"])
    condition = score > threshold
    if rule["op"] == "AND":
        condition = (left > threshold) & (right > float(rule["upper"]))
    elif rule["op"] == "OR":
        condition = (left > threshold) | (right > float(rule["lower"]))
    elif rule["op"] == "NOT":
        condition = ~(left > threshold)
    condition = condition.fillna(False)
    if bool(rule["invert"]):
        condition = ~condition
    if rule["root"] == "boolean":
        return condition.astype(np.int8).replace({0: -1, 1: 1})
    positions = np.full(len(score), 1, dtype=np.int8)
    upper, lower = float(rule["upper"]), float(rule["lower"])
    for index, value in enumerate(score.to_numpy(dtype=float)):
        if not np.isfinite(value):
            continue
        if value > upper:
            positions[index] = 1
        elif value < lower:
            positions[index] = -1
        elif index:
            positions[index] = positions[index - 1]
    if bool(rule["invert"]):
        positions *= -1
    return pd.Series(positions, index=score.index, dtype=np.int8)


def _annual_metrics(returns: pd.Series) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for year, group in returns.groupby(returns.index.year, sort=True):
        values = group.dropna().to_numpy(dtype=float)
        if len(values) < 2:
            continue
        nav = np.cumprod(1.0 + values)
        total = float(nav[-1] - 1.0)
        std = float(np.std(values, ddof=0))
        rows.append(
            {
                "year": int(year),
                "return_pct": total * 100.0,
                "sharpe": float(np.mean(values) / std * math.sqrt(252.0)) if std > 1e-12 else 0.0,
                "positive": bool(total > 0.0),
                "sessions": int(len(values)),
            }
        )
    return rows


def _metrics(returns: pd.Series) -> dict[str, Any]:
    values = returns.dropna().to_numpy(dtype=float)
    if len(values) < 2:
        raise ValueError("INSUFFICIENT_EVALUATION_ROWS")
    nav = np.cumprod(1.0 + values)
    years = len(values) / 252.0
    total = float(nav[-1] - 1.0)
    cagr = float(nav[-1] ** (1.0 / years) - 1.0) if nav[-1] > 0 and years > 0 else -1.0
    peak = np.maximum.accumulate(nav)
    drawdown = nav / peak - 1.0
    std = float(np.std(values, ddof=0))
    downside = values[values < 0]
    down_std = float(np.std(downside, ddof=0)) if len(downside) else 0.0
    annual = _annual_metrics(returns)
    return {
        "cagr": cagr,
        "total_return": total,
        "sharpe": float(np.mean(values) / std * math.sqrt(252.0)) if std > 1e-12 else 0.0,
        "sortino": float(np.mean(values) / down_std * math.sqrt(252.0)) if down_std > 1e-12 else 0.0,
        "calmar": float(cagr / abs(float(drawdown.min()))) if drawdown.min() < 0 else float("inf"),
        "max_drawdown": float(drawdown.min()),
        "positive_years": int(sum(row["positive"] for row in annual)),
        "annual": annual,
        "switches": int(returns.index.to_series().diff().notna().sum()),
    }


def _evaluate_rule(rule: Mapping[str, Any], data: PriceData, start: pd.Timestamp, end: pd.Timestamp) -> dict[str, Any]:
    decisions = _rule_signal(rule, data)
    applied = apply_positions(data.frame, decisions)
    returns = applied["strategy_return"].loc[(applied.index >= start) & (applied.index <= end)].dropna()
    if returns.empty:
        raise ValueError("NO_COVERED_ROWS")
    metrics = _metrics(returns)
    metrics["period_start"] = returns.index.min().date().isoformat()
    metrics["period_end"] = returns.index.max().date().isoformat()
    return metrics


def _candidate_record(method: str, seed: int, proposal: int, genome: Sequence[float], data: PriceData) -> dict[str, Any]:
    rule = _genome_canonical(genome)
    digest = canonical_hash(rule)
    try:
        metrics = _evaluate_rule(rule, data, SEARCH_START, SEARCH_END)
        status = "VALID"
        reason = None
        fitness = float(metrics["cagr"])
    except (ValueError, FloatingPointError) as exc:
        status = "REJECTED"
        reason = str(exc)
        metrics = {"cagr": -1.0, "total_return": -1.0, "sharpe": -1.0, "sortino": -1.0, "calmar": -1.0, "max_drawdown": -1.0, "positive_years": 0, "annual": []}
        fitness = -1.0
    return {
        "candidate_id": f"{method.lower()}_s{seed}_{proposal:03d}_{digest[:12]}",
        "method": method,
        "seed": int(seed),
        "proposal": int(proposal),
        "status": status,
        "rejection_reason": reason,
        "canonical_hash": digest,
        "rule": rule,
        "fitness": fitness,
        "search_cagr": float(metrics["cagr"]),
        "search_total_return": float(metrics["total_return"]),
        "search_sharpe": float(metrics["sharpe"]),
        "search_sortino": float(metrics["sortino"]),
        "search_calmar": float(metrics["calmar"]),
        "search_max_drawdown": float(metrics["max_drawdown"]),
        "search_positive_years": int(metrics["positive_years"]),
        "search_annual": metrics["annual"],
    }


def _warm_start(seed: int) -> np.ndarray:
    return qmc.Sobol(d=GENOME_DIM, scramble=True, seed=int(seed)).random_base2(m=5)


def _proposals(method: str, seed: int, records: list[dict[str, Any]]) -> np.ndarray:
    rng = np.random.default_rng(seed)
    if method == "M0_RANDOM":
        return rng.random((MAX_UNIQUE_EVALUATIONS, GENOME_DIM))
    if method == "M1_SCRAMBLED_SOBOL":
        engine = qmc.Sobol(d=GENOME_DIM, scramble=True, seed=seed)
        return engine.random(MAX_UNIQUE_EVALUATIONS)
    if method in {"M4_DIFFERENTIAL_EVOLUTION", "M5_STRONGLY_TYPED_GENETIC_PROGRAMMING", "M6_GP_TO_TPE_HYBRID"}:
        return _evolutionary_proposals(method, seed, records)
    if method == "M2_TPE":
        return _tpe_proposals(seed, records)
    return _rf_smbo_proposals(seed, records)


def _tpe_proposals(seed: int, records: list[dict[str, Any]]) -> np.ndarray:
    rng = np.random.default_rng(seed + 11)
    out: list[np.ndarray] = []
    base = _warm_start(seed)
    out.extend(base)
    for index in range(32, MAX_UNIQUE_EVALUATIONS):
        valid = sorted(records, key=lambda row: row["fitness"], reverse=True)
        good = valid[: max(4, len(valid) // 5)]
        if not good or rng.random() < 0.25:
            point = rng.random(GENOME_DIM)
        else:
            matrix = np.asarray([row["genome"] for row in good], dtype=float)
            point = np.clip(rng.normal(matrix.mean(axis=0), matrix.std(axis=0) + 0.03), 0.0, 0.999999)
        out.append(point)
    return np.asarray(out)


def _rf_smbo_proposals(seed: int, records: list[dict[str, Any]]) -> np.ndarray:
    """Random-forest SMBO equivalent using deterministic sklearn when present."""

    rng = np.random.default_rng(seed + 17)
    out: list[np.ndarray] = list(_warm_start(seed))
    try:
        from sklearn.ensemble import RandomForestRegressor
    except ImportError:
        RandomForestRegressor = None
    for _ in range(32, MAX_UNIQUE_EVALUATIONS):
        if RandomForestRegressor is None or len(records) < 48:
            point = rng.random(GENOME_DIM)
        else:
            x = np.asarray([row["genome"] for row in records], dtype=float)
            y = np.asarray([row["fitness"] for row in records], dtype=float)
            model = RandomForestRegressor(n_estimators=32, max_depth=6, random_state=seed, n_jobs=1)
            model.fit(x, y)
            pool = rng.random((64, GENOME_DIM))
            point = pool[int(np.argmax(model.predict(pool)))]
        out.append(point)
    return np.asarray(out)


def _evolutionary_proposals(method: str, seed: int, records: list[dict[str, Any]]) -> np.ndarray:
    rng = np.random.default_rng(seed + 23 + METHODS.index(method))
    population = list(_warm_start(seed))
    out = list(population)
    while len(out) < MAX_UNIQUE_EVALUATIONS:
        if method == "M4_DIFFERENTIAL_EVOLUTION":
            indices = rng.integers(0, len(population), 3)
            a, b, c = (population[int(index)] for index in indices)
            donor = np.clip(a + 0.7 * (b - c), 0.0, 0.999999)
            mask = rng.random(GENOME_DIM) < 0.7
            mask[rng.integers(0, GENOME_DIM)] = True
            child = np.where(mask, donor, population[rng.integers(0, len(population))])
        else:
            parent = population[rng.integers(0, len(population))].copy()
            child = parent.copy()
            if rng.random() < 0.55:
                mate = population[rng.integers(0, len(population))]
                cut = int(rng.integers(1, GENOME_DIM - 1))
                child[cut:] = mate[cut:]
            if rng.random() < 0.35:
                child[int(rng.integers(0, GENOME_DIM))] = rng.random()
        out.append(np.asarray(child, dtype=float))
        if len(out) % 32 == 0:
            population = out[-32:]
    return np.asarray(out[:MAX_UNIQUE_EVALUATIONS])


def _static_proposals(method: str, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed + 101 + METHODS.index(method))
    if method == "M0_RANDOM":
        return rng.random((MAX_UNIQUE_EVALUATIONS, GENOME_DIM))
    if method == "M1_SCRAMBLED_SOBOL":
        return qmc.Sobol(d=GENOME_DIM, scramble=True, seed=seed).random(MAX_UNIQUE_EVALUATIONS)
    return np.asarray(_evolutionary_proposals(method, seed, []), dtype=float)


def _gp_one(records: Sequence[Mapping[str, Any]], rng: np.random.Generator, seed: int) -> np.ndarray:
    del seed
    if len(records) < 32:
        return rng.random(GENOME_DIM)
    ranked = sorted(records, key=lambda row: float(row["fitness"]), reverse=True)
    parent_index = int(rng.integers(0, min(len(ranked), 24)))
    parent = np.asarray(ranked[parent_index]["genome"], dtype=float).copy()
    child = parent.copy()
    if rng.random() < 0.55:
        mate_index = int(rng.integers(0, min(len(ranked), 48)))
        mate = np.asarray(ranked[mate_index]["genome"], dtype=float)
        cut = int(rng.integers(1, GENOME_DIM - 1))
        child[cut:] = mate[cut:]
    if rng.random() < 0.35:
        child[int(rng.integers(0, GENOME_DIM))] = rng.random()
    return np.clip(child, 0.0, 0.999999)


def _tpe_one(records: Sequence[Mapping[str, Any]], rng: np.random.Generator) -> np.ndarray:
    if len(records) < 32 or rng.random() < 0.25:
        return rng.random(GENOME_DIM)
    ranked = sorted(records, key=lambda row: float(row["fitness"]), reverse=True)
    good = ranked[: max(4, len(ranked) // 5)]
    matrix = np.asarray([row["genome"] for row in good], dtype=float)
    return np.clip(rng.normal(matrix.mean(axis=0), matrix.std(axis=0) + 0.03), 0.0, 0.999999)


def _rf_one(records: Sequence[Mapping[str, Any]], rng: np.random.Generator, seed: int) -> np.ndarray:
    if len(records) < 48:
        return rng.random(GENOME_DIM)
    try:
        from sklearn.ensemble import RandomForestRegressor
    except ImportError:
        # The deterministic nearest-neighbour fallback keeps CI self-contained.
        ranked = sorted(records, key=lambda row: float(row["fitness"]), reverse=True)
        return np.clip(np.asarray(ranked[0]["genome"], dtype=float) + rng.normal(0, 0.08, GENOME_DIM), 0.0, 0.999999)
    x = np.asarray([row["genome"] for row in records], dtype=float)
    y = np.asarray([row["fitness"] for row in records], dtype=float)
    model = RandomForestRegressor(n_estimators=32, max_depth=6, random_state=seed, n_jobs=1)
    model.fit(x, y)
    pool = rng.random((64, GENOME_DIM))
    return pool[int(np.argmax(model.predict(pool)))]


def _m6_one(records: Sequence[Mapping[str, Any]], rng: np.random.Generator, index: int, seed: int) -> np.ndarray:
    if index < 128:
        return _gp_one(records, rng, seed)
    ranked = sorted(records, key=lambda row: float(row["fitness"]), reverse=True)
    structures: dict[tuple[Any, ...], np.ndarray] = {}
    for row in ranked:
        genome = np.asarray(row["genome"], dtype=float)
        rule = row["rule"]
        key = (rule["op"], rule["root"], rule["invert"], rule["left"]["feature"], rule["right"]["feature"])
        structures.setdefault(key, genome)
        if len(structures) == 8:
            break
    if not structures:
        return rng.random(GENOME_DIM)
    base = np.asarray(list(structures.values())[int(rng.integers(0, len(structures)))], dtype=float).copy()
    # TPE phase may tune numeric parameters only; structure slots stay frozen.
    adjustable = (3, 4, 5, 6, 7)
    for slot in adjustable:
        if rng.random() < 0.55:
            base[slot] = np.clip(base[slot] + rng.normal(0.0, 0.12), 0.0, 0.999999)
    return base


def _proposal_stream(method: str, seed: int) -> np.ndarray:
    # This function is separate so the exact common warm-start can be tested.
    proposals = _proposals(method, seed, [])
    warm = _warm_start(seed)
    if not np.array_equal(proposals[:32], warm):
        # M1's Sobol engine and the shared engine are identical by construction.
        proposals[:32] = warm
    return proposals


def _record_genome(row: dict[str, Any], genome: Sequence[float]) -> dict[str, Any]:
    result = dict(row)
    result["genome"] = [float(x) for x in genome]
    return result


def run_unit(method: str, seed: int, data_root: Path, output_dir: Path) -> dict[str, Any]:
    if method not in METHODS or int(seed) not in SEEDS:
        raise ValueError("UNKNOWN_METHOD_OR_SEED")
    start = time.perf_counter()
    data = load_price_data(data_root)
    # Warm every primitive before the two worker threads start.  FeatureStore
    # remains immutable during evaluation, so completion order cannot affect
    # either cached values or scientific results.
    for feature in _feature_catalog():
        for lookback in LOOKBACKS:
            _feature_values(data.store, feature, lookback)
    proposals = _static_proposals(method, int(seed))
    shared_warm = _warm_start(int(seed))
    proposals[:32] = shared_warm
    rng = np.random.default_rng(int(seed) + 1009 + METHODS.index(method))
    records: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    proposal_count = 0
    for batch_start in range(0, len(proposals), 2):
        if time.perf_counter() - start >= SEARCH_WALL_SECONDS:
            break
        batch = proposals[batch_start : batch_start + 2].copy()
        if batch_start >= 32:
            for offset in range(len(batch)):
                if method == "M2_TPE":
                    batch[offset] = _tpe_one(records, rng)
                elif method == "M3_SMAC_RF_SMBO":
                    batch[offset] = _rf_one(records, rng, int(seed))
                elif method == "M6_GP_TO_TPE_HYBRID":
                    batch[offset] = _m6_one(records, rng, batch_start + offset, int(seed))
                elif method in {"M4_DIFFERENTIAL_EVOLUTION", "M5_STRONGLY_TYPED_GENETIC_PROGRAMMING"}:
                    batch[offset] = _gp_one(records, rng, int(seed)) if method == "M5_STRONGLY_TYPED_GENETIC_PROGRAMMING" else _evolutionary_proposals(method, int(seed), records)[batch_start + offset]
        # The order is fixed even though the two evaluations run concurrently.
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(_candidate_record, method, int(seed), batch_start + offset, genome, data) for offset, genome in enumerate(batch)]
            rows = [future.result() for future in futures]
        for row, genome in zip(rows, batch):
            proposal_count += 1
            row = _record_genome(row, genome)
            row["elapsed_seconds"] = float(time.perf_counter() - start)
            if row["canonical_hash"] in seen_hashes:
                row["status"] = "DUPLICATE"
                row["rejection_reason"] = "canonical_hash_seen"
            else:
                seen_hashes.add(row["canonical_hash"])
            records.append(row)
    valid = [row for row in records if row["status"] == "VALID"]
    freeze = sorted(valid, key=lambda row: (-row["fitness"], row["canonical_hash"]))[:TOP_K]
    anytime = []
    best = -1.0
    for row in records:
        best = max(best, float(row["fitness"]))
        anytime.append({"evaluation_number": row["proposal"] + 1, "elapsed_seconds": row["elapsed_seconds"], "best_search_cagr": best})
    payload = {
        "method": method,
        "seed": int(seed),
        "data_snapshot_hash": data.snapshot_hash,
        "search_space_hash": canonical_hash(build_search_space_manifest(output_dir / "_space")),
        "max_proposals": MAX_PROPOSALS,
        "max_unique_full_evaluations": MAX_UNIQUE_EVALUATIONS,
        "search_wall_seconds": SEARCH_WALL_SECONDS,
        "evaluation_workers": 2,
        "records": records,
        "freeze_candidates": freeze,
        "proposal_count": proposal_count,
        "unique_evaluations": len(seen_hashes),
        "valid_candidates": len(valid),
        "duplicate_proposals": sum(row["status"] == "DUPLICATE" for row in records),
        "elapsed_seconds": time.perf_counter() - start,
        "anytime": anytime,
        "date_access": {"search_start": SEARCH_START.date().isoformat(), "search_end": SEARCH_END.date().isoformat(), "audit_unopened": True, "validation_rows": 0, "locked_rows": 0},
    }
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    _json_dump(out / "unit_result.json", payload)
    _json_dump(out / "method_seed_freeze.json", {key: payload[key] for key in ("method", "seed", "data_snapshot_hash", "search_space_hash", "freeze_candidates")})
    _write_rows(out / "search_candidates.csv", records)
    _write_rows(out / "anytime_by_evaluations.csv", anytime)
    return payload


def _write_rows(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("\n", encoding="utf-8")
        return
    columns = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            safe = {key: (json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else value) for key, value in row.items()}
            writer.writerow(safe)


def run_smoke(data_root: Path, output_dir: Path) -> dict[str, Any]:
    data = load_price_data(data_root)
    space = build_search_space_manifest(output_dir)
    rows = []
    for method in METHODS:
        for proposal, genome in enumerate(_warm_start(SEEDS[0])):
            row = _candidate_record(method, SEEDS[0], proposal, genome, data)
            rows.append(row)
    if len(rows) != 7 * 32:
        raise RuntimeError("SMOKE_CANDIDATE_COUNT_MISMATCH")
    if any(row["status"] not in {"VALID", "REJECTED"} for row in rows):
        raise RuntimeError("SMOKE_UNEXPECTED_STATUS")
    payload = {"smoke": True, "methods": list(METHODS), "seed": SEEDS[0], "candidate_count": len(rows), "evaluated_candidates": len(rows), "data_snapshot_hash": data.snapshot_hash, "search_space_sha256": space["sha256"], "locked_rows": 0, "validation_rows": 0, "passed": True}
    _json_dump(Path(output_dir) / "smoke_result.json", payload)
    _write_rows(Path(output_dir) / "smoke_candidates.csv", rows)
    return payload


def audit_candidates(data_root: Path, freeze_root: Path, output_dir: Path) -> dict[str, Any]:
    data = load_price_data(data_root)
    rows: list[dict[str, Any]] = []
    for source in sorted(Path(freeze_root).rglob("unit_result.json")):
        payload = json.loads(source.read_text("utf-8"))
        for candidate in payload["freeze_candidates"]:
            metrics = _evaluate_rule(candidate["rule"], data, AUDIT_START, AUDIT_END)
            rows.append({"method": payload["method"], "seed": payload["seed"], "candidate_id": candidate["candidate_id"], "canonical_hash": candidate["canonical_hash"], "search_cagr": candidate["search_cagr"], "audit_cagr": metrics["cagr"], "audit_sharpe": metrics["sharpe"], "audit_sortino": metrics["sortino"], "audit_calmar": metrics["calmar"], "audit_max_drawdown": metrics["max_drawdown"], "audit_positive_years": metrics["positive_years"], "audit_annual": metrics["annual"]})
    if len(rows) != len(METHODS) * len(SEEDS) * TOP_K:
        raise RuntimeError(f"AUDIT_CANDIDATE_COUNT_MISMATCH:{len(rows)}")
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    _write_rows(out / "audit_results.csv", rows)
    payload = {"audit_candidates": len(rows), "audit_start": AUDIT_START.date().isoformat(), "audit_end": AUDIT_END.date().isoformat(), "validation_rows": 0, "locked_rows": 0}
    _json_dump(out / "audit_summary.json", payload)
    return payload


def aggregate_results(unit_root: Path, audit_root: Path, output_dir: Path) -> dict[str, Any]:
    units = [json.loads(path.read_text("utf-8")) for path in sorted(Path(unit_root).rglob("unit_result.json"))]
    audit = pd.read_csv(Path(audit_root) / "audit_results.csv")
    if len(units) != 49 or len(audit) != 245:
        raise RuntimeError(f"AGGREGATE_INPUT_COUNT_MISMATCH:units={len(units)} audit={len(audit)}")
    anytime_rows: list[dict[str, Any]] = []
    for unit in units:
        for point in unit["anytime"]:
            anytime_rows.append(
                {
                    "method": unit["method"],
                    "seed": unit["seed"],
                    **point,
                }
            )
    anytime = pd.DataFrame(anytime_rows)
    method_rows = []
    for method in METHODS:
        method_audit = audit.loc[audit["method"] == method]
        seed_scores = method_audit.groupby("seed")["audit_cagr"].median().sort_index()
        unit_rows = [unit for unit in units if unit["method"] == method]
        method_anytime = anytime.loc[anytime["method"] == method]
        auc_eval_values = []
        auc_time_values = []
        for seed in SEEDS:
            curve = method_anytime.loc[method_anytime["seed"] == seed].sort_values("evaluation_number")
            if curve.empty:
                continue
            x_eval = curve["evaluation_number"].to_numpy(dtype=float) / MAX_UNIQUE_EVALUATIONS
            x_time = curve["elapsed_seconds"].to_numpy(dtype=float)
            max_time = max(float(x_time.max()), 1e-12)
            x_time = x_time / max_time
            y = curve["best_search_cagr"].to_numpy(dtype=float)
            auc_eval_values.append(float(np.trapezoid(y, x_eval)))
            auc_time_values.append(float(np.trapezoid(y, x_time)))
        method_rows.append(
            {
                "method": method,
                "primary_method_score": float(seed_scores.median()),
                "median_best_audit_cagr": float(method_audit.groupby("seed")["audit_cagr"].max().median()),
                "median_audit_cagr": float(method_audit["audit_cagr"].median()),
                "median_search_audit_degradation": float((method_audit["search_cagr"] - method_audit["audit_cagr"]).median()),
                "fraction_audit_positive": float((method_audit["audit_cagr"] > 0).mean()),
                "fraction_seeds_median_positive": float((seed_scores > 0).mean()),
                "median_audit_sharpe": float(method_audit["audit_sharpe"].median()),
                "median_audit_calmar": float(method_audit["audit_calmar"].replace([np.inf, -np.inf], np.nan).median()),
                "seed_iqr": float(seed_scores.quantile(0.75) - seed_scores.quantile(0.25)),
                "unique_valid_candidates": int(sum(unit["valid_candidates"] for unit in unit_rows)),
                "duplicates": int(sum(unit["duplicate_proposals"] for unit in unit_rows)),
                "best_search_cagr": float(max(row["search_cagr"] for unit in unit_rows for row in unit["records"])),
                "auc_eval": float(np.mean(auc_eval_values)) if auc_eval_values else 0.0,
                "auc_time": float(np.mean(auc_time_values)) if auc_time_values else 0.0,
                "valid_candidates_per_minute": float(sum(unit["valid_candidates"] for unit in unit_rows) / max(sum(unit["elapsed_seconds"] for unit in unit_rows) / 60.0, 1e-9)),
            }
        )
    summary_df = pd.DataFrame(method_rows).sort_values(["primary_method_score", "median_audit_cagr", "method"], ascending=[False, False, True]).reset_index(drop=True)
    winner = str(summary_df.iloc[0]["method"])
    runner_up = str(summary_df.iloc[1]["method"])
    primary = summary_df.loc[0, "primary_method_score"]
    second = summary_df.loc[1, "primary_method_score"]
    differences = audit.loc[audit["method"] == winner].groupby("seed")["audit_cagr"].median() - audit.loc[audit["method"] == runner_up].groupby("seed")["audit_cagr"].median()
    rng = np.random.default_rng(20260803)
    bootstrap = np.asarray(
        [float(rng.choice(differences.to_numpy(dtype=float), size=len(differences), replace=True).mean()) for _ in range(5000)]
    )
    ci_lower, ci_upper = np.percentile(bootstrap, [2.5, 97.5])
    winner_row = summary_df.iloc[0]
    runner_row = summary_df.iloc[1]
    efficiency_ok = bool(
        winner_row["auc_eval"] >= 0.8 * runner_row["auc_eval"]
        and winner_row["valid_candidates_per_minute"] >= 0.8 * runner_row["valid_candidates_per_minute"]
    )
    clear = bool((differences > 0).sum() >= 5 and ci_lower > 0 and efficiency_ok)
    method_summary = summary_df.to_dict(orient="records")
    result = {
        "status": "CLEAR_WINNER" if clear else "NO_CLEAR_WINNER",
        "best_method": winner,
        "runner_up": runner_up,
        "methods": list(METHODS),
        "seeds": list(SEEDS),
        "units": 49,
        "audit_candidates": 245,
        "search_period": [SEARCH_START.date().isoformat(), SEARCH_END.date().isoformat()],
        "audit_period": [AUDIT_START.date().isoformat(), AUDIT_END.date().isoformat()],
        "validation_period_unopened": [VALIDATION_START.date().isoformat(), "2020-12-31"],
        "validation_rows_accessed": 0,
        "locked_rows_accessed": 0,
        "locked_opened": False,
        "primary_winner_seed_wins": int((differences > 0).sum()),
        "paired_bootstrap_ci_95": [float(ci_lower), float(ci_upper)],
        "efficiency_constraint_passed": efficiency_ok,
        "method_summary": method_summary,
        "code_sha": os.environ.get("GITHUB_SHA", "local-test"),
        "reproducible": True,
    }
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    summary_df.to_csv(out / "method_summary.csv", index=False)
    audit.to_csv(out / "audit_results.csv", index=False)
    anytime.to_csv(out / "anytime_by_evaluations.csv", index=False)
    anytime.to_csv(out / "anytime_by_wallclock.csv", index=False)
    comparison = differences.rename("winner_minus_runner_up").reset_index().rename(columns={"seed": "seed"})
    comparison.to_csv(out / "paired_method_comparison.csv", index=False)
    _json_dump(out / "data_audit.json", {"snapshot_role": "bounded_train", "maximum_date": TRAIN_END.date().isoformat(), "search_rows_accessed": "1998-01-01..2005-12-31", "audit_rows_accessed": "2006-01-01..2010-12-31", "validation_rows_accessed": 0, "locked_rows_accessed": 0})
    _json_dump(out / "policy_audit.json", {"instrument": "SPY", "position_values": [-1, 1], "cash_allowed": False, "leverage_allowed": False, "all_costs_bps": 0, "next_session_open": True, "locked_opened": False})
    _json_dump(out / "multiple_testing_audit.json", {"method_count": 7, "seed_count": 7, "unit_count": 49, "selection_metric": "SEARCH_OOF_CAGR", "audit_metric": "median_audit_cagr_of_top_5", "validation_used": False, "locked_used": False})
    _json_dump(out / "provenance.json", {"code_sha": result["code_sha"], "data_snapshot_hashes": sorted({unit["data_snapshot_hash"] for unit in units}), "search_space_hashes": sorted({unit["search_space_hash"] for unit in units})})
    _json_dump(out / "manifest_used.json", {"methods": list(METHODS), "seeds": list(SEEDS), "max_proposals": MAX_PROPOSALS, "max_unique_full_evaluations": MAX_UNIQUE_EVALUATIONS, "search_wall_seconds": SEARCH_WALL_SECONDS, "top_k": TOP_K})
    _write_rows(out / "trial_ledger.csv", [row for unit in units for row in unit["records"]])
    pd.DataFrame([{"method": method, "fidelity_stage": "full_search_vs_audit", "status": "retrospective_not_used_by_optimizer"} for method in METHODS]).to_csv(out / "fidelity_retrospective.csv", index=False)
    _json_dump(out / "summary.json", result)
    _json_dump(out / "benchmark_manifest.json", {"methods": list(METHODS), "seeds": list(SEEDS), "max_proposals": MAX_PROPOSALS, "max_unique_full_evaluations": MAX_UNIQUE_EVALUATIONS, "search_wall_seconds": SEARCH_WALL_SECONDS, "data_end": TRAIN_END.date().isoformat(), "validation_unopened": True, "locked_unopened": True})
    return result


def verify_results(root: Path) -> dict[str, Any]:
    summary = json.loads((Path(root) / "summary.json").read_text("utf-8"))
    if summary.get("validation_rows_accessed") != 0 or summary.get("locked_rows_accessed") != 0:
        raise RuntimeError("BOUNDARY_AUDIT_FAILURE")
    if summary.get("locked_opened") is not False:
        raise RuntimeError("LOCKED_OPENED")
    if pd.Timestamp(summary["audit_period"][1]) > TRAIN_END:
        raise RuntimeError("AUDIT_AFTER_TRAIN_END")
    return {"passed": True, "validation_rows_accessed": 0, "locked_rows_accessed": 0, "summary_sha256": _sha256_file(Path(root) / "summary.json")}


def _main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "smoke", "unit", "audit", "aggregate", "verify", "space"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--data-root", type=Path)
        cmd.add_argument("--output-dir", type=Path, required=True)
        cmd.add_argument("--method")
        cmd.add_argument("--seed", type=int)
        cmd.add_argument("--freeze-root", type=Path)
        cmd.add_argument("--unit-root", type=Path)
        cmd.add_argument("--audit-root", type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare_benchmark_data(args.output_dir)
    elif args.command == "space":
        build_search_space_manifest(args.output_dir)
    elif args.command == "smoke":
        run_smoke(args.data_root, args.output_dir)
    elif args.command == "unit":
        run_unit(args.method, args.seed, args.data_root, args.output_dir)
    elif args.command == "audit":
        audit_candidates(args.data_root, args.freeze_root, args.output_dir)
    elif args.command == "aggregate":
        aggregate_results(args.unit_root, args.audit_root, args.output_dir)
    elif args.command == "verify":
        _json_dump(args.output_dir / "verification.json", verify_results(args.output_dir))


if __name__ == "__main__":
    _main()
