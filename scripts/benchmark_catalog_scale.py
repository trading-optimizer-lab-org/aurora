"""GitHub-only scale qualification for one and ten million catalog results."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

import numpy as np
import pyarrow as pa

from aurora.infra.sp500_megarun.catalog_result_store import (
    CatalogResultStore,
    CatalogStreamingResultWriter,
)
from aurora.infra.sp500_megarun.catalog_vector_engine import evaluate_signal_block


def _evaluate_unique_positions(
    *,
    unique_position_count: int,
    session_count: int,
) -> tuple[tuple[str, ...], np.ndarray, float]:
    row = np.arange(unique_position_count, dtype=np.int64)[:, None]
    column = np.arange(session_count, dtype=np.int64)[None, :]
    decisions = np.zeros((unique_position_count, session_count), dtype=np.int8)
    decisions[(column + row) % 31 == 0] = 1
    decisions[(column * 3 + row) % 47 == 0] = -1
    spy_returns = np.sin(np.arange(session_count)) * 0.0005
    years = 1998 + np.minimum(
        12,
        np.arange(session_count) * 13 // session_count,
    )
    started = time.perf_counter()
    evaluation = evaluate_signal_block(decisions, spy_returns, years)
    elapsed = time.perf_counter() - started
    if evaluation.validation_opened or evaluation.locked_opened:
        raise ValueError("CATALOG_SCALE_PROTECTED_PERIOD_OPENED")
    return evaluation.position_hashes, evaluation.annualized_return, elapsed


def _table(
    start: int,
    count: int,
    *,
    position_hashes: tuple[str, ...],
    annualized_returns: np.ndarray,
) -> pa.Table:
    indices = np.arange(start, start + count, dtype=np.int64)
    source = indices % len(position_hashes)
    return pa.table(
        {
            "strategy_id": [f"S{value:010d}" for value in indices],
            "recipe_sha256": [f"{value + 1:064x}" for value in indices],
            "position_sha256": [position_hashes[value] for value in source],
            "annualized_return": annualized_returns[source],
            "weekly_positive_rate": 0.50 + (source % 101) / 1000.0,
        }
    )


def build_scale_report(
    root: Path,
    *,
    total_recipes: int = 10_000_000,
    first_milestone: int = 1_000_000,
    unique_position_count: int = 4096,
    session_count: int = 4516,
    batch_size: int = 50_000,
    partition_size: int = 100_000,
) -> dict[str, object]:
    if not 0 < first_milestone < total_recipes:
        raise ValueError("CATALOG_SCALE_MILESTONE_INVALID")
    if batch_size < 1 or first_milestone % batch_size:
        raise ValueError("CATALOG_SCALE_BATCH_INVALID")
    positions, annualized, physical_seconds = _evaluate_unique_positions(
        unique_position_count=unique_position_count,
        session_count=session_count,
    )
    output = Path(root)
    writer = CatalogStreamingResultWriter(
        output,
        contract_sha256="a" * 64,
        partition_size=partition_size,
    )
    started = time.perf_counter()
    for start in range(0, first_milestone, batch_size):
        writer.append_table(
            _table(
                start,
                min(batch_size, first_milestone - start),
                position_hashes=positions,
                annualized_returns=annualized,
            )
        )
    checkpoint = writer.checkpoint()
    first_seconds = time.perf_counter() - started
    first_bytes = sum(
        (output / item.path).stat().st_size for item in checkpoint.partitions
    )

    resumed = CatalogStreamingResultWriter(
        output,
        contract_sha256="a" * 64,
        partition_size=partition_size,
        resume=True,
    )
    for start in range(first_milestone, total_recipes, batch_size):
        resumed.append_table(
            _table(
                start,
                min(batch_size, total_recipes - start),
                position_hashes=positions,
                annualized_returns=annualized,
            )
        )
    manifest = resumed.commit()
    total_seconds = time.perf_counter() - started
    verified = CatalogResultStore.open(output)
    total_bytes = sum(
        (output / item.path).stat().st_size for item in manifest.partitions
    )
    if (
        verified.manifest.row_count != total_recipes
        or manifest.validation_opened
        or manifest.locked_opened
        or resumed.max_buffered_rows != 0
    ):
        raise ValueError("CATALOG_SCALE_QUALIFICATION_FAILED")
    return {
        "schema_version": 1,
        "one_million": {
            "requested_recipes": first_milestone,
            "physical_backtests": unique_position_count,
            "behavior_equivalence_hits": first_milestone - unique_position_count,
            "wall_seconds": first_seconds,
            "strategies_per_wall_minute": first_milestone * 60.0 / first_seconds,
            "result_bytes": first_bytes,
            "bytes_per_recipe": first_bytes / first_milestone,
        },
        "ten_million": {
            "requested_recipes": total_recipes,
            "physical_backtests": unique_position_count,
            "behavior_equivalence_hits": total_recipes - unique_position_count,
            "wall_seconds": total_seconds,
            "strategies_per_wall_minute": total_recipes * 60.0 / total_seconds,
            "result_bytes": total_bytes,
            "bytes_per_recipe": total_bytes / total_recipes,
            "partition_count": manifest.partition_count,
            "resume_verified": True,
            "maximum_python_row_buffer": resumed.max_buffered_rows,
        },
        "unique_position_evaluation_seconds": physical_seconds,
        "session_count": session_count,
        "validation_opened": False,
        "locked_opened": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_scale_report(args.store_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", "utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
