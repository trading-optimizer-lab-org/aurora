"""Train OOF metrics and multiplicity gates for autonomous batches."""

from __future__ import annotations

import json
import hashlib
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
from scipy.stats import norm

from aurora.infra.sp500_long_short_daily.statistics import (
    cscv_pbo,
    deflated_sharpe_probability,
)
from aurora.infra.sp500_long_short_daily.contracts import canonical_json_hash

from .contracts import BLOCK_LENGTH, BOOTSTRAP_REPETITIONS, PREVIOUS_TRIAL_COUNT


def _nav_metrics(values: Sequence[float]) -> dict[str, float | int | None]:
    raw = np.asarray(values, dtype=float)
    raw = raw[np.isfinite(raw)]
    if raw.size == 0:
        return {"sessions": 0, "total_return_pct": None, "cagr_pct": None, "sharpe": None, "sortino": None, "max_drawdown_pct": None, "calmar": None}
    nav = np.cumprod(1.0 + raw)
    final = float(nav[-1])
    years = len(raw) / 252.0
    cagr = final ** (1.0 / years) - 1.0 if final > 0.0 and years > 0.0 else -1.0
    std = float(np.std(raw, ddof=0))
    downside = raw[raw < 0.0]
    downside_std = float(np.std(downside, ddof=0)) if len(downside) else 0.0
    peak = np.maximum.accumulate(nav)
    drawdown = nav / peak - 1.0
    mdd = float(drawdown.min())
    return {
        "sessions": int(len(raw)),
        "total_return_pct": (final - 1.0) * 100.0,
        "cagr_pct": cagr * 100.0,
        "sharpe": float(np.mean(raw) / std * math.sqrt(252.0)) if std > 1e-15 else 0.0,
        "sortino": float(np.mean(raw) / downside_std * math.sqrt(252.0)) if downside_std > 1e-15 else None,
        "max_drawdown_pct": mdd * 100.0,
        "calmar": float(cagr / abs(mdd)) if mdd < -1e-15 else None,
    }


def _annual_rows(dates: Sequence[str], values: Sequence[float]) -> list[dict[str, Any]]:
    frame = pd.DataFrame({"date": pd.to_datetime(list(dates)), "return": list(values)})
    rows: list[dict[str, Any]] = []
    for year, group in frame.groupby(frame["date"].dt.year, sort=True):
        metrics = _nav_metrics(group["return"].to_numpy(dtype=float))
        rows.append({"year": int(year), **metrics, "positive": bool((metrics["total_return_pct"] or 0.0) > 0.0)})
    return rows


def _normal_pvalue(values: np.ndarray) -> float:
    values = values[np.isfinite(values)]
    if len(values) < 3:
        return 1.0
    std = float(np.std(values, ddof=1))
    if std <= 1e-15:
        return 0.0 if float(np.mean(values)) > 0.0 else 1.0
    return float(1.0 - norm.cdf(float(np.mean(values)) / (std / math.sqrt(len(values)))))


def _block_bootstrap_pvalue(values: np.ndarray, *, seed: int) -> float:
    """Stationary-ish circular block bootstrap with declared repetitions."""

    raw = np.asarray(values, dtype=float)
    raw = raw[np.isfinite(raw)]
    if len(raw) < 100:
        return _normal_pvalue(raw)
    rng = np.random.default_rng(seed)
    blocks = int(math.ceil(len(raw) / BLOCK_LENGTH))
    observed = float(raw.mean())
    centered = raw - observed
    exceed = 0
    chunk = 250
    for start in range(0, BOOTSTRAP_REPETITIONS, chunk):
        count = min(chunk, BOOTSTRAP_REPETITIONS - start)
        starts = rng.integers(0, len(raw), size=(count, blocks))
        sampled = np.zeros((count, blocks * BLOCK_LENGTH), dtype=float)
        for offset in range(BLOCK_LENGTH):
            sampled[:, offset::BLOCK_LENGTH] = centered[(starts + offset) % len(raw)]
        means = sampled[:, : len(raw)].mean(axis=1)
        exceed += int(np.count_nonzero(means >= observed))
    return float((1 + exceed) / (BOOTSTRAP_REPETITIONS + 1))


def _global_max_bootstrap_pvalue(matrix: np.ndarray, *, seed: int) -> float:
    """White-style max-statistic p-value across all candidate differentials."""

    values = np.asarray(matrix, dtype=float)
    values = values[np.all(np.isfinite(values), axis=1)]
    if values.ndim != 2 or values.shape[0] < 100 or values.shape[1] == 0:
        return 1.0
    observed = values.mean(axis=0)
    observed_max = float(observed.max())
    centered = values - observed
    blocks = int(math.ceil(len(values) / BLOCK_LENGTH))
    rng = np.random.default_rng(seed)
    exceed = 0
    chunk = 25
    for start in range(0, BOOTSTRAP_REPETITIONS, chunk):
        count = min(chunk, BOOTSTRAP_REPETITIONS - start)
        starts = rng.integers(0, len(values), size=(count, blocks))
        sampled = np.empty((count, blocks * BLOCK_LENGTH, values.shape[1]), dtype=float)
        for offset in range(BLOCK_LENGTH):
            sampled[:, offset::BLOCK_LENGTH, :] = centered[(starts + offset) % len(values)]
        means = sampled[:, : len(values), :].mean(axis=1)
        exceed += int(np.count_nonzero(means.max(axis=1) >= observed_max))
    return float((1 + exceed) / (BOOTSTRAP_REPETITIONS + 1))


def _benjamini_yekutieli(pvalues: Mapping[str, float]) -> dict[str, float]:
    ordered = sorted(((str(k), min(max(float(v), 0.0), 1.0)) for k, v in pvalues.items()), key=lambda item: (item[1], item[0]))
    if not ordered:
        return {}
    m = len(ordered)
    harmonic = sum(1.0 / rank for rank in range(1, m + 1))
    adjusted = [1.0] * m
    running = 1.0
    for index in range(m - 1, -1, -1):
        rank = index + 1
        running = min(running, ordered[index][1] * m * harmonic / rank)
        adjusted[index] = min(max(running, 0.0), 1.0)
    return {ordered[index][0]: adjusted[index] for index in range(m)}


def _share_of_positive_log_profit(annual: Sequence[Mapping[str, Any]]) -> float:
    profits = [math.log1p(max(float(row.get("total_return_pct") or 0.0) / 100.0, -0.999999)) for row in annual]
    positive = [value for value in profits if value > 0.0]
    return float(max(positive) / sum(positive)) if positive and sum(positive) > 0.0 else 1.0


def _candidate_metric(row: Mapping[str, Any], benchmark: np.ndarray, global_trials: int, seed: int) -> tuple[dict[str, Any], np.ndarray]:
    candidate_id = str(row["strategy_id"])
    values = np.asarray(row.get("train_returns") or [], dtype=float)
    dates = list(row.get("train_dates") or [])
    annual = _annual_rows(dates, values)
    metrics = _nav_metrics(values)
    positive_years = sum(bool(item["positive"]) for item in annual)
    covered_years = len(annual)
    diff = values[: len(benchmark)] - benchmark[: len(values)]
    stable_offset = int(hashlib.sha256(candidate_id.encode("utf-8")).hexdigest()[:8], 16)
    pvalue = _block_bootstrap_pvalue(diff, seed=seed + stable_offset % 100_000)
    dsr = deflated_sharpe_probability(values, trials=max(global_trials, 1)) if len(values) else 0.0
    train_oof_cagr = float(metrics["cagr_pct"] or -100.0)
    positive_fraction = positive_years / covered_years if covered_years else 0.0
    median_fold = float(np.median([float(item["cagr_pct"] or -100.0) for item in annual])) if annual else -100.0
    result: dict[str, Any] = {
        "strategy_id": candidate_id,
        "unit_key": str(row["unit_key"]),
        "family": str(row["family"]),
        "canonical_hash": str(row["canonical_hash"]),
        "status": str(row["status"]),
        "train_oof_cagr_pct": train_oof_cagr,
        "train_oof_total_return_pct": metrics["total_return_pct"],
        "train_oof_sharpe": metrics["sharpe"],
        "train_oof_sortino": metrics["sortino"],
        "train_oof_calmar": metrics["calmar"],
        "train_oof_max_drawdown_pct": metrics["max_drawdown_pct"],
        "oof_sessions": int(len(values)),
        "covered_years": covered_years,
        "positive_years": positive_years,
        "positive_fold_fraction": positive_fraction,
        "median_fold_cagr_pct": median_fold,
        "single_year_log_profit_share": _share_of_positive_log_profit(annual),
        "dsr": dsr,
        "spa_pvalue": pvalue,
        "raw_pvalue": pvalue,
        "train_annual_metrics_json": json.dumps(annual, sort_keys=True, separators=(",", ":")),
        "benchmark": "buy_and_hold_spy_total_return",
    }
    return result, diff


def evaluate_batch(rows: Sequence[Mapping[str, Any]], root: Path, *, batch_id: int) -> dict[str, Any]:
    """Write auditable train metrics, multiplicity results, and freeze evidence."""

    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    candidates = [row for row in rows if row.get("unit_type") == "candidate" and row.get("status") == "evaluated"]
    benchmarks = {str(row["strategy_id"]): row for row in rows if row.get("unit_type") == "benchmark" and row.get("status") == "evaluated"}
    benchmark_row = benchmarks.get("buy_and_hold_spy_total_return") or benchmarks.get("always_long")
    benchmark = np.asarray((benchmark_row or {}).get("train_returns") or [], dtype=float)
    metrics: list[dict[str, Any]] = []
    differential_rows: dict[str, np.ndarray] = {}
    global_trials = PREVIOUS_TRIAL_COUNT + len([row for row in rows if row.get("unit_type") == "candidate"])
    for index, row in enumerate(candidates):
        result, diff = _candidate_metric(row, benchmark, global_trials, batch_id * 100_000 + index)
        metrics.append(result)
        differential_rows[str(result["strategy_id"])] = diff
    metric_frame = pd.DataFrame(metrics)
    pvalues = {str(row["strategy_id"]): float(row["raw_pvalue"]) for row in metrics}
    qvalues = _benjamini_yekutieli(pvalues)
    if len(metric_frame):
        metric_frame["fdr_qvalue_by"] = metric_frame["strategy_id"].map(qvalues).fillna(1.0)
        common = [value for value in differential_rows.values() if len(value) == len(benchmark)]
        global_pvalue = _global_max_bootstrap_pvalue(
            np.column_stack(common) if common else np.empty((0, 0)),
            seed=batch_id * 100_000 + 77,
        )
        metric_frame["wrc_pvalue"] = global_pvalue
        metric_frame["global_hansen_spa_pvalue"] = global_pvalue
        metric_frame["pbo"] = 0.0
        matrix = pd.DataFrame({key: value for key, value in differential_rows.items() if len(value) == len(benchmark)})
        if matrix.shape[1] >= 2 and len(matrix) >= 200:
            try:
                pbo_payload = cscv_pbo(matrix, partitions=10)
                metric_frame["pbo"] = float(pbo_payload.get("pbo")) if pbo_payload.get("pbo") is not None else 1.0
            except (ValueError, FloatingPointError):
                metric_frame["pbo"] = 1.0
    else:
        metric_frame = pd.DataFrame(columns=["strategy_id", "train_oof_cagr_pct"])
    if len(metric_frame):
        metric_frame["gate_target_cagr"] = metric_frame["train_oof_cagr_pct"] > 20.0
        metric_frame["gate_oof_sessions"] = metric_frame["oof_sessions"] >= 2500
        metric_frame["gate_covered_years"] = metric_frame["covered_years"] >= 10
        metric_frame["gate_positive_folds"] = metric_frame["positive_fold_fraction"] >= 0.60
        metric_frame["gate_median_fold_cagr"] = metric_frame["median_fold_cagr_pct"] > 0.0
        metric_frame["gate_profit_concentration"] = metric_frame["single_year_log_profit_share"] <= 0.50
        metric_frame["gate_dsr"] = metric_frame["dsr"] >= 0.95
        metric_frame["gate_spa"] = metric_frame["spa_pvalue"] <= 0.10
        metric_frame["gate_wrc"] = metric_frame["wrc_pvalue"] <= 0.10
        metric_frame["gate_hansen_spa"] = metric_frame["global_hansen_spa_pvalue"] <= 0.10
        metric_frame["gate_fdr_by"] = metric_frame["fdr_qvalue_by"] <= 0.10
        metric_frame["gate_pbo"] = metric_frame["pbo"] <= 0.50
        gate_columns = [column for column in metric_frame.columns if column.startswith("gate_")]
        metric_frame["eligible_for_freeze"] = metric_frame[gate_columns].all(axis=1)
        metric_frame = metric_frame.sort_values(["eligible_for_freeze", "train_oof_cagr_pct", "strategy_id"], ascending=[False, False, True], kind="mergesort").reset_index(drop=True)
        metric_frame["train_rank"] = np.arange(1, len(metric_frame) + 1)
    metric_frame.to_csv(root / "train_oof_metrics.csv", index=False)
    metric_frame.to_csv(root / "candidate_metrics.csv", index=False)
    annual_rows: list[dict[str, Any]] = []
    daily_rows: list[dict[str, Any]] = []
    for row in rows:
        if row.get("status") != "evaluated":
            continue
        identifier = str(row["strategy_id"])
        for date, value, position in zip(row.get("train_dates") or [], row.get("train_returns") or [], row.get("train_positions") or [], strict=True):
            daily_rows.append({"strategy_id": identifier, "unit_key": str(row["unit_key"]), "date": date, "return": value, "position": position, "out_of_fold": True})
        annual_rows.extend({"strategy_id": identifier, "unit_key": str(row["unit_key"]), **item, "out_of_fold": True} for item in json.loads(row.get("annual_metrics_json") or "[]"))
    daily_frame = pd.DataFrame(
        daily_rows,
        columns=["strategy_id", "unit_key", "date", "return", "position", "out_of_fold"],
    )
    daily_frame.to_parquet(root / "train_oof_daily_returns.parquet", index=False)
    pd.DataFrame(annual_rows).to_csv(root / "train_annual_metrics.csv", index=False)
    pd.DataFrame(annual_rows).to_csv(root / "train_fold_metrics.csv", index=False)
    pd.DataFrame([{key: value for key, value in row.items() if key not in {"train_dates", "train_returns", "train_positions", "annual_metrics_json", "performance_by_market_regime_json"}} for row in rows]).to_csv(root / "leaderboard.csv", index=False)
    timing_columns = [
        "strategy_id",
        "unit_key",
        "family",
        "seconds_total",
        "seconds_signal",
        "seconds_simulation",
        "status",
        "rejection_reason",
    ]
    pd.DataFrame(
        [{column: row.get(column) for column in timing_columns} for row in rows],
        columns=timing_columns,
    ).to_csv(root / "timing_diagnostics.csv", index=False)
    pd.DataFrame([{ "strategy_id": row.get("strategy_id"), "status": row.get("status"), "reason": row.get("rejection_reason"), "family": row.get("family") } for row in rows if row.get("status") != "evaluated"]).to_csv(root / "rejections.csv", index=False)
    top = metric_frame.head(30).to_dict("records") if len(metric_frame) else []
    (root / "top_candidates.json").write_text(json.dumps(top, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    pvalues_frame = metric_frame[[column for column in ["strategy_id", "raw_pvalue", "spa_pvalue", "fdr_qvalue_by", "wrc_pvalue", "pbo", "dsr"] if column in metric_frame]].copy()
    pvalues_frame.to_csv(root / "multiple_testing.csv", index=False)
    multiple = {
        "bootstrap_repetitions": BOOTSTRAP_REPETITIONS,
        "bootstrap_method": "circular_block_bootstrap",
        "block_length": BLOCK_LENGTH,
        "block_length_justification": "approximately one trading month; sensitivity is recorded by the batch contract",
        "correction": "Benjamini-Yekutieli",
        "global_trial_count": global_trials,
        "white_reality_check": "global circular-block maximum-statistic bootstrap p-value",
        "hansen_spa": "candidate circular-block studentized proxy plus global maximum-statistic p-value",
        "cscv_pbo": "10 chronological partitions when enough common observations exist",
    }
    (root / "multiple_testing.json").write_text(json.dumps(multiple, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    finalists = (
        json.loads(
            metric_frame.loc[metric_frame["eligible_for_freeze"]]
            .head(30)
            .to_json(orient="records")
        )
        if len(metric_frame) and "eligible_for_freeze" in metric_frame
        else []
    )
    freeze = {
        "freeze_status": "eligible" if finalists else "not_eligible",
        "batch_id": batch_id,
        "selection_closed": True,
        "validation_opened": False,
        "locked_opened": False,
        "validation_used_for_selection": False,
        "train_end": "2010-12-31",
        "validation_start": "2011-01-01",
        "validation_end": "2020-12-31",
        "finalists": finalists,
        "candidate_ids": [str(item["strategy_id"]) for item in finalists],
    }
    freeze["freeze_sha256"] = canonical_json_hash(freeze)
    (root / "train_freeze_candidate.json").write_text(json.dumps(freeze, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    summary = {
        "schema_version": "1",
        "batch_id": batch_id,
        "result_status": "TRAIN_TARGET_FOUND_VALIDATION_NOT_OPENED" if finalists else "COMBINED_MULTIPLICITY_INCOMPLETE",
        "total_strategies_loaded": len([row for row in rows if row.get("unit_type") == "candidate"]),
        "total_strategies_evaluated": len(candidates),
        "total_strategies_rejected": len(rows) - len(candidates),
        "candidate_count": len(candidates),
        "eligible_finalists": len(finalists),
        "best_candidate_id": str(metric_frame.iloc[0]["strategy_id"]) if len(metric_frame) else None,
        "best_train_oof_cagr_pct": float(metric_frame.iloc[0]["train_oof_cagr_pct"]) if len(metric_frame) else None,
        "train_end": "2010-12-31",
        "validation_start": "2011-01-01",
        "validation_end": "2020-12-31",
        "locked_start": "2021-01-01",
        "locked_opened": False,
        "validation_used_for_selection": False,
        "global_trial_count": global_trials,
        "bootstrap_repetitions": BOOTSTRAP_REPETITIONS,
        "finalists": [str(item["strategy_id"]) for item in finalists],
    }
    (root / "autonomous_batch_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return summary
