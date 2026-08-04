"""One-shot validation of the cryptographically frozen train finalists."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from aurora.infra.github_performance.workloads.common import primary_metric_record
from aurora.infra.sp500_long_short_daily.contracts import (
    LOCKED_START,
    VALIDATION_END,
    canonical_json_hash,
)
from aurora.infra.sp500_long_short_daily.data import (
    PreparedMarketData,
    load_market_snapshot,
)
from aurora.infra.sp500_long_short_daily.ledger import apply_positions
from aurora.infra.sp500_long_short_daily.signals import (
    CandidateRejected,
    benchmark_decisions,
    candidate_decisions,
)
from aurora.infra.sp500_long_short_daily.workload import (
    BENCHMARK_IDS,
    METRIC_FIELDS,
    _annual_rows,
    _extended_metrics,
    _market_regime_states,
    _package,
)
from aurora.infra.github_performance.shard_planner import sha256_file


VALIDATION_ACK = "OPEN_VALIDATION_2011_2020_ONCE"
VALIDATION_START = pd.Timestamp("2011-01-01")


class ValidationGateError(RuntimeError):
    """Raised before performance is exposed when the one-shot contract fails."""


def verify_train_freeze(path: Path, *, code_sha: str | None = None) -> Mapping[str, Any]:
    freeze = json.loads(Path(path).read_text(encoding="utf-8"))
    claimed = str(freeze.get("freeze_sha256", ""))
    unhashed = dict(freeze)
    unhashed.pop("freeze_sha256", None)
    if not claimed or canonical_json_hash(unhashed) != claimed:
        raise ValidationGateError("TRAIN_FREEZE_HASH_MISMATCH")
    if freeze.get("selection_closed") is not True:
        raise ValidationGateError("TRAIN_SELECTION_NOT_CLOSED")
    if freeze.get("validation_opened") is not False or freeze.get("locked_opened") is not False:
        raise ValidationGateError("TRAIN_FREEZE_BOUNDARY_INVALID")
    if freeze.get("train_end") != "2010-12-31" or freeze.get("locked_start") != "2021-01-01":
        raise ValidationGateError("TRAIN_FREEZE_DATES_INVALID")
    current_sha = code_sha or os.environ.get("GITHUB_SHA", "")
    frozen_sha = str(freeze.get("code_sha", ""))
    if current_sha and frozen_sha not in {current_sha, "LOCAL_TEST_ONLY"}:
        raise ValidationGateError("TRAIN_FREEZE_CODE_SHA_MISMATCH")
    return freeze


def combine_phase_snapshots(
    train: PreparedMarketData,
    validation: PreparedMarketData,
) -> PreparedMarketData:
    if train.split != "train" or validation.split != "validation":
        raise ValidationGateError("SNAPSHOT_PHASE_MISMATCH")
    if train.ledger.index.max() > pd.Timestamp("2010-12-31"):
        raise ValidationGateError("TRAIN_SNAPSHOT_BOUNDARY_BREACH")
    if validation.ledger.index.min() < VALIDATION_START:
        raise ValidationGateError("VALIDATION_SNAPSHOT_START_BREACH")
    if validation.ledger.index.max() > VALIDATION_END:
        raise ValidationGateError("VALIDATION_SNAPSHOT_END_BREACH")
    ledger = pd.concat([train.ledger, validation.ledger]).sort_index(kind="mergesort")
    if ledger.index.duplicated().any() or ledger.index.max() >= LOCKED_START:
        raise ValidationGateError("TECHNICAL_FAILURE_LOCKED_BREACH")
    series: dict[str, pd.Series] = {}
    for name in sorted(set(train.series) | set(validation.series)):
        values = pd.concat(
            [
                train.series.get(name, pd.Series(dtype=float)),
                validation.series.get(name, pd.Series(dtype=float)),
            ]
        ).sort_index(kind="mergesort")
        values = values.loc[~values.index.duplicated(keep="last")]
        if len(values) and values.index.max() >= LOCKED_START:
            raise ValidationGateError("TECHNICAL_FAILURE_LOCKED_BREACH")
        series[name] = values
    return PreparedMarketData(
        ledger=ledger,
        series=series,
        available_dataset_ids=(train.available_dataset_ids & validation.available_dataset_ids),
        rejected_datasets={**train.rejected_datasets, **validation.rejected_datasets},
        receipts=(*train.receipts, *validation.receipts),
        split="validation",
    )


def _evaluate_validation_unit(
    data: PreparedMarketData,
    unit_key: str,
    parameters: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    is_benchmark = parameters.get("unit_type") == "benchmark"
    strategy_id = str(parameters.get("benchmark_id", parameters.get("strategy_id", unit_key)))
    row: dict[str, Any] = {
        "unit_key": unit_key,
        "strategy_id": strategy_id,
        "unit_type": "benchmark" if is_benchmark else "candidate",
        "family": "benchmark" if is_benchmark else str(parameters["family"]),
        "canonical_hash": canonical_json_hash(parameters)
        if is_benchmark
        else parameters["canonical_hash"],
        "status": "evaluated",
        "rejection_reason": None,
        "validation_opened": True,
        "validation_used_for_selection": False,
        "locked_opened": False,
    }
    try:
        signal = (
            benchmark_decisions(str(parameters["benchmark_id"]), data)
            if is_benchmark
            else candidate_decisions(
                parameters, data, candidate_lookup=_package().candidate_by_id()
            )
        )
        if signal.first_evaluable_date is None or signal.missing_fraction > 0.02 + 1e-12:
            raise CandidateRejected("DATA_INELIGIBLE:VALIDATION_CAUSAL_COVERAGE")
        applied = apply_positions(data.ledger, signal.decisions)
        selected = applied.loc[
            (applied.index >= VALIDATION_START) & (applied.index <= VALIDATION_END)
        ]
        returns = selected["strategy_return"].dropna().astype(float)
        positions = selected.loc[returns.index, "position"].astype(np.int8)
        if len(returns) < 2000 or set(returns.index.year) != set(range(2011, 2021)):
            raise CandidateRejected("DATA_INELIGIBLE:INCOMPLETE_VALIDATION_COVERAGE")
        if not positions.isin((-1, 1)).all():
            raise CandidateRejected("TECHNICAL_FAILURE_POSITION")
        record = primary_metric_record(
            unit_key, "validation", returns.to_numpy(dtype=float), periods_per_year=252
        )
        for name in METRIC_FIELDS:
            row[f"validation_{name}"] = record.reported.get(name)
        extended = _extended_metrics(
            returns,
            positions,
            _market_regime_states(data, returns.index),
        )
        row.update(
            {key.replace("train_", "validation_", 1): value for key, value in extended.items()}
        )
        daily = [
            {
                "unit_key": unit_key,
                "date": date,
                "return": float(value),
                "position": int(position),
            }
            for date, value, position in zip(
                returns.index, returns.to_numpy(), positions.to_numpy(), strict=True
            )
        ]
        annual = [{"unit_key": unit_key, **item} for item in _annual_rows(returns)]
    except CandidateRejected as exc:
        row["status"] = "rejected"
        row["rejection_reason"] = str(exc)
        daily, annual = [], []
    return row, daily, annual


def _validation_gate_results(
    row: Mapping[str, Any],
    annual: pd.DataFrame,
    benchmarks: Mapping[str, Mapping[str, Any]],
    frozen: Mapping[str, Any],
) -> Mapping[str, bool]:
    def finite(value: Any, *, fallback: float = float("-inf")) -> float:
        try:
            converted = float(value)
        except (TypeError, ValueError):
            return fallback
        return converted if np.isfinite(converted) else fallback

    def benchmark_ratio(item: Mapping[str, Any], name: str) -> float:
        value = finite(item.get(name))
        if value != float("-inf"):
            return value
        return (
            float("inf")
            if finite(item.get("validation_cagr_pct"), fallback=0.0) > 0
            else float("-inf")
        )

    benchmark_rows = [
        benchmarks[name] for name in ("always_long", "symmetric_sma_200", "symmetric_momentum_12m")
    ]
    positive_log = annual.loc[annual["return_pct"] > 0, "return_pct"].map(
        lambda value: np.log1p(float(value) / 100.0)
    )
    concentration = (
        float(positive_log.max() / positive_log.sum())
        if len(positive_log) and positive_log.sum() > 0
        else 1.0
    )
    long_fraction = float(row["validation_long_days"]) / float(row["validation_period_count"])
    short_fraction = float(row["validation_short_days"]) / float(row["validation_period_count"])
    train_metrics = frozen["train_metrics"]
    candidate_cagr = finite(row.get("validation_cagr_pct"))
    candidate_sharpe = finite(row.get("validation_sharpe"))
    candidate_calmar = finite(row.get("validation_calmar"))
    candidate_drawdown = finite(row.get("validation_max_drawdown_pct"))
    candidate_rolling = finite(row.get("validation_median_rolling_3y_cagr_pct"))
    cagr_beats = all(
        candidate_cagr > finite(item.get("validation_cagr_pct")) for item in benchmark_rows
    )
    calmar_alternative = (
        all(
            candidate_calmar >= benchmark_ratio(item, "validation_calmar") + 0.15
            for item in benchmark_rows
        )
        and candidate_cagr >= finite(benchmarks["always_long"].get("validation_cagr_pct")) - 2.0
    )
    return {
        "cagr_positive": candidate_cagr > 0,
        "sharpe_ge_0_45": candidate_sharpe >= 0.45,
        "calmar_ge_0_35": candidate_calmar >= 0.35,
        "max_drawdown_gt_minus_45": candidate_drawdown > -45.0,
        "positive_years_ge_6": int(row["validation_positive_years"]) >= 6,
        "median_rolling_3y_positive": candidate_rolling > 0,
        "benchmark_return_or_calmar_gate": cagr_beats or calmar_alternative,
        "sharpe_beats_best_benchmark_by_0_10": candidate_sharpe
        >= max(benchmark_ratio(item, "validation_sharpe") for item in benchmark_rows) + 0.10,
        "positive_growth_concentration_le_50pct": concentration <= 0.50,
        "both_directions_ge_5pct": long_fraction >= 0.05 and short_fraction >= 0.05,
        "sharpe_degradation_gate": candidate_sharpe >= 0.40 * train_metrics["sharpe"],
        "calmar_degradation_gate": candidate_calmar >= 0.35 * train_metrics["calmar"],
    }


def run_validation_once(
    *,
    train_results_dir: Path,
    train_prepared_dir: Path,
    validation_prepared_dir: Path,
    output_dir: Path,
    validation_ack: str,
    code_sha: str | None = None,
) -> Mapping[str, Any]:
    if validation_ack != VALIDATION_ACK:
        raise ValidationGateError("VALIDATION_ACK_MISMATCH")
    train_root = Path(train_results_dir).resolve()
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    freeze = verify_train_freeze(train_root / "train_selection_freeze.json", code_sha=code_sha)
    finalists = list(freeze.get("finalists", []))
    if not finalists:
        raise ValidationGateError("NO_FROZEN_FINALISTS_VALIDATION_MUST_NOT_OPEN")
    train = load_market_snapshot(Path(train_prepared_dir))
    validation = load_market_snapshot(Path(validation_prepared_dir))
    data = combine_phase_snapshots(train, validation)
    lookup = _package().candidate_by_id()
    rows: list[dict[str, Any]] = []
    daily_rows: list[dict[str, Any]] = []
    annual_rows: list[dict[str, Any]] = []
    frozen_by_id = {str(item["strategy_id"]): item for item in finalists}
    for finalist in finalists:
        strategy_id = str(finalist["strategy_id"])
        candidate = lookup.get(strategy_id)
        if candidate is None or candidate["canonical_hash"] != finalist["canonical_hash"]:
            raise ValidationGateError(f"FROZEN_CANDIDATE_HASH_MISMATCH:{strategy_id}")
        row, daily, annual = _evaluate_validation_unit(data, strategy_id, candidate)
        rows.append(row)
        daily_rows.extend(daily)
        annual_rows.extend(annual)
    for benchmark_id in BENCHMARK_IDS:
        row, daily, annual = _evaluate_validation_unit(
            data,
            f"BENCHMARK::{benchmark_id}",
            {"benchmark_id": benchmark_id, "unit_type": "benchmark"},
        )
        rows.append(row)
        daily_rows.extend(daily)
        annual_rows.extend(annual)
    metrics = pd.DataFrame(rows)
    annual = pd.DataFrame(annual_rows)
    benchmark_map = {
        str(row["strategy_id"]): row
        for row in rows
        if row["unit_type"] == "benchmark" and row["status"] == "evaluated"
    }
    required_benchmarks = {"always_long", "symmetric_sma_200", "symmetric_momentum_12m"}
    if not required_benchmarks <= set(benchmark_map):
        raise ValidationGateError("VALIDATION_BENCHMARKS_INCOMPLETE")
    gate_rows = []
    for row in rows:
        if row["unit_type"] != "candidate" or row["status"] != "evaluated":
            continue
        strategy_id = str(row["strategy_id"])
        yearly = annual.loc[annual["unit_key"] == strategy_id]
        gates = _validation_gate_results(row, yearly, benchmark_map, frozen_by_id[strategy_id])
        passed = all(gates.values()) and not bool(frozen_by_id[strategy_id].get("diagnostic_only"))
        gate_rows.append(
            {
                "strategy_id": strategy_id,
                **gates,
                "diagnostic_only": bool(frozen_by_id[strategy_id].get("diagnostic_only")),
                "passes_all_validation_gates": passed,
            }
        )
    gate_frame = pd.DataFrame(gate_rows)
    metrics.to_csv(output / "validation_candidate_and_benchmark_metrics.csv", index=False)
    annual.to_csv(output / "validation_annual_returns.csv", index=False)
    gate_frame.to_csv(output / "validation_gates.csv", index=False)
    pq.write_table(pa.Table.from_pylist(daily_rows), output / "validation_daily_returns.parquet")
    passing = int(gate_frame["passes_all_validation_gates"].sum()) if len(gate_frame) else 0
    rejected_finalists = int(
        ((metrics["unit_type"] == "candidate") & (metrics["status"] == "rejected")).sum()
    )
    rejected_benchmarks = int(
        ((metrics["unit_type"] == "benchmark") & (metrics["status"] == "rejected")).sum()
    )
    if rejected_finalists or rejected_benchmarks:
        result_status = "TECHNICAL_FAILURE"
    elif passing:
        result_status = "POSITIVE_VALIDATED_RESULT"
    else:
        result_status = "NEGATIVE_RESULT"
    summary = {
        "schema_version": "1",
        "campaign_id": "sp500_long_short_daily_zero_cost_v1",
        "result_status": result_status,
        "frozen_finalists": len(finalists),
        "evaluated_finalists": int(
            ((metrics["unit_type"] == "candidate") & (metrics["status"] == "evaluated")).sum()
        ),
        "rejected_finalists": rejected_finalists,
        "rejected_benchmarks": rejected_benchmarks,
        "passing_finalists": passing,
        "validation_start": "2011-01-01",
        "validation_end": "2020-12-31",
        "validation_opened": True,
        "validation_used_for_selection": False,
        "locked_start": "2021-01-01",
        "locked_opened": False,
        "train_freeze_sha256": freeze["freeze_sha256"],
        "code_sha": code_sha or os.environ.get("GITHUB_SHA", "LOCAL_TEST_ONLY"),
    }
    summary["summary_sha256"] = canonical_json_hash(summary)
    (output / "validation_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    shutil.copy2(
        train_root / "train_selection_freeze.json",
        output / "train_selection_freeze.json",
    )
    for source_name, target_name in (
        ("raw_manifest.jsonl", "validation_raw_manifest.jsonl"),
        ("market_data_manifest.json", "validation_market_data_manifest.json"),
    ):
        source = Path(validation_prepared_dir) / source_name
        if not source.is_file():
            raise ValidationGateError(f"VALIDATION_EVIDENCE_MISSING:{source_name}")
        shutil.copy2(source, output / target_name)
    (output / "RESULT_STATUS.md").write_text(
        "\n".join(
            (
                f"# {result_status}",
                "",
                f"- Frozen finalists: {len(finalists)}",
                f"- Passing finalists: {passing}",
                f"- Rejected finalists: {rejected_finalists}",
                "- Validation opened once: true",
                "- Validation used for selection: false",
                "- Locked observations opened: false",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    files = [
        path for path in output.iterdir() if path.is_file() and path.name != "final_manifest.json"
    ]
    final_manifest = {
        "schema_version": "1",
        "campaign_id": "sp500_long_short_daily_zero_cost_v1",
        "result_status": result_status,
        "validation_opened": True,
        "validation_used_for_selection": False,
        "locked_start": "2021-01-01",
        "locked_opened": False,
        "files": {path.name: sha256_file(path) for path in sorted(files)},
    }
    final_manifest["manifest_sha256"] = canonical_json_hash(final_manifest)
    (output / "final_manifest.json").write_text(
        json.dumps(final_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary
