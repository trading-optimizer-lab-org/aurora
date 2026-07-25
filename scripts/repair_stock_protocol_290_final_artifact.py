"""Repair a preserved 290-event-study artifact without recomputing statistics."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
from typing import Any

import pyarrow.parquet as pq

from aurora.core.execution_policy import (
    require_github_actions_or_explicit_local_permission,
)
from scripts.merge_stock_protocol_290_event_study import (
    AUDIT_SUMMARY_NAME,
    FINAL_MANIFEST_NAME,
    OPPORTUNITIES_CSV_GZIP,
    OPPORTUNITIES_PARQUET,
    OPPORTUNITIES_PARTS,
    _artifact_manifest,
    _concatenate_parquet_files,
    _parquet_to_gzip_csv,
    _sha256,
)


REPAIR_AUDIT_NAME = "final_artifact_repair_audit.json"
PRE_REPAIR_MANIFEST_NAME = "pre_repair_final_artifact_manifest.json"
VALID_STATUSES = {"completed", "right_censored", "failed_due_to_data"}


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _status_counts(path: Path) -> dict[str, int]:
    counts = {status: 0 for status in sorted(VALID_STATUSES)}
    rows = 0
    for batch in pq.ParquetFile(path).iter_batches(
        columns=["status", "censored"],
        batch_size=100_000,
    ):
        statuses = [
            str(value)
            for value in batch.column(
                batch.schema.get_field_index("status")
            ).to_pylist()
        ]
        censored = batch.column(
            batch.schema.get_field_index("censored")
        ).to_pylist()
        unknown = sorted(set(statuses) - VALID_STATUSES)
        if unknown:
            raise ValueError(f"repaired ledger contains unknown statuses: {unknown[:5]}")
        for status, flag in zip(statuses, censored, strict=True):
            expected = status == "right_censored"
            if flag is None or bool(flag) != expected:
                raise ValueError("repaired censored flag contradicts status")
            counts[status] += 1
            rows += 1
    counts["rows"] = rows
    return counts


def _rewrite_gzip_csv(
    parquet_path: Path,
    output_path: Path,
    *,
    period: str | None = None,
) -> int:
    temporary = output_path.with_name(f".{output_path.name}.repairing")
    if temporary.exists():
        temporary.unlink()
    try:
        rows = _parquet_to_gzip_csv(
            parquet_path,
            temporary,
            period=period,
        )
        os.replace(temporary, output_path)
        return rows
    finally:
        if temporary.exists():
            temporary.unlink()


def repair_final_artifact(root: Path, *, source_run_id: str) -> dict[str, Any]:
    require_github_actions_or_explicit_local_permission(
        "stock protocol 290 preserved final-artifact repair"
    )
    root = root.resolve()
    opportunities = root / OPPORTUNITIES_PARQUET
    opportunities_csv = root / OPPORTUNITIES_CSV_GZIP
    opportunity_parts = root / OPPORTUNITIES_PARTS
    summary_path = root / AUDIT_SUMMARY_NAME
    manifest_path = root / FINAL_MANIFEST_NAME
    for required in (
        opportunities,
        opportunities_csv,
        opportunity_parts,
        summary_path,
        manifest_path,
    ):
        if not required.exists():
            raise FileNotFoundError(f"preserved artifact is missing {required.name}")

    original_manifest_text = manifest_path.read_text(encoding="utf-8")
    original_manifest = json.loads(original_manifest_text)
    original_manifest_sha256 = _sha256(manifest_path)
    original_opportunity_metadata = original_manifest.get("files", {}).get(
        OPPORTUNITIES_PARQUET, {}
    )
    original_opportunity_sha256 = str(
        original_opportunity_metadata.get("sha256", "")
    )
    if len(original_opportunity_sha256) != 64:
        raise ValueError("pre-repair manifest has no opportunity-ledger hash")

    source_bytes = opportunities.stat().st_size
    free_bytes = shutil.disk_usage(root).free
    if free_bytes <= source_bytes + 1_000_000_000:
        raise OSError(
            "insufficient runner disk for atomic opportunity-ledger repair: "
            f"source={source_bytes}, free={free_bytes}"
        )

    temporary = root / f".{OPPORTUNITIES_PARQUET}.repairing"
    if temporary.exists():
        temporary.unlink()
    try:
        rewritten_rows = _concatenate_parquet_files(
            [opportunities],
            temporary,
            derive_censored_from_status=True,
        )
        os.replace(temporary, opportunities)
    finally:
        if temporary.exists():
            temporary.unlink()

    counts = _status_counts(opportunities)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    expected = {
        "rows": int(summary.get("opportunity_count", -1)),
        "completed": int(summary.get("completed", -1)),
        "right_censored": int(summary.get("censored", -1)),
        "failed_due_to_data": int(summary.get("failed_due_to_data", -1)),
    }
    observed = {
        "rows": int(counts["rows"]),
        "completed": int(counts["completed"]),
        "right_censored": int(counts["right_censored"]),
        "failed_due_to_data": int(counts["failed_due_to_data"]),
    }
    if rewritten_rows != expected["rows"] or observed != expected:
        raise ValueError(
            f"repair changed reconciled counts: expected={expected}, observed={observed}"
        )

    full_csv_rows = _rewrite_gzip_csv(opportunities, opportunities_csv)
    if full_csv_rows != rewritten_rows:
        raise ValueError("repaired gzip ledger changed the opportunity count")
    partition_paths = sorted(
        opportunity_parts.glob("period=*/part-*.csv.gz")
    )
    if not partition_paths:
        raise ValueError("preserved artifact has no partitioned opportunity ledgers")
    partition_rows = 0
    partition_periods: list[str] = []
    for partition_path in partition_paths:
        parent = partition_path.parent.name
        if not parent.startswith("period="):
            raise ValueError(f"invalid opportunity partition path: {partition_path}")
        period = parent.split("=", 1)[1]
        if period not in {"A", "B", "C"}:
            raise ValueError(f"invalid opportunity partition period: {period}")
        partition_periods.append(period)
        partition_rows += _rewrite_gzip_csv(
            opportunities,
            partition_path,
            period=period,
        )
    if partition_rows != rewritten_rows or set(partition_periods) != {"A", "B", "C"}:
        raise ValueError(
            "repaired partitioned ledgers do not reconcile to the full ledger"
        )

    pre_repair_manifest_path = root / PRE_REPAIR_MANIFEST_NAME
    pre_repair_manifest_path.write_text(
        original_manifest_text,
        encoding="utf-8",
    )
    repair_audit = {
        "schema_version": 1,
        "repair": "materialize_censored_from_frozen_status",
        "source_run_id": str(source_run_id),
        "source_artifact": "stock-protocol-original-290-unverified-merge-recovery",
        "source_manifest_sha256": original_manifest_sha256,
        "source_opportunity_parquet_sha256": original_opportunity_sha256,
        "repaired_opportunity_parquet_sha256": _sha256(opportunities),
        "rows": int(rewritten_rows),
        "completed": observed["completed"],
        "censored": observed["right_censored"],
        "failed_due_to_data": observed["failed_due_to_data"],
        "mapping": {
            "right_censored": True,
            "completed": False,
            "failed_due_to_data": False,
        },
        "statistics_recomputed": False,
        "gzip_ledger_rows": int(full_csv_rows),
        "partitioned_gzip_ledger_rows": int(partition_rows),
        "partitioned_gzip_ledger_files": len(partition_paths),
        "partition_periods": sorted(set(partition_periods)),
        "opportunities_removed": 0,
        "capital_filter_applied": False,
        "portfolio_simulation_applied": False,
        "sizing_applied": False,
        "overlap_filter_applied": False,
        "new_oos_claimed": False,
        "optimization_performed_on_opened_data": False,
        "implementation_commit": os.environ.get("GITHUB_SHA", "unknown"),
    }
    _write_json(root / REPAIR_AUDIT_NAME, repair_audit)
    _write_json(manifest_path, _artifact_manifest(root))
    return repair_audit


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--source-run-id", required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            repair_final_artifact(
                args.artifact_root,
                source_run_id=str(args.source_run_id),
            ),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
