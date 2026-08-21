"""Stream-verify Atlas shards, preserve every row, and reduce exact cells."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Iterable
import hashlib
from itertools import product
import json
import os
from pathlib import Path
import re
from typing import Any

import pandas as pd

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


_RECOVERY_ROW_FIELDS = frozenset(
    {
        "plan_sha256",
        "shard_index",
        "validation_opened",
        "locked_opened",
        "result_sha256",
        "ordinal",
        "positive_weeks",
        "positive_months",
        "joint_positive_above_spy_years",
        "strategy_id",
        "scientific_recipe_sha256",
        "raw_ordinal",
        "total_weeks",
        "total_months",
        "total_years",
        "positive_week_fraction",
        "positive_month_fraction",
        "joint_positive_above_spy_fraction",
        "annualized_strategy_return",
        "annualized_alpha",
        "weeks_beating_spy",
        "week_count",
        "components",
        "composition",
    }
)

# Worker rows are emitted with ``sort_keys=True``.  Consequently the large
# annual history is the first value in every canonical row.  In recovery the
# whole source file is already protected by the receipt's SHA-256, so we can
# skip that value with the C-backed regular-expression engine and decode only
# the compact reducer fields.  The old structural scanner remains the safe
# fallback for non-canonical input and tests.
_RECOVERY_ANNUAL_ROWS_PREFIX = re.compile(rb'^\{"annual_rows":\[.*?\],')


def _skip_json_string(data: bytes, position: int) -> int:
    if position >= len(data) or data[position] != ord('"'):
        raise ValueError("ATLAS_REDUCER_JSON_STRING_REQUIRED")
    position += 1
    while position < len(data):
        value = data[position]
        if value == ord("\\"):
            position += 2
            continue
        if value == ord('"'):
            return position + 1
        position += 1
    raise ValueError("ATLAS_REDUCER_JSON_STRING_UNTERMINATED")


def _skip_json_value(data: bytes, position: int) -> int:
    while position < len(data) and data[position] in b" \t\r\n":
        position += 1
    if position >= len(data):
        raise ValueError("ATLAS_REDUCER_JSON_VALUE_MISSING")
    value = data[position]
    if value == ord('"'):
        return _skip_json_string(data, position)
    if value in (ord("{"), ord("[")):
        closing = ord("}") if value == ord("{") else ord("]")
        position += 1
        while True:
            while position < len(data) and data[position] in b" \t\r\n":
                position += 1
            if position >= len(data):
                raise ValueError("ATLAS_REDUCER_JSON_CONTAINER_UNTERMINATED")
            if data[position] == closing:
                return position + 1
            if value == ord("{"):
                position = _skip_json_string(data, position)
                while position < len(data) and data[position] in b" \t\r\n":
                    position += 1
                if position >= len(data) or data[position] != ord(":"):
                    raise ValueError("ATLAS_REDUCER_JSON_OBJECT_COLON_REQUIRED")
                position += 1
            position = _skip_json_value(data, position)
            while position < len(data) and data[position] in b" \t\r\n":
                position += 1
            if position >= len(data):
                raise ValueError("ATLAS_REDUCER_JSON_CONTAINER_UNTERMINATED")
            if data[position] == ord(","):
                position += 1
                continue
            if data[position] == closing:
                return position + 1
            raise ValueError("ATLAS_REDUCER_JSON_SEPARATOR_INVALID")
    start = position
    while position < len(data) and data[position] not in b",]} \t\r\n":
        position += 1
    if position == start:
        raise ValueError("ATLAS_REDUCER_JSON_SCALAR_MISSING")
    return position


def _decode_recovery_row(raw_line: bytes, line_number: int) -> dict[str, object]:
    """Decode only the fields needed by recovery, skipping annual_rows bytes.

    Recovery is already bound to each worker file hash.  Parsing the large
    ``annual_rows`` value with a general JSON decoder was the dominant cost on
    the GitHub runner, so this scanner validates the top-level JSON structure
    and decodes only the small scalar/compact fields used by the reducer.
    """

    data = raw_line.strip()
    if not data or data[0] != ord("{"):
        raise ValueError(f"ATLAS_REDUCER_ROW_OBJECT_REQUIRED:{line_number}")

    fast_prefix = _RECOVERY_ANNUAL_ROWS_PREFIX.match(data)
    if fast_prefix is not None:
        # ``annual_rows`` is deliberately not parsed here: the immutable
        # artifact hash has already authenticated the complete source line.
        # Decode the remaining compact object in C instead of walking every
        # byte of the large annual-history array in Python.
        try:
            compact = json.loads(b"{" + data[fast_prefix.end() :])
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"ATLAS_REDUCER_JSON_COMPACT_ROW_INVALID:{line_number}") from exc
        if not isinstance(compact, dict):
            raise ValueError(f"ATLAS_REDUCER_ROW_OBJECT_REQUIRED:{line_number}")
        return {key: value for key, value in compact.items() if key in _RECOVERY_ROW_FIELDS}

    position = 1
    row: dict[str, object] = {}
    keys: set[str] = set()
    while True:
        while position < len(data) and data[position] in b" \t\r\n":
            position += 1
        if position >= len(data):
            raise ValueError(f"ATLAS_REDUCER_JSON_OBJECT_UNTERMINATED:{line_number}")
        if data[position] == ord("}"):
            if position + 1 != len(data):
                raise ValueError(f"ATLAS_REDUCER_JSON_TRAILING_DATA:{line_number}")
            return row
        key_start = position
        position = _skip_json_string(data, position)
        key = json.loads(data[key_start:position])
        if not isinstance(key, str):
            raise ValueError(f"ATLAS_REDUCER_JSON_KEY_INVALID:{line_number}")
        if key in keys:
            raise ValueError(f"ATLAS_REDUCER_JSON_DUPLICATE_KEY:{line_number}:{key}")
        keys.add(key)
        while position < len(data) and data[position] in b" \t\r\n":
            position += 1
        if position >= len(data) or data[position] != ord(":"):
            raise ValueError(f"ATLAS_REDUCER_JSON_OBJECT_COLON_REQUIRED:{line_number}")
        position += 1
        value_start = position
        position = _skip_json_value(data, position)
        if key in _RECOVERY_ROW_FIELDS:
            row[key] = json.loads(data[value_start:position])
        while position < len(data) and data[position] in b" \t\r\n":
            position += 1
        if position >= len(data) or data[position] == ord("}"):
            if position >= len(data) or position + 1 != len(data):
                raise ValueError(f"ATLAS_REDUCER_JSON_TRAILING_DATA:{line_number}")
            return row
        if data[position] != ord(","):
            raise ValueError(f"ATLAS_REDUCER_JSON_SEPARATOR_INVALID:{line_number}")
        position += 1


def _read_rows_with_recovery_raw_lines(
    path: Path,
    *,
    file_digest: Any | None = None,
) -> Iterable[tuple[dict[str, object], bytes]]:
    """Read recovery rows with the native JSON decoder and keep raw bytes.

    Recovery is already bound to the immutable worker-file hash.  The
    previous byte-at-a-time structural scanner tried to avoid decoding
    ``annual_rows``, but its Python loop was dramatically slower on GitHub
    runners than the C-backed JSON decoder.  Decode the complete row here,
    while preserving the exact source line for the output dataset.
    """

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


_RECOVERY_FRONTIER_FIELDS = (
    "ordinal",
    "strategy_id",
    "scientific_recipe_sha256",
    "raw_ordinal",
    "positive_weeks",
    "total_weeks",
    "positive_months",
    "total_months",
    "joint_positive_above_spy_years",
    "total_years",
    "positive_week_fraction",
    "positive_month_fraction",
    "joint_positive_above_spy_fraction",
    "annualized_strategy_return",
    "annualized_alpha",
    "weeks_beating_spy",
    "week_count",
    "components",
    "composition",
)


def _recovery_frontier_row(row: dict[str, object]) -> dict[str, object]:
    """Keep only fields needed by frontier/reserve and later robustness."""

    compact = {key: row[key] for key in _RECOVERY_FRONTIER_FIELDS if key != "raw_ordinal"}
    compact["raw_ordinal"] = row.get("raw_ordinal")
    return compact


def _iter_recovery_projected_rows(path: Path) -> Iterable[dict[str, object]]:
    """Project reducer fields without parsing the large annual history.

    The complete source file is verified and copied separately.  Each row is
    decoded with ``_decode_recovery_row``; canonical rows take the fast
    prefix path above and only the compact fields reach ``json.loads``.  This
    avoids both the old Python byte-at-a-time scan and jq parsing hundreds of
    megabytes of annual history.
    """

    with Path(path).open("rb") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            if not raw_line.strip():
                continue
            yield _decode_recovery_row(raw_line, line_number)


def _read_recovery_shard_payload(
    shard_index: int,
    result_path: Path,
    expected_recipe_count: int,
    *,
    receipt_result_sha256: object,
) -> tuple[int, bytes, list[dict[str, object]]]:
    """Verify and return one recovery shard without decoding its JSON rows.

    The source file is already bound to the immutable worker receipt.  Decode
    only the compact reducer projection while the bytes are already in
    memory; the large annual history is skipped by ``_decode_recovery_row``.
    This avoids reopening the concatenated file for a second full pass.
    """

    raw_bytes = result_path.read_bytes()
    if not raw_bytes.endswith(b"\n") or raw_bytes.count(b"\n") != expected_recipe_count:
        raise ValueError(f"ATLAS_REDUCER_ROW_COUNT_INVALID:{shard_index}")
    if re.search(rb'"validation_opened"\s*:\s*true', raw_bytes):
        raise ValueError(f"ATLAS_REDUCER_ROW_BOUNDARY_OPEN:{shard_index}:validation")
    if re.search(rb'"locked_opened"\s*:\s*true', raw_bytes):
        raise ValueError(f"ATLAS_REDUCER_ROW_BOUNDARY_OPEN:{shard_index}:locked")
    if hashlib.sha256(raw_bytes).hexdigest() != receipt_result_sha256:
        raise ValueError(f"ATLAS_REDUCER_RESULT_FILE_HASH_INVALID:{shard_index}")
    projected_rows = [
        _decode_recovery_row(raw_line, line_number)
        for line_number, raw_line in enumerate(raw_bytes.splitlines(keepends=True), start=1)
        if raw_line.strip()
    ]
    if len(projected_rows) != expected_recipe_count:
        raise ValueError(f"ATLAS_REDUCER_PROJECTED_ROW_COUNT_INVALID:{shard_index}")
    return shard_index, raw_bytes, projected_rows


def _iter_recovery_shard_payloads(
    plan: object,
    by_index: dict[int, Path],
    *,
    workers: int,
) -> Iterable[tuple[int, bytes, list[dict[str, object]]]]:
    """Process recovery shards in bounded parallel batches."""

    shards = list(plan.shards)
    batch_size = max(1, workers)
    for start in range(0, len(shards), batch_size):
        batch = shards[start : start + batch_size]
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = []
            for shard in batch:
                receipt_path = by_index[shard.shard_index]
                receipt = json.loads(receipt_path.read_text("utf-8"))
                futures.append(
                    executor.submit(
                        _read_recovery_shard_payload,
                        shard.shard_index,
                        _find_result_path(receipt_path),
                        shard.expected_recipe_count,
                        receipt_result_sha256=receipt.get("result_sha256"),
                    )
                )
            for future in futures:
                yield future.result()


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
    # receipt.  Recovery workers decode the compact projection while each
    # source shard is already in memory, so the frontier/reserve pass can use
    # it without parsing the concatenated output again.  The normal path
    # deliberately keeps its existing streaming behaviour and row-hash
    # verification.
    cached_rows: list[dict[str, object]] | None = [] if not verify_row_hashes else None
    results_digest = hashlib.sha256() if not verify_row_hashes else None
    if verify_row_hashes:
        result_handle = results_path.open("x", encoding="utf-8", newline="\n")
    else:
        result_handle = results_path.open("xb")
    recovery_payloads = None
    if not verify_row_hashes:
        try:
            recovery_workers = max(1, int(os.environ.get("ATLAS_RECOVERY_WORKERS", "32")))
        except ValueError as exc:
            raise ValueError("ATLAS_REDUCER_RECOVERY_WORKERS_INVALID") from exc
        recovery_payloads = iter(
            _iter_recovery_shard_payloads(
                plan,
                by_index,
                workers=recovery_workers,
            )
        )
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
            if verify_row_hashes:
                if _sha256_file(result_path) != receipt.get("result_sha256"):
                    raise ValueError(f"ATLAS_REDUCER_RESULT_FILE_HASH_INVALID:{shard.shard_index}")
                shard_count = 0
                for row in _read_rows(result_path):
                    ordinal = _verify_row(
                        row,
                        plan_sha256=plan.plan_sha256,
                        shard_index=shard.shard_index,
                        verify_result_hash=True,
                    )
                    if ordinal < shard.start_ordinal or ordinal >= shard.stop_ordinal:
                        raise ValueError(f"ATLAS_REDUCER_ORDINAL_OUT_OF_SHARD:{ordinal}")
                    if ordinal in seen:
                        raise ValueError(f"ATLAS_REDUCER_DUPLICATE_ORDINAL:{ordinal}")
                    seen.add(ordinal)
                    cells.add(_cell(row))
                    result_handle.write(
                        json.dumps(row, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
                    )
                    row_count += 1
                    shard_count += 1
            else:
                # Process independent shards in bounded parallel batches.  A
                # single runner was spending about eleven minutes decoding one
                # shard.  Each worker now verifies/copies bytes and projects
                # compact fields once while that shard is already in memory.
                assert recovery_payloads is not None
                payload_shard_index, raw_bytes, projected_rows = next(recovery_payloads)
                if payload_shard_index != shard.shard_index:
                    raise ValueError(f"ATLAS_REDUCER_RECOVERY_ORDER_INVALID:{shard.shard_index}")
                result_handle.write(raw_bytes)
                assert results_digest is not None
                results_digest.update(raw_bytes)
                shard_count = 0
                for row in projected_rows:
                    verified_ordinal = _verify_row(
                        row,
                        plan_sha256=plan.plan_sha256,
                        shard_index=shard.shard_index,
                        verify_result_hash=False,
                    )
                    if verified_ordinal < shard.start_ordinal or verified_ordinal >= shard.stop_ordinal:
                        raise ValueError(f"ATLAS_REDUCER_ORDINAL_OUT_OF_SHARD:{verified_ordinal}")
                    if verified_ordinal in seen:
                        raise ValueError(f"ATLAS_REDUCER_DUPLICATE_ORDINAL:{verified_ordinal}")
                    seen.add(verified_ordinal)
                    cells.add(_cell(row))
                    cached_rows.append(_recovery_frontier_row(row))
                    row_count += 1
                    shard_count += 1
                if shard_count != shard.expected_recipe_count:
                    raise ValueError(
                        f"ATLAS_REDUCER_PROJECTED_ROW_COUNT_INVALID:{shard.shard_index}:{shard_count}"
                    )
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
