"""Cumulative V1+V2 train ranking and binding multiple-testing controls."""

from __future__ import annotations

import io
import json
import math
import zipfile
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
from scipy.stats import norm

from aurora.infra.sp500_long_short_daily.statistics import (
    _benjamini_hochberg,
    _percentile_rank,
    cscv_pbo,
    deflated_sharpe_probability,
    reality_check_and_spa,
)
from aurora.infra.sp500_long_short_daily_v2.contracts import (
    EXPECTED_CUMULATIVE_TRIALS,
    EXPECTED_V1_EVALUATED,
    EXPECTED_V1_REJECTED,
    EXPECTED_V1_RESULTS_SHA256,
    sha256_file,
)

BOOTSTRAP_SAMPLES = 5_000
BLOCK_LENGTHS = (5, 10, 15, 20, 60)


def load_v1_evidence(results_zip: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    path = Path(results_zip)
    if sha256_file(path) != EXPECTED_V1_RESULTS_SHA256:
        raise RuntimeError("COMBINED_MULTIPLICITY_INCOMPLETE:V1_RESULTS_HASH")
    with zipfile.ZipFile(path) as archive:
        daily = pd.read_parquet(io.BytesIO(archive.read("train_daily_returns.parquet")))
        eligibility = pd.read_csv(io.BytesIO(archive.read("eligibility_and_rejections.csv")))
        candidate_metrics = pd.read_csv(io.BytesIO(archive.read("candidate_metrics.csv")))
    daily["date"] = pd.to_datetime(daily["date"])
    candidate_daily = daily.loc[~daily["unit_key"].astype(str).str.startswith("BENCHMARK::")]
    if candidate_daily["unit_key"].nunique() != EXPECTED_V1_EVALUATED:
        raise RuntimeError("COMBINED_MULTIPLICITY_INCOMPLETE:V1_STREAM_COUNT")
    v1_candidates = eligibility.loc[~eligibility["unit_key"].astype(str).str.startswith("BENCHMARK::")]
    rejected = int(v1_candidates["status"].eq("rejected").sum())
    if len(v1_candidates) != 168 or rejected != EXPECTED_V1_REJECTED:
        raise RuntimeError("COMBINED_MULTIPLICITY_INCOMPLETE:V1_LEDGER_COUNT")
    return daily, eligibility, candidate_metrics


def _single_candidate_raw_pvalue(differential: pd.Series) -> float:
    values = differential.dropna().to_numpy(dtype=float)
    if len(values) < 3:
        return 1.0
    std = float(np.std(values, ddof=1))
    if std <= 1e-15:
        return 1.0
    statistic = float(np.mean(values) / (std / math.sqrt(len(values))))
    return float(1.0 - norm.cdf(statistic))


def cumulative_train_ranking(
    candidate_metrics: pd.DataFrame,
    annual_metrics: pd.DataFrame,
    v2_daily_returns: pd.DataFrame,
    benchmark_daily_returns: pd.DataFrame,
    *,
    v1_results_zip: Path,
    seed: int,
) -> tuple[pd.DataFrame, Mapping[str, Any], pd.DataFrame, Mapping[str, Any]]:
    metrics = candidate_metrics.loc[candidate_metrics["status"] == "evaluated"].copy()
    v1_daily, v1_eligibility, _v1_metrics = load_v1_evidence(v1_results_zip)
    v1_candidates = v1_daily.loc[~v1_daily["unit_key"].astype(str).str.startswith("BENCHMARK::")]
    v1_wide = v1_candidates.pivot(index="date", columns="unit_key", values="return")
    v2 = v2_daily_returns.copy()
    v2["date"] = pd.to_datetime(v2["date"])
    v2_wide = v2.pivot(index="date", columns="unit_key", values="return") if len(v2) else pd.DataFrame()
    benchmark = benchmark_daily_returns.copy()
    benchmark["date"] = pd.to_datetime(benchmark["date"])
    benchmark_wide = benchmark.pivot(index="date", columns="unit_key", values="return")
    strongest = max(
        benchmark_wide.columns,
        key=lambda column: float(benchmark_wide[column].mean() / max(benchmark_wide[column].std(ddof=0), 1e-15)),
    )
    combined = pd.concat([v1_wide.add_prefix("V1::"), v2_wide.add_prefix("V2::")], axis=1)
    common = combined.join(benchmark_wide[[strongest]], how="inner").dropna(axis=0, how="any")
    if len(common) < 1_500 or common.shape[1] != 1 + EXPECTED_V1_EVALUATED + len(v2_wide.columns):
        raise RuntimeError("COMBINED_MULTIPLICITY_INCOMPLETE:COMMON_INTERVAL")
    candidate_common = common.drop(columns=[strongest])
    differential = candidate_common.subtract(common[strongest], axis=0)
    multiple = dict(
        reality_check_and_spa(
            differential,
            seed=seed,
            samples=BOOTSTRAP_SAMPLES,
            block_lengths=BLOCK_LENGTHS,
        )
    )
    pbo = cscv_pbo(candidate_common)
    multiple.update(
        {
            "cscv": pbo,
            "pbo": pbo["pbo"],
            "strongest_benchmark": str(strongest),
            "common_interval_start": common.index.min().date().isoformat(),
            "common_interval_end": common.index.max().date().isoformat(),
            "common_interval_sessions": len(common),
            "v1_evaluated_streams": EXPECTED_V1_EVALUATED,
            "v2_evaluated_streams": len(v2_wide.columns),
            "declared_trials": EXPECTED_CUMULATIVE_TRIALS,
            "bootstrap_samples": BOOTSTRAP_SAMPLES,
            "block_lengths": list(BLOCK_LENGTHS),
        }
    )

    candidate_spa = multiple.get("candidate_spa_pvalues", {})
    all_declared_p: dict[str, float] = {}
    v1_status = v1_eligibility.loc[~v1_eligibility["unit_key"].astype(str).str.startswith("BENCHMARK::")]
    for row in v1_status.to_dict("records"):
        key = f"V1::{row['unit_key']}"
        all_declared_p[key] = (
            _single_candidate_raw_pvalue(differential[key])
            if row["status"] == "evaluated" and key in differential
            else 1.0
        )
    for row in candidate_metrics.to_dict("records"):
        key = f"V2::{row['unit_key']}"
        all_declared_p[key] = (
            _single_candidate_raw_pvalue(differential[key])
            if row["status"] == "evaluated" and key in differential
            else 1.0
        )
    if len(all_declared_p) != EXPECTED_CUMULATIVE_TRIALS:
        raise RuntimeError("COMBINED_MULTIPLICITY_INCOMPLETE:FDR_TRIAL_COUNT")
    qvalues = _benjamini_hochberg(all_declared_p)
    multiple["cumulative_fdr_qvalues"] = qvalues

    if metrics.empty:
        return metrics, multiple, pd.DataFrame(), {
            "v1_declared": 168, "v1_evaluated": 65, "v1_rejected": 103,
            "v2_declared": 144, "total_declared": 312,
        }
    metrics["deflated_sharpe_probability"] = metrics["unit_key"].map(
        lambda key: deflated_sharpe_probability(
            v2_wide[key].dropna().to_numpy(dtype=float), trials=EXPECTED_CUMULATIVE_TRIALS
        )
    )
    metrics["spa_pvalue"] = metrics["unit_key"].map(
        lambda key: candidate_spa.get(f"V2::{key}")
    )
    metrics["fdr_qvalue"] = metrics["unit_key"].map(
        lambda key: qvalues.get(f"V2::{key}")
    )
    metrics["pbo"] = pbo["pbo"]
    sensitivity: dict[str, float] = {}
    for _, group in metrics.groupby("family", sort=True):
        ordered = group.sort_values("strategy_id", kind="mergesort").reset_index(drop=True)
        positive = (ordered["train_cagr_pct"] > 0) & (ordered["train_sharpe"] > 0)
        for index, key in enumerate(ordered["unit_key"]):
            neighbours = [i for i in (index - 1, index + 1) if 0 <= i < len(ordered)]
            sensitivity[str(key)] = float(positive.iloc[neighbours].mean()) if neighbours else 0.0
    metrics["neighbour_positive_fraction"] = metrics["unit_key"].map(sensitivity)

    global_spa = multiple.get("hansen_spa_pvalue")
    checks = {
        "cagr_positive": metrics["train_cagr_pct"] > 0,
        "sharpe_gt_0_30": metrics["train_sharpe"] > 0.30,
        "calmar_gt_0_25": metrics["train_calmar"] > 0.25,
        "max_drawdown_gt_minus_55": metrics["train_max_drawdown_pct"] > -55.0,
        "positive_years_ge_60pct": metrics["train_positive_year_fraction"] >= 0.60,
        "rolling_3y_cagr_positive": metrics["train_median_rolling_3y_cagr_pct"] > 0,
        "worst_fold_gt_minus_30": metrics["train_min_outer_fold_cagr_pct"] > -30.0,
        "gain_concentration_le_60pct": metrics["train_gain_concentration"] <= 0.60,
        "neighbour_sensitivity": metrics["neighbour_positive_fraction"] >= 0.50,
        "deflated_sharpe_gt_0_80": metrics["deflated_sharpe_probability"] > 0.80,
        "candidate_spa_le_0_10": metrics["spa_pvalue"].notna() & (metrics["spa_pvalue"] <= 0.10),
        "fdr_q_le_0_10": metrics["fdr_qvalue"].notna() & (metrics["fdr_qvalue"] <= 0.10),
        "global_combined_spa_le_0_10": pd.Series(global_spa is not None and global_spa <= 0.10, index=metrics.index),
        "combined_pbo_lt_0_50": pd.Series(pbo["pbo"] is not None and pbo["pbo"] < 0.50, index=metrics.index),
        "pre_2011_evidence": metrics["evidence_track"].eq("pre_2011_evidence"),
    }
    for name, values in checks.items():
        metrics[f"gate_{name}"] = values
    metrics["hard_train_eligible"] = pd.DataFrame(checks).all(axis=1)
    ranks = {
        "cagr": _percentile_rank(metrics["train_cagr_pct"]),
        "calmar": _percentile_rank(metrics["train_calmar"]),
        "sharpe": _percentile_rank(metrics["train_sharpe"]),
        "sortino": _percentile_rank(metrics["train_sortino"]),
        "positive": _percentile_rank(metrics["train_positive_year_fraction"]),
        "rolling": _percentile_rank(metrics["train_median_rolling_3y_cagr_pct"]),
        "worst": _percentile_rank(metrics["train_worst_year_return_pct"]),
        "fold": _percentile_rank(metrics["train_min_outer_fold_cagr_pct"]),
    }
    metrics["train_selection_score"] = (
        .22*ranks["cagr"] + .17*ranks["calmar"] + .14*ranks["sharpe"] + .10*ranks["sortino"]
        + .10*ranks["positive"] + .10*ranks["rolling"] + .09*ranks["worst"] + .08*ranks["fold"]
        - .05*(metrics["complexity_score"] / max(float(metrics["complexity_score"].max()), 1.0))
        - .06*(1.0-metrics["neighbour_positive_fraction"])
        - .04*metrics["train_gain_concentration"].clip(0, 1)
    )
    metrics["eligible_for_freeze"] = metrics["hard_train_eligible"]
    metrics = metrics.sort_values(
        ["eligible_for_freeze", "train_selection_score", "unit_key"],
        ascending=[False, False, True], kind="mergesort"
    ).reset_index(drop=True)
    metrics["train_rank"] = np.arange(1, len(metrics) + 1)

    ledger_rows = []
    for row in v1_status.to_dict("records"):
        ledger_rows.append({"campaign": "V1", "strategy_id": row["unit_key"], "status": row["status"], "fdr_pvalue": all_declared_p[f"V1::{row['unit_key']}"]})
    for row in candidate_metrics.to_dict("records"):
        ledger_rows.append({"campaign": "V2", "strategy_id": row["unit_key"], "status": row["status"], "fdr_pvalue": all_declared_p[f"V2::{row['unit_key']}"]})
    trial_ledger = pd.DataFrame(ledger_rows)
    audit = {
        "v1_results_sha256": EXPECTED_V1_RESULTS_SHA256,
        "v1_declared": 168,
        "v1_evaluated": 65,
        "v1_rejected": 103,
        "v1_daily_streams_loaded": int(v1_wide.shape[1]),
        "v2_declared": 144,
        "v2_evaluated": int(v2_wide.shape[1]),
        "total_declared": int(len(trial_ledger)),
        "common_interval_sessions": len(common),
        "complete": True,
    }
    return metrics, multiple, trial_ledger, audit
