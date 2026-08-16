"""Synthetic GitHub benchmark for multi-asset and PIT catalog architecture."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

import numpy as np

from aurora.infra.sp500_megarun.catalog_cross_sectional import (
    build_sparse_point_in_time_portfolio,
)
from aurora.infra.sp500_megarun.catalog_multi_asset import (
    build_asset_panel,
    evaluate_multi_asset_panel,
)
from aurora.infra.sp500_megarun.catalog_vector_engine import (
    evaluate_signal_block,
    scalar_reference,
)


def _multi_asset_case(asset_count: int, session_count: int) -> dict[str, int | float]:
    assets: dict[str, dict[int, float]] = {}
    for asset_index in range(asset_count):
        assets[f"A{asset_index:04d}"] = {
            session: float(100 + asset_index + np.sin(session / 7 + asset_index))
            for session in range(session_count)
            if (session + asset_index) % 19 != 0
        }
    started = time.perf_counter()
    panel = build_asset_panel(assets)
    evaluated = evaluate_multi_asset_panel(panel, lookback=5)
    elapsed = time.perf_counter() - started
    if (
        evaluated.asset_count != asset_count
        or evaluated.shared_calendar_builds != 1
        or evaluated.asset_specific_work_units != asset_count
        or evaluated.validation_opened
        or evaluated.locked_opened
    ):
        raise ValueError("MULTI_ASSET_BENCHMARK_CONTRACT_FAILED")
    return {
        "asset_count": asset_count,
        "session_count": session_count,
        "valid_observation_count": evaluated.valid_observation_count,
        "shared_calendar_builds": evaluated.shared_calendar_builds,
        "asset_specific_work_units": evaluated.asset_specific_work_units,
        "wall_seconds": elapsed,
    }


def _cross_sectional_case(date_count: int, asset_count: int) -> dict[str, int | float]:
    dates = np.arange(date_count, dtype=np.float64)[:, None]
    assets = np.arange(asset_count, dtype=np.float64)[None, :]
    signals = np.sin(dates / 11.0 + assets / 23.0)
    membership = ((dates.astype(np.int64) + assets.astype(np.int64)) % 29) != 0
    signals[~membership] = np.nan
    started = time.perf_counter()
    portfolio = build_sparse_point_in_time_portfolio(
        signals,
        membership,
        top_count=20,
        bottom_count=20,
    )
    elapsed = time.perf_counter() - started
    dense = portfolio.to_dense()
    if (
        portfolio.asset_count != asset_count
        or portfolio.nonzero_weight_count != date_count * 40
        or not np.allclose(dense.sum(axis=1), 0.0)
        or bool(np.any(dense[~membership] != 0.0))
        or portfolio.validation_opened
        or portfolio.locked_opened
    ):
        raise ValueError("CROSS_SECTIONAL_BENCHMARK_CONTRACT_FAILED")
    dense_bytes = int(dense.nbytes)
    ratio = portfolio.storage_bytes / dense_bytes
    if ratio >= 0.10:
        raise ValueError("CROSS_SECTIONAL_STORAGE_REGRESSION")
    return {
        "date_count": date_count,
        "asset_count": asset_count,
        "nonzero_weight_count": portfolio.nonzero_weight_count,
        "sparse_bytes": portfolio.storage_bytes,
        "dense_bytes": dense_bytes,
        "sparse_to_dense_ratio": ratio,
        "wall_seconds": elapsed,
    }


def _vector_case(recipe_count: int, session_count: int) -> dict[str, int | float]:
    row = np.arange(recipe_count, dtype=np.int64)[:, None]
    column = np.arange(session_count, dtype=np.int64)[None, :]
    decisions = np.zeros((recipe_count, session_count), dtype=np.int8)
    decisions[(column + row) % 31 == 0] = 1
    decisions[(column * 3 + row) % 47 == 0] = -1
    spy_returns = np.sin(np.arange(session_count)) * 0.0005
    years = 1998 + np.minimum(
        12,
        np.arange(session_count) * 13 // session_count,
    )

    started = time.perf_counter()
    scalar = scalar_reference(decisions, spy_returns, years)
    scalar_seconds = time.perf_counter() - started
    started = time.perf_counter()
    vector = evaluate_signal_block(decisions, spy_returns, years)
    vector_seconds = time.perf_counter() - started
    if (
        not np.array_equal(vector.annualized_return, scalar.annualized_return)
        or not np.array_equal(vector.annual_returns, scalar.annual_returns)
        or vector.position_hashes != scalar.position_hashes
    ):
        raise ValueError("VECTOR_BENCHMARK_EQUIVALENCE_FAILED")
    speedup = scalar_seconds / vector_seconds
    if speedup < 3.0:
        raise ValueError("VECTOR_BENCHMARK_SPEEDUP_REGRESSION")
    return {
        "recipe_count": recipe_count,
        "session_count": session_count,
        "scalar_seconds": scalar_seconds,
        "vector_seconds": vector_seconds,
        "speedup": speedup,
        "unique_position_count": vector.unique_position_count,
    }


def build_report() -> dict[str, object]:
    return {
        "schema_version": 1,
        "multi_asset": [
            _multi_asset_case(10, 256),
            _multi_asset_case(100, 256),
        ],
        "cross_sectional_point_in_time": _cross_sectional_case(128, 1000),
        "cross_sectional_scale_5000": _cross_sectional_case(128, 5000),
        "vector_engine": _vector_case(512, 4096),
        "validation_opened": False,
        "locked_opened": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", "utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
