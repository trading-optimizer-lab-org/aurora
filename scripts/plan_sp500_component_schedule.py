"""Create a measured, deterministic LPT schedule for catalog components."""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

from aurora.infra.sp500_megarun.catalog_cost_model import CatalogCostModelV1
from aurora.infra.sp500_megarun.catalog_scheduler import (
    schedule_components_by_affinity,
)
from aurora.infra.sp500_megarun.dehb_runtime_inputs import (
    RUNTIME_FRAGMENT_DATASET_IDS,
)
from aurora.infra.sp500_megarun.dehb_lane_registry import (
    runtime_dataset_ids_for_lane,
)
from scripts.build_sp500_component_store import collect_unique_components
from aurora.infra.sp500_megarun.data_contract import load_and_validate_contract


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--selected-config", type=Path, required=True)
    parser.add_argument("--data-contract", type=Path, required=True)
    parser.add_argument("--performance-report", type=Path, required=True)
    parser.add_argument("--workers", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    performance = json.loads(args.performance_report.read_text("utf-8"))
    if (
        performance.get("validation_opened") is not False
        or performance.get("locked_opened") is not False
        or not isinstance(performance.get("component_profiles"), dict)
    ):
        raise SystemExit("COMPONENT_COST_EVIDENCE_INVALID")
    catalog_rows = [
        json.loads(line)
        for line in args.catalog.read_text("utf-8").splitlines()
        if line
    ]
    selected_rows = json.loads(args.selected_config.read_text("utf-8"))
    components = collect_unique_components(catalog_rows, selected_rows)
    data_contract = load_and_validate_contract(args.data_contract)
    lane_datasets = {
        lane.lane_id: tuple(sorted(runtime_dataset_ids_for_lane(lane.lane_id)))
        for lane in data_contract.lanes
    }
    component_ids = {str(item["configuration_sha256"]) for item in components}
    profiles = {
        key: profile
        for key, profile in performance["component_profiles"].items()
        if str(profile.get("configuration_sha256", "")) in component_ids
    }
    measured_ids = {
        str(profile["configuration_sha256"])
        for profile in profiles.values()
    }
    measured_ratio = len(measured_ids) / len(component_ids)
    if measured_ratio < 0.95:
        raise SystemExit(
            f"COMPONENT_COST_EVIDENCE_COVERAGE_LOW:{measured_ratio:.6f}"
        )
    p95_values = [
        float(profile["p95_seconds"])
        for profile in profiles.values()
        if float(profile["p95_seconds"]) > 0.0
    ]
    if not p95_values:
        raise SystemExit("COMPONENT_COST_EVIDENCE_EMPTY")
    model = CatalogCostModelV1.from_performance_profiles(
        profiles,
        fallback_seconds=float(statistics.median(p95_values)),
    )
    affinity_by_component = {
        str(component["configuration_sha256"]): tuple(
            sorted(
                dataset_id
                for dataset_id in lane_datasets[str(component["lane_id"])]
                if dataset_id in RUNTIME_FRAGMENT_DATASET_IDS
            )
        )
        for component in components
    }
    schedule = schedule_components_by_affinity(
        components,
        model=model,
        workers=args.workers,
        affinity_by_component=affinity_by_component,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "component_cost_model.json").write_text(
        model.model_dump_json(indent=2) + "\n",
        "utf-8",
    )
    (args.output_dir / "component_schedule.json").write_text(
        schedule.model_dump_json(indent=2) + "\n",
        "utf-8",
    )
    receipt = {
        "schema_version": 1,
        "component_count": len(components),
        "worker_count": args.workers,
        "cost_sample_count": sum(item.sample_count for item in model.components),
        "measured_component_count": len(model.components),
        "measured_component_ratio": measured_ratio,
        "fallback_seconds": model.fallback_seconds,
        "estimated_tail_ratio": schedule.tail_ratio,
        "affinity_mode": "heavy_runtime_dataset_set",
        "affinity_group_count": len(set(affinity_by_component.values())),
        "cost_model_sha256": model.model_sha256,
        "component_schedule_sha256": schedule.plan_sha256,
        "validation_opened": False,
        "locked_opened": False,
    }
    (args.output_dir / "component_schedule_receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        "utf-8",
    )
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
