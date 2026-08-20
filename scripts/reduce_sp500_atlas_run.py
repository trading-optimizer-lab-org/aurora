"""Stream-verify Atlas shards, preserve every row, and reduce exact cells."""

from __future__ import annotations

import argparse
from collections.abc import Iterable
import hashlib
from itertools import product
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.json as pajson

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.atlas_execution_contract import load_plan


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _receipt_paths(root: Path) -> list[Path]:
    return sorted(Path(root).rglob("worker_receipt.json"))


def _find_result_path(receipt_path: Path) -> Path:
    path = receipt_path.parent / "results.jsonl"
    if not path.is_file():
        raise ValueError(f"ATLAS_REDUCER_RESULTS_MISSING:{receipt_path.parent.name}")
    return path


def _verify_row(
    row: dict[str, object],
    *,
    plan_sha256: str,
    shard_index: int,
    verify_result_hash: bool = True,
) -> int:
    if row.get("plan_sha256") != plan_sha256:
        raise ValueError("ATLAS_REDUCER_ROW_PLAN_MISMATCH")
    if int(row.get("shard_index", -1)) != shard_index:
        raise ValueError("ATLAS_REDUCER_ROW_SHARD_MISMATCH")
    if row.get("validation_opened") is not False or row.get("locked_opened") is not False:
        raise ValueError("ATLAS_REDUCER_ROW_BOUNDARY_OPEN")
    supplied = row.get("result_sha256")
    if not isinstance(supplied, str) or len(supplied) != 64 or any(
        character not in "0123456789abcdef" for character in supplied
    ):
        raise ValueError("ATLAS_REDUCER_ROW_HASH_INVALID")
    if verify_result_hash:
        identity = {key: value for key, value in row.items() if key != "result_sha256"}
        if supplied != canonical_sha256(identity):
            raise ValueError("ATLAS_REDUCER_ROW_HASH_INVALID")
    return int(row["ordinal"])


def _read_rows(path: Path) -> Iterable[dict[str, object]]:
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"ATLAS_REDUCER_ROW_OBJECT_REQUIRED:{line_number}")
            yield row


def _read_rows_with_raw_lines(
    path: Path,
    *,
    file_digest: Any | None = None,
) -> Iterable[tuple[dict[str, object], bytes]]:
    with Path(path).open("rb") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            if file_digest is not None:
                file_digest.update(raw_line)
            if not raw_line.strip():
                continue
            row = json.loads(raw_line)
            if not isinstance(row, dict):
                raise ValueError(f"ATLAS_REDUCER_ROW_OBJECT_REQUIRED:{line_number}")
            yield row, raw_line


def _read_rows_with_arrow_raw_lines(
    path: Path,
    *,
    file_digest: Any | None = None,
) -> Iterable[tuple[dict[str, object], bytes]]:
    """Decode a recovery shard with Arrow while preserving its raw lines.

    Worker result files are already bound to an immutable artifact hash.  The
    recovery path therefore needs the raw bytes for exact preservation and a
    structural decode for coverage/metric checks, but it does not need Python's
    per-line JSON decoder.  Arrow performs that decode in native code.
    """

    raw_bytes = Path(path).read_bytes()
    if file_digest is not None:
        file_digest.update(raw_bytes)
    raw_lines = [line for line in raw_bytes.splitlines(keepends=True) if line.strip()]
    recovery_schema = pa.schema(
        [
            pa.field("plan_sha256", pa.string()),
            pa.field("shard_index", pa.int64()),
            pa.field("validation_opened", pa.bool_()),
            pa.field("locked_opened", pa.bool_()),
            pa.field("result_sha256", pa.string()),
            pa.field("ordinal", pa.int64()),
            pa.field("positive_weeks", pa.int64()),
            pa.field("positive_months", pa.int64()),
            pa.field("joint_positive_above_spy_years", pa.int64()),
            pa.field("strategy_id", pa.string()),
            pa.field("scientific_recipe_sha256", pa.string()),
            pa.field("raw_ordinal", pa.int64()),
            pa.field("total_weeks", pa.int64()),
            pa.field("total_months", pa.int64()),
            pa.field("total_years", pa.int64()),
            pa.field("positive_week_fraction", pa.float64()),
            pa.field("positive_month_fraction", pa.float64()),
            pa.field("joint_positive_above_spy_fraction", pa.float64()),
            pa.field("annualized_strategy_return", pa.float64()),
            pa.field("annualized_alpha", pa.float64()),
            pa.field("weeks_beating_spy", pa.int64()),
            pa.field("week_count", pa.int64()),
            pa.field("components", pa.list_(pa.string())),
            pa.field(
                "composition",
                pa.struct(
                    [
                        pa.field("direction", pa.int64()),
                        pa.field("kind", pa.string()),
                    ]
                ),
            ),
        ]
    )
    table = pajson.read_json(
        pa.BufferReader(raw_bytes),
        read_options=pajson.ReadOptions(use_threads=True),
        parse_options=pajson.ParseOptions(
            explicit_schema=recovery_schema,
            unexpected_field_behavior="ignore",
        ),
    )
    rows = table.to_pylist()
    if len(rows) != len(raw_lines):
        raise ValueError("ATLAS_REDUCER_ARROW_ROW_COUNT_INVALID")
    for line_number, (row, raw_line) in enumerate(zip(rows, raw_lines), start=1):
        if not isinstance(row, dict):
            raise ValueError(f"ATLAS_REDUCER_ROW_OBJECT_REQUIRED:{line_number}")
        yield row, raw_line


def _cell(row: dict[str, object]) -> tuple[int, int, int]:
    return (
        int(row["positive_weeks"]),
        int(row["positive_months"]),
        int(row["joint_positive_above_spy_years"]),
    )


def _pareto_cells(cells: Iterable[tuple[int, int, int]]) -> set[tuple[int, int, int]]:
    """Find non-dominated integer cells with a Fenwick prefix maximum."""

    unique = sorted(set(cells), key=lambda value: (-value[0], -value[1], -value[2]))
    months = sorted({value[1] for value in unique}, reverse=True)
    month_rank = {value: index + 1 for index, value in enumerate(months)}
    tree: list[int | None] = [None] * (len(months) + 1)

    def query(index: int) -> int | None:
        best: int | None = None
        while index:
            value = tree[index]
            if value is not None and (best is None or value > best):
                best = value
            index -= index & -index
        return best

    def update(index: int, value: int) -> None:
        while index < len(tree):
            if tree[index] is None or value > tree[index]:
                tree[index] = value
            index += index & -index

    frontier: set[tuple[int, int, int]] = set()
    for week, month, year in unique:
        rank = month_rank[month]
        best_year = query(rank)
        if best_year is None or best_year < year:
            frontier.add((week, month, year))
        update(rank, year)
    return frontier


def _is_near_frontier(
    cell: tuple[int, int, int],
    frontier_cells: set[tuple[int, int, int]],
) -> bool:
    """Return whether ``cell`` is within one unit of a frontier cell.

    The previous implementation scanned every frontier cell for every
    non-frontier result.  Because the reserve rule requires each coordinate
    difference to be either 0 or 1, only the eight cells in the 3D unit cube
    above ``cell`` can match.  Checking those exact candidates preserves the
    rule while making the work independent of frontier size.
    """

    return any(
        tuple(cell[index] + delta[index] for index in range(3)) in frontier_cells
        for delta in product((0, 1), repeat=3)
    )


def _compact_row(row: dict[str, object]) -> dict[str, object]:
    raw_ordinal = row.get("raw_ordinal")
    return {
        "ordinal": int(row["ordinal"]),
        "strategy_id": str(row["strategy_id"]),
        "scientific_recipe_sha256": str(row["scientific_recipe_sha256"]),
        "raw_ordinal": int(row["ordinal"] if raw_ordinal is None else raw_ordinal),
        "positive_weeks": int(row["positive_weeks"]),
        "total_weeks": int(row["total_weeks"]),
        "positive_months": int(row["positive_months"]),
        "total_months": int(row["total_months"]),
        "joint_positive_above_spy_years": int(row["joint_positive_above_spy_years"]),
        "total_years": int(row["total_years"]),
        "positive_week_fraction": float(row["positive_week_fraction"]),
        "positive_month_fraction": float(row["positive_month_fraction"]),
        "joint_positive_above_spy_fraction": float(row["joint_positive_above_spy_fraction"]),
        "annualized_strategy_return": float(row["annualized_strategy_return"]),
        "annualized_alpha": float(row["annualized_alpha"]),
        "weeks_beating_spy": int(row["weeks_beating_spy"]),
        "week_count": int(row["week_count"]),
        "components_json": json.dumps(row.get("components", []), sort_keys=True),
        "composition_json": json.dumps(row.get("composition", {}), sort_keys=True),
    }


def _write_parquet(path: Path, rows: list[dict[str, object]]) -> None:
    pd.DataFrame(rows).to_parquet(path, index=False)


def reduce_atlas_run(
    *,
    plan_path: Path,
    partitions_root: Path,
    output_dir: Path,
    verify_row_hashes: bool = True,
) -> dict[str, object]:
    plan = load_plan(Path(plan_path))
    print(
        json.dumps(
            {
                "event": "ATLAS_REDUCER_START",
                "plan_sha256": plan.plan_sha256,
                "expected_recipe_count": plan.requested_recipe_count,
                "expected_shard_count": plan.total_shards,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    receipts = _receipt_paths(Path(partitions_root))
    by_index: dict[int, Path] = {}
    redundant_shard_receipt_count = 0
    for receipt_path in receipts:
        receipt = json.loads(receipt_path.read_text("utf-8"))
        index = int(receipt.get("shard_index", -1))
        if index in by_index:
            prior = json.loads(by_index[index].read_text("utf-8"))
            comparable = (
                prior.get("plan_sha256") == receipt.get("plan_sha256")
                and prior.get("catalog_manifest_sha256") == receipt.get("catalog_manifest_sha256")
                and prior.get("start_ordinal") == receipt.get("start_ordinal")
                and prior.get("stop_ordinal") == receipt.get("stop_ordinal")
                and prior.get("result_sha256") == receipt.get("result_sha256")
            )
            if not comparable:
                raise ValueError("ATLAS_REDUCER_CONFLICTING_DUPLICATE_SHARD_RECEIPT")
            redundant_shard_receipt_count += 1
            continue
        by_index[index] = receipt_path
    if set(by_index) != set(range(plan.total_shards)):
        missing = sorted(set(range(plan.total_shards)) - set(by_index))
        extra = sorted(set(by_index) - set(range(plan.total_shards)))
        raise ValueError(f"ATLAS_REDUCER_SHARD_COVERAGE_INVALID:missing={missing[:5]}:extra={extra[:5]}")

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    results_path = output / "results.jsonl"
    seen: set[int] = set()
    cells: set[tuple[int, int, int]] = set()
    row_count = 0
    # Recovery mode already binds every source file to the immutable worker
    # receipt.  Keep the decoded rows in memory while that single source pass
    # runs so the frontier/reserve pass does not parse the complete dataset a
    # second time.  The normal path deliberately keeps its existing streaming
    # behaviour and row-hash verification.
    cached_rows: list[dict[str, object]] | None = [] if not verify_row_hashes else None
    results_digest = hashlib.sha256() if not verify_row_hashes else None
    if verify_row_hashes:
        result_handle = results_path.open("x", encoding="utf-8", newline="\n")
    else:
        result_handle = results_path.open("xb")
    with result_handle:
        for shard in plan.shards:
            receipt_path = by_index[shard.shard_index]
            receipt = json.loads(receipt_path.read_text("utf-8"))
            expected = {
                "plan_sha256": plan.plan_sha256,
                "catalog_manifest_sha256": plan.catalog_manifest_sha256,
                "shard_index": shard.shard_index,
                "start_ordinal": shard.start_ordinal,
                "stop_ordinal": shard.stop_ordinal,
                "expected_recipe_count": shard.expected_recipe_count,
                "actual_recipe_count": shard.expected_recipe_count,
                "validation_opened": False,
                "locked_opened": False,
            }
            for key, value in expected.items():
                if receipt.get(key) != value:
                    raise ValueError(f"ATLAS_REDUCER_RECEIPT_MISMATCH:{shard.shard_index}:{key}")
            result_path = _find_result_path(receipt_path)
            file_digest = None if verify_row_hashes else hashlib.sha256()
            if verify_row_hashes and _sha256_file(result_path) != receipt.get("result_sha256"):
                raise ValueError(f"ATLAS_REDUCER_RESULT_FILE_HASH_INVALID:{shard.shard_index}")
            shard_count = 0
            raw_rows = (
                _read_rows(result_path)
                if verify_row_hashes
                else _read_rows_with_arrow_raw_lines(result_path, file_digest=file_digest)
            )
            for item in raw_rows:
                if verify_row_hashes:
                    row = item
                    raw_line = None
                else:
                    row, raw_line = item
                ordinal = _verify_row(
                    row,
                    plan_sha256=plan.plan_sha256,
                    shard_index=shard.shard_index,
                    verify_result_hash=verify_row_hashes,
                )
                if ordinal < shard.start_ordinal or ordinal >= shard.stop_ordinal:
                    raise ValueError(f"ATLAS_REDUCER_ORDINAL_OUT_OF_SHARD:{ordinal}")
                if ordinal in seen:
                    raise ValueError(f"ATLAS_REDUCER_DUPLICATE_ORDINAL:{ordinal}")
                seen.add(ordinal)
                cells.add(_cell(row))
                if raw_line is None:
                    result_handle.write(
                        json.dumps(row, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
                    )
                else:
                    result_handle.write(raw_line)
                    if results_digest is not None:
                        results_digest.update(raw_line)
                    if cached_rows is not None:
                        cached_rows.append(row)
                row_count += 1
                shard_count += 1
            if file_digest is not None and file_digest.hexdigest() != receipt.get("result_sha256"):
                raise ValueError(f"ATLAS_REDUCER_RESULT_FILE_HASH_INVALID:{shard.shard_index}")
            if shard_count != shard.expected_recipe_count:
                raise ValueError(f"ATLAS_REDUCER_ROW_COUNT_INVALID:{shard.shard_index}")
            print(
                json.dumps(
                    {
                        "event": "ATLAS_REDUCER_SHARD_VERIFIED",
                        "shard_index": shard.shard_index,
                        "verified_recipe_count": row_count,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )

    if row_count != plan.requested_recipe_count or seen != set(range(plan.ordinal_start, plan.ordinal_stop)):
        raise ValueError("ATLAS_REDUCER_GLOBAL_COVERAGE_INVALID")
    print(
        json.dumps(
            {
                "event": "ATLAS_REDUCER_COVERAGE_VERIFIED",
                "verified_recipe_count": row_count,
                "verified_shard_count": len(by_index),
                "unique_metric_cells": len(cells),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    frontier_cells = _pareto_cells(cells)
    print(
        json.dumps(
            {
                "event": "ATLAS_REDUCER_PARETO_COMPUTED",
                "pareto_cell_count": len(frontier_cells),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    frontier_rows: list[dict[str, object]] = []
    reserve_limit = 50_000
    reserve_rows: list[dict[str, object]] = []
    frontier_path = output / "pareto_frontier.jsonl"
    if verify_row_hashes:
        frontier_handle = frontier_path.open("x", encoding="utf-8", newline="\n")
        frontier_rows_source = ((row, None) for row in _read_rows(results_path))
    else:
        frontier_handle = frontier_path.open("xb")
        assert cached_rows is not None
        frontier_rows_source = ((row, None) for row in cached_rows)
    with frontier_handle:
        for row, raw_line in frontier_rows_source:
            compact = _compact_row(row)
            cell = _cell(row)
            if cell in frontier_cells:
                frontier_rows.append(compact)
                payload = json.dumps(row, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
                if raw_line is None and verify_row_hashes:
                    frontier_handle.write(payload + "\n")
                else:
                    frontier_handle.write(payload.encode("utf-8") + b"\n")
            elif _is_near_frontier(cell, frontier_cells):
                # This pass already has every row decoded after the exact
                # frontier cells are known.  Collect the reserve here so the
                # recovery path does not parse all results a third time.
                reserve_rows.append(compact)
    frontier_rows.sort(key=lambda row: str(row["strategy_id"]))
    _write_parquet(output / "pareto_cells.parquet", [
        {"positive_weeks": w, "positive_months": m, "joint_positive_above_spy_years": y}
        for w, m, y in sorted(frontier_cells, reverse=True)
    ])
    _write_parquet(output / "pareto_strategies.parquet", frontier_rows)

    reserve_rows.sort(key=lambda row: str(row["strategy_id"]))
    reserve_rows = reserve_rows[:reserve_limit]
    print(
        json.dumps(
            {
                "event": "ATLAS_REDUCER_RESERVE_COMPUTED",
                "reserve_recipe_count": len(reserve_rows),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    _write_parquet(output / "reserve_strategies.parquet", reserve_rows)
    # Robustness has not run yet.  Keep the required artifact explicit but
    # empty instead of labelling the reserve as fragile before perturbations.
    _write_parquet(
        output / "fragile_reserve.parquet",
        [],
    )

    metrics = [
        {"positive_weeks": w, "positive_months": m, "joint_positive_above_spy_years": y}
        for w, m, y in sorted(cells, reverse=True)
    ]
    _write_parquet(output / "descriptive_metrics.parquet", metrics)
    dataset = output / "all_results_dataset"
    dataset.mkdir()
    if verify_row_hashes:
        results_sha256 = _sha256_file(results_path)
    else:
        assert results_digest is not None
        results_sha256 = results_digest.hexdigest()
    dataset_manifest = {
        "schema_version": 1,
        "results_path": "../results.jsonl",
        "results_sha256": results_sha256,
        "row_count": row_count,
        "streaming": True,
        "row_hash_verification_mode": (
            "canonical_row_hash" if verify_row_hashes else "artifact_file_hash_bound"
        ),
        "row_hashes_recomputed": verify_row_hashes,
        "result_file_hashes_verified": True,
        "validation_opened": False,
        "locked_opened": False,
    }
    (dataset / "manifest.json").write_text(json.dumps(dataset_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "all_results_manifest.json").write_text(json.dumps(dataset_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "coverage_report.json").write_text(json.dumps({
        "requested_recipe_count": plan.requested_recipe_count,
        "verified_recipe_count": row_count,
        "verified_shard_count": len(by_index),
        "missing_ordinals": 0,
        "duplicate_ordinals": 0,
        "conflicts": 0,
        "redundant_shard_receipt_count": redundant_shard_receipt_count,
        "validation_opened": False,
        "locked_opened": False,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = {
        "schema_version": 1,
        "accepted": True,
        "plan_sha256": plan.plan_sha256,
        "catalog_manifest_sha256": plan.catalog_manifest_sha256,
        "selection_sha256": plan.selection_sha256,
        "requested_recipe_count": plan.requested_recipe_count,
        "verified_recipe_count": row_count,
        "verified_shard_count": len(by_index),
        "pareto_recipe_count": len(frontier_rows),
        "pareto_cell_count": len(frontier_cells),
        "reserve_recipe_count": len(reserve_rows),
        "redundant_shard_receipt_count": redundant_shard_receipt_count,
        "results_sha256": results_sha256,
        "frontier_sha256": _sha256_file(frontier_path),
        "row_hash_verification_mode": (
            "canonical_row_hash" if verify_row_hashes else "artifact_file_hash_bound"
        ),
        "row_hashes_recomputed": verify_row_hashes,
        "result_file_hashes_verified": True,
        "validation_opened": False,
        "locked_opened": False,
    }
    (output / "reduction_receipt.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--partitions-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--artifact-file-hash-only",
        action="store_true",
        help="Recovery-only mode: bind rows to verified result-file hashes.",
    )
    args = parser.parse_args()
    if args.artifact_file_hash_only and os.environ.get("ATLAS_RECOVERY_FAST_PATH") != "1":
        parser.error("--artifact-file-hash-only requires ATLAS_RECOVERY_FAST_PATH=1")
    reducer_kwargs: dict[str, object] = {
        "plan_path": args.plan,
        "partitions_root": args.partitions_root,
        "output_dir": args.output_dir,
    }
    if args.artifact_file_hash_only:
        reducer_kwargs["verify_row_hashes"] = False
    print(json.dumps(reduce_atlas_run(**reducer_kwargs), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
