"""Run one artifact-derived historical 29-exit replication shard."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from aurora.core.execution_policy import (
    require_github_actions_or_explicit_local_permission,
)
from aurora.research.stock_protocol.event_study_290_manifest import (
    COMBINATION_MANIFEST_NAME,
    EXPECTED_COMBINATION_COUNT,
    EXPECTED_ENTRY_SPEC_COUNT,
    EXPECTED_EXIT_SPEC_COUNT,
)
from aurora.research.stock_protocol.scientific_evaluation import (
    evaluate_development_walk_forward_many_from_pack,
)


OUTPUT_NAME = "historical_290_replication_results.csv"
AUDIT_NAME = "historical_290_replication_audit.json"
DEVELOPMENT_START = "1995-01-01"
DEVELOPMENT_END = "2015-12-31"
METRIC_TOLERANCES: dict[str, float] = {
    "cagr": 0.0002,
    "sharpe": 0.005,
    "max_drawdown": 0.0002,
    "trades": 0.0,
}
HASH_COLUMNS = ("dataset_hash", "policy_hash", "source_snapshot_sha256")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True, default=str)
        + "\n",
        encoding="utf-8",
    )


def _resolve_pack_root(root: Path) -> Path:
    candidates = [Path(root), Path(root) / "pre2021_full_daily_pack"]
    candidates.extend(path.parent for path in Path(root).rglob("trading_calendar.parquet"))
    for candidate in candidates:
        if (
            (candidate / "trading_calendar.parquet").is_file()
            and (candidate / "shard-000.parquet").is_file()
            and (candidate / "shard-031.parquet").is_file()
        ):
            return candidate
    raise FileNotFoundError("could not resolve the immutable 32-shard price pack")


def _validate_manifest_contract(manifest: pd.DataFrame) -> None:
    if len(manifest) != EXPECTED_COMBINATION_COUNT:
        raise ValueError("290 manifest does not contain exactly 290 combinations")
    combination_ids = manifest["combination_id"].astype(str).str.strip()
    if combination_ids.eq("").any() or combination_ids.nunique() != EXPECTED_COMBINATION_COUNT:
        raise ValueError("290 manifest must contain exactly 290 unique combination IDs")
    for column in HASH_COLUMNS:
        values = manifest[column].astype(str).str.strip().str.lower()
        valid = values.str.fullmatch(r"[0-9a-f]{64}")
        if not valid.all() or values.nunique() != 1:
            raise ValueError(f"290 manifest {column} must be one uniform sha256")


def load_entry_manifest_rows(
    manifest_root: Path,
    entry_index: int,
) -> tuple[Path, pd.DataFrame]:
    """Load one complete 29-row entry axis from the derived manifest."""

    if entry_index not in range(EXPECTED_ENTRY_SPEC_COUNT):
        raise ValueError("entry_index must be between 0 and 9")
    manifest_path = Path(manifest_root) / COMBINATION_MANIFEST_NAME
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    manifest = pd.read_csv(manifest_path, dtype=str, keep_default_na=False)
    required = {
        "combination_id",
        "candidate_id",
        "entry_spec_id",
        "exit_spec_id",
        "spec_json",
        "dataset_hash",
        "policy_hash",
        "source_snapshot_sha256",
    }
    missing = required - set(manifest.columns)
    if missing:
        raise ValueError(f"290 manifest is missing columns: {sorted(missing)}")
    _validate_manifest_contract(manifest)
    entry_ids = manifest["entry_spec_id"].drop_duplicates().tolist()
    if len(entry_ids) != EXPECTED_ENTRY_SPEC_COUNT:
        raise ValueError("290 manifest does not contain exactly 10 entry specs")
    rows = manifest.loc[manifest["entry_spec_id"].eq(entry_ids[entry_index])].copy()
    if (
        len(rows) != EXPECTED_EXIT_SPEC_COUNT
        or rows["exit_spec_id"].nunique() != EXPECTED_EXIT_SPEC_COUNT
    ):
        raise ValueError("entry shard does not contain exactly 29 distinct exit specs")
    if not rows["combination_id"].equals(rows["candidate_id"]):
        raise ValueError("derived combination identity differs from source candidate identity")
    return manifest_path, rows.reset_index(drop=True)


def _numeric(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if np.isfinite(result) else None


def reconcile_historical_rows(
    source_rows: pd.DataFrame,
    evaluations: tuple[object, ...],
) -> pd.DataFrame:
    """Compare the 29 observations using the frozen reproduction tolerances."""

    if len(source_rows) != EXPECTED_EXIT_SPEC_COUNT or len(evaluations) != len(source_rows):
        raise ValueError("historical reconciliation requires exactly 29 paired results")
    rows: list[dict[str, object]] = []
    for (_, source), cross_validated in zip(
        source_rows.iterrows(), evaluations, strict=True
    ):
        result = cross_validated.result
        observed = result.result_row()
        row: dict[str, object] = {
            "entry_spec_id": source["entry_spec_id"],
            "exit_spec_id": source["exit_spec_id"],
            "combination_id": source["combination_id"],
            "source_status": source.get("status", ""),
            "observed_status": result.status,
            "status_match": str(source.get("status", "")) == str(result.status),
            "candidate_id_match": str(result.candidate_id) == str(source["combination_id"]),
            "walk_forward_folds": len(cross_validated.folds),
            "locked_opened": bool(result.locked_opened),
            "data_end": result.data_end,
        }
        comparisons: list[bool] = []
        for metric, tolerance in METRIC_TOLERANCES.items():
            expected_value = _numeric(source.get(metric))
            observed_value = _numeric(observed.get(metric))
            difference = (
                observed_value - expected_value
                if expected_value is not None and observed_value is not None
                else np.nan
            )
            available = expected_value is not None and observed_value is not None
            passed = bool(available and abs(float(difference)) <= tolerance)
            row[f"{metric}_expected"] = expected_value
            row[f"{metric}_observed"] = observed_value
            row[f"{metric}_difference"] = difference
            row[f"{metric}_tolerance"] = tolerance
            row[f"{metric}_available"] = available
            row[f"{metric}_passed"] = passed
            comparisons.append(passed)
        row["replication_passed"] = bool(
            row["candidate_id_match"]
            and row["status_match"]
            and result.status == "evaluated"
            and not result.locked_opened
            and all(comparisons)
        )
        rows.append(row)
    return pd.DataFrame(rows)


def run_historical_shard(
    *,
    manifest_root: Path,
    pack_root: Path,
    entry_index: int,
    output_root: Path,
) -> dict[str, object]:
    require_github_actions_or_explicit_local_permission(
        "stock protocol 290 historical replication shard"
    )
    manifest_path, source_rows = load_entry_manifest_rows(manifest_root, entry_index)
    specs: list[dict[str, Any]] = []
    for raw in source_rows["spec_json"]:
        spec = json.loads(raw)
        if not isinstance(spec, dict):
            raise ValueError("manifest spec_json must contain an object")
        specs.append(spec)
    evaluations = evaluate_development_walk_forward_many_from_pack(
        _resolve_pack_root(Path(pack_root)),
        specs,
        start=DEVELOPMENT_START,
        end=DEVELOPMENT_END,
        mode="expanding",
    )
    reconciliation = reconcile_historical_rows(source_rows, evaluations)
    reconciliation.insert(0, "entry_index", entry_index)
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    result_path = output_root / OUTPUT_NAME
    reconciliation.to_csv(result_path, index=False)
    audit: dict[str, object] = {
        "schema_version": 1,
        "entry_index": entry_index,
        "entry_spec_id": str(source_rows.iloc[0]["entry_spec_id"]),
        "combination_count": len(reconciliation),
        "replication_passed_count": int(reconciliation["replication_passed"].sum()),
        "replication_failed_count": int((~reconciliation["replication_passed"]).sum()),
        "all_replications_passed": bool(reconciliation["replication_passed"].all()),
        "manifest_path": str(manifest_path),
        "manifest_sha256": _sha256(manifest_path),
        "source_snapshot_sha256": str(source_rows.iloc[0]["source_snapshot_sha256"]),
        "dataset_hash": str(source_rows.iloc[0]["dataset_hash"]),
        "policy_hash": str(source_rows.iloc[0]["policy_hash"]),
        "development_start": DEVELOPMENT_START,
        "development_end": DEVELOPMENT_END,
        "walk_forward_mode": "expanding",
        "metric_tolerances": METRIC_TOLERANCES,
        "locked_opened": False,
        "new_oos_claimed": False,
        "optimization_performed_on_opened_data": False,
        "result_path": str(result_path),
        "result_sha256": _sha256(result_path),
    }
    _write_json(output_root / AUDIT_NAME, audit)
    print(json.dumps(audit, sort_keys=True))
    return audit


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest-root", "--contract-root", dest="manifest_root", type=Path, required=True
    )
    parser.add_argument("--pack-root", type=Path, required=True)
    parser.add_argument("--entry-index", type=int, choices=range(10), required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser


def main() -> int:
    run_historical_shard(**vars(_parser().parse_args()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
