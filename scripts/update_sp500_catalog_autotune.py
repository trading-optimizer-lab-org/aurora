"""Ingest verified GitHub benchmark evidence into the catalog autotuner."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from aurora.infra.sp500_megarun.catalog_autotune import (
    CatalogBenchmarkObservationV1,
    CatalogPerformanceHistoryV1,
    CatalogTuningDecisionV1,
    ThermalState,
    select_history_configuration,
)


def _object(path: Path) -> dict[str, object]:
    value = json.loads(Path(path).read_text("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("CATALOG_AUTOTUNE_INPUT_INVALID")
    return value


def update_autotune_history(
    *,
    history_path: Path | None,
    runtime_audit_paths: tuple[Path, ...],
    equivalence_paths: tuple[Path, ...],
    science_identity_sha256: str,
    thermal_state: ThermalState,
    minimum_samples: int,
    previous_best_median_seconds: float | None,
    max_regression_ratio: float,
) -> tuple[CatalogPerformanceHistoryV1, CatalogTuningDecisionV1]:
    if not runtime_audit_paths or len(runtime_audit_paths) != len(equivalence_paths):
        raise ValueError("CATALOG_AUTOTUNE_EVIDENCE_COUNT_INVALID")
    history = (
        CatalogPerformanceHistoryV1.load(history_path)
        if history_path is not None
        else CatalogPerformanceHistoryV1.create()
    )
    for audit_path, equivalence_path in zip(
        runtime_audit_paths,
        equivalence_paths,
        strict=True,
    ):
        audit = _object(audit_path)
        equivalence = _object(equivalence_path)
        if (
            audit.get("thermal_state") != thermal_state
            or audit.get("validation_opened") is not False
            or audit.get("locked_opened") is not False
            or equivalence.get("equivalent") is not True
            or int(equivalence.get("difference_count", -1)) != 0
            or equivalence.get("validation_opened") is not False
            or equivalence.get("locked_opened") is not False
        ):
            raise ValueError("CATALOG_AUTOTUNE_EQUIVALENCE_INVALID")
        history = history.append(
            CatalogBenchmarkObservationV1(
                run_id=int(audit["run_id"]),
                head_sha=str(audit["head_sha"]),
                science_identity_sha256=science_identity_sha256,
                thermal_state=thermal_state,
                workers=int(audit["workers"]),
                processes_per_worker=int(audit["processes_per_worker"]),
                block_size=int(audit["block_size"]),
                wall_seconds=float(audit["wall_seconds"]),
                peak_memory_fraction=float(audit["worker_peak_memory_fraction"]),
                equivalent=True,
            )
        )
    decision = select_history_configuration(
        history,
        science_identity_sha256=science_identity_sha256,
        thermal_state=thermal_state,
        minimum_samples=minimum_samples,
        previous_best_median_seconds=previous_best_median_seconds,
        max_regression_ratio=max_regression_ratio,
    )
    return history, decision


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history", type=Path)
    parser.add_argument("--runtime-audit", type=Path, action="append", required=True)
    parser.add_argument("--equivalence", type=Path, action="append", required=True)
    parser.add_argument("--science-identity-sha256", required=True)
    parser.add_argument(
        "--thermal-state",
        choices=("cold", "component_warm", "fully_hot"),
        required=True,
    )
    parser.add_argument("--minimum-samples", type=int, default=3)
    parser.add_argument("--previous-best-median-seconds", type=float)
    parser.add_argument("--max-regression-ratio", type=float, default=0.05)
    parser.add_argument("--output-history", type=Path, required=True)
    parser.add_argument("--output-decision", type=Path, required=True)
    args = parser.parse_args()
    history, decision = update_autotune_history(
        history_path=args.history,
        runtime_audit_paths=tuple(args.runtime_audit),
        equivalence_paths=tuple(args.equivalence),
        science_identity_sha256=args.science_identity_sha256,
        thermal_state=args.thermal_state,
        minimum_samples=args.minimum_samples,
        previous_best_median_seconds=args.previous_best_median_seconds,
        max_regression_ratio=args.max_regression_ratio,
    )
    history.write(args.output_history)
    args.output_decision.parent.mkdir(parents=True, exist_ok=True)
    args.output_decision.write_text(decision.model_dump_json(indent=2) + "\n", "utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
