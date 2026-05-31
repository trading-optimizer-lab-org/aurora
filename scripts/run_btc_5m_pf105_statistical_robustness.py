from __future__ import annotations

import argparse
import csv
import json
import math
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from aurora.core.metrics import compute_metrics
from aurora.research.btc_5m_trainonly_search import (
    BTC5mSearchConfig,
    WAVE_SEED_STRIDE,
    _candidate_specs,
    _method_offset,
    _scores_for_spec,
    candidate_id_from_spec,
    load_dataset,
    positions_from_scores,
)
from aurora.validation.deflated_sharpe import deflated_sharpe_annualized


PPY_DAILY = 365
DEFAULT_N_TRIALS = 36555


def _float(value: object, default: float = float("nan")) -> float:
    try:
        out = float(value)
    except Exception:
        return default
    return out if math.isfinite(out) else default


def _daily_from_5m(values: np.ndarray, index: pd.DatetimeIndex) -> np.ndarray:
    series = pd.Series(np.asarray(values, dtype=np.float64), index=pd.DatetimeIndex(index))
    grouped = series.groupby(series.index.date).apply(lambda item: float(np.prod(1.0 + item) - 1.0))
    return grouped.to_numpy(dtype=np.float64)


def _profit_factor(values: np.ndarray) -> float:
    arr = np.asarray(values, dtype=np.float64)
    arr = arr[np.isfinite(arr)]
    gains = float(arr[arr > 0.0].sum())
    losses = float(arr[arr < 0.0].sum())
    if abs(losses) > 1e-15:
        return float(gains / abs(losses))
    return float("inf") if gains > 0.0 else 0.0


def _block_indices(n: int, block: int, rng: np.random.Generator) -> np.ndarray:
    pieces: list[np.ndarray] = []
    total = 0
    while total < n:
        start = int(rng.integers(0, n))
        take = min(int(block), n - total)
        pieces.append((start + np.arange(take)) % n)
        total += take
    return np.concatenate(pieces)


def _bh(p_values: dict[str, float]) -> dict[str, float]:
    finite = sorted((key, float(value)) for key, value in p_values.items() if math.isfinite(float(value)))
    raw: dict[str, float] = {}
    prev = 1.0
    total = len(finite)
    for rank, (key, p_value) in reversed(list(enumerate(finite, start=1))):
        q_value = min(prev, p_value * total / rank)
        raw[key] = max(0.0, min(1.0, q_value))
        prev = q_value
    return {key: raw[key] for key, _ in finite}


def _load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _select_rows(
    rows: list[dict[str, str]],
    *,
    mode: str,
    chunk_index: int,
    total_chunks: int,
    wave: int,
    stage: int,
) -> list[dict[str, str]]:
    if mode == "non_ml_chunk":
        non_ml = [row for row in rows if str(row.get("method") or row.get("source_method")) != "github_ml"]
        return [row for idx, row in enumerate(non_ml) if idx % total_chunks == chunk_index]
    if mode == "github_ml_stage":
        return [
            row
            for row in rows
            if str(row.get("method") or row.get("source_method")) == "github_ml"
            and int(float(row.get("wave", -1))) == int(wave)
            and int(float(row.get("stage", -1))) == int(stage)
        ]
    raise ValueError(f"unknown mode: {mode}")


def _replay_ml_specs(
    dataset: dict[str, Any],
    config: BTC5mSearchConfig,
    rows: list[dict[str, str]],
    *,
    wave: int,
    stage: int,
    total_stages: int,
) -> dict[str, dict[str, Any]]:
    if not rows:
        return {}
    wanted = {row["candidate_id"] for row in rows}
    max_iteration = 0
    for row in rows:
        try:
            max_iteration = max(max_iteration, int(json.loads(row["rule"]).get("iteration", 0)))
        except Exception:
            pass
    seed = int(config.random_seed + int(wave) * WAVE_SEED_STRIDE + int(stage) * 10_000 + _method_offset("github_ml"))
    rng = np.random.default_rng(seed)
    found: dict[str, dict[str, Any]] = {}
    for iteration in range(max_iteration + 1):
        specs = _candidate_specs(
            dataset,
            config,
            method="github_ml",
            stage=int(stage),
            total_stages=int(total_stages),
            rng=rng,
            iteration=iteration,
        )
        for spec in specs:
            public_spec = {key: value for key, value in spec.items() if not key.startswith("_")}
            cid = candidate_id_from_spec(public_spec)
            if cid in wanted:
                found[cid] = spec
        if len(found) == len(wanted):
            break
    return found


def _candidate_returns(
    row: dict[str, str],
    dataset: dict[str, Any],
    spec: dict[str, Any],
) -> np.ndarray:
    scores = _scores_for_spec(dataset["valid_x"], dataset["valid_returns"], spec, fit_payload=spec.get("_fit_payload"))
    positions = positions_from_scores(scores, threshold=float(spec["threshold"]))
    positions = positions * _float(row.get("position_size"), 1.0)
    return positions * np.asarray(dataset["valid_returns"], dtype=np.float64)


def _robustness_row(
    row: dict[str, str],
    candidate_daily: np.ndarray,
    benchmark_daily: np.ndarray,
    benchmark_metrics: Any,
    *,
    n_trials: int,
    n_bootstrap: int,
    n_permutations: int,
    alpha: float,
    max_fdr_q: float,
) -> dict[str, object]:
    n = min(len(candidate_daily), len(benchmark_daily))
    candidate = np.asarray(candidate_daily[-n:], dtype=np.float64)
    benchmark = np.asarray(benchmark_daily[-n:], dtype=np.float64)
    metrics = compute_metrics(candidate, ppy=PPY_DAILY)
    excess = candidate - benchmark
    if len(excess) > 3 and float(np.std(excess, ddof=1)) > 1e-12:
        mean_p = float(stats.ttest_1samp(excess, 0.0, alternative="greater").pvalue)
    else:
        mean_p = 1.0

    rng = np.random.default_rng(abs(hash(str(row.get("candidate_id")))) % (2**32))
    cand_calmar = np.empty(n_bootstrap)
    excess_calmar = np.empty(n_bootstrap)
    for idx in range(n_bootstrap):
        sample = _block_indices(n, 5, rng)
        c_calmar = compute_metrics(candidate[sample], ppy=PPY_DAILY).calmar
        b_calmar = compute_metrics(benchmark[sample], ppy=PPY_DAILY).calmar
        cand_calmar[idx] = c_calmar
        excess_calmar[idx] = c_calmar - b_calmar
    bootstrap_calmar_p05 = float(np.nanpercentile(cand_calmar, 5))
    bootstrap_excess_calmar_p05 = float(np.nanpercentile(excess_calmar, 5))
    bootstrap_excess_pvalue = float(np.nanmean(excess_calmar <= 0.0))

    perm_samples = np.empty(n_permutations)
    observed_calmar = float(metrics.calmar)
    for idx in range(n_permutations):
        shift = int(rng.integers(1, max(2, n - 1)))
        perm_samples[idx] = compute_metrics(np.roll(candidate, shift), ppy=PPY_DAILY).calmar
    permutation_pvalue = float(np.mean(perm_samples >= observed_calmar))

    try:
        dsr = deflated_sharpe_annualized(
            float(metrics.sharpe),
            max(1, int(n_trials)),
            max(2, int(metrics.n_periods)),
            PPY_DAILY,
            skew=float(metrics.skew),
            kurtosis=float(metrics.kurtosis),
            min_dsr=0.95,
            min_psr=0.95,
        )
        dsr_value = float(dsr.dsr)
        psr_value = float(dsr.psr_vs_zero)
        dsr_pass = bool(dsr.passed)
        psr_pass = psr_value >= 0.95
    except Exception:
        dsr_value = float("nan")
        psr_value = float("nan")
        dsr_pass = False
        psr_pass = False

    p_values = {
        "mean_excess_vs_benchmark": mean_p,
        "bootstrap_excess_calmar": bootstrap_excess_pvalue,
        "circular_shift_permutation_calmar": permutation_pvalue,
    }
    q_values = _bh(p_values)
    checks = {
        "target_calmar": observed_calmar >= 1.0,
        "beats_benchmark_calmar": observed_calmar > float(benchmark_metrics.calmar),
        "p_value_mean_excess_vs_benchmark": mean_p <= alpha,
        "bootstrap_calmar_p05": bootstrap_calmar_p05 >= 0.0,
        "bootstrap_excess_calmar_p05": bootstrap_excess_calmar_p05 >= 0.0,
        "deflated_sharpe": dsr_pass,
        "probabilistic_sharpe": psr_pass,
        "permutation_test_circular_shift": permutation_pvalue <= alpha,
        "fdr_correction": all(value <= max_fdr_q for value in q_values.values()),
    }
    fail_reasons = ";".join(key for key, value in checks.items() if not value)
    return {
        "candidate_id": row.get("candidate_id"),
        "method": row.get("method") or row.get("source_method"),
        "wave": row.get("wave"),
        "stage": row.get("stage"),
        "position_size": row.get("position_size"),
        "validation_sharpe_5m": row.get("validation_sharpe"),
        "validation_profit_factor_5m": row.get("validation_profit_factor"),
        "validation_trades_per_month_5m": row.get("validation_trades_per_month"),
        "daily_cagr": float(metrics.cagr),
        "daily_sharpe": float(metrics.sharpe),
        "daily_calmar": observed_calmar,
        "daily_max_drawdown": float(metrics.mdd),
        "daily_profit_factor": _profit_factor(candidate),
        "benchmark_daily_cagr": float(benchmark_metrics.cagr),
        "benchmark_daily_sharpe": float(benchmark_metrics.sharpe),
        "benchmark_daily_calmar": float(benchmark_metrics.calmar),
        "mean_excess_pvalue": mean_p,
        "bootstrap_calmar_p05": bootstrap_calmar_p05,
        "bootstrap_excess_calmar_p05": bootstrap_excess_calmar_p05,
        "bootstrap_excess_pvalue": bootstrap_excess_pvalue,
        "deflated_sharpe": dsr_value,
        "probabilistic_sharpe": psr_value,
        "permutation_pvalue": permutation_pvalue,
        "fdr_max_q": max(q_values.values()) if q_values else float("nan"),
        "statistical_pass": all(checks.values()),
        "fail_reasons": fail_reasons,
        "locked_opened": False,
        "features": row.get("features", ""),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates-csv", required=True)
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--summary-json", required=True)
    parser.add_argument("--mode", choices=["non_ml_chunk", "github_ml_stage"], required=True)
    parser.add_argument("--chunk-index", type=int, default=0)
    parser.add_argument("--total-chunks", type=int, default=1)
    parser.add_argument("--wave", type=int, default=-1)
    parser.add_argument("--stage", type=int, default=-1)
    parser.add_argument("--total-stages", type=int, default=36)
    parser.add_argument("--n-bootstrap", type=int, default=80)
    parser.add_argument("--n-permutations", type=int, default=80)
    parser.add_argument("--n-trials", type=int, default=DEFAULT_N_TRIALS)
    args = parser.parse_args()

    warnings.filterwarnings("ignore")
    rows = _select_rows(
        _load_rows(Path(args.candidates_csv)),
        mode=args.mode,
        chunk_index=args.chunk_index,
        total_chunks=args.total_chunks,
        wave=args.wave,
        stage=args.stage,
    )

    output = Path(args.output_csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    summary_path = Path(args.summary_json)
    summary_path.parent.mkdir(parents=True, exist_ok=True)

    if not rows:
        output.write_text("", encoding="utf-8")
        summary_path.write_text(json.dumps({"rows": 0, "locked_opened": False}, indent=2), encoding="utf-8")
        return 0

    config = BTC5mSearchConfig(run_id="btc_5m_all_features_5methods_trainonly_9h_max500_real180")
    dataset, _audit = load_dataset(config)
    benchmark_daily = _daily_from_5m(np.asarray(dataset["valid_returns"], dtype=np.float64), dataset["valid_index"])
    benchmark_metrics = compute_metrics(benchmark_daily, ppy=PPY_DAILY)

    ml_specs: dict[str, dict[str, Any]] = {}
    if args.mode == "github_ml_stage":
        ml_specs = _replay_ml_specs(
            dataset,
            config,
            rows,
            wave=args.wave,
            stage=args.stage,
            total_stages=args.total_stages,
        )

    results: list[dict[str, object]] = []
    for row in rows:
        try:
            if args.mode == "github_ml_stage":
                spec = ml_specs.get(str(row.get("candidate_id")))
                if spec is None:
                    raise ValueError("github_ml spec could not be reconstructed")
            else:
                spec = json.loads(row["rule"])
            candidate_5m = _candidate_returns(row, dataset, spec)
            candidate_daily = _daily_from_5m(candidate_5m, dataset["valid_index"])
            results.append(
                _robustness_row(
                    row,
                    candidate_daily,
                    benchmark_daily,
                    benchmark_metrics,
                    n_trials=args.n_trials,
                    n_bootstrap=args.n_bootstrap,
                    n_permutations=args.n_permutations,
                    alpha=0.05,
                    max_fdr_q=0.10,
                )
            )
        except Exception as exc:
            results.append(
                {
                    "candidate_id": row.get("candidate_id"),
                    "method": row.get("method") or row.get("source_method"),
                    "wave": row.get("wave"),
                    "stage": row.get("stage"),
                    "statistical_pass": False,
                    "fail_reasons": f"error:{str(exc)[:240]}",
                    "locked_opened": False,
                }
            )

    fieldnames = list(results[0].keys())
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)

    summary = {
        "rows": len(results),
        "statistical_pass": sum(1 for row in results if row.get("statistical_pass") is True),
        "mode": args.mode,
        "chunk_index": args.chunk_index,
        "total_chunks": args.total_chunks,
        "wave": args.wave,
        "stage": args.stage,
        "n_bootstrap": args.n_bootstrap,
        "n_permutations": args.n_permutations,
        "period": "validation_daily_from_5m",
        "costs": "zero",
        "locked_opened": False,
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
