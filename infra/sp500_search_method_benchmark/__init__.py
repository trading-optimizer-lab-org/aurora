"""Short, train-only benchmark of strategy-search methods for Aurora."""

from .benchmark import (
    METHODS,
    SEEDS,
    audit_candidates,
    aggregate_results,
    build_search_space_manifest,
    prepare_benchmark_data,
    run_smoke,
    run_unit,
    verify_results,
)

__all__ = [
    "METHODS",
    "SEEDS",
    "audit_candidates",
    "aggregate_results",
    "build_search_space_manifest",
    "prepare_benchmark_data",
    "run_smoke",
    "run_unit",
    "verify_results",
]
