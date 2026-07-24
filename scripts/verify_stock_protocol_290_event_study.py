"""Fail closed unless the final 290-combination event-study artifact is complete."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from aurora.research.stock_protocol.event_study_290_manifest import (
    COMBINATION_MANIFEST_NAME,
    ENTRY_SPECS_NAME,
    EXIT_SPECS_NAME,
    EXPECTED_COMBINATION_COUNT,
    EXPECTED_ENTRY_SPEC_COUNT,
    EXPECTED_EXIT_SPEC_COUNT,
)
from aurora.research.stock_protocol.event_study_290_statistics import (
    SURVIVAL_REPORTING_HORIZONS,
)
from scripts.merge_stock_protocol_290_event_study import (
    AUDIT_SUMMARY_NAME,
    COVERAGE_CSV_GZIP,
    COVERAGE_PARQUET,
    CUTOFF,
    EXPECTED_CORRECTED_SHARDS,
    EXPECTED_HISTORICAL_SHARDS,
    FINAL_MANIFEST_NAME,
    FINAL_REPORT_NAME,
    FINANCING_RECONCILIATION_STATUSES,
    FROZEN_FX_RATES_NAME,
    FUNCTIONAL_DUPLICATES_NAME,
    FX_AUDIT_NAME,
    EXACT_STRATEGY_NAME,
    OPPORTUNITIES_CSV_GZIP,
    OPPORTUNITIES_PARQUET,
    OPPORTUNITIES_PARTS,
    PERIOD_NAMES,
    PRIOR_AUDIT_RECONCILIATION_NAME,
    RECONCILIATION_NAME,
    REQUIRED_TOP_LEVEL_FILES,
    SEMANTIC_AUDIT_NAME,
    SOURCE_LOCK_NAME,
    STATISTIC_FILES,
)
from scripts.run_stock_protocol_290_historical_shard import (
    AUDIT_NAME as HISTORICAL_AUDIT_NAME,
    METRIC_TOLERANCES,
    OUTPUT_NAME as HISTORICAL_RESULTS_NAME,
)


FORBIDDEN_EVENT_METRICS = ("cagr", "sharpe", "portfolio_sharpe")
FALSE_FLAGS = (
    "new_oos_claimed",
    "optimization_performed_on_opened_data",
    "validation_used_for_selection",
)
TRUE_FLAGS = (
    "no_portfolio_simulation",
    "no_capital_exclusions",
    "all_combinations_reconciled",
    "historical_replication_passed",
    "semantic_audit_preserved",
    "functional_duplicates_preserved",
)

OPPORTUNITY_LEDGER_REQUIRED_COLUMNS = (
    "entry_index", "opportunity_id", "combination_id", "entry_spec_id",
    "exit_spec_id", "candidate_id", "upstream_candidate_id",
    "entry_upstream_candidate_id", "upstream_candidate_ids_json",
    "track", "status", "applicability", "censored", "censor_reason",
    "delisting_date", "symbol", "selection_date", "signal_date",
    "entry_signal_date", "entry_date", "entry_price", "exit_date", "exit_price",
    "optimistic_exit_price", "exit_reason", "gross_return", "mtm_date",
    "mtm_price", "mtm_return", "maximum_favourable_excursion",
    "maximum_adverse_excursion", "intratrade_max_drawdown", "holding_sessions",
    "calendar_days_invested", "stop_hit", "target_hit", "time_exit",
    "max_holding_reached", "volatility", "score", "period",
    "semantic_applicability", "semantic_not_applicable_reason", "ranking_eligible",
    "dataset_cutoff", "entry_value_local_per_initial_share",
    "exit_value_local_per_initial_share", "price_return_local", "total_return_local",
    "dividends_local", "dividend_payments_local_json", "dividend_event_count",
    "split_event_count", "cumulative_split_factor", "entry_day_volume",
    "entry_day_dollar_volume_local", "entry_adv20_local", "executor_gross_return",
    "country", "market", "exchange", "currency", "price_scale_to_currency_unit",
    "metadata_source", "currency_unknown", "fx_entry_date",
    "fx_entry_rate_usd_per_local", "fx_exit_date", "fx_exit_rate_usd_per_local",
    "fx_dividend_dates_used", "dividend_value_usd_per_share",
    "entry_value_usd_per_share", "exit_value_usd_per_share", "return_usd",
    "fx_return_contribution", "fx_merge_status", "fx_values_invented",
    "capital_rejected", "capital_rejection_reason", "portfolio_simulated",
    "sizing_applied", "overlap_discarded", "new_oos_claimed",
    "optimization_performed_on_opened_data", "primary_event_return",
    "primary_event_return_basis", "gross_return_basis",
    "financed_in_old_portfolio", "financing_information_only",
    "financing_reconciliation_status", "prior_audit_opportunity_id",
    "prior_not_financed_reason",
    "entry_gap", "signal_score", "mom_12_1", "mom_6_1",
    "momentum_12_1", "momentum_6_1", "h52", "high_52", "rvol50", "atr20",
    "wait_sessions", "waits", "waited", "remaining_sessions_estimate",
    "trajectory_volatility", "entry_rule", "entry_rule_kind", "entry_rule_json",
    "exit_rule", "exit_rule_json", "component_signals_json",
    "signal_weights_json", "cost_levels_bps_per_side_json",
    "net_returns_by_cost_bps_json", "liquidity_entry_volume",
    "liquidity_entry_notional_local", "liquidity_adv20_local",
    "liquidity_currency",
    *(f"breakout_{window}" for window in (20, 50, 100, 150, 200, 252)),
    *(f"breakout_level_{window}" for window in (20, 50, 100, 150, 200, 252)),
    *(f"round_trip_cost_{cost}bps" for cost in (0, 5, 10, 25, 50, 100, 200)),
    *(f"net_return_{cost}bps" for cost in (0, 5, 10, 25, 50, 100, 200)),
    *(
        f"net_return_cost_{cost}_bps_per_side"
        for cost in (0, 5, 10, 25, 50, 100, 200)
    ),
)

OPPORTUNITY_VERIFICATION_COLUMNS = (
    "opportunity_id",
    "combination_id",
    "period",
    "status",
    "censored",
    "time_exit",
    "exit_reason",
    "entry_date",
    "exit_date",
    "mtm_date",
    "return_usd",
    "total_return_local",
    "primary_event_return",
    "gross_return",
    "primary_event_return_basis",
    "gross_return_basis",
    "capital_rejected",
    "capital_rejection_reason",
    "portfolio_simulated",
    "sizing_applied",
    "overlap_discarded",
    "fx_values_invented",
    "financing_information_only",
    "financing_reconciliation_status",
    "prior_audit_opportunity_id",
    "fx_entry_date",
    "fx_exit_date",
    "dividend_payments_local_json",
    "fx_dividend_dates_used",
)

COVERAGE_REQUIRED_COLUMNS = (
    "entry_index", "entry_spec_id", "symbol", "selection_date",
    "entry_signal_date", "entry_date_resolved", "selected", "triggered",
    "wait_sessions", "waited", "waits", "entry_in_period", "coverage_status",
    "period_assignment_basis", "period",
)

REPORT_QUESTION_IDS = tuple(f"Q{number:02d}" for number in range(1, 26))


class EventStudy290VerificationError(ValueError):
    """Raised when a final event-study artifact violates its frozen contract."""


def _fail(message: str) -> None:
    raise EventStudy290VerificationError(message)


def _require(condition: bool, message: str) -> None:
    if not condition:
        _fail(message)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        _fail(f"missing required file: {path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EventStudy290VerificationError(f"invalid JSON: {path.name}") from exc
    if not isinstance(value, dict):
        _fail(f"{path.name} must contain a JSON object")
    return value


def _as_bool(value: object, label: str) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    normalized = str(value).strip().lower()
    if normalized in {"true", "1"}:
        return True
    if normalized in {"false", "0"}:
        return False
    _fail(f"{label} is not boolean")
    raise AssertionError("unreachable")


def _columns(frame: pd.DataFrame, required: Iterable[str], label: str) -> None:
    missing = set(required) - set(frame.columns)
    if missing:
        _fail(f"{label} missing columns: {sorted(missing)}")


def _finite_frame(frame: pd.DataFrame, label: str) -> None:
    numeric = frame.select_dtypes(include=[np.number])
    if numeric.empty:
        return
    if numeric.isna().any().any() or not np.isfinite(numeric.to_numpy(dtype=float)).all():
        _fail(f"{label} contains non-finite numeric values")
    forbidden_text = {"nan", "+nan", "-nan", "inf", "+inf", "-inf", "infinity"}
    for column in frame.select_dtypes(include=["object"]).columns:
        values = frame[column].dropna().astype(str).str.strip().str.lower()
        if values.isin(forbidden_text).any():
            _fail(f"{label}.{column} contains a textual non-finite value")


def _finite_json(value: object, label: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            _finite_json(item, f"{label}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _finite_json(item, f"{label}[{index}]")
    elif isinstance(value, float) and not math.isfinite(value):
        _fail(f"{label} is non-finite")


def _dates(frame: pd.DataFrame, label: str) -> None:
    for column in frame.columns:
        lower = column.lower()
        if lower not in {
            "date",
            "selection_date",
            "signal_date",
            "entry_signal_date",
            "entry_date",
            "exit_date",
            "mtm_date",
            "fx_date",
            "fx_entry_date",
            "fx_exit_date",
            "comparison_end",
            "start",
            "end",
        } and not lower.endswith("_date"):
            continue
        values = pd.to_datetime(frame[column], errors="coerce").dropna()
        if not values.empty and values.max().normalize() > CUTOFF:
            _fail(f"{label}.{column} exceeds {CUTOFF.date()}")


def _verify_required_files(root: Path) -> None:
    present = {path.name for path in root.iterdir() if path.is_file()}
    missing = REQUIRED_TOP_LEVEL_FILES - present
    if missing:
        _fail(f"missing required files: {sorted(missing)}")
    part_root = root / OPPORTUNITIES_PARTS
    _require(part_root.is_dir(), f"missing partitioned output: {OPPORTUNITIES_PARTS}")
    parts = sorted(part_root.glob("period=*/part-*.csv.gz"))
    _require(len(parts) == len(PERIOD_NAMES), "partitioned opportunity output must have three parts")
    _require(
        {path.parent.name for path in parts} == {f"period={period}" for period in PERIOD_NAMES},
        "partitioned opportunity output does not cover A, B and C",
    )


def _verify_manifest(root: Path) -> None:
    manifest = _json(root / FINAL_MANIFEST_NAME)
    _require(manifest.get("hash_algorithm") == "sha256", "artifact manifest is not sha256")
    files = manifest.get("files")
    _require(isinstance(files, dict) and bool(files), "artifact manifest has no files")
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != FINAL_MANIFEST_NAME
    }
    _require(set(files) == actual, "artifact manifest file inventory differs from disk")
    for relative, metadata in files.items():
        _require(isinstance(metadata, dict), f"invalid manifest metadata for {relative}")
        path = root / relative
        _require(path.is_file(), f"manifest path is missing: {relative}")
        _require(path.stat().st_size == metadata.get("bytes"), f"size mismatch: {relative}")
        _require(_sha256(path) == metadata.get("sha256"), f"sha256 mismatch: {relative}")


def _verify_summary(root: Path) -> dict[str, Any]:
    summary = _json(root / AUDIT_SUMMARY_NAME)
    expected = {
        "contract": "290-10-29",
        "combination_count": EXPECTED_COMBINATION_COUNT,
        "entry_spec_count": EXPECTED_ENTRY_SPEC_COUNT,
        "exit_spec_count": EXPECTED_EXIT_SPEC_COUNT,
        "historical_shard_count": EXPECTED_HISTORICAL_SHARDS,
        "corrected_shard_count": EXPECTED_CORRECTED_SHARDS,
        "cutoff": CUTOFF.date().isoformat(),
        "selection_period": "A",
        "diagnostic_periods": ["B", "C"],
    }
    for key, value in expected.items():
        _require(summary.get(key) == value, f"audit summary has invalid {key}")
    for flag in FALSE_FLAGS:
        _require(summary.get(flag) is False, f"audit flag {flag} must be false")
    for flag in TRUE_FLAGS:
        _require(summary.get(flag) is True, f"audit flag {flag} must be true")
    counts = [
        int(summary.get("completed", -1)),
        int(summary.get("censored", -1)),
        int(summary.get("failed_due_to_data", -1)),
    ]
    _require(all(value >= 0 for value in counts), "audit status counts are invalid")
    _require(sum(counts) == int(summary.get("opportunity_count", -1)), "audit counts do not reconcile")
    _require(summary.get("declared_tests") == EXPECTED_COMBINATION_COUNT, "audit declared_tests is not 290")
    eligible = int(summary.get("eligible_tests", -1))
    unique = int(summary.get("functionally_unique_tests", -1))
    _require(0 <= eligible <= EXPECTED_COMBINATION_COUNT, "audit eligible_tests is invalid")
    _require(2 <= unique <= EXPECTED_COMBINATION_COUNT, "audit global unique count is invalid")
    _require(summary.get("prior_audit_financing_reconciled") is True, "prior financing did not reconcile")
    _require(summary.get("financing_information_only") is True, "old financing is not informational")
    financed = int(summary.get("financed_in_old_portfolio", -1))
    not_financed = int(summary.get("not_financed_in_old_portfolio", -1))
    _require(financed >= 0 and not_financed >= 0, "old financing counts are invalid")
    classification_counts = summary.get("classification_counts")
    _require(isinstance(classification_counts, dict), "classification counts are absent")
    _require(
        sum(int(value) for value in classification_counts.values())
        == EXPECTED_COMBINATION_COUNT,
        "classification counts do not total 290",
    )
    for field in (
        "manifest_sha256",
        "dataset_hash",
        "policy_hash",
        "source_snapshot_sha256",
        "source_lock_sha256",
        "exact_strategy_sha256",
        "frozen_fx_rates_sha256",
    ):
        value = str(summary.get(field, ""))
        _require(
            len(value) == 64 and all(character in "0123456789abcdef" for character in value),
            f"audit {field} is not a complete sha256",
        )
    _finite_json(summary, AUDIT_SUMMARY_NAME)
    return summary


def _verify_contract(root: Path) -> pd.DataFrame:
    manifest = pd.read_csv(
        root / COMBINATION_MANIFEST_NAME, dtype=str, keep_default_na=False
    )
    _columns(
        manifest,
        (
            "combination_id",
            "entry_spec_id",
            "exit_spec_id",
            "corrected_track_applicability",
            "dataset_hash",
            "policy_hash",
            "source_snapshot_sha256",
        ),
        "contract manifest",
    )
    _require(len(manifest) == EXPECTED_COMBINATION_COUNT, "contract manifest is not 290 rows")
    _require(manifest["combination_id"].nunique() == EXPECTED_COMBINATION_COUNT, "contract IDs are not unique")
    _require(manifest["entry_spec_id"].nunique() == EXPECTED_ENTRY_SPEC_COUNT, "contract is not 10 entries")
    _require(manifest["exit_spec_id"].nunique() == EXPECTED_EXIT_SPEC_COUNT, "contract is not 29 exits")
    _require(
        not manifest[["entry_spec_id", "exit_spec_id"]].duplicated().any(),
        "contract repeats an entry/exit pair",
    )
    entries = json.loads((root / ENTRY_SPECS_NAME).read_text(encoding="utf-8"))
    exits = json.loads((root / EXIT_SPECS_NAME).read_text(encoding="utf-8"))
    _require(isinstance(entries, list) and len(entries) == EXPECTED_ENTRY_SPEC_COUNT, "entry spec JSON is not 10")
    _require(isinstance(exits, list) and len(exits) == EXPECTED_EXIT_SPEC_COUNT, "exit spec JSON is not 29")
    return manifest


def _verify_historical(root: Path, contract: pd.DataFrame) -> None:
    results = pd.read_csv(root / HISTORICAL_RESULTS_NAME, dtype={"combination_id": str})
    _dates(results, HISTORICAL_RESULTS_NAME)
    audit = _json(root / HISTORICAL_AUDIT_NAME)
    _require(len(results) == EXPECTED_COMBINATION_COUNT, "historical results are not 290 rows")
    _require(results["combination_id"].nunique() == EXPECTED_COMBINATION_COUNT, "historical results repeat IDs")
    _require(set(results["combination_id"]) == set(contract["combination_id"]), "historical IDs differ from contract")
    _require(audit.get("historical_shard_count") == EXPECTED_HISTORICAL_SHARDS, "historical audit is not 10 shards")
    _require(audit.get("combination_count") == EXPECTED_COMBINATION_COUNT, "historical audit is not 290 combinations")
    _require(audit.get("all_replications_passed") is True, "historical audit did not pass")
    _require(audit.get("metric_tolerances") == METRIC_TOLERANCES, "historical tolerances changed")
    _require(results["replication_passed"].map(lambda value: _as_bool(value, "replication_passed")).all(), "historical row failed")
    for metric, tolerance in METRIC_TOLERANCES.items():
        columns = (
            f"{metric}_difference",
            f"{metric}_tolerance",
            f"{metric}_available",
            f"{metric}_passed",
        )
        _columns(results, columns, "historical results")
        difference = pd.to_numeric(results[columns[0]], errors="coerce")
        declared = pd.to_numeric(results[columns[1]], errors="coerce")
        _require(not difference.isna().any() and np.isfinite(difference).all(), f"historical {metric} is non-finite")
        _require(np.isclose(declared, tolerance, rtol=0.0, atol=0.0).all(), f"historical {metric} tolerance changed")
        _require((difference.abs() <= tolerance).all(), f"historical {metric} exceeds tolerance")
        _require(results[columns[2]].map(lambda value: _as_bool(value, columns[2])).all(), f"historical {metric} unavailable")
        _require(results[columns[3]].map(lambda value: _as_bool(value, columns[3])).all(), f"historical {metric} failed")


def _verify_opportunities(root: Path, summary: Mapping[str, Any], contract: pd.DataFrame) -> pd.DataFrame:
    parquet_path = root / OPPORTUNITIES_PARQUET
    parquet_file = pq.ParquetFile(parquet_path)
    parquet_schema = parquet_file.schema_arrow.names
    missing = set(OPPORTUNITY_LEDGER_REQUIRED_COLUMNS) - set(parquet_schema)
    _require(not missing, f"opportunities missing columns: {sorted(missing)}")
    lineage_columns = (
        "combination_id",
        "candidate_id",
        "upstream_candidate_id",
        "entry_upstream_candidate_id",
        "upstream_candidate_ids_json",
    )
    observed_lineage: set[tuple[str, ...]] = set()
    for batch in parquet_file.iter_batches(
        batch_size=100_000, columns=list(lineage_columns)
    ):
        lineage = batch.to_pandas(types_mapper=pd.ArrowDtype).drop_duplicates()
        observed_lineage.update(
            tuple(str(value) for value in row)
            for row in lineage.itertuples(index=False, name=None)
        )
    expected_lineage = {
        tuple(str(value) for value in row)
        for row in contract.loc[:, lineage_columns].itertuples(index=False, name=None)
    }
    _require(
        observed_lineage == expected_lineage,
        "opportunity lineage differs from the frozen 290-combination manifest",
    )
    csv_columns = pd.read_csv(root / OPPORTUNITIES_CSV_GZIP, nrows=0).columns.tolist()
    _require(set(parquet_schema) == set(csv_columns), "parquet and gzip ledger schemas differ")
    parquet = pd.read_parquet(
        parquet_path,
        columns=list(OPPORTUNITY_VERIFICATION_COLUMNS),
        dtype_backend="pyarrow",
    )
    csv_rows = sum(
        len(chunk)
        for chunk in pd.read_csv(
            root / OPPORTUNITIES_CSV_GZIP,
            usecols=["opportunity_id"],
            chunksize=200_000,
            dtype_backend="pyarrow",
        )
    )
    _require(len(parquet) == csv_rows, "parquet and gzip opportunity counts differ")
    _require(len(parquet) == int(summary["opportunity_count"]), "opportunity count differs from audit")
    _require(parquet["opportunity_id"].nunique() == len(parquet), "technical opportunity IDs are duplicated")
    _require(set(parquet["combination_id"].astype(str)) == set(contract["combination_id"]), "opportunities do not cover exact contract")
    _require(set(parquet["period"].astype(str)) == set(PERIOD_NAMES), "opportunities do not cover A, B and C")
    statuses = parquet["status"].astype(str)
    _require(set(statuses) <= {"completed", "right_censored", "failed_due_to_data"}, "opportunity status is invalid")
    right_censored = statuses.eq("right_censored")
    completed_status = statuses.eq("completed")
    censored_right = parquet.loc[right_censored, "censored"].map(
        lambda value: _as_bool(value, "censored")
    )
    censored_completed = parquet.loc[completed_status, "censored"].map(
        lambda value: _as_bool(value, "censored")
    )
    time_exit_censored = parquet.loc[right_censored, "time_exit"].map(
        lambda value: _as_bool(value, "time_exit")
    )
    _require(
        censored_right.all() and not censored_completed.any(),
        "censored flag does not match right-censored status",
    )
    _require(
        not time_exit_censored.any(),
        "a right-censored opportunity was counted as a time exit",
    )
    _require(
        not parquet.loc[right_censored, "exit_reason"]
        .fillna("")
        .astype(str)
        .str.lower()
        .str.contains("time")
        .any(),
        "a right-censored opportunity declares a temporal exit reason",
    )
    actual_counts = {
        "completed": int(statuses.eq("completed").sum()),
        "censored": int(statuses.eq("right_censored").sum()),
        "failed_due_to_data": int(statuses.eq("failed_due_to_data").sum()),
    }
    for key, value in actual_counts.items():
        _require(value == int(summary[key]), f"opportunity {key} count differs from audit")
    completed = statuses.eq("completed")
    usd = pd.to_numeric(parquet["return_usd"], errors="coerce")
    local = pd.to_numeric(parquet["total_return_local"], errors="coerce")
    primary = pd.to_numeric(parquet["primary_event_return"], errors="coerce")
    gross = pd.to_numeric(parquet["gross_return"], errors="coerce")
    expected_primary = usd.where(usd.notna(), local)
    _require(
        np.isclose(
            primary.loc[completed].to_numpy(dtype=float),
            expected_primary.loc[completed].to_numpy(dtype=float),
            rtol=1e-12,
            atol=1e-14,
        ).all(),
        "primary event return is not USD total return with local fallback",
    )
    _require(
        np.isclose(
            gross.loc[completed].to_numpy(dtype=float),
            primary.loc[completed].to_numpy(dtype=float),
            rtol=1e-12,
            atol=1e-14,
        ).all(),
        "gross_return does not carry the selected total-return metric",
    )
    expected_basis = np.where(
        usd.loc[completed].notna(), "total_return_usd", "total_return_local"
    )
    _require(
        np.array_equal(
            parquet.loc[completed, "primary_event_return_basis"].astype(str).to_numpy(),
            expected_basis,
        ),
        "primary event return basis is invalid",
    )
    _require(
        np.array_equal(
            parquet.loc[completed, "gross_return_basis"].astype(str).to_numpy(),
            parquet.loc[completed, "primary_event_return_basis"].astype(str).to_numpy(),
        ),
        "gross and primary return bases differ",
    )
    _require(
        primary.loc[~completed].isna().all() and gross.loc[~completed].isna().all(),
        "non-completed opportunities declare a realized return",
    )
    for column in ("capital_rejected", "portfolio_simulated", "sizing_applied", "overlap_discarded"):
        if column in parquet:
            _require(not parquet[column].map(lambda value: _as_bool(value, column)).any(), f"{column} was applied")
    if "capital_rejection_reason" in parquet:
        reasons = parquet["capital_rejection_reason"].fillna("").astype(str).str.strip()
        _require(reasons.eq("").all(), "capital rejection reasons are present")
    _require(not parquet["fx_values_invented"].map(lambda value: _as_bool(value, "fx_values_invented")).any(), "FX values were invented")
    _require(
        parquet["financing_information_only"]
        .map(lambda value: _as_bool(value, "financing_information_only"))
        .all(),
        "old financing was not labelled informational",
    )
    financing_status = parquet["financing_reconciliation_status"].astype(str)
    _require(
        set(financing_status) <= FINANCING_RECONCILIATION_STATUSES,
        "old financing reconciliation status is invalid",
    )
    matched_financing = financing_status.eq("matched_prior_audit")
    _require(matched_financing.any(), "no opportunity reconciles to prior financing")
    linked_to_prior = financing_status.isin(
        {"matched_prior_audit", "prior_audit_only_failed_due_to_data"}
    )
    _require(
        parquet.loc[linked_to_prior, "prior_audit_opportunity_id"]
        .fillna("")
        .astype(str)
        .str.strip()
        .ne("")
        .all(),
        "prior-linked financing rows lack prior audit IDs",
    )
    entry_dates = pd.to_datetime(parquet["entry_date"], errors="coerce")
    valuation_dates = pd.to_datetime(parquet["exit_date"], errors="coerce").where(
        statuses.ne("right_censored"),
        pd.to_datetime(parquet["mtm_date"], errors="coerce"),
    )
    fx_entry_dates = pd.to_datetime(parquet["fx_entry_date"], errors="coerce")
    fx_exit_dates = pd.to_datetime(parquet["fx_exit_date"], errors="coerce")
    _require(
        not (fx_entry_dates.notna() & (fx_entry_dates > entry_dates)).any(),
        "future FX was used at entry",
    )
    _require(
        not (fx_exit_dates.notna() & (fx_exit_dates > valuation_dates)).any(),
        "future FX was used at exit or mark-to-market",
    )
    dividend_rows = parquet.loc[
        parquet["dividend_payments_local_json"].fillna("[]").astype(str).ne("[]")
    ]
    for row in dividend_rows.itertuples(index=False):
        try:
            payments = json.loads(str(row.dividend_payments_local_json))
        except json.JSONDecodeError as exc:
            raise EventStudy290VerificationError(
                "invalid dividend_payments_local_json"
            ) from exc
        _require(isinstance(payments, list), "dividend payments are not a JSON list")
        payment_dates = [str(payment["date"]) for payment in payments]
        used_dates = [
            value
            for value in str(getattr(row, "fx_dividend_dates_used", "")).split(",")
            if value
        ]
        if pd.notna(row.return_usd):
            _require(payment_dates == used_dates, "USD return omits causal dividend dates")
        for date in payment_dates:
            timestamp = pd.Timestamp(date).normalize()
            _require(timestamp <= CUTOFF, "dividend FX date exceeds cutoff")
            _require(timestamp >= pd.Timestamp(row.entry_date).normalize(), "dividend predates entry")
            valuation = row.exit_date if pd.notna(row.exit_date) else row.mtm_date
            _require(pd.notna(valuation), "dividend row lacks a valuation endpoint")
            _require(timestamp <= pd.Timestamp(valuation).normalize(), "dividend follows valuation")
    _dates(parquet, "opportunities")
    part_rows = 0
    part_periods: set[str] = set()
    for path in sorted((root / OPPORTUNITIES_PARTS).glob("period=*/part-*.csv.gz")):
        for chunk in pd.read_csv(
            path,
            usecols=["period"],
            chunksize=200_000,
            dtype_backend="pyarrow",
        ):
            part_rows += len(chunk)
            part_periods.update(chunk["period"].astype(str).unique())
    _require(part_rows == len(parquet), "partitioned opportunity count differs")
    _require(part_periods == set(PERIOD_NAMES), "partitioned opportunity periods differ")
    return parquet


def _verify_reconciliation(root: Path, opportunities: pd.DataFrame, contract: pd.DataFrame) -> None:
    reconciliation = pd.read_csv(root / RECONCILIATION_NAME, dtype={"combination_id": str})
    _columns(
        reconciliation,
        ("combination_id", "period", "opportunities", "completed", "censored", "failed_due_to_data", "reconciled"),
        "reconciliation",
    )
    expected_rows = EXPECTED_COMBINATION_COUNT * (len(PERIOD_NAMES) + 1)
    _require(len(reconciliation) == expected_rows, "reconciliation does not contain 290 rows per scope")
    for period in (*PERIOD_NAMES, "ALL"):
        scope = reconciliation.loc[reconciliation["period"].astype(str).eq(period)]
        _require(len(scope) == EXPECTED_COMBINATION_COUNT, f"reconciliation scope {period} is not 290")
        _require(set(scope["combination_id"]) == set(contract["combination_id"]), f"reconciliation scope {period} IDs differ")
    arithmetic = (
        reconciliation["opportunities"]
        == reconciliation["completed"]
        + reconciliation["censored"]
        + reconciliation["failed_due_to_data"]
    )
    _require(arithmetic.all(), "opportunity reconciliation arithmetic failed")
    _require(reconciliation["reconciled"].map(lambda value: _as_bool(value, "reconciled")).all(), "a reconciliation row failed")
    aggregate = reconciliation.loc[reconciliation["period"].eq("ALL")]
    _require(int(aggregate["opportunities"].sum()) == len(opportunities), "aggregate reconciliation count differs")
    for period in PERIOD_NAMES:
        expected = int(opportunities["period"].astype(str).eq(period).sum())
        actual = int(reconciliation.loc[reconciliation["period"].eq(period), "opportunities"].sum())
        _require(actual == expected, f"period {period} reconciliation count differs")


def _verify_frozen_inputs(root: Path, summary: Mapping[str, Any]) -> None:
    source_lock_path = root / SOURCE_LOCK_NAME
    exact_path = root / EXACT_STRATEGY_NAME
    fx_path = root / FROZEN_FX_RATES_NAME
    _require(_sha256(source_lock_path) == summary["source_lock_sha256"], "source lock hash differs")
    _require(_sha256(exact_path) == summary["exact_strategy_sha256"], "exact strategy hash differs")
    _require(_sha256(fx_path) == summary["frozen_fx_rates_sha256"], "frozen FX hash differs")
    source_lock = _json(source_lock_path)
    _require(source_lock.get("cutoff") == CUTOFF.date().isoformat(), "source lock cutoff differs")
    verified = source_lock.get("verified_artifacts")
    _require(isinstance(verified, list), "source lock lacks verified artifacts")
    roles = {str(row.get("role")): row for row in verified if isinstance(row, dict)}
    for role in ("prior_opportunity_audit", "frozen_exact_strategy"):
        _require(role in roles, f"source lock lacks {role}")
        _require(roles[role].get("expired") is False, f"source lock marks {role} expired")
        digest = str(roles[role].get("digest", ""))
        _require(digest.startswith("sha256:") and len(digest) == 71, f"invalid {role} digest")
    exact = _json(exact_path)
    _require(exact.get("candidate_id") == summary["exact_strategy_candidate_id"], "exact candidate differs")
    _require(isinstance(exact.get("strategy_spec"), dict), "exact strategy spec is absent")
    _require(
        exact.get("governance", {}).get("parameter_search_allowed") is False,
        "exact strategy permits parameter search",
    )
    fx = pd.read_csv(fx_path)
    _columns(fx, ("date", "currency", "usd_per_local"), "frozen FX rates")
    _require(not fx.duplicated(["currency", "date"]).any(), "frozen FX rates repeat observations")
    rates = pd.to_numeric(fx["usd_per_local"], errors="coerce")
    _require(rates.notna().all() and np.isfinite(rates).all() and rates.gt(0).all(), "invalid frozen FX rates")
    _dates(fx, FROZEN_FX_RATES_NAME)
    fx_audit = pd.read_csv(root / FX_AUDIT_NAME)
    non_identity = fx_audit["currency"].astype(str).ne("USD")
    _require(
        set(fx_audit.loc[non_identity, "source"].astype(str)) <= {"frozen_cli_fx_rates"},
        "FX audit contains a non-frozen source",
    )


def _verify_prior_financing(
    root: Path,
    opportunities: pd.DataFrame,
    summary: Mapping[str, Any],
) -> None:
    reconciliation = pd.read_csv(root / PRIOR_AUDIT_RECONCILIATION_NAME)
    _columns(
        reconciliation,
        (
            "exact_combination_id",
            "exact_entry_spec_id",
            "symbol",
            "selection_date",
            "entry_date",
            "prior_audit_opportunity_id",
            "financed_in_old_portfolio",
            "prior_not_financed_reason",
            "present_in_prior_audit",
            "informational_only",
            "reconciled",
        ),
        "prior financing reconciliation",
    )
    _require(not reconciliation.empty, "prior financing reconciliation is empty")
    _require(
        reconciliation["informational_only"].map(
            lambda value: _as_bool(value, "informational_only")
        ).all(),
        "prior financing reconciliation is not informational",
    )
    _require(
        reconciliation["reconciled"].map(lambda value: _as_bool(value, "reconciled")).all(),
        "a prior financing row is unreconciled",
    )
    _require(
        not reconciliation.duplicated(["symbol", "selection_date", "entry_date"]).any(),
        "prior financing reconciliation keys repeat",
    )
    present_in_prior = reconciliation["present_in_prior_audit"].map(
        lambda value: _as_bool(value, "present_in_prior_audit")
    )
    reconciliation_ids = (
        reconciliation["prior_audit_opportunity_id"]
        .fillna("")
        .astype(str)
        .str.strip()
    )
    _require(
        reconciliation_ids.loc[present_in_prior].ne("").all(),
        "prior financing rows marked present lack prior audit IDs",
    )
    _require(
        reconciliation_ids.loc[~present_in_prior].eq("").all(),
        "new corrected opportunities unexpectedly reference prior audit IDs",
    )
    _require(
        not reconciliation_ids.loc[present_in_prior].duplicated().any(),
        "prior financing reconciliation repeats prior audit IDs",
    )
    financed = reconciliation["financed_in_old_portfolio"].map(
        lambda value: _as_bool(value, "financed_in_old_portfolio")
    )
    _require(int(financed.sum()) == int(summary["financed_in_old_portfolio"]), "financed count differs")
    _require(int((~financed).sum()) == int(summary["not_financed_in_old_portfolio"]), "unfinanced count differs")
    matched = opportunities.loc[
        opportunities["financing_reconciliation_status"]
        .astype(str)
        .isin({"matched_prior_audit", "prior_audit_only_failed_due_to_data"})
    ]
    matched_ids = (
        matched["prior_audit_opportunity_id"].fillna("").astype(str).str.strip()
    )
    _require(
        set(matched_ids) == set(reconciliation_ids.loc[present_in_prior]),
        "ledger and prior financing IDs differ",
    )
    new_corrected = opportunities.loc[
        opportunities["financing_reconciliation_status"]
        .astype(str)
        .eq("new_corrected_opportunity_not_in_prior_audit")
    ]
    _require(
        new_corrected["prior_audit_opportunity_id"]
        .fillna("")
        .astype(str)
        .str.strip()
        .eq("")
        .all(),
        "new corrected ledger opportunities unexpectedly reference prior audit IDs",
    )


def _verify_semantics(root: Path, contract: pd.DataFrame) -> None:
    semantic = pd.read_csv(root / SEMANTIC_AUDIT_NAME, dtype={"combination_id": str})
    _require(len(semantic) == EXPECTED_COMBINATION_COUNT, "semantic audit is not 290 rows")
    _require(set(semantic["combination_id"]) == set(contract["combination_id"]), "semantic audit IDs differ")
    _require(semantic["semantic_audit_preserved"].map(lambda value: _as_bool(value, "semantic_audit_preserved")).all(), "semantic audit was not preserved")
    duplicates = pd.read_csv(root / FUNCTIONAL_DUPLICATES_NAME, dtype={"combination_id": str})
    _columns(
        duplicates,
        (
            "combination_id",
            "duplicate_type",
            "functionally_duplicated",
            "fingerprint",
            "canonical_combination_id",
            "global_functional_canonical_combination_id",
            "globally_functionally_unique",
        ),
        "functional duplicates",
    )
    _require(len(duplicates) == EXPECTED_COMBINATION_COUNT * 3, "functional duplicate audit is not 3 by 290")
    _require(set(duplicates["duplicate_type"]) == {"spec", "trades", "results"}, "functional duplicate types are incomplete")
    _require(set(duplicates["combination_id"]) == set(contract["combination_id"]), "functional duplicate IDs differ")
    _require(
        duplicates.groupby("combination_id")["global_functional_canonical_combination_id"]
        .nunique()
        .eq(1)
        .all(),
        "global functional canonical mapping differs by audit layer",
    )


def _verify_statistics(
    root: Path, contract: pd.DataFrame, audit_summary: Mapping[str, Any]
) -> None:
    frames: dict[str, pd.DataFrame] = {}
    for key, filename in STATISTIC_FILES.items():
        path = root / filename
        frame = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)
        frames[key] = frame
        _finite_frame(frame, filename)
        _dates(frame, filename)
        for column in frame.columns:
            lowered = column.lower()
            _require(
                "cagr" not in lowered and "sharpe" not in lowered,
                f"forbidden event-study metric in {filename}: {column}",
            )
    summary = frames["summary"]
    _columns(
        summary,
        (
            "opportunities", "opportunities_per_year", "complete_events",
            "censored_events", "censoring_rate", "mean_return", "median_return",
            "geometric_mean_return", "mean_log_return", "net_mean_return",
            "net_median_return", "win_rate", "profit_factor", "payoff_ratio",
            "target_hit_rate", "return_p10", "return_p25", "return_p75",
            "return_p90", "best_return", "worst_return", "return_std",
            "downside_deviation", "semivariance", "expected_shortfall_5",
            "expected_shortfall_10", "mean_loss", "median_loss", "worst_decile",
            "mae_mean_abs", "mae_median_abs", "mae_p90_abs", "mae_p95_abs",
            "intratrade_drawdown_mean", "intratrade_drawdown_median",
            "probability_loss_gt_10pct", "probability_loss_gt_20pct",
            "probability_loss_gt_30pct", "probability_loss_gt_40pct",
            "probability_loss_gt_50pct", "duration_mean", "duration_median",
            "calendar_days_mean", "calendar_days_median", "time_to_target_mean",
            "time_to_target_median", "duration_p90", "mean_return_per_session",
            "median_return_per_session", "mean_log_return_per_session",
            "return_per_capital_day", "mae_per_session", "months_with_opportunities",
            "unique_symbols", "unique_countries", "unique_markets",
            "positive_years_pct", "positive_entry_months_pct",
            "event_return_to_risk", "event_return_to_mae", "event_speed",
            "event_risk_adjusted_speed",
        ),
        "combination summary metrics",
    )
    _require(len(summary) == EXPECTED_COMBINATION_COUNT * 7, "summary is not 290 by seven costs")
    _require(set(summary["combination_id"].astype(str)) == set(contract["combination_id"]), "summary IDs differ")
    _require(set(summary["cost_bps_per_side"]) == {0, 5, 10, 25, 50, 100, 200}, "cost grid differs")
    _require(summary.groupby("combination_id")["cost_bps_per_side"].nunique().eq(7).all(), "a combination lacks cost levels")
    _require(
        summary["evidence_role"].astype(str).eq("all_periods_diagnostic").all(),
        "combined summary is being used as selection evidence",
    )
    period = frames["period"]
    _require(set(period["cut_value"].astype(str)) == set(PERIOD_NAMES), "period summary does not cover A, B and C")
    _require(period.groupby("cut_value")["combination_id"].nunique().eq(EXPECTED_COMBINATION_COUNT).all(), "period summary is not 290 per period")
    for key in ("year", "decade", "country", "market", "currency"):
        frame = frames[key]
        _require(frame["cut"].astype(str).eq(key).all(), f"{key} output contains another cut")
        _require(
            set(frame["combination_id"].astype(str)) == set(contract["combination_id"]),
            f"{key} output does not cover the 290 combinations",
        )
    year = frames["year"]
    _columns(year, ("mean_return", "mean_return_sign"), "yearly return sign")
    year_mean = pd.to_numeric(year["mean_return"], errors="coerce")
    expected_sign = np.select(
        (year_mean.gt(0), year_mean.lt(0), year_mean.eq(0)),
        ("positive", "negative", "zero"),
        default="not_estimable",
    )
    _require(
        year["mean_return_sign"].astype(str).to_numpy().tolist()
        == expected_sign.tolist(),
        "yearly mean-return sign is missing or inconsistent",
    )
    for key in (
        "year",
        "decade",
        "country",
        "market",
        "currency",
        "censoring",
        "survival",
        "leave_out",
        "concentration",
        "inference",
    ):
        _require(not frames[key].empty, f"{key} output is empty")
    leave_out = frames["leave_out"]
    required_opportunity_omissions = {"top5_opportunities", "top20_opportunities"}
    opportunity_omissions = leave_out.loc[
        leave_out["omission"].astype(str).isin(required_opportunity_omissions)
    ]
    _require(
        set(opportunity_omissions["omission"].astype(str))
        == required_opportunity_omissions,
        "leave-out audit lacks top-5 or top-20 opportunity stress",
    )
    _require(
        opportunity_omissions.groupby("combination_id")["omission"]
        .nunique()
        .eq(len(required_opportunity_omissions))
        .all()
        and opportunity_omissions["combination_id"].astype(str).nunique()
        == EXPECTED_COMBINATION_COUNT,
        "leave-out opportunity stresses do not cover every combination",
    )
    survival = frames["survival"]
    _columns(
        survival,
        ("event_duration", "requested_horizon", "kaplan_meier_survival"),
        "fixed-horizon survival",
    )
    requested = survival.loc[
        survival["requested_horizon"].map(
            lambda value: _as_bool(value, "requested_horizon")
        )
    ].copy()
    requested["event_duration"] = pd.to_numeric(
        requested["event_duration"], errors="raise"
    ).astype(int)
    _require(
        set(requested["event_duration"]) == set(SURVIVAL_REPORTING_HORIZONS),
        "survival output lacks one or more fixed reporting horizons",
    )
    _require(
        requested.groupby("combination_id")["event_duration"]
        .nunique()
        .eq(len(SURVIVAL_REPORTING_HORIZONS))
        .all()
        and requested["combination_id"].astype(str).nunique()
        == EXPECTED_COMBINATION_COUNT,
        "fixed survival horizons do not cover every combination",
    )
    _columns(
        frames["inference"],
        (
            "combination_id",
            "two_way_cluster_standard_error",
            "two_way_cluster_ci_low95",
            "two_way_cluster_ci_high95",
            "two_way_cluster_pvalue_two_sided",
            "two_way_cluster_dimensions",
            "sign_test_pvalue",
            "wilcoxon_pvalue",
        ),
        "robust inference diagnostics",
    )
    _require(
        frames["inference"]["two_way_cluster_dimensions"]
        .astype(str)
        .eq("symbol,entry_month")
        .all(),
        "two-way clustered inference does not use symbol and entry month",
    )
    ranked_ids = set(frames["balanced"]["combination_id"].astype(str))
    pareto_ids = set(frames["pareto"]["combination_id"].astype(str))
    ideal_ids = set(frames["ideal"]["combination_id"].astype(str))
    _require(bool(ranked_ids) and ranked_ids <= set(contract["combination_id"]), "balanced ranking IDs are invalid")
    _require(
        bool(pareto_ids) and ideal_ids == pareto_ids and pareto_ids <= ranked_ids,
        "ideal ranking must contain exactly the Pareto front",
    )
    _require(not frames["pareto"].empty, "Pareto front is empty")
    for key in ("ideal", "balanced", "pareto"):
        _require(
            frames[key]["evidence_role"]
            .astype(str)
            .eq("period_A_development_selection")
            .all(),
            f"{key} is not restricted to development selection",
        )
    objectives = set(frames["top_objectives"]["objective"].astype(str))
    from aurora.research.stock_protocol.event_study_290_statistics import (
        CONTRACT_CLASSIFICATIONS,
    )

    required_winners = {
        "01_highest_median_return",
        "02_highest_mean_return",
        "03_highest_event_speed",
        "04_lowest_mae",
        "05_lowest_expected_shortfall",
        "06_lowest_duration",
        "07_highest_profit_factor",
        "08_best_annual_stability",
        "09_pareto_closest_to_ideal",
        "10_highest_balanced_opportunity_score",
        "11_best_at_25_bps_per_side",
        "12_best_at_50_bps_per_side",
        "13_best_at_100_bps_per_side",
        "14_best_in_period_A",
        "14_best_in_period_B",
        "14_best_in_period_C",
        "15_most_stable_across_periods",
    }
    _require(objectives == required_winners, "top objective winners differ from part 15")
    classifications = frames["classifications"]
    _columns(
        classifications,
        (
            "combination_id", "classification", "selection_eligible",
            "ranking_metrics_complete", "bootstrap_median_return_ci_low95",
            "bootstrap_median_return_ci_width95", "complete_events",
            "minimum_period_complete_events", "functionally_duplicated",
            "evidence_role", "classification_evidence_role",
            "robust_gate_all_passed", "robust_gate_fail_reasons_json",
            "robust_gate_semantic_unique_sample",
            "robust_gate_positive_net_median",
            "robust_gate_grouped_global_lower_positive",
            "robust_gate_clear_majority_positive_years",
            "robust_gate_not_single_year_dependent",
            "robust_gate_not_single_country_dependent",
            "robust_gate_pareto_front",
            "robust_gate_all_three_periods_positive",
            "robust_gate_multiple_testing",
            "robust_gate_low_censoring",
        ),
        "classifications",
    )
    _require(len(classifications) == EXPECTED_COMBINATION_COUNT, "classifications are not 290 rows")
    _require(set(classifications["combination_id"].astype(str)) == set(contract["combination_id"]), "classification IDs differ")
    _require(set(classifications["classification"].astype(str)) <= set(CONTRACT_CLASSIFICATIONS), "unknown classification")
    robust_rows = classifications["classification"].astype(str).eq("robust_leader")
    gate_passed = classifications["robust_gate_all_passed"].map(
        lambda value: _as_bool(value, "robust_gate_all_passed")
    )
    _require(
        gate_passed.loc[robust_rows].all(),
        "a robust leader fails at least one declared gate",
    )
    _require(
        (~gate_passed.loc[~robust_rows]).all(),
        "a combination passes all robust gates without robust_leader classification",
    )
    observed_classifications = {
        str(key): int(value)
        for key, value in classifications["classification"].value_counts().items()
    }
    _require(observed_classifications == audit_summary["classification_counts"], "classification counts differ")
    multiple = frames["multiple_testing"]
    _columns(
        multiple,
        (
            "bh_declared_290_pvalue",
            "holm_declared_290_pvalue",
            "bh_functionally_unique_pvalue",
            "holm_functionally_unique_pvalue",
            "declared_correction_status",
            "unique_correction_status",
            "global_functional_canonical_combination_id",
            "globally_functionally_unique",
        ),
        "multiple testing",
    )
    _require(len(multiple) == EXPECTED_COMBINATION_COUNT, "multiple-testing output is not 290")
    _require(multiple["combination_id"].nunique() == EXPECTED_COMBINATION_COUNT, "multiple-testing IDs repeat")
    _require(
        multiple["evidence_role"]
        .astype(str)
        .eq("period_A_development_selection")
        .all(),
        "multiple testing used validation for selection",
    )
    _require(multiple["declared_tests"].eq(EXPECTED_COMBINATION_COUNT).all(), "multiple-testing declared_tests is not 290")
    eligible_expected = int(contract["corrected_track_applicability"].ne("not_applicable").sum())
    _require(multiple["eligible_tests"].eq(eligible_expected).all(), "multiple-testing eligible_tests differs from semantics")
    unique_counts = set(pd.to_numeric(multiple["functionally_unique_tests"], errors="raise"))
    _require(len(unique_counts) == 1, "functionally_unique_tests is inconsistent")
    functionally_unique = int(next(iter(unique_counts)))
    duplicate_audit = pd.read_csv(root / FUNCTIONAL_DUPLICATES_NAME)
    audit_unique = duplicate_audit["global_functional_canonical_combination_id"].nunique()
    _require(functionally_unique == audit_unique, "functionally_unique_tests is not derived from global audit")
    _require(2 <= functionally_unique <= EXPECTED_COMBINATION_COUNT, "functionally_unique_tests is invalid")
    _require(int(audit_summary["declared_tests"]) == EXPECTED_COMBINATION_COUNT, "audit and testing declared counts differ")
    _require(int(audit_summary["eligible_tests"]) == eligible_expected, "audit and testing eligible counts differ")
    _require(int(audit_summary["functionally_unique_tests"]) == functionally_unique, "audit and testing unique counts differ")
    expected_unsupported = contract.set_index("combination_id")["corrected_track_applicability"].eq("not_applicable")
    observed_unsupported = multiple.set_index("combination_id")["analysis_status"].eq("unsupported_semantics")
    expected_unsupported = expected_unsupported.reindex(observed_unsupported.index)
    _require(
        np.array_equal(observed_unsupported.to_numpy(), expected_unsupported.to_numpy()),
        "unsupported semantic rows differ from contract",
    )
    allowed_statuses = {
        "unsupported_semantics", "unsupported_insufficient_completed_events",
        "supported_cluster_only", "supported_functional_duplicate", "supported",
    }
    _require(set(multiple["analysis_status"].astype(str)) <= allowed_statuses, "multiple-testing status is invalid")
    included = multiple["pbo_included"].map(
        lambda value: _as_bool(value, "pbo_included")
    )
    _require(included.any(), "multiple-testing has no PBO-included rows")
    supported = multiple["declared_correction_status"].astype(str).eq(
        "estimable_in_declared_290_family"
    )
    _require(supported.any(), "multiple-testing has no estimable declared rows")
    for column in (
        "cluster_pvalue_one_sided",
        "benjamini_hochberg_pvalue", "holm_pvalue",
        "bh_declared_290_pvalue", "holm_declared_290_pvalue",
    ):
        values = pd.to_numeric(multiple.loc[supported, column], errors="coerce")
        _require(values.notna().all() and np.isfinite(values).all(), f"supported {column} is non-finite")
    unique_supported = multiple["unique_correction_status"].astype(str).str.startswith("estimable_")
    for column in ("bh_functionally_unique_pvalue", "holm_functionally_unique_pvalue"):
        values = pd.to_numeric(multiple.loc[unique_supported, column], errors="coerce")
        _require(values.notna().all() and np.isfinite(values).all(), f"unique {column} is non-finite")
    _require(
        multiple.loc[~supported, "bh_declared_290_pvalue"].astype(str).eq("not_estimable").all(),
        "declared non-estimable rows are not explicit",
    )
    pbo = frames["pbo"]
    _require(not pbo.empty, "CSCV/PBO output is empty")
    _require(pd.to_numeric(pbo["pbo"], errors="coerce").between(0.0, 1.0).all(), "PBO is outside [0, 1]")
    _require(pbo["declared_tests"].eq(EXPECTED_COMBINATION_COUNT).all(), "PBO declared_tests is not 290")
    _require(pbo["eligible_tests"].eq(eligible_expected).all(), "PBO eligible_tests differs")
    _require(pbo["functionally_unique_tests"].eq(functionally_unique).all(), "PBO functionally_unique_tests differs")
    _require((pbo["family_functionally_unique_tests"] >= 2).all(), "a PBO family has fewer than two unique rules")
    _require((pbo["matrix_rows"] >= 8).all(), "a PBO family has fewer than eight shared events")
    _require(not frames["cluster_summary"].empty and not frames["cluster_samples"].empty, "cluster outputs are empty")
    paired_exit = frames["paired_exit"]
    paired_entry = frames["paired_entry"]
    paired_columns = (
        "baseline", "challenger", "metric", "metric_source", "causal_keys",
        "pairs", "analysis_status", "mean_delta", "median_delta", "ci_low95",
        "ci_high95", "positive_pairs", "negative_pairs", "ties",
        "sign_test_pvalue", "primary_inference_method", "evidence_role",
    )
    _columns(paired_exit, ("entry_spec_id", *paired_columns), "paired exits")
    _columns(paired_entry, ("exit_spec_id", *paired_columns), "paired entries")
    expected_exit_rows = EXPECTED_ENTRY_SPEC_COUNT * math.comb(EXPECTED_EXIT_SPEC_COUNT, 2) * 5
    expected_entry_rows = EXPECTED_EXIT_SPEC_COUNT * math.comb(EXPECTED_ENTRY_SPEC_COUNT, 2) * 7
    _require(len(paired_exit) == expected_exit_rows, "paired exits do not contain every pair and metric")
    _require(len(paired_entry) == expected_entry_rows, "paired entries do not contain every pair and metric")
    _require(set(paired_exit["metric"]) == {"return", "loss", "mae", "duration", "return_per_session"}, "paired exit metrics differ")
    _require(set(paired_entry["metric"]) == {"trigger_probability", "entry_price", "entry_delay_sessions", "return", "mae", "duration", "coverage"}, "paired entry metrics differ")
    for key, frame, fixed in (
        ("paired_exit", paired_exit, "entry_spec_id"),
        ("paired_entry", paired_entry, "exit_spec_id"),
    ):
        _require(
            not frame.duplicated([fixed, "baseline", "challenger", "metric"]).any(),
            f"{key} repeats a pair metric",
        )
        estimable = frame["analysis_status"].astype(str).eq("estimable")
        _require((frame.loc[estimable, "pairs"] > 0).all(), f"{key} estimable row has no pairs")
        _require(
            frame.loc[~estimable, "analysis_status"].astype(str).str.startswith("not_estimable").all(),
            f"{key} has an unknown classification",
        )


def _verify_report(root: Path) -> None:
    report = (root / FINAL_REPORT_NAME).read_text(encoding="utf-8")
    numbers = [int(value) for value in re.findall(r"(?m)^(\d+)\. \*\*", report)]
    _require(numbers == list(range(1, 26)), "final report does not answer exactly 25 numbered questions")
    ids = re.findall(r"(?m)^\d+\. \*\*\[(Q\d{2})\]", report)
    _require(tuple(ids) == REPORT_QUESTION_IDS, "final report question IDs differ from Q01-Q25")
    _require(report.count("Resultado:") == 25, "final report lacks one result per question")
    _require("## Hechos" in report, "final report lacks facts section")
    _require("## Inferencias" in report, "final report lacks inferences section")
    _require("## Limitaciones" in report, "final report lacks limitations section")
    lowered = report.lower()
    for forbidden in FORBIDDEN_EVENT_METRICS:
        _require(forbidden not in lowered, f"final report contains forbidden metric {forbidden}")
    required_content = (
        "¿Cuántas reglas de las 290 eran realmente únicas?",
        "¿Cuántas eran duplicadas?",
        "¿Cuántas eran semánticamente inválidas?",
        "¿Cuántas oportunidades completas tuvo cada combinación?",
        "¿Qué entrada activó más oportunidades?",
        "¿Qué entrada obtuvo mejor retorno condicionado?",
        "¿Qué entrada ofreció mejor equilibrio entre retorno y cobertura?",
        "¿Qué salida produjo mayor retorno?",
        "¿Qué salida redujo más el riesgo?",
        "¿Qué salida fue más rápida?",
        "¿Qué salida mejoró más el retorno por sesión?",
        "¿Qué combinación obtuvo el mayor retorno mediano?",
        "¿Cuál tuvo menor MAE?",
        "¿Cuál tuvo menor expected shortfall?",
        "¿Cuál tuvo mayor event speed?",
        "¿Cuál fue la más estable entre periodos?",
        "¿Cuál fue la mejor en la frontera de Pareto?",
        "¿Cuál quedó más cerca del punto ideal?",
        "¿Cuál obtuvo mayor Balanced Opportunity Score?",
        "¿Cuál sobrevivió mejor a costes?",
        "¿Cuáles dependieron excesivamente de un año?",
        "¿Cuáles dependieron de pocos símbolos?",
        "¿Cuáles superaron las correcciones por múltiples pruebas?",
        "¿Cuál sería la mejor candidata para congelar prospectivamente?",
        "¿Qué limitaciones impiden considerarla validada?",
        "ninguna oportunidad fue excluida por capital",
    )
    for text in required_content:
        _require(text.lower() in lowered, f"final report lacks required answer content: {text}")


def verify(root: Path) -> None:
    root = Path(root)
    _require(root.is_dir(), "final artifact root does not exist")
    _verify_required_files(root)
    summary = _verify_summary(root)
    contract = _verify_contract(root)
    _require(
        _sha256(root / COMBINATION_MANIFEST_NAME) == summary["manifest_sha256"],
        "contract manifest hash differs from audit summary",
    )
    for field in ("dataset_hash", "policy_hash", "source_snapshot_sha256"):
        _require(
            contract[field].astype(str).eq(str(summary[field])).all(),
            f"contract {field} differs from audit summary",
        )
    _verify_historical(root, contract)
    opportunities = _verify_opportunities(root, summary, contract)
    coverage = pd.read_parquet(root / COVERAGE_PARQUET)
    coverage_csv = pd.read_csv(root / COVERAGE_CSV_GZIP, low_memory=False)
    _columns(coverage, COVERAGE_REQUIRED_COLUMNS, "entry coverage")
    _require(set(coverage.columns) == set(coverage_csv.columns), "coverage schemas differ")
    _require(len(coverage) == len(coverage_csv), "coverage parquet and gzip counts differ")
    _require(
        set(coverage["entry_spec_id"].astype(str)) == set(contract["entry_spec_id"]),
        "coverage does not contain all ten entries",
    )
    _require(set(coverage["period"].astype(str)) == set(PERIOD_NAMES), "coverage lacks a period")
    _require(
        not coverage.duplicated(["entry_spec_id", "symbol", "selection_date", "period"]).any(),
        "coverage causal keys repeat",
    )
    _require(
        set(coverage["coverage_status"].astype(str))
        <= {"entry_triggered", "entry_not_triggered"},
        "coverage status is invalid",
    )
    _dates(coverage, "entry coverage")
    _verify_reconciliation(root, opportunities, contract)
    _verify_frozen_inputs(root, summary)
    _verify_prior_financing(root, opportunities, summary)
    _verify_semantics(root, contract)
    _verify_statistics(root, contract, summary)
    _verify_report(root)
    _verify_manifest(root)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    verify(parser.parse_args().root)
    print("verified stock protocol 290-10-29 event-study artifact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
