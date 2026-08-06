"""One-shot validation for cryptographically frozen V2 train finalists."""

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

from aurora.infra.github_performance.shard_planner import sha256_file
from aurora.infra.github_performance.workloads.common import primary_metric_record
from aurora.infra.sp500_long_short_daily.ledger import apply_positions
from aurora.infra.sp500_long_short_daily.signals import CandidateRejected, benchmark_decisions
from aurora.infra.sp500_long_short_daily.validation import (
    _validation_gate_results,
    combine_phase_snapshots,
)
from aurora.infra.sp500_long_short_daily.workload import (
    BENCHMARK_IDS,
    METRIC_FIELDS,
    _annual_rows,
    _extended_metrics,
    _market_regime_states,
)
from aurora.infra.sp500_long_short_daily_v2.contracts import (
    EXPECTED_V1_RESULTS_SHA256,
    VALIDATION_ACK,
    canonical_json_hash,
)
from aurora.infra.sp500_long_short_daily_v2.data import load_market_snapshot
from aurora.infra.sp500_long_short_daily_v2.signals import FeatureStore, candidate_decisions
from aurora.infra.sp500_long_short_daily_v2.workload import _package

VALIDATION_START = pd.Timestamp("2011-01-01")
VALIDATION_END = pd.Timestamp("2020-12-31")
LOCKED_START = pd.Timestamp("2021-01-01")


class ValidationGateError(RuntimeError):
    """Raised before validation performance is exposed when a gate fails."""


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
    if freeze.get("train_end") != "2010-12-31":
        raise ValidationGateError("TRAIN_FREEZE_DATES_INVALID")
    if freeze.get("validation_start") != "2011-01-01" or freeze.get("validation_end") != "2020-12-31":
        raise ValidationGateError("TRAIN_FREEZE_DATES_INVALID")
    if freeze.get("locked_start") != "2021-01-01":
        raise ValidationGateError("TRAIN_FREEZE_DATES_INVALID")
    if freeze.get("validation_authorization_required") != VALIDATION_ACK:
        raise ValidationGateError("TRAIN_FREEZE_ACK_CONTRACT_MISMATCH")
    if freeze.get("v1_results_sha256") != EXPECTED_V1_RESULTS_SHA256:
        raise ValidationGateError("COMBINED_MULTIPLICITY_INCOMPLETE")
    if int(freeze.get("cumulative_declared_trials", 0)) != 312:
        raise ValidationGateError("COMBINED_MULTIPLICITY_INCOMPLETE")
    current_sha = code_sha or os.environ.get("GITHUB_SHA", "")
    frozen_sha = str(freeze.get("code_sha", ""))
    if current_sha and frozen_sha not in {current_sha, "LOCAL_TEST_ONLY"}:
        raise ValidationGateError("TRAIN_FREEZE_CODE_SHA_MISMATCH")
    finalists = list(freeze.get("finalists", []))
    if not finalists:
        raise ValidationGateError("NO_FROZEN_FINALISTS_VALIDATION_MUST_NOT_OPEN")
    for finalist in finalists:
        if finalist.get("eligible_for_validation") is not True:
            raise ValidationGateError("INELIGIBLE_FROZEN_FINALIST")
        if finalist.get("candidate_rules", {}).get("evidence_track") != "pre_2011_evidence":
            raise ValidationGateError("POST_2010_FINALIST_PROHIBITED")
    return freeze


def _evaluate_unit(
    data: Any,
    unit_key: str,
    parameters: Mapping[str, Any],
    feature_store: FeatureStore,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    is_benchmark = parameters.get("unit_type") == "benchmark"
    strategy_id = str(parameters.get("benchmark_id", parameters.get("strategy_id", unit_key)))
    row: dict[str, Any] = {
        "unit_key": unit_key,
        "strategy_id": strategy_id,
        "unit_type": "benchmark" if is_benchmark else "candidate",
        "family": "benchmark" if is_benchmark else str(parameters["family"]),
        "canonical_hash": canonical_json_hash(parameters) if is_benchmark else parameters["canonical_hash"],
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
            else candidate_decisions(parameters, data, feature_store=feature_store)
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
        row.update(
            {
                key.replace("train_", "validation_", 1): value
                for key, value in _extended_metrics(
                    returns, positions, _market_regime_states(data, returns.index)
                ).items()
            }
        )
        daily = [
            {"unit_key": unit_key, "date": date, "return": float(value), "position": int(position)}
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
    freeze = verify_train_freeze(
        train_root / "v2_train_selection_freeze.json", code_sha=code_sha
    )
    train = load_market_snapshot(Path(train_prepared_dir))
    validation = load_market_snapshot(Path(validation_prepared_dir))
    data = combine_phase_snapshots(train, validation)
    if data.ledger.index.max() >= LOCKED_START:
        raise ValidationGateError("TECHNICAL_FAILURE_LOCKED_BREACH")
    feature_store = FeatureStore.build(data)
    lookup = _package().candidate_by_id()
    rows: list[dict[str, Any]] = []
    daily_rows: list[dict[str, Any]] = []
    annual_rows: list[dict[str, Any]] = []
    frozen_by_id = {str(item["strategy_id"]): item for item in freeze["finalists"]}
    for finalist in freeze["finalists"]:
        strategy_id = str(finalist["strategy_id"])
        candidate = lookup.get(strategy_id)
        if candidate is None or candidate["canonical_hash"] != finalist["canonical_hash"]:
            raise ValidationGateError(f"FROZEN_CANDIDATE_HASH_MISMATCH:{strategy_id}")
        row, daily, annual = _evaluate_unit(data, strategy_id, candidate, feature_store)
        rows.append(row)
        daily_rows.extend(daily)
        annual_rows.extend(annual)
    for benchmark_id in BENCHMARK_IDS:
        row, daily, annual = _evaluate_unit(
            data,
            f"BENCHMARK::{benchmark_id}",
            {"benchmark_id": benchmark_id, "unit_type": "benchmark"},
            feature_store,
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
    required = {"always_long", "symmetric_sma_200", "symmetric_momentum_12m"}
    if not required <= set(benchmark_map):
        raise ValidationGateError("VALIDATION_BENCHMARKS_INCOMPLETE")
    gates: list[dict[str, Any]] = []
    for row in rows:
        if row["unit_type"] != "candidate" or row["status"] != "evaluated":
            continue
        strategy_id = str(row["strategy_id"])
        yearly = annual.loc[annual["unit_key"] == strategy_id]
        results = _validation_gate_results(
            row, yearly, benchmark_map, frozen_by_id[strategy_id]
        )
        gates.append(
            {"strategy_id": strategy_id, **results, "passes_all_validation_gates": all(results.values())}
        )
    gate_frame = pd.DataFrame(gates)
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
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
    status = (
        "TECHNICAL_FAILURE"
        if rejected_finalists or rejected_benchmarks
        else "POSITIVE_VALIDATED_RESULT" if passing else "NEGATIVE_RESULT"
    )
    summary = {
        "schema_version": "2",
        "campaign_id": "sp500_long_short_daily_zero_cost_v2_new_strategies",
        "result_status": status,
        "frozen_finalists": len(freeze["finalists"]),
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
    shutil.copy2(train_root / "v2_train_selection_freeze.json", output / "v2_train_selection_freeze.json")
    for source_name, target_name in (
        ("raw_manifest.jsonl", "validation_raw_manifest.jsonl"),
        ("market_data_manifest.json", "validation_market_data_manifest.json"),
    ):
        source = Path(validation_prepared_dir) / source_name
        if not source.is_file():
            raise ValidationGateError(f"VALIDATION_EVIDENCE_MISSING:{source_name}")
        shutil.copy2(source, output / target_name)
    (output / "RESULT_STATUS.md").write_text(
        f"# {status}\n\n- Frozen finalists: {len(freeze['finalists'])}\n- Passing finalists: {passing}\n- Validation opened once: true\n- Validation used for selection: false\n- Locked opened: false\n",
        encoding="utf-8",
    )
    files = [p for p in output.iterdir() if p.is_file() and p.name != "final_manifest.json"]
    manifest = {
        "schema_version": "2",
        "campaign_id": summary["campaign_id"],
        "result_status": status,
        "validation_opened": True,
        "validation_used_for_selection": False,
        "locked_start": "2021-01-01",
        "locked_opened": False,
        "files": {p.name: sha256_file(p) for p in sorted(files)},
    }
    manifest["manifest_sha256"] = canonical_json_hash(manifest)
    (output / "final_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary
