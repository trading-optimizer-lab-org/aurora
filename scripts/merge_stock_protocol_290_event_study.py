"""Merge the immutable 10 x 29 stock-protocol opportunity event study."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import math
import os
from itertools import combinations
from pathlib import Path
import shutil
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from aurora.core.execution_policy import (
    require_github_actions_or_explicit_local_permission,
)
from aurora.research.stock_protocol.event_study_290_manifest import (
    COMBINATION_MANIFEST_NAME,
    ENTRY_SPECS_NAME,
    EXIT_SPECS_NAME,
    EXPECTED_COMBINATION_COUNT,
    EXPECTED_ENTRY_SPEC_COUNT,
    EXPECTED_EXIT_SPEC_COUNT,
)
from aurora.research.stock_protocol.event_study_290_statistics import (
    COSTS_BPS_PER_SIDE,
    REQUIRED_OBJECTIVES,
    benjamini_hochberg,
    censoring_audit,
    cluster_bootstrap_confidence_intervals,
    cluster_mean_significance_tests,
    concentration_statistics,
    cscv_pbo,
    deflated_event_statistic,
    detect_functional_duplicates,
    holm_adjust,
    leave_one_out_audit,
    metric_cuts,
    metrics_by_combination,
    objective_winners,
    rank_combinations,
    survival_incidence_table,
    westfall_young_max_t,
    white_spa_equivalent,
)
from aurora.research.stock_protocol.opportunity_audit import causal_fx_merge
from scripts.run_stock_protocol_290_corrected_shard import (
    AUDIT_NAME as CORRECTED_AUDIT_NAME,
    COVERAGE_STEM,
    FX_COLUMNS,
    LEDGER_STATUSES,
    OPPORTUNITIES_STEM,
    PERIODS,
    RECONCILIATION_STEM,
)
from scripts.run_stock_protocol_290_historical_shard import (
    AUDIT_NAME as HISTORICAL_AUDIT_NAME,
    METRIC_TOLERANCES,
    OUTPUT_NAME as HISTORICAL_RESULTS_NAME,
)


CUTOFF = pd.Timestamp("2026-07-17")
EXPECTED_HISTORICAL_SHARDS = 10
EXPECTED_CORRECTED_SHARDS = 30
PERIOD_NAMES = tuple(PERIODS)

OPPORTUNITIES_PARQUET = "all_290_combination_opportunities.parquet"
OPPORTUNITIES_CSV_GZIP = "all_290_combination_opportunities.csv.gz"
OPPORTUNITIES_PARTS = "all_290_combination_opportunities_csv_gzip"
COVERAGE_PARQUET = "all_290_entry_coverage.parquet"
COVERAGE_CSV_GZIP = "all_290_entry_coverage.csv.gz"
RECONCILIATION_NAME = "opportunity_reconciliation.csv"
SEMANTIC_AUDIT_NAME = "combination_semantic_audit.csv"
FUNCTIONAL_DUPLICATES_NAME = "functional_duplicate_groups.csv"
FX_AUDIT_NAME = "historical_290_fx_audit.csv"
FROZEN_FX_RATES_NAME = "frozen_fx_rates.csv"
SOURCE_LOCK_NAME = "stock-protocol-290-source-lock.json"
EXACT_STRATEGY_NAME = "frozen_oos_strategy_manifest.json"
PRIOR_AUDIT_RECONCILIATION_NAME = "prior_audit_financing_reconciliation.csv"

STATISTIC_FILES: dict[str, str] = {
    "summary": "combination_summary_results.csv",
    "period": "combination_period_results.csv",
    "year": "combination_yearly_results.csv",
    "decade": "combination_decade_results.csv",
    "country": "combination_country_results.csv",
    "market": "combination_market_results.csv",
    "currency": "combination_currency_results.csv",
    "paired_entry": "paired_entry_comparisons.csv",
    "paired_exit": "paired_exit_comparisons.csv",
    "cluster_summary": "clustered_bootstrap_results.csv",
    "cluster_samples": "clustered_bootstrap_samples.parquet",
    "multiple_testing": "multiple_testing_results.csv",
    "pbo": "cscv_pbo_results.csv",
    "leave_out": "leave_one_group_out_results.csv",
    "concentration": "return_concentration_results.csv",
    "pareto": "opportunity_pareto_frontier.csv",
    "ideal": "opportunity_ideal_point_ranking.csv",
    "balanced": "balanced_opportunity_ranking.csv",
    "top_objectives": "top_combinations_by_objective.csv",
    "classifications": "combination_classifications.csv",
    "censoring": "censoring_audit.csv",
    "survival": "survival_analysis_by_combination.csv",
}

AUDIT_SUMMARY_NAME = "audit_summary.json"
FINAL_REPORT_NAME = "final_290_opportunity_event_study.md"
FINAL_MANIFEST_NAME = "final_artifact_manifest.json"

REQUIRED_TOP_LEVEL_FILES = {
    OPPORTUNITIES_PARQUET,
    OPPORTUNITIES_CSV_GZIP,
    COVERAGE_PARQUET,
    COVERAGE_CSV_GZIP,
    RECONCILIATION_NAME,
    SEMANTIC_AUDIT_NAME,
    FUNCTIONAL_DUPLICATES_NAME,
    FX_AUDIT_NAME,
    FROZEN_FX_RATES_NAME,
    SOURCE_LOCK_NAME,
    EXACT_STRATEGY_NAME,
    PRIOR_AUDIT_RECONCILIATION_NAME,
    HISTORICAL_RESULTS_NAME,
    HISTORICAL_AUDIT_NAME,
    COMBINATION_MANIFEST_NAME,
    ENTRY_SPECS_NAME,
    EXIT_SPECS_NAME,
    AUDIT_SUMMARY_NAME,
    FINAL_REPORT_NAME,
    FINAL_MANIFEST_NAME,
    *STATISTIC_FILES.values(),
}

STATISTICAL_LEDGER_COLUMNS = (
    "opportunity_id",
    "combination_id",
    "entry_spec_id",
    "exit_spec_id",
    "symbol",
    "period",
    "status",
    "censor_reason",
    "selection_date",
    "signal_date",
    "entry_signal_date",
    "entry_date",
    "entry_price",
    "exit_date",
    "exit_reason",
    "gross_return",
    "maximum_adverse_excursion",
    "holding_sessions",
    "stop_hit",
    "target_hit",
    "time_exit",
    "max_holding_reached",
    "country",
    "market",
    "currency",
    "semantic_applicability",
    "ranking_eligible",
)

STATISTICAL_COVERAGE_COLUMNS = (
    "entry_spec_id",
    "symbol",
    "selection_date",
    "period",
    "triggered",
    "entry_in_period",
    "wait_sessions",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _resident_memory_kib() -> int | None:
    """Return current RSS on Linux without adding a runtime dependency."""

    status = Path("/proc/self/status")
    if not status.is_file():
        return None
    for line in status.read_text(encoding="utf-8").splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1])
    return None


def _read_parquet_compact(path: Path) -> pd.DataFrame:
    """Keep large shard strings and timestamps Arrow-backed during the merge."""

    return pd.read_parquet(path, dtype_backend="pyarrow")


def _append_parquet_frame(
    writer: pq.ParquetWriter | None,
    schema: pa.Schema | None,
    path: Path,
    frame: pd.DataFrame,
) -> tuple[pq.ParquetWriter, pa.Schema]:
    table = pa.Table.from_pandas(frame, preserve_index=False)
    if writer is None:
        schema = table.schema
        writer = pq.ParquetWriter(path, schema, compression="zstd")
    assert schema is not None
    extras = set(table.column_names) - set(schema.names)
    if extras:
        raise ValueError(f"streamed parquet introduced columns: {sorted(extras)}")
    for field in schema:
        if field.name not in table.column_names:
            table = table.append_column(
                field.name, pa.nulls(len(table), type=field.type)
            )
    table = table.select(schema.names)
    if table.schema != schema:
        table = table.cast(schema, safe=False)
    writer.write_table(table)
    return writer, schema


def _parquet_to_gzip_csv(
    parquet_path: Path,
    csv_path: Path,
    *,
    period: str | None = None,
) -> int:
    rows = 0
    header = True
    with csv_path.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as compressed:
            with io.TextIOWrapper(compressed, encoding="utf-8", newline="") as text:
                for batch in pq.ParquetFile(parquet_path).iter_batches(batch_size=50_000):
                    frame = batch.to_pandas(types_mapper=pd.ArrowDtype)
                    if period is not None:
                        frame = frame.loc[frame["period"].astype(str).eq(period)]
                    if frame.empty:
                        continue
                    frame.to_csv(text, index=False, header=header)
                    header = False
                    rows += len(frame)
    return rows


def _json(path: Path, payload: Mapping[str, object]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True, default=_json_default)
        + "\n",
        encoding="utf-8",
    )


def _json_default(value: object) -> object:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, (pd.Timestamp, pd.Period)):
        return str(value)
    raise TypeError(f"cannot serialize {type(value).__name__}")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _find_unique(root: Path, name: str) -> Path:
    matches = sorted(Path(root).rglob(name))
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {name} below {root}; found {len(matches)}")
    return matches[0]


def _verify_manifest_member(root: Path, relative_name: str) -> Path:
    manifest_path = _find_unique(root, FINAL_MANIFEST_NAME)
    manifest = _read_json(manifest_path)
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise ValueError(f"{manifest_path} has no file hash mapping")
    matches = [
        (name, metadata)
        for name, metadata in files.items()
        if Path(str(name)).name == relative_name
    ]
    if len(matches) != 1 or not isinstance(matches[0][1], dict):
        raise ValueError(f"{manifest_path} does not lock exactly one {relative_name}")
    name, metadata = matches[0]
    path = manifest_path.parent / str(name)
    if not path.is_file():
        raise FileNotFoundError(path)
    _assert_sha256(path, metadata.get("sha256"), f"locked input {relative_name}")
    if int(metadata.get("bytes", -1)) != path.stat().st_size:
        raise ValueError(f"locked input {relative_name} byte count mismatch")
    return path


def _load_provenance_inputs(
    *,
    prior_audit_root: Path,
    exact_strategy_root: Path,
    source_lock_path: Path,
) -> tuple[dict[str, Any], pd.DataFrame, dict[str, Any]]:
    source_lock = _read_json(source_lock_path)
    if str(source_lock.get("cutoff")) != CUTOFF.date().isoformat():
        raise ValueError("source lock cutoff mismatch")
    if _as_bool(source_lock.get("new_oos_claimed", True)):
        raise ValueError("source lock claims new OOS")
    if _as_bool(source_lock.get("optimization_performed_on_opened_data", True)):
        raise ValueError("source lock permits optimization on opened data")
    verified = source_lock.get("verified_artifacts")
    if not isinstance(verified, list):
        raise ValueError("source lock has no verified_artifacts list")
    by_role = {str(row.get("role")): row for row in verified if isinstance(row, dict)}
    for role in ("prior_opportunity_audit", "frozen_exact_strategy"):
        row = by_role.get(role)
        if row is None or row.get("expired") is not False:
            raise ValueError(f"source lock does not preserve {role}")
        digest = str(row.get("digest", "")).lower()
        if not digest.startswith("sha256:") or len(digest) != 71:
            raise ValueError(f"source lock has invalid digest for {role}")

    exact_path = _verify_manifest_member(exact_strategy_root, EXACT_STRATEGY_NAME)
    exact = _read_json(exact_path)
    strategy_spec = exact.get("strategy_spec")
    candidate_id = str(exact.get("candidate_id", ""))
    if not candidate_id or not isinstance(strategy_spec, dict):
        raise ValueError("exact strategy artifact lacks candidate_id or strategy_spec")
    if str(exact.get("periods", {}).get("locked_end")) != CUTOFF.date().isoformat():
        raise ValueError("exact strategy artifact cutoff mismatch")
    if exact.get("governance", {}).get("parameter_search_allowed") is not False:
        raise ValueError("exact strategy artifact permits parameter search")

    prior_exact_path = _verify_manifest_member(prior_audit_root, "frozen_strategy_exact.json")
    prior_exact = _read_json(prior_exact_path)
    if str(prior_exact.get("candidate_id", "")) != candidate_id:
        raise ValueError("prior audit and exact artifact candidate IDs differ")
    if prior_exact.get("strategy_spec") != strategy_spec:
        raise ValueError("prior audit and exact artifact strategy specs differ")
    prior_opportunities_path = _verify_manifest_member(
        prior_audit_root, "all_individual_opportunities.csv"
    )
    prior_opportunities = pd.read_csv(prior_opportunities_path, low_memory=False)
    _assert_columns(
        prior_opportunities,
        (
            "opportunity_id",
            "symbol",
            "selection_date",
            "entry_date",
            "originally_financed",
            "not_financed_reason",
        ),
        "prior opportunity audit",
    )
    return exact, prior_opportunities, source_lock


def reconcile_prior_financing(
    opportunities: pd.DataFrame,
    manifest: pd.DataFrame,
    exact_strategy: Mapping[str, Any],
    prior_opportunities: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Attach old portfolio financing as provenance only, never as a filter."""

    candidate_id = str(exact_strategy["candidate_id"])
    exact_rows = manifest.loc[manifest["combination_id"].astype(str).eq(candidate_id)]
    if len(exact_rows) != 1:
        raise ValueError("exact frozen strategy is not one of the declared 290 combinations")
    exact_entry_spec_id = str(exact_rows.iloc[0]["entry_spec_id"])
    keys = ["symbol", "selection_date", "entry_date"]
    prior = prior_opportunities.copy()
    for column in ("selection_date", "entry_date"):
        prior[column] = pd.to_datetime(prior[column], errors="raise").dt.normalize()
    if prior.duplicated(keys).any():
        raise ValueError("prior audit financing keys are not unique")
    prior["originally_financed"] = prior["originally_financed"].map(_as_bool)
    lookup = prior[
        [
            *keys,
            "opportunity_id",
            "originally_financed",
            "not_financed_reason",
        ]
    ].rename(
        columns={
            "opportunity_id": "prior_audit_opportunity_id",
            "originally_financed": "_prior_financed",
            "not_financed_reason": "prior_not_financed_reason",
        }
    )
    result = opportunities.copy()
    for column in ("selection_date", "entry_date"):
        result[column] = pd.to_datetime(result[column], errors="coerce").dt.normalize()
    exact_entry = result["entry_spec_id"].astype(str).eq(exact_entry_spec_id)
    exact_input = result.loc[exact_entry].copy()
    exact_input["_result_index"] = exact_input.index
    matched = exact_input.merge(
        lookup, on=keys, how="left", validate="many_to_one"
    )
    if matched["prior_audit_opportunity_id"].isna().any():
        raise ValueError("exact strategy opportunities do not fully reconcile to prior audit")
    result["financed_in_old_portfolio"] = False
    result["financing_information_only"] = True
    result["financing_reconciliation_status"] = "not_applicable_different_entry_spec"
    result["prior_audit_opportunity_id"] = ""
    result["prior_not_financed_reason"] = ""
    matched_index = matched["_result_index"].to_numpy(dtype=int)
    result.loc[matched_index, "financed_in_old_portfolio"] = matched[
        "_prior_financed"
    ].to_numpy(dtype=bool)
    result.loc[matched_index, "financing_reconciliation_status"] = "matched_prior_audit"
    result.loc[matched_index, "prior_audit_opportunity_id"] = matched[
        "prior_audit_opportunity_id"
    ].astype(str).to_numpy()
    result.loc[matched_index, "prior_not_financed_reason"] = matched[
        "prior_not_financed_reason"
    ].fillna("").astype(str).to_numpy()
    reconciliation = matched[
        [
            *keys,
            "prior_audit_opportunity_id",
            "_prior_financed",
            "prior_not_financed_reason",
        ]
    ].drop_duplicates(keys, keep="first")
    reconciliation = reconciliation.rename(
        columns={"_prior_financed": "financed_in_old_portfolio"}
    )
    reconciliation.insert(0, "exact_combination_id", candidate_id)
    reconciliation.insert(1, "exact_entry_spec_id", exact_entry_spec_id)
    reconciliation["informational_only"] = True
    reconciliation["reconciled"] = True
    return result, reconciliation.reset_index(drop=True)


def _as_bool(value: object) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    raise ValueError(f"not a boolean value: {value!r}")


def _assert_sha256(path: Path, expected: object, label: str) -> None:
    actual = _sha256(path)
    if actual != str(expected).strip().lower():
        raise ValueError(f"{label} sha256 mismatch")


def _assert_columns(frame: pd.DataFrame, columns: Iterable[str], label: str) -> None:
    missing = set(columns) - set(frame.columns)
    if missing:
        raise ValueError(f"{label} missing columns: {sorted(missing)}")


def _assert_dates_at_cutoff(frame: pd.DataFrame, label: str) -> None:
    for column in (
        "selection_date",
        "signal_date",
        "entry_signal_date",
        "entry_date",
        "exit_date",
        "mtm_date",
        "fx_entry_date",
        "fx_exit_date",
        "date",
    ):
        if column not in frame:
            continue
        values = pd.to_datetime(frame[column], errors="coerce").dropna()
        if not values.empty and values.max().normalize() > CUTOFF:
            raise ValueError(f"{label}.{column} exceeds cutoff {CUTOFF.date()}")


def _discover_shards(
    root: Path,
    audit_name: str,
    expected: int,
) -> list[tuple[Path, dict[str, Any]]]:
    paths = sorted(Path(root).rglob(audit_name))
    if len(paths) != expected:
        raise ValueError(
            f"expected exactly {expected} {audit_name} shards; found {len(paths)}"
        )
    return [(path.parent, _read_json(path)) for path in paths]


def _contract(contract_root: Path) -> tuple[pd.DataFrame, list[dict[str, Any]], list[dict[str, Any]]]:
    manifest_path = Path(contract_root) / COMBINATION_MANIFEST_NAME
    entries_path = Path(contract_root) / ENTRY_SPECS_NAME
    exits_path = Path(contract_root) / EXIT_SPECS_NAME
    for path in (manifest_path, entries_path, exits_path):
        if not path.is_file():
            raise FileNotFoundError(path)
    manifest = pd.read_csv(manifest_path, dtype=str, keep_default_na=False)
    _assert_columns(
        manifest,
        (
            "combination_id",
            "entry_spec_id",
            "exit_spec_id",
            "entry_spec_json",
            "exit_spec_json",
            "corrected_track_applicability",
            "corrected_track_reason",
        ),
        "290 manifest",
    )
    if len(manifest) != EXPECTED_COMBINATION_COUNT:
        raise ValueError("manifest must contain exactly 290 rows")
    if manifest["combination_id"].nunique() != EXPECTED_COMBINATION_COUNT:
        raise ValueError("manifest combination IDs are not unique")
    if manifest["entry_spec_id"].nunique() != EXPECTED_ENTRY_SPEC_COUNT:
        raise ValueError("manifest must contain exactly 10 entry specs")
    if manifest["exit_spec_id"].nunique() != EXPECTED_EXIT_SPEC_COUNT:
        raise ValueError("manifest must contain exactly 29 exit specs")
    pairs = manifest[["entry_spec_id", "exit_spec_id"]]
    if pairs.duplicated().any() or len(pairs) != EXPECTED_ENTRY_SPEC_COUNT * EXPECTED_EXIT_SPEC_COUNT:
        raise ValueError("manifest is not the exact 10 by 29 Cartesian contract")
    entries = json.loads(entries_path.read_text(encoding="utf-8"))
    exits = json.loads(exits_path.read_text(encoding="utf-8"))
    if not isinstance(entries, list) or len(entries) != EXPECTED_ENTRY_SPEC_COUNT:
        raise ValueError("original entry spec JSON must contain exactly 10 specs")
    if not isinstance(exits, list) or len(exits) != EXPECTED_EXIT_SPEC_COUNT:
        raise ValueError("original exit spec JSON must contain exactly 29 specs")
    return manifest, entries, exits


def merge_historical_shards(
    shards_root: Path,
    manifest: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    shards = _discover_shards(
        shards_root, HISTORICAL_AUDIT_NAME, EXPECTED_HISTORICAL_SHARDS
    )
    coordinates: set[int] = set()
    frames: list[pd.DataFrame] = []
    audits: list[dict[str, Any]] = []
    manifest_hashes: set[str] = set()
    for root, audit in shards:
        index = int(audit.get("entry_index", -1))
        if index not in range(EXPECTED_ENTRY_SPEC_COUNT) or index in coordinates:
            raise ValueError(f"invalid or duplicate historical entry_index {index}")
        coordinates.add(index)
        result_path = root / HISTORICAL_RESULTS_NAME
        if not result_path.is_file():
            raise FileNotFoundError(result_path)
        _assert_sha256(result_path, audit.get("result_sha256"), str(result_path))
        if int(audit.get("combination_count", -1)) != EXPECTED_EXIT_SPEC_COUNT:
            raise ValueError(f"historical shard {index} is not a 29-exit shard")
        if _as_bool(audit.get("locked_opened", True)):
            raise ValueError("historical replication opened locked data")
        if _as_bool(audit.get("new_oos_claimed", True)):
            raise ValueError("historical replication claimed new OOS")
        if _as_bool(audit.get("optimization_performed_on_opened_data", True)):
            raise ValueError("historical replication optimized opened data")
        tolerances = audit.get("metric_tolerances")
        if tolerances != METRIC_TOLERANCES:
            raise ValueError(f"historical shard {index} changed frozen tolerances")
        frame = pd.read_csv(result_path, dtype={"combination_id": str})
        if len(frame) != EXPECTED_EXIT_SPEC_COUNT:
            raise ValueError(f"historical shard {index} does not contain 29 rows")
        frames.append(frame)
        manifest_hashes.add(str(audit.get("manifest_sha256", "")))
        audits.append(audit)
    if coordinates != set(range(EXPECTED_ENTRY_SPEC_COUNT)):
        raise ValueError("historical shards do not cover entry indexes 0 through 9")
    merged = pd.concat(frames, ignore_index=True)
    _assert_columns(merged, ("combination_id", "replication_passed"), "historical results")
    expected_ids = set(manifest["combination_id"])
    if len(merged) != EXPECTED_COMBINATION_COUNT or set(merged["combination_id"]) != expected_ids:
        raise ValueError("historical replication does not cover the exact 290 contract")
    if merged["combination_id"].duplicated().any():
        raise ValueError("historical replication repeats a combination")
    if not merged["replication_passed"].map(_as_bool).all():
        raise ValueError("one or more historical replications failed")
    for metric, tolerance in METRIC_TOLERANCES.items():
        required = (
            f"{metric}_expected",
            f"{metric}_observed",
            f"{metric}_difference",
            f"{metric}_tolerance",
            f"{metric}_available",
            f"{metric}_passed",
        )
        _assert_columns(merged, required, "historical results")
        difference = pd.to_numeric(merged[f"{metric}_difference"], errors="coerce")
        declared = pd.to_numeric(merged[f"{metric}_tolerance"], errors="coerce")
        if difference.isna().any() or declared.isna().any():
            raise ValueError(f"historical {metric} comparison is non-finite")
        if not np.isfinite(difference).all() or not np.isfinite(declared).all():
            raise ValueError(f"historical {metric} comparison is non-finite")
        if not np.isclose(declared, tolerance, rtol=0.0, atol=0.0).all():
            raise ValueError(f"historical {metric} tolerance changed")
        if (difference.abs() > tolerance).any():
            raise ValueError(f"historical {metric} exceeds tolerance")
        if not merged[f"{metric}_available"].map(_as_bool).all():
            raise ValueError(f"historical {metric} is unavailable")
        if not merged[f"{metric}_passed"].map(_as_bool).all():
            raise ValueError(f"historical {metric} failed")
    audit = {
        "schema_version": 1,
        "historical_shard_count": EXPECTED_HISTORICAL_SHARDS,
        "combination_count": EXPECTED_COMBINATION_COUNT,
        "entry_spec_count": EXPECTED_ENTRY_SPEC_COUNT,
        "exit_spec_count": EXPECTED_EXIT_SPEC_COUNT,
        "all_replications_passed": True,
        "metric_tolerances": METRIC_TOLERANCES,
        "manifest_sha256_values": sorted(manifest_hashes),
        "new_oos_claimed": False,
        "optimization_performed_on_opened_data": False,
        "shards": audits,
    }
    if len(manifest_hashes) != 1:
        raise ValueError("historical shards do not share one manifest hash")
    only_manifest_hash = next(iter(manifest_hashes))
    if len(only_manifest_hash) != 64 or any(
        character not in "0123456789abcdef" for character in only_manifest_hash
    ):
        raise ValueError("historical manifest hash is not a complete sha256")
    return merged.sort_values("combination_id", kind="stable"), audit


def _audit_output_path(root: Path, metadata: Mapping[str, Any], stem: str, kind: str) -> Path:
    expected_name = f"{stem}.{'csv.gz' if kind == 'csv_gzip' else kind}"
    path = root / expected_name
    if not path.is_file():
        raise FileNotFoundError(path)
    _assert_sha256(path, metadata.get(f"{kind}_sha256"), str(path))
    return path


def merge_corrected_shards(
    shards_root: Path,
    manifest: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[dict[str, Any]]]:
    shards = _discover_shards(
        shards_root, CORRECTED_AUDIT_NAME, EXPECTED_CORRECTED_SHARDS
    )
    coordinates: set[tuple[int, str]] = set()
    opportunity_frames: list[pd.DataFrame] = []
    coverage_frames: list[pd.DataFrame] = []
    reconciliation_frames: list[pd.DataFrame] = []
    audits: list[dict[str, Any]] = []
    contract_ids = set(manifest["combination_id"])
    for root, audit in shards:
        index = int(audit.get("entry_index", -1))
        period = str(audit.get("period", ""))
        coordinate = (index, period)
        if index not in range(EXPECTED_ENTRY_SPEC_COUNT) or period not in PERIOD_NAMES:
            raise ValueError(f"invalid corrected shard coordinate {coordinate}")
        if coordinate in coordinates:
            raise ValueError(f"duplicate corrected shard coordinate {coordinate}")
        coordinates.add(coordinate)
        if int(audit.get("combination_count", -1)) != EXPECTED_EXIT_SPEC_COUNT:
            raise ValueError(f"corrected shard {coordinate} is not a 29-exit shard")
        if str(audit.get("cutoff")) != CUTOFF.date().isoformat():
            raise ValueError(f"corrected shard {coordinate} changed the cutoff")
        if _as_bool(audit.get("new_oos_claimed", True)):
            raise ValueError("corrected shard claimed new OOS")
        if _as_bool(audit.get("optimization_performed_on_opened_data", True)):
            raise ValueError("corrected shard optimized opened data")
        if _as_bool(audit.get("capital_rejection_applied", True)):
            raise ValueError("corrected shard applied a capital exclusion")
        if _as_bool(audit.get("portfolio_or_sizing_applied", True)):
            raise ValueError("corrected shard applied portfolio or sizing logic")
        if _as_bool(audit.get("overlaps_discarded", True)):
            raise ValueError("corrected shard discarded overlapping opportunities")
        outputs = audit.get("outputs")
        if not isinstance(outputs, dict):
            raise ValueError(f"corrected shard {coordinate} has no output audit")
        paths: dict[str, Path] = {}
        for key, stem in (
            ("opportunities", OPPORTUNITIES_STEM),
            ("coverage", COVERAGE_STEM),
            ("reconciliation", RECONCILIATION_STEM),
        ):
            metadata = outputs.get(key)
            if not isinstance(metadata, dict):
                raise ValueError(f"corrected shard {coordinate} has no {key} metadata")
            paths[key] = _audit_output_path(root, metadata, stem, "parquet")
            _audit_output_path(root, metadata, stem, "csv_gzip")
        opportunities = _read_parquet_compact(paths["opportunities"])
        coverage = _read_parquet_compact(paths["coverage"])
        reconciliation = _read_parquet_compact(paths["reconciliation"])
        _assert_columns(
            opportunities,
            ("opportunity_id", "combination_id", "entry_spec_id", "exit_spec_id", "period", "status"),
            "corrected opportunities",
        )
        if not set(opportunities["combination_id"].astype(str)) <= contract_ids:
            raise ValueError(f"corrected shard {coordinate} contains a foreign combination")
        if set(opportunities["status"].astype(str)) - LEDGER_STATUSES:
            raise ValueError(f"corrected shard {coordinate} contains an invalid status")
        if not opportunities["period"].astype(str).eq(period).all():
            raise ValueError(f"corrected shard {coordinate} mixes periods")
        if len(opportunities) != int(audit.get("opportunity_count", -1)):
            raise ValueError(f"corrected shard {coordinate} opportunity count differs from audit")
        if not reconciliation["reconciled"].map(_as_bool).all():
            raise ValueError(f"corrected shard {coordinate} does not reconcile")
        _assert_dates_at_cutoff(opportunities, f"corrected shard {coordinate}")
        opportunity_frames.append(opportunities)
        coverage_frames.append(coverage)
        reconciliation_frames.append(reconciliation)
        audits.append(audit)
        print(
            json.dumps(
                {
                    "stage": "loaded_corrected_shard",
                    "coordinate": [index, period],
                    "opportunity_rows": len(opportunities),
                    "rss_kib": _resident_memory_kib(),
                },
                sort_keys=True,
            ),
            flush=True,
        )
    expected_coordinates = {
        (index, period)
        for index in range(EXPECTED_ENTRY_SPEC_COUNT)
        for period in PERIOD_NAMES
    }
    if coordinates != expected_coordinates:
        raise ValueError("corrected shards do not cover the exact 10 by 3 coordinates")
    print(
        json.dumps(
            {
                "stage": "concatenating_corrected_shards",
                "shards": len(opportunity_frames),
                "rss_kib": _resident_memory_kib(),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    opportunities = pd.concat(opportunity_frames, ignore_index=True, copy=False)
    coverage = pd.concat(coverage_frames, ignore_index=True, copy=False)
    shard_reconciliation = pd.concat(
        reconciliation_frames, ignore_index=True, copy=False
    )
    opportunities = _remove_technical_duplicates(opportunities)
    return opportunities, coverage, shard_reconciliation, audits


def stream_corrected_shards(
    shards_root: Path,
    manifest: pd.DataFrame,
    *,
    fx_rates: pd.DataFrame,
    exact_strategy: Mapping[str, Any],
    prior_opportunities: pd.DataFrame,
    output_root: Path,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    list[dict[str, Any]],
    pd.DataFrame,
    pd.DataFrame,
    int,
    int,
]:
    """Merge the large ledgers out of core, retaining only statistics columns."""

    shards = _discover_shards(
        shards_root, CORRECTED_AUDIT_NAME, EXPECTED_CORRECTED_SHARDS
    )
    contract_ids = set(manifest["combination_id"].astype(str))
    coordinates: dict[tuple[int, str], dict[str, Any]] = {}
    base_column_order: list[str] = []
    base_column_types: dict[str, pa.DataType] = {}
    entry_indexes: dict[str, int] = {}
    coverage_frames: list[pd.DataFrame] = []
    reconciliation_frames: list[pd.DataFrame] = []
    audits: list[dict[str, Any]] = []

    for root, audit in shards:
        index = int(audit.get("entry_index", -1))
        period = str(audit.get("period", ""))
        coordinate = (index, period)
        if index not in range(EXPECTED_ENTRY_SPEC_COUNT) or period not in PERIOD_NAMES:
            raise ValueError(f"invalid corrected shard coordinate {coordinate}")
        if coordinate in coordinates:
            raise ValueError(f"duplicate corrected shard coordinate {coordinate}")
        if int(audit.get("combination_count", -1)) != EXPECTED_EXIT_SPEC_COUNT:
            raise ValueError(f"corrected shard {coordinate} is not a 29-exit shard")
        if str(audit.get("cutoff")) != CUTOFF.date().isoformat():
            raise ValueError(f"corrected shard {coordinate} changed the cutoff")
        for field in (
            "new_oos_claimed",
            "optimization_performed_on_opened_data",
            "capital_rejection_applied",
            "portfolio_or_sizing_applied",
            "overlaps_discarded",
        ):
            if _as_bool(audit.get(field, True)):
                raise ValueError(f"corrected shard {coordinate} violates {field}=false")
        outputs = audit.get("outputs")
        if not isinstance(outputs, dict):
            raise ValueError(f"corrected shard {coordinate} has no output audit")
        paths: dict[str, Path] = {}
        for key, stem in (
            ("opportunities", OPPORTUNITIES_STEM),
            ("coverage", COVERAGE_STEM),
            ("reconciliation", RECONCILIATION_STEM),
        ):
            metadata = outputs.get(key)
            if not isinstance(metadata, dict):
                raise ValueError(f"corrected shard {coordinate} has no {key} metadata")
            paths[key] = _audit_output_path(root, metadata, stem, "parquet")
            redundant_csv = _audit_output_path(root, metadata, stem, "csv_gzip")
            redundant_csv.unlink()

        coverage = _read_parquet_compact(paths["coverage"])
        _assert_columns(
            coverage,
            STATISTICAL_COVERAGE_COLUMNS,
            "corrected entry coverage",
        )
        shard_reconciliation = _read_parquet_compact(paths["reconciliation"])
        if not shard_reconciliation["reconciled"].map(_as_bool).all():
            raise ValueError(f"corrected shard {coordinate} does not reconcile")
        entry_spec_id = str(audit.get("entry_spec_id", ""))
        if entry_spec_id in entry_indexes and entry_indexes[entry_spec_id] != index:
            raise ValueError("one corrected entry spec maps to multiple indexes")
        entry_indexes[entry_spec_id] = index
        coordinates[coordinate] = {
            "opportunities_path": paths["opportunities"],
            "expected_rows": int(audit.get("opportunity_count", -1)),
            "loaded_rows": 0,
        }
        for field in pq.ParquetFile(paths["opportunities"]).schema_arrow:
            if field.name not in base_column_types:
                base_column_order.append(field.name)
                base_column_types[field.name] = field.type
                continue
            existing = base_column_types[field.name]
            if pa.types.is_null(existing) and not pa.types.is_null(field.type):
                base_column_types[field.name] = field.type
            elif not pa.types.is_null(field.type) and existing != field.type:
                raise ValueError(
                    f"corrected shards disagree on type for {field.name}: "
                    f"{existing} versus {field.type}"
                )
        coverage_frames.append(coverage)
        reconciliation_frames.append(shard_reconciliation)
        audits.append(audit)

    expected_coordinates = {
        (index, period)
        for index in range(EXPECTED_ENTRY_SPEC_COUNT)
        for period in PERIOD_NAMES
    }
    if set(coordinates) != expected_coordinates:
        raise ValueError("corrected shards do not cover the exact 10 by 3 coordinates")
    if set(entry_indexes) != set(manifest["entry_spec_id"].astype(str)):
        raise ValueError("corrected shards do not cover the exact entry specs")

    full_path = output_root / OPPORTUNITIES_PARQUET
    statistical_path = output_root / "_statistical_ledger.parquet"
    full_writer: pq.ParquetWriter | None = None
    full_schema: pa.Schema | None = None
    statistical_writer: pq.ParquetWriter | None = None
    statistical_schema: pa.Schema | None = None
    financing_frames: list[pd.DataFrame] = []
    fx_audit_frames: list[pd.DataFrame] = []
    technical_input_rows = 0
    technical_duplicates_removed = 0
    exact_entry_spec_id = str(
        manifest.loc[
            manifest["combination_id"].astype(str).eq(str(exact_strategy["candidate_id"])),
            "entry_spec_id",
        ].iloc[0]
    )

    try:
        for row in manifest.to_dict(orient="records"):
            combination_id = str(row["combination_id"])
            entry_spec_id = str(row["entry_spec_id"])
            index = entry_indexes[entry_spec_id]
            pieces: list[pd.DataFrame] = []
            for period in PERIOD_NAMES:
                metadata = coordinates[(index, period)]
                piece = pd.read_parquet(
                    metadata["opportunities_path"],
                    filters=[("combination_id", "==", combination_id)],
                    dtype_backend="pyarrow",
                )
                if not piece.empty:
                    _assert_columns(
                        piece,
                        (
                            "opportunity_id",
                            "combination_id",
                            "entry_spec_id",
                            "exit_spec_id",
                            "period",
                            "status",
                        ),
                        "corrected opportunity slice",
                    )
                    if not piece["combination_id"].astype(str).eq(combination_id).all():
                        raise ValueError("filtered corrected slice contains a foreign combination")
                    if set(piece["status"].astype(str)) - LEDGER_STATUSES:
                        raise ValueError("filtered corrected slice contains an invalid status")
                    if not piece["period"].astype(str).eq(period).all():
                        raise ValueError("filtered corrected slice mixes periods")
                metadata["loaded_rows"] += len(piece)
                pieces.append(piece)

            combined = pd.concat(pieces, ignore_index=True, copy=False)
            technical_input_rows += len(combined)
            combined = _remove_technical_duplicates(combined)
            technical_duplicates_removed += sum(len(piece) for piece in pieces) - len(combined)
            _assert_dates_at_cutoff(combined, f"corrected combination {combination_id}")
            for field in (
                "capital_rejected",
                "portfolio_simulated",
                "sizing_applied",
                "overlap_discarded",
                "new_oos_claimed",
                "optimization_performed_on_opened_data",
            ):
                if field in combined and combined[field].map(_as_bool).any():
                    raise ValueError(f"corrected combination violates {field}=false")

            combined, fx_audit = enrich_fx_causally(combined, fx_rates)
            if entry_spec_id == exact_entry_spec_id:
                combined, financing = reconcile_prior_financing(
                    combined, manifest, exact_strategy, prior_opportunities
                )
                financing_frames.append(financing)
            else:
                combined["financed_in_old_portfolio"] = False
                combined["financing_information_only"] = True
                combined["financing_reconciliation_status"] = (
                    "not_applicable_different_entry_spec"
                )
                combined["prior_audit_opportunity_id"] = ""
                combined["prior_not_financed_reason"] = ""
            fx_audit_frames.append(fx_audit)

            for column in base_column_order:
                if column not in combined:
                    combined[column] = pd.Series(
                        pa.nulls(len(combined), type=base_column_types[column]),
                        dtype=pd.ArrowDtype(base_column_types[column]),
                    )
            base_columns = set(base_column_order)
            output_columns = [
                *base_column_order,
                *(column for column in combined.columns if column not in base_columns),
            ]
            combined = combined.loc[:, output_columns]

            full_writer, full_schema = _append_parquet_frame(
                full_writer, full_schema, full_path, combined
            )
            missing_statistics = set(STATISTICAL_LEDGER_COLUMNS) - set(combined.columns)
            if missing_statistics:
                raise ValueError(
                    f"statistical ledger missing columns: {sorted(missing_statistics)}"
                )
            statistical_writer, statistical_schema = _append_parquet_frame(
                statistical_writer,
                statistical_schema,
                statistical_path,
                combined.loc[:, STATISTICAL_LEDGER_COLUMNS],
            )
            print(
                json.dumps(
                    {
                        "stage": "streamed_combination",
                        "combination_id": combination_id,
                        "rows": len(combined),
                        "rss_kib": _resident_memory_kib(),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
    finally:
        if full_writer is not None:
            full_writer.close()
        if statistical_writer is not None:
            statistical_writer.close()

    for coordinate, metadata in coordinates.items():
        if metadata["loaded_rows"] != metadata["expected_rows"]:
            raise ValueError(
                f"corrected shard {coordinate} row count differs from audit"
            )
    if full_writer is None or statistical_writer is None:
        raise ValueError("corrected shards produced no opportunities")

    opportunities = pd.read_parquet(statistical_path, dtype_backend="pyarrow")
    statistical_path.unlink()
    coverage = pd.concat(coverage_frames, ignore_index=True, copy=False)
    shard_reconciliation = pd.concat(
        reconciliation_frames, ignore_index=True, copy=False
    )
    financing_reconciliation = pd.concat(
        financing_frames, ignore_index=True, copy=False
    ).drop_duplicates(["symbol", "selection_date", "entry_date"], keep="first")
    fx_audit = pd.concat(fx_audit_frames, ignore_index=True, copy=False).drop_duplicates()
    return (
        opportunities,
        coverage,
        shard_reconciliation,
        audits,
        fx_audit,
        financing_reconciliation.reset_index(drop=True),
        technical_input_rows,
        technical_duplicates_removed,
    )


def _remove_technical_duplicates(frame: pd.DataFrame) -> pd.DataFrame:
    duplicated = frame[frame.duplicated("opportunity_id", keep=False)]
    if duplicated.empty:
        return frame.reset_index(drop=True)
    for _, group in duplicated.groupby("opportunity_id", sort=False):
        comparable = group.copy()
        for column in comparable.columns:
            if pd.api.types.is_datetime64_any_dtype(comparable[column]):
                comparable[column] = comparable[column].astype(str)
        if len(comparable.drop_duplicates()) != 1:
            raise ValueError("conflicting rows share a technical opportunity_id")
    return frame.drop_duplicates("opportunity_id", keep="first").reset_index(drop=True)


def reconcile_all_combinations(
    opportunities: pd.DataFrame,
    manifest: pd.DataFrame,
) -> pd.DataFrame:
    expected = manifest[["combination_id", "entry_spec_id", "exit_spec_id"]].copy()
    rows: list[dict[str, object]] = []
    for period in (*PERIOD_NAMES, "ALL"):
        source = opportunities if period == "ALL" else opportunities.loc[
            opportunities["period"].astype(str).eq(period)
        ]
        grouped = {
            str(key): group for key, group in source.groupby("combination_id", sort=False)
        }
        for spec in expected.to_dict(orient="records"):
            combination_id = str(spec["combination_id"])
            group = grouped.get(combination_id, source.iloc[0:0])
            statuses = group["status"].astype(str)
            unsupported = sorted(set(statuses) - LEDGER_STATUSES)
            completed = int(statuses.eq("completed").sum())
            censored = int(statuses.eq("right_censored").sum())
            failed = int(statuses.eq("failed_due_to_data").sum())
            total = int(len(group))
            rows.append(
                {
                    "combination_id": combination_id,
                    "entry_spec_id": spec["entry_spec_id"],
                    "exit_spec_id": spec["exit_spec_id"],
                    "period": period,
                    "opportunities": total,
                    "completed": completed,
                    "censored": censored,
                    "failed_due_to_data": failed,
                    "unsupported_statuses_json": json.dumps(unsupported),
                    "reconciled": not unsupported
                    and total == completed + censored + failed,
                }
            )
    result = pd.DataFrame(rows)
    if len(result) != EXPECTED_COMBINATION_COUNT * (len(PERIOD_NAMES) + 1):
        raise AssertionError("internal reconciliation row count error")
    if not result["reconciled"].all():
        raise ValueError("one or more combinations do not reconcile")
    return result


def _empty_fx_audit(currency: str, status: str) -> dict[str, object]:
    return {
        "currency": currency,
        "status": status,
        "orientation": "not_available",
        "source": "none",
        "observations": 0,
    }


def _fx_audit_frame(rows: Sequence[Mapping[str, object]]) -> pd.DataFrame:
    columns = (
        "currency",
        "status",
        "orientation",
        "source",
        "source_symbol",
        "start",
        "end",
        "observations",
    )
    return pd.DataFrame(list(rows)).reindex(columns=columns)


def _apply_primary_event_return(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    completed = result["status"].astype(str).eq("completed")
    usd = pd.to_numeric(result["return_usd"], errors="coerce")
    local = pd.to_numeric(result["total_return_local"], errors="coerce")
    if (completed & usd.isna() & local.isna()).any():
        raise ValueError("completed opportunities require USD or local total return")
    result["primary_event_return"] = np.where(usd.notna(), usd, local)
    result.loc[~completed, "primary_event_return"] = np.nan
    result["primary_event_return_basis"] = np.where(
        usd.notna(), "total_return_usd", "total_return_local"
    )
    result.loc[~completed, "primary_event_return_basis"] = "not_realized"
    result["gross_return"] = pd.to_numeric(
        result.get("gross_return"), errors="coerce"
    )
    result.loc[completed, "gross_return"] = result.loc[
        completed, "primary_event_return"
    ]
    result.loc[~completed, "gross_return"] = np.nan
    result["gross_return_basis"] = result["primary_event_return_basis"]
    return result


def enrich_fx_causally(
    opportunities: pd.DataFrame,
    fx_rates: pd.DataFrame | None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fill FX fields from a caller-supplied frozen table, never a live source."""

    result = opportunities.copy().reset_index(drop=True)
    _assert_columns(
        result,
        (
            "currency",
            "currency_unknown",
            "entry_date",
            "entry_price",
            "entry_value_local_per_initial_share",
            "exit_date",
            "exit_price",
            "exit_value_local_per_initial_share",
            "mtm_date",
            "mtm_price",
            "dividends_local",
            "dividend_payments_local_json",
            "total_return_local",
            "price_scale_to_currency_unit",
        ),
        "FX opportunity ledger",
    )
    if fx_rates is None:
        raise ValueError("frozen FX rates are required; live FX download is prohibited")
    _assert_columns(fx_rates, ("date", "currency", "usd_per_local"), "FX rates")
    rates = fx_rates.copy()
    rates["date"] = pd.to_datetime(rates["date"], errors="raise").dt.normalize()
    rates["usd_per_local"] = pd.to_numeric(rates["usd_per_local"], errors="coerce")
    if rates["usd_per_local"].isna().any() or not np.isfinite(rates["usd_per_local"]).all():
        raise ValueError("FX rates contain non-finite values")
    if (rates["usd_per_local"] <= 0).any() or (rates["date"] > CUTOFF).any():
        raise ValueError("FX rates are non-positive or exceed the cutoff")
    if rates.duplicated(["currency", "date"]).any():
        raise ValueError("FX rates repeat a currency-date observation")
    result["currency_unknown"] = result["currency_unknown"].map(_as_bool)
    known = ~result["currency_unknown"] & result["currency"].notna()
    known &= result["currency"].astype(str).str.strip().ne("")
    currencies = sorted(set(result.loc[known, "currency"].astype(str)))
    existing = pd.to_numeric(result.get("return_usd"), errors="coerce")
    needs_fx = known & existing.isna()
    if not needs_fx.any():
        audit = _fx_audit_frame(
            [
                {
                    "currency": currency,
                    "status": "already_enriched",
                    "orientation": "USD_identity" if currency == "USD" else "usd_per_local",
                    "source": "identity" if currency == "USD" else "frozen_cli_fx_rates",
                    "observations": int(rates["currency"].astype(str).eq(currency).sum()),
                }
                for currency in currencies
            ]
        )
        return _apply_primary_event_return(result), audit
    audit_rows = []
    for currency in currencies:
        observations = int(rates["currency"].astype(str).eq(currency).sum())
        audit_rows.append(
            {
                "currency": currency,
                "status": (
                    "identity" if currency == "USD" else "provided" if observations else "missing"
                ),
                "orientation": "USD_identity" if currency == "USD" else "usd_per_local",
                "source": "identity" if currency == "USD" else "frozen_cli_fx_rates",
                "observations": observations,
            }
        )
    audit = _fx_audit_frame(audit_rows)
    for column in FX_COLUMNS:
        if column not in result:
            if column in {"fx_entry_date", "fx_exit_date"}:
                result[column] = pd.Series(
                    pd.NaT, index=result.index, dtype="datetime64[ns]"
                )
            elif column == "fx_dividend_dates_used":
                result[column] = pd.Series("", index=result.index, dtype=object)
            else:
                result[column] = np.nan
    for column in ("fx_entry_date", "fx_exit_date"):
        result[column] = pd.to_datetime(result[column], errors="coerce")
    result["fx_dividend_dates_used"] = (
        result["fx_dividend_dates_used"]
        .astype("string[python]")
        .fillna("")
        .astype(object)
    )
    for column in set(FX_COLUMNS) - {
        "fx_entry_date",
        "fx_exit_date",
        "fx_dividend_dates_used",
    }:
        result[column] = pd.to_numeric(result[column], errors="coerce").astype(float)
    if "fx_merge_status" not in result:
        result["fx_merge_status"] = "not_available"
    else:
        result["fx_merge_status"] = result["fx_merge_status"].fillna("not_available").astype(object)
    if "fx_values_invented" not in result:
        result["fx_values_invented"] = False
    work = result.loc[needs_fx].copy()
    work["_source_index"] = work.index
    work["_valuation_date"] = pd.to_datetime(work["exit_date"], errors="coerce")
    work["_valuation_price"] = pd.to_numeric(work["exit_price"], errors="coerce")
    censored = work["status"].astype(str).eq("right_censored")
    work.loc[censored, "_valuation_date"] = pd.to_datetime(
        work.loc[censored, "mtm_date"], errors="coerce"
    )
    work.loc[censored, "_valuation_price"] = pd.to_numeric(
        work.loc[censored, "mtm_price"], errors="coerce"
    )
    mergeable = work["entry_date"].notna() & work["_valuation_date"].notna()
    work.loc[~mergeable, "fx_merge_status"] = "missing_valuation_date"
    merged = work.loc[mergeable].copy()
    if not merged.empty:
        entry = causal_fx_merge(merged, rates, date_column="entry_date").rename(
            columns={"fx_date": "_fx_entry_date", "fx_usd_per_local": "_fx_entry"}
        )
        valued = causal_fx_merge(entry, rates, date_column="_valuation_date").rename(
            columns={"fx_date": "_fx_exit_date", "fx_usd_per_local": "_fx_exit"}
        )
        valued = valued.set_index("_source_index", drop=False)
        scale = pd.to_numeric(valued["price_scale_to_currency_unit"], errors="coerce")
        entry_price = pd.to_numeric(
            valued["entry_value_local_per_initial_share"], errors="coerce"
        )
        exit_price = pd.to_numeric(
            valued["exit_value_local_per_initial_share"], errors="coerce"
        )
        entry_value = entry_price * scale * valued["_fx_entry"]
        exit_value = exit_price * scale * valued["_fx_exit"]
        dividends = pd.to_numeric(valued["dividends_local"], errors="coerce").fillna(0.0)
        rates_available = valued["_fx_entry"].notna() & valued["_fx_exit"].notna()
        dividend_usd = pd.Series(0.0, index=valued.index, dtype=float)
        dividend_dates = pd.Series("", index=valued.index, dtype=object)
        dividend_complete = pd.Series(True, index=valued.index, dtype=bool)
        payment_rows: list[dict[str, object]] = []
        for source_index, row in valued.iterrows():
            raw = row.get("dividend_payments_local_json", "[]")
            try:
                payments = json.loads(str(raw))
            except json.JSONDecodeError as exc:
                raise ValueError("invalid dividend_payments_local_json") from exc
            if not isinstance(payments, list):
                raise ValueError("dividend_payments_local_json must contain a list")
            declared_total = 0.0
            dates_used: list[str] = []
            for payment in payments:
                if not isinstance(payment, dict):
                    raise ValueError("dividend payment must be a JSON object")
                date = pd.to_datetime(payment.get("date"), errors="coerce")
                cash = pd.to_numeric(
                    pd.Series([payment.get("cash_local_per_initial_share")]),
                    errors="coerce",
                ).iloc[0]
                if pd.isna(date) or not np.isfinite(cash):
                    raise ValueError("dividend payment has invalid date or amount")
                date = pd.Timestamp(date).normalize()
                if date > CUTOFF or date < pd.Timestamp(row["entry_date"]).normalize():
                    raise ValueError("dividend payment lies outside its causal holding window")
                if date > pd.Timestamp(row["_valuation_date"]).normalize():
                    raise ValueError("dividend payment occurs after valuation")
                declared_total += float(cash)
                dates_used.append(date.date().isoformat())
                payment_rows.append(
                    {
                        "_source_index": source_index,
                        "date": date,
                        "currency": row["currency"],
                        "cash_local_per_initial_share": float(cash),
                        "price_scale_to_currency_unit": float(scale.loc[source_index]),
                    }
                )
            if not np.isclose(
                declared_total,
                float(dividends.loc[source_index]),
                rtol=1e-10,
                atol=1e-12,
            ):
                dividend_complete.loc[source_index] = False
            dividend_dates.loc[source_index] = ",".join(dates_used)
        if payment_rows:
            payments = causal_fx_merge(
                pd.DataFrame(payment_rows), rates, date_column="date"
            )
            payments["cash_usd_per_initial_share"] = (
                payments["cash_local_per_initial_share"]
                * payments["price_scale_to_currency_unit"]
                * payments["fx_usd_per_local"]
            )
            for source_index, group in payments.groupby("_source_index", sort=False):
                complete_payment_fx = group["fx_usd_per_local"].notna().all()
                dividend_complete.loc[source_index] &= bool(complete_payment_fx)
                if complete_payment_fx:
                    dividend_usd.loc[source_index] = float(
                        group["cash_usd_per_initial_share"].sum()
                    )
        convertible = rates_available & dividend_complete & entry_value.gt(0)
        result.loc[valued.index, "fx_entry_date"] = valued["_fx_entry_date"].to_numpy()
        result.loc[valued.index, "fx_exit_date"] = valued["_fx_exit_date"].to_numpy()
        result.loc[valued.index, "fx_entry_rate_usd_per_local"] = valued["_fx_entry"].to_numpy()
        result.loc[valued.index, "fx_exit_rate_usd_per_local"] = valued["_fx_exit"].to_numpy()
        result.loc[valued.index, "entry_value_usd_per_share"] = entry_value.to_numpy()
        result.loc[valued.index, "exit_value_usd_per_share"] = exit_value.to_numpy()
        result.loc[valued.index, "dividend_value_usd_per_share"] = np.where(
            dividend_complete, dividend_usd, np.nan
        )
        result.loc[valued.index, "fx_dividend_dates_used"] = dividend_dates.to_numpy()
        result.loc[valued.index, "return_usd"] = np.where(
            convertible,
            exit_value.add(dividend_usd).div(entry_value).sub(1.0),
            np.nan,
        )
        local_return = pd.to_numeric(valued["total_return_local"], errors="coerce")
        result.loc[valued.index, "fx_return_contribution"] = np.where(
            convertible,
            exit_value.add(dividend_usd).div(entry_value).sub(1.0) - local_return,
            np.nan,
        )
        statuses = np.select(
            [~rates_available, rates_available & ~dividend_complete, convertible],
            ["missing_fx_rate", "missing_dividend_payment_detail_or_fx", "causal_enriched"],
            default="invalid_price_for_fx",
        )
        result.loc[valued.index, "fx_merge_status"] = statuses
    result.loc[~known, "fx_merge_status"] = "currency_unknown"
    result["fx_values_invented"] = False
    _assert_dates_at_cutoff(result, "FX-enriched opportunities")
    return _apply_primary_event_return(result), audit


def _event_ledger(opportunities: pd.DataFrame) -> pd.DataFrame:
    ledger = opportunities.loc[
        opportunities["status"].astype(str).isin({"completed", "right_censored"})
    ].copy()
    if ledger.empty:
        raise ValueError("no completed or right-censored opportunities are available")
    for column in ("country", "market", "currency"):
        if column not in ledger:
            ledger[column] = "UNKNOWN"
        ledger[column] = ledger[column].fillna("UNKNOWN").replace("", "UNKNOWN")
    _assert_columns(
        ledger,
        ("combination_id", "symbol", "entry_date", "gross_return", "holding_sessions", "period"),
        "event ledger",
    )
    return ledger


def _selection_ledger(ledger: pd.DataFrame) -> pd.DataFrame:
    development = ledger.loc[ledger["period"].astype(str).eq("A")].copy()
    if development.empty:
        raise ValueError("period A has no development opportunities")
    development["period"] = "development"
    development["selection_role"] = "development"
    development["validation_used_for_selection"] = False
    development["locked_used_for_selection"] = False
    return development


def _write_frame(path: Path, frame: pd.DataFrame) -> None:
    if path.suffix == ".parquet":
        frame.to_parquet(path, index=False)
    else:
        frame.to_csv(path, index=False)


PAIRED_EXIT_METRICS: dict[str, str] = {
    "return": "net_event_return",
    "loss": "loss_indicator",
    "mae": "event_mae",
    "duration": "event_duration",
    "return_per_session": "event_speed",
}
PAIRED_ENTRY_METRICS = (
    "trigger_probability",
    "entry_price",
    "entry_delay_sessions",
    "return",
    "mae",
    "duration",
    "coverage",
)


def _paired_delta_row(
    left: pd.DataFrame,
    right: pd.DataFrame,
    *,
    keys: Sequence[str],
    left_value: str,
    right_value: str,
    baseline: str,
    challenger: str,
    metric: str,
    source: str,
) -> dict[str, object]:
    pairs = left[[*keys, left_value]].merge(
        right[[*keys, right_value]],
        on=list(keys),
        how="inner",
        validate="one_to_one",
        suffixes=("_baseline", "_challenger"),
    )
    baseline_column = f"{left_value}_baseline" if left_value == right_value else left_value
    challenger_column = (
        f"{right_value}_challenger" if left_value == right_value else right_value
    )
    baseline_values = pd.to_numeric(pairs[baseline_column], errors="coerce")
    challenger_values = pd.to_numeric(pairs[challenger_column], errors="coerce")
    deltas = challenger_values.sub(baseline_values).dropna().to_numpy(dtype=float)
    common = {
        "baseline": baseline,
        "challenger": challenger,
        "metric": metric,
        "metric_source": source,
        "causal_keys": json.dumps(list(keys), separators=(",", ":")),
        "pairs": int(len(deltas)),
    }
    if not len(deltas):
        return {
            **common,
            "analysis_status": "not_estimable_no_complete_pairs",
            "mean_delta": "not_estimable",
            "median_delta": "not_estimable",
            "ci_low95": "not_estimable",
            "ci_high95": "not_estimable",
            "positive_pairs": 0,
            "negative_pairs": 0,
            "ties": 0,
            "sign_test_pvalue": "not_estimable",
            "primary_inference_method": "not_estimable",
        }
    mean = float(deltas.mean())
    if len(deltas) > 1:
        half_width = 1.96 * float(deltas.std(ddof=1)) / math.sqrt(len(deltas))
    else:
        half_width = 0.0
    positive = int((deltas > 0).sum())
    negative = int((deltas < 0).sum())
    nonzero = positive + negative
    if nonzero:
        tail = sum(
            math.comb(nonzero, index) for index in range(min(positive, negative) + 1)
        ) / (2**nonzero)
        sign_pvalue = min(1.0, 2.0 * tail)
    else:
        sign_pvalue = 1.0
    return {
        **common,
        "analysis_status": "estimable",
        "mean_delta": mean,
        "median_delta": float(np.median(deltas)),
        "ci_low95": mean - half_width,
        "ci_high95": mean + half_width,
        "positive_pairs": positive,
        "negative_pairs": negative,
        "ties": int((deltas == 0).sum()),
        "sign_test_pvalue": sign_pvalue,
        "primary_inference_method": "paired_sign_test_with_normal_mean_ci",
    }


def _paired_exit_rows(
    ledger: pd.DataFrame,
    *,
    entry_ids: Sequence[str],
    exit_ids: Sequence[str],
) -> pd.DataFrame:
    enriched = ledger.copy()
    enriched["loss_indicator"] = np.where(
        pd.to_numeric(enriched["gross_return"], errors="coerce").notna(),
        pd.to_numeric(enriched["gross_return"], errors="coerce").lt(0).astype(float),
        np.nan,
    )
    from aurora.research.stock_protocol.event_study_290_statistics import (
        add_event_efficiency_metrics,
    )

    enriched = add_event_efficiency_metrics(enriched)
    keys = ("symbol", "period", "selection_date", "entry_signal_date", "entry_date")
    rows: list[dict[str, object]] = []
    for entry_spec_id in entry_ids:
        family = enriched.loc[
            enriched["entry_spec_id"].astype(str).eq(str(entry_spec_id))
        ]
        for baseline, challenger in combinations(exit_ids, 2):
            left = family.loc[family["exit_spec_id"].astype(str).eq(str(baseline))]
            right = family.loc[family["exit_spec_id"].astype(str).eq(str(challenger))]
            for metric, column in PAIRED_EXIT_METRICS.items():
                row = _paired_delta_row(
                    left,
                    right,
                    keys=keys,
                    left_value=column,
                    right_value=column,
                    baseline=str(baseline),
                    challenger=str(challenger),
                    metric=metric,
                    source="opportunity_ledger",
                )
                row["entry_spec_id"] = entry_spec_id
                rows.append(row)
    return pd.DataFrame(rows)


def _paired_entry_rows(
    ledger: pd.DataFrame,
    coverage: pd.DataFrame,
    manifest: pd.DataFrame,
    *,
    entry_ids: Sequence[str],
    exit_ids: Sequence[str],
) -> pd.DataFrame:
    lineage = (
        manifest[
            ["entry_spec_id", "entry_upstream_candidate_id", "upstream_candidate_ids_json"]
        ]
        .drop_duplicates("entry_spec_id")
        .set_index("entry_spec_id")
    )
    coverage_frame = coverage.copy()
    _assert_columns(
        coverage_frame,
        (
            "entry_spec_id",
            "symbol",
            "selection_date",
            "period",
            "triggered",
            "entry_in_period",
            "wait_sessions",
        ),
        "entry coverage",
    )
    coverage_frame["trigger_probability"] = coverage_frame["triggered"].map(_as_bool).astype(float)
    coverage_frame["coverage"] = 1.0
    coverage_frame["entry_delay_sessions"] = pd.to_numeric(
        coverage_frame["wait_sessions"], errors="coerce"
    )
    coverage_frame = coverage_frame.merge(
        lineage.reset_index(), on="entry_spec_id", how="left", validate="many_to_one"
    )
    event = ledger.copy()
    event["return"] = pd.to_numeric(event["gross_return"], errors="coerce")
    event["mae"] = pd.to_numeric(event["maximum_adverse_excursion"], errors="coerce")
    event["duration"] = pd.to_numeric(event["holding_sessions"], errors="coerce")
    event = event.merge(
        lineage.reset_index(), on="entry_spec_id", how="left", validate="many_to_one"
    )
    rows: list[dict[str, object]] = []
    coverage_keys = (
        "symbol",
        "period",
        "selection_date",
        "entry_upstream_candidate_id",
        "upstream_candidate_ids_json",
    )
    event_keys = (
        "symbol",
        "period",
        "selection_date",
        "entry_upstream_candidate_id",
        "upstream_candidate_ids_json",
    )
    for baseline, challenger in combinations(entry_ids, 2):
        same_upstream = (
            lineage.loc[baseline, "entry_upstream_candidate_id"]
            == lineage.loc[challenger, "entry_upstream_candidate_id"]
            and lineage.loc[baseline, "upstream_candidate_ids_json"]
            == lineage.loc[challenger, "upstream_candidate_ids_json"]
        )
        left_coverage = coverage_frame.loc[
            coverage_frame["entry_spec_id"].astype(str).eq(str(baseline))
        ]
        right_coverage = coverage_frame.loc[
            coverage_frame["entry_spec_id"].astype(str).eq(str(challenger))
        ]
        for exit_spec_id in exit_ids:
            for metric in PAIRED_ENTRY_METRICS:
                if not same_upstream:
                    row = {
                        "baseline": str(baseline),
                        "challenger": str(challenger),
                        "metric": metric,
                        "metric_source": "upstream_coverage",
                        "causal_keys": json.dumps(list(coverage_keys), separators=(",", ":")),
                        "pairs": 0,
                        "analysis_status": "not_estimable_different_upstream",
                        "mean_delta": "not_estimable",
                        "median_delta": "not_estimable",
                        "ci_low95": "not_estimable",
                        "ci_high95": "not_estimable",
                        "positive_pairs": 0,
                        "negative_pairs": 0,
                        "ties": 0,
                        "sign_test_pvalue": "not_estimable",
                        "primary_inference_method": "not_estimable",
                    }
                elif metric in {"trigger_probability", "entry_delay_sessions", "coverage"}:
                    left_metric = left_coverage
                    right_metric = right_coverage
                    if metric == "entry_delay_sessions":
                        left_metric = left_metric.loc[
                            left_metric["triggered"].map(_as_bool)
                        ]
                        right_metric = right_metric.loc[
                            right_metric["triggered"].map(_as_bool)
                        ]
                    if metric in {"trigger_probability", "coverage"}:
                        aligned = left_coverage[[*coverage_keys, metric]].merge(
                            right_coverage[[*coverage_keys, metric]],
                            on=list(coverage_keys),
                            how="outer",
                            validate="one_to_one",
                            suffixes=("_baseline", "_challenger"),
                        )
                        aligned[f"{metric}_baseline"] = aligned[
                            f"{metric}_baseline"
                        ].fillna(0.0)
                        aligned[f"{metric}_challenger"] = aligned[
                            f"{metric}_challenger"
                        ].fillna(0.0)
                        left_metric = aligned[[*coverage_keys, f"{metric}_baseline"]]
                        right_metric = aligned[[*coverage_keys, f"{metric}_challenger"]]
                    row = _paired_delta_row(
                        left_metric,
                        right_metric,
                        keys=coverage_keys,
                        left_value=(
                            f"{metric}_baseline"
                            if metric in {"trigger_probability", "coverage"}
                            else metric
                        ),
                        right_value=(
                            f"{metric}_challenger"
                            if metric in {"trigger_probability", "coverage"}
                            else metric
                        ),
                        baseline=str(baseline),
                        challenger=str(challenger),
                        metric=metric,
                        source="upstream_entry_coverage",
                    )
                else:
                    left_event = event.loc[
                        event["entry_spec_id"].astype(str).eq(str(baseline))
                        & event["exit_spec_id"].astype(str).eq(str(exit_spec_id))
                    ]
                    right_event = event.loc[
                        event["entry_spec_id"].astype(str).eq(str(challenger))
                        & event["exit_spec_id"].astype(str).eq(str(exit_spec_id))
                    ]
                    row = _paired_delta_row(
                        left_event,
                        right_event,
                        keys=event_keys,
                        left_value=metric if metric != "entry_price" else "entry_price",
                        right_value=metric if metric != "entry_price" else "entry_price",
                        baseline=str(baseline),
                        challenger=str(challenger),
                        metric=metric,
                        source="opportunity_ledger_matched_on_upstream_selection",
                    )
                row["exit_spec_id"] = exit_spec_id
                rows.append(row)
    return pd.DataFrame(rows)


def _family_return_matrix(
    development: pd.DataFrame,
    combination_ids: Sequence[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    complete = development.loc[
        development["status"].astype(str).eq("completed")
        & development["combination_id"].astype(str).isin(combination_ids)
    ].copy()
    causal_keys = ["symbol", "signal_date"]
    _assert_columns(complete, (*causal_keys, "gross_return"), "family return matrix")
    if complete.duplicated(["combination_id", *causal_keys]).any():
        raise ValueError("family return matrix has duplicate causal keys")
    complete["gross_return"] = pd.to_numeric(complete["gross_return"], errors="coerce")
    matrix = complete.pivot(
        index=causal_keys,
        columns="combination_id",
        values="gross_return",
    ).reindex(columns=list(combination_ids)).dropna(axis=0, how="any")
    if matrix.shape[0] < 8 or matrix.shape[1] < 2:
        raise ValueError("family has insufficient shared events for clustered PBO")
    if not np.isfinite(matrix.to_numpy(dtype=float)).all():
        raise ValueError("family return matrix contains non-finite values")
    cluster_frame = matrix.index.to_frame(index=False)
    cluster_frame["entry_year"] = pd.to_datetime(
        cluster_frame["signal_date"], errors="raise"
    ).dt.year.astype(int)
    if pd.to_datetime(cluster_frame["signal_date"], errors="raise").nunique() < 8:
        raise ValueError("family has fewer than eight distinct causal dates")
    return matrix.reset_index(drop=True), cluster_frame.reset_index(drop=True)


def _functional_representatives(
    functional_duplicates: pd.DataFrame,
    combination_ids: Sequence[str],
) -> tuple[list[str], dict[str, str]]:
    candidates = {str(value) for value in combination_ids}
    mapping = {value: value for value in candidates}
    duplicated = functional_duplicates.loc[
        functional_duplicates["combination_id"].astype(str).isin(candidates)
        & functional_duplicates["functionally_duplicated"].astype(bool)
    ]
    for row in duplicated.to_dict(orient="records"):
        combination = str(row["combination_id"])
        canonical = str(row["canonical_combination_id"])
        if canonical in candidates:
            mapping[combination] = min(mapping[combination], canonical)
    for combination in sorted(mapping):
        while mapping[combination] != mapping.get(mapping[combination], mapping[combination]):
            mapping[combination] = mapping[mapping[combination]]
    retained = [value for value in combination_ids if mapping[str(value)] == str(value)]
    return [str(value) for value in retained], mapping


def _global_functional_mapping(
    functional_duplicates: pd.DataFrame,
    combination_ids: Sequence[str],
) -> dict[str, str]:
    """Collapse every duplicate edge from the global spec/trade/result audit."""

    identifiers = [str(value) for value in combination_ids]
    parent = {value: value for value in identifiers}

    def find(value: str) -> str:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: str, right: str) -> None:
        if left not in parent or right not in parent:
            return
        left_root = find(left)
        right_root = find(right)
        canonical = min(left_root, right_root)
        parent[left_root] = canonical
        parent[right_root] = canonical

    _assert_columns(
        functional_duplicates,
        ("combination_id", "functionally_duplicated", "canonical_combination_id"),
        "global functional duplicate audit",
    )
    for row in functional_duplicates.to_dict(orient="records"):
        if _as_bool(row["functionally_duplicated"]):
            union(str(row["combination_id"]), str(row["canonical_combination_id"]))
    groups: dict[str, list[str]] = {}
    for identifier in identifiers:
        groups.setdefault(find(identifier), []).append(identifier)
    mapping: dict[str, str] = {}
    for members in groups.values():
        canonical = min(members)
        mapping.update({member: canonical for member in members})
    return mapping


def _deduplicate_result_vectors(matrix: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
    fingerprints: dict[str, str] = {}
    canonical: dict[str, str] = {}
    retained: list[str] = []
    for column in matrix.columns:
        values = np.round(matrix[column].to_numpy(dtype=float), 12)
        fingerprint = hashlib.sha256(values.tobytes()).hexdigest()
        if fingerprint in fingerprints:
            canonical[str(column)] = fingerprints[fingerprint]
        else:
            fingerprints[fingerprint] = str(column)
            canonical[str(column)] = str(column)
            retained.append(str(column))
    return matrix[retained], canonical


def _multiple_testing(
    development: pd.DataFrame,
    manifest: pd.DataFrame,
    functional_duplicates: pd.DataFrame,
    *,
    bootstrap_samples: int,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    declared = manifest[
        ["combination_id", "entry_spec_id", "exit_spec_id", "corrected_track_applicability"]
    ].copy()
    declared["combination_id"] = declared["combination_id"].astype(str)
    declared["analysis_status"] = np.where(
        declared["corrected_track_applicability"].eq("not_applicable"),
        "unsupported_semantics",
        "unsupported_insufficient_completed_events",
    )
    declared["observations"] = 0
    declared["pbo_included"] = False
    declared["functional_canonical_combination_id"] = declared["combination_id"]
    result_columns = (
        "mean_return",
        "cluster_pvalue_one_sided",
        "benjamini_hochberg_pvalue",
        "holm_pvalue",
        "bh_declared_290_pvalue",
        "holm_declared_290_pvalue",
        "bh_functionally_unique_pvalue",
        "holm_functionally_unique_pvalue",
        "event_statistic",
        "expected_max_under_trials",
        "deflated_event_statistic",
        "deflated_event_probability",
        "westfall_young_statistic",
        "westfall_young_pvalue",
    )
    for column in result_columns:
        declared[column] = "not_estimable"
    declared["cluster_method"] = "not_supported"
    declared["westfall_young_method"] = "not_supported"

    complete = development.loc[development["status"].astype(str).eq("completed")]
    counts = complete.groupby("combination_id").size()
    semantically_eligible = declared.loc[
        declared["corrected_track_applicability"].ne("not_applicable"),
        "combination_id",
    ].tolist()
    individually_supported = [
        combination for combination in semantically_eligible if int(counts.get(combination, 0)) >= 2
    ]
    if not individually_supported:
        raise ValueError("no semantically eligible rule has enough completed events")
    cluster_ledger = development.loc[
        development["combination_id"].astype(str).isin(individually_supported)
    ]
    cluster_tests = cluster_mean_significance_tests(
        cluster_ledger,
        bootstrap_samples=bootstrap_samples,
        seed=20260721,
    ).set_index("combination_id")
    raw_pvalues = cluster_tests.loc[individually_supported, "pvalue_one_sided"].to_numpy(dtype=float)
    for position, combination in enumerate(individually_supported):
        group = complete.loc[complete["combination_id"].astype(str).eq(combination)]
        values = pd.to_numeric(group["gross_return"], errors="coerce").to_numpy(dtype=float)
        deflated = deflated_event_statistic(values, trials=EXPECTED_COMBINATION_COUNT)
        mask = declared["combination_id"].eq(combination)
        declared.loc[mask, "analysis_status"] = "supported_cluster_only"
        declared.loc[mask, "observations"] = len(values)
        declared.loc[mask, "mean_return"] = float(cluster_tests.loc[combination, "mean_return"])
        declared.loc[mask, "cluster_pvalue_one_sided"] = float(raw_pvalues[position])
        declared.loc[mask, "cluster_method"] = str(cluster_tests.loc[combination, "method"])
        for key in (
            "event_statistic",
            "expected_max_under_trials",
            "deflated_event_statistic",
            "deflated_event_probability",
        ):
            declared.loc[mask, key] = float(deflated[key])

    max_t_frames: list[pd.DataFrame] = []
    pbo_rows: list[dict[str, Any]] = []
    global_mapping = _global_functional_mapping(
        functional_duplicates, declared["combination_id"].tolist()
    )
    declared["global_functional_canonical_combination_id"] = declared[
        "combination_id"
    ].map(global_mapping)
    declared["globally_functionally_unique"] = (
        declared["global_functional_canonical_combination_id"]
        == declared["combination_id"]
    )
    globally_unique_tests = len(set(global_mapping.values()))
    entry_order = manifest["entry_spec_id"].drop_duplicates().astype(str).tolist()
    for entry_spec_id in entry_order:
        family = declared.loc[
            declared["entry_spec_id"].astype(str).eq(entry_spec_id)
            & declared["combination_id"].isin(individually_supported),
            "combination_id",
        ].tolist()
        representatives, canonical = _functional_representatives(
            functional_duplicates, family
        )
        for combination, representative in canonical.items():
            declared.loc[
                declared["combination_id"].eq(combination),
                "functional_canonical_combination_id",
            ] = representative
        if len(representatives) < 2:
            continue
        try:
            matrix, cluster_frame = _family_return_matrix(development, representatives)
        except ValueError:
            continue
        matrix, vector_canonical = _deduplicate_result_vectors(matrix)
        for combination, representative in vector_canonical.items():
            declared.loc[
                declared["combination_id"].eq(combination),
                "functional_canonical_combination_id",
            ] = representative
        if matrix.shape[1] < 2:
            continue
        max_t = westfall_young_max_t(
            matrix,
            cluster_frame=cluster_frame,
            bootstrap_samples=bootstrap_samples,
            seed=20260721,
        ).rename(
            columns={
                "statistic": "westfall_young_statistic",
                "adjusted_pvalue": "westfall_young_pvalue",
                "method": "westfall_young_method",
            }
        )
        max_t["entry_spec_id"] = entry_spec_id
        max_t_frames.append(max_t)
        white_spa = white_spa_equivalent(
            matrix,
            cluster_frame=cluster_frame,
            bootstrap_samples=bootstrap_samples,
            seed=20260721,
        ).set_index("test")
        pbo = cscv_pbo(
            matrix,
            partitions=8,
            observation_dates=cluster_frame["signal_date"],
            functional_duplicates=functional_duplicates,
        )
        if int(pbo["effective_combinations"]) != matrix.shape[1]:
            raise ValueError(
                "PBO found a functional duplicate not removed from the family matrix"
            )
        logits = np.asarray(pbo["logits"], dtype=float)
        pbo_rows.append(
            {
                "entry_spec_id": entry_spec_id,
                "pbo": float(pbo["pbo"]),
                "splits": int(pbo["splits"]),
                "median_logit": float(pbo["median_logit"]),
                "logit_min": float(logits.min()),
                "logit_max": float(logits.max()),
                "method": pbo["method"],
                "rank_method": pbo["rank_method"],
                "matrix_rows": int(matrix.shape[0]),
                "family_eligible_tests": len(family),
                "family_functionally_unique_tests": int(pbo["effective_combinations"]),
                "white_statistic": float(white_spa.loc["white_reality_check", "statistic"]),
                "white_pvalue": float(white_spa.loc["white_reality_check", "pvalue"]),
                "spa_statistic": float(white_spa.loc["spa", "statistic"]),
                "spa_pvalue": float(white_spa.loc["spa", "pvalue"]),
                "selection_period": "A_development_only",
            }
        )
    if not pbo_rows:
        raise ValueError("no entry family supports clustered CSCV/PBO")
    if max_t_frames:
        max_t_all = pd.concat(max_t_frames, ignore_index=True).set_index("combination_id")
        for combination, row in max_t_all.iterrows():
            mask = declared["combination_id"].eq(str(combination))
            declared.loc[mask, "analysis_status"] = "supported"
            declared.loc[mask, "pbo_included"] = True
            declared.loc[mask, "westfall_young_statistic"] = float(
                row["westfall_young_statistic"]
            )
            declared.loc[mask, "westfall_young_pvalue"] = float(
                row["westfall_young_pvalue"]
            )
            declared.loc[mask, "westfall_young_method"] = str(
                row["westfall_young_method"]
            )
    duplicate_mask = (
        declared["functional_canonical_combination_id"].astype(str)
        != declared["combination_id"].astype(str)
    ) & declared["analysis_status"].astype(str).str.startswith("supported")
    declared.loc[duplicate_mask, "analysis_status"] = "supported_functional_duplicate"
    declared_pvalues = np.ones(EXPECTED_COMBINATION_COUNT, dtype=float)
    estimable_mask = declared["combination_id"].isin(individually_supported)
    declared_pvalues[estimable_mask.to_numpy()] = pd.to_numeric(
        declared.loc[estimable_mask, "cluster_pvalue_one_sided"], errors="raise"
    ).to_numpy(dtype=float)
    declared_bh = benjamini_hochberg(declared_pvalues)
    declared_holm = holm_adjust(declared_pvalues)
    declared.loc[estimable_mask, "bh_declared_290_pvalue"] = declared_bh[
        estimable_mask.to_numpy()
    ]
    declared.loc[estimable_mask, "holm_declared_290_pvalue"] = declared_holm[
        estimable_mask.to_numpy()
    ]
    declared.loc[estimable_mask, "benjamini_hochberg_pvalue"] = declared.loc[
        estimable_mask, "bh_declared_290_pvalue"
    ]
    declared.loc[estimable_mask, "holm_pvalue"] = declared.loc[
        estimable_mask, "holm_declared_290_pvalue"
    ]
    declared["declared_correction_status"] = np.where(
        estimable_mask, "estimable_in_declared_290_family", "not_estimable"
    )

    unique_ids = sorted(set(global_mapping.values()))
    unique_raw = np.ones(len(unique_ids), dtype=float)
    unique_estimable: dict[str, str] = {}
    for position, canonical in enumerate(unique_ids):
        members = sorted(
            combination
            for combination, representative in global_mapping.items()
            if representative == canonical and combination in individually_supported
        )
        if members:
            chosen = members[0]
            unique_raw[position] = float(cluster_tests.loc[chosen, "pvalue_one_sided"])
            unique_estimable[canonical] = chosen
    unique_bh = benjamini_hochberg(unique_raw)
    unique_holm = holm_adjust(unique_raw)
    declared["unique_correction_status"] = "not_estimable_global_group"
    for position, canonical in enumerate(unique_ids):
        chosen = unique_estimable.get(canonical)
        if chosen is None:
            continue
        members = declared["global_functional_canonical_combination_id"].eq(canonical)
        declared.loc[members, "bh_functionally_unique_pvalue"] = float(
            unique_bh[position]
        )
        declared.loc[members, "holm_functionally_unique_pvalue"] = float(
            unique_holm[position]
        )
        declared.loc[members, "unique_correction_status"] = np.where(
            declared.loc[members, "combination_id"].eq(chosen),
            "estimable_global_representative",
            "estimable_via_global_representative",
        )
    declared["declared_tests"] = EXPECTED_COMBINATION_COUNT
    declared["eligible_tests"] = len(semantically_eligible)
    declared["functionally_unique_tests"] = globally_unique_tests
    pbo_frame = pd.DataFrame(pbo_rows)
    pbo_frame["declared_tests"] = EXPECTED_COMBINATION_COUNT
    pbo_frame["eligible_tests"] = len(semantically_eligible)
    pbo_frame["functionally_unique_tests"] = globally_unique_tests
    worst = pbo_frame.sort_values(["pbo", "entry_spec_id"], ascending=[False, True]).iloc[0]
    payload = {
        "pbo": float(worst["pbo"]),
        "entry_spec_id": str(worst["entry_spec_id"]),
        "matrix_rows": int(pbo_frame["matrix_rows"].sum()),
        "declared_tests": EXPECTED_COMBINATION_COUNT,
        "eligible_tests": len(semantically_eligible),
        "functionally_unique_tests": globally_unique_tests,
    }
    return declared, pbo_frame, payload


def _replace_nonfinite_with_status(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    unsupported = pd.Series(False, index=result.index, dtype=bool)
    for column in result.select_dtypes(include=[np.number]).columns:
        values = pd.to_numeric(result[column], errors="coerce")
        invalid = ~np.isfinite(values.to_numpy(dtype=float))
        if not invalid.any():
            continue
        unsupported |= invalid
        result[column] = result[column].astype(object)
        result.loc[invalid, column] = "not_estimable"
    if "analysis_status" not in result:
        result["analysis_status"] = np.where(
            unsupported, "not_estimable", "supported"
        )
    return result


def build_statistical_outputs(
    opportunities: pd.DataFrame,
    coverage: pd.DataFrame,
    manifest: pd.DataFrame,
    *,
    bootstrap_samples: int,
) -> dict[str, pd.DataFrame | dict[str, Any]]:
    ledger = _event_ledger(opportunities)
    development = _selection_ledger(ledger)
    summary = metrics_by_combination(ledger)
    cuts = metric_cuts(ledger)
    summary["evidence_role"] = "all_periods_diagnostic"
    cuts["evidence_role"] = "all_periods_diagnostic"
    development_zero = metrics_by_combination(
        development, costs_bps_per_side=(0,)
    )
    cluster_summary, cluster_samples = cluster_bootstrap_confidence_intervals(
        development,
        bootstrap_samples=bootstrap_samples,
        seed=20260721,
    )
    cluster_numeric = cluster_samples.select_dtypes(include=[np.number])
    cluster_samples = cluster_samples.loc[
        np.isfinite(cluster_numeric.to_numpy(dtype=float)).all(axis=1)
    ].reset_index(drop=True)
    if cluster_samples.empty:
        raise ValueError("cluster bootstrap produced no wholly finite samples")
    entry_ids = manifest["entry_spec_id"].drop_duplicates().astype(str).tolist()
    exit_ids = manifest["exit_spec_id"].drop_duplicates().astype(str).tolist()
    paired_exit = _paired_exit_rows(
        ledger,
        entry_ids=entry_ids,
        exit_ids=exit_ids,
    )
    paired_entry = _paired_entry_rows(
        ledger,
        coverage,
        manifest,
        entry_ids=entry_ids,
        exit_ids=exit_ids,
    )
    duplicate_trade_columns = [
        column
        for column in (
            "symbol",
            "period",
            "selection_date",
            "entry_signal_date",
            "entry_date",
            "exit_date",
            "status",
            "gross_return",
            "holding_sessions",
        )
        if column in opportunities
    ]
    duplicate_result_columns = [
        column
        for column in REQUIRED_OBJECTIVES
        if column in development_zero
    ]
    functional = detect_functional_duplicates(
        manifest,
        opportunities,
        development_zero,
        spec_columns=("entry_spec_json", "exit_spec_json"),
        trade_columns=duplicate_trade_columns,
        result_columns=duplicate_result_columns,
    )
    global_mapping = _global_functional_mapping(
        functional, manifest["combination_id"].astype(str).tolist()
    )
    functional["global_functional_canonical_combination_id"] = functional[
        "combination_id"
    ].astype(str).map(global_mapping)
    functional["globally_functionally_unique"] = (
        functional["combination_id"].astype(str)
        == functional["global_functional_canonical_combination_id"]
    )
    bootstrap_rank = cluster_summary.loc[
        cluster_summary["method"].astype(str).eq("hierarchical_year_symbol")
        & cluster_summary["metric"].astype(str).eq("mean_return"),
        ["combination_id", "ci_low95", "ci_high95"],
    ].rename(
        columns={
            "ci_low95": "bootstrap_mean_return_ci_low95",
            "ci_high95": "bootstrap_mean_return_ci_high95",
        }
    )
    bootstrap_rank["bootstrap_mean_return_ci_width95"] = (
        bootstrap_rank["bootstrap_mean_return_ci_high95"]
        - bootstrap_rank["bootstrap_mean_return_ci_low95"]
    )
    development_zero = development_zero.merge(
        bootstrap_rank,
        on="combination_id",
        how="left",
        validate="one_to_one",
    )
    duplicate_flags = (
        functional.assign(
            _functionally_duplicated=functional["functionally_duplicated"].map(_as_bool)
        )
        .groupby("combination_id", as_index=False)["_functionally_duplicated"]
        .any()
        .rename(columns={"_functionally_duplicated": "functionally_duplicated"})
    )
    development_zero = development_zero.merge(
        duplicate_flags,
        on="combination_id",
        how="left",
        validate="one_to_one",
    )
    ranked = rank_combinations(development_zero)
    ranked["evidence_role"] = "period_A_development_selection"
    winners = objective_winners(ranked)
    winners["evidence_role"] = "period_A_development_selection"
    multiple, pbo, pbo_payload = _multiple_testing(
        development,
        manifest,
        functional,
        bootstrap_samples=bootstrap_samples,
    )
    multiple["evidence_role"] = "period_A_development_selection"
    pbo["evidence_role"] = "period_A_development_selection"
    paired_entry["evidence_role"] = "all_periods_diagnostic"
    paired_exit["evidence_role"] = "all_periods_diagnostic"
    cluster_summary["evidence_role"] = "period_A_development_selection"
    cluster_samples["evidence_role"] = "period_A_development_selection"
    eligible_ranked = ranked.loc[ranked["selection_eligible"].astype(bool)].copy()
    if eligible_ranked.empty:
        raise ValueError("no semantically supported combination can be ranked")
    raw_outputs = {
        "summary": summary,
        "period": cuts.loc[cuts["cut"].eq("period")].reset_index(drop=True),
        "year": cuts.loc[cuts["cut"].eq("year")].reset_index(drop=True),
        "decade": cuts.loc[cuts["cut"].eq("decade")].reset_index(drop=True),
        "country": cuts.loc[cuts["cut"].eq("country")].reset_index(drop=True),
        "market": cuts.loc[cuts["cut"].eq("market")].reset_index(drop=True),
        "currency": cuts.loc[cuts["cut"].eq("currency")].reset_index(drop=True),
        "leave_out": leave_one_out_audit(ledger).assign(
            evidence_role="all_periods_diagnostic"
        ),
        "censoring": censoring_audit(ledger).assign(
            evidence_role="all_periods_diagnostic"
        ),
    }
    serializable = {
        key: _replace_nonfinite_with_status(value) for key, value in raw_outputs.items()
    }
    return {
        "summary": serializable["summary"],
        "period": serializable["period"],
        "year": serializable["year"],
        "decade": serializable["decade"],
        "country": serializable["country"],
        "market": serializable["market"],
        "currency": serializable["currency"],
        "paired_entry": paired_entry,
        "paired_exit": paired_exit,
        "cluster_summary": _replace_nonfinite_with_status(cluster_summary),
        "cluster_samples": cluster_samples,
        "multiple_testing": multiple,
        "pbo": pbo,
        "pbo_payload": pbo_payload,
        "leave_out": serializable["leave_out"],
        "concentration": concentration_statistics(ledger).assign(
            evidence_role="all_periods_diagnostic"
        ),
        "pareto": eligible_ranked.loc[eligible_ranked["pareto_rank"].eq(1)].reset_index(drop=True),
        "ideal": eligible_ranked.sort_values(
            ["ideal_distance", "combination_id"], kind="stable"
        ).reset_index(drop=True),
        "balanced": eligible_ranked.sort_values(
            ["balanced_score", "combination_id"], ascending=[False, True], kind="stable"
        ).reset_index(drop=True),
        "top_objectives": winners,
        "classifications": _replace_nonfinite_with_status(ranked),
        "censoring": serializable["censoring"],
        "survival": survival_incidence_table(ledger).assign(
            evidence_role="all_periods_diagnostic"
        ),
        "functional_duplicates": functional,
    }


def _semantic_audit(
    manifest: pd.DataFrame,
    reconciliation: pd.DataFrame,
) -> pd.DataFrame:
    aggregate = reconciliation.loc[reconciliation["period"].eq("ALL")].drop(
        columns=["entry_spec_id", "exit_spec_id", "period", "unsupported_statuses_json"]
    )
    columns = [
        "combination_id",
        "entry_spec_id",
        "exit_spec_id",
        "corrected_track_applicability",
        "corrected_track_reason",
        "entry_spec_json",
        "exit_spec_json",
    ]
    result = manifest[columns].merge(
        aggregate, on="combination_id", how="left", validate="one_to_one"
    )
    result["semantic_audit_preserved"] = True
    result["ranking_eligible"] = result["corrected_track_applicability"].ne(
        "not_applicable"
    )
    return result


def _write_partitioned_csv(root: Path, opportunities: pd.DataFrame) -> None:
    root.mkdir(parents=True, exist_ok=False)
    for period in PERIOD_NAMES:
        partition = root / f"period={period}"
        partition.mkdir()
        opportunities.loc[opportunities["period"].astype(str).eq(period)].to_csv(
            partition / "part-00000.csv.gz",
            index=False,
            compression={"method": "gzip", "mtime": 0},
        )


def _assert_event_outputs_finite(outputs: Mapping[str, pd.DataFrame | dict[str, Any]]) -> None:
    for name, value in outputs.items():
        if name in {"pbo", "functional_duplicates"} or not isinstance(value, pd.DataFrame):
            continue
        numeric = value.select_dtypes(include=[np.number])
        if numeric.empty:
            continue
        if numeric.isna().any().any() or not np.isfinite(numeric.to_numpy(dtype=float)).all():
            raise ValueError(f"statistical output {name} contains non-finite values")


def _report(
    summary: Mapping[str, Any],
    pbo: Mapping[str, Any],
    statistics: Mapping[str, pd.DataFrame | dict[str, Any]],
) -> str:
    combination = statistics["summary"]
    period = statistics["period"]
    yearly = statistics["year"]
    country = statistics["country"]
    market = statistics["market"]
    paired_entry = statistics["paired_entry"]
    paired_exit = statistics["paired_exit"]
    clusters = statistics["cluster_summary"]
    multiple = statistics["multiple_testing"]
    pareto = statistics["pareto"]
    ideal = statistics["ideal"]
    balanced = statistics["balanced"]
    objectives = statistics["top_objectives"]
    censoring = statistics["censoring"]
    concentration = statistics["concentration"]
    leave_out = statistics["leave_out"]
    frames = (
        combination,
        period,
        yearly,
        country,
        market,
        paired_entry,
        paired_exit,
        clusters,
        multiple,
        pareto,
        ideal,
        balanced,
        objectives,
        censoring,
        concentration,
        leave_out,
    )
    if not all(isinstance(frame, pd.DataFrame) for frame in frames):
        raise TypeError("report statistics must be data frames")

    def best_estimable(
        frame: pd.DataFrame, column: str, *, ascending: bool = False
    ) -> pd.Series:
        estimable = frame.copy()
        estimable["_report_value"] = pd.to_numeric(
            estimable[column], errors="coerce"
        )
        estimable = estimable.dropna(subset=["_report_value"])
        if estimable.empty:
            raise ValueError(f"report has no estimable {column}")
        return estimable.sort_values(
            "_report_value", ascending=ascending, kind="stable"
        ).iloc[0]

    zero = combination.loc[combination["cost_bps_per_side"].eq(0)]
    high_cost = combination.loc[combination["cost_bps_per_side"].eq(max(COSTS_BPS_PER_SIDE))]
    best_mean = best_estimable(zero, "mean_return")
    best_cost = best_estimable(high_cost, "mean_return")
    period_a = period.loc[period["cut_value"].astype(str).eq("A")]
    best_period = best_estimable(period_a, "mean_return")
    best_year = best_estimable(yearly, "mean_return")
    best_country = best_estimable(country, "mean_return")
    best_market = best_estimable(market, "mean_return")
    paired_entry_return = paired_entry.loc[
        paired_entry["metric"].astype(str).eq("return")
    ]
    if paired_entry_return.empty:
        paired_entry_answer = (
            "Ninguna: hubo 0 comparaciones con pares causales completos entre entradas."
        )
    else:
        best_entry = best_estimable(paired_entry_return, "mean_delta")
        paired_entry_answer = (
            f"Para la salida `{best_entry['exit_spec_id']}`, "
            f"`{best_entry['challenger']}` frente a `{best_entry['baseline']}`: "
            f"{float(best_entry['mean_delta']):.8f} sobre {int(best_entry['pairs'])} pares."
        )
    paired_exit_return = paired_exit.loc[
        paired_exit["metric"].astype(str).eq("return")
    ]
    if paired_exit_return.empty:
        paired_exit_answer = (
            "Ninguna: hubo 0 comparaciones con pares causales completos entre salidas."
        )
    else:
        best_exit = best_estimable(paired_exit_return, "mean_delta")
        paired_exit_answer = (
            f"Para la entrada `{best_exit['entry_spec_id']}`, "
            f"`{best_exit['challenger']}` frente a `{best_exit['baseline']}`: "
            f"{float(best_exit['mean_delta']):.8f} sobre {int(best_exit['pairs'])} pares."
        )
    cluster_mean = clusters.loc[clusters["metric"].eq("mean_return")]
    best_cluster = best_estimable(cluster_mean, "estimate")
    best_declared = best_estimable(multiple, "bh_declared_290_pvalue", ascending=True)
    best_unique = best_estimable(
        multiple.drop_duplicates("global_functional_canonical_combination_id"),
        "bh_functionally_unique_pvalue",
        ascending=True,
    )
    ideal_row = ideal.iloc[0]
    balanced_row = balanced.iloc[0]
    mean_objective = objectives.loc[objectives["objective"].eq("mean_return")].iloc[0]
    speed_objective = objectives.loc[objectives["objective"].eq("event_speed")].iloc[0]
    highest_censor = censoring.sort_values("censoring_rate", ascending=False, kind="stable").iloc[0]
    highest_concentration = concentration.sort_values(
        "concentration_hhi", ascending=False, kind="stable"
    ).iloc[0]
    estimable_leave_out = leave_out.copy()
    estimable_leave_out["_change"] = pd.to_numeric(
        estimable_leave_out["change_from_baseline"], errors="coerce"
    )
    estimable_leave_out = estimable_leave_out.dropna(subset=["_change"])
    worst_leave_out = estimable_leave_out.sort_values("_change", kind="stable").iloc[0]
    pareto_ids = ", ".join(pareto["combination_id"].astype(str).head(5))
    if len(pareto) > 5:
        pareto_ids += ", ..."
    return f"""# Estudio de eventos de las 290 combinaciones

## Hechos

1. **[Q01] ¿Cuál es el contrato declarado?** Resultado: 290 combinaciones, 10 entradas y 29 salidas.
2. **[Q02] ¿Qué estrategia y fuentes congeladas se preservan?** Resultado: estrategia exacta `{summary['exact_strategy_candidate_id']}`, source lock `{summary['source_lock_sha256']}` y estrategia `{summary['exact_strategy_sha256']}`.
3. **[Q03] ¿Cuántos shards históricos se integraron?** Resultado: exactamente 10.
4. **[Q04] ¿Cuántos shards corregidos se integraron?** Resultado: exactamente 30.
5. **[Q05] ¿La réplica histórica respetó las tolerancias congeladas?** Resultado: sí, las 290 comparaciones pasaron.
6. **[Q06] ¿Cuántas oportunidades hay y cómo terminan?** Resultado: {int(summary['opportunity_count'])}; {int(summary['completed'])} observadas, {int(summary['censored'])} censuradas y {int(summary['failed_due_to_data'])} fallidas por datos.
7. **[Q07] ¿Cómo se reconcilia la financiación del portfolio antiguo?** Resultado: reconciliación informativa completa; {int(summary['financed_in_old_portfolio'])} financiadas y {int(summary['not_financed_in_old_portfolio'])} no financiadas, sin excluir ninguna oportunidad.
8. **[Q08] ¿Cómo se valoran FX y dividendos?** Resultado: FX exclusivamente desde `frozen_fx_rates.csv` `{summary['frozen_fx_rates_sha256']}` y cada pago de `dividend_payments_local_json` se convierte en su fecha causal.
9. **[Q09] ¿Reconciliaron todas las combinaciones?** Resultado: sí, las 290 en A, B, C y agregado.
10. **[Q10] ¿Qué combinación lidera sin costes en el diagnóstico combinado?** Resultado: `{best_mean['combination_id']}`, retorno medio {float(best_mean['mean_return']):.8f}; no selecciona.
11. **[Q11] ¿Qué combinación lidera con 200 puntos básicos por lado?** Resultado: `{best_cost['combination_id']}`, retorno medio {float(best_cost['mean_return']):.8f}; no selecciona.
12. **[Q12] ¿Cuál lidera el periodo A de desarrollo?** Resultado: `{best_period['combination_id']}`, retorno medio {float(best_period['mean_return']):.8f}.
13. **[Q13] ¿Qué líderes aparecen por año, país y mercado?** Resultado: año `{best_year['combination_id']}`/{best_year['cut_value']}; país `{best_country['combination_id']}`/{best_country['cut_value']}; mercado `{best_market['combination_id']}`/{best_market['cut_value']}.
14. **[Q14] ¿Qué muestran las entradas emparejadas?** Resultado: {paired_entry_answer} Se publican trigger probability, precio, retraso, retorno, MAE, duración y cobertura usando cohorte upstream.
15. **[Q15] ¿Qué muestran las salidas emparejadas?** Resultado: {paired_exit_answer} Se publican todas las parejas para retorno, pérdida, MAE, duración y retorno por sesión.

## Inferencias

16. **[Q16] ¿Qué combinación destaca en el bootstrap agrupado?** Resultado: `{best_cluster['combination_id']}`, método `{best_cluster['method']}`, estimación {float(best_cluster['estimate']):.8f}, IC [{float(best_cluster['ci_low95']):.8f}, {float(best_cluster['ci_high95']):.8f}].
17. **[Q17] ¿Cuál es el menor BH dentro de las 290 pruebas declaradas?** Resultado: `{best_declared['combination_id']}`, BH {float(best_declared['bh_declared_290_pvalue']):.8f} y Holm {float(best_declared['holm_declared_290_pvalue']):.8f}; las no estimables permanecen explícitas.
18. **[Q18] ¿Cuál es el menor BH entre reglas funcionalmente únicas?** Resultado: `{best_unique['global_functional_canonical_combination_id']}`, BH {float(best_unique['bh_functionally_unique_pvalue']):.8f} y Holm {float(best_unique['holm_functionally_unique_pvalue']):.8f}; hay {int(pbo['functionally_unique_tests'])} grupos derivados de la auditoría global.
19. **[Q19] ¿Qué indica CSCV/PBO?** Resultado: PBO {float(pbo['pbo']):.6f} para `{pbo['entry_spec_id']}` sobre {int(pbo['matrix_rows'])} filas; es un gate familiar, no el contador global de duplicados.
20. **[Q20] ¿Cuántas combinaciones forman el primer frente de Pareto?** Resultado: {len(pareto)}; IDs iniciales {pareto_ids}.
21. **[Q21] ¿Qué combinación queda más cerca del punto ideal?** Resultado: `{ideal_row['combination_id']}`, distancia {float(ideal_row['ideal_distance']):.8f}.
22. **[Q22] ¿Qué combinación equilibra mejor los pilares y objetivos?** Resultado: `{balanced_row['combination_id']}`, puntuación {float(balanced_row['balanced_score']):.8f}; retorno `{mean_objective['combination_id']}` y velocidad `{speed_objective['combination_id']}`.

## Limitaciones

23. **[Q23] ¿Qué muestra supervivencia y censura?** Resultado: `survival_analysis_by_combination.csv`; mayor censura en `{highest_censor['combination_id']}` con {float(highest_censor['censoring_rate']):.8f}, sin convertir censura en retorno.
24. **[Q24] ¿Qué fragilidad muestran concentración y leave-out?** Resultado: HHI máximo `{highest_concentration['combination_id']}`={float(highest_concentration['concentration_hhi']):.8f}; peor omisión `{worst_leave_out['combination_id']}` `{worst_leave_out['omission']}`=`{worst_leave_out['omitted_value']}`, delta {float(worst_leave_out['change_from_baseline']):.8f}.
25. **[Q25] ¿Qué clasificaciones y gates limitan la conclusión?** Resultado: clasificaciones `{json.dumps(summary['classification_counts'], sort_keys=True)}`. B/C son diagnóstico, no selección; {int(summary['semantic_not_applicable_count'])} reglas no aplicables, {int(summary['fx_currency_unknown_count'])} monedas desconocidas y {int(summary['fx_dividend_detail_missing_count'])} dividendos sin FX causal completo. Gates: source lock, réplica, esquema, causalidad, reconciliación, multiplicidad y clasificación explícita de no estimables. No hubo exclusiones de capital ni portfolio nuevo.
"""


def _artifact_manifest(root: Path) -> dict[str, Any]:
    files: dict[str, dict[str, object]] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == FINAL_MANIFEST_NAME:
            continue
        relative = path.relative_to(root).as_posix()
        files[relative] = {"bytes": path.stat().st_size, "sha256": _sha256(path)}
    return {
        "schema_version": 1,
        "hash_algorithm": "sha256",
        "self_excluded": FINAL_MANIFEST_NAME,
        "implementation_commit": os.environ.get("GITHUB_SHA", "unknown"),
        "files": files,
    }


def merge_event_study(
    *,
    contract_root: Path,
    historical_shards_root: Path,
    corrected_shards_root: Path,
    prior_audit_root: Path,
    exact_strategy_root: Path,
    output_root: Path,
    fx_rates: pd.DataFrame | None,
    fx_rates_source_path: Path | None = None,
    source_lock_path: Path | None = None,
    bootstrap_samples: int = 2000,
    enforce_execution_policy: bool = True,
) -> dict[str, Any]:
    if enforce_execution_policy:
        require_github_actions_or_explicit_local_permission(
            "stock protocol 290 final event-study merge"
        )
    if bootstrap_samples < 1:
        raise ValueError("bootstrap_samples must be positive")
    pd.options.mode.copy_on_write = True
    if fx_rates is None:
        raise ValueError("--fx-rates is required; live FX download is prohibited")
    output = Path(output_root)
    if output.exists() and any(output.iterdir()):
        raise ValueError("output root must be empty")
    output.mkdir(parents=True, exist_ok=True)
    contract_root = Path(contract_root)
    source_lock_path = source_lock_path or contract_root / SOURCE_LOCK_NAME
    exact_strategy, prior_opportunities, _ = _load_provenance_inputs(
        prior_audit_root=Path(prior_audit_root),
        exact_strategy_root=Path(exact_strategy_root),
        source_lock_path=Path(source_lock_path),
    )
    manifest, _, _ = _contract(contract_root)
    historical, historical_audit = merge_historical_shards(
        Path(historical_shards_root), manifest
    )
    (
        opportunities,
        coverage,
        shard_reconciliation,
        corrected_audits,
        fx_audit,
        financing_reconciliation,
        technical_input_rows,
        technical_duplicates_removed,
    ) = stream_corrected_shards(
        Path(corrected_shards_root),
        manifest,
        fx_rates=fx_rates,
        exact_strategy=exact_strategy,
        prior_opportunities=prior_opportunities,
        output_root=output,
    )
    corrected_manifest_hashes = {
        str(audit.get("manifest_sha256", "")) for audit in corrected_audits
    }
    historical_manifest_hashes = set(historical_audit["manifest_sha256_values"])
    if corrected_manifest_hashes != historical_manifest_hashes:
        raise ValueError("historical and corrected shards use different manifest hashes")
    provenance: dict[str, str] = {}
    for field in ("dataset_hash", "policy_hash", "source_snapshot_sha256"):
        values = {str(audit.get(field, "")) for audit in corrected_audits}
        if len(values) != 1:
            raise ValueError(f"corrected shards do not share one {field}")
        value = next(iter(values))
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError(f"corrected shard {field} is not a complete sha256")
        historical_values = {
            str(audit.get(field, "")) for audit in historical_audit["shards"]
        }
        if historical_values != {value}:
            raise ValueError(f"historical and corrected shards use different {field}")
        provenance[field] = value
    _assert_dates_at_cutoff(opportunities, "merged opportunities")
    for column in (
        "capital_rejected",
        "portfolio_simulated",
        "sizing_applied",
        "overlap_discarded",
        "new_oos_claimed",
        "optimization_performed_on_opened_data",
    ):
        if column in opportunities and opportunities[column].map(_as_bool).any():
            raise ValueError(f"merged opportunities violate invariant {column}=false")
    reconciliation = reconcile_all_combinations(opportunities, manifest)
    semantic = _semantic_audit(manifest, reconciliation)
    statistics = build_statistical_outputs(
        opportunities,
        coverage,
        manifest,
        bootstrap_samples=bootstrap_samples,
    )
    _assert_event_outputs_finite(statistics)

    historical.to_csv(output / HISTORICAL_RESULTS_NAME, index=False)
    _json(output / HISTORICAL_AUDIT_NAME, historical_audit)
    for name in (COMBINATION_MANIFEST_NAME, ENTRY_SPECS_NAME, EXIT_SPECS_NAME):
        shutil.copy2(contract_root / name, output / name)
    shutil.copy2(Path(source_lock_path), output / SOURCE_LOCK_NAME)
    shutil.copy2(
        _find_unique(Path(exact_strategy_root), EXACT_STRATEGY_NAME),
        output / EXACT_STRATEGY_NAME,
    )
    if fx_rates_source_path is not None:
        shutil.copy2(Path(fx_rates_source_path), output / FROZEN_FX_RATES_NAME)
    else:
        frozen_fx_rates = fx_rates.copy()
        frozen_fx_rates["date"] = pd.to_datetime(
            frozen_fx_rates["date"], errors="raise"
        ).dt.strftime("%Y-%m-%d")
        frozen_fx_rates.sort_values(["currency", "date"], kind="stable").to_csv(
            output / FROZEN_FX_RATES_NAME, index=False
        )
    csv_rows = _parquet_to_gzip_csv(
        output / OPPORTUNITIES_PARQUET,
        output / OPPORTUNITIES_CSV_GZIP,
    )
    if csv_rows != len(opportunities):
        raise ValueError("streamed opportunity CSV row count differs")
    parts_root = output / OPPORTUNITIES_PARTS
    parts_root.mkdir(parents=True, exist_ok=False)
    partition_rows = 0
    for period in PERIOD_NAMES:
        partition = parts_root / f"period={period}"
        partition.mkdir()
        partition_rows += _parquet_to_gzip_csv(
            output / OPPORTUNITIES_PARQUET,
            partition / "part-00000.csv.gz",
            period=period,
        )
    if partition_rows != len(opportunities):
        raise ValueError("partitioned opportunity CSV row count differs")
    coverage.to_parquet(output / COVERAGE_PARQUET, index=False)
    coverage.to_csv(
        output / COVERAGE_CSV_GZIP,
        index=False,
        compression={"method": "gzip", "mtime": 0},
    )
    reconciliation.to_csv(output / RECONCILIATION_NAME, index=False)
    semantic.to_csv(output / SEMANTIC_AUDIT_NAME, index=False)
    functional_duplicates = statistics["functional_duplicates"]
    assert isinstance(functional_duplicates, pd.DataFrame)
    functional_duplicates.to_csv(output / FUNCTIONAL_DUPLICATES_NAME, index=False)
    fx_audit.to_csv(output / FX_AUDIT_NAME, index=False)
    financing_reconciliation.to_csv(
        output / PRIOR_AUDIT_RECONCILIATION_NAME, index=False
    )
    for key, filename in STATISTIC_FILES.items():
        value = statistics[key]
        if isinstance(value, pd.DataFrame):
            _write_frame(output / filename, value)
        else:
            _json(output / filename, value)

    aggregate = reconciliation.loc[reconciliation["period"].eq("ALL")]
    pbo_payload = statistics["pbo_payload"]
    assert isinstance(pbo_payload, dict)
    classifications = statistics["classifications"]
    assert isinstance(classifications, pd.DataFrame)
    summary: dict[str, Any] = {
        "schema_version": 1,
        "contract": "290-10-29",
        "combination_count": EXPECTED_COMBINATION_COUNT,
        "entry_spec_count": EXPECTED_ENTRY_SPEC_COUNT,
        "exit_spec_count": EXPECTED_EXIT_SPEC_COUNT,
        "historical_shard_count": EXPECTED_HISTORICAL_SHARDS,
        "corrected_shard_count": EXPECTED_CORRECTED_SHARDS,
        "opportunity_count": int(aggregate["opportunities"].sum()),
        "completed": int(aggregate["completed"].sum()),
        "censored": int(aggregate["censored"].sum()),
        "failed_due_to_data": int(aggregate["failed_due_to_data"].sum()),
        "technical_input_rows": technical_input_rows,
        "technical_duplicates_removed": technical_duplicates_removed,
        "all_combinations_reconciled": bool(reconciliation["reconciled"].all()),
        "historical_replication_passed": True,
        "semantic_audit_preserved": True,
        "functional_duplicates_preserved": True,
        "semantic_not_applicable_count": int(
            semantic["corrected_track_applicability"].eq("not_applicable").sum()
        ),
        "functional_duplicate_rows": int(
            functional_duplicates["functionally_duplicated"].map(_as_bool).sum()
        ),
        "fx_currency_unknown_count": int(
            opportunities["currency_unknown"].map(_as_bool).sum()
        ),
        "fx_dividend_detail_missing_count": int(
            opportunities["fx_merge_status"]
            .astype(str)
            .str.startswith("missing_dividend_payment")
            .sum()
        ),
        "exact_strategy_candidate_id": str(exact_strategy["candidate_id"]),
        "prior_audit_financing_reconciled": bool(
            financing_reconciliation["reconciled"].map(_as_bool).all()
        ),
        "financing_information_only": True,
        "financed_in_old_portfolio": int(
            financing_reconciliation["financed_in_old_portfolio"].map(_as_bool).sum()
        ),
        "not_financed_in_old_portfolio": int(
            (~financing_reconciliation["financed_in_old_portfolio"].map(_as_bool)).sum()
        ),
        "declared_tests": int(pbo_payload["declared_tests"]),
        "eligible_tests": int(pbo_payload["eligible_tests"]),
        "functionally_unique_tests": int(
            pbo_payload["functionally_unique_tests"]
        ),
        "classification_counts": {
            str(key): int(value)
            for key, value in classifications["classification"].value_counts().items()
        },
        "new_oos_claimed": False,
        "optimization_performed_on_opened_data": False,
        "validation_used_for_selection": False,
        "no_portfolio_simulation": True,
        "no_capital_exclusions": True,
        "cutoff": CUTOFF.date().isoformat(),
        "selection_period": "A",
        "diagnostic_periods": ["B", "C"],
        "shard_reconciliation_rows": len(shard_reconciliation),
        "manifest_sha256": next(iter(corrected_manifest_hashes)),
        "source_lock_sha256": _sha256(output / SOURCE_LOCK_NAME),
        "exact_strategy_sha256": _sha256(output / EXACT_STRATEGY_NAME),
        "frozen_fx_rates_sha256": _sha256(output / FROZEN_FX_RATES_NAME),
        **provenance,
    }
    _json(output / AUDIT_SUMMARY_NAME, summary)
    (output / FINAL_REPORT_NAME).write_text(
        _report(summary, pbo_payload, statistics), encoding="utf-8"
    )
    _json(output / FINAL_MANIFEST_NAME, _artifact_manifest(output))
    print(json.dumps(summary, sort_keys=True))
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract-root", type=Path, required=True)
    parser.add_argument("--historical-shards-root", type=Path, required=True)
    parser.add_argument("--corrected-shards-root", type=Path, required=True)
    parser.add_argument("--prior-audit-root", type=Path, required=True)
    parser.add_argument("--exact-strategy-root", type=Path, required=True)
    parser.add_argument("--source-lock", type=Path)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--fx-rates", type=Path, required=True)
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    return parser


def main() -> int:
    args = _parser().parse_args()
    rates = pd.read_csv(args.fx_rates)
    merge_event_study(
        contract_root=args.contract_root,
        historical_shards_root=args.historical_shards_root,
        corrected_shards_root=args.corrected_shards_root,
        prior_audit_root=args.prior_audit_root,
        exact_strategy_root=args.exact_strategy_root,
        output_root=args.output_root,
        fx_rates=rates,
        fx_rates_source_path=args.fx_rates,
        source_lock_path=args.source_lock,
        bootstrap_samples=args.bootstrap_samples,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
